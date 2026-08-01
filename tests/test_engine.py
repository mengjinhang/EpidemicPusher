import os
import tempfile

import pytest
from unittest.mock import patch, MagicMock

from app import create_app
from epidemic_pusher.database import db
from epidemic_pusher.models import Subscriber, Group, Report, SendLog, SmtpConfig
from epidemic_pusher.push.engine import PushEngine, PushError
from epidemic_pusher.push.tracker import PushTracker


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


def setup_test_data(app):
    with app.app_context():
        group = Group(name="教师组")
        db.session.add(group)
        db.session.flush()

        sub1 = Subscriber(name="张三", email="zhang@example.com", group_id=group.id)
        sub2 = Subscriber(name="李四", email="li@example.com", group_id=group.id)
        db.session.add_all([sub1, sub2])

        report = Report(
            title="测试报告",
            file_path="/tmp/test_report.pdf",
            file_type="pdf",
            file_size=1024,
        )
        db.session.add(report)

        smtp = SmtpConfig(
            host="smtp.test.com",
            port=465,
            username="test@test.com",
            password="test123",
            sender_name="测试系统",
            sender_email="test@test.com",
            is_active=True,
        )
        db.session.add(smtp)
        db.session.commit()

        return group, [sub1, sub2], report, smtp


class TestPushEngine:

    def test_push_no_report(self, app):
        with app.app_context():
            engine = PushEngine(app)
            with pytest.raises(PushError, match="报告不存在"):
                engine.push(report_id=999)

    def test_push_no_smtp(self, app):
        with app.app_context():
            report = Report(
                title="报告",
                file_path=__file__,
                file_type="pdf",
                file_size=100,
            )
            sub = Subscriber(name="A", email="a@example.com")
            db.session.add_all([report, sub])
            db.session.commit()

            engine = PushEngine(app)
            with pytest.raises(PushError, match="未配置 SMTP"):
                engine.push(report_id=report.id)

    def test_push_no_subscribers(self, app):
        with app.app_context():
            report = Report(
                title="报告",
                file_path=__file__,
                file_type="pdf",
                file_size=100,
            )
            smtp = SmtpConfig(
                host="smtp.test.com",
                port=465,
                username="test@test.com",
                password="test123",
                sender_name="测试",
                sender_email="test@test.com",
                is_active=True,
            )
            db.session.add_all([report, smtp])
            db.session.commit()

            engine = PushEngine(app)
            with pytest.raises(PushError, match="没有符合条件"):
                engine.push(report_id=report.id, group_ids=[999])


class TestPushExecution:

    def test_push_completes_after_request_context_gone(self, app, tmp_path):
        """回归: 推送线程不得依赖发起请求时的 ORM 对象/session (DetachedInstanceError)。"""
        report_file = tmp_path / "report.pdf"
        report_file.write_bytes(b"%PDF-1.4 test")

        with app.app_context():
            setup_test_data(app)
            report = Report.query.first()
            report.file_path = str(report_file)
            db.session.commit()
            report_id = report.id

        with patch("epidemic_pusher.push.engine.EmailSender") as mock_sender, \
                patch("epidemic_pusher.push.engine.EmailBuilder") as mock_builder:
            mock_sender.return_value.send_with_retry.return_value = True
            mock_builder.return_value.build_report_email.return_value = MagicMock()

            engine = PushEngine(app, max_workers=2)

            # 模拟 Web 请求: 独立的 app context 发起推送, 随后立即销毁 session
            with app.app_context():
                result = engine.push(report_id=report_id)
                db.session.remove()

            assert result["total"] == 2
            batch_id = result["batch_id"]

            import time
            for _ in range(100):
                if batch_id not in engine._active_tasks:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("推送任务未在预期时间内完成")

        with app.app_context():
            logs = SendLog.query.filter_by(batch_id=batch_id).all()
            assert len(logs) == 2
            assert all(log.status == "success" for log in logs)
            assert {log.subscriber_email for log in logs} == {
                "zhang@example.com", "li@example.com",
            }


class TestPushTracker:

    def test_dashboard_stats_empty(self, app):
        with app.app_context():
            stats = PushTracker.get_dashboard_stats()
            assert stats["total_subscribers"] == 0
            assert stats["total_sent"] == 0
            assert stats["success_rate"] == 0

    def test_dashboard_stats_with_data(self, app):
        with app.app_context():
            setup_test_data(app)
            report = Report.query.first()
            subs = Subscriber.query.all()

            from datetime import datetime, timezone
            log1 = SendLog(
                report_id=report.id,
                subscriber_id=subs[0].id,
                batch_id="test001",
                status="success",
                sent_at=datetime.now(timezone.utc),
            )
            log2 = SendLog(
                report_id=report.id,
                subscriber_id=subs[1].id,
                batch_id="test001",
                status="failed",
                error_msg="连接超时",
            )
            db.session.add_all([log1, log2])
            db.session.commit()

            stats = PushTracker.get_dashboard_stats()
            assert stats["total_subscribers"] == 2
            assert stats["total_sent"] == 1
            assert stats["total_failed"] == 1
            assert stats["success_rate"] == 50.0

    def test_batch_summary(self, app):
        with app.app_context():
            setup_test_data(app)
            report = Report.query.first()
            subs = Subscriber.query.all()

            for sub in subs:
                log = SendLog(
                    report_id=report.id,
                    subscriber_id=sub.id,
                    batch_id="batch123",
                    status="success",
                )
                db.session.add(log)
            db.session.commit()

            summary = PushTracker.get_batch_summary("batch123")
            assert summary["total"] == 2
            assert summary["success"] == 2
            assert summary["success_rate"] == 100.0

    def test_daily_stats(self, app):
        with app.app_context():
            stats = PushTracker.get_daily_stats(days=7)
            assert len(stats) == 7
            for day in stats:
                assert "date" in day
                assert "success" in day
                assert "failed" in day

    def test_recent_batches_empty(self, app):
        with app.app_context():
            batches = PushTracker.get_recent_batches()
            assert batches == []
