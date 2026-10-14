"""校内直连（Clash 系统代理兼容）：把校内域名/网段加入 Windows 代理例外。

问题背景(几乎困扰每个用 Clash 的同学):
开「系统代理」后, 浏览器把所有流量交给本机 Clash, 再由境外节点去连目标 ——
远程节点根本到不了校园内网, 于是统一认证 / 校内论坛 / 校内邮箱全部打不开,
只能关掉 Clash。

原理: Windows 的代理例外列表(HKCU\\...\\Internet Settings\\ProxyOverride,
即"设置 → 网络 → 代理 → 请勿对以下列表开头的地址使用代理服务器")里列出的
主机不走系统代理。把 `*.zju.edu.cn` 与 `10.*` 加进去, 校内站点就会直连。

两个坑都要处理:
1. Clash 每次开关系统代理都会**整段重写** ProxyOverride(只留它自己的 bypass),
   我们补的条目会被冲掉 —— 所以由监控线程每 3 秒检查一次、缺了就补(只读注册表,
   开销可忽略)。
2. PAC 模式走 AutoConfigURL, 例外列表不生效; TUN 模式连例外机制都绕过 ——
   这两种情况只能提示用户去 Clash 侧加 DIRECT 规则, 检测到时给出一次性建议。

仅改 HKCU(当前用户注册表), 无需管理员; 浏览器自行监听该键, 数秒内生效。
"""

from __future__ import annotations

import ipaddress
import re
import sys
import urllib.parse

# 私网网段主机名前缀(Windows 例外列表按主机名字符串通配, 不支持 CIDR)
_PRIVATE_PREFIXES = ("10.*",)

_INTERNET_SETTINGS = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def _winreg():
    if sys.platform != "win32":
        return None
    try:
        import winreg
        return winreg
    except ImportError:  # pragma: no cover - win32 总有 winreg
        return None


def _read_value(name: str):
    winreg = _winreg()
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS) as key:
            value, _typ = winreg.QueryValueEx(key, name)
            return value
    except OSError:
        return None


def _write_override(value: str) -> bool:
    winreg = _winreg()
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _INTERNET_SETTINGS,
                            0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, value)
        return True
    except OSError:
        return False
    # 刻意不调用 InternetSetOption(SETTINGS_CHANGED) 广播: 那是系统级的一次全量
    # 通知, 新版 WSL 监听到会弹「网络配置更改, 请重启 WSL」(真实反馈)。现代浏览器
    # (Edge/Chrome/Firefox)自己监听该注册表键, 写入后数秒内即自动生效。


def proxy_enabled() -> bool:
    return bool(_read_value("ProxyEnable"))


def pac_mode() -> bool:
    return bool(_read_value("AutoConfigURL"))


# TUN 虚拟网卡的命名特征(按"词"匹配): 早期用子串 "tun" 匹配, 会把几乎每台
# Windows 都有的「Teredo Tunneling Pseudo-Interface」误判成 TUN 接管, 结果系统
# 代理开着也拒绝写例外 —— 校内直连对这些机器整个失效。
_TUN_NAME = re.compile(r"\b(clash|mihomo|meta|sing-?box|wintun|tun\d*|utun\d*)\b", re.I)
_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")


def tun_mode() -> bool:
    """检测 TUN 接管(fake-ip 网段地址, 或已启用且带 IPv4 的 TUN 命名网卡)。"""
    try:
        from PyQt6.QtNetwork import QNetworkInterface
    except ImportError:
        return False
    try:
        for iface in QNetworkInterface.allInterfaces():
            if not iface.flags() & QNetworkInterface.InterfaceFlag.IsUp:
                continue
            v4 = [ip for ip in (e.ip().toString() for e in iface.addressEntries())
                  if _is_ipv4(ip)]
            if not v4:
                continue
            if any(_in_fake_pool(ip) for ip in v4):
                return True  # fake-ip 网段(Clash/mihomo TUN 默认 198.18.0.1)
            # Windows 上 name() 常是 GUID, 描述性名称在 humanReadableName()
            # (早期写成不存在的 humanName(), 首个网卡就抛异常被吞, TUN 检测从未生效)
            if _TUN_NAME.search(iface.name() + " " + iface.humanReadableName()):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


def _is_ipv4(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).version == 4
    except ValueError:
        return False


