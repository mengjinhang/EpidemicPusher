import os
import uuid
import logging
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

from epidemic_pusher.database import db
from epidemic_pusher.models import Subscriber, Report, SendLog, SmtpConfig
from epidemic_pusher.mail.sender import EmailSender, SendError
from epidemic_pusher.mail.builder import EmailBuilder

logger = logging.getLogger(__name__)


class PushError(Exception):
    pass


class PushTask:

    def __init__(self, batch_id, report_title, total):
        self.batch_id = batch_id
        self.report_title = report_title
        self.total = total
        self.success = 0
        self.failed = 0
        self.pending = total
        self.status = "running"  # running, completed, cancelled
        self._lock = threading.Lock()
        self._cancel_event = threading.Event()

    def increment_success(self):
        with self._lock:
            self.success += 1
            self.pending -= 1

    def increment_failed(self):
        with self._lock:
            self.failed += 1
            self.pending -= 1

    def cancel(self):
        self._cancel_event.set()
        self.status = "cancelled"

    @property
    def is_cancelled(self):
        return self._cancel_event.is_set()

    @property
    def progress(self):
        return {
            "batch_id": self.batch_id,
            "report_title": self.report_title,
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "pending": self.pending,
            "status": self.status,
            "progress_pct": round((self.success + self.failed) / max(self.total, 1) * 100, 1),
        }


