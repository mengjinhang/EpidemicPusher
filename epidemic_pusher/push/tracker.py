import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, case

from epidemic_pusher.database import db
from epidemic_pusher.models import SendLog, Report, Subscriber

logger = logging.getLogger(__name__)


class PushTracker:

    @staticmethod
    def get_send_logs(batch_id=None, status=None, page=1, per_page=20):
        query = SendLog.query

        if batch_id:
            query = query.filter_by(batch_id=batch_id)
        if status:
            query = query.filter_by(status=status)

        query = query.order_by(SendLog.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)

        return {
            "items": [log.to_dict() for log in pagination.items],
            "total": pagination.total,
            "page": pagination.page,
            "pages": pagination.pages,
        }

    @staticmethod
    def get_batch_summary(batch_id):
        logs = SendLog.query.filter_by(batch_id=batch_id).all()
        if not logs:
            return None

        summary = {
            "batch_id": batch_id,
            "total": len(logs),
            "success": 0,
            "failed": 0,
            "pending": 0,
            "sending": 0,
        }

        for log in logs:
            if log.status in summary:
                summary[log.status] += 1

        report = logs[0].report if logs else None
        summary["report_title"] = report.title if report else "未知"
        summary["created_at"] = logs[0].created_at.strftime("%Y-%m-%d %H:%M:%S")
        summary["success_rate"] = (
            round(summary["success"] / max(summary["total"], 1) * 100, 1)
        )

        return summary

    @staticmethod
    def get_dashboard_stats():
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        total_subscribers = Subscriber.query.filter_by(status="active").count()
        total_reports = Report.query.count()

        total_sent = SendLog.query.filter_by(status="success").count()
        today_sent = SendLog.query.filter(
            SendLog.status == "success",
            SendLog.sent_at >= today_start,
        ).count()

        total_failed = SendLog.query.filter_by(status="failed").count()

        total_logs = SendLog.query.filter(
            SendLog.status.in_(["success", "failed"])
        ).count()
        success_rate = round(total_sent / max(total_logs, 1) * 100, 1)

        return {
            "total_subscribers": total_subscribers,
            "total_reports": total_reports,
            "total_sent": total_sent,
            "today_sent": today_sent,
            "total_failed": total_failed,
            "success_rate": success_rate,
        }

    @staticmethod
    def get_recent_batches(limit=10):
        subq = (
            db.session.query(
                SendLog.batch_id,
                func.min(SendLog.created_at).label("created_at"),
                func.count(SendLog.id).label("total"),
                func.sum(case((SendLog.status == "success", 1), else_=0)).label("success"),
                func.sum(case((SendLog.status == "failed", 1), else_=0)).label("failed"),
            )
            .group_by(SendLog.batch_id)
            .order_by(func.min(SendLog.created_at).desc())
            .limit(limit)
            .all()
        )

        batches = []
        for row in subq:
            log = SendLog.query.filter_by(batch_id=row.batch_id).first()
            report_title = log.report.title if log and log.report else "未知"

            batches.append({
                "batch_id": row.batch_id,
                "report_title": report_title,
                "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "total": row.total,
                "success": row.success,
                "failed": row.failed,
                "success_rate": round(row.success / max(row.total, 1) * 100, 1),
            })

        return batches

    @staticmethod
    def get_daily_stats(days=7):
        now = datetime.now(timezone.utc)
        stats = []

        for i in range(days - 1, -1, -1):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            success = SendLog.query.filter(
                SendLog.status == "success",
                SendLog.sent_at >= day_start,
                SendLog.sent_at < day_end,
            ).count()

            failed = SendLog.query.filter(
                SendLog.status == "failed",
                SendLog.created_at >= day_start,
                SendLog.created_at < day_end,
            ).count()

            stats.append({
                "date": day_start.strftime("%m-%d"),
                "success": success,
                "failed": failed,
            })

        return stats

    @staticmethod
    def cleanup_old_logs(days=90):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = SendLog.query.filter(SendLog.created_at < cutoff).delete(
            synchronize_session="fetch"
        )
        db.session.commit()
        logger.info("清理 %d 天前的发送记录: %d 条", days, count)
        return count
