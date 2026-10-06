# Sourced by install.sh --upgrade; no package installation or automatic Git pull.
prepare_upgrade() {
  stage='核对已有部署'
  for tool in docker python3 ip tar systemctl timeout; do
    command -v "$tool" >/dev/null || { printf '缺少升级工具：%s；请先手动安装。\n' "$tool" >&2; exit 1; }
  done
  [[ -f .env ]] || { printf '升级必须保留原 .env，不能自动生成新密钥。\n' >&2; exit 1; }
  if [[ -n ${DOCKER_CONTEXT:-} ]]; then
    docker_endpoint=$(docker_cmd context inspect "$DOCKER_CONTEXT" --format '{{.Endpoints.docker.Host}}')
  else
    docker_endpoint=${DOCKER_HOST:-$(docker_cmd context inspect --format '{{.Endpoints.docker.Host}}')}
  fi
  [[ $docker_endpoint == unix:///var/run/docker.sock || $docker_endpoint == unix:///run/docker.sock ]] || { printf '请在服务器本机使用标准Docker服务执行；远程或rootless上下文需手动处理。\n' >&2; exit 1; }
  docker_cmd info >/dev/null
  docker_cmd compose config --quiet
  project_name=$(docker_cmd compose config --format json | python3 -c '
import json,sys
config=json.load(sys.stdin); project=config["name"]
assert set(config["services"])=={"app","caddy"}, "只支持标准app/Caddy两服务部署"
assert not config["services"]["app"].get("ports") and set(config["services"]["app"]["networks"])=={"backend"}, "新版app必须仅在内部backend网络"
assert config["services"]["app"]["environment"]["LOTTERY_DB_PATH"]=="/app/data/history_v6.sqlite3", "新版必须使用v6目标路径"
for name in ("lottery_data","lottery_backups","caddy_data","caddy_config"):
    volume=config["volumes"][name]
    assert volume["name"]==f"{project}_{name}" and not volume.get("external"), "新版不能改接其它持久卷"
for service,expected in (("app",{"/app/data":"lottery_data","/app/backups":"lottery_backups"}), ("caddy",{"/data":"caddy_data","/config":"caddy_config"})):
    mounts={m["target"]:m for m in config["services"][service]["volumes"]}
    assert all(mounts[p]["type"]=="volume" and mounts[p]["source"]==n for p,n in expected.items()), "新版卷映射不匹配"
print(project)
')
  [[ $project_name =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { printf 'Compose项目名无效。\n' >&2; exit 1; }
  app=$(docker_cmd ps -q --filter "label=com.docker.compose.project=$project_name" --filter 'label=com.docker.compose.service=app')
  caddy=$(docker_cmd ps -q --filter "label=com.docker.compose.project=$project_name" --filter 'label=com.docker.compose.service=caddy')
  [[ $app =~ ^[a-f0-9]+$ && $caddy =~ ^[a-f0-9]+$ ]] || { printf '升级需要本项目各一个运行中的app/Caddy；停止或部分安装请手动恢复。\n' >&2; exit 1; }
  metadata=$(docker_cmd inspect "$app" "$caddy" | python3 -c '
import json,re,sys
app,caddy=json.load(sys.stdin)
project,directory=sys.argv[1:]
for item in (app,caddy):
    labels=item["Config"]["Labels"]
    assert labels["com.docker.compose.project"]==project and labels["com.docker.compose.project.working_dir"]==directory, "容器不属于本安装目录"
    assert item["State"]["Running"], "容器未运行"
assert app["State"].get("Health",{}).get("Status")=="healthy", "旧app尚未健康"
assert app["HostConfig"].get("NetworkMode")!="host" and not str(app["HostConfig"].get("NetworkMode","")).startswith("container:"), "app不在独立容器网络"
assert not any((app["HostConfig"].get("PortBindings") or {}).values()), "app发布了宿主端口；不能建立维护隔离"
assert set(app["NetworkSettings"]["Networks"]) in ({f"{project}_default"},{f"{project}_backend"}), "旧app有非标准网络连接"
env=dict(x.split("=",1) for x in app["Config"]["Env"] if "=" in x)
version=next((v for v in (5,6) if env.get("LOTTERY_DB_PATH")==f"/app/data/history_v{v}.sqlite3"),None)
assert version and env.get("LOTTERY_DATA_DIR")=="/app/data", "只支持标准v5/v6数据路径"
assert env.get("LOTTERY_JOBS_DIR")==f"/app/data/jobs_v{version}" and env.get("LOTTERY_EXPORTS_DIR")==f"/app/data/exports_v{version}", "任务/导出路径非标准配置"
mounts={m["Destination"]:m for m in app["Mounts"]}
assert set(mounts)=={"/app/data","/app/backups"}, "旧app有额外挂载，需手动升级"
for destination,name in (("/app/data","lottery_data"),("/app/backups","lottery_backups")):
    assert mounts[destination]["Type"]=="volume" and mounts[destination]["Name"]==f"{project}_{name}", "只支持本项目标准命名卷"
assert app["Config"]["WorkingDir"]=="/app", "旧镜像工作目录非标准配置"
mounts={m["Destination"]:m for m in caddy["Mounts"]}
assert set(mounts)=={"/data","/config","/srv","/etc/caddy/Caddyfile"}, "旧Caddy有非标准挂载"
for destination,name in (("/data","caddy_data"),("/config","caddy_config")):
    assert mounts[destination]["Type"]=="volume" and mounts[destination]["Name"]==f"{project}_{name}", "旧证书卷与新配置不一致"
assert mounts["/srv"]["Type"]=="bind" and mounts["/srv"]["Source"]==directory+"/frontend/dist", "旧前端挂载不是本目录产物"
assert mounts["/etc/caddy/Caddyfile"]["Type"]=="bind" and mounts["/etc/caddy/Caddyfile"]["Source"]==directory+"/Caddyfile", "旧Caddyfile挂载不是本目录配置"
assert re.fullmatch(r"sha256:[a-f0-9]{64}",app["Image"]), "无法确定旧镜像身份"
print(version, app["Image"])
' "$project_name" "$project_dir")
  read -r source_version old_image <<< "$metadata"
  # Never down an unexpected service or an orphan from the same project.
  services=$(docker_cmd ps -a --filter "label=com.docker.compose.project=$project_name" --format '{{.ID}}')
  for container in $services; do
    [[ $container == "$app" || $container == "$caddy" ]] || { printf '项目含其它容器；请先人工核对，不自动清理。\n' >&2; exit 1; }
  done
  # A running container can outlive its image; verify helper creation before maintenance.
  if ! docker_cmd run --rm --pull never --network none --entrypoint python "$old_image" \
    -c 'from dashboard.job_models import JobState, read_json; from scripts.backup_db import backup_database'; then
    printf '旧镜像无法启动备份辅助容器：%s。尚未暂停备份或停止网站；保留旧app，先恢复对应旧镜像，不使用新版镜像替代。\n' "$old_image" >&2
    exit 1
  fi
  printf '升级目录：%s\nCompose项目：%s\n当前数据：v%s\n' "$project_dir" "$project_name" "$source_version"
  printf '请安排维护窗口，停止用户提交并等待任务结束。脚本会备份、停止服务、重建本项目网络，保留原卷/.env/证书。\n'
  if [[ $source_version == 5 ]]; then
    printf 'v5升级仅导入账号和登录限制；旧池、配置、历史、Trace和会话不迁入，原v5材料继续保留。\n'
    read -r -p '接受上述迁移范围请输入 ACCOUNTS：' answer
    [[ $answer == ACCOUNTS ]] || { printf '已取消升级。\n'; exit 1; }
  fi
  read -r -p '确认维护及升级请输入 UPGRADE：' answer
  [[ $answer == UPGRADE ]] || { printf '已取消升级。\n'; exit 1; }
  stage='暂停备份调度'
  timer_state=$("${admin[@]}" systemctl show lottery-backup.timer --property=LoadState --value)
  if [[ $timer_state != not-found ]]; then
    [[ $timer_state == loaded ]] || { printf '备份timer状态未知，已停止升级。\n' >&2; exit 1; }
    "${admin[@]}" systemctl stop lottery-backup.timer
    [[ $("${admin[@]}" systemctl show lottery-backup.timer --property=ActiveState --value) == inactive ]] || { printf '备份timer尚未停止。\n' >&2; exit 1; }
  fi
  backup_state=$("${admin[@]}" systemctl show lottery-backup.service --property=ActiveState --value)
  [[ $backup_state == inactive || $backup_state == failed ]] || { printf '备份服务仍活动或状态未知，请等待并核对。\n' >&2; exit 1; }
  stage='阻止新请求并检查旧任务'
  docker_cmd compose stop caddy
  docker_cmd exec -i "$app" python - probe "$source_version" < scripts/upgrade_probe.py
  stage='备份旧数据库与运行材料'
  "${admin[@]}" install -d -m 700 "/var/backups/lottery/$project_name"
  backup_dir=$("${admin[@]}" mktemp -d "/var/backups/lottery/$project_name/upgrade-$(date +%Y%m%d-%H%M%S)-XXXXXX")
  snapshot=$(basename "$backup_dir")
  container_backup="/app/backups/$snapshot"
  # Freeze late in-flight requests; recheck using the OLD image and frozen data.
  docker_cmd pause "$app"
  upgrade_paused=1
  upgrade_helper_cid="$backup_dir/probe.cid"
  "${admin[@]}" timeout --kill-after=10 600 "$(command -v docker)" run --rm --pull never -i \
    --cidfile "$upgrade_helper_cid" --network none --workdir /app --entrypoint python \
    -v "${project_name}_lottery_data:/app/data:ro" \
    -v "${project_name}_lottery_backups:/app/backups" \
    "$old_image" - backup "$source_version" "$container_backup" < scripts/upgrade_probe.py
  upgrade_helper_cid=''
  docker_cmd cp "$app:$container_backup/source.sqlite3" "$backup_dir/source.sqlite3"
  "${admin[@]}" python3 -c 'import pathlib,sqlite3,sys; p=pathlib.Path(sys.argv[1]); db=sqlite3.connect(p.as_uri()+"?mode=ro",uri=True); assert db.execute("PRAGMA integrity_check").fetchall()==[("ok",)]; db.close()' "$backup_dir/source.sqlite3"
  "${admin[@]}" cp -- .env "$backup_dir/env.snapshot"
  docker_cmd inspect "$app" "$caddy" | "${admin[@]}" tee "$backup_dir/containers.json" >/dev/null
  docker_cmd compose config --format json | "${admin[@]}" tee "$backup_dir/new-compose.json" >/dev/null
  "${admin[@]}" tar -C "$project_dir" -czf "$backup_dir/frontend-dist.tar.gz" frontend/dist
  docker_cmd cp "$app:/app/data/." "$backup_dir/data"
  "${admin[@]}" chmod -R go-rwx "$backup_dir"
  printf '私有备份：%s（包含凭据，不公开或提交Git）\n' "$backup_dir"
  stage='重建本项目服务网络'
  docker_cmd rm --force "$app"  # Frozen, rechecked and backed up; never remove its volumes.
  upgrade_paused=0
  docker_cmd compose down  # No -v, no orphan removal; original named volumes survive.
}

upgrade_database() {
  stage='迁移v6数据库'
  docker_cmd compose run --rm app python manage.py migrate
  if [[ $source_version == 5 ]]; then
    stage='只读导入v5账号'
    docker_cmd compose run --rm app python manage.py import_v5_accounts --source "$container_backup/source.sqlite3"
    stage='初始化v6默认业务'
    docker_cmd compose run --rm app python manage.py init_business_defaults
  fi
}

finish_upgrade() {
  printf '\n升级服务已启动，尚需原账号登录、连续实验、Trace、取消和可信公网HTTPS验收。\n'
  printf '原卷/.env/证书与备份保留；失败时不要删除卷或覆盖数据库来重跑。\n'
  if [[ $timer_state == loaded ]]; then
    printf '备份timer保持暂停。标准部署再次运行脚本，选择运维→配置/更新每日备份；自定义unit需人工核对。\n'
    printf '业务与HTTPS验收通过后，选择运维→恢复每日备份；脚本先实际备份，再启用timer。\n'
  fi
  printf '备份与手动恢复边界见docs/deployment.md。脚本没有git pull或自动回滚。\n'
}
