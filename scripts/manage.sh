# Sourced by install.sh; one action per invocation, reuse install/upgrade unchanged.
source scripts/deployment_checks.sh
management_menu() {
  trap 'if [[ $mode == legacy-reinstall ]]; then printf "永久卸载停止：%s；已删除：%s。不自动重试或恢复。\n" "$stage" "${legacy_deleted:-无}" >&2; else printf "管理操作失败；保留现场，不自动重试或删除数据。\n" >&2; fi' ERR
  printf '\n抽奖模拟器服务器管理\n目录：%s\n1) 安装\n2) 卸载\n3) 运维（启停、状态、日志、备份、定时备份）\n4) 更新\n0) 退出\n' "$project_dir"
  read -r -p '请选择：' choice
  case $choice in
    1)
      printf '1) 全新安装\n2) 重装保留的v6数据（不初始化账号）\n'
      read -r -p '请选择安装方式：' operation
      case $operation in
        1) exec bash "$project_dir/scripts/install.sh" --install;;
        2) exec bash "$project_dir/scripts/install.sh" --restore;;
        *) printf '已取消。\n'; return;;
      esac;;
    2)
      printf '1) 卸载服务并保留数据\n2) 永久卸载本项目受管资源\n'
      read -r -p '请选择卸载方式：' operation
      case $operation in
        1) action=uninstall;;
        2) mode=legacy-reinstall; management_legacy_run uninstall; return;;
        *) printf '已取消。\n'; return;;
      esac;;
    3)
      printf '1) 启动原容器\n2) 停止\n3) 重启原容器\n4) 状态\n5) 日志\n6) 备份数据库\n7) 配置/更新每日备份\n8) 恢复每日备份\n'
      read -r -p '请选择运维操作：' operation
      case $operation in
        1) action=start;; 2) action=stop;; 3) action=restart;; 4) action=status;;
        5) action=logs;; 6) action=backup;; 7) action=schedule;; 8) action=resume;;
        *) printf '未执行操作。\n'; return;;
      esac;;
    4) management_update; return;;
    *) printf '未执行操作。\n'; return;;
  esac
  management_project
  case $action in
    start) management_start;;
    stop|restart)
      management_confirm STOP '先等待任务完成或在网页取消；此操作暂停备份和停止网站。'
      management_stop
      [[ $action != restart ]] || management_start;;
    status) docker_cmd ps -a --filter "label=com.docker.compose.project=$project_name";;
    logs) docker_cmd logs --tail=100 "$app"; docker_cmd logs --tail=100 "$caddy";;
    backup) management_backup;;
    schedule) management_schedule;;
    resume) management_resume;;
    uninstall) management_uninstall;;
  esac
}

management_confirm() {
  local expected=$1 message=$2 answer
  printf '%s\n' "$message"
  read -r -p "确认请输入 $expected：" answer
  [[ $answer == "$expected" ]] || { printf '已取消。\n'; exit 1; }
}

management_admin() {
  if (( EUID == 0 )); then admin=(); else admin=(sudo); sudo -v; fi
}
docker_cmd() { "${admin[@]}" docker "$@"; }