class PushEngine:

    def __init__(self, app, max_workers=5, rate_limit=30, retry_max=3, retry_delay=60):
        self.app = app
        self.max_workers = max_workers
        self.rate_limit = rate_limit
        self.retry_max = retry_max
        self.retry_delay = retry_delay
        self._active_tasks = {}
        self._lock = threading.Lock()

    def push(self, report_id, group_ids=None, subscriber_ids=None, extra_message=""):
        with self.app.app_context():
            report = Report.query.get(report_id)
            if not report:
                raise PushError(f"报告不存在: ID={report_id}")

            if not os.path.isfile(report.file_path):
                raise PushError(f"报告文件不存在: {report.file_path}")

            if subscriber_ids:
                subscribers = Subscriber.query.filter(
                    Subscriber.id.in_(subscriber_ids),
                    Subscriber.status == "active",
                ).all()
            elif group_ids:
                subscribers = Subscriber.query.filter(
                    Subscriber.group_id.in_(group_ids),
                    Subscriber.status == "active",
                ).all()
            else:
                subscribers = Subscriber.query.filter_by(status="active").all()

            if not subscribers:
                raise PushError("没有符合条件的活跃订阅者")

            smtp_config = SmtpConfig.query.filter_by(is_active=True).first()
            if not smtp_config:
                raise PushError("未配置 SMTP 邮箱，请先在设置中配置")

            batch_id = str(uuid.uuid4())[:8]

            # ORM 对象绑定当前请求的 session, 不能带进后台线程
            # (请求结束 session 销毁后访问属性会抛 DetachedInstanceError),
            # 因此这里先转成纯数据再传递
            report_data = {
                "id": report.id,
                "title": report.title,
                "summary": report.summary,
                "file_path": report.file_path,
            }
            subscribers_data = [
                {"id": s.id, "email": s.email, "name": s.name} for s in subscribers
            ]
            smtp_data = {
                "host": smtp_config.host,
                "port": smtp_config.port,
                "username": smtp_config.username,
                "password": smtp_config.password,
                "use_ssl": smtp_config.use_ssl,
                "use_tls": smtp_config.use_tls,
                "sender_name": smtp_config.sender_name,
                "sender_email": smtp_config.sender_email,
            }

            for sub in subscribers_data:
                log = SendLog(
                    report_id=report_data["id"],
                    subscriber_id=sub["id"],
                    subscriber_email=sub["email"],
                    subscriber_name=sub["name"],
                    batch_id=batch_id,
                    status="pending",
                )
                db.session.add(log)
            db.session.commit()

            task = PushTask(batch_id, report_data["title"], len(subscribers_data))

            with self._lock:
                self._active_tasks[batch_id] = task

            thread = threading.Thread(
                target=self._execute_push,
                args=(batch_id, report_data, subscribers_data, smtp_data, extra_message),
                daemon=True,
            )
            thread.start()

            logger.info(
                "推送任务已创建: batch=%s, report=%s, 收件人=%d",
                batch_id,
                report_data["title"],
                len(subscribers_data),
            )
            return task.progress

    def _execute_push(self, batch_id, report_data, subscribers_data, smtp_data, extra_message):
        with self.app.app_context():
            task = self._active_tasks.get(batch_id)
            if not task:
                return

            email_sender = EmailSender(smtp_data, rate_limit=self.rate_limit)
            email_builder = EmailBuilder(smtp_data["sender_name"], smtp_data["sender_email"])

            try:
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = {}
                    for sub in subscribers_data:
                        if task.is_cancelled:
                            break

                        future = executor.submit(
                            self._send_single,
                            email_sender,
                            email_builder,
                            report_data,
                            sub,
                            batch_id,
                            extra_message,
                        )
                        futures[future] = sub

                    for future in as_completed(futures):
                        if task.is_cancelled:
                            break

                        sub = futures[future]
                        try:
                            success = future.result()
                            if success:
                                task.increment_success()
                            else:
                                task.increment_failed()
                        except Exception:
                            task.increment_failed()

            finally:
                email_sender.close()
                task.status = "completed"

                report = Report.query.get(report_data["id"])
                if report:
                    report.push_count = (report.push_count or 0) + 1
                    db.session.commit()

                with self._lock:
                    self._active_tasks.pop(batch_id, None)

                logger.info(
                    "推送任务完成: batch=%s, 成功=%d, 失败=%d",
                    batch_id,
                    task.success,
                    task.failed,
                )

    def _send_single(self, email_sender, email_builder, report_data, sub_data, batch_id, extra_message):
        with self.app.app_context():
            log = SendLog.query.filter_by(
                batch_id=batch_id,
                subscriber_id=sub_data["id"],
            ).first()

            if not log:
                return False

            try:
                log.status = "sending"
                db.session.commit()

                message = email_builder.build_report_email(
                    to_email=sub_data["email"],
                    to_name=sub_data["name"],
                    report_title=report_data["title"],
                    report_summary=report_data["summary"] or "请查看附件",
                    report_file_path=report_data["file_path"],
                    extra_message=extra_message,
                )

                email_sender.send_with_retry(
                    message=message,
                    recipient=sub_data["email"],
                    max_retries=self.retry_max,
                    base_delay=self.retry_delay,
                )

                log.status = "success"
                log.sent_at = datetime.now(timezone.utc)
                db.session.commit()

                return True

            except SendError as e:
                log.status = "failed"
                log.error_msg = e.reason
                log.retry_count = self.retry_max
                db.session.commit()

                if not e.retryable:
                    subscriber = Subscriber.query.get(sub_data["id"])
                    if subscriber:
                        subscriber.status = "bounced"
                        db.session.commit()

                logger.warning("发送失败 [%s]: %s", sub_data["email"], e.reason)
                return False

            except Exception as e:
                log.status = "failed"
                log.error_msg = str(e)
                db.session.commit()
                logger.error("发送异常 [%s]: %s", sub_data["email"], e)
                return False

    def get_task_progress(self, batch_id):
        task = self._active_tasks.get(batch_id)
        if task:
            return task.progress
        return None

    def cancel_task(self, batch_id):
        task = self._active_tasks.get(batch_id)
        if task:
            task.cancel()
            with self.app.app_context():
                SendLog.query.filter_by(batch_id=batch_id, status="pending").update(
                    {"status": "cancelled"}, synchronize_session="fetch"
                )
                db.session.commit()
            return True
        return False

    def get_active_tasks(self):
        return [t.progress for t in self._active_tasks.values()]
