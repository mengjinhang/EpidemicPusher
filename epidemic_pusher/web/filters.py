from datetime import datetime, timezone


def register_filters(app):

    @app.template_filter("status_badge")
    def status_badge(status):
        badges = {
            "active": '<span class="badge bg-success">活跃</span>',
            "inactive": '<span class="badge bg-secondary">停用</span>',
            "bounced": '<span class="badge bg-danger">退信</span>',
            "success": '<span class="badge bg-success">成功</span>',
            "failed": '<span class="badge bg-danger">失败</span>',
            "pending": '<span class="badge bg-warning text-dark">待发送</span>',
            "sending": '<span class="badge bg-info">发送中</span>',
            "cancelled": '<span class="badge bg-secondary">已取消</span>',
            "retry": '<span class="badge bg-warning text-dark">重试中</span>',
        }
        return badges.get(status, f'<span class="badge bg-secondary">{status}</span>')

    @app.template_filter("file_type_icon")
    def file_type_icon(file_type):
        icons = {
            "pdf": '<i class="bi bi-file-earmark-pdf text-danger"></i>',
            "docx": '<i class="bi bi-file-earmark-word text-primary"></i>',
            "doc": '<i class="bi bi-file-earmark-word text-primary"></i>',
        }
        return icons.get(file_type, '<i class="bi bi-file-earmark"></i>')

    @app.template_filter("format_size")
    def format_size(size_bytes):
        if not size_bytes:
            return "0 B"
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / 1024 / 1024:.2f} MB"

    @app.template_filter("time_ago")
    def time_ago(dt):
        if not dt:
            return "N/A"
        if isinstance(dt, str):
            dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")

        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        diff = now - dt
        seconds = diff.total_seconds()

        if seconds < 60:
            return "刚刚"
        elif seconds < 3600:
            return f"{int(seconds / 60)} 分钟前"
        elif seconds < 86400:
            return f"{int(seconds / 3600)} 小时前"
        elif seconds < 604800:
            return f"{int(seconds / 86400)} 天前"
        else:
            return dt.strftime("%Y-%m-%d")

    @app.template_filter("truncate_text")
    def truncate_text(text, length=100):
        if not text:
            return ""
        if len(text) <= length:
            return text
        return text[:length] + "..."
