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
   我们补的条目会被冲掉 —— 所以由监控循环定期检查、缺了就补(默认 60 秒内恢复)。
2. PAC 模式走 AutoConfigURL, 例外列表不生效; TUN 模式连例外机制都绕过 ——
   这两种情况只能提示用户去 Clash 侧加 DIRECT 规则, 检测到时给出一次性建议。

仅改 HKCU(当前用户注册表), 无需管理员; 改完用 wininet 通知系统立即生效。
"""

from __future__ import annotations

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
        _notify_wininet()
        return True
    except OSError:
        return False


def _notify_wininet() -> None:
    """让浏览器立即感知代理设置变化(否则要等它自己轮询注册表)。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        wininet = ctypes.windll.wininet
        wininet.InternetSetOptionW(0, 39, 0, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
        wininet.InternetSetOptionW(0, 37, 0, 0)  # INTERNET_OPTION_REFRESH
    except Exception:  # noqa: BLE001 - 通知失败只是晚一点生效
        pass


def proxy_enabled() -> bool:
    return bool(_read_value("ProxyEnable"))


def pac_mode() -> bool:
    return bool(_read_value("AutoConfigURL"))


def tun_mode() -> bool:
    """检测 TUN 接管(fake-ip 网段或常见 TUN 虚拟网卡名)。"""
    try:
        from PyQt6.QtNetwork import QNetworkInterface
    except ImportError:
        return False
    try:
        for iface in QNetworkInterface.allInterfaces():
            # Windows 上 name() 常是 GUID, 描述性名称在 humanName()
            name = (iface.name() + " " + iface.humanName()).lower()
            if any(tag in name for tag in ("clash", "meta", "mihomo", "sing-box",
                                           "tun", "utun", "wintun")):
                if iface.addressEntries():
                    return True
            for entry in iface.addressEntries():
                ip = entry.ip().toString()
                if ip.startswith("198.18.") or ip.startswith("198.19."):
                    return True  # fake-ip 网段(TUN 常用)
    except Exception:  # noqa: BLE001
        return False
    return False


def campus_suffixes(cfg) -> list[str]:
    """由门户地址推导校内域名后缀, 再叠加用户自填(逗号分隔)。

    例: 门户 https://net.zju.edu.cn → ["zju.edu.cn"], 例外条目为
    *.zju.edu.cn 与 zju.edu.cn; 其他学校(portal.xxx.edu.cn)同理自动适配。
    """
    suffixes: list[str] = []
    host = urllib.parse.urlsplit(str(getattr(cfg, "base_url", "") or "")).hostname or ""
    parts = host.split(".")
    if len(parts) >= 2:
        suffixes.append(".".join(parts[1:]))  # 去掉首标签 → zju.edu.cn
    for item in str(cfg.data.get("campus_bypass_extra") or "").replace(";", ",").split(","):
        item = item.strip().lstrip("*.").strip()
        if item and item not in suffixes:
            suffixes.append(item)
    return suffixes


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

    返回 (是否写入了注册表, 本次新增的条目)。
    """
    current = _split(str(_read_value("ProxyOverride") or ""))
    missing = [e for e in desired_entries(cfg) if e not in current]
    if not missing:
        return False, []
    merged = current + missing
    if not _write_override(";".join(merged)):
        return False, []
    applied = list(cfg.data.get("campus_bypass_applied") or [])
    for entry in missing:
        if entry not in applied:
            applied.append(entry)
    cfg.data["campus_bypass_applied"] = applied
    return True, missing


def remove_bypass(cfg) -> bool:
    """只移除我们加过的条目(campus_bypass_applied 记账), 别人的原样保留。"""
    applied = list(cfg.data.get("campus_bypass_applied") or [])
    if not applied:
        return False
    current = _split(str(_read_value("ProxyOverride") or ""))
    remaining = [e for e in current if e not in applied]
    if remaining != current:
        if not _write_override(";".join(remaining)):
            return False
    cfg.data["campus_bypass_applied"] = []
    return True


def ensure(cfg) -> str:
    """监控循环周期调用: 开关打开时保持例外存在(Clash 重写后自动补回)。

    返回事件: "applied"(写入了条目) / "removed"(开关关了并清掉条目) /
    "pac"(PAC 模式, 例外列表无效) / "tun"(TUN 接管, 需在 Clash 侧加规则) / ""(无事)。
    首次还是补写由调用方自行记录(它知道自己进程内是否提示过)。
    """
    enabled = bool(cfg.data.get("campus_direct"))
    if not enabled:
        if cfg.data.get("campus_bypass_applied"):
            remove_bypass(cfg)
            return "removed"
        return ""
    if pac_mode():
        return "pac"
    if tun_mode():
        return "tun"
    if not proxy_enabled():
        return ""  # 系统代理没开: 无需写, 开了会自动补
    wrote, _missing = apply_bypass(cfg)
    return "applied" if wrote else ""
