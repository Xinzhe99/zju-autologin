"""GUI 崩溃自愈: 登录自启之外的第二层守护。

原理: 每 5 分钟的计划任务检查 GUI 是否存活, 不在则拉起(--minimized)。
- 仅 frozen + Windows 安装版启用(便携版/开发模式跳过)
- 与 GUI 同为用户权限, 不需要管理员
- 通过互斥的锁文件判定存活(与单实例锁同目录不同名, 避免冲突)

两类标记(均在配置目录):
- gui.alive      GUI 心跳, 启动与每 5 分钟 touch; 超过 10 分钟未更新视为死亡
- watchdog.pause 更新前写入: 安装器覆写 exe 期间看护任务必须按兵不动,
                 否则会把写了一半的 exe 拉起来(Failed to load Python DLL)。
                 带独立 TTL, 更新失败没人清除时 15 分钟后自动恢复守护。
"""

from __future__ import annotations

import os
import sys

TASK = "ZJUAutoLogin-Watchdog"
ALIVE_STALE_MIN = 10   # 心跳超过该分钟数 → GUI 视为死亡
PAUSE_TTL_MIN = 15     # 暂停标记超过该分钟数 → 自动失效(防更新失败后守护永久关闭)


def _enabled() -> bool:
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def _marker_path(name: str):
    from .config import config_dir
    return config_dir() / name


def _ps_script() -> str:
    """看护脚本正文: 心跳新鲜 或 暂停标记未过期 时绝不拉起。"""
    alive = _marker_path("gui.alive")
    pause = _marker_path("watchdog.pause")
    exe = sys.executable
    return (
        f"$a='{alive}'; $p='{pause}'; "
        "$f=(Test-Path $a) -and (((Get-Date)-(Get-Item $a).LastWriteTime).TotalMinutes -le "
        f"{ALIVE_STALE_MIN}); "
        "$u=(Test-Path $p) -and (((Get-Date)-(Get-Item $p).LastWriteTime).TotalMinutes -le "
        f"{PAUSE_TTL_MIN}); "
        f"if (-not $f -and -not $u) {{ Start-Process '{exe}' -ArgumentList '--minimized' }}"
    )


def install() -> bool:
    """注册轻量看护计划任务(每 5 分钟)。"""
    if not _enabled():
        return False
    import subprocess

    ps = _ps_script()
    cmd = (
        "schtasks /Create /F /TN " + TASK +
        " /SC MINUTE /MO 5 /RL LIMITED"
        f' /TR "powershell -NoProfile -WindowStyle Hidden -Command \"{ps}\""'
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                           capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def refresh_if_installed() -> bool:
    """任务已存在则用当前脚本重建(向存量机器铺新判断逻辑); 未安装不创建。"""
    if not _enabled():
        return False
    import subprocess

    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", TASK],
                           capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and install()


def uninstall() -> bool:
    if not _enabled():
        return False
    import subprocess

    try:
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK],
                       capture_output=True, timeout=30,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def touch_alive() -> None:
    """GUI 心跳: 启动与每 5 分钟更新存活标记(必须短于 ALIVE_STALE_MIN)。"""
    if not _enabled():
        return
    try:
        path = _marker_path("gui.alive")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass


def pause_for_update() -> None:
    """更新前调用: 安装器覆写 exe 期间看护任务不拉起(TTL 自动失效兜底)。"""
    if not _enabled():
        return
    try:
        path = _marker_path("watchdog.pause")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass


def resume() -> None:
    """GUI 启动时调用: 上轮更新已结束, 清除暂停标记恢复守护。"""
    try:
        _marker_path("watchdog.pause").unlink(missing_ok=True)
    except OSError:
        pass
