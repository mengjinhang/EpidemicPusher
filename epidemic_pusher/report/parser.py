import os
import logging
from datetime import datetime, timezone

from epidemic_pusher.database import db
from epidemic_pusher.models import Report

logger = logging.getLogger(__name__)


class ReportParseError(Exception):
    pass


class ReportParser:

    SUPPORTED_TYPES = {".pdf", ".docx", ".doc"}

    @classmethod
    def scan_directory(cls, scan_dir):
        if not os.path.isdir(scan_dir):
            os.makedirs(scan_dir, exist_ok=True)
            logger.info("报告目录不存在, 已创建: %s", scan_dir)
            return []

        reports = []
        for filename in sorted(os.listdir(scan_dir)):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in cls.SUPPORTED_TYPES:
                continue

            file_path = os.path.join(scan_dir, filename)
            if not os.path.isfile(file_path):
                continue

            reports.append({
                "filename": filename,
                "file_path": os.path.abspath(file_path),
                "file_type": ext.lstrip("."),
                "file_size": os.path.getsize(file_path),
                "modified_at": datetime.fromtimestamp(
                    os.path.getmtime(file_path), tz=timezone.utc
                ),
            })

        return reports

    @classmethod
    def sync_reports(cls, scan_dir):
        files = cls.scan_directory(scan_dir)
        new_count = 0
        updated_count = 0

        for file_info in files:
            existing = Report.query.filter_by(file_path=file_info["file_path"]).first()

            if existing:
                if existing.file_size != file_info["file_size"]:
                    existing.file_size = file_info["file_size"]
                    summary = cls.extract_summary(file_info["file_path"])
                    if summary:
                        existing.summary = summary
                    updated_count += 1
            else:
                summary = cls.extract_summary(file_info["file_path"])
                report = Report(
                    title=os.path.splitext(file_info["filename"])[0],
                    file_path=file_info["file_path"],
                    file_type=file_info["file_type"],
                    file_size=file_info["file_size"],
                    summary=summary or "",
                )
                db.session.add(report)
                new_count += 1

        db.session.commit()
        logger.info("报告同步完成: 新增 %d, 更新 %d", new_count, updated_count)
        return {"new": new_count, "updated": updated_count}

    @classmethod
    def extract_summary(cls, file_path, max_length=500):
        ext = os.path.splitext(file_path)[1].lower()

        try:
            if ext == ".docx":
                return cls._extract_docx_summary(file_path, max_length)
            elif ext == ".pdf":
                return cls._extract_pdf_summary(file_path, max_length)
            elif ext == ".doc":
                return "(旧版 .doc 格式, 暂不支持摘要提取)"
        except Exception as e:
            logger.warning("提取摘要失败 [%s]: %s", file_path, e)

        return ""

    @classmethod
    def _extract_docx_summary(cls, file_path, max_length):
        try:
            from docx import Document
        except ImportError:
            return "(需安装 python-docx 以提取 Word 摘要)"

        doc = Document(file_path)
        paragraphs = []
        total_len = 0

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            paragraphs.append(text)
            total_len += len(text)
            if total_len >= max_length:
                break

        summary = "\n".join(paragraphs)
        if len(summary) > max_length:
            summary = summary[:max_length] + "..."

        return summary

    @classmethod
    def _extract_pdf_summary(cls, file_path, max_length):
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                return "(需安装 pypdf 以提取 PDF 摘要)"

        reader = PdfReader(file_path)
        text_parts = []
        total_len = 0

        for page in reader.pages[:3]:
            text = page.extract_text()
            if text:
                text = text.strip()
                text_parts.append(text)
                total_len += len(text)
                if total_len >= max_length:
                    break

        summary = "\n".join(text_parts)
        if len(summary) > max_length:
            summary = summary[:max_length] + "..."

        return summary

    @staticmethod
    def get_report(report_id):
        report = Report.query.get(report_id)
        if not report:
            raise ReportParseError(f"报告不存在: ID={report_id}")
        return report

    @staticmethod
    def list_reports(page=1, per_page=20):
        pagination = Report.query.order_by(Report.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        return {
            "items": [r.to_dict() for r in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
        }

    @staticmethod
    def delete_report(report_id):
        report = Report.query.get(report_id)
        if not report:
            raise ReportParseError(f"报告不存在: ID={report_id}")

        db.session.delete(report)
        db.session.commit()
        logger.info("删除报告记录: %s", report.title)
        return True
