import os
import logging
import tempfile

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify,
    current_app,
    send_from_directory,
)

from epidemic_pusher.database import db
from epidemic_pusher.models import Subscriber, Group, Report, SendLog, SmtpConfig
from epidemic_pusher.subscriber.manager import SubscriberManager, SubscriberError
from epidemic_pusher.subscriber.group import GroupManager, GroupError
from epidemic_pusher.subscriber.importer import SubscriberImporter, ImportError_
from epidemic_pusher.report.parser import ReportParser
from epidemic_pusher.push.tracker import PushTracker
from epidemic_pusher.mail.sender import EmailSender
from epidemic_pusher.push.scheduled import ScheduledPushService
from epidemic_pusher.push.scheduler import PushScheduler

logger = logging.getLogger(__name__)

bp = Blueprint("main", __name__)


# ─── Dashboard ───────────────────────────────────────────────

@bp.route("/")
def dashboard():
    stats = PushTracker.get_dashboard_stats()
    recent_batches = PushTracker.get_recent_batches(limit=5)
    daily_stats = PushTracker.get_daily_stats(days=7)
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_batches=recent_batches,
        daily_stats=daily_stats,
    )


# ─── Subscribers ─────────────────────────────────────────────

@bp.route("/subscribers")
def subscribers():
    page = request.args.get("page", 1, type=int)
    group_id = request.args.get("group_id", type=int)
    keyword = request.args.get("keyword", "")
    status = request.args.get("status", "")

    result = SubscriberManager.list_all(
        group_id=group_id,
        status=status or None,
        keyword=keyword or None,
        page=page,
    )
    groups = GroupManager.list_all()

    return render_template(
        "subscribers.html",
        subscribers=result,
        groups=groups,
        current_group=group_id,
        current_keyword=keyword,
        current_status=status,
    )


@bp.route("/subscribers/add", methods=["POST"])
def subscriber_add():
    try:
        SubscriberManager.add(
            name=request.form["name"],
            email=request.form["email"],
            group_id=request.form.get("group_id", type=int) or None,
            remark=request.form.get("remark", ""),
        )
        flash("订阅者添加成功", "success")
    except SubscriberError as e:
        flash(str(e), "danger")
    return redirect(url_for("main.subscribers"))


@bp.route("/subscribers/<int:subscriber_id>/delete", methods=["POST"])
def subscriber_delete(subscriber_id):
    try:
        SubscriberManager.delete(subscriber_id)
        flash("删除成功", "success")
    except SubscriberError as e:
        flash(str(e), "danger")
    return redirect(url_for("main.subscribers"))


@bp.route("/subscribers/<int:subscriber_id>/update", methods=["POST"])
def subscriber_update(subscriber_id):
    try:
        kwargs = {}
        for field in ("name", "email", "remark", "status"):
            val = request.form.get(field)
            if val is not None:
                kwargs[field] = val
        gid = request.form.get("group_id")
        if gid is not None:
            kwargs["group_id"] = int(gid) if gid else None

        SubscriberManager.update(subscriber_id, **kwargs)
        flash("更新成功", "success")
    except SubscriberError as e:
        flash(str(e), "danger")
    return redirect(url_for("main.subscribers"))


@bp.route("/subscribers/import", methods=["POST"])
def subscriber_import():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("请选择文件", "danger")
        return redirect(url_for("main.subscribers"))

    group_id = request.form.get("group_id", type=int) or None

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".csv", ".xlsx", ".xls"):
        flash("仅支持 CSV 和 Excel 文件", "danger")
        return redirect(url_for("main.subscribers"))

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        result = SubscriberImporter.import_file(tmp_path, default_group_id=group_id)
        info = result.to_dict()
        flash(
            f"导入完成: 成功 {info['success_count']}, "
            f"跳过 {info['skip_count']}, 失败 {info['fail_count']}",
            "success" if info["fail_count"] == 0 else "warning",
        )
    except ImportError_ as e:
        flash(str(e), "danger")
    finally:
        os.unlink(tmp_path)

    return redirect(url_for("main.subscribers"))


@bp.route("/subscribers/template")
def subscriber_template():
    tmp_path = os.path.join(tempfile.gettempdir(), "import_template.csv")
    SubscriberImporter.generate_template_csv(tmp_path)
    directory = os.path.dirname(tmp_path)
    filename = os.path.basename(tmp_path)
    return send_from_directory(directory, filename, as_attachment=True)


# ─── Groups ──────────────────────────────────────────────────

@bp.route("/groups")
def groups():
    group_list = GroupManager.get_with_subscriber_count()
    return render_template("groups.html", groups=group_list)


