# 部署接口与运维说明

本文记录当前 Django＋React 实现对应的生产接口，不表示已在真实服务器部署或验收。生产需要 HTTPS 反向代理、静态前端服务、Gunicorn Web 服务和本机任务 worker；本次不连接服务器、不启动公网服务。

日常本机启动见[本地使用手册](local-usage.md)，页面操作见[网页指南](dashboard-guide.md)，项目入口见[README](../README.md)。本文是生产配置参考与发布检查顺序，不是已经实测通过的一键部署教程。

## 组件与请求分流

- `frontend/dist/`：由 Vite 构建的静态资源。生产 Web 服务器提供静态文件；SPA 页面路径回退到 `index.html`。
- `/api/`：转发到 `webapp.wsgi:application` 对应的 Gunicorn 服务。API 路径不能回退到前端 HTML。
- 模拟任务：由 Django 接受后在独立 worker 进程执行。不要在 HTTP 请求里执行模拟；不要因 Web 服务重启而清理或误杀已接受的任务。
- SQLite：默认 `data/history_v5.sqlite3`，任务状态和导出临时目录分别为 `data/jobs_v5/`、`data/exports_v5/`。三个位置均需为服务账号可写的私有持久目录。

本地开发时 Vite 在 `127.0.0.1:5173` 提供网页，并把 `/api` 代理至 `127.0.0.1:8000`。生产由反向代理保证浏览器只使用同一个 HTTPS 主机；不需要 CORS。前端构建变量 `VITE_*` 会进入公开资源，绝不能放密钥、数据库路径凭据或其他私有值。

## 生产环境变量

至少设置并持久保存以下 Django 环境值：

```text
LOTTERY_ENV=production
SECRET_KEY=<高熵随机值>
LOTTERY_ALLOWED_HOSTS=<正式主机名>
LOTTERY_DB_PATH=<私有持久路径>/history_v5.sqlite3
LOTTERY_JOBS_DIR=<私有持久路径>/jobs_v5
LOTTERY_EXPORTS_DIR=<私有持久路径>/exports_v5
```

生产模式缺少 `SECRET_KEY` 会拒绝启动。Compose 将 `LOTTERY_ALLOWED_HOSTS` 限定为正式域名，并将该 HTTPS Origin 放入 `LOTTERY_CSRF_TRUSTED_ORIGINS`；Caddy保留原Host并转发 `X-Forwarded-Proto`。当前 Django settings 未配置 `SECURE_PROXY_SSL_HEADER`，因此不把任意转发头当作安全判定依据；Secure Cookie 由 `LOTTERY_ENV=production` 明确启用。Cookie 保持 HttpOnly、SameSite=Lax。不要公开 SQLite、任务目录、备份或环境文件。

## 构建与服务配置

仓库的 Docker Compose 接口由 `app` 和 `caddy` 两个服务组成。`.env` 至少提供 `DOMAIN` 和高熵 `SECRET_KEY`。发布前安装锁文件依赖并构建前端：`npm --prefix frontend ci && npm --prefix frontend run build`；随后执行 `docker compose config --quiet` 检查配置，再按维护流程迁移目标数据库。`frontend/dist/` 以只读目录挂载给 Caddy。`app` 只在内部网络监听8000并由 Gunicorn 提供 WSGI；只有 Caddy发布80/443。Caddy把裸 `/api` 及 `/api/*` 转发到 Gunicorn，其余请求从 `frontend/dist/` 服务静态资源并将前端路径回退到 `index.html`；API不存在的路径仍由 Django 返回404，不会回退前端页面。Vite带内容哈希的 `/assets/*` 设置一年 immutable 缓存，`index.html` 设置 no-cache；私有 API 响应不应被共享缓存。生产不运行 Django `runserver`、Vite dev 或 Vite preview。

镜像以 `0700` 创建数据库、任务、导出和备份目录，容器用户为非root服务账号。Gunicorn使用2个gthread worker、每进程4个请求线程、120秒超时；每个WSGI进程默认只有1个并发导出槽，因此单容器最多两个长下载同时进行，其余线程仍可处理控制请求。导出槽是进程内限制，不是跨进程全局队列。

## 首次部署顺序（待服务器验收）

1. 准备正式域名、HTTPS入口、受控服务账号和持久存储；确认不覆盖已有数据库。
2. 配置私有 `.env` 中的 `DOMAIN`、`SECRET_KEY`，核对Compose环境及卷映射。
3. 安装锁定的前端依赖并构建 `frontend/dist/`，执行 `docker compose config --quiet` 检查配置，并构建app镜像。
4. 在与正式app相同的环境和持久卷中执行 `python manage.py migrate`；只有新库才执行 `python manage.py init_admin --username 实际管理员用户名`，交互输入密码。
5. 启动app及Caddy，检查健康状态、日志、域名证书和前端/API分流。
6. 验证登录、CSRF、双用户数据隔离、小型模拟、历史读取、Trace下载、取消任务及备份恢复，再开放日常使用。

