import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import yaml

from app import create_app
from epidemic_pusher.database import db
from epidemic_pusher.models import Group, Report, Subscriber, SmtpConfig
from epidemic_pusher.push.scheduled import ScheduledPushService


class FakePushEngine:

    def __init__(self):
        self.calls = []

    def push(self, report_id, group_ids=None, subscriber_ids=None, extra_message=""):
        self.calls.append({
            "report_id": report_id,
            "group_ids": group_ids,
            "subscriber_ids": subscriber_ids,
            "extra_message": extra_message,
        })
        return {"batch_id": "batch001", "total": 1}


@pytest.fixture
def app():
    with tempfile.TemporaryDirectory() as tmpdir:
        reports_dir = os.path.join(tmpdir, "reports")
        config_path = os.path.join(tmpdir, "config.yaml")
        db_path = os.path.join(tmpdir, "test.db")
        config = {
            "database": {"path": db_path},
            "report": {"scan_dir": reports_dir},
            "scheduled_push": {
                "enabled": False,
                "timezone": "Asia/Shanghai",
                "report_dir": reports_dir,
                "today_only": True,
                "skip_if_pushed": True,
                "target_groups": ["教师组"],
                "extra_message": "请及时查收",
            },
            "scheduler": {"enabled": False},
        }
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True)


        app = create_app(config_path)
        app.config["TESTING"] = True
        with app.app_context():
            db.create_all()
            yield app
            db.session.remove()
            db.drop_all()


def _write_report(path, mtime):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("fake report")
    ts = mtime.timestamp()
    os.utime(path, (ts, ts))


def _seed_group_and_smtp():
    group = Group(name="教师组")
    db.session.add(group)
    db.session.flush()
    db.session.add(Subscriber(name="张三", email="zhang@example.com", group_id=group.id))
    db.session.add(SmtpConfig(
        host="smtp.test.com",
        port=465,
        username="test@example.com",
        password="secret",
        sender_email="test@example.com",
        is_active=True,
    ))
    db.session.commit()
    return group


class TestScheduledPushService:

    def test_pushes_today_report_once(self, app):
        tz = ZoneInfo("Asia/Shanghai")
        now = datetime(2026, 7, 23, 8, 0, tzinfo=tz)
        reports_dir = app.config["APP_CONFIG"]["scheduled_push"]["report_dir"]
        _write_report(os.path.join(reports_dir, "2026-07-23.pdf"), now)

        with app.app_context():
            group = _seed_group_and_smtp()
            engine = FakePushEngine()
            service = ScheduledPushService(app, engine)

            result = service.run_once(now=now)
            assert result["status"] == "started"
            assert result["batch_id"] == "batch001"
            assert engine.calls == [{
                "report_id": result["report_id"],
                "group_ids": [group.id],
                "subscriber_ids": None,
                "extra_message": "请及时查收",
            }]

            report = db.session.get(Report, result["report_id"])
            assert report.auto_pushed_at is not None
            assert report.auto_push_batch_id == "batch001"

            second = service.run_once(now=now)
            assert second["status"] == "skipped"
            assert len(engine.calls) == 1

    def test_waits_when_today_report_is_missing(self, app):
        tz = ZoneInfo("Asia/Shanghai")
        now = datetime(2026, 7, 23, 8, 0, tzinfo=tz)
        reports_dir = app.config["APP_CONFIG"]["scheduled_push"]["report_dir"]
        _write_report(
            os.path.join(reports_dir, "2026-07-22.pdf"),
            now - timedelta(days=1),
        )

        with app.app_context():
            _seed_group_and_smtp()
            engine = FakePushEngine()
            service = ScheduledPushService(app, engine)

            result = service.run_once(now=now)
            assert result["status"] == "waiting"
            assert result["reason"] == "no_report"
            assert engine.calls == []

    def test_missing_target_group_fails_closed(self, app):
        tz = ZoneInfo("Asia/Shanghai")
        now = datetime(2026, 7, 23, 8, 0, tzinfo=tz)
        reports_dir = app.config["APP_CONFIG"]["scheduled_push"]["report_dir"]
        _write_report(os.path.join(reports_dir, "2026-07-23.pdf"), now)

        with app.app_context():
            db.session.add(SmtpConfig(
                host="smtp.test.com",
                port=465,
                username="test@example.com",
                password="secret",
                sender_email="test@example.com",
                is_active=True,
            ))
            db.session.commit()
            service = ScheduledPushService(app, FakePushEngine())

            with pytest.raises(ValueError, match="目标分组不存在"):
                service.run_once(now=now)
