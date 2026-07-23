import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from epidemic_pusher.database import db
from epidemic_pusher.models import Group, Report
from epidemic_pusher.report.parser import ReportParser

logger = logging.getLogger(__name__)


class ScheduledPushService:

    def __init__(self, app, push_engine):
        self.app = app
        self.push_engine = push_engine

    def run_once(self, now=None):
        with self.app.app_context():
            config = self._config()
            now_local = self._local_now(now, config)
            scan_dir = config.get("report_dir") or self.app.config.get(
                "REPORT_SCAN_DIR", "reports"
            )

            ReportParser.sync_reports(scan_dir)
            report = self._find_report(scan_dir, now_local, config)
            if not report:
                logger.info("定时推送等待报告: date=%s, dir=%s", now_local.date(), scan_dir)
                return {
                    "status": "waiting",
                    "reason": "no_report",
                    "date": now_local.date().isoformat(),
                }

            if config.get("skip_if_pushed", True) and report.auto_pushed_at:
                logger.info("定时推送跳过已推送报告: report_id=%s", report.id)
                return {
                    "status": "skipped",
                    "reason": "already_pushed",
                    "report_id": report.id,
                    "batch_id": report.auto_push_batch_id,
                }

            group_ids = self._resolve_group_ids(config)
            extra_message = config.get("extra_message", "")

            result = self.push_engine.push(
                report_id=report.id,
                group_ids=group_ids,
                extra_message=extra_message,
            )

            report.auto_pushed_at = datetime.now(timezone.utc)
            report.auto_push_batch_id = result.get("batch_id")
            db.session.commit()

            logger.info(
                "定时推送已创建: report_id=%s, batch=%s",
                report.id,
                report.auto_push_batch_id,
            )
            return {
                "status": "started",
                "report_id": report.id,
                "batch_id": report.auto_push_batch_id,
                "total": result.get("total", 0),
            }

    def _config(self):
        return self.app.config.get("APP_CONFIG", {}).get("scheduled_push", {}) or {}

    def _find_report(self, scan_dir, now_local, config):
        candidates = []
        for report in Report.query.order_by(Report.created_at.desc()).all():
            if not report.file_path or not os.path.isfile(report.file_path):
                continue

            if not self._is_under_scan_dir(report.file_path, scan_dir):
                continue

            mtime = datetime.fromtimestamp(
                os.path.getmtime(report.file_path), tz=now_local.tzinfo
            )
            if config.get("today_only", True) and mtime.date() != now_local.date():
                continue

            candidates.append((mtime, report))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _resolve_group_ids(self, config):
        group_ids = config.get("target_group_ids")
        if group_ids:
            return [int(gid) for gid in group_ids]

        group_names = [name for name in config.get("target_groups", []) if name]
        if not group_names:
            return None

        groups = Group.query.filter(Group.name.in_(group_names)).all()
        found_names = {group.name for group in groups}
        missing = sorted(set(group_names) - found_names)
        if missing:
            raise ValueError(f"定时推送目标分组不存在: {', '.join(missing)}")

        return [group.id for group in groups]

    @staticmethod
    def _is_under_scan_dir(file_path, scan_dir):
        try:
            return os.path.commonpath([
                os.path.abspath(file_path),
                os.path.abspath(scan_dir),
            ]) == os.path.abspath(scan_dir)
        except ValueError:
            return False

    @staticmethod
    def _local_now(now, config):
        tz_name = config.get("timezone", "Asia/Shanghai")
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning("未知时区 %s, 使用 Asia/Shanghai", tz_name)
            tz = ZoneInfo("Asia/Shanghai")

        if now is None:
            return datetime.now(tz)
        if now.tzinfo is None:
            return now.replace(tzinfo=tz)
        return now.astimezone(tz)