management_context() {
  management_admin
  for tool in docker python3 systemctl; do command -v "$tool" >/dev/null; done
  local endpoint
  if [[ -n ${DOCKER_CONTEXT:-} ]]; then
    endpoint=$(docker_cmd context inspect "$DOCKER_CONTEXT" --format '{{.Endpoints.docker.Host}}')
  else
    endpoint=${DOCKER_HOST:-$(docker_cmd context inspect --format '{{.Endpoints.docker.Host}}')}
  fi
  [[ $endpoint == unix:///var/run/docker.sock || $endpoint == unix:///run/docker.sock ]] || { printf '仅支持服务器本机标准Docker。\n' >&2; exit 1; }
  docker_cmd info >/dev/null
  [[ -f .env && -f docker-compose.yml ]] || { printf '缺少原.env或Compose文件，停止操作。\n' >&2; exit 1; }
  project_name=$(docker_cmd compose config --format json | python3 -c 'import json,sys; c=json.load(sys.stdin); assert set(c["services"])=={"app","caddy"}; print(c["name"])')
  [[ $project_name =~ ^[a-z0-9][a-z0-9_-]*$ ]] || exit 1
}

management_project() {
  management_context
  app=$(docker_cmd ps -aq --filter "label=com.docker.compose.project=$project_name" --filter 'label=com.docker.compose.service=app')
  caddy=$(docker_cmd ps -aq --filter "label=com.docker.compose.project=$project_name" --filter 'label=com.docker.compose.service=caddy')
  [[ $app =~ ^[a-f0-9]+$ && $caddy =~ ^[a-f0-9]+$ ]] || { printf '需要本目录各一个原app和Caddy容器；容器缺失不自动按新版重建。\n' >&2; exit 1; }
  source_version=$(docker_cmd inspect "$app" "$caddy" | python3 -c '
import json,sys
app,caddy=json.load(sys.stdin); project,directory=sys.argv[1:]
for item,service in ((app,"app"),(caddy,"caddy")):
    labels=item["Config"]["Labels"]
    assert labels["com.docker.compose.project"]==project and labels["com.docker.compose.project.working_dir"]==directory and labels["com.docker.compose.service"]==service, "容器身份不符"
env=dict(x.split("=",1) for x in app["Config"]["Env"] if "=" in x)
version=next((v for v in (5,6) if env.get("LOTTERY_DB_PATH")==f"/app/data/history_v{v}.sqlite3"),None)
assert version and env.get("LOTTERY_DATA_DIR")=="/app/data" and env.get("LOTTERY_JOBS_DIR")==f"/app/data/jobs_v{version}" and env.get("LOTTERY_EXPORTS_DIR")==f"/app/data/exports_v{version}", "非标准数据路径"
assert not any((app["HostConfig"].get("PortBindings") or {}).values()) and app["HostConfig"].get("NetworkMode")!="host", "app公开端口，无法隔离维护"
for item,expected in ((app,{"/app/data":"lottery_data","/app/backups":"lottery_backups"}),(caddy,{"/data":"caddy_data","/config":"caddy_config"})):
    mounts={m["Destination"]:m for m in item["Mounts"]}
    assert set(mounts)==(set(expected) if item is app else set(expected)|{"/srv","/etc/caddy/Caddyfile"}), "存在额外挂载"
    assert {p for p,m in mounts.items() if m["Type"]=="volume"}==set(expected), "存在非标准命名卷"
    for p,name in expected.items():
        assert mounts[p]["Type"]=="volume" and mounts[p]["Name"]==f"{project}_{name}", "卷身份不符"
mounts={m["Destination"]:m for m in caddy["Mounts"]}
assert mounts["/srv"]["Type"]=="bind" and mounts["/srv"]["Source"]==directory+"/frontend/dist", "前端不属于本目录"
assert mounts["/etc/caddy/Caddyfile"]["Type"]=="bind" and mounts["/etc/caddy/Caddyfile"]["Source"]==directory+"/Caddyfile", "Caddyfile不属于本目录"
print(version)
' "$project_name" "$project_dir")
  local container containers
  containers=$(docker_cmd ps -aq --filter "label=com.docker.compose.project=$project_name")
  for container in $containers; do
    [[ $container == "$app" || $container == "$caddy" ]] || { printf '项目存在额外容器，停止自动管理。\n' >&2; exit 1; }
  done
  printf '已核对项目 %s，原数据库v%s。\n' "$project_name" "$source_version"
}

management_restore_prepare() {
  management_context
  local name volume containers
  containers=$(docker_cmd ps -aq --filter "label=com.docker.compose.project=$project_name")
  [[ -z $containers ]] || { printf '仍有项目容器；请用启动或更新，不执行重装。\n' >&2; exit 1; }
  for name in lottery_data lottery_backups caddy_data caddy_config; do
    volume="${project_name}_$name"
    docker_cmd volume inspect "$volume" | python3 -c 'import json,sys; v,=json.load(sys.stdin); p,n=sys.argv[1:]; assert v["Labels"]["com.docker.compose.project"]==p and v["Labels"]["com.docker.compose.volume"]==n' "$project_name" "$name"
    containers=$(docker_cmd ps -aq --filter "volume=$volume")
    [[ -z $containers ]] || { printf '卷仍被容器使用，拒绝重装。\n' >&2; exit 1; }
  done
  docker_cmd compose config --format json | python3 -c '
import json,sys
c=json.load(sys.stdin); p=c["name"]
assert c["services"]["app"]["environment"]["LOTTERY_DB_PATH"]=="/app/data/history_v6.sqlite3"
env=c["services"]["app"]["environment"]
assert all(env.get(k)==v for k,v in {"LOTTERY_DATA_DIR":"/app/data","LOTTERY_JOBS_DIR":"/app/data/jobs_v6","LOTTERY_EXPORTS_DIR":"/app/data/exports_v6"}.items()), "重装数据路径非标准配置"
assert not c["services"]["app"].get("ports") and set(c["services"]["app"]["networks"])=={"backend"}
for n in ("lottery_data","lottery_backups","caddy_data","caddy_config"):
    assert c["volumes"][n]["name"]==f"{p}_{n}" and not c["volumes"][n].get("external"), "重装不能改接卷"
for service,expected in (("app",{"/app/data":"lottery_data","/app/backups":"lottery_backups"}),("caddy",{"/data":"caddy_data","/config":"caddy_config"})):
    mounts={m["target"]:m for m in c["services"][service]["volumes"]}
    assert all(mounts[t]["type"]=="volume" and mounts[t]["source"]==n for t,n in expected.items()), "重装挂载不匹配"
'
  management_confirm RESTORE '仅重装已保留的v6数据；要求.env和四个原卷齐全、没有残留容器。先保留受控备份，不重置管理员。v5不能使用此入口。'
}

management_start() {
  local paused
  paused=$(docker_cmd inspect --format '{{.State.Paused}}' "$app")
  [[ $paused == true || $paused == false ]] || exit 1
  if [[ $paused == true ]]; then
    management_confirm UNPAUSE '旧app处于暂停状态；确认需要恢复原容器运行。'
    docker_cmd unpause "$app"
  else
    docker_cmd start "$app"
  fi
  docker_cmd start "$caddy"
  printf '已启动原容器，不重建、不迁移。请核对状态、日志与网页；每日备份需单独恢复。\n'
}

management_pause_timer() {
  local active
  deployment_check_timer || exit 1
  timer_load=$timer_state
  if [[ $timer_state == loaded ]]; then
    "${admin[@]}" systemctl stop lottery-backup.timer
    [[ $("${admin[@]}" systemctl show lottery-backup.timer --property=ActiveState --value) == inactive ]] || exit 1
    active=$(deployment_unit_property lottery-backup.service ActiveState) || exit 1
    [[ $active == inactive || $active == failed ]] || { printf '正在备份或service状态未知；请等待后再操作。\n' >&2; exit 1; }
  fi
}

management_stop() {
  [[ -f scripts/upgrade_probe.py ]] || { printf '缺少任务检查脚本，停止操作。\n' >&2; exit 1; }
  management_pause_timer
  docker_cmd stop "$caddy"
  local running paused
  running=$(docker_cmd inspect --format '{{.State.Running}}' "$app")
  [[ $running == true || $running == false ]] || exit 1
  if [[ $running == true ]]; then
    paused=$(docker_cmd inspect --format '{{.State.Paused}}' "$app")
    [[ $paused == false ]] || { printf 'app暂停中或状态未知，请先核对恢复；入口保持停止。\n' >&2; exit 1; }
    docker_cmd exec -i "$app" python - probe "$source_version" < scripts/upgrade_probe.py
    docker_cmd stop --timeout 120 "$app"
  fi
  printf '原容器已停止，数据保留，timer暂停。\n'
}

management_backup() {
  local stamp destination private
  stamp=$(date +%Y%m%d-%H%M%S-%N)
  destination="/app/backups/lottery-v$source_version-$stamp.sqlite3"
  private="/var/backups/lottery/$project_name/manual-$stamp"
  docker_cmd exec "$app" python3 scripts/backup_db.py "/app/data/history_v$source_version.sqlite3" "$destination"
  "${admin[@]}" install -d -m 700 "$private"
  docker_cmd cp "$app:$destination" "$private/source.sqlite3"
  "${admin[@]}" chmod 600 "$private/source.sqlite3"
  printf '数据库快照：%s/source.sqlite3；备份卷中保留 %s。含账号等私密信息，不含任务目录，请另存受控异机。\n' "$private" "$destination"
}

management_check_units() {
  # Only manage the supplied standard unit; never overwrite another project's scheduler.
  [[ $project_dir == /opt/lottery-simulator && $project_name == lottery-simulator ]] || { printf '定时备份示例仅支持/opt/lottery-simulator及默认项目名；自定义调度需人工处理。\n' >&2; exit 1; }
  deployment_check_timer || exit 1
  if [[ $timer_state == not-found ]]; then
    local service_load
    service_load=$(deployment_unit_property lottery-backup.service LoadState) || exit 1
    case $service_load in
      not-found) ;;
      loaded) deployment_check_service || exit 1;;
      *) printf '备份service状态未知，停止操作。\n' >&2; exit 1;;
    esac
  fi
}