@bp.route("/groups/add", methods=["POST"])
def group_add():
    try:
        GroupManager.create(
            name=request.form["name"],
            description=request.form.get("description", ""),
        )
        flash("分组创建成功", "success")
    except GroupError as e:
        flash(str(e), "danger")
    return redirect(url_for("main.groups"))


@bp.route("/groups/<int:group_id>/delete", methods=["POST"])
def group_delete(group_id):
    try:
        GroupManager.delete(group_id)
        flash("分组已删除", "success")
    except GroupError as e:
        flash(str(e), "danger")
    return redirect(url_for("main.groups"))


@bp.route("/groups/<int:group_id>/update", methods=["POST"])
def group_update(group_id):
    try:
        GroupManager.update(
            group_id,
            name=request.form["name"],
            description=request.form.get("description", ""),
        )
        flash("分组更新成功", "success")
    except GroupError as e:
        flash(str(e), "danger")
    return redirect(url_for("main.groups"))


# ─── Reports ─────────────────────────────────────────────────

@bp.route("/reports")
def reports():
    scan_dir = current_app.config.get("REPORT_SCAN_DIR", "reports")
    ReportParser.sync_reports(scan_dir)
    result = ReportParser.list_reports(
        page=request.args.get("page", 1, type=int),
    )
    return render_template("reports.html", reports=result, scan_dir=os.path.abspath(scan_dir))


@bp.route("/reports/<int:report_id>/delete", methods=["POST"])
def report_delete(report_id):
    try:
        ReportParser.delete_report(report_id)
        flash("报告记录已删除", "success")
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("main.reports"))


# ─── Push ─────────────────────────────────────────────────────

@bp.route("/push")
def push():
    reports_list = Report.query.order_by(Report.created_at.desc()).all()
    groups_list = GroupManager.get_with_subscriber_count()
    push_engine = current_app.config.get("PUSH_ENGINE")
    active_tasks = push_engine.get_active_tasks() if push_engine else []
    return render_template(
        "push.html",
        reports=reports_list,
        groups=groups_list,
        active_tasks=active_tasks,
    )


@bp.route("/push/send", methods=["POST"])
def push_send():
    push_engine = current_app.config.get("PUSH_ENGINE")
    if not push_engine:
        flash("推送引擎未初始化", "danger")
        return redirect(url_for("main.push"))

    report_id = request.form.get("report_id", type=int)
    if not report_id:
        flash("请选择要推送的报告", "danger")
        return redirect(url_for("main.push"))

    group_ids = request.form.getlist("group_ids", type=int)
    extra_message = request.form.get("extra_message", "")

    try:
        result = push_engine.push(
            report_id=report_id,
            group_ids=group_ids or None,
            extra_message=extra_message,
        )
        flash(
            f"推送任务已创建 (批次: {result['batch_id']}), "
            f"共 {result['total']} 封邮件",
            "success",
        )
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("main.push"))


@bp.route("/api/push/progress/<batch_id>")
def push_progress(batch_id):
    push_engine = current_app.config.get("PUSH_ENGINE")
    if push_engine:
        progress = push_engine.get_task_progress(batch_id)
        if progress:
            return jsonify(progress)
    return jsonify(PushTracker.get_batch_summary(batch_id) or {"error": "not found"})


# ─── Logs ─────────────────────────────────────────────────────

@bp.route("/logs")
def logs():
    page = request.args.get("page", 1, type=int)
    batch_id = request.args.get("batch_id", "")
    status = request.args.get("status", "")

    result = PushTracker.get_send_logs(
        batch_id=batch_id or None,
        status=status or None,
        page=page,
    )
    return render_template(
        "logs.html",
        logs=result,
        current_batch=batch_id,
        current_status=status,
    )


# ─── Scheduled Push ───────────────────────────────────────────

@bp.route("/scheduled-push")
def scheduled_push():
    groups = GroupManager.get_with_subscriber_count()
    app_config = current_app.config.get("APP_CONFIG", {})
    sp_config = app_config.get("scheduled_push", {}) or {}
    scheduler = current_app.config.get("PUSH_SCHEDULER")
    scheduler_jobs = scheduler.list_jobs() if scheduler else []

    recent_logs = []
    from epidemic_pusher.models import Report as ReportModel
    auto_pushed = ReportModel.query.filter(
        ReportModel.auto_pushed_at.isnot(None)
    ).order_by(ReportModel.auto_pushed_at.desc()).limit(10).all()
    for r in auto_pushed:
        recent_logs.append({
            "title": r.title,
            "batch_id": r.auto_push_batch_id,
            "pushed_at": r.auto_pushed_at.strftime("%Y-%m-%d %H:%M:%S") if r.auto_pushed_at else "",
        })

    return render_template(
        "scheduled_push.html",
        groups=groups,
        sp_config=sp_config,
        scheduler_jobs=scheduler_jobs,
        recent_logs=recent_logs,
    )


