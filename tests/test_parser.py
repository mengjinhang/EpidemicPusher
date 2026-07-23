import os
import pytest
import tempfile

from app import create_app
from epidemic_pusher.database import db
from epidemic_pusher.models import Report
from epidemic_pusher.report.parser import ReportParser
from epidemic_pusher.report.converter import ReportConverter, ConvertError


@pytest.fixture
def app():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "config.yaml")
        db_path = os.path.join(tmpdir, "test.db")
        reports_dir = os.path.join(tmpdir, "reports")

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(
                "database:\n"
                f"  path: '{db_path}'\n"
                "report:\n"
                f"  scan_dir: '{reports_dir}'\n"
                "scheduler:\n"
                "  enabled: false\n"
            )

        app = create_app(config_path)
        app.config["TESTING"] = True

        with app.app_context():
            db.create_all()
            yield app
            db.session.remove()
            db.drop_all()


class TestReportParser:

    def test_scan_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports = ReportParser.scan_directory(tmpdir)
            assert reports == []

    def test_scan_creates_directory(self):
        path = os.path.join(tempfile.gettempdir(), "test_scan_nonexist")
        if os.path.exists(path):
            os.rmdir(path)
        reports = ReportParser.scan_directory(path)
        assert reports == []
        assert os.path.isdir(path)
        os.rmdir(path)

    def test_scan_with_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["report1.pdf", "report2.docx", "readme.txt", "data.xlsx"]:
                open(os.path.join(tmpdir, name), "w").close()

            reports = ReportParser.scan_directory(tmpdir)
            assert len(reports) == 2
            types = {r["file_type"] for r in reports}
            assert types == {"pdf", "docx"}

    def test_sync_reports(self, app):
        with app.app_context():
            with tempfile.TemporaryDirectory() as tmpdir:
                pdf_path = os.path.join(tmpdir, "test_report.pdf")
                with open(pdf_path, "w") as f:
                    f.write("fake pdf content")

                result = ReportParser.sync_reports(tmpdir)
                assert result["new"] == 1

                result2 = ReportParser.sync_reports(tmpdir)
                assert result2["new"] == 0

    def test_list_reports(self, app):
        with app.app_context():
            for i in range(5):
                report = Report(
                    title=f"报告{i}",
                    file_path=f"/tmp/report{i}.pdf",
                    file_type="pdf",
                    file_size=1024,
                )
                db.session.add(report)
            db.session.commit()

            result = ReportParser.list_reports(page=1, per_page=3)
            assert len(result["items"]) == 3
            assert result["total"] == 5

    def test_delete_report(self, app):
        with app.app_context():
            report = Report(
                title="待删除",
                file_path="/tmp/del.pdf",
                file_type="pdf",
            )
            db.session.add(report)
            db.session.commit()

            ReportParser.delete_report(report.id)
            assert Report.query.get(report.id) is None


class TestReportConverter:

    def test_get_file_info(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"x" * 2048)
            path = f.name

        try:
            info = ReportConverter.get_file_info(path)
            assert info["file_type"] == "pdf"
            assert info["file_size"] == 2048
            assert "KB" in info["file_size_display"]
        finally:
            os.unlink(path)

    def test_get_file_info_not_exists(self):
        with pytest.raises(ConvertError):
            ReportConverter.get_file_info("/tmp/nonexist_12345.pdf")

    def test_format_size_bytes(self):
        assert ReportConverter._format_size(500) == "500 B"

    def test_format_size_kb(self):
        assert "KB" in ReportConverter._format_size(2048)

    def test_format_size_mb(self):
        assert "MB" in ReportConverter._format_size(2 * 1024 * 1024)

    def test_unsupported_format(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"text content")
            path = f.name
        try:
            with pytest.raises(ConvertError):
                ReportConverter.to_plain_text(path)
        finally:
            os.unlink(path)
