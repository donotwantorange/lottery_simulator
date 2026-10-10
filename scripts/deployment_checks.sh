# Read-only checks shared by update, management, and removal paths.
deployment_unit_property() {
  local value
  value=$("${admin[@]}" systemctl show "$1" "--property=$2" --value) || {
    printf '无法读取%s的%s；保持服务原状。\n' "$1" "$2" >&2
    return 1
  }
  printf '%s' "$value"
}

deployment_check_unit_file() {
  local unit=$1 path drops reload
  path=$(deployment_unit_property "$unit" FragmentPath) || return 1
  drops=$(deployment_unit_property "$unit" DropInPaths) || return 1
  reload=$(deployment_unit_property "$unit" NeedDaemonReload) || return 1
  [[ $path == "/etc/systemd/system/$unit" && -z $drops && $reload == no ]] || {
    printf '%s存在外来路径或附加配置；保持原状，需人工核对。\n' "$unit" >&2
    return 1
  }
  [[ -f "deploy/$unit" ]] && "${admin[@]}" cmp -s "deploy/$unit" "$path" || {
    printf '%s有效配置与仓库标准定义不符；保持原状。\n' "$unit" >&2
    return 1
  }
}

deployment_check_service() {
  local state directory command
  state=$(deployment_unit_property lottery-backup.service LoadState) || return 1
  [[ $state == loaded ]] || { printf '关联备份service未正常加载。\n' >&2; return 1; }
  deployment_check_unit_file lottery-backup.service || return 1
  directory=$(deployment_unit_property lottery-backup.service WorkingDirectory) || return 1
  [[ $directory == "$project_dir" ]] || { printf '备份service属于其它目录。\n' >&2; return 1; }
  command=$(deployment_unit_property lottery-backup.service ExecStart) || return 1
  python3 - "$command" <<'PY'
import re
import sys
command = sys.argv[1]
match = re.search(r'argv\[\]=([^;]+)', command)
argv = match.group(1).strip() if match else command.strip()
pattern = (r'/bin/sh -c /usr/bin/docker compose exec -T app python3 '
           r'scripts/backup_db\.py /app/data/history_v6\.sqlite3 '
           r'/app/backups/lottery-v6-\$\(date \+%%?F\)\.sqlite3')
if not re.fullmatch(pattern, argv):
    raise SystemExit('备份service执行命令不是本项目标准v6配置；需人工核对。')
PY
}

deployment_check_timer() {
  local unit service_load active
  timer_state=$(deployment_unit_property lottery-backup.timer LoadState) || return 1
  case $timer_state in
    not-found)
      service_load=$(deployment_unit_property lottery-backup.service LoadState) || return 1
      case $service_load in
        not-found) return 0;;
        loaded) deployment_check_service || return 1;;
        *) printf '备份service加载状态未知；保持原状。\n' >&2; return 1;;
      esac
      active=$(deployment_unit_property lottery-backup.service ActiveState) || return 1
      [[ $active == inactive || $active == failed ]] || {
        printf '无timer但备份service仍活动；请等待并核对。\n' >&2
        return 1
      }
      return 0;;
    loaded) ;;
    *) printf '备份timer加载状态未知；保持原状。\n' >&2; return 1;;
  esac
  deployment_check_unit_file lottery-backup.timer || return 1
  unit=$(deployment_unit_property lottery-backup.timer Unit) || return 1
  [[ $unit == lottery-backup.service ]] || { printf 'timer关联其它service；保持原状。\n' >&2; return 1; }
  deployment_check_service
}