def _in_fake_pool(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in _FAKE_IP_NET
    except ValueError:
        return False


def campus_suffixes(cfg) -> list[str]:
    """由门户地址推导校内域名后缀, 再叠加用户自填(逗号分隔)。

    例: 门户 https://net.zju.edu.cn → ["zju.edu.cn"], 例外条目为
    *.zju.edu.cn 与 zju.edu.cn; 其他学校(portal.xxx.edu.cn)同理自动适配。
    """
    suffixes: list[str] = []
    host = urllib.parse.urlsplit(str(getattr(cfg, "base_url", "") or "")).hostname or ""
    parts = host.split(".")
    # 门户写成 IP(http://10.0.0.1)时没有域名可推导: 以前会拼出 "*.0.0.1" 这种
    # 无意义条目; 只剩一级(如 portal.cn → "cn")时更危险, 等于整个顶级域都不走代理
    if not _is_ip(host) and len(parts) >= 3:
        suffixes.append(".".join(parts[1:]))  # 去掉首标签 → zju.edu.cn
    for item in str(cfg.data.get("campus_bypass_extra") or "").replace(";", ",").split(","):
        item = item.strip()
        if "://" in item:  # 用户常直接粘贴网址(https://www.cc98.org/), 取主机名
            item = urllib.parse.urlsplit(item).hostname or ""
        item = item.split("/")[0].strip().lstrip("*.").strip().lower()
        if item and " " not in item and item not in suffixes:
            suffixes.append(item)
    return suffixes


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def desired_entries(cfg) -> list[str]:
    """要注入例外列表的完整条目(域名后缀 + 私网前缀), 去重且保序。"""
    entries: list[str] = []
    for suffix in campus_suffixes(cfg):
        entries.append(f"*.{suffix}")
        entries.append(suffix)
    for prefix in _PRIVATE_PREFIXES:
        entries.append(prefix)
    seen: set[str] = set()
    return [e for e in entries if not (e in seen or seen.add(e))]


def _split(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def apply_bypass(cfg) -> tuple[bool, list[str]]:
    """把缺失的校内条目补进 ProxyOverride(保留原有条目)。

    同时清掉"我们以前加过、但现在已不需要"的条目(例如用户删掉了某个额外域名),
    否则它们会一直留在例外列表里直到关闭开关。比较不区分大小写(Windows 匹配
    本身就不区分, Clash 写回的条目大小写也未必与我们一致)。

    返回 (是否写入了注册表, 本次新增的条目)。
    """
    desired = desired_entries(cfg)
    desired_low = {e.lower() for e in desired}
    applied = list(cfg.data.get("campus_bypass_applied") or [])
    stale_low = {e.lower() for e in applied} - desired_low
    current = _split(str(_read_value("ProxyOverride") or ""))
    kept = [e for e in current if e.lower() not in stale_low]
    present = {e.lower() for e in kept}
    missing = [e for e in desired if e.lower() not in present]
    if not missing and len(kept) == len(current):
        if stale_low:
            cfg.data["campus_bypass_applied"] = [e for e in applied
                                                 if e.lower() not in stale_low]
        return False, []
    if not _write_override(";".join(kept + missing)):
        return False, []
    applied = [e for e in applied if e.lower() not in stale_low]
    for entry in missing:
        if entry.lower() not in {a.lower() for a in applied}:
            applied.append(entry)
    cfg.data["campus_bypass_applied"] = applied
    return True, missing


def remove_bypass(cfg) -> bool:
    """只移除我们加过的条目(campus_bypass_applied 记账), 别人的原样保留。"""
    applied = list(cfg.data.get("campus_bypass_applied") or [])
    if not applied:
        return False
    ours = {e.lower() for e in applied}
    current = _split(str(_read_value("ProxyOverride") or ""))
    remaining = [e for e in current if e.lower() not in ours]
    if remaining != current:
        if not _write_override(";".join(remaining)):
            return False
    cfg.data["campus_bypass_applied"] = []
    return True


def ensure(cfg, detect_tun: bool = True) -> str:
    """监控循环周期调用: 开关打开时保持例外存在(Clash 重写后自动补回)。

    返回事件: "applied"(写入了条目) / "removed"(开关关了并清掉条目) /
    "pac"(PAC 模式, 例外列表无效) / "tun"(TUN 接管, 需在 Clash 侧加规则) / ""(无事)。

    只要系统代理开着就保证例外在位 —— 不再因为"疑似 TUN"就放弃写入: TUN 判定
    有误报(早期把 Teredo 隧道网卡当成 TUN, 整个功能对这类机器失效), 而例外条目
    在 TUN 下只是不起作用, 写了没有任何副作用。TUN/PAC 只作为提示返回。
    detect_tun=False: 跳过 TUN 判定(要枚举网卡), 供高频自愈节拍使用。
    """
    enabled = bool(cfg.data.get("campus_direct"))
    if not enabled:
        if cfg.data.get("campus_bypass_applied"):
            remove_bypass(cfg)
            return "removed"
        return ""
    if pac_mode():
        return "pac"
    if proxy_enabled():
        wrote, _missing = apply_bypass(cfg)
        if wrote:
            return "applied"
    if detect_tun and tun_mode():
        return "tun"
    return ""


def status(cfg, tun: bool | None = None) -> str:
    """供界面展示的当前状态(只读, 不改注册表)。

    unsupported(非 Windows) / off(开关关闭) / pac / active(系统代理开着且条目
    齐全) / pending(系统代理开着但条目缺失, 下个周期补) / tun / idle(没开代理,
    无需处理)。tun 传入调用方已有的 TUN 判定, None 时现场检测。
    """
    if _winreg() is None:
        return "unsupported"
    if not cfg.data.get("campus_direct"):
        return "off"
    if pac_mode():
        return "pac"
    if proxy_enabled():
        present = {e.lower() for e in _split(str(_read_value("ProxyOverride") or ""))}
        if all(e.lower() in present for e in desired_entries(cfg)):
            return "active"
        return "pending"
    if tun_mode() if tun is None else tun:
        return "tun"
    return "idle"
