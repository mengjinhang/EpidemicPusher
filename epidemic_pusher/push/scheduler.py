import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class PushScheduler:

    def __init__(self, app=None, push_engine=None):
        self.app = app
        self.push_engine = push_engine
        self.scheduler = BackgroundScheduler()
        self._jobs = {}
        self._scheduled_push_service = None
        self._scheduled_push_config = {}

    def init_app(self, app, push_engine):
        self.app = app
        self.push_engine = push_engine

    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("定时调度器已启动")

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("定时调度器已停止")

    def add_job(self, job_id, cron_expr, report_id, group_ids=None, extra_message=""):
        trigger = self._build_cron_trigger(cron_expr)

        job = self.scheduler.add_job(
            func=self._push_job,
            trigger=trigger,
            id=job_id,
            kwargs={
                "report_id": report_id,
                "group_ids": group_ids,
                "extra_message": extra_message,
            },
            replace_existing=True,
        )

        self._jobs[job_id] = {
            "type": "fixed_report",
            "cron": cron_expr,
            "report_id": report_id,
            "group_ids": group_ids,
            "next_run": self._format_next_run(job),
        }

        logger.info("定时任务已添加: %s, cron=%s", job_id, cron_expr)
        return self._jobs[job_id]

    def add_scheduled_push_job(self, service, config):
        self._scheduled_push_service = service
        self._scheduled_push_config = config or {}

        cron_expr = self._scheduled_push_config.get("cron", "0 8 * * *")
        timezone_name = self._scheduled_push_config.get("timezone", "Asia/Shanghai")
        trigger = self._build_cron_trigger(cron_expr, timezone_name)
        job_id = self._scheduled_push_config.get("job_id", "daily_report_auto_push")

        job = self.scheduler.add_job(
            func=self._scheduled_push_job,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            max_instances=1,
        )
        self._jobs[job_id] = {
            "type": "scheduled_push",
            "cron": cron_expr,
            "next_run": self._format_next_run(job),
        }
        logger.info("自动定时推送任务已添加: %s, cron=%s", job_id, cron_expr)
        return self._jobs[job_id]

    def remove_job(self, job_id):
        try:
            self.scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            logger.info("定时任务已移除: %s", job_id)
            return True
        except Exception as e:
            logger.warning("移除定时任务失败: %s, %s", job_id, e)
            return False

    def list_jobs(self):
        jobs = []
        for job in self.scheduler.get_jobs():
            info = self._jobs.get(job.id, {})
            jobs.append({
                "id": job.id,
                "type": info.get("type", ""),
                "cron": info.get("cron", ""),
                "report_id": info.get("report_id"),
                "group_ids": info.get("group_ids"),
                "next_run": self._format_next_run(job),
            })
        return jobs

    def _push_job(self, report_id, group_ids=None, extra_message=""):
        logger.info("定时推送触发: report_id=%d", report_id)
        try:
            self.push_engine.push(
                report_id=report_id,
                group_ids=group_ids,
                extra_message=extra_message,
            )
        except Exception as e:
            logger.error("定时推送失败: %s", e)

    def _scheduled_push_job(self):
        if not self._scheduled_push_service:
            logger.error("自动定时推送服务未初始化")
            return

        try:
            result = self._scheduled_push_service.run_once()
            if result.get("status") == "waiting":
                self._schedule_retry_if_needed()
            else:
                self._remove_retry_job()
        except Exception as e:
            logger.error("自动定时推送失败: %s", e)
            self._remove_retry_job()

    def _scheduled_push_retry_job(self, deadline):
        if datetime.now(timezone.utc) > deadline:
            logger.warning("自动定时推送等待报告超时")
            self._remove_retry_job()
            return

        try:
            result = self._scheduled_push_service.run_once()
            if result.get("status") != "waiting":
                self._remove_retry_job()
        except Exception as e:
            logger.error("自动定时推送重试失败: %s", e)
            self._remove_retry_job()

    def _schedule_retry_if_needed(self):
        wait_config = self._scheduled_push_config.get("wait_report", {}) or {}
        if not wait_config.get("enabled", True):
            return

        retry_job_id = self._scheduled_push_config.get(
            "retry_job_id", "daily_report_auto_push_retry"
        )
        if self.scheduler.get_job(retry_job_id):
            return

        retry_interval = int(wait_config.get("retry_interval", 300))
        timeout = int(wait_config.get("timeout", 3600))
        deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout)

        self.scheduler.add_job(
            func=self._scheduled_push_retry_job,
            trigger=IntervalTrigger(seconds=retry_interval),
            id=retry_job_id,
            kwargs={"deadline": deadline},
            replace_existing=True,
            max_instances=1,
        )
        logger.info(
            "自动定时推送等待报告: 每 %d 秒重试, 截止 %s",
            retry_interval,
            deadline.isoformat(),
        )

    def _remove_retry_job(self):
        retry_job_id = self._scheduled_push_config.get(
            "retry_job_id", "daily_report_auto_push_retry"
        )
        job = self.scheduler.get_job(retry_job_id)
        if job:
            self.scheduler.remove_job(retry_job_id)
            logger.info("自动定时推送重试任务已移除")

    @staticmethod
    def _format_next_run(job):
        next_run = getattr(job, "next_run_time", None)
        return str(next_run) if next_run else ""

    @staticmethod
    def _build_cron_trigger(cron_expr, timezone_name=None):
        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"无效的 cron 表达式: {cron_expr} (需要5段)")

        kwargs = {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }
        if timezone_name:
            try:
                kwargs["timezone"] = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                logger.warning("未知时区 %s, 调度器使用本地时区", timezone_name)

        return CronTrigger(**kwargs)
