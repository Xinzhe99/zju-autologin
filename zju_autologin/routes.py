"""门户直连路由（Windows，需管理员确认）：为门户 IP 添加持久化 /32 主机路由。

TUN/全局 VPN 会在 IP 层接管默认路由，应用层无法绕过；此操作在路由表中为
门户 IP 写一条经物理网关的直连路由（PersistentStore，重启保留），使认证
流量绕过 VPN。提供对应的移除方法。仅对门户的公网 IP 生效，不影响其他流量。
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.parse

# 常见虚拟网卡/代理 TUN 适配器名，寻找物理默认网关时排除
_VIRTUAL_HINT = "Clash|TUN|WireGuard|utun|Meta|mihomo|sing-box|v2ray|tun|Virtual|VMware|Hyper-V|WSL"


def portal_ips(base_url: str) -> list[str]:
    """解析门户的公网 IPv4（内网/回环地址不需要直连路由）。"""
    host = urllib.parse.urlsplit(base_url).hostname or ""
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
    except (OSError, socket.gaierror):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for info in infos:
        ip = info[4][0]
        if ip in seen:
            continue
        seen.add(ip)
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_private or addr.is_link_local:
            continue
        out.append(ip)
    return out


def route_script(ips: list[str], remove: bool = False) -> str:
    """生成添加/移除直连路由的 PowerShell 脚本。"""
    lines = ["$ErrorActionPreference = 'SilentlyContinue'"]
    if remove:
        for ip in ips:
            lines.append(
                f"Remove-NetRoute -DestinationPrefix '{ip}/32' -Confirm:$false "
                "-PolicyStore All -ErrorAction SilentlyContinue"
            )
        # 验证路由确已移除, 否则非零退出让 Python 侧报失败
        for ip in ips:
            lines.append(
                f"if (Get-NetRoute -DestinationPrefix '{ip}/32') {{ exit 2 }}"
            )
    else:
        lines.append(
            "$lan = Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
            f"Where-Object {{ $_.InterfaceAlias -notmatch '{_VIRTUAL_HINT}' }} | "
            "Sort-Object { $_.RouteMetric + $_.InterfaceMetric } | Select-Object -First 1"
        )
        lines.append("if (-not $lan) { exit 1 }")
        for ip in ips:
            lines.append(
                f"New-NetRoute -DestinationPrefix '{ip}/32' -InterfaceIndex $lan.InterfaceIndex "
                "-NextHop $lan.NextHop -RouteMetric 1 -PolicyStore PersistentStore "
                "-ErrorAction SilentlyContinue"
            )
        # 验证路由确已写入, 否则非零退出让 Python 侧报失败
        for ip in ips:
            lines.append(
                f"if (-not (Get-NetRoute -DestinationPrefix '{ip}/32')) {{ exit 2 }}"
            )
    return "\n".join(lines) + "\n"


def _valid_ips(raw) -> list[str]:
    """过滤出合法 IPv4; 防止配置文件被篡改后把任意字符串拼入提权脚本。

    IPv6 必须排除: 脚本里前缀固定写 /32, '::1/32' 这种前缀非法, 会让删除
    路由的命令整条失败, 残留路由再也清不掉。
    """
    import ipaddress

    out = []
    for ip in raw or []:
        try:
            addr = ipaddress.ip_address(str(ip).strip())
        except ValueError:
            continue
        if addr.version != 4:
            continue
        out.append(str(addr))
    return out


def add_direct_routes(cfg) -> tuple[bool, str]:
    """为门户 IP 添加持久化直连路由（弹 UAC）。返回 (成功?, 说明)。"""
    import sys

    if sys.platform != "win32":
        return False, "windows only"
    ips = portal_ips(cfg.base_url)
    if not ips:
        return False, "no-portal-ip"
    from .service import _run_elevated_ps

    ok, detail = _run_elevated_ps(route_script(ips))
    if not ok:
        return False, detail or "elevation failed"
    cfg.portal_route_ips = ips
    cfg.portal_route_added = True
    cfg.save()
    return True, " ".join(ips)


def remove_direct_routes(cfg) -> tuple[bool, str]:
    """移除已添加的门户直连路由（弹 UAC）。"""
    import sys

    if sys.platform != "win32":
        return False, "windows only"
    ips = _valid_ips(cfg.portal_route_ips) or portal_ips(cfg.base_url)
    if not ips:
        return False, "no-ips-recorded"
    from .service import _run_elevated_ps

    ok, detail = _run_elevated_ps(route_script(ips, remove=True))
    if not ok:
        return False, detail or "elevation failed"
    cfg.portal_route_added = False
    cfg.portal_route_ips = []
    cfg.save()
    return True, " ".join(ips)
