"""GUI 崩溃自愈: 登录自启之外的第二层守护。

原理: 每 5 分钟的计划任务检查 GUI 是否存活, 不在则拉起(--minimized)。
- 仅 frozen + Windows 安装版启用(便携版/开发模式跳过)
- 与 GUI 同为用户权限, 不需要管理员
- 通过互斥的锁文件判定存活(与单实例锁同目录不同名, 避免冲突)
"""

from __future__ import annotations

import os
import sys

TASK = "ZJUAutoLogin-Watchdog"


def _enabled() -> bool:
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def install() -> bool:
    """注册轻量看护计划任务(每 5 分钟)。"""
    if not _enabled():
        return False
    import subprocess

    exe = sys.executable
    # 检查标记文件: GUI 每次启动 touch, 看护脚本只拉起超过 10 分钟未更新的
    marker = os.path.join(os.environ.get("APPDATA", ""), "ZJUAutoLogin", "gui.alive")
    ps = (
        f"$m='{marker}'; "
        "if (-not (Test-Path $m) -or ((Get-Date) - (Get-Item $m).LastWriteTime).TotalMinutes -gt 10) {{ "
        f"Start-Process '{exe}' -ArgumentList '--minimized' }}"
    )
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
    """GUI 心跳: 每次启动与每小时更新存活标记。"""
    if not _enabled():
        return
    try:
        from .config import config_dir
        path = config_dir() / "gui.alive"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()), encoding="ascii")
    except OSError:
        pass
