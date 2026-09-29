"""系统级保活（Windows 服务模式）：以 SYSTEM 账户计划任务实现"开机即认证"。

与普通"开机自启"的区别：不需要任何用户登录到桌面，重启/停电后停在登录界面
也能自动完成校园网认证，远程桌面始终可达。

实现方式：
- 全局配置写入 C:\\ProgramData\\ZJUAutoLogin\\config.json（SYSTEM 账户可读）
- 计划任务 `ZJUAutoLogin`，触发器 onstart，账户 SYSTEM，
  通过 PowerShell Register-ScheduledTask 注册（引号转义比 schtasks 可靠）
- 创建/删除任务需要管理员权限：生成临时 .ps1 脚本经 UAC 提权执行

macOS 的等价能力由 LaunchAgent（用户级）提供，系统级需手写 LaunchDaemon，见 README。
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import service_config_dir

TASK_NAME = "ZJUAutoLogin"


def _exe_and_args(config_path: str) -> tuple[str, str]:
    """返回计划任务要执行的 (程序, 参数)。"""
    if getattr(sys, "frozen", False):
        return sys.executable, f'watch --config "{config_path}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    main_py = Path(__file__).parent.parent / "main.py"
    interpreter = pythonw if pythonw.is_file() else Path(sys.executable)
    return str(interpreter), f'"{main_py}" watch --config "{config_path}"'


def write_service_config(cfg) -> Path:
    """把凭据/参数写入全局配置（SYSTEM 账户可读；密码混淆存储）。"""
    from .config import _DEFAULTS

    sdir = service_config_dir()
    sdir.mkdir(parents=True, exist_ok=True)
    payload = {"password_backend": "file"}
    for key in _DEFAULTS:
        if key.startswith(("notify_", "smtp_", "traffic_limit")):
            continue  # 服务模式不推送，避免读取全局隐私配置
        payload[key] = cfg.data.get(key, _DEFAULTS[key])
    payload["password_b64"] = base64.b64encode(cfg.get_password().encode("utf-8")).decode("ascii")
    payload["autostart"] = True
    path = sdir / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _run_elevated_ps(script: str) -> bool:
    """把 PowerShell 脚本写入临时文件并经 UAC 提权执行（标记文件确认已跑完）。"""
    script_path = Path(tempfile.gettempdir()) / f"zju_aul_{os.getpid()}.ps1"
    marker = script_path.with_suffix(".done")
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass
    script_path.write_text(script + f'\nSet-Content -Path "{marker}" -Value ok\n', encoding="utf-8")
    command = (
        'Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden '
        f'-ArgumentList \'-NoProfile -ExecutionPolicy Bypass -File "{script_path}"\''
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, timeout=180,
        )
        # 用户取消 UAC 时标记文件不会生成
        return marker.exists()
    except (OSError, subprocess.TimeoutExpired):
        return False
    finally:
        for p in (script_path, marker):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


_installed_cache: tuple[float, bool] | None = None
_INSTALLED_TTL = 60.0


def is_installed(max_age: float = _INSTALLED_TTL) -> bool:
    """检查系统级计划任务是否存在（schtasks 较慢, 结果缓存 60 秒）。"""
    global _installed_cache
    if _installed_cache is not None and time.time() - _installed_cache[0] < max_age:
        return _installed_cache[1]
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME],
            capture_output=True, timeout=15,
        )
        result = out.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        result = False
    _installed_cache = (time.time(), result)
    return result


def install(cfg) -> tuple[bool, str]:
    """创建系统级计划任务（需要 UAC 确认）。返回 (成功?, 说明)。"""
    if sys.platform != "win32":
        return False, "windows only"
    cfg_path = write_service_config(cfg)
    exe, args = _exe_and_args(str(cfg_path))
    script = f"""
$action = New-ScheduledTaskAction -Execute '{exe}' -Argument '{args}'
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force | Out-Null
"""
    if not _run_elevated_ps(script):
        return False, "elevation failed"
    result = (True, "installed") if is_installed(max_age=0) else (False, "task not found")
    global _installed_cache
    return result


def uninstall() -> tuple[bool, str]:
    """删除系统级计划任务（需要 UAC 确认）。"""
    if sys.platform != "win32":
        return False, "windows only"
    script = f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue\n"
    if not _run_elevated_ps(script):
        return False, "elevation failed"
    try:
        (service_config_dir() / "config.json").unlink(missing_ok=True)
    except OSError:
        pass
    return (True, "removed") if not is_installed() else (False, "task still present")
