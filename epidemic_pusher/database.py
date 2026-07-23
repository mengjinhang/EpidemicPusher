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
    if "reports" not in inspector.get_table_names():
        return

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
