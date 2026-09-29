# 部署接口与运维说明

本文记录当前 Django＋React 实现对应的生产接口，不表示已在真实服务器部署或验收。生产需要 HTTPS 反向代理、静态前端服务、Gunicorn Web 服务和本机任务 worker；本次不连接服务器、不启动公网服务。

## 组件与请求分流

- `frontend/dist/`：由 Vite 构建的静态资源。生产 Web 服务器提供静态文件；SPA 页面路径回退到 `index.html`。
- `/api/`：转发到 `webapp.wsgi:application` 对应的 Gunicorn 服务。API 路径不能回退到前端 HTML。
- 模拟任务：由 Django 接受后在独立 worker 进程执行。不要在 HTTP 请求里执行模拟；不要因 Web 服务重启而清理或误杀已接受的任务。
- SQLite：默认 `data/history_v5.sqlite3`，任务状态和导出临时目录分别为 `data/jobs_v5/`、`data/exports_v5/`。三个位置均需为服务账号可写的私有持久目录。

本地开发时 Vite 在 `127.0.0.1:5173` 提供网页，并把 `/api` 代理至 `127.0.0.1:8000`。生产由反向代理保证浏览器只使用同一个 HTTPS 主机；不需要 CORS。前端构建变量 `VITE_*` 会进入公开资源，绝不能放密钥、数据库路径凭据或其他私有值。

## 生产配置要求

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

仓库的 Docker Compose 接口由 `app` 和 `caddy` 两个服务组成。`.env` 至少提供 `DOMAIN` 和高熵 `SECRET_KEY`。发布前安装锁文件依赖并构建前端：`npm --prefix frontend ci && npm --prefix frontend run build`；随后执行 `docker compose config --quiet` 检查配置，再按维护流程迁移目标数据库。`frontend/dist/` 以只读目录挂载给 Caddy。`app` 只在内部网络监听8000并由 Gunicorn 提供 WSGI；只有 Caddy发布80/443。Caddy把裸 `/api` 及 `/api/*` 转发到 Gunicorn，其余请求从 `frontend/dist/` 服务静态资源并将前端路径回退到 `index.html`；API不存在的路径仍由 Django 返回404，不会回退前端页面。Vite带内容哈希的 `/assets/*` 设置一年 immutable 缓存，`index.html` 设置 no-cache；私有 API 响应不应被共享缓存。生产不运行 Django `runserver`、Vite dev 或 Vite preview。

镜像以 `0700` 创建数据库、任务、导出和备份目录，容器用户为非root服务账号。Gunicorn使用2个gthread worker、每进程4个请求线程、120秒超时；每个WSGI进程默认只有1个并发导出槽，因此单容器最多两个长下载同时进行，其余线程仍可处理控制请求。导出槽是进程内限制，不是跨进程全局队列。改动 Django 配置、代码或依赖后按服务管理器重启 Web 服务；重启 Web 不应自动删除任务目录或终止已接受 worker。更新前确认进程管理方式能分别管理 Web 和 worker。完整停机/维护应先停止接收新任务，再等待或明确取消 worker，最后停止 Web。

## 数据库与备份

本版本使用 Django migration 管理 v5 schema。迁移前先验证目标 `LOTTERY_DB_PATH` 是预期的 v5 路径；不要将新版本指向旧 Streamlit 数据库，也不要自动迁移旧历史。任务14尚未完成真实切换，因此不要把下方接口当作旧数据清理许可。

备份脚本可对运行中的 SQLite 源库执行在线备份：

```bash
python3 scripts/backup_db.py /srv/lottery/data/history_v5.sqlite3 /srv/lottery/backups/lottery-v5-$(date +%F-%H%M%S).sqlite3
```

备份包含账号、密码哈希、会话、角色池、配置和已提交历史。它不包含 `jobs_v5/` 或 `exports_v5/`。脚本成功时输出 `Backup integrity_check: ok`，目标文件权限设置为 `0600`。备份目录应限制为服务/运维账号可访问，并复制到受控异机位置；不得放入静态网站目录或提交 Git。

恢复前停止 Web、worker 和定时备份，保存当前数据库副本，再恢复明确选定的 v5 备份。检查 `PRAGMA integrity_check` 为 `ok`，启动后验证账号登录、历史读取和小型模拟写入。恢复不会回滚或恢复任务目录；若任务状态与恢复后的数据库不一致，先保留目录并调查，不能递归清理数据目录。

仓库提供的 `deploy/lottery-backup.service` 与 `.timer` 是 systemd 备份接口示例，假设 Docker Compose 服务名 `app` 和容器路径 `/app/data`、`/app/backups`。它们已与当前 Compose 配置对齐，使用 `history_v5.sqlite3` 与 `lottery-v5-` 前缀；用于非 Compose 的本机 Gunicorn 部署时需由维护者适配真实路径。本轮不安装或执行 systemd 单元。

## 未验证事项

本地双账号浏览器验收已完成，记录于[浏览器验收记录](changes/2026-09-29-user-pool-browser-acceptance.md)，覆盖登录、账号隔离、池复制、Trace/非Trace模拟、刷新、图表、筛选、CSRF原生下载请求和实际取消。该记录不证明公网反向代理、HTTPS/域名、生产容器、Gunicorn/worker systemd 生命周期或真实数据切换已经验证。旧 Streamlit 入口及依赖已从本工作树移除；旧数据仍留在原稳定目录。