management_schedule() {
  [[ $source_version == 6 ]] || { printf '先完成v6升级，不能给v5安装v6备份配置。\n' >&2; exit 1; }
  [[ -f deploy/lottery-backup.service && -f deploy/lottery-backup.timer ]] || { printf '缺少备份unit示例文件。\n' >&2; exit 1; }
  management_check_units
  [[ $(command -v docker) == /usr/bin/docker ]] || { printf 'Docker路径不是unit标准路径，需人工适配。\n' >&2; exit 1; }
  management_confirm BACKUP '将备份现有标准unit，安装仓库v6每日备份配置，并实际执行一次备份；确认没有需保留的自定义参数。'
  management_pause_timer
  local private unit
  private="/var/backups/lottery/$project_name/units-$(date +%Y%m%d-%H%M%S-%N)"
  "${admin[@]}" install -d -m 700 "$private"
  for unit in lottery-backup.service lottery-backup.timer; do
    if "${admin[@]}" test -f "/etc/systemd/system/$unit"; then "${admin[@]}" cp "/etc/systemd/system/$unit" "$private/$unit"; fi
    "${admin[@]}" install -m 644 "deploy/$unit" "/etc/systemd/system/$unit"
  done
  "${admin[@]}" systemctl daemon-reload
  management_resume
}

