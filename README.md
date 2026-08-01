# 疫情报告邮件推送系统

一个基于 Flask 的疫情报告邮件推送平台：自动扫描本地报告文件（PDF / Word），管理订阅者与分组，通过 SMTP 将报告作为附件批量推送给订阅者，并提供推送进度跟踪、发送日志与每日定时自动推送能力。

## 功能特性

### 📄 报告管理
- 自动扫描 `reports/` 目录下的报告文件（支持 `.pdf`、`.docx`、`.doc`）
- 扫描目录可在页面上更改：内置目录浏览器弹窗，逐级点选或直接输入路径（Windows 支持盘符切换），保存后持久化生效
- 自动提取报告摘要（PDF 前 3 页 / Word 段落，最多 500 字），用于邮件正文
- 文件变更后自动更新摘要和文件大小
- 报告列表分页展示，记录每份报告的推送次数

### 👥 订阅者管理
- 订阅者增删改查，支持按分组 / 状态 / 关键词（姓名、邮箱、备注）筛选
- 订阅者状态管理：`active`（活跃）/ `inactive`(停用) / `bounced`（退信，发送被拒后自动标记）
- 分组管理：创建、编辑、删除分组（删除时组内订阅者自动移至"未分组"）
- 批量导入：支持 CSV 和 Excel（`.xlsx` / `.xls`）导入，可下载导入模板
  - 导入时自动校验邮箱格式、拒绝临时邮箱域名、跳过组内重复邮箱
  - CSV 支持 UTF-8（含 BOM）和 GBK 编码
  - 导入文件中的 `group` 列可自动创建不存在的分组

### 📧 邮件推送
- 手动推送：选择报告 + 目标分组（不选则推送给全部活跃订阅者），一键群发
- 邮件为 HTML + 纯文本双格式，报告文件作为附件（单附件限 25MB）
- 多线程并发发送（默认 5 个 worker），带每分钟限流（默认 30 封/分钟）
- 失败自动重试：指数退避（默认最多 3 次），收件人被拒等永久性错误不重试并自动将订阅者标记为退信
- 实时推送进度查询（成功 / 失败 / 待发送 / 百分比），支持取消任务
- 支持在邮件中附加自定义留言

### ⏰ 定时自动推送
- 每天定时（默认 8:00，时区 Asia/Shanghai）自动扫描报告目录并推送当天最新报告
- "等待报告"模式：到点未发现当天报告时，按间隔重试（默认每 5 分钟，最长等待 1 小时）
- 可配置仅推送当天文件（`today_only`）、跳过已推送报告（`skip_if_pushed`）、目标分组
- Web 界面可视化配置，保存后写回 `config.yaml` 并热更新调度任务

### 📊 统计与日志
- 仪表盘：活跃订阅者数、报告总数、累计/今日发送量、成功率、近 7 天发送趋势、最近批次
- 发送日志：按批次 / 状态筛选，记录每封邮件的发送状态、错误原因、发送时间
- 支持清理历史日志（默认保留 90 天）

### ⚙️ SMTP 配置
- Web 界面配置 SMTP 服务器，支持 SSL / STARTTLS
- 内置常用邮箱预设：QQ、163、126、Gmail、Outlook
- 一键测试连接

## 技术栈

| 组件 | 说明 |
|------|------|
| Flask 3.x | Web 框架 |
| Flask-SQLAlchemy / SQLAlchemy 2.x | ORM，数据存储于 SQLite |
| APScheduler | 定时任务调度 |
| python-docx | Word 摘要提取 |
| pypdf | PDF 摘要提取 |
| tzdata | Windows 下的时区数据（仅 Windows 安装） |
| openpyxl | Excel 导入 |
| Jinja2 + Bootstrap | 页面与邮件模板 |

## 项目结构

```
Email push/
├── app.py                      # 应用入口（create_app 工厂 + 开发服务器）
├── config.yaml                 # 全局配置文件
├── requirements.txt            # Python 依赖
├── reports/                    # 报告扫描目录（放入 PDF/Word 即可被识别）
├── data/                       # SQLite 数据库（自动创建）
├── logs/                       # 运行日志（自动创建）
├── templates/                  # Web 页面模板
│   └── email/                  # 邮件 HTML 模板（epidemic.html / default.html）
├── static/                     # 静态资源
├── tests/                      # pytest 测试套件
└── epidemic_pusher/            # 核心包
    ├── database.py             # 数据库初始化与轻量 schema 迁移
    ├── models.py               # 数据模型（订阅者/分组/报告/发送日志/SMTP配置）
    ├── mail/
    │   ├── validator.py        # 邮箱格式校验、临时邮箱拦截、批量去重
    │   ├── builder.py          # 邮件构建（HTML+纯文本+附件+内嵌图片）
    │   └── sender.py           # SMTP 连接管理、限流、重试发送
    ├── subscriber/
    │   ├── manager.py          # 订阅者增删改查
    │   ├── group.py            # 分组管理
    │   └── importer.py         # CSV/Excel 批量导入
    ├── report/
    │   ├── parser.py           # 报告目录扫描、同步入库、摘要提取
    │   └── converter.py        # 报告格式转换辅助
    ├── push/
    │   ├── engine.py           # 推送引擎（多线程群发、进度跟踪、取消）
    │   ├── scheduler.py        # APScheduler 封装（cron 任务、等待重试）
    │   ├── scheduled.py        # 定时自动推送业务逻辑
    │   └── tracker.py          # 发送日志查询与统计
    └── web/
        ├── routes.py           # 全部 Web 路由
        └── filters.py          # Jinja2 模板过滤器
```

