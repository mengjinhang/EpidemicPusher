import os
import tempfile

import pytest
import yaml

from app import create_app
from epidemic_pusher.database import db


@pytest.fixture
def app():
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, "config.yaml")
        db_path = os.path.join(tmpdir, "test.db")
        reports_dir = os.path.join(tmpdir, "reports")
        os.makedirs(reports_dir)

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
        app.config["_TMPDIR"] = tmpdir

        with app.app_context():
            db.create_all()
            yield app
            db.session.remove()
            db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


class TestFsListDirs:

    def test_list_dirs(self, app, client):
        tmpdir = app.config["_TMPDIR"]
        os.makedirs(os.path.join(tmpdir, "sub_a"))
        os.makedirs(os.path.join(tmpdir, ".hidden"))

        resp = client.get("/api/fs/dirs", query_string={"path": tmpdir})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["path"] == os.path.realpath(tmpdir) or data["path"] == tmpdir
        names = [d["name"] for d in data["dirs"]]
        assert "sub_a" in names
        assert ".hidden" not in names
        assert data["parent"]

    def test_list_missing_dir(self, client):
        resp = client.get("/api/fs/dirs", query_string={"path": "/no/such/dir/xyz"})
        assert resp.status_code == 404
        assert "目录不存在" in resp.get_json()["error"]

    def test_default_to_home(self, client):
        resp = client.get("/api/fs/dirs")
        assert resp.status_code == 200
        assert resp.get_json()["path"] == os.path.expanduser("~")


class TestReportsScanDir:

    def test_update_scan_dir(self, app, client):
        tmpdir = app.config["_TMPDIR"]
        new_dir = os.path.join(tmpdir, "new_reports")
        os.makedirs(new_dir)

        resp = client.post("/reports/scan-dir", data={"scan_dir": new_dir})
        assert resp.status_code == 302
        assert app.config["REPORT_SCAN_DIR"] == new_dir
        assert app.config["APP_CONFIG"]["report"]["scan_dir"] == new_dir

    def test_persists_to_own_config_file(self, app, client):
        """回归: 配置必须写回启动时使用的配置文件, 而不是项目根目录的 config.yaml。"""
        tmpdir = app.config["_TMPDIR"]
        new_dir = os.path.join(tmpdir, "persist_reports")
        os.makedirs(new_dir)

        client.post("/reports/scan-dir", data={"scan_dir": new_dir})

        with open(app.config["CONFIG_PATH"], "r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f)
        assert file_config["report"]["scan_dir"] == new_dir

    def test_reject_missing_dir(self, app, client):
        old = app.config["REPORT_SCAN_DIR"]
        resp = client.post("/reports/scan-dir", data={"scan_dir": "/no/such/dir/xyz"})
        assert resp.status_code == 302
        assert app.config["REPORT_SCAN_DIR"] == old

    def test_reject_empty(self, app, client):
        old = app.config["REPORT_SCAN_DIR"]
        resp = client.post("/reports/scan-dir", data={"scan_dir": "  "})
        assert resp.status_code == 302
        assert app.config["REPORT_SCAN_DIR"] == old