@bp.route("/scheduled-push/save", methods=["POST"])
def scheduled_push_save():
    import yaml

    enabled = "sp_enabled" in request.form
    hour = request.form.get("sp_hour", "8")
    minute = request.form.get("sp_minute", "0")
    target_groups = request.form.getlist("sp_groups")
    extra_message = request.form.get("sp_extra_message", "")
    today_only = "sp_today_only" in request.form
    skip_if_pushed = "sp_skip_if_pushed" in request.form
    wait_enabled = "sp_wait_enabled" in request.form
    wait_interval = request.form.get("sp_wait_interval", "300")
    wait_timeout = request.form.get("sp_wait_timeout", "3600")

    cron_expr = f"{minute} {hour} * * *"

    app_config = current_app.config.get("APP_CONFIG", {})
    app_config["scheduled_push"] = {
        "enabled": enabled,
        "cron": cron_expr,
        "timezone": "Asia/Shanghai",
        "report_dir": app_config.get("report", {}).get("scan_dir", "reports"),
        "today_only": today_only,
        "skip_if_pushed": skip_if_pushed,
        "target_groups": target_groups,
        "extra_message": extra_message,
        "wait_report": {
            "enabled": wait_enabled,
            "retry_interval": int(wait_interval),
            "timeout": int(wait_timeout),
        },
    }

    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.yaml"
    )
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f) or {}
        file_config["scheduled_push"] = app_config["scheduled_push"]
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(file_config, f, allow_unicode=True, default_flow_style=False)

    push_engine = current_app.config.get("PUSH_ENGINE")
    scheduler = current_app.config.get("PUSH_SCHEDULER")

    if enabled and push_engine:
        if not scheduler:
            scheduler = PushScheduler()
            scheduler.init_app(current_app._get_current_object(), push_engine)
            scheduler.start()
            current_app.config["PUSH_SCHEDULER"] = scheduler

        service = current_app.config.get("SCHEDULED_PUSH_SERVICE")
        if not service:
            service = ScheduledPushService(
                current_app._get_current_object(), push_engine
            )
            current_app.config["SCHEDULED_PUSH_SERVICE"] = service

        scheduler.add_scheduled_push_job(service, app_config["scheduled_push"])
        flash(f"定时推送已启用 (每天 {hour}:{minute.zfill(2)})", "success")
    else:
        if scheduler:
            scheduler.remove_job("daily_report_auto_push")
            scheduler.remove_job("daily_report_auto_push_retry")
        flash("定时推送已关闭", "info")

    return redirect(url_for("main.scheduled_push"))


# ─── Settings ─────────────────────────────────────────────────

@bp.route("/settings")
def settings():
    smtp = SmtpConfig.query.filter_by(is_active=True).first()
    return render_template("settings.html", smtp=smtp)


@bp.route("/settings/smtp", methods=["POST"])
def settings_smtp():
    SmtpConfig.query.update({"is_active": False})

    smtp = SmtpConfig.query.first()
    if not smtp:
        smtp = SmtpConfig(
            host=request.form["host"],
            port=int(request.form["port"]),
            username=request.form["username"],
            password=request.form["password"],
            use_ssl="use_ssl" in request.form,
            use_tls="use_tls" in request.form,
            sender_name=request.form.get("sender_name", "疫情报告推送系统"),
            sender_email=request.form["sender_email"],
            is_active=True,
        )
        db.session.add(smtp)
    else:
        smtp.host = request.form["host"]
        smtp.port = int(request.form["port"])
        smtp.username = request.form["username"]
        if request.form["password"] != "******":
            smtp.password = request.form["password"]
        smtp.use_ssl = "use_ssl" in request.form
        smtp.use_tls = "use_tls" in request.form
        smtp.sender_name = request.form.get("sender_name", "疫情报告推送系统")
        smtp.sender_email = request.form["sender_email"]
        smtp.is_active = True

    db.session.commit()
    flash("SMTP 配置已保存", "success")
    return redirect(url_for("main.settings"))


@bp.route("/settings/smtp/test", methods=["POST"])
def settings_smtp_test():
    config = {
        "host": request.form["host"],
        "port": int(request.form["port"]),
        "username": request.form["username"],
        "password": request.form["password"],
        "use_ssl": "use_ssl" in request.form,
        "use_tls": "use_tls" in request.form,
    }

    if config["password"] == "******":
        smtp = SmtpConfig.query.filter_by(is_active=True).first()
        if smtp:
            config["password"] = smtp.password

    sender = EmailSender(config)
    ok, msg = sender.test_connection()

    return jsonify({"success": ok, "message": msg})