## 快速开始

### 1. 环境要求

- Python 3.9+（开发环境为 3.13）
- macOS / Linux / Windows 均支持

### 2. 安装依赖

macOS / Linux：

```bash
cd "Email push"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows（PowerShell 或 CMD）：

```powershell
cd "Email push"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> Windows 下 `requirements.txt` 会自动附带安装 `tzdata`（时区数据），定时推送依赖它。

### 3. 启动应用

```bash
python app.py
```

启动后访问 <http://127.0.0.1:5000>。

首次启动会自动完成：
- 创建 `data/app.db` SQLite 数据库及全部表结构
- 创建 `reports/`、`logs/` 目录
- 日志同时输出到控制台和 `logs/app.log`

### 4. 初始化配置（Web 界面操作）

1. **配置 SMTP**：进入「设置」页面，填写 SMTP 服务器信息（或使用 QQ/163/Gmail 等预设），点击"测试连接"确认可用后保存。
   > 注意：QQ / 163 等邮箱需使用**授权码**而非登录密码，需先在邮箱设置中开启 SMTP 服务。
2. **添加订阅者**：进入「订阅者」页面手动添加，或下载 CSV 模板批量导入。模板列为 `name, email, group, remark`。
3. **放入报告**：将 PDF / Word 报告文件放入 `reports/` 目录，访问「报告」页面即自动扫描入库。
4. **推送**：进入「推送」页面，选择报告和目标分组，点击发送；或在「定时推送」页面配置每日自动推送。

## 配置说明（config.yaml）

```yaml
server:
  host: 0.0.0.0        # 监听地址（仅本机使用建议改为 127.0.0.1）
  port: 5000
  debug: true          # 生产环境务必改为 false

database:
  path: data/app.db    # SQLite 数据库路径

report:
  scan_dir: reports    # 报告扫描目录
  allowed_types: [.pdf, .docx, .doc]

push:
  max_workers: 5       # 并发发送线程数
  rate_limit: 30       # 每分钟最大发送量（防止触发邮箱服务商限制）
  retry_max: 3         # 单封邮件最大重试次数
  retry_delay: 60      # 重试基础延迟（秒），按 60/120/240 指数退避
  batch_size: 50

scheduled_push:        # 定时自动推送（也可在 Web 界面配置）
  enabled: false
  cron: 0 8 * * *      # 标准 5 段 cron，默认每天 8:00
  timezone: Asia/Shanghai
  report_dir: reports
  today_only: true     # 仅推送当天（按文件修改时间）的报告
  skip_if_pushed: true # 已自动推送过的报告不重复推送
  target_groups: []    # 目标分组名列表，空 = 全部活跃订阅者
  extra_message: ''    # 附加到邮件中的留言
  wait_report:         # 到点没有报告时的等待策略
    enabled: true
    retry_interval: 300  # 每 5 分钟重试一次
    timeout: 3600        # 最长等待 1 小时

smtp:                  # SMTP 预设参考（实际生效配置存在数据库中，通过「设置」页面管理）
  presets: {qq, netease_163, netease_126, gmail, outlook}
```

## 运行测试

```bash
python -m pytest tests/ -v
```

测试覆盖邮箱校验、订阅者管理、报告解析、推送引擎、定时推送等核心逻辑。

## 使用建议与注意事项

- **安全**：系统目前**没有登录认证**，且 SMTP 密码明文存储于本地 SQLite。请仅在本机或可信内网使用，切勿将服务直接暴露到公网；对外部署前应将 `server.host` 改为 `127.0.0.1`、`debug` 改为 `false`，并在前面加反向代理 + 认证。
- **发送限流**：各邮箱服务商对发信频率有限制（如 QQ 邮箱约 100 封/天起步），建议根据实际账号调整 `rate_limit`，避免账号被临时封禁。
- **附件大小**：单封邮件附件限制 25MB，超出会发送失败。
- **删除报告**：报告页面的删除仅移除数据库记录；只要文件仍在 `reports/` 目录中，下次访问报告页会被重新扫描入库。要彻底移除请同时删除文件。
- **时间显示**：数据库中的时间以 UTC 存储，页面部分时间可能与本地时间（东八区）相差 8 小时。

## 许可

内部使用项目，未指定开源许可证。
