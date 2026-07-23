document.addEventListener('DOMContentLoaded', function () {
    initClock();
    initSidebarToggle();
    initAutoRefreshTasks();
});

function initClock() {
    var el = document.getElementById('currentTime');
    if (!el) return;

    function update() {
        var now = new Date();
        el.textContent = now.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        });
    }
    update();
    setInterval(update, 1000);
}

function initSidebarToggle() {
    var toggle = document.getElementById('sidebarToggle');
    var sidebar = document.querySelector('.sidebar');
    if (!toggle || !sidebar) return;

    toggle.addEventListener('click', function () {
        sidebar.classList.toggle('show');
    });

    document.addEventListener('click', function (e) {
        if (
            window.innerWidth < 768 &&
            sidebar.classList.contains('show') &&
            !sidebar.contains(e.target) &&
            !toggle.contains(e.target)
        ) {
            sidebar.classList.remove('show');
        }
    });
}

function initAutoRefreshTasks() {
    var tasks = document.querySelectorAll('.push-task[data-batch]');
    if (tasks.length === 0) return;

    tasks.forEach(function (taskEl) {
        var batchId = taskEl.dataset.batch;
        pollTask(batchId, taskEl);
    });
}

function pollTask(batchId, taskEl) {
    fetch('/api/push/progress/' + batchId)
        .then(function (resp) { return resp.json(); })
        .then(function (data) {
            if (data.error) return;

            var progressBar = taskEl.querySelector('.progress-bar');
            var statusBadge = taskEl.querySelector('.badge');
            var statsSpan = taskEl.querySelector('.text-muted span:first-child');
            var pctSpan = taskEl.querySelector('.text-muted span:last-child');

            if (progressBar) {
                progressBar.style.width = data.progress_pct + '%';
            }
            if (statusBadge) {
                statusBadge.textContent = data.status;
            }
            if (statsSpan) {
                statsSpan.textContent = '成功: ' + data.success + ' / 失败: ' + data.failed;
            }
            if (pctSpan) {
                pctSpan.textContent = data.progress_pct + '%';
            }

            if (data.status === 'running') {
                setTimeout(function () { pollTask(batchId, taskEl); }, 2000);
            } else if (statusBadge) {
                if (data.status === 'cancelled') {
                    statusBadge.className = 'badge bg-secondary';
                    statusBadge.textContent = '已取消';
                } else if (data.failed > 0) {
                    statusBadge.className = 'badge bg-warning text-dark';
                    statusBadge.textContent = '部分失败';
                } else {
                    statusBadge.className = 'badge bg-success';
                    statusBadge.textContent = '已完成';
                }
            }
        })
        .catch(function () {
            setTimeout(function () { pollTask(batchId, taskEl); }, 5000);
        });
}