上述为发布顺序，不表示本次已运行Docker、配置DNS或验证TLS。主目录已有管理员不代表服务器的新卷也已初始化。

## 更新、重启与完整停机

修改环境、后端代码或依赖后需按实际服务管理方式更新Web；前端修改需重新构建静态资源。数据库迁移前备份并核对目标路径。

**重启Web进程不等于重启整个app容器。** 当前worker由app内启动，容器停止或重建可能一并终止worker，不能承诺跨容器重启继续运行。没有验证进程生命周期之前，不得在活动模拟期间直接重建容器。

完整维护顺序：停止接收新任务 → 等待任务结束或请求取消并确认worker退出 → 停止相关服务 → 备份/迁移/更新 → 启动并检查登录、历史及小型模拟。当前不提供一键维护模式，应由维护者安排访问窗口并核对活动任务；不能只退出浏览器就认为已经停机。不要清空任务目录来代替取消。

### 本次图表修改的发布范围

2026-09-29图表改进同时修改后端图表API和React组件：后端在原`spec`、`rarity_labels`之外返回供数值表使用的`rows`，前端消费同一聚合数据。应配套发布后端代码和重新构建的前端资源，不能只替换其中一侧。

本次没有数据库迁移、格式版本变更或新依赖，不需要清空历史、重建账号或重新模拟。现有Trace可直接读取。主目录已执行前端构建，但没有执行服务器部署或重启生产服务；容器部署仍需按前节维护流程更新app镜像和静态资源。

发布后的最小检查：已有Trace结果可打开；宽窄窗口下图表联动；悬停、数值表的计数/比例一致；非Trace页面保持提示。不要为验证本次展示修改而删除数据。

## 数据库与备份

### 数据库版本边界

本版本使用 Django migration 管理 v5 schema。迁移前先验证目标 `LOTTERY_DB_PATH` 是预期的 v5 路径；不要将新版本指向旧 Streamlit 数据库，也不要自动迁移旧历史。2026-09-29已完成主目录本地合并、授权旧数据清理及空v5库迁移；以下部署接口不构成其它目录或服务器的数据删除许可。

### 备份

备份脚本可对运行中的SQLite源库执行在线备份。以下是非容器部署的路径示例，不是Compose命名卷在宿主机上的实际路径；维护者须先确认真实映射：

```bash
python3 scripts/backup_db.py /srv/lottery/data/history_v5.sqlite3 /srv/lottery/backups/lottery-v5-$(date +%F-%H%M%S).sqlite3
```

备份包含账号、密码哈希、会话、角色池、配置和已提交历史。它不包含 `jobs_v5/` 或 `exports_v5/`。脚本成功时输出 `Backup integrity_check: ok`，目标文件权限设置为 `0600`。备份目录应限制为服务/运维账号可访问，并复制到受控异机位置；不得放入静态网站目录或提交 Git。

### 恢复

恢复前停止 Web、worker 和定时备份，保存当前数据库副本，再恢复明确选定的 v5 备份。检查 `PRAGMA integrity_check` 为 `ok`，启动后验证账号登录、历史读取和小型模拟写入。恢复不会回滚或恢复任务目录；若任务状态与恢复后的数据库不一致，先保留目录并调查，不能递归清理数据目录。

### 定时备份接口

仓库提供的 `deploy/lottery-backup.service` 与 `.timer` 是 systemd 备份接口示例，假设 Docker Compose 服务名 `app` 和容器路径 `/app/data`、`/app/backups`。它们已与当前 Compose 配置对齐，使用 `history_v5.sqlite3` 与 `lottery-v5-` 前缀；用于非 Compose 的本机 Gunicorn 部署时需由维护者适配真实路径。本轮不安装或执行 systemd 单元。

## 未验证事项

本地双账号浏览器验收已完成，记录于[浏览器验收记录](changes/2026-09-29-user-pool-browser-acceptance.md)，覆盖登录、账号隔离、池复制、Trace/非Trace模拟、刷新、图表、筛选、CSRF原生下载请求和实际取消。该记录不证明公网反向代理、HTTPS/域名、生产容器或Gunicorn/worker systemd生命周期已经验证。主项目已移除旧Streamlit及授权旧数据，v5库迁移及首个管理员交互初始化完成，真实库登录/模拟/历史/Trace读取验收通过，详见[实施记录](changes/2026-09-24-user-pool-experiment.md)。
