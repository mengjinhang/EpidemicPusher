from datetime import datetime, timezone

from epidemic_pusher.database import db


class Group(db.Model):
    __tablename__ = "groups"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    subscribers = db.relationship("Subscriber", backref="group", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "subscriber_count": self.subscribers.count(),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


class Subscriber(db.Model):
    __tablename__ = "subscribers"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("groups.id"), nullable=True)
    status = db.Column(db.String(20), default="active")  # active, inactive, bounced
    remark = db.Column(db.String(500), default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (db.UniqueConstraint("email", "group_id", name="uq_email_group"),)

    send_logs = db.relationship("SendLog", backref="subscriber", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "group_id": self.group_id,
            "group_name": self.group.name if self.group else None,
            "status": self.status,
            "remark": self.remark,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)  # pdf, docx
    file_size = db.Column(db.Integer, default=0)
    summary = db.Column(db.Text, default="")
    push_count = db.Column(db.Integer, default=0)
    auto_pushed_at = db.Column(db.DateTime, nullable=True)
    auto_push_batch_id = db.Column(db.String(36), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    send_logs = db.relationship("SendLog", backref="report", lazy="dynamic")

    def to_dict(self):
        size_mb = round(self.file_size / 1024 / 1024, 2) if self.file_size else 0
        return {
            "id": self.id,
            "title": self.title,
            "file_path": self.file_path,
            "file_type": self.file_type,
            "file_size": self.file_size,
            "file_size_display": f"{size_mb} MB",
            "summary": self.summary,
            "push_count": self.push_count,
            "auto_pushed_at": (
                self.auto_pushed_at.strftime("%Y-%m-%d %H:%M:%S")
                if self.auto_pushed_at else None
            ),
            "auto_push_batch_id": self.auto_push_batch_id,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


class SendLog(db.Model):
    __tablename__ = "send_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id"), nullable=True)
    subscriber_id = db.Column(
        db.Integer, db.ForeignKey("subscribers.id"), nullable=True
    )
    # 发送时的收件人快照: 订阅者被删除后日志仍可读, 且重新添加同邮箱时可按此重新关联
    subscriber_email = db.Column(db.String(200), default="")
    subscriber_name = db.Column(db.String(100), default="")
    batch_id = db.Column(db.String(36), nullable=False)
    status = db.Column(db.String(20), default="pending")  # pending, sending, success, failed, retry
    error_msg = db.Column(db.Text, default="")
    retry_count = db.Column(db.Integer, default=0)
    sent_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "report_title": self.report.title if self.report else None,
            "subscriber_name": (
                self.subscriber.name if self.subscriber else (self.subscriber_name or None)
            ),
            "subscriber_email": (
                self.subscriber.email if self.subscriber else (self.subscriber_email or None)
            ),
            "batch_id": self.batch_id,
            "status": self.status,
            "error_msg": self.error_msg,
            "retry_count": self.retry_count,
            "sent_at": self.sent_at.strftime("%Y-%m-%d %H:%M:%S") if self.sent_at else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        }


class SmtpConfig(db.Model):
    __tablename__ = "smtp_config"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    host = db.Column(db.String(200), nullable=False)
    port = db.Column(db.Integer, nullable=False, default=465)
    username = db.Column(db.String(200), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    use_ssl = db.Column(db.Boolean, default=True)
    use_tls = db.Column(db.Boolean, default=False)
    sender_name = db.Column(db.String(100), default="疫情报告推送系统")
    sender_email = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": "******",
            "use_ssl": self.use_ssl,
            "use_tls": self.use_tls,
            "sender_name": self.sender_name,
            "sender_email": self.sender_email,
            "is_active": self.is_active,
        }
