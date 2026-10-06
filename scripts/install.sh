#!/usr/bin/env bash
# 中文交互式服务器管理；从完整项目目录运行。
set -Eeuo pipefail
stage='检查安装环境'
mode=menu
backup_dir='尚未创建'
upgrade_paused=0
upgrade_helper_cid=''

if [[ ${1:-} == --help ]]; then
  printf '用法：bash scripts/install.sh [--install|--upgrade|--restore]\n无参数：选择安装、卸载、运维（启停/状态/日志/备份/定时备份）或更新。\n--install：直接首次安装，拒绝已有数据。\n--upgrade：直接升级已下载版本，不自动git pull。菜单更新可先拉取Git新版。\n--restore：重装保留的标准v6数据卷，不初始化账号；拒绝v5与活动/损坏数据。\nv5仅迁账号及登录限制；旧业务保留在旧库。卸载可保留数据或二次确认永久删除。\n失败不自动续跑/回滚，备份timer在业务及HTTPS验收后恢复。\n详见 docs/deployment.md；不要使用 curl | bash。\n'
  exit 0
fi
case ${1:-} in --upgrade) mode=upgrade; shift;; --install) mode=install; shift;; --restore) mode=restore; shift;; esac
if (( $# )); then printf '不支持的参数；使用 --help 查看说明。\n' >&2; exit 1; fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$project_dir"
[[ -t 0 ]] || { printf '请在交互式终端执行，不要使用 curl | bash。\n' >&2; exit 1; }
if [[ $mode == menu ]]; then
  [[ -f scripts/manage.sh ]] || { printf '缺少 scripts/manage.sh；请获取完整新版项目。\n' >&2; exit 1; }
  source scripts/manage.sh
  management_menu
  exit
fi
for file in docker-compose.yml Dockerfile Caddyfile configs/pools/default.json configs/rules/zmd.json frontend/package-lock.json; do
  [[ -f $file ]] || { printf '缺少项目文件：%s；请下载完整 master 项目。\n' "$file" >&2; exit 1; }
done
if (( EUID == 0 )); then admin=(); else admin=(sudo); sudo -v; fi
docker_cmd() { "${admin[@]}" docker "$@"; }
has_runtime_material() {
  [[ -e data/history_v6.sqlite3 || -e data/history_v5.sqlite3 ]] && return 0
  command -v docker >/dev/null || return 2
  local containers volumes
  containers=$(docker_cmd ps -aq --filter "label=com.docker.compose.project.working_dir=${project_dir:-$PWD}") || return 2
  [[ -z $containers ]] || return 0
  volumes=$(docker_cmd volume ls -q --filter 'label=com.docker.compose.volume=lottery_data') || return 2
  [[ -z $volumes ]] && return 1 || return 0
}
report_failure() {
  local status=$1 line=$2
  if [[ $mode == upgrade ]]; then
    if [[ -n $upgrade_helper_cid ]] && "${admin[@]}" test -f "$upgrade_helper_cid"; then
      helper_id=$("${admin[@]}" cat "$upgrade_helper_cid")
      if [[ $helper_id =~ ^[a-f0-9]{64}$ ]]; then docker_cmd rm --force "$helper_id" >/dev/null 2>&1 || true; fi
    fi
    if [[ $upgrade_paused == 1 ]]; then
      if docker_cmd unpause "$app" >/dev/null; then upgrade_paused=0;
      else printf '旧app仍可能暂停；请人工核对后docker unpause，不要删除数据。\n' >&2; fi
    fi
    printf '\n升级停止：%s失败（第%s行）。备份：%s。\n' "$stage" "$line" "$backup_dir" >&2
    printf '保留原卷、旧库及错误现场；入口/服务可能已停止。不会自动恢复已暂停的timer或服务；核对状态后按docs/deployment.md手动恢复，不自动覆盖或重试。\n' >&2
  elif [[ $mode == restore ]]; then
    printf '\n重装停止：%s失败（第%s行）；原卷与.env保留，不自动初始化或重试。\n' "$stage" "$line" >&2
  else
    if has_runtime_material; then found=0; else found=$?; fi
    if [[ $found == 0 ]]; then
      printf '\n安装停止：%s失败（第 %s 行）。已存在运行材料；先核对状态并备份，再按 docs/deployment.md 手动恢复或升级。脚本不会自动续跑或清理数据。\n' "$stage" "$line" >&2
    elif [[ $found == 1 ]]; then
      printf '\n安装停止：%s失败（第 %s 行）。未发现数据库、容器或数据卷；处理错误后可重新运行，现有 .env 会保留。\n' "$stage" "$line" >&2
    else
      printf '\n安装停止：%s失败（第 %s 行）。无法读取Docker状态，现有数据状态未知；请核对状态与备份后按 docs/deployment.md 手动恢复或升级。\n' "$stage" "$line" >&2
    fi
  fi
  exit "$status"
}
trap 'report_failure "$?" "$LINENO"' ERR
trap 'report_failure 130 "$LINENO"' INT
trap 'report_failure 143 "$LINENO"' TERM

stop_existing_install() {
  printf '检测到已有安装或数据库数据，首次安装已停止。请先核对状态并备份，再按 docs/deployment.md 手动恢复或升级；不会自动续跑、创建账号或改动现有数据。\n' >&2
  exit 1
}

if [[ $mode == upgrade ]]; then
  for file in scripts/upgrade.sh scripts/upgrade_probe.py; do
    [[ -f $file ]] || { printf '缺少升级文件：%s；请获取完整新版。\n' "$file" >&2; exit 1; }
  done
  source scripts/upgrade.sh
  prepare_upgrade
elif [[ $mode == restore ]]; then
  for file in scripts/manage.sh scripts/upgrade_probe.py; do
    [[ -f $file ]] || { printf '缺少重装文件：%s。\n' "$file" >&2; exit 1; }
  done
  source scripts/manage.sh
  management_restore_prepare
else
for path in data/history_v5.sqlite3 data/history_v6.sqlite3 data/jobs_v5 data/exports_v5; do
  [[ ! -e $path ]] || stop_existing_install
done

printf '抽奖模拟器首次安装\n安装目录：%s\n' "$project_dir"
if command -v docker >/dev/null; then
  docker_cmd info >/dev/null 2>&1 || {
    printf '无法检查 Docker 数据卷，安装已停止。\n' >&2; exit 1;
  }
  existing=$(docker_cmd ps -aq --filter "label=com.docker.compose.project.working_dir=$project_dir") || {
    printf '无法检查本目录的 Docker 容器，安装已停止。\n' >&2; exit 1;
  }
  [[ -z $existing ]] || stop_existing_install
  if [[ -f .env ]]; then
    project_name=$(docker_cmd compose config --format json 2>/dev/null | python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])') || {
      printf '无法读取 Compose 项目标识，安装已停止。\n' >&2; exit 1;
    }
  else
    project_name=${COMPOSE_PROJECT_NAME:-$(basename "$project_dir" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')}
  fi
  volume=$(docker_cmd volume ls -q \
    --filter "label=com.docker.compose.project=$project_name" \
    --filter 'label=com.docker.compose.volume=lottery_data') || {
    printf '无法检查已有数据库卷，安装已停止。\n' >&2; exit 1;
  }
  [[ -z $volume ]] || stop_existing_install
fi

stage='安装基础工具'
# 已有全部工具时不刷新软件源；全新 Ubuntu 按官方 apt 安装。
missing=0
for tool in curl git openssl nano python3; do command -v "$tool" >/dev/null || missing=1; done
if (( missing )) || ! command -v docker >/dev/null; then
  . /etc/os-release
  [[ $ID == ubuntu && $VERSION_ID == 24.04 ]] || {
    printf '自动安装仅支持 Ubuntu 24.04；其他系统请先手动安装 Docker 和基础工具。\n' >&2; exit 1;
  }
  "${admin[@]}" apt-get update
  "${admin[@]}" apt-get install -y ca-certificates curl git openssl nano python3
fi

stage='安装 Docker'
if ! command -v docker >/dev/null; then
  for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc; do
    if dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed'; then
      printf '发现可能冲突的软件包 %s，请按官方文档确认用途并处理后再运行。\n' "$package" >&2; exit 1
    fi
  done
  if [[ -e /etc/apt/sources.list.d/docker.sources || -e /etc/apt/sources.list.d/docker.list ]]; then
    printf '已有 Docker 软件源，需先确认其配置并手动安装 Docker，脚本不会覆盖。\n' >&2; exit 1
  fi
  "${admin[@]}" install -m 0755 -d /etc/apt/keyrings
  "${admin[@]}" curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  "${admin[@]}" chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  "${admin[@]}" tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  "${admin[@]}" apt-get update
  "${admin[@]}" apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  "${admin[@]}" systemctl enable --now docker
fi
docker_cmd info >/dev/null
docker_cmd compose version
docker_cmd buildx version

stage='配置镜像加速'
read -r -p '是否配置腾讯云内网 Docker 镜像加速？仅腾讯云服务器可用 [y/N]：' mirror
if [[ $mirror == y || $mirror == Y ]]; then
  if [[ -n $(docker_cmd ps -q) ]]; then
    printf 'Docker 还有其他运行容器，不能自动重启。请维护后手动配置镜像，再运行安装。\n' >&2; exit 1
  fi
  "${admin[@]}" mkdir -p /etc/docker
  # 安全合并现有 JSON；验证失败时保持错误现场及原始备份，不自动重启。
  "${admin[@]}" python3 - <<'PY'
import json, os, shutil, tempfile
from datetime import datetime
from pathlib import Path
p = Path('/etc/docker/daemon.json')
config = json.loads(p.read_text()) if p.exists() else {}
if not isinstance(config, dict):
    raise SystemExit('Docker 配置必须是 JSON 对象')
mirrors = config.get('registry-mirrors', [])
if not isinstance(mirrors, list) or not all(isinstance(x, str) for x in mirrors):
    raise SystemExit('registry-mirrors 必须是字符串数组')
address = 'https://mirror.ccs.tencentyun.com'
if address not in mirrors:
    config['registry-mirrors'] = [address, *mirrors]
    if p.exists():
        shutil.copy2(p, str(p) + '.bak-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    fd, temp = tempfile.mkstemp(dir=p.parent, prefix='.daemon-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(config, f, indent=2)
            f.write('\n')
        os.replace(temp, p)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
PY
  "${admin[@]}" dockerd --validate --config-file=/etc/docker/daemon.json
  "${admin[@]}" systemctl restart docker
fi
docker_cmd pull hello-world
docker_cmd run --rm hello-world

stage='配置应用环境'
if [[ -f .env ]]; then
  printf '保留已有 .env，不修改域名或密钥。\n'
else
  read -r -p '请输入已解析到本服务器的域名（不带 https://）：' domain
  python3 - "$domain" <<'PY'
import ipaddress, re, sys
domain = sys.argv[1]
try:
    ipaddress.ip_address(domain)
except ValueError:
    pass
else:
    raise SystemExit('本安装流程需要域名，不接受 IP 地址')
if len(domain) > 253 or '.' not in domain or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', x) for x in domain.split('.')):
    raise SystemExit('域名格式无效；国际化域名请使用 ASCII/Punycode 格式')
PY
  app_secret=$(openssl rand -hex 48)
  (umask 077; set -o noclobber; printf 'DOMAIN=%s\nSECRET_KEY=%s\n' "$domain" "$app_secret" > .env)
  unset app_secret
fi
fi

docker_cmd compose config --quiet

stage='检查代理网络配置'
docker_cmd compose config --format json | "${admin[@]}" python3 scripts/check_proxy_network.py --project "$(docker_cmd compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')" --docker "$(command -v docker)"

stage='构建前端'
docker_cmd run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$project_dir/frontend:/work/frontend" -v "$project_dir/configs:/work/configs:ro" \
  -w /work/frontend node:22-bookworm-slim sh -c 'npm ci && npm run build'
[[ -f frontend/dist/index.html ]]

stage='构建后端'
docker_cmd compose build app
docker_cmd compose pull caddy
if [[ $mode == upgrade ]]; then
  upgrade_database
elif [[ $mode == restore ]]; then
  stage='核对保留的v6数据与任务'
  container_backup="/app/backups/upgrade-restore-$(date +%Y%m%d-%H%M%S-%N)"
  docker_cmd compose run --rm -T --no-deps app python - backup 6 "$container_backup" < scripts/upgrade_probe.py
  printf '重装前v6数据库快照已保存：%s/source.sqlite3\n' "$container_backup"
  stage='迁移保留的v6数据库'
  docker_cmd compose run --rm app python manage.py migrate
else
stage='检查全新v6数据目录'
docker_cmd compose run --rm -T app python -c '
from pathlib import Path
root = Path("/app/data")
allowed = {"jobs_v6", "exports_v6"}
bad = [p for p in root.iterdir() if p.name not in allowed or not p.is_dir() or next(p.iterdir(), None) is not None]
if bad:
    raise SystemExit("检测到已有数据库或文件数据，首次安装已停止；请核对数据库与备份，再按 docs/deployment.md 手动恢复或升级。")
'
stage='迁移数据库'
docker_cmd compose run --rm app python manage.py migrate
stage='检查管理员初始化状态'
initialized=$(docker_cmd compose run --rm -T app python manage.py shell -c \
  'from dashboard.models import AppMeta, User, Pool, Rule; print("READY" if AppMeta.objects.filter(key="initialized").exists() else "PARTIAL" if User.objects.exists() or Pool.objects.exists() or Rule.objects.exists() else "EMPTY")' | tail -n 1)
case "$initialized" in
  READY) printf '发现已有初始化数据，首次安装已停止；请核对数据库与备份，再按 docs/deployment.md 手动恢复或升级。\n' >&2; exit 1 ;;
  EMPTY)
    read -r -p '请输入首个管理员用户名：' username
    [[ -n $username ]] || { printf '用户名不能为空。\n' >&2; exit 1; }
    stage='创建首个管理员'
    docker_cmd compose run --rm app python manage.py init_admin --username "$username"
    ;;
  *) printf '初始化状态异常：请检查数据库，不会自动删除或重置数据。\n' >&2; exit 1 ;;
esac
fi
stage='启动服务'
if [[ $mode != install ]]; then
  docker_cmd compose up -d --wait --wait-timeout 120
else
  docker_cmd compose up -d
fi
docker_cmd compose ps
printf '\n启动命令已完成。请使用 .env 中的域名通过 HTTPS 访问。\n'
printf '证书可能仍在申请：sudo docker compose logs --tail=100 app caddy\n'
printf '完成登录、小型模拟、Trace 与备份验收后再开放日常使用。\n'
printf '再次运行脚本，选择运维，可配置或恢复每日备份；详情见 docs/deployment.md。\n'

if [[ $mode == upgrade ]]; then finish_upgrade; fi
