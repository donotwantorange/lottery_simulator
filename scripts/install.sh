#!/usr/bin/env bash
# 中文交互式首次安装；从完整项目目录运行，不用于线上更新。
set -Eeuo pipefail
stage='检查安装环境'
trap 'printf "\n安装停止：%s失败（第 %s 行）。处理错误后可重新运行；已有数据不会自动清除。\n" "$stage" "$LINENO" >&2' ERR

if [[ ${1:-} == --help ]]; then
  printf '用法：bash scripts/install.sh\n适用：Ubuntu 24.04，从完整项目目录交互执行首次部署。\n先完成域名解析及80/443端口配置，再获取完整项目。\n已有运行服务时退出；日常更新按 docs/deployment.md 的版本更新章节执行。\n启动后按上线验收清单验证；定时备份另行设置。\n'
  exit 0
fi
if (( $# )); then printf '不支持的参数；使用 --help 查看说明。\n' >&2; exit 1; fi
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$project_dir"
for file in docker-compose.yml Dockerfile Caddyfile configs/pools/default.json frontend/package-lock.json; do
  [[ -f $file ]] || { printf '缺少项目文件：%s；请下载完整 master 项目。\n' "$file" >&2; exit 1; }
done
[[ -t 0 ]] || { printf '请在交互式终端执行，不要使用 curl | bash。\n' >&2; exit 1; }
if (( EUID == 0 )); then admin=(); else admin=(sudo); sudo -v; fi
docker_cmd() { "${admin[@]}" docker "$@"; }

printf '抽奖模拟器首次安装\n安装目录：%s\n' "$project_dir"
if command -v docker >/dev/null && docker_cmd info >/dev/null 2>&1; then
  running=$(docker_cmd ps -q --filter "label=com.docker.compose.project.working_dir=$project_dir")
  if [[ -n $running ]]; then
    printf '本目录已有运行中的服务。首次安装已退出；更新请按 docs/deployment.md 的版本更新章节执行。\n'
    docker_cmd ps --filter "label=com.docker.compose.project.working_dir=$project_dir"
    exit 0
  fi
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
docker_cmd compose config --quiet

stage='构建前端'
docker_cmd run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$project_dir/frontend:/work/frontend" -v "$project_dir/configs:/work/configs:ro" \
  -w /work/frontend node:22-bookworm-slim sh -c 'npm ci && npm run build'
[[ -f frontend/dist/index.html ]]

stage='构建后端'
docker_cmd compose build app
docker_cmd compose pull caddy
stage='迁移数据库'
docker_cmd compose run --rm app python manage.py migrate
stage='检查管理员初始化状态'
initialized=$(docker_cmd compose run --rm -T app python manage.py shell -c \
  'from dashboard.models import AppMeta, User, Pool; print("READY" if AppMeta.objects.filter(key="initialized").exists() else "PARTIAL" if User.objects.exists() or Pool.objects.exists() else "EMPTY")' | tail -n 1)
case "$initialized" in
  READY) printf '保留已有管理员和数据，跳过初始化。\n' ;;
  EMPTY)
    read -r -p '请输入首个管理员用户名：' username
    [[ -n $username ]] || { printf '用户名不能为空。\n' >&2; exit 1; }
    stage='创建首个管理员'
    docker_cmd compose run --rm app python manage.py init_admin --username "$username"
    ;;
  *) printf '初始化状态异常：请检查数据库，不会自动删除或重置数据。\n' >&2; exit 1 ;;
esac
stage='启动服务'
docker_cmd compose up -d
docker_cmd compose ps
printf '\n启动命令已完成。请使用 .env 中的域名通过 HTTPS 访问。\n'
printf '证书可能仍在申请：sudo docker compose logs --tail=100 app caddy\n'
printf '完成登录、小型模拟、Trace 与备份验收后再开放日常使用。\n'
printf '定时备份安装和更新操作见 docs/deployment.md。\n'
