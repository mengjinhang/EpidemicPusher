import os
import mimetypes
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders
from email.header import Header
from email.utils import formataddr, formatdate

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "templates", "email")


class EmailBuildError(Exception):
    pass


class EmailBuilder:

    def __init__(self, sender_name, sender_email):
        self.sender_name = sender_name
        self.sender_email = sender_email
        self._jinja_env = None

    @property
    def jinja_env(self):
        if self._jinja_env is None:
            self._jinja_env = Environment(
                loader=FileSystemLoader(TEMPLATES_DIR),
                autoescape=select_autoescape(["html"]),
            )
        return self._jinja_env

    def build(self, to_email, to_name, subject, template_name=None,
              template_vars=None, plain_text=None, html_content=None,
              attachments=None, embedded_images=None):

        msg = MIMEMultipart("mixed")

        msg["From"] = formataddr((self.sender_name, self.sender_email))
        msg["To"] = formataddr((to_name, to_email))
        msg["Subject"] = Header(subject, "utf-8")
        msg["Date"] = formatdate(localtime=True)
        msg["X-Mailer"] = "EpidemicReportPusher/1.0"

        body_part = MIMEMultipart("alternative")

        if plain_text:
            body_part.attach(MIMEText(plain_text, "plain", "utf-8"))

        html = self._build_html(template_name, template_vars, html_content)
        if html:
            if embedded_images:
                html_related = MIMEMultipart("related")
                html_related.attach(MIMEText(html, "html", "utf-8"))
                for cid, img_path in embedded_images.items():
                    self._attach_inline_image(html_related, cid, img_path)
                body_part.attach(html_related)
            else:
                body_part.attach(MIMEText(html, "html", "utf-8"))

        msg.attach(body_part)

        if attachments:
            for file_path in attachments:
                self._attach_file(msg, file_path)

        return msg

    def _build_html(self, template_name, template_vars, html_content):
        if html_content:
            return html_content

        if template_name:
            try:
                template = self.jinja_env.get_template(template_name)
                return template.render(**(template_vars or {}))
            except Exception as e:
                logger.error("模板渲染失败 [%s]: %s", template_name, e)
                raise EmailBuildError(f"模板渲染失败: {e}")

        return None

    def _attach_file(self, msg, file_path):
        if not os.path.isfile(file_path):
            raise EmailBuildError(f"附件不存在: {file_path}")

        file_size = os.path.getsize(file_path)
        max_size = 25 * 1024 * 1024  # 25MB
        if file_size > max_size:
            raise EmailBuildError(
                f"附件大小超过限制: {file_path} "
                f"({file_size / 1024 / 1024:.1f}MB > 25MB)"
            )

        filename = os.path.basename(file_path)
        content_type, _ = mimetypes.guess_type(file_path)
        if content_type is None:
            content_type = "application/octet-stream"

        maintype, subtype = content_type.split("/", 1)

        with open(file_path, "rb") as f:
            attachment = MIMEBase(maintype, subtype)
            attachment.set_payload(f.read())

        encoders.encode_base64(attachment)
        attachment.add_header(
            "Content-Disposition",
            "attachment",
            filename=("utf-8", "", filename),
        )

        msg.attach(attachment)
        logger.debug("附件已添加: %s (%.1f KB)", filename, file_size / 1024)

    def _attach_inline_image(self, msg, cid, img_path):
        if not os.path.isfile(img_path):
            logger.warning("内嵌图片不存在: %s", img_path)
            return

        content_type, _ = mimetypes.guess_type(img_path)
        if not content_type or not content_type.startswith("image/"):
            logger.warning("文件不是图片类型: %s", img_path)
            return

        subtype = content_type.split("/", 1)[1]

        with open(img_path, "rb") as f:
            img = MIMEImage(f.read(), _subtype=subtype)

        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=os.path.basename(img_path))

        msg.attach(img)

    def build_report_email(self, to_email, to_name, report_title, report_summary,
                           report_file_path, extra_message=""):
        template_vars = {
            "recipient_name": to_name,
            "report_title": report_title,
            "report_summary": report_summary,
            "extra_message": extra_message,
        }

        plain_text = (
            f"尊敬的{to_name}:\n\n"
            f"您好！请查收最新的疫情报告: {report_title}\n\n"
            f"报告摘要:\n{report_summary}\n\n"
            f"{extra_message}\n"
            f"详细内容请查看附件。\n\n"
            f"此邮件由疫情报告推送系统自动发送，请勿直接回复。"
        )

        return self.build(
            to_email=to_email,
            to_name=to_name,
            subject=f"【疫情报告】{report_title}",
            template_name="epidemic.html",
            template_vars=template_vars,
            plain_text=plain_text,
            attachments=[report_file_path],
        )
