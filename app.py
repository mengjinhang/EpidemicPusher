import os
import logging

import yaml
from flask import Flask

from epidemic_pusher.database import init_db
from epidemic_pusher.web.routes import bp as main_bp
from epidemic_pusher.web.filters import register_filters
from epidemic_pusher.push.engine import PushEngine
from epidemic_pusher.push.scheduler import PushScheduler
from epidemic_pusher.push.scheduled import ScheduledPushService


def create_app(config_path="config.yaml"):
    app = Flask(__name__)
    app.secret_key = os.urandom(24)

    config = load_config(config_path)
    app.config["APP_CONFIG"] = config
    app.config["REPORT_SCAN_DIR"] = config.get("report", {}).get("scan_dir", "reports")

    setup_logging()

    db_path = config.get("database", {}).get("path", "data/app.db")
    init_db(app, db_path)

    os.makedirs(app.config["REPORT_SCAN_DIR"], exist_ok=True)

    push_config = config.get("push", {})
    push_engine = PushEngine(
        app,
        max_workers=push_config.get("max_workers", 5),
        rate_limit=push_config.get("rate_limit", 30),
        retry_max=push_config.get("retry_max", 3),
        retry_delay=push_config.get("retry_delay", 60),
    )
    app.config["PUSH_ENGINE"] = push_engine

    scheduler_config = config.get("scheduler", {})
    scheduled_push_config = config.get("scheduled_push", {})
    if scheduler_config.get("enabled") or scheduled_push_config.get("enabled"):
        push_scheduler = PushScheduler()
        push_scheduler.init_app(app, push_engine)
        if scheduled_push_config.get("enabled"):
            scheduled_push_service = ScheduledPushService(app, push_engine)
            push_scheduler.add_scheduled_push_job(
                scheduled_push_service, scheduled_push_config
            )
            app.config["SCHEDULED_PUSH_SERVICE"] = scheduled_push_service
        push_scheduler.start()
        app.config["PUSH_SCHEDULER"] = push_scheduler

    register_filters(app)

    app.register_blueprint(main_bp)

    return app


def load_config(config_path):
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def setup_logging():
    os.makedirs("logs", exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/app.log", encoding="utf-8"),
        ],
    )


if __name__ == "__main__":
    config = load_config("config.yaml")
    server = config.get("server", {})

    app = create_app()
    app.run(
        host=server.get("host", "0.0.0.0"),
        port=server.get("port", 5000),
        debug=server.get("debug", True),
    )