management_resume() {
  management_check_units
  [[ $timer_state == loaded && $source_version == 6 ]] || { printf '未安装本项目标准v6 timer；请先配置每日备份。\n' >&2; exit 1; }
  management_confirm VERIFIED '确认业务和HTTPS已验收；将实际执行一次备份，成功后启用每日timer。'
  "${admin[@]}" systemctl start lottery-backup.service
  [[ $("${admin[@]}" systemctl show lottery-backup.service --property=Result --value) == success ]] || exit 1
  "${admin[@]}" journalctl -u lottery-backup.service -n 20 --no-pager
  "${admin[@]}" systemctl enable --now lottery-backup.timer
  "${admin[@]}" systemctl list-timers lottery-backup.timer
}

management_uninstall() {
  local removal name volume private container containers networks network
  removal=1
  networks=$(docker_cmd network ls -q --filter "label=com.docker.compose.project=$project_name")
  for network in $networks; do
    docker_cmd network inspect "$network" | python3 -c '
import json,sys
n,=json.load(sys.stdin); project,app,caddy=sys.argv[1:]; logical=n["Labels"]["com.docker.compose.network"]
assert n["Labels"]["com.docker.compose.project"]==project and logical in {"default","backend"} and n["Name"]==f"{project}_{logical}", "非标准项目网络"
assert all(cid.startswith((app,caddy)) for cid in n.get("Containers",{})), "网络存在其它容器"
' "$project_name" "$app" "$caddy"
  done
  management_confirm UNINSTALL '将停止本项目并移除原app/Caddy容器；timer保持暂停。保留数据卸载后，需按明确版本重新部署，启动菜单不会创建新容器。'
  if [[ $removal == 1 ]]; then
    local image
    image=$(docker_cmd inspect --format '{{.Image}}' "$app")
    [[ $image =~ ^sha256:[a-f0-9]{64}$ ]] || exit 1
    docker_cmd run --rm --pull never --network none --entrypoint python "$image" \
      -c 'from dashboard.job_models import JobState, read_json; from scripts.backup_db import backup_database'
    private="/var/backups/lottery/$project_name/uninstall-$(date +%Y%m%d-%H%M%S-%N)"
    "${admin[@]}" install -d -m 700 "$private"
    docker_cmd inspect "$app" "$caddy" | "${admin[@]}" tee "$private/containers.json" >/dev/null
    "${admin[@]}" cp -- .env "$private/env.snapshot"
    printf '原容器身份与环境副本：%s；含凭据，不公开。数据仍留在原卷。\n' "$private"
  fi
  management_stop
  if [[ $timer_load == loaded ]]; then "${admin[@]}" systemctl disable lottery-backup.timer; fi
  docker_cmd rm "$app" "$caddy"
  for network in $networks; do docker_cmd network rm "$network"; done
  printf '卸载完成；代码、Docker、其他项目及外部备份未删除。\n'
}

