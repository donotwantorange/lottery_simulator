# Linux 公网部署与运维

## 范围与前提

适用于个人白名单使用的单实例 Streamlit 仪表盘。服务器需要 Linux、Docker Engine、Docker Compose v2、systemd，以及可管理的公网域名。本文不自动安装系统软件。

部署目录以 `/opt/lottery-simulator` 为例；若位置不同，所有 `cd` 和备份 service 的 `WorkingDirectory` 都必须改成实际目录。以下命令在服务器上的项目根目录执行。Docker 命令需要有 Docker 权限的运维账号；该权限等价于高权限，不授予不可信账号。

✅ 部署接口已实现、静态合同已验证：配置固定生产/OIDC，只有 Caddy 发布 80/443，且 Caddyfile 声明 `Strict-Transport-Security: max-age=31536000; includeSubDomains`。按用户最新范围，本轮只完成本地功能，服务器实际部署和测试暂缓。⚠️ 当前开发环境没有 Docker/Caddy，镜像构建、Compose 官方解析和运行、卷权限、自动证书、HSTS 实际响应与公网 OIDC 均为“服务器现场未验”；下面是未来部署时执行的步骤，不是本轮成功记录。

## 1. 域名、端口和认证

1. 为域名设置指向服务器公网 IPv4 的 DNS A 记录。只有实际可达的 IPv6 才设置 AAAA；错误的 AAAA 会导致部分客户端或证书校验失败。
2. 云安全组和主机防火墙放行 TCP 80、443；保持 SSH 管理通道。不要向公网放行 8501，也不要给 Compose 的 app 增加 `ports`。
3. 在 OIDC 提供商注册 Web 应用，回调地址精确设为 `https://${DOMAIN}/oauth2callback`（将 `${DOMAIN}` 换成真实域名，不保留占位符）。取得 client ID、client secret 和 HTTPS discovery metadata URL；提供商需要返回允许登录用户的 `email` claim。

项目根目录新建 `.env`（不要提交）：

```dotenv
DOMAIN=lottery.example.com
ALLOWED_EMAILS=owner@example.com,another@example.com
```

只有这两个变量从 `.env` 注入。`DOMAIN` 仅填主机名，不带协议、路径或端口。白名单是逗号分隔的完整邮箱，代码规范化大小写并精确匹配；缺少白名单会拒绝访问。Compose 的 `${...:?}` 也会拒绝缺少或为空的变量。不要通过修改 Compose 关闭生产认证。

创建私密 OIDC 配置：

