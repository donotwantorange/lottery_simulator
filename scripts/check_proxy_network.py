#!/usr/bin/env python3
"""Fail closed when the dedicated proxy backend overlaps a host or Docker network."""
import argparse
import ipaddress
import json
import subprocess
import sys


def inspect(command):
    return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)


def ipv4_routes(output):
    routes = json.loads(output)
    if not isinstance(routes, list):
        raise ValueError("ip route JSON 必须是数组")
    parsed = []
    for route in routes:
        if not isinstance(route, dict) or not isinstance(route.get("dst"), str):
            raise ValueError("无法解析 IPv4 路由项")
        if route["dst"] == "default":
            parsed.append((None, route))
            continue
        network = ipaddress.ip_network(route["dst"], strict=False)
        if network.version != 4:
            raise ValueError("IPv4 路由输出包含非 IPv4 目标")
        parsed.append((network, route))
    return parsed


def preflight(config, project, docker, route_reader=None):
    networks = config["networks"]
    backend = networks["backend"]
    ipam = backend.get("ipam", {}).get("config", [])
    if len(ipam) != 1 or not backend.get("internal"):
        raise ValueError("backend 必须是 internal 且只配置一个 IPv4 子网")
    raw_subnet = ipam[0]["subnet"]
    subnet = ipaddress.ip_network(raw_subnet, strict=True)
    if str(subnet) != raw_subnet:
        raise ValueError("LOTTERY_PROXY_SUBNET 必须使用规范网络地址")
    caddy_raw = config["services"]["caddy"]["networks"]["backend"]["ipv4_address"]
    caddy_ip = ipaddress.ip_address(caddy_raw)
    if (subnet.version != 4 or caddy_ip.version != 4 or caddy_ip not in subnet or
            str(caddy_ip) != caddy_raw):
        raise ValueError("LOTTERY_CADDY_IP 必须是 LOTTERY_PROXY_SUBNET 内的 IPv4")
    raw_gateway = ipam[0].get("gateway")
    if not isinstance(raw_gateway, str):
        raise ValueError("backend 必须显式配置 IPv4 网关，避免动态范围改变默认网关")
    gateway_ip = ipaddress.ip_address(raw_gateway)
    if (gateway_ip.version != 4 or str(gateway_ip) != raw_gateway or gateway_ip not in subnet
            or gateway_ip in {subnet.network_address, subnet.broadcast_address, caddy_ip}):
        raise ValueError("网关须为子网内的规范 IPv4 地址，且不能占用 Caddy、网络或广播地址")
    reserved = {subnet.network_address, subnet.broadcast_address, gateway_ip}
    if caddy_ip in reserved or subnet.num_addresses < 8:
        raise ValueError("代理地址须避开网络、广播和网关地址，子网至少为 /29")
    raw_range = ipam[0].get("ip_range")
    if not isinstance(raw_range, str):
        raise ValueError("backend 必须配置 app 动态地址范围，避免占用 Caddy 固定地址")
    dynamic_range = ipaddress.ip_network(raw_range, strict=True)
    if (str(dynamic_range) != raw_range or dynamic_range.version != 4
            or not dynamic_range.subnet_of(subnet) or caddy_ip in dynamic_range
            or dynamic_range.num_addresses <= sum(ip in dynamic_range for ip in reserved)):
        raise ValueError("动态地址范围须是子网内的规范 IPv4 范围，排除 Caddy 地址并留有 app 地址")
    ids = subprocess.run([docker, "network", "ls", "-q"], check=True,
                         capture_output=True, text=True).stdout.split()
    existing = inspect([docker, "network", "inspect", *ids]) if ids else []
    backend_name = f"{project}_backend"
    reused_backend = False
    bridge_name = None
    expected_gateway = str(gateway_ip)
    for network in existing:
        labels = network.get("Labels") or {}
        same = network.get("Name") == backend_name and labels.get("com.docker.compose.project") == project and labels.get("com.docker.compose.network") == "backend"
        for entry in network.get("IPAM", {}).get("Config") or []:
            cidr = entry.get("Subnet")
            if not cidr:
                continue
            other = ipaddress.ip_network(cidr, strict=False)
            if subnet.overlaps(other):
                actual_gateway = entry.get("Gateway")
                if (same and other == subnet and network.get("Internal") and
                        network.get("Driver") == "bridge" and actual_gateway == expected_gateway and
                        entry.get("IPRange") == str(dynamic_range)):
                    reused_backend = True
                    bridge_name = (network.get("Options") or {}).get("com.docker.network.bridge.name") or f"br-{network.get('Id', '')[:12]}"
                    if bridge_name == "br-":
                        raise ValueError("無法核对现存 backend 网络的桥接口")
                    continue
                raise ValueError(f"子网 {subnet} 与现存 Docker 网络 {network.get('Name')} ({other}) 重叠")

    routes = route_reader() if route_reader else subprocess.run(
        ["ip", "-4", "-j", "route", "show", "table", "all"],
        check=True, capture_output=True, text=True
    ).stdout
    routes = ipv4_routes(routes) if isinstance(routes, str) else routes
    reused_route_seen = False
    for other, route in routes:
        if other is None:
            continue
        if subnet.overlaps(other):
            dev = route.get("dev")
            route_type = route.get("type", "unicast")
            table = route.get("table", "main")
            own_connected = (reused_backend and other == subnet and dev == bridge_name and
                             route_type == "unicast" and table in ("main", 254) and
                             "gateway" not in route)
            own_gateway = (reused_backend and other == ipaddress.ip_network(f"{gateway_ip}/32") and
                           dev == bridge_name and route_type == "local" and
                           table in ("local", 255) and "gateway" not in route)
            own_broadcast = (reused_backend and other.prefixlen == 32 and
                             other.network_address in (subnet.network_address, subnet.broadcast_address) and
                             dev == bridge_name and route_type == "broadcast" and
                             table in ("local", 255) and "gateway" not in route)
            if own_connected:
                reused_route_seen = True
                continue
            if own_gateway or own_broadcast:
                continue
            raise ValueError(f"子网 {subnet} 与主机路由 {route.get('type', 'unicast')} {other} 重叠")
    if reused_backend and not reused_route_seen:
        raise ValueError("现存 backend 网络未找到匹配子网、网关和桥接口的连接路由")
    return subnet, caddy_ip


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--docker", required=True)
    args = parser.parse_args()
    try:
        config = json.load(sys.stdin)
        subnet, address = preflight(config, args.project, args.docker)
    except (KeyError, TypeError, AttributeError, ValueError, OSError,
            subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"代理网络预检失败或无法读取；请解决冲突后重试：{exc}", file=sys.stderr)
        return 1
    print(f"代理网络预检通过：{subnet}，Caddy {address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
