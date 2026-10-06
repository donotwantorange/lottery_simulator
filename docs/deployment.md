# 部署指南与运维说明

本指南适用于新版 Django＋React 的单机部署。先准备服务器并获取项目，再选择手动安装或可选脚本安装；服务启动后统一按验收清单验证，后续查看运维与备份章节。

截至2026-10-01，用户确认现有腾讯云服务器曾通过手动指令部署旧版。该事实不代表当前v6界面、接口或数据升级已在线验收。自动安装脚本尚未实机测试。

日常本机开发见[本地使用手册](local-usage.md)，网页操作见[网页页面指南](dashboard-guide.md)，项目介绍见[README](../README.md)。

| 你要做什么 | 阅读入口 |
| --- | --- |
| 在空服务器安装v6 | [准备服务器](#准备服务器) → [获取项目](#获取项目) → [手动安装](#手动安装) |
| 了解自动安装脚本（尚未实机测试） | [可选交互式安装](#可选方式交互式安装) |
| 保留v5账号并建立v6 | [v5账号保留与v6切换](#v5账号保留与v6切换) |
| 已经部署，查看状态或更新 | [日常运维](#日常运维) |
| 备份、恢复或迁移旧服务器数据 | [备份恢复与迁移](#备份恢复与迁移) |
| 遇到报错 | [常见问题](#常见问题) |
| 查看配置及验证范围 | [配置参考](#配置参考)、[验证状态](#验证状态) |

## 准备服务器

### 系统与目录

以下假设使用全新 Ubuntu 24.04 服务器、具有 sudo 权限的普通管理账号，以及一个可配置 DNS 的域名。采用仓库的 Docker Compose＋Caddy，不另装 Nginx、Python 虚拟环境；前端用临时 Node 容器构建。

项目固定放在 `/opt/lottery-simulator`，与备份服务配置一致。本教程初始化空 v6 数据库；如需保留v5账号，按[v5账号保留与v6切换](#v5账号保留与v6切换)操作，不运行 `init_admin`。旧池、实验、历史和会话不会导入。当前方案是单机部署，不要让多台服务器直接共享 SQLite 和任务目录。

### 域名与端口

- 将实际域名（示例 `lottery.example.com`）的 A 记录指向服务器公网 IPv4；无可用 IPv6 时不要配置 AAAA。
- 云安全组开放 TCP 80、443；SSH 端口只允许管理地址访问。
- 确保 80、443 没有被其他服务占用。不开放 8000、5173 或数据库。
- 服务器需能访问 GitHub、Docker 镜像仓库、npm、PyPI 和证书服务。

Caddy 在条件满足时自动申请和续期证书，见[Caddy 官方说明](https://caddyserver.com/docs/automatic-https)。Docker 发布端口可能绕过部分 UFW 规则，应同时检查云安全组，见[Docker 防火墙说明](https://docs.docker.com/engine/install/ubuntu/#firewall-limitations)。

## 获取项目

项目下载入口：

- [GitHub 仓库](https://github.com/donotwantorange/lottery_simulator)
- [新版 master 分支](https://github.com/donotwantorange/lottery_simulator/tree/master)
- [直接下载 master ZIP](https://github.com/donotwantorange/lottery_simulator/archive/refs/heads/master.zip)

如果选择 Git 克隆，而服务器尚无 Git，先安装下载所需的工具：

```bash
sudo apt update
sudo apt install -y git ca-certificates
```

服务器部署建议使用下面的 `git clone`，方便后续更新。ZIP 适合手动下载查看，不包含 Git 历史，解压后不能直接执行本文的 `git pull` 更新步骤。

仅在目标目录尚未安装项目时执行：

```bash
sudo install -d -o "$(id -un)" -g "$(id -gn)" /opt/lottery-simulator
git clone --branch master --single-branch \
  https://github.com/donotwantorange/lottery_simulator.git \
  /opt/lottery-simulator
cd /opt/lottery-simulator
git log -1 --oneline
```

使用新版 `master`，保留 `old_Streamlit` 作为旧版参考。目录非空时先检查，不要删除覆盖。ZIP 下载后需将完整项目放到约定目录；后续 Git 更新命令仅适用于克隆安装。

选择脚本安装前检查 `scripts/install.sh` 是否存在。脚本已包含在master提交 `a20a893` 中；2026-09-30本地保存的 `origin/master` 也指向该提交，本次未联网核查GitHub。脚本尚未实机测试；文件存在或代码已提交不等于安装流程已实测。

**后续项目命令均在 `/opt/lottery-simulator` 执行。** 固定目录和 Compose 项目名，避免换名后连接到另一组空卷。

## 可选方式：交互式安装

该脚本用于首次安装，已有隔离流程检查记录，但尚未进行实机安装测试。下载完整新版 master 项目并进入项目目录后，可以按中文提示执行安装流程：

```bash
bash scripts/install.sh
```

先按[获取项目](#获取项目)下载 ZIP 或克隆；脚本必须随完整项目运行。它会定位自己的项目目录，无需逐条输入后续构建和启动命令。普通管理账号会提示 sudo 验证，也支持 root。

脚本安装所需基础工具；未安装 Docker 时按 Ubuntu 24.04 官方软件源安装，已有 Docker 则验证 Engine、Buildx、Compose。按提示选择腾讯云内网镜像加速、填写域名和首个管理员用户名，密码由初始化命令交互输入。脚本自动生成应用密钥，构建前后端、迁移数据库并启动服务。

域名解析和云安全组仍需先在腾讯云控制台完成。脚本不自动配置 DNS、安全组或定时备份；启动后按[上线验收](#上线验收)验证，并按后面的备份章节设置定时备份。

运行边界：

- 本安装目录已有运行容器时直接显示状态并退出；已成功部署的网站不需要再安装。日常更新使用维护章节。
- `.env` 已存在则保留，不换域名或密钥；发现已有数据库、容器（含停止状态）或本项目数据卷时，首次安装脚本停止，不自动跳过初始化后继续部署。不删除数据库、卷或任务。
- 安装器会在构建和数据库操作前检查代理后端子网与现存 Docker 网络、主机路由；无法读取或发现重叠时停止。默认子网为 `172.30.96.0/24`、Caddy 地址为 `172.30.96.2`，需要调整时在首次安装前设置 `.env` 的 `LOTTERY_PROXY_SUBNET` 、`LOTTERY_CADDY_IP`、`LOTTERY_PROXY_DYNAMIC_RANGE` 与 `LOTTERY_PROXY_GATEWAY`，动态范围必须在子网内、排除 Caddy 固定地址并留有 app 地址；默认动态范围为 `172.30.96.128/25`，防止先启动的 app 占用代理地址。默认显式网关为 `172.30.96.1`，需在子网内且不能占用 Caddy、网络或广播地址。
- 选择配置镜像时，若 Docker 中存在其他运行容器，安装脚本会退出，不停止这些容器；已有 Docker 软件源或冲突包需要手动确认。
- 任一步失败即停止并显示步骤。尚未创建数据卷/数据库/容器时，可处理错误后重跑并保留`.env`；一旦留下这些运行材料，重跑会被已有安装保护阻止。先核对实际状态与备份，再按手动部署或升级步骤恢复，不删除数据卷来绕过检查。2026-10-02隔离测试已复现迁移或管理员初始化失败后的这一边界。
- 结束只代表启动命令完成；HTTPS、登录、模拟、Trace 和恢复仍须按清单验证。该脚本尚未在全新服务器实机验收。

脚本成功后直接进入[上线验收](#上线验收)，不再重复下面的手动安装。

## 手动安装

仅在不使用安装脚本，或需要逐步排障时执行本节。以下步骤共用前面的服务器准备和项目目录；已初始化的数据库不要再次执行管理员初始化。

### 安装 Docker 和基础工具

以下命令在服务器 SSH 终端执行，不是在本机电脑执行；适用于本文约定的 Ubuntu 24.04。按[Docker 官方 Ubuntu 安装文档](https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository)使用官方 apt 仓库，不使用远程一键安装 Docker 的脚本。逐块执行，出现错误先停下处理。

#### 1.1 检查系统和已有安装

```bash
cat /etc/os-release
dpkg --print-architecture
sudo -v
command -v docker
dpkg -l docker-ce docker.io docker-compose docker-compose-v2 podman-docker containerd containerd.io runc
```

确认系统为 Ubuntu 24.04（代号 `noble`），架构通常为 `amd64` 或 `arm64`。`sudo -v` 验证当前账号有管理权限；输入密码时终端不显示字符是正常的。

全新服务器找不到 docker、部分包显示未安装属正常情况。若已有 Docker，先执行 `sudo docker version`、`sudo docker compose version`、`sudo docker ps -a`，检查版本、来源及现有容器，不能直接卸载。发行版自带的 `docker.io`、旧 Compose、`podman-docker` 或现有 `containerd/runc` 可能与官方包冲突；先确认没有其他业务或 Kubernetes 依赖，再按官方文档处理实际冲突包。本文不自动删除任何旧容器、卷或软件。

#### 1.2 安装基础工具

```bash
sudo apt update
sudo apt install -y ca-certificates curl git openssl nano
```

- `ca-certificates`：验证 HTTPS 服务器证书。
- `curl`：下载 Docker 官方签名密钥。
- `git`：下载代码及后续更新。
- `openssl`：生成应用随机密钥。
- `nano`：编辑 `.env` 等文本配置；使用熟悉的编辑器也可以。

`apt update` 更新软件包索引，不是升级整台服务器的所有软件。若软件源或网络报错，先解决再继续，不要关闭证书校验。

#### 1.3 添加 Docker 官方签名密钥

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

该文件是软件仓库的公开签名密钥，不是你的账号密码。APT 使用它校验软件包来源。

#### 1.4 添加官方软件源

以下整块复制执行，包括最后单独一行 `EOF`。仅用于首次配置；已有 Docker 软件源时先检查，避免重复定义或覆盖定制源。

```bash
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
```

命令自动读取 Ubuntu 代号和处理器架构。若终端持续显示 `>`，通常是尚未输入结束行 `EOF`；它前面不能有空格。若提示签名、源冲突或发行版不支持，不要跳过验证。

#### 1.5 安装 Docker Engine、构建和 Compose 插件

```bash
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

Engine 和 CLI 负责运行及管理容器，containerd 是运行时，Buildx 用于镜像构建，Compose 用于按项目配置启动多个服务。本项目使用 `docker compose`（中间有空格），不是旧版 `docker-compose` 命令。

#### 1.6 启动 Docker 并检查插件

```bash
sudo systemctl enable --now docker
sudo systemctl is-active docker
sudo docker version
sudo docker buildx version
sudo docker compose version
```

成功标准：服务显示 `active`，Docker 能显示 Client 和 Server 信息，两个插件均输出版本。腾讯云大陆服务器建议先完成下一小节的镜像配置，再执行镜像拉取检查。

后续统一使用 `sudo docker`，不必加入高权限 docker 用户组，也不要用 `chmod 666 /var/run/docker.sock` 解决权限错误。

#### 1.7 腾讯云服务器：配置 Docker 镜像加速

腾讯云大陆服务器可在首次拉取镜像前配置腾讯云官方加速地址 `https://mirror.ccs.tencentyun.com`。该地址只支持腾讯云内网访问，应在腾讯云服务器上配置，不适用于普通外网电脑。来源：[腾讯云镜像源说明](https://cloud.tencent.com/document/product/213/8623)。

`Unable to find image ... locally` 仅表示本机没有镜像；后续的连接超时才是下载失败。无需因此重装 Docker。

**第一步：备份已有配置，再编辑。** 以下命令仅在文件存在时备份，不覆盖原文件：

```bash
sudo mkdir -p /etc/docker
if sudo test -f /etc/docker/daemon.json; then
  sudo cp -a /etc/docker/daemon.json \
    "/etc/docker/daemon.json.bak-$(date +%Y%m%d-%H%M%S)"
fi
sudo nano /etc/docker/daemon.json
```

文件为空时填写：

```json
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com"
  ]
}
```

已有配置时，保留其他字段，只添加或修改 `registry-mirrors`；不要粘贴第二个完整 JSON 对象，也不要重复同名字段。JSON 不支持注释或末尾多余逗号。nano 中按 `Ctrl+O`、回车保存，再按 `Ctrl+X` 退出。

**第二步：检查配置，再重启。**

```bash
sudo dockerd --validate --config-file=/etc/docker/daemon.json
```

只有显示配置有效后才继续。若有错误，修正 JSON 或恢复刚才的明确备份文件，不要直接重启。重启 Docker 可能影响已有容器，须确认没有活动业务或已安排维护窗口。

```bash
sudo systemctl restart docker
sudo systemctl is-active docker
sudo docker info --format '{{json .RegistryConfig.Mirrors}}'
```

应显示服务 `active`，镜像列表中包含腾讯云地址。这里只修改了 Docker 配置，无需执行 `systemctl daemon-reload`。

镜像列表中出现地址只证明配置已加载，下一小节还要实际拉取镜像。此配置只针对 Docker Hub，不加速 GitHub、APT、npm 或 pip，也不保证所有标签可用。

#### 1.8 验证镜像拉取与运行

```bash
sudo docker pull hello-world
sudo docker run --rm hello-world
```

成功拉取并显示 `Hello from Docker!` 后继续部署。若镜像已缓存，仅运行成功不能证明下载网络正常。`--rm` 删除此次示例容器，保留下载的镜像。若仍失败，按[常见问题](#常见问题)检查网络和 DNS，不必重装 Docker。

### 创建私有环境文件

```bash
touch .env
chmod 600 .env
openssl rand -hex 48
nano .env
```

在编辑器内填写，已有文件不要直接覆盖：

```dotenv
DOMAIN=lottery.example.com
SECRET_KEY=替换为刚生成的随机值
```

DOMAIN 换成实际域名，不带协议、端口或路径。保存密钥，重启不要重新生成。`.env` 不得提交 Git，密钥不得放进公开的 `VITE_*` 变量。

### 构建前后端

```bash
sudo docker run --rm \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "$PWD/frontend:/work/frontend" \
  -v "$PWD/configs:/work/configs:ro" \
  -w /work/frontend \
  node:22-bookworm-slim \
  sh -c 'npm ci && npm run build'

test -f frontend/dist/index.html && echo "前端构建完成"
sudo docker compose config --quiet
sudo docker compose build app
sudo docker compose pull caddy
```

前端要求 Node >=22.12.0；临时容器退出后删除，构建文件保留在 `frontend/dist/`。前端引用 `configs/pools/default.json`，因此必须同时挂载前端和项目配置目录，保持两者的相对路径；只挂载 frontend 会出现 TS2307。configs 挂载为只读。已有满足要求的 Node 时可改用 `npm --prefix frontend ci && npm --prefix frontend run build`。

成功标准：构建成功、入口文件存在、Compose 配置检查成功。不要公开完整 `docker compose config` 输出，它可能含密钥。

### 初始化全新数据库和管理员

```bash
sudo docker compose run --rm app python manage.py migrate
sudo docker compose run --rm app python manage.py init_admin --username admin
```

交互输入两次密码，同时创建默认公共`zmd`规则和角色池。程序最低要求 6 个字符，但公网管理员应使用更长、唯一的密码。

`init_admin` 只执行一次。如果提示已初始化，先确认卷中是否已有数据，不能删库重试。本机账号不会自动出现在服务器的新卷中。

### 启动服务

```bash
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 app caddy
```

等待 app 健康、Caddy 正常运行，然后访问 `https://你的实际域名`。首次证书签发可能需要等待，结合日志判断，不要反复重启。不要使用 HTTP 或公网 IP 代替正式 HTTPS 域名验收。

## 上线验收

脚本安装和手动安装共用以下清单：

- [ ] 证书可信，HTTP 跳转 HTTPS；登录、退出、刷新正常。
- [ ] 前端页面直接打开和刷新正常；不存在的 API 路径返回 404，不回退前端 HTML。
- [ ] 规则页可查看/复制规则，池显示动态稀有度、UP组和权重；用隔离账号完成规则、初始状态和赠送验证。
- [ ] 主抽30次×2轮并开启Trace时分别核对主抽、赠送抽、总抽、直接赠送和Trace事件口径。
- [ ] 图表适应窗口，悬停与数值表一致；历史可重开、Trace 可下载。
- [ ] 非 Trace 模拟正常，并显示无法读取逐抽明细的提示。
- [ ] 两个普通用户的私有池、实验配置和历史互相隔离。
- [ ] 取消仍在执行的任务，确认 worker 退出且不保存残次历史。
- [ ] 无活动任务时重启服务，账号和历史仍存在。
- [ ] 完成备份，并在隔离环境验证恢复后的登录、历史和小型模拟。

容器健康只证明接口能响应，不等于业务或权限验收通过。完成验收后再开放日常使用。

## 日常运维

### 查看状态与日志

```bash
cd /opt/lottery-simulator
sudo docker compose ps
sudo docker compose logs --tail=100 app caddy
```

### 停止与重新启动

先等待任务结束，或在网页取消并确认 worker 退出。关闭网页不会自动取消任务。当前没有一键维护模式，需安排访问窗口，避免维护期间收到新任务。

停止服务：

```bash
sudo docker compose stop
```

重新启动：

```bash
sudo docker compose up -d
```

整个 app 容器停止或重建可能终止其中的模拟 worker，不能承诺任务跨容器重启继续运行。不要用清空任务目录代替取消。

不要执行 `docker compose down -v` 或清理项目持久卷，这可能删除数据库、备份及证书。

### 版本更新

1. 通知暂停使用，确认活动任务结束或取消且 worker 退出。
2. 完成[在线备份](#备份)，将备份复制到安全位置，并记录当前 `git rev-parse HEAD`。
3. 如果启用了备份 timer，停止调度并确认已开始的备份完成。
4. 停止服务、更新代码、重新构建前后端；确认Compose连接v6数据库/目录，再执行迁移。
5. 启动后验证登录、历史、Trace 和小型模拟，再恢复访问与备份调度。

已安装 timer 时执行：

```bash
sudo systemctl stop lottery-backup.timer
sudo systemctl status lottery-backup.service
```

确认备份没有在执行后：

```bash
sudo docker compose stop
git status --short
git pull --ff-only origin master
```

工作区有本地改动或拉取失败时先处理，不强制覆盖。ZIP 安装没有 Git 元数据，应取得新版本并核对文件替换，保留原 `.env`、安装目录和持久卷，不能执行上述 `git pull`。

然后重新执行[构建前后端](#构建前后端)中的命令，再执行：

```bash
sudo docker compose run --rm app python manage.py migrate
sudo docker compose up -d
sudo docker compose ps
sudo docker compose logs --tail=100 app caddy
```

验收通过后，只恢复此前启用的 timer：

```bash
sudo systemctl start lottery-backup.timer
```

更新不重复初始化管理员。若数据库已迁移，不能假设只回退代码就安全，应按代码与数据库版本确定恢复方案。

2026-09-29图表修改要求后端 API 与新前端配套发布，没有数据库格式变化或新依赖。已有 Trace 可直接读取，不需要清空历史或重新模拟。发布后检查窗口联动、悬停与表格一致、非 Trace 提示，详见[图表修改记录](changes/2026-09-29-position-chart-usability.md)。

## 备份、恢复与迁移

### 数据库版本边界

当前程序使用 Django migration 管理 v6 schema。默认路径是 `/app/data/history_v6.sqlite3`、`/app/data/jobs_v6/` 和 `/app/data/exports_v6/`。v5数据库不能作为v6目标，也不会原地迁移；只读账号导入流程见下节。旧版文件保留为独立备份，不能改名伪装成v6数据库。

### v5账号保留与v6切换

此流程建立空v6库，再从明确的v5源只读复制账号与登录防护。池、实验配置、运行历史、Trace和会话不会迁入。真实环境操作前需核对源库、目标库和备份路径，并先在隔离副本演练；这里的步骤不授权删除或覆盖真实数据。

切换前先按旧版受控流程停止服务和活动任务，并确认没有删除中账号或未完成删除清单。目标迁移、账号导入、默认初始化及验收成功后才切换到配套新版代码/前端；失败时保留旧库与备份，恢复旧代码和路径，不让旧代码打开v6。

当前Compose将数据库和目录配置为`history_v6.sqlite3`、`jobs_v6/`、`exports_v6/`。先备份明确选定的v5数据库到新的私有文件；使用该备份作为导入来源，绝不能把`LOTTERY_DB_PATH`设为源库。目标v6必须是完整迁移后且业务表为空：

```bash
sudo docker compose run --rm app python manage.py migrate
sudo docker compose run --rm app python manage.py import_v5_accounts --source /app/backups/selected-v5.sqlite3
sudo docker compose run --rm app python manage.py init_business_defaults
```

导入命令只读验证源库版本、完整性、迁移状态和未完成账号删除标记，并要求目标为空；它只复制账号与登录限制，不复制会话。重复导入会拒绝。副本验收应确认账号可登录、默认`zmd`规则和池已建立，再核对最终运行数据路径。不得在已有账号库运行`init_admin`；该命令只用于全新空库。

### 备份

Compose 部署优先使用以下在线备份命令（app 需运行）：

```bash
sudo docker compose exec -T app python3 scripts/backup_db.py \
  /app/data/history_v6.sqlite3 \
  "/app/backups/lottery-v6-$(date +%F-%H%M%S).sqlite3"
```

数据和备份分别保存在 `lottery_data`、`lottery_backups` 命名卷，实际卷名带 Compose 项目前缀；容器路径不是宿主机同名目录。不要直接编辑 Docker 内部卷文件。

将选定备份复制到宿主机私有目录（替换示例文件名）：

```bash
sudo install -d -m 700 /opt/lottery-private-backups
sudo docker compose cp \
  app:/app/backups/lottery-v6-YYYY-MM-DD-HHMMSS.sqlite3 \
  /opt/lottery-private-backups/
sudo chmod 600 /opt/lottery-private-backups/lottery-v6-YYYY-MM-DD-HHMMSS.sqlite3
```

此目录由 root 管理，复制和异机传输使用受控管理权限。还须将备份复制到受控异机位置，检查容量并安排保留周期；同机备份无法防止服务器整体丢失。

备份包含账号、密码哈希、会话、规则、角色池、实验配置和已提交历史。它不包含 `jobs_v6/` 或 `exports_v6/`。脚本成功时输出 `Backup integrity_check: ok`，目标文件权限设置为 `0600`。备份目录应限制为服务/运维账号可访问，并复制到受控异机位置；不得放入静态网站目录或提交 Git。

### 每日自动备份

仓库提供的 `deploy/lottery-backup.service` 与 `.timer` 是 systemd 备份接口示例，假设 Docker Compose 服务名 `app` 和容器路径 `/app/data`、`/app/backups`，使用v6数据库和`lottery-v6-`前缀。

标准安装路径为 `/opt/lottery-simulator`，Docker 路径为 `/usr/bin/docker`；若不同，先调整服务文件。安装与检查命令：

```bash
sudo install -m 644 deploy/lottery-backup.service /etc/systemd/system/lottery-backup.service
sudo install -m 644 deploy/lottery-backup.timer /etc/systemd/system/lottery-backup.timer
sudo systemctl daemon-reload
sudo systemctl start lottery-backup.service
sudo systemctl status lottery-backup.service
sudo journalctl -u lottery-backup.service -n 50 --no-pager
sudo systemctl enable --now lottery-backup.timer
sudo systemctl list-timers lottery-backup.timer
```

一次性 service 成功后变为 inactive 正常，应确认退出成功和完整性检查日志。定时器按服务器时区每日运行；同一天重复执行会更新当天备份。它不自动清理旧备份或异机复制。维护前用 `sudo systemctl stop lottery-backup.timer` 停止调度，并确认已开始的备份也执行完毕。

### 恢复

恢复前停止 Web、worker 和定时备份，保存当前数据库副本，再恢复明确选定的v6备份。确认实际卷、代码版本、文件属主和权限，不能在数据库使用中覆盖，不能混用旧 WAL/SHM 与恢复快照。检查 `PRAGMA integrity_check` 为 `ok`，启动后验证账号登录、历史读取和小型模拟写入，再恢复访问和定时备份。v5备份不是v6恢复文件；账号保留导入见前文。

迁移到新服务器时账号已包含在备份中，不执行 `init_admin`。恢复不会回滚或恢复任务目录；若任务状态与恢复后的数据库不一致，先保留目录并调查，不能递归清理数据目录。恢复演练应使用隔离目录与卷；涉及覆盖现有数据库时应先确定具体目标，不直接套用通用覆盖命令。

## 配置参考

### 组件与数据位置

| 组件或数据 | 位置与作用 |
| --- | --- |
| Caddy | 对外发布 TCP 80/443，提供 HTTPS、静态网页和 API 反向代理 |
| app | Django＋Gunicorn，仅在 internal backend 网络监听 8000，不发布宿主机端口；在容器内启动模拟 worker |
| 前端 | 宿主机 `frontend/dist/` 只读挂载到 Caddy 的 `/srv` |
| 数据库 | `/app/data/history_v6.sqlite3`，卷 `lottery_data` |
| 任务与临时导出 | `/app/data/jobs_v6/`、`/app/data/exports_v6/`，卷 `lottery_data` |
| 备份 | `/app/backups/`，卷 `lottery_backups` |
| 证书与 Caddy 状态 | `/data`、`/config`，卷 `caddy_data`、`caddy_config` |

表中为 Compose 逻辑卷名，真实名称通常带项目名前缀；容器内路径不是宿主机同名目录。固定安装目录和项目名，避免误连新卷。

Caddy 将裸 `/api` 及 `/api/*` 转发给 app，其余路径服务静态文件并回退 `index.html`。不存在的 API 路径由 Django 返回 404，不回退网页。带哈希的 `/assets/*` 设置一年 immutable 缓存，入口页设置 no-cache。前后端同 HTTPS 域名，不需要另加 CORS。

镜像以非 root 服务账号运行，私有目录初始权限为 `0700`。Gunicorn 使用 2 个 gthread 进程、每进程 4 线程、120 秒超时；默认每进程一个并发导出槽，不是跨进程全局队列。

### 环境变量

Compose 用户只需按安装章节填写 `.env` 的 `DOMAIN` 和 `SECRET_KEY`，下面的应用变量由 `docker-compose.yml` 自动设置，无需再次在终端 export：

```text
LOTTERY_ENV=production
SECRET_KEY=<.env中的随机密钥>
LOTTERY_ALLOWED_HOSTS=<DOMAIN>
LOTTERY_CSRF_TRUSTED_ORIGINS=https://<DOMAIN>
LOTTERY_DATA_DIR=/app/data
LOTTERY_DB_PATH=/app/data/history_v6.sqlite3
LOTTERY_JOBS_DIR=/app/data/jobs_v6
LOTTERY_EXPORTS_DIR=/app/data/exports_v6
LOTTERY_PROXY_SUBNET=172.30.96.0/24
LOTTERY_CADDY_IP=172.30.96.2
LOTTERY_PROXY_DYNAMIC_RANGE=172.30.96.128/25
LOTTERY_PROXY_GATEWAY=172.30.96.1
LOTTERY_TRUSTED_PROXIES=172.30.96.2
```

生产缺少密钥会拒绝启动。Compose 将 app 放在 internal backend 网络，Caddy同时接入可对外访问的默认网络并使用固定 backend IPv4。Caddy覆盖转发的 `X-Forwarded-For` 为其连接对端；app只信任由同一 `LOTTERY_CADDY_IP` 生成的精确代理地址。不得将这些设置改成CIDR或整段私网信任。新增 CDN 或多层代理须另行定义可信链。Caddy保留Host并转发 `X-Forwarded-Proto`；当前 Django 未配置 `SECURE_PROXY_SSL_HEADER`。Secure Cookie 由生产环境明确启用，会话 Cookie 保持 HttpOnly、SameSite=Lax。

本安装流程使用域名＋HTTPS，不提供公网 IP＋HTTP 登录配置。前端构建变量 `VITE_*` 会进入公开资源，不放密钥、数据库、任务、备份或环境文件。

### 非 Compose 部署参考

本文推荐 Compose。自行使用 Gunicorn 和其它反向代理时，需适配上面的生产变量、请求分流、服务权限、worker 生命周期和私有持久目录；不要照搬容器路径。

备份脚本可对运行中的SQLite源库执行在线备份。以下是非容器部署的路径示例，不是Compose命名卷在宿主机上的实际路径；维护者须先确认真实映射：

```bash
python3 scripts/backup_db.py /srv/lottery/data/history_v6.sqlite3 /srv/lottery/backups/lottery-v6-$(date +%F-%H%M%S).sqlite3
```

## 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 镜像或依赖下载失败 | 外网、DNS、代理、镜像标签和软件源；不要盲目换不可信源 |
| DOMAIN 或 SECRET_KEY 缺失 | 当前目录与 `.env`；不要公开含密钥的配置输出 |
| 构建被 Killed | 系统日志、内存和磁盘；先处理资源问题 |
| app 不健康、Caddy 未启动 | app 日志中的迁移、权限和环境错误 |
| 证书日志出现 NXDOMAIN | 域名尚无有效公网解析；为根域名设置主机记录 `@` 的 A 记录，指向公网 IPv4。仅设置 www 不够 |
| 登录或 CSRF 403 | 正式 HTTPS 域名、DOMAIN 和 CSRF Origin 是否一致 |
| 首页 HTTPS 返回 404 | 检查宿主机 `frontend/dist/index.html` 与容器 `/srv/index.html`；证书成功不代表前端已构建 |
| 页面刷新 404 | 检查仓库 Caddyfile 的前端路由回退；API 路径不应回退 HTML |
| 构建报 TS2307，找不到 default.json | 同时挂载 frontend 与 configs，保持相对路径，使用本文更新后的构建命令 |
| npm 报告依赖漏洞 | 与本次缺配置文件的构建错误分开处理；查看 audit 详情，不盲目执行 `npm audit fix --force` |
| 历史突然为空 | 是否换了 Compose 项目名、目录或卷；不要立即重新初始化 |
| 自动备份失败 | app 是否运行、systemd 工作目录、Docker 路径、日志和空间 |
| `sudo` 权限不足 | 由服务器管理员授予必要权限，不绕过权限限制 |
| `Unable to locate package docker-ce` | 检查软件源文件和 `apt update` 是否成功 |
| APT 锁被占用 | 等待系统更新结束，不直接删除锁文件 |
| 下载超时、解析失败 | 检查网络、DNS、代理；终端能联网不代表 Docker 守护进程的代理也已配置 |
| `Cannot connect to the Docker daemon` | 执行 `sudo systemctl status docker --no-pager` 和 `sudo journalctl -u docker -n 100 --no-pager` |
| `docker compose` 不存在 | 确认安装的是 `docker-compose-plugin` |
| hello-world 拉取失败 | 检查镜像仓库网络、限流或认证；腾讯云先按镜像配置章节设置加速 |

常用定位命令（在项目根目录执行）：

```bash
getent ahostsv4 你的实际域名
sudo docker compose ps
sudo docker compose logs --tail=100 app caddy
ls -l frontend/dist/index.html
sudo docker compose exec caddy ls -l /srv/index.html
curl -I --connect-timeout 15 --max-time 20 https://你的实际域名
```

公网 DNS 解析应返回服务器公网 IP；HTTPS `200` 只证明入口响应，登录和模拟仍须实际验证。首次申请证书时 Caddy 会重试，解决解析问题后等待并观察日志，不反复删证书或重启。

排障不要提供密码、环境文件、Cookie 或数据库内容。

## 验证状态

截至2026-10-01，区分以下证据：

| 项目 | 当前证据 |
| --- | --- |
| 任务16新版集中验收 | 后端242项、前端52项及构建通过，后续账号/夹具回归通过；浏览器与最终dist加载已核对。详见[实施记录](changes/2026-09-30-independent-rules-rarities.md)，不是服务器验收 |
| 本地功能 | 已有[浏览器验收](changes/2026-09-29-user-pool-browser-acceptance.md)和[实施记录](changes/2026-09-24-user-pool-experiment.md) |
| 腾讯云手动部署 | 用户已明确确认服务器使用手动指令完成部署；此前提供日志显示 app 健康、Caddy 启动、正式 Let's Encrypt 证书签发成功。本次未连接服务器复核 |
| 服务器业务验收 | 未逐项记录登录、双用户隔离、模拟、下载、取消与恢复的服务器验收结果 |
| 新交互式安装脚本 | 已纳入master；已有Bash语法及5项隔离流程检查记录，见[安装脚本记录](changes/2026-09-30-interactive-installer.md)。自动安装尚未实机测试；不使用手动部署成功推定脚本成功 |
| 生产备份与维护 | 定时器、恢复及活动任务跨容器生命周期未实机验收 |

用户的手动部署成功不等于新安装脚本已实测；证书签发成功也不能代替业务验收。本文所列安装、备份和恢复步骤不构成删除已有数据的许可。

### 2026-10-06修复交付补充

最新v6可靠性修复仍位于隔离工作树，未合并主检出或部署服务器；本文已有服务器结果保留原时点，不代表本轮版本已上线。任务1—10、12、13完成；271项后端、65项前端及后续30项部署/安装定向回归的实际版本边界见[实施记录](changes/2026-10-02-v6-runtime-reliability-fixes.md#2026-10-06任务13文档与最终交付完成)。最后前端CSS调整经重新构建及浏览器复验，没有重复65项全套。

本轮隔离Docker/Caddy实际peer/XFF、两个来源限流桶、固定地址重建和临时CA HTTPS通过；Caddy出站公网TLS曾收到不受信任自签证书，可信公网HTTPS仍待验证。不是正式域名/ACME或全新服务器首次安装实测。部署前需使用独立环境补网络验证，不能关闭TLS校验绕过。测试配置/证书/卷/原始拓扑日志已按用户要求删除，历史恢复命令不可直接执行；重新验收需准备新材料。当前部署步骤也不构成服务器升级或数据清理授权。
