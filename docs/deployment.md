# 部署指南

这份指南用于把抽奖模拟器部署到 Ubuntu 24.04 服务器，使用项目自带的 Docker Compose 和 Caddy。所有命令都在**服务器的 SSH 终端**执行，项目目录约定为 `/opt/lottery-simulator`。

| 你的情况 | 从这里开始 |
| --- | --- |
| 空服务器，第一次安装 | [首次安装](#首次安装) |
| 已有标准 Docker 部署，需要更新 | [版本更新](#版本更新) |
| 安装或升级报错、中途停止 | [故障处理](#故障处理) |
| 网站已运行，查看日志或备份 | [日常运维](#日常运维) |
| 自定义环境，需要逐步操作 | [手动安装](#手动安装)、[手动版本更新](#手动版本更新) |

本机开发见[本地使用手册](local-usage.md)，Windows 环境见[Windows＋WSL说明](windows-wsl-temporary.md)，网页操作见[页面指南](dashboard-guide.md)。

**验证范围：** 安装／升级相关的45项隔离检查已通过；完整新服务器安装、完整服务器升级和本轮正式 HTTPS 尚未实测。详细证据见文末[验证状态](#验证状态)。

## 首次安装

首次安装只用于没有项目数据的新环境。已有账号或网站时，转到[版本更新](#版本更新)，不要重新初始化。

### 准备服务器

准备好以下条件再开始：

- Ubuntu 24.04，以及有 `sudo` 权限的管理账号。
- 一个实际域名，A记录指向服务器公网 IPv4；没有可用 IPv6 时不设置 AAAA记录。
- 云安全组允许 TCP 80、443，且这两个端口未被其他服务占用。SSH端口只向管理地址开放，不开放8000、5173或数据库。
- 服务器能访问 GitHub、Docker镜像仓库、npm、PyPI和证书服务。

下面用 `lottery.example.com` 表示域名，使用时换成你的域名。无需另装 Nginx 或在服务器创建 Python 虚拟环境。

### 获取项目

先安装 Git，再下载完整项目。**仅在目标目录为空时执行：**

```bash
sudo apt update
sudo apt install -y git ca-certificates
sudo install -d -o "$(id -un)" -g "$(id -gn)" /opt/lottery-simulator
git clone --branch master --single-branch \
  https://github.com/donotwantorange/lottery_simulator.git \
  /opt/lottery-simulator
cd /opt/lottery-simulator
git log -1 --oneline
```

成功后，目录中应有 `docker-compose.yml`、`scripts/install.sh` 和 `frontend/`。目录非空时先检查内容，不要删除覆盖。

也可[下载完整 ZIP](https://github.com/donotwantorange/lottery_simulator/archive/refs/heads/master.zip)并解压到相同目录；ZIP没有Git历史，后续不能使用 `git pull` 更新。服务器只能下载已经发布到[GitHub仓库](https://github.com/donotwantorange/lottery_simulator)的代码。

### 运行安装脚本

```bash
cd /opt/lottery-simulator
bash scripts/install.sh
```

在终端按中文提示操作：验证sudo权限、选择是否使用腾讯云内网镜像、填写域名、设置管理员用户名和密码。输入密码时不显示字符是正常现象。

脚本会准备基础工具和Docker，生成应用密钥，构建前后端，建立v6数据库并启动服务。腾讯云内网镜像选项仅适用于腾讯云服务器。已有Docker软件源、冲突包或其他运行容器需要先人工核对，脚本不会替你卸载或停止它们。

脚本保留已有 `.env`；发现数据库、容器或本项目数据卷时会停止首次安装。安装中断后，按[故障处理](#故障处理)判断能否重跑，不通过删除数据绕过保护。不要使用 `curl | bash`。

### 确认启动并完成验收

```bash
sudo docker compose ps
sudo docker compose logs --tail=100 app caddy
```

预期 app 为健康状态，Caddy正常运行。浏览器打开 `https://你的实际域名`，使用刚创建的管理员登录。首次证书申请可能需要等待，结合日志判断。

接下来依次完成[上线验收](#上线验收)和[每日自动备份](#每日自动备份)，再开放日常使用。安装成功后无需执行附录中的手动安装。

## 版本更新

先确认旧版本的数据处理范围：

| 服务器当前版本 | 升级后的数据 |
| --- | --- |
| v5 | 仅迁入账号及登录限制，建立默认规则和池；旧池、实验配置、历史、Trace和会话不导入v6，旧库仍保留 |
| v6 | 保留账号和现有业务数据，执行需要的数据库迁移 |

升级期间网站会停止服务。安排维护窗口，通知用户停止提交新任务，等待任务完成或在网页取消并确认结束。固定原安装目录、Compose项目名、`.env`和所有持久卷。

### 脚本升级

适用于服务器本机的标准Docker部署：app和Caddy各一个，app健康，使用原项目命名卷。远程Docker、rootless、自定义挂载／网络、app公开8000端口、额外项目容器、停止或部分安装不适用，见[手动版本更新](#手动版本更新)。

**第一步：检查并记录旧版本。此时保留旧app和Caddy运行，升级脚本需要检查它们。**

```bash
cd /opt/lottery-simulator
git status --short
git rev-parse HEAD
sudo docker compose ps
```

保存旧提交号。`git status --short`没有输出才表示工作区干净；有修改先保留并处理，不能强制覆盖。建议维护前另存一份受控异机备份。

**第二步：获取新版。** Git安装执行：

```bash
git pull --ff-only origin master
```

拉取失败就停下处理。ZIP安装应先保存旧代码，再替换完整新版文件，保留原 `.env`、项目目录和数据；不要执行Git更新命令。

**第三步：核对新入口，再运行升级。**

```bash
ls scripts/install.sh scripts/upgrade.sh scripts/upgrade_probe.py
bash scripts/install.sh --help
bash scripts/install.sh --upgrade
```

缺文件或没有 `--upgrade` 帮助说明，表示尚未取得所需完整版本，不要继续。v5需输入 `ACCOUNTS` 确认只迁账号，所有升级需输入 `UPGRADE` 确认维护。

脚本依次暂停已有定时备份、停止网站入口、检查任务、冻结旧app并再次检查、制作私有备份。备份成功后才移除旧app、重建本项目网络，随后构建新版、迁移数据库并启动服务。它不删除原卷、不重置密码或密钥、不自动拉取代码或回滚。

记录脚本输出的备份目录：`/var/backups/lottery/<项目名>/upgrade-<时间>-<随机值>`。其中保存数据库快照、旧数据目录、旧前端、`.env`和容器配置，包含私密信息；仅管理员可访问，不放到网站目录或Git中。原备份卷也保留数据库快照。

**第四步：完成验收并恢复备份。**

先完成[上线验收](#上线验收)，重点验证原账号、小实验后紧接第二次实验、Trace和取消。v5升级需重新登录。再按[备份服务配置随升级更新](#备份服务配置随升级更新)检查原备份服务、实际执行备份，最后恢复定时备份。

如果脚本失败，保留输出的失败阶段与备份路径，转到[故障处理](#故障处理)。它不会自动恢复网站入口或定时备份。

## 上线验收

首次安装、升级和恢复后都使用以下清单。容器健康或首页能打开，只代表服务能响应。

- [ ] 域名证书可信，HTTP跳转HTTPS；登录、退出、刷新页面正常。
- [ ] 用管理员或原账号完成一次小实验，例如10抽×1轮并开启Trace，随后立即运行第二次实验，两次都正常完成。
- [ ] 两条历史都能重新打开，图表和计数正常，Trace能查看和下载；未开启Trace的任务明确提示没有过程明细。
- [ ] 提交一条足够长的任务，在执行中点击停止；确认任务取消、后台worker退出，没有残缺历史。
- [ ] 规则及角色池页面正常；使用测试账号核对规则复制、初始状态、赠送，以及两个普通用户之间的私有资源隔离。
- [ ] 前端页面直接访问及刷新正常；不存在的API路径返回404，不返回前端网页。
- [ ] 无活动任务时重启服务，账号和历史仍在。
- [ ] 备份成功；在隔离环境恢复副本后，登录、历史和小实验均正常。

验证抽数时分别比较主抽、赠送抽、总真实抽数、直接赠送数量和Trace事件数，不能把这些数字混作同一个口径。计数取决于实际规则与初始状态。

## 日常运维

### 查看状态与日志

```bash
cd /opt/lottery-simulator
sudo docker compose ps
sudo docker compose logs --tail=100 app caddy
```

排障时保留错误信息，但不要公开密码、`.env`、Cookie、数据库或完整Compose配置。

### 停止与重新启动

先停止新提交，等待任务结束，或在网页取消并确认worker退出。关闭网页不会取消任务；容器重启也不能保证任务继续运行。

停止服务：

```bash
sudo docker compose stop
```

重新启动：

```bash
sudo docker compose up -d
```

不要执行 `docker compose down -v`、清理项目卷或清空任务目录来解决问题，这些操作可能丢失数据。

### 备份

下面用于运行中的v6服务。v5应使用对应旧版路径，不能把旧库改名为v6。

```bash
sudo docker compose exec -T app python3 scripts/backup_db.py \
  /app/data/history_v6.sqlite3 \
  "/app/backups/lottery-v6-$(date +%F-%H%M%S).sqlite3"
```

成功标志是输出 `Backup integrity_check: ok`。备份包含账号、登录会话、规则、池、实验配置和已提交历史，不包含任务目录和临时导出目录。

将选定备份复制到宿主机，**替换下面的示例文件名**：

```bash
sudo install -d -m 700 /opt/lottery-private-backups
sudo docker compose cp \
  app:/app/backups/lottery-v6-YYYY-MM-DD-HHMMSS.sqlite3 \
  /opt/lottery-private-backups/
sudo chmod 600 /opt/lottery-private-backups/lottery-v6-YYYY-MM-DD-HHMMSS.sqlite3
```

备份含账号等私密数据，应再复制到受控异机位置，并安排容量检查和保留期限。同机备份无法防止整台服务器丢失。

### 每日自动备份

仅在尚未安装这项定时备份时使用本节。已有备份服务按下一节更新，保留自定义配置。

仓库示例假定项目位于 `/opt/lottery-simulator`，Docker位于 `/usr/bin/docker`。先核对这两个路径，再安装：

```bash
sudo install -m 644 deploy/lottery-backup.service /etc/systemd/system/lottery-backup.service
sudo install -m 644 deploy/lottery-backup.timer /etc/systemd/system/lottery-backup.timer
sudo systemctl daemon-reload
sudo systemctl start lottery-backup.service
sudo systemctl status lottery-backup.service
sudo journalctl -u lottery-backup.service -n 50 --no-pager
```

确认执行成功且日志有完整性检查通过，再启用每日调度：

```bash
sudo systemctl enable --now lottery-backup.timer
sudo systemctl list-timers lottery-backup.timer
```

一次性备份service执行后变为inactive是正常现象，以退出结果和日志为准。定时器按服务器时区每日运行，同一天再次运行会更新当天备份；不自动删除旧备份或异机复制。

### 备份服务配置随升级更新

升级脚本会暂停已有timer，但不会覆盖系统中已安装的服务配置。更新仓库文件也不会自动更新 `/etc/systemd/system/` 中的副本。

先检查当前配置和附加配置：

```bash
sudo systemctl cat lottery-backup.service lottery-backup.timer
```

核对工作目录、Docker路径和数据库路径。标准安装可备份旧service再安装新版；有自定义参数时应保留，并将数据库路径和备份前缀改为v6。

```bash
sudo install -d -m 700 /opt/lottery-private-backups
sudo cp /etc/systemd/system/lottery-backup.service \
  "/opt/lottery-private-backups/lottery-backup.service-before-$(date +%F-%H%M%S)"
sudo install -m 644 deploy/lottery-backup.service /etc/systemd/system/lottery-backup.service
sudo systemctl daemon-reload
sudo systemctl start lottery-backup.service
sudo systemctl status lottery-backup.service
sudo journalctl -u lottery-backup.service -n 50 --no-pager
```

确认业务及备份检查通过后，恢复原有timer：

```bash
sudo systemctl start lottery-backup.timer
sudo systemctl list-timers lottery-backup.timer
```

失败时保持timer暂停并排查。原来没有timer的部署不需要执行本节；需要新增时使用上一节。

## 故障处理

### 安装或升级中断

先记录报错阶段，查看容器状态与日志，不要马上重跑或删除卷。

| 中断情况 | 下一步 |
| --- | --- |
| 首次安装尚未创建容器、数据卷或数据库 | 处理原因后可重跑，原 `.env`会保留；以脚本实际检查为准 |
| 首次安装已有运行材料或已初始化一部分 | 按实际完成阶段手动恢复，首次安装器会拒绝重跑 |
| 升级时旧app仍在 | 核实app是否暂停、任务状态及已完成步骤；需要恢复时使用确认过的旧容器身份和旧配置，不能盲目用新版配置重建 |
| 升级时旧app已移除 | 使用记录的旧提交／镜像、卷映射和私有备份制定恢复步骤；先保存当前数据，不能仅回退代码或覆盖数据库 |
| v5升级已经生成部分v6材料 | 保留现场并核对导入进度；脚本拒绝自动覆盖或续跑，不删v6库绕过保护 |

升级失败会尝试解除本次暂停的旧app，但不会自动恢复Caddy入口或timer。数据库已迁移时，旧代码未必能读取新库。恢复操作见[恢复](#恢复)。

### 常见问题

| 现象 | 优先检查 |
| --- | --- |
| GitHub、镜像或依赖下载超时 | 网络、DNS、代理和对应仓库；Docker守护进程与终端可能使用不同代理 |
| Docker无法连接 | `sudo systemctl status docker --no-pager`，以及Docker日志 |
| 没有 `docker compose` 命令 | 是否安装 `docker-compose-plugin` |
| APT锁被占用 | 等待系统更新完成，不直接删除锁文件 |
| 构建被Killed | 内存、磁盘和系统日志 |
| 前端找不到default.json | 构建时须同时挂载frontend和configs，见[构建前后端](#构建前后端) |
| 代理网络冲突 | 调整[配套网络变量](#配置参考)，不删除其他项目网络 |
| app不健康 | app日志中的数据库迁移、权限或环境配置错误 |
| 证书报NXDOMAIN | 实际访问域名是否有正确A记录；仅配置www不能覆盖根域名 |
| HTTPS首页404 | `frontend/dist/index.html`是否存在；证书成功不代表网页构建成功 |
| 登录或CSRF 403 | 访问的HTTPS域名是否与 `.env`中的DOMAIN一致 |
| 历史突然为空 | 是否换了安装目录、Compose项目名或卷，不立即初始化新账号 |
| 备份失败 | app是否运行、systemd配置、日志及磁盘空间 |

域名排查命令中的占位文字需替换：

```bash
getent ahostsv4 你的实际域名
curl -I --connect-timeout 15 --max-time 20 https://你的实际域名
```

证书错误应修复解析、网络或可信链，不关闭TLS校验。镜像加速只针对相应镜像仓库，不会同时加速GitHub、npm和PyPI。

## 附录：手动操作

以下用于熟悉Docker的维护者逐步安装或排障。每块命令成功后才继续；脚本已完成的步骤不重复执行。

### 手动安装

先完成[服务器准备](#准备服务器)和[获取项目](#获取项目)。已有Docker时检查版本与其他业务；没有Docker时按[官方Ubuntu安装步骤](https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository)安装Engine、Buildx和Compose插件，避免覆盖已有软件源或卸载其他业务依赖。

基础工具和Docker检查：

```bash
sudo apt update
sudo apt install -y ca-certificates curl git openssl nano python3 iproute2
sudo docker version
sudo docker buildx version
sudo docker compose version
sudo docker pull hello-world
sudo docker run --rm hello-world
```

腾讯云服务器可参考[腾讯云镜像说明](https://cloud.tencent.com/document/product/213/8623)，在 `/etc/docker/daemon.json` 的 `registry-mirrors` 中添加 `https://mirror.ccs.tencentyun.com`。先备份原文件，保留其他字段；用 `sudo dockerd --validate --config-file=/etc/docker/daemon.json`验证后，安排维护重启Docker。该地址仅供腾讯云内网使用。

**创建环境文件。** 已有 `.env` 时保留密钥并核对内容；全新环境执行：

```bash
cd /opt/lottery-simulator
touch .env
chmod 600 .env
openssl rand -hex 48
nano .env
```

填写实际域名和刚生成的随机密钥：

```dotenv
DOMAIN=lottery.example.com
SECRET_KEY=替换为刚生成的随机值
```

域名不带协议、端口或路径。密钥不公开、不随重启重新生成。保存后执行下面的网络预检和构建。

### 网络预检

```bash
sudo docker compose config --quiet
sudo docker compose config --format json | sudo python3 scripts/check_proxy_network.py \
  --project "$(sudo docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')" \
  --docker "$(command -v docker)"
```

失败就停止，核对冲突或读取权限。完整Compose配置可能含密钥，不公开输出。

### 构建前后端

```bash
sudo docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/frontend:/work/frontend" -v "$PWD/configs:/work/configs:ro" \
  -w /work/frontend node:22-bookworm-slim sh -c 'npm ci && npm run build'
test -f frontend/dist/index.html && echo "前端构建完成"
sudo docker compose build app
sudo docker compose pull caddy
```

前端与configs的相对路径必须保留。使用项目锁文件，不在部署时随意升级依赖。已有Node >=22.12.0时，也可在本机执行 `npm --prefix frontend ci && npm --prefix frontend run build`。

### 初始化全新数据库和管理员

仅用于确认没有任何已有数据的空卷；v5转v6使用下一节，已有v6使用手动更新。

```bash
sudo docker compose run --rm app python manage.py migrate
sudo docker compose run --rm app python manage.py init_admin --username admin
sudo docker compose up -d --wait --wait-timeout 120
```

输入管理员密码，初始化会同时创建默认规则和池。提示已初始化时停止核对，不删库重试。启动后完成[上线验收](#上线验收)和备份配置。

### 手动版本更新

本节用于已有v6部署。自定义部署应先核对实际服务、挂载、项目名和配置；命令以本仓库两服务Compose为例，不能原样用于其他拓扑。

1. 进入维护窗口，停止新任务，等待或取消活动任务并确认worker退出。
2. 如有备份timer，停止它并确认正在执行的备份也已结束；完成[数据库备份](#备份)，保存 `.env`、旧代码版本、前端及卷映射。
3. 检查工作区，停止服务后获取新版：

```bash
git status --short
git rev-parse HEAD
sudo docker compose stop
```

保存修改及旧提交号、确认工作区干净后再执行 `git pull --ff-only origin master`。ZIP安装保存旧文件后替换完整新版，保留原环境和数据。

本轮网络布局有变化，需要重建本项目网络；确认只有预期项目服务后执行：

```bash
sudo docker compose down
```

命令不加 `-v`或 `--remove-orphans`，保留原命名卷。然后依次执行[网络预检](#网络预检)、[构建前后端](#构建前后端)，再运行：

```bash
sudo docker compose run --rm app python manage.py migrate
sudo docker compose up -d --wait --wait-timeout 120
```

不重复初始化管理员。完成上线验收、更新并验证备份服务后，恢复原有timer及日常访问。

### v5账号保留与v6切换

标准运行中的Compose部署优先使用[脚本升级](#脚本升级)。手动操作前先在隔离副本演练，并确认只迁账号和登录限制：旧池、实验、历史、Trace和会话不迁入。

安排维护、停止新请求与活动任务，确认没有删除中账号或未完成删除清单。使用旧版备份流程生成明确的v5快照，保留旧库和运行材料。停止旧服务后，按手动更新步骤准备新网络、配套代码与前端。

将选定快照放入新app可读取的私有备份卷；下面的 `selected-v5.sqlite3` 是需准备的文件，不会自动生成。确认目标路径是独立的 `history_v6.sqlite3`，没有已有v6业务，再执行：

```bash
sudo docker compose run --rm app python manage.py migrate
sudo docker compose run --rm app python manage.py import_v5_accounts --source /app/backups/selected-v5.sqlite3
sudo docker compose run --rm app python manage.py init_business_defaults
sudo docker compose up -d --wait --wait-timeout 120
```

导入会校验源版本、完整性、迁移状态、删除标记以及目标为空。重复导入会拒绝；不运行 `init_admin`，不将v5改名或配置为v6目标。验收原账号、默认规则和池，保留旧库直到确认恢复方案。

### 恢复

恢复前停止网站、worker和备份调度，另存当前数据库及相关运行材料，再选择明确的v6备份。核对代码版本、实际卷、文件属主和权限；禁止在数据库使用中覆盖，也不能混用旧WAL/SHM文件与恢复快照。

恢复后先检查 `PRAGMA integrity_check` 为 `ok`，再验证登录、历史与小实验写入，最后恢复访问和备份。迁到新服务器时账号已在备份中，不执行管理员初始化。

数据库备份不恢复任务目录。若旧任务状态与恢复后的历史不一致，保留现场核对，不清空整个data目录。涉及覆盖真实数据库时，应按确认后的路径制定命令，本指南不提供可直接误覆盖的通用命令。v5快照只能作为账号导入来源，不能当作v6恢复文件。

## 配置参考

### 组件与数据位置

| 内容 | 默认位置 |
| --- | --- |
| 对外入口 | Caddy的80／443端口，提供HTTPS、静态页面和API代理 |
| 后端 | app的内部8000端口，不向宿主机公开 |
| 网页产物 | 宿主机 `frontend/dist/`，只读挂载到Caddy `/srv` |
| 数据库 | app内 `/app/data/history_v6.sqlite3` |
| 任务／临时导出 | app内 `/app/data/jobs_v6/`、`/app/data/exports_v6/` |
| 数据／备份卷 | `lottery_data`、`lottery_backups`；备份挂载在 `/app/backups/` |
| 证书卷 | `caddy_data`、`caddy_config` |

实际卷名带Compose项目前缀。容器路径不是宿主机同名目录；不要直接编辑Docker内部卷文件。当前是单机SQLite部署，不让多台服务器共享同一数据库与任务目录。

### 环境变量与代理网络

通常只需在 `.env` 填写 `DOMAIN`和 `SECRET_KEY`。Compose会设置生产模式、允许域名、CSRF来源、v6数据路径与可信代理。

网络冲突时，配套调整以下四项，不能只改一个地址：

| `.env`变量 | 默认值 | 要求 |
| --- | --- | --- |
| `LOTTERY_PROXY_SUBNET` | `172.30.96.0/24` | 不与现有Docker网络及主机路由重叠 |
| `LOTTERY_CADDY_IP` | `172.30.96.2` | 子网内固定地址，独占给Caddy |
| `LOTTERY_PROXY_DYNAMIC_RANGE` | `172.30.96.128/25` | 子网内动态范围，排除Caddy并留有app地址 |
| `LOTTERY_PROXY_GATEWAY` | `172.30.96.1` | 子网内网关，不占用Caddy、网络或广播地址 |

app仅连接内部backend网络；Caddy还连接可出站的默认网络。app只信任Caddy的精确地址，不将整段私网设为可信代理。添加CDN或多层代理时须重新设计可信链。

前后端共用HTTPS域名，`/api`和`/api/*`由后端处理，其他页面支持前端路由刷新。生产Cookie要求HTTPS，不提供公网IP＋HTTP登录配置。`VITE_*`会进入公开前端文件，不能存放密钥。

非Compose部署需自行适配生产变量、请求分流、文件权限和worker生命周期，不照搬容器路径。可参考[应用配置](../webapp/settings.py)及[Compose文件](../docker-compose.yml)。

## 验证状态

截至2026-10-06，当前可确认的范围如下；历史详情保存在修改记录中，不作为在线状态监控。

| 范围 | 结果与限制 |
| --- | --- |
| 本地v6及可靠性修复 | 已合并，本机原账号连续实验、Trace及取消验收通过；不是服务器上线证明 |
| 业务回归 | 记录有后端271项、前端65项通过；后续CSS经构建和浏览器复验，实际版本边界见[修复记录](changes/2026-10-02-v6-runtime-reliability-fixes.md) |
| 安装与升级 | 提交前45项隔离检查通过，Shell语法通过；旧v5验证器和Docker暂停／复制／移除有独立探针记录，见[升级记录](changes/2026-10-06-compose-upgrade.md) |
| Docker／Caddy拓扑 | 本地代理来源、来源限流、固定地址重建和临时证书HTTPS已验证；可信公网HTTPS尚有缺口 |
| 完整服务器部署 | 用户曾确认旧版手动部署成功；新版首次安装、完整升级、正式证书及生产备份恢复仍需实机验收 |

已提交代码、隔离测试通过和服务启动成功，分别对应不同阶段。部署者应保留本次服务器版本、备份位置、实际步骤及上线验收结果。