management_private() {
  # Recheck the fixed parent immediately before deletion; never follow symlinked trees.
  "${admin[@]}" python3 - "$@" <<'PY'
from pathlib import Path
import shutil, sys
from scripts.deployment_resources import check_private_tree
action, raw_private, raw_env = sys.argv[1:]
private, env = Path(raw_private), Path(raw_env)
assert action in {'check','delete'} and private.parent == Path('/var/backups/lottery') and env == Path.cwd()/'.env', '删除路径超出固定边界'
for path in (private.parent.parent, private.parent, private, env):
    if path.is_symlink(): raise SystemExit('私有路径被重定向，拒绝删除')
assert env.is_file() and not env.is_symlink(), '.env缺失或被重定向'
check_private_tree(private)
if action == 'delete':
    if private.exists(): shutil.rmtree(private)
    env.unlink(missing_ok=True)
PY
}

management_legacy_snapshot() {
  local args=(--project-dir "$project_dir" --docker "$(command -v docker)")
  "${admin[@]}" python3 scripts/deployment_resources.py "${args[@]}"
}

management_legacy_preflight() {
  stage='预检目标版本和运行环境'
  for file in docker-compose.yml Dockerfile Caddyfile manage.py requirements.txt \
    configs/pools/default.json configs/rules/zmd.json frontend/package.json \
    frontend/package-lock.json scripts/install.sh scripts/manage.sh \
    scripts/deployment_checks.sh scripts/deployment_resources.py \
    scripts/check_proxy_network.py scripts/backup_db.py; do
    [[ -f $file ]] || { printf '缺少目标版本文件：%s。\n' "$file" >&2; return 1; }
  done
  for tool in git openssl; do command -v "$tool" >/dev/null || return 1; done
  management_legacy_context || return 1
  docker_cmd compose version >/dev/null || return 1
  docker_cmd buildx version >/dev/null || return 1
  local target_config
  target_config=$("${admin[@]}" env DOMAIN=preflight.invalid SECRET_KEY=preflight-only docker compose config --format json) || return 1
  legacy_target_project=$(python3 -c 'import json,re,sys; name=json.load(sys.stdin)["name"]; assert isinstance(name,str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]*",name); print(name)' <<< "$target_config") || return 1
  local proxy_settings
  proxy_settings=$(printf '%s' "$target_config" | python3 -c '
import json, sys
config=json.load(sys.stdin)
backend=config["networks"]["backend"]["ipam"]["config"][0]
values=(backend["subnet"],backend["ip_range"],backend["gateway"],
        config["services"]["caddy"]["networks"]["backend"]["ipv4_address"])
assert all(isinstance(x,str) and x and not any(ch.isspace() for ch in x) for x in values)
print("\t".join(values))
') || return 1
  IFS=$'\t' read -r legacy_proxy_subnet legacy_proxy_range legacy_proxy_gateway legacy_proxy_ip <<< "$proxy_settings"
  printf '%s' "$target_config" | "${admin[@]}" python3 scripts/check_proxy_network.py \
    --project "$legacy_target_project" --docker "$(command -v docker)" || return 1
  docker_cmd pull node:22-bookworm-slim || return 1
  "${admin[@]}" env DOMAIN=preflight.invalid SECRET_KEY=preflight-only docker compose pull caddy || return 1
  "${admin[@]}" env DOMAIN=preflight.invalid SECRET_KEY=preflight-only docker compose build app || return 1
  docker_cmd run --rm --user "$(id -u):$(id -g)" \
    -v "$project_dir/frontend:/src:ro" -v "$project_dir/configs:/tmp/configs:ro" \
    -w /tmp/frontend node:22-bookworm-slim sh -c \
    'mkdir -p /tmp/frontend && tar --exclude=node_modules --exclude=dist -C /src -cf - . | tar -C /tmp/frontend -xf - && npm ci && npm run build' || return 1
}

management_legacy_context() {
  for tool in docker python3 systemctl; do command -v "$tool" >/dev/null || return 1; done
  local endpoint
  if [[ -n ${DOCKER_CONTEXT:-} ]]; then
    endpoint=$(docker_cmd context inspect "$DOCKER_CONTEXT" --format '{{.Endpoints.docker.Host}}') || return 1
  else
    endpoint=${DOCKER_HOST:-$(docker_cmd context inspect --format '{{.Endpoints.docker.Host}}')} || return 1
  fi
  [[ $endpoint == unix:///var/run/docker.sock || $endpoint == unix:///run/docker.sock ]] || { printf '仅支持本机Docker。\n' >&2; return 1; }
  docker_cmd info >/dev/null || return 1
}

management_legacy_run() {
  local outcome=$1 snapshot current private cid name new_project active resources kind value
  local -a containers volumes networks
  legacy_deleted=''
  management_admin || return 1
  if [[ $outcome == reinstall ]]; then
    management_legacy_preflight || return 1
  else
    management_legacy_context || return 1
  fi
  stage='核对旧项目资源和备份调度'
  snapshot=$(management_legacy_snapshot) || return 1
  project_name=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["project"])' <<< "$snapshot") || return 1
  if [[ $outcome == reinstall && $project_name != "$legacy_target_project" ]]; then
    printf '目标Compose项目与原资源项目不一致，停止自动重装。\n' >&2
    return 1
  fi
  private="/var/backups/lottery/$project_name"
  management_private check "$private" "$project_dir/.env" || return 1
  deployment_check_timer || return 1
  resources=$(printf '%s' "$snapshot" | python3 -c '
import json, re, sys
document = json.load(sys.stdin)
for kind, key, pattern in (("container", "containers", r"[0-9a-f]{12,64}"),
                           ("volume", "volumes", r"[A-Za-z0-9][A-Za-z0-9_.-]*"),
                           ("network", "networks", r"[A-Za-z0-9][A-Za-z0-9_.-]*")):
    group = document[key]
    if not isinstance(group, dict): raise ValueError(f"{key} must be a mapping")
    for name in group:
        if not isinstance(name, str) or not re.fullmatch(pattern, name):
            raise ValueError(f"invalid {kind} target")
        print(f"{kind}\t{name}")
') || return 1
  while IFS=$'\t' read -r kind value; do
    [[ -n $kind ]] || continue
    case $kind in
      container) containers+=("$value");;
      volume) volumes+=("$value");;
      network) networks+=("$value");;
      *) printf '资源清单类型异常，停止操作。\n' >&2; return 1;;
    esac
  done <<< "$resources"
  printf '永久删除清单（项目 %s，目录 %s）：\n' "$project_name" "$project_dir"
  printf '  容器：%s\n  网络：%s\n  命名卷：%s\n  文件：%s/.env；%s\n' \
    "${containers[*]:-无}" "${networks[*]:-无}" "${volumes[*]:-无}" "$project_dir" "$private"
  if [[ $outcome == reinstall ]]; then
    new_project=$project_name
    printf '删除后首次安装项目名：%s；将生成新密钥、空v6数据库和新管理员。\n' "$new_project"
  fi
  printf '原账号、业务、Trace、未完成任务、备份和证书将丢失；请先另存必要备份。代码、前端产物、unit定义、Docker及镜像保留。\n'
  management_confirm UNINSTALL '确认永久卸载以上本项目资源。'
  management_confirm "DELETE-$project_name" '再次确认实际项目名；取消不会停止服务。'
  stage='临执行复查资源归属与共享使用者'
  current=$(management_legacy_snapshot) || return 1
  [[ $current == "$snapshot" ]] || { printf '确认后资源清单变化，停止操作；不会扩大删除范围。\n' >&2; return 1; }
  management_private check "$private" "$project_dir/.env" || return 1
  deployment_check_timer || return 1
  stage='停止本项目备份调度'
  if [[ $timer_state == loaded ]]; then
    "${admin[@]}" systemctl stop lottery-backup.timer || return 1
    active=$(deployment_unit_property lottery-backup.timer ActiveState) || return 1
    [[ $active == inactive ]] || return 1
    active=$(deployment_unit_property lottery-backup.service ActiveState) || return 1
    [[ $active == inactive || $active == failed ]] || { printf '备份仍在执行，停止清理。\n' >&2; return 1; }
    "${admin[@]}" systemctl disable lottery-backup.timer || return 1
  fi
  stage='停止和清理旧容器'
  for cid in "${containers[@]}"; do docker_cmd stop --timeout 120 "$cid" || return 1; done
  for cid in "${containers[@]}"; do
    docker_cmd rm "$cid" || return 1
    legacy_deleted="$legacy_deleted 容器:$cid"
  done
  stage='清理旧网络'
  for name in "${networks[@]}"; do docker_cmd network rm "$name" || return 1; legacy_deleted="$legacy_deleted 网络:$name"; done
  stage='清理受管命名卷'
  for name in "${volumes[@]}"; do docker_cmd volume rm "$name" || return 1; legacy_deleted="$legacy_deleted 卷:$name"; done
  stage='清理受管私有文件'
  management_private delete "$private" "$project_dir/.env" || return 1
  legacy_deleted="$legacy_deleted 文件:$project_dir/.env,$private"
  stage='核对清理结果和端口'
  management_legacy_cleared "$project_name" "$project_dir" "${volumes[@]}" "${networks[@]}" || return 1
  printf '已清理：%s\n' "${legacy_deleted:-无}"
  if [[ $outcome == reinstall ]]; then
    stage='全新安装空v6与新管理员'
    COMPOSE_PROJECT_NAME="$project_name" \
      LOTTERY_PROXY_SUBNET="$legacy_proxy_subnet" \
      LOTTERY_PROXY_DYNAMIC_RANGE="$legacy_proxy_range" \
      LOTTERY_PROXY_GATEWAY="$legacy_proxy_gateway" \
      LOTTERY_CADDY_IP="$legacy_proxy_ip" \
      bash "$project_dir/scripts/install.sh" --install || return 1
  fi
}

