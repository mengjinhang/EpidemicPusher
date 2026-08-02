import smtplib
import logging
import time
import threading
from contextlib import contextmanager
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders
from email.header import Header
from email.utils import formataddr, formatdate

logger = logging.getLogger(__name__)


class SmtpConnectionError(Exception):
    pass


class SendError(Exception):
    def __init__(self, recipient, reason, retryable=True):
        self.recipient = recipient
        self.reason = reason
        self.retryable = retryable
        super().__init__(f"发送失败 [{recipient}]: {reason}")


class SmtpConnection:

    def __init__(self, host, port, username, password, use_ssl=True, use_tls=False, timeout=30):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.use_tls = use_tls
        self.timeout = timeout
        self._connection = None

    def connect(self):
        try:
            if self.use_ssl:
                self._connection = smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout
                )
            else:
                self._connection = smtplib.SMTP(
                    self.host, self.port, timeout=self.timeout
                )
                if self.use_tls:
                    self._connection.starttls()

            self._connection.login(self.username, self.password)
            logger.info("SMTP 连接成功: %s:%d", self.host, self.port)
            return self._connection

        except smtplib.SMTPAuthenticationError as e:
            raise SmtpConnectionError(f"SMTP 认证失败: {e}")
        except smtplib.SMTPConnectError as e:
            raise SmtpConnectionError(f"SMTP 连接失败: {e}")
        except Exception as e:
            raise SmtpConnectionError(f"SMTP 未知错误: {e}")

    def disconnect(self):
        if self._connection:
            try:
                self._connection.quit()
            except Exception:
                pass
            finally:
                self._connection = None

    def is_alive(self):
        if not self._connection:
            return False
        try:
            status = self._connection.noop()[0]
            return status == 250
        except Exception:
            return False


class RateLimiter:

    def __init__(self, max_per_minute=30):
        self.max_per_minute = max_per_minute
        self._timestamps = []
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.time()
            self._timestamps = [t for t in self._timestamps if now - t < 60]

            if len(self._timestamps) >= self.max_per_minute:
                wait_time = 60 - (now - self._timestamps[0])
                if wait_time > 0:
                    logger.info("触发限流, 等待 %.1f 秒", wait_time)
                    time.sleep(wait_time)

            self._timestamps.append(time.time())


class EmailSender:

    def __init__(self, smtp_config, rate_limit=30):
        self.smtp_config = smtp_config
        self.rate_limiter = RateLimiter(max_per_minute=rate_limit)
        self._connection = None
        self._lock = threading.Lock()

    @contextmanager
    def _get_connection(self):
        # 锁必须覆盖整个发送过程: SMTP 单连接上的事务不能交错,
        # 并发 MAIL FROM 会被服务端以 454 拒绝并断连
        with self._lock:
            if not self._connection or not self._connection.is_alive():
                if self._connection:
                    self._connection.disconnect()
                self._connection = SmtpConnection(
                    host=self.smtp_config["host"],
                    port=self.smtp_config["port"],
                    username=self.smtp_config["username"],
                    password=self.smtp_config["password"],
                    use_ssl=self.smtp_config.get("use_ssl", True),
                    use_tls=self.smtp_config.get("use_tls", False),
                )
                self._connection.connect()
            try:
                yield self._connection._connection
            except smtplib.SMTPServerDisconnected:
                self._connection = None
                raise

    def send(self, message, recipient):
        self.rate_limiter.acquire()

        try:
            with self._get_connection() as conn:
                conn.send_message(message)
                logger.info("邮件发送成功: %s", recipient)
                return True

        except smtplib.SMTPRecipientsRefused as e:
            raise SendError(recipient, f"收件人被拒绝: {e}", retryable=False)
        except smtplib.SMTPDataError as e:
            raise SendError(recipient, f"邮件数据错误: {e}", retryable=False)
        except smtplib.SMTPServerDisconnected:
            raise SendError(recipient, "SMTP 连接断开", retryable=True)
        except smtplib.SMTPException as e:
            raise SendError(recipient, f"SMTP 错误: {e}", retryable=True)
        except Exception as e:
            raise SendError(recipient, f"未知错误: {e}", retryable=True)

    def send_with_retry(self, message, recipient, max_retries=3, base_delay=60):
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                return self.send(message, recipient)
            except SendError as e:
                last_error = e
                if not e.retryable or attempt >= max_retries:
                    raise

                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "发送失败, 第 %d/%d 次重试, %d 秒后重试: %s",
                    attempt + 1,
                    max_retries,
                    delay,
                    e.reason,
                )
                time.sleep(delay)

        raise last_error

    def test_connection(self):
        try:
            conn = SmtpConnection(
                host=self.smtp_config["host"],
                port=self.smtp_config["port"],
                username=self.smtp_config["username"],
                password=self.smtp_config["password"],
                use_ssl=self.smtp_config.get("use_ssl", True),
                use_tls=self.smtp_config.get("use_tls", False),
            )
            conn.connect()
            conn.disconnect()
            return True, "连接测试成功"
        except SmtpConnectionError as e:
            return False, str(e)

    def close(self):
        if self._connection:
            self._connection.disconnect()
            self._connection = None
