import os
import tempfile

import pytest

from app import create_app
from epidemic_pusher.database import db
from epidemic_pusher.models import Subscriber, Group, Report, SendLog
from epidemic_pusher.subscriber.manager import SubscriberManager, SubscriberError
from epidemic_pusher.subscriber.group import GroupManager, GroupError


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


@pytest.fixture
def client(app):
    return app.test_client()


class TestGroupManager:

    def test_create_group(self, app):
        with app.app_context():
            group = GroupManager.create("教师组", "所有教师")
            assert group.name == "教师组"
            assert group.description == "所有教师"

    def test_create_duplicate(self, app):
        with app.app_context():
            GroupManager.create("教师组")
            with pytest.raises(GroupError):
                GroupManager.create("教师组")

    def test_create_empty_name(self, app):
        with app.app_context():
            with pytest.raises(GroupError):
                GroupManager.create("")

    def test_update_group(self, app):
        with app.app_context():
            group = GroupManager.create("旧名称")
            updated = GroupManager.update(group.id, name="新名称")
            assert updated.name == "新名称"

    def test_delete_group(self, app):
        with app.app_context():
            group = GroupManager.create("待删除")
            assert GroupManager.delete(group.id)
            assert Group.query.get(group.id) is None

    def test_delete_group_with_subscribers(self, app):
        with app.app_context():
            group = GroupManager.create("有成员")
            SubscriberManager.add("张三", "zhang@example.com", group.id)
            GroupManager.delete(group.id)
            sub = Subscriber.query.filter_by(email="zhang@example.com").first()
            assert sub.group_id is None

    def test_list_all(self, app):
        with app.app_context():
            GroupManager.create("组A")
            GroupManager.create("组B")
            groups = GroupManager.list_all()
            assert len(groups) == 2


class TestSubscriberManager:

    def test_add_subscriber(self, app):
        with app.app_context():
            sub = SubscriberManager.add("张三", "zhang@example.com")
            assert sub.name == "张三"
            assert sub.email == "zhang@example.com"
            assert sub.status == "active"

    def test_add_invalid_email(self, app):
        with app.app_context():
            with pytest.raises(SubscriberError):
                SubscriberManager.add("张三", "not-an-email")

    def test_add_duplicate(self, app):
        with app.app_context():
            SubscriberManager.add("张三", "zhang@example.com")
            with pytest.raises(SubscriberError):
                SubscriberManager.add("张三2", "zhang@example.com")

    def test_add_with_group(self, app):
        with app.app_context():
            group = GroupManager.create("教师组")
            sub = SubscriberManager.add("李四", "li@example.com", group.id)
            assert sub.group_id == group.id

    def test_add_with_invalid_group(self, app):
        with app.app_context():
            with pytest.raises(SubscriberError):
                SubscriberManager.add("王五", "wang@example.com", group_id=999)

    def test_update_subscriber(self, app):
        with app.app_context():
            sub = SubscriberManager.add("原名", "orig@example.com")
            updated = SubscriberManager.update(sub.id, name="新名")
            assert updated.name == "新名"

    def test_delete_subscriber(self, app):
        with app.app_context():
            sub = SubscriberManager.add("待删", "del@example.com")
            SubscriberManager.delete(sub.id)
            assert Subscriber.query.get(sub.id) is None

    def test_list_with_pagination(self, app):
        with app.app_context():
            for i in range(25):
                SubscriberManager.add(f"用户{i}", f"user{i}@example.com")

            result = SubscriberManager.list_all(page=1, per_page=10)
            assert len(result["items"]) == 10
            assert result["total"] == 25
            assert result["pages"] == 3

    def test_list_filter_by_group(self, app):
        with app.app_context():
            g1 = GroupManager.create("组A")
            g2 = GroupManager.create("组B")
            SubscriberManager.add("A1", "a1@example.com", g1.id)
            SubscriberManager.add("A2", "a2@example.com", g1.id)
            SubscriberManager.add("B1", "b1@example.com", g2.id)

            result = SubscriberManager.list_all(group_id=g1.id)
            assert result["total"] == 2

    def test_list_filter_by_keyword(self, app):
        with app.app_context():
            SubscriberManager.add("张三", "zhang@example.com")
            SubscriberManager.add("李四", "li@example.com")

            result = SubscriberManager.list_all(keyword="张")
            assert result["total"] == 1

    def test_set_status(self, app):
        with app.app_context():
            sub = SubscriberManager.add("测试", "test@example.com")
            updated = SubscriberManager.set_status(sub.id, "inactive")
            assert updated.status == "inactive"

    def test_set_invalid_status(self, app):
        with app.app_context():
            sub = SubscriberManager.add("测试", "test@example.com")
            with pytest.raises(SubscriberError):
                SubscriberManager.set_status(sub.id, "unknown")

    def test_count(self, app):
        with app.app_context():
            SubscriberManager.add("A", "a@example.com")
            SubscriberManager.add("B", "b@example.com")
            assert SubscriberManager.count() == 2


class TestSubscriberDeleteWithLogs:

    @staticmethod
    def _add_send_log(subscriber, batch_id="batch-1"):
        report = Report(title="测试报告", file_path="/tmp/report.pdf", file_type="pdf")
        db.session.add(report)
        db.session.flush()
        log = SendLog(
            report_id=report.id,
            subscriber_id=subscriber.id,
            subscriber_email=subscriber.email,
            subscriber_name=subscriber.name,
            batch_id=batch_id,
            status="success",
        )
        db.session.add(log)
        db.session.commit()
        return log

    def test_delete_subscriber_keeps_send_logs(self, app):
        with app.app_context():
            sub = SubscriberManager.add("有记录", "haslog@example.com")
            self._add_send_log(sub)

            SubscriberManager.delete(sub.id)

            log = SendLog.query.filter_by(batch_id="batch-1").first()
            assert log is not None
            assert log.subscriber_id is None
            data = log.to_dict()
            assert data["subscriber_email"] == "haslog@example.com"
            assert data["subscriber_name"] == "有记录"

    def test_readd_subscriber_relinks_send_logs(self, app):
        with app.app_context():
            sub = SubscriberManager.add("张三", "relink@example.com")
            self._add_send_log(sub)
            SubscriberManager.delete(sub.id)

            new_sub = SubscriberManager.add("张三回归", "relink@example.com")

            log = SendLog.query.filter_by(batch_id="batch-1").first()
            assert log.subscriber_id == new_sub.id

    def test_delete_batch_keeps_send_logs(self, app):
        with app.app_context():
            sub = SubscriberManager.add("批量删", "batchdel@example.com")
            self._add_send_log(sub)

            SubscriberManager.delete_batch([sub.id])

            log = SendLog.query.filter_by(batch_id="batch-1").first()
            assert log.subscriber_id is None
            assert log.subscriber_email == "batchdel@example.com"