management_legacy_cleared() {
  local project=$1 directory=$2 name; shift 2
  local remaining found
  remaining=$(docker_cmd ps -aq --filter "label=com.docker.compose.project=$project") || return 1
  [[ -z $remaining ]] || { printf '仍有项目容器，停止安装。\n' >&2; return 1; }
  remaining=$(docker_cmd volume ls -q --filter "label=com.docker.compose.project=$project") || return 1
  [[ -z $remaining ]] || { printf '仍有项目命名卷，停止安装。\n' >&2; return 1; }
  remaining=$(docker_cmd network ls -q --filter "label=com.docker.compose.project=$project") || return 1
  [[ -z $remaining ]] || { printf '仍有项目网络，停止安装。\n' >&2; return 1; }
  for name in "$@"; do
    if [[ $name == "${project}_"* ]]; then
      found=$(docker_cmd volume ls -q --filter "name=^${name}$") || return 1
      [[ -z $found ]] || { printf '卷仍存在：%s\n' "$name" >&2; return 1; }
      found=$(docker_cmd network ls -q --filter "name=^${name}$") || return 1
      [[ -z $found ]] || { printf '网络仍存在：%s\n' "$name" >&2; return 1; }
    fi
  done
  [[ ! -e $directory/.env && ! -L $directory/.env && ! -e /var/backups/lottery/$project && ! -L /var/backups/lottery/$project ]] || return 1
  management_legacy_ports
}

