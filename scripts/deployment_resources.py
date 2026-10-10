"""Read-only inventory for an explicitly selected local Compose installation.

The JSON snapshot is also the deletion allow-list.  This module never removes
anything; callers must compare a fresh snapshot immediately before mutation.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


class InventoryError(ValueError):
    pass


def check_private_tree(private, mountinfo=None):
    """Reject redirected or mounted private backup trees and return a metadata snapshot."""
    private = Path(private)
    if not private.is_absolute() or private.is_symlink():
        raise InventoryError("私有备份根路径被重定向")
    try:
        if mountinfo is None:
            mountinfo = Path("/proc/self/mountinfo").read_text()
    except OSError as exc:
        raise InventoryError("无法读取挂载状态") from exc
    if not mountinfo.strip():
        raise InventoryError("挂载状态为空")
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if not separator or len(fields) < 6 or len(after.split()) < 3:
            raise InventoryError("挂载状态格式异常")
        encoded = fields[4]
        decoded = re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), encoded)
        if "\\" in decoded or not decoded.startswith("/"):
            raise InventoryError("挂载点路径无法解析")
        mountpoint = Path(decoded)
        if mountpoint == private or private in mountpoint.parents:
            raise InventoryError("私有备份树包含挂载点；需人工处理")
    if private.exists() and not private.is_dir():
        raise InventoryError("私有备份路径不是目录")
    files = {}
    if not private.exists():
        return files
    root_stat = private.stat()
    files["."] = [root_stat.st_dev, root_stat.st_ino, root_stat.st_size, root_stat.st_mtime_ns]
    def walk_error(exc):
        raise InventoryError("私有备份目录读取失败") from exc
    for base, dirs, names in os.walk(private, followlinks=False, onerror=walk_error):
        for name in [*dirs, *names]:
            path = Path(base, name)
            if path.is_symlink():
                raise InventoryError("私有备份目录中存在符号链接")
            stat = path.stat()
            if stat.st_dev != root_stat.st_dev:
                raise InventoryError("私有备份树跨越文件系统")
            files[str(path.relative_to(private))] = [stat.st_dev, stat.st_ino,
                                                      stat.st_size, stat.st_mtime_ns]
    return files


def inventory(project_dir, docker=("docker",), run=subprocess.run,
              backup_parent=Path("/var/backups/lottery")):
    directory = str(Path(project_dir).resolve(strict=True))
    if directory != str(Path(project_dir)):
        raise InventoryError("安装目录必须是已解析的绝对路径")
    env = Path(directory, ".env")
    if env.is_symlink() or not env.is_file():
        raise InventoryError("原.env缺失或被重定向")

    def call(*args):
        variables = dict(os.environ)
        if args[:2] == ("compose", "config"):
            variables.update(DOMAIN="preflight.invalid", SECRET_KEY="preflight-only")
        result = run([*docker, *args], cwd=directory, capture_output=True,
                     text=True, env=variables)
        if result.returncode:
            raise InventoryError("Docker状态读取失败：" + " ".join(args[:3]))
        return result.stdout

    def ids(*args, hex_ids=True):
        values = call(*args).splitlines()
        pattern = r"[0-9a-f]{12,64}" if hex_ids else r"[A-Za-z0-9][A-Za-z0-9_.-]*"
        if len(set(values)) != len(values) or any(not re.fullmatch(pattern, x) for x in values):
            raise InventoryError("Docker资源ID异常")
        return sorted(values)

    def inspect(kind, identifier):
        args = ("inspect", identifier) if kind == "container" else (kind, "inspect", identifier)
        try:
            item, = json.loads(call(*args))
        except (ValueError, TypeError) as exc:
            raise InventoryError("Docker资源详情读取失败") from exc
        if not isinstance(item, dict):
            raise InventoryError("Docker资源详情格式异常")
        return item

    try:
        config = json.loads(call("compose", "config", "--format", "json"))
        project = config["name"]
    except (ValueError, KeyError, TypeError) as exc:
        raise InventoryError("无法从本目录Compose配置确认实际项目名") from exc
    if not isinstance(project, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        raise InventoryError("Compose项目名异常")

    all_ids = ids("ps", "-aq")
    all_containers = {cid: inspect("container", cid) for cid in all_ids}
    owned = {}
    for cid, item in all_containers.items():
        labels = (item.get("Config") or {}).get("Labels") or {}
        if labels.get("com.docker.compose.project") != project:
            continue
        if labels.get("com.docker.compose.project.working_dir") != directory:
            raise InventoryError("同名项目容器属于其它安装目录")
        service = labels.get("com.docker.compose.service")
        if not service or not re.fullmatch(r"[A-Za-z0-9_.-]+", service):
            raise InventoryError("旧容器服务标签异常")
        mounts = item.get("Mounts")
        if not isinstance(mounts, list):
            raise InventoryError("旧容器挂载状态未知")
        for mount in mounts:
            if mount.get("Type") == "bind":
                allowed = {("/srv", directory + "/frontend/dist"),
                           ("/etc/caddy/Caddyfile", directory + "/Caddyfile")}
                if (mount.get("Destination"), mount.get("Source")) not in allowed:
                    raise InventoryError("存在任意宿主机绑定目录；需人工处理")
            elif mount.get("Type") != "volume":
                raise InventoryError("存在未知挂载类型")
        networks = (item.get("NetworkSettings") or {}).get("Networks")
        if not isinstance(networks, dict):
            raise InventoryError("旧容器网络状态未知")
        owned[cid] = {"id": item.get("Id", cid), "name": item.get("Name", ""),
                      "service": service, "labels": labels, "mounts": mounts,
                      "networks": networks}

    volumes = {}
    managed_volumes = {"lottery_data", "lottery_backups", "caddy_data", "caddy_config"}
    declared_volumes = config.get("volumes") or {}
    if not isinstance(declared_volumes, dict):
        raise InventoryError("Compose卷声明异常")
    for vid in ids("volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}", hex_ids=False):
        item = inspect("volume", vid)
        labels = item.get("Labels") or {}
        logical = labels.get("com.docker.compose.volume")
        name = item.get("Name")
        if labels.get("com.docker.compose.project") != project or logical not in managed_volumes or \
           name != f"{project}_{logical}":
            raise InventoryError("命名卷归属或实际名称异常")
        declaration = declared_volumes.get(logical)
        if not isinstance(declaration, dict) or declaration.get("name") != name or declaration.get("external"):
            raise InventoryError("卷没有本目录Compose声明作归属证据")
        users = sorted(cid for cid, container in all_containers.items()
                       if any(m.get("Type") == "volume" and m.get("Name") == name
                              for m in container.get("Mounts", [])))
        if any(cid not in owned for cid in users):
            raise InventoryError("命名卷被其它容器共享")
        volumes[name] = {"name": name, "labels": labels, "users": users}

    networks = {}
    declared_networks = config.get("networks") or {}
    if not isinstance(declared_networks, dict):
        raise InventoryError("Compose网络声明异常")
    for nid in ids("network", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"):
        item = inspect("network", nid)
        labels = item.get("Labels") or {}
        logical = labels.get("com.docker.compose.network")
        name = item.get("Name")
        if labels.get("com.docker.compose.project") != project or not logical or \
           not re.fullmatch(r"[A-Za-z0-9_.-]+", logical) or name != f"{project}_{logical}":
            raise InventoryError("网络归属或实际名称异常")
        declaration = declared_networks.get(logical)
        if not isinstance(declaration, dict) or declaration.get("name") != name or declaration.get("external"):
            raise InventoryError("网络没有本目录Compose声明作归属证据")
        attached = item.get("Containers")
        if not isinstance(attached, dict):
            raise InventoryError("网络使用者状态未知")
        users = sorted(cid for cid, container in all_containers.items()
                       if name in ((container.get("NetworkSettings") or {}).get("Networks") or {}))
        def is_owned(candidate):
            if not isinstance(candidate, str) or not re.fullmatch(r"[0-9a-f]{12,64}", candidate):
                return False
            matches = [record for record in owned.values()
                       if record["id"] == candidate or record["id"].startswith(candidate)]
            return len(matches) == 1
        if any(not is_owned(cid) for cid in [*users, *attached]):
            raise InventoryError("网络被其它容器共享")
        networks[name] = {"id": item.get("Id", nid), "name": name,
                          "labels": labels, "users": users, "attached": sorted(attached)}

    for cid, item in owned.items():
        for mount in item["mounts"]:
            if mount.get("Type") == "volume" and mount.get("Name") not in volumes:
                raise InventoryError("旧容器使用归属不明的卷")
        for name in item["networks"]:
            if name not in networks:
                raise InventoryError("旧容器使用归属不明的网络")
    if not owned and not volumes and not networks:
        raise InventoryError("没有可核对的本项目旧资源；不会凭名称删除")
    parent = Path(backup_parent)
    private = parent / project
    if private.parent != parent or any(path.is_symlink() for path in (parent.parent, parent, private)):
        raise InventoryError("备份路径被重定向")
    files = check_private_tree(private)
    env_stat = env.stat()
    filesystem = {"env": [env_stat.st_dev, env_stat.st_ino, env_stat.st_size,
                           env_stat.st_mtime_ns, hashlib.sha256(env.read_bytes()).hexdigest()],
                  "backup": files}
    return {"project": project, "directory": directory,
            "containers": dict(sorted(owned.items())), "volumes": dict(sorted(volumes.items())),
            "networks": dict(sorted(networks.items())), "filesystem": filesystem}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--sudo", action="store_true")
    args = parser.parse_args()
    try:
        result = inventory(args.project_dir, (("sudo",) if args.sudo else ()) + (args.docker,))
    except (InventoryError, OSError) as exc:
        print(f"资源核对停止：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
