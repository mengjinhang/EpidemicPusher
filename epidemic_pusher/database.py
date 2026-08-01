import os

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text

db = SQLAlchemy()


def init_db(app, db_path="data/app.db"):
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.abspath(db_path)}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "connect_args": {"check_same_thread": False},
    }

    db.init_app(app)

    with app.app_context():
        from epidemic_pusher.models import Subscriber, Group, Report, SendLog, SmtpConfig  # noqa: F401

        db.create_all()
        ensure_schema_compatibility()

    return db


def ensure_schema_compatibility():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    if "reports" in tables:
        _ensure_report_columns(inspector)
    if "send_logs" in tables:
        _ensure_send_log_schema(inspector)


def _ensure_report_columns(inspector):
    columns = {column["name"] for column in inspector.get_columns("reports")}
    statements = []
    if "auto_pushed_at" not in columns:
        statements.append("ALTER TABLE reports ADD COLUMN auto_pushed_at DATETIME")
    if "auto_push_batch_id" not in columns:
        statements.append("ALTER TABLE reports ADD COLUMN auto_push_batch_id VARCHAR(36)")

    if not statements:
        return

    with db.engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def _ensure_send_log_schema(inspector):
    """旧库中 send_logs 的外键为 NOT NULL 且无收件人快照列。

    SQLite 无法用 ALTER TABLE 放宽 NOT NULL, 只能重建表:
    外键改为可空(删除订阅者/报告时日志保留), 并补充 subscriber_email/name
    快照列(从 subscribers 表回填), 供删除后展示与重新添加时重新关联。
    """
    columns = {c["name"]: c for c in inspector.get_columns("send_logs")}

    has_snapshot = "subscriber_email" in columns and "subscriber_name" in columns
    fks_nullable = (
        columns["subscriber_id"]["nullable"] and columns["report_id"]["nullable"]
    )
    if has_snapshot and fks_nullable:
        return

    if "subscriber_email" in columns:
        email_expr = "COALESCE(sl.subscriber_email, '')"
        name_expr = "COALESCE(sl.subscriber_name, '')"
    else:
        email_expr = (
            "COALESCE((SELECT s.email FROM subscribers s WHERE s.id = sl.subscriber_id), '')"
        )
        name_expr = (
            "COALESCE((SELECT s.name FROM subscribers s WHERE s.id = sl.subscriber_id), '')"
        )

    with db.engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE send_logs_migrated (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER REFERENCES reports (id),
                subscriber_id INTEGER REFERENCES subscribers (id),
                subscriber_email VARCHAR(200),
                subscriber_name VARCHAR(100),
                batch_id VARCHAR(36) NOT NULL,
                status VARCHAR(20),
                error_msg TEXT,
                retry_count INTEGER,
                sent_at DATETIME,
                created_at DATETIME
            )
            """
        ))
        conn.execute(text(
            f"""
            INSERT INTO send_logs_migrated (
                id, report_id, subscriber_id, subscriber_email, subscriber_name,
                batch_id, status, error_msg, retry_count, sent_at, created_at
            )
            SELECT
                sl.id, sl.report_id, sl.subscriber_id, {email_expr}, {name_expr},
                sl.batch_id, sl.status, sl.error_msg, sl.retry_count,
                sl.sent_at, sl.created_at
            FROM send_logs sl
            """
        ))
        conn.execute(text("DROP TABLE send_logs"))
        conn.execute(text("ALTER TABLE send_logs_migrated RENAME TO send_logs"))