```bash
cd /opt/lottery-simulator
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
chmod 600 .env .streamlit/secrets.toml
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

把上一步生成的随机值填入 `cookie_secret`，用编辑器设置 `.streamlit/secrets.toml`。生产启动会拒绝缺失、空白或 UTF-8 字节数少于 32 的 `cookie_secret`，并拒绝缺失或空白的 OIDC 必填字段；长度检查不能替代使用高熵随机值：

```toml
[auth]
redirect_uri = "https://lottery.example.com/oauth2callback"
cookie_secret = "替换为随机长密钥"
client_id = "替换为提供商客户端ID"
client_secret = "替换为提供商客户端密钥"
server_metadata_url = "https://identity.example.com/.well-known/openid-configuration"
expose_tokens = []
```

该 TOML 不展开环境变量，回调必须与真实域名和提供商注册值完全一致。不要在日志、截图或提交中泄露密钥。容器以 UID 10001 运行，因此首次启动前赋予该 UID 文件读取权限；以后编辑需使用有权限的管理员：

```bash
sudo chown 10001:10001 .streamlit/secrets.toml
sudo chmod 600 .streamlit/secrets.toml
```

secrets 只读挂载，不进入镜像。`.env`、数据库、备份、私钥以及 `*.pem`、`*.key`、`*.crt`、`*.cer`、`*.p12`、`*.pfx` 证书/密钥文件均由 `.dockerignore` 排除；默认数据和备份路径也由 `.gitignore` 排除。证书实际保存到 Docker 命名卷，不在源码目录中。

## 2. 构建与启动

```bash
docker compose config --quiet
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 app caddy
```

检查解析结果：app 无宿主机端口；只有 Caddy 映射 `80:80`、`443:443`；app 的 `APP_ENVIRONMENT=production`、`APP_AUTH_MODE=oidc`。不要将解析结果分享给无关人员（其中含白名单）。Caddy 等待 app 健康后启动，自动管理 HTTPS 并代理 `app:8501`；无需关闭 Streamlit 的 XSRF/CORS 防护。

镜像固定 `python:3.12.14-slim-trixie`，Caddy 固定 `caddy:2.11.4-alpine`，Python 依赖来自 `requirements.txt`。`EXPOSE 8501` 仅是镜像元数据，不发布端口。

持久化路径：

| 命名卷 | 容器路径 | 内容 |
| --- | --- | --- |
| `lottery_data` | app `/app/data` | `lottery_v3.sqlite3`、任务文件 `jobs_v3/` |
| `lottery_backups` | app `/app/backups` | SQLite 备份 |
| `caddy_data` | Caddy `/data` | 证书、私钥及 ACME 状态 |
| `caddy_config` | Caddy `/config` | Caddy 持久配置 |

实际卷名会带 Compose 项目前缀。升级和恢复时保持同一项目目录/项目名，避免误用新空卷。不要执行 `docker compose down -v`，它会删除持久卷。

Compose 显式设置 `LOTTERY_DATA_DIR=/app/data`、`LOTTERY_DB_PATH=/app/data/lottery_v3.sqlite3`。页面和 worker 共用这个数据库路径，定时备份也使用它。非容器开发未设置 `LOTTERY_DB_PATH` 时使用 `LOTTERY_DATA_DIR/history_v3.sqlite3`，任务状态使用同目录下的 `jobs_v3/`。旧的 `lottery.sqlite3`（包括旧 `data/history.sqlite3` 或已存在卷中的 `/app/data/lottery.sqlite3`）不读取、不迁移、不覆盖，也不自动删除；需要保留它时请单独备份。自定义数据库路径时，父目录需已存在且可写。

## 3. 健康检查和公网验收

```bash
docker compose exec -T app python3 -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=5); print(r.status, r.read().decode())"
docker compose logs --since=10m app caddy
curl -I http://lottery.example.com
curl -I https://lottery.example.com
```

把 curl 域名替换为 `.env` 中的真实域名。预期本地 health 返回 `200 ok`，公网 HTTP 跳转 HTTPS，HTTPS 证书有效，且 HTTPS 响应包含 `Strict-Transport-Security: max-age=31536000; includeSubDomains`。⚠️ health 只证明 Streamlit 服务存活，不证明脚本成功渲染、数据库可写、登录正常或 Caddy 在服务器上实际发送 HSTS。

未来部署时必须使用公网域名进行人工验收（本轮暂缓，不作为本地完成条件）：

- 无登录时只有登录入口；OIDC 回调正确，白名单用户可以访问，白名单外用户不能访问，退出后受保护操作不可用。
- 登录后运行小模拟，刷新/新会话可查历史，以确认持久数据库已初始化（未首次登录时不会创建库）。
- 桌面与窄屏分别检查结果页六个区域（总览、六星构成、具体角色、附赠奖励、保底统计、Trace）完整可见；在主池、赠送、总计之间切换，并展开各区域对应的数值表；历史快照不包含概率曲线时显示明确提示。
- 用 Tab/Shift+Tab 按视觉顺序遍历侧栏、图表数值展开、下载、历史筛选/选择/复用/删除；每一步焦点均可见，Enter/Space 可操作。
- 删除第一次点击只出现确认，取消后记录仍在，独立“确认删除”后才移除。用本次创建的验收记录，不删除真实重要历史。

⚠️ 单元测试和 AppTest 不能替代浏览器布局、键盘焦点、DNS、证书和真实 OIDC 验收。应把实际观察逐项补记到变更记录。

## 4. 在线备份和每日定时任务

先完成一次登录和模拟，确认 `/app/data/lottery_v3.sqlite3` 存在。手动在线备份：

```bash
docker compose exec -T app python3 scripts/backup_db.py /app/data/lottery_v3.sqlite3 /app/backups/lottery-v3-$(date +%F).sqlite3
```

脚本只读打开源库，使用 SQLite 在线 backup API，包含已提交 WAL 数据；创建目标父目录，拒绝同一路径/符号链接/硬链接别名，并检查目标 `PRAGMA integrity_check`。退出码为 0 且输出 `Backup integrity_check: ok` 才算成功。非零退出后目标可能已存在或已覆盖，不可使用该次输出恢复；同日命令会覆盖同名备份，重要操作前使用带时分秒的独立文件名。该脚本只备份 SQLite 历史，不备份任务文件、OIDC secrets 或证书。

安装 systemd 定时任务前，编辑项目内 `deploy/lottery-backup.service`，把 `WorkingDirectory=/opt/lottery-simulator` 改为真实部署路径，并用 `command -v docker` 确认 `/usr/bin/docker` 是否正确。service 中 `date +%%F` 的双百分号是 systemd 转义，手工终端命令用单百分号。

```bash
sudo install -m 644 deploy/lottery-backup.service /etc/systemd/system/lottery-backup.service
sudo install -m 644 deploy/lottery-backup.timer /etc/systemd/system/lottery-backup.timer
sudo systemctl daemon-reload
sudo systemctl enable --now lottery-backup.timer
sudo systemctl start lottery-backup.service
sudo systemctl status lottery-backup.timer lottery-backup.service --no-pager
sudo systemctl list-timers lottery-backup.timer --all
sudo journalctl -u lottery-backup.service -n 50 --no-pager
```

timer 按服务器时区每日执行，`Persistent=true` 在错过计划后补执行；容器未运行时备份会失败，需监控 service 日志。没有自动保留/清理策略：检查磁盘空间，并将已校验备份复制到受控异机存储。命名卷不能抵御整机/磁盘丢失：

```bash
install -d -m 700 backups
docker compose cp app:/app/backups/lottery-v3-$(date +%F).sqlite3 backups/
chmod 600 backups/*.sqlite3
```

使用你已有的加密传输/存储流程做异机复制；本文不配置外部存储，不自动删除旧备份。

## 5. 停机恢复

恢复会替换当前历史。先选择已知成功的备份（下面日期为示例，必须替换），暂停定时器，停止 app，保留当前库的独立备份，再恢复。`docker compose run` 复用命名卷，以镜像的非 root 用户运行脚本，不启动 Streamlit；不要在 app 运行时直接复制 SQLite 文件或删除 WAL 文件。

```bash
cd /opt/lottery-simulator
sudo systemctl stop lottery-backup.timer
sudo systemctl stop lottery-backup.service
docker compose stop app
docker compose run --rm --no-deps app python3 scripts/backup_db.py /app/data/lottery_v3.sqlite3 /app/backups/pre-restore-v3-$(date +%F-%H%M%S).sqlite3
docker compose run --rm --no-deps app python3 scripts/backup_db.py /app/backups/lottery-v3-2026-09-14.sqlite3 /app/data/lottery_v3.sqlite3
```

每条备份/恢复命令必须检查退出码；任何一步失败就停下，不要继续启动服务。首次空库恢复可以跳过不存在源库的 pre-restore 步骤；不要跳过现有库的保护备份。

```bash
docker compose run --rm --no-deps app python3 -c "import sqlite3; c=sqlite3.connect('file:/app/data/lottery_v3.sqlite3?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchall()); print(c.execute('SELECT count(*) FROM simulation_runs').fetchone()); c.close()"
docker compose up -d app
docker compose ps
sudo systemctl start lottery-backup.timer
```

校验输出必须是 `[('ok',)]`，历史数量须符合所选快照；重新登录检查历史/Trace，并运行一个小模拟验证恢复后仍可写。备份不会恢复未完成任务；若有旧任务状态影响运行，先保留 `jobs_v3/` 并调查，不要批量清理数据目录。⚠️ 当前已在临时真实 SQLite 上验证恢复及继续写入，但容器卷上的停机恢复仍须现场验证。

## 6. 镜像升级与按 Git 提交回滚

升级前记录当前已部署提交，取一个明确名称，避免“回滚到最新”这种不确定目标：

```bash
git status --short
git tag deployment-before-upgrade-2026-09-14 HEAD
docker compose exec -T app python3 scripts/backup_db.py /app/data/lottery_v3.sqlite3 /app/backups/pre-upgrade-v3-$(date +%F-%H%M%S).sqlite3
```

先处理工作区中已有修改；不要覆盖它们。如果这个 tag 已存在，选一个新的明确名称。获取并切换到已经审查的目标提交，例如先 `git fetch --all`，再 `git switch --detach <目标提交>`（替换尖括号参数）。保持部署目录与卷项目名不变，再运行：

```bash
docker compose build --pull app
docker compose pull caddy
docker compose up -d
docker compose ps
docker compose logs --tail=100 app caddy
```

重复健康、登录、历史读写检查。不兼容 schema 不会被旧版 repository 静默改写；如果升级包含数据库迁移，回滚代码之外还需要按上一节恢复升级前兼容备份。

回滚到上面命名的提交：

```bash
docker compose stop app
git switch --detach deployment-before-upgrade-2026-09-14
docker compose build app
docker compose up -d
docker compose ps
```

重新验证 HTTPS/OIDC、历史与新模拟；失败时保留日志和当前库，不执行 `git reset --hard` 或删除卷。固定版本降低漂移，但并非完整镜像可重复构建证明；本轮不进行额外 SHA/镜像摘要核验。