management_legacy_ports() {
  "${admin[@]}" python3 - <<'PY'
import errno, socket
for port in (80, 443):
    for family, host in ((socket.AF_INET, '0.0.0.0'), (socket.AF_INET6, '::')):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.bind((host, port))
        except OSError as exc:
            if family == socket.AF_INET6 and exc.errno in (errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT, errno.EADDRNOTAVAIL):
                continue
            raise SystemExit(f'端口{port}不可用：{exc}')
PY
}

management_update() {
  printf '1) 当前v6保留数据更新：拉取Git\n2) 当前v6保留数据更新：已下载版本\n3) 旧版永久卸载重装：拉取Git\n4) 旧版永久卸载重装：已下载版本\n'
  local selection top branch status
  read -r -p '请选择更新方式：' selection
  case $selection in
    1|3)
      top=$(git rev-parse --show-toplevel)
      branch=$(git branch --show-current)
      status=$(git status --porcelain)
      [[ $top == "$project_dir" && $branch == master && -z $status ]] || { printf '需要本目录干净的master工作区；先保存本地修改。\n' >&2; exit 1; }
      case $(git remote get-url origin) in
        https://github.com/donotwantorange/lottery_simulator.git|git@github.com:donotwantorange/lottery_simulator.git) ;;
        *) printf 'origin不是预期仓库，停止自动更新。\n' >&2; exit 1;;
      esac
      management_confirm UPDATE '将从origin/master快进更新代码，再运行新版目标流程。失败保留现场；不会强制覆盖工作区。'
      printf '旧提交：'; git rev-parse HEAD
      git pull --ff-only origin master;;
    2|4) ;;
    *) printf '已取消。\n'; return;;
  esac
  if [[ $selection == 3 || $selection == 4 ]]; then
    exec bash "$project_dir/scripts/install.sh" --legacy-reinstall
  else
    exec bash "$project_dir/scripts/install.sh" --upgrade
  fi
}
