"""系统级保活（Windows 服务模式）：以 SYSTEM 账户计划任务实现"开机即认证"。

与普通"开机自启"的区别：不需要任何用户登录到桌面，重启/停电后停在登录界面
也能自动完成校园网认证，远程桌面始终可达。

实现方式：
- 全局配置写入 C:\\ProgramData\\ZJUAutoLogin\\config.json（SYSTEM 账户可读）
- 计划任务 ZJUAutoLogin，触发器 onstart，账户 SYSTEM，
  优先 PowerShell Register-ScheduledTask 注册，失败自动回退 schtasks.exe
- 创建/删除任务需要管理员权限：生成临时 .ps1 脚本经 UAC 提权执行，
  执行结果（含错误）写入标记文件与 ProgramData\\ZJUAutoLogin\\elevate.log
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

_installed_cache: tuple[float, bool] | None = None


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


def _elevate_log_path() -> Path:
    return service_config_dir() / "elevate.log"


def _run_elevated_ps(script: str) -> tuple[bool, str]:
    """把脚本写入临时文件并经 UAC 提权执行。

    标记文件写入 'ok' 视为成功；否则读取标记/提权日志中的错误文本返回
    （错误同时追加到 ProgramData\\ZJUAutoLogin\\elevate.log 便于排查）。
    """
    script_path = Path(tempfile.gettempdir()) / f"zju_aul_{os.getpid()}.ps1"
    marker = script_path.with_suffix(".done")
    log_path = _elevate_log_path()
    try:
        marker.unlink(missing_ok=True)
    except OSError:
        pass
    marker_ps = str(marker).replace("'", "''")
    log_ps = str(log_path).replace("'", "''")
    nl = chr(10)
    wrapped = (
        "try { Set-ExecutionPolicy Bypass -Scope Process -Force } catch {}" + nl
        + "try {" + nl
        + script + nl
        + f"  Set-Content -Path '{marker_ps}' -Value 'ok'" + nl
        + "} catch {" + nl
        + f"  Add-Content -Path '{log_ps}' -Value (\"[{time.strftime('%Y-%m-%d %H:%M:%S')}] \" + $_)" + nl
        + f"  Set-Content -Path '{marker_ps}' -Value 'err'" + nl
        + "  exit 1" + nl
        + "}" + nl
    )
    script_path.write_text(wrapped, encoding="utf-8-sig")  # BOM 让 PS5 按 UTF-8 解析
    command = (
        "Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden "
        f"-ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"{script_path}\"'"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, timeout=180, creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass

    detail = ""
    try:
        detail = marker.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        detail = ""
    tail = ""
    try:
        tail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-400:]
    except OSError:
        pass
    finally:
        for p in (script_path, marker):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    if detail == "ok":
        return True, "ok"
    return False, detail or tail or "no-marker (UAC 取消或提权进程未运行)"


def is_installed(max_age: float = 60.0) -> bool:
    """检查系统级计划任务是否存在（schtasks 较慢, 结果缓存 60 秒）。"""
    global _installed_cache
    now = time.time()
    if _installed_cache is not None and now - _installed_cache[0] < max_age:
        return _installed_cache[1]
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME],
            capture_output=True, timeout=15,
        )
        if out.returncode == 0:
            result = True
        else:
            # SYSTEM 创建的任务对普通权限进程返回"拒绝访问"——任务存在但不可读
            text = (out.stdout + out.stderr).decode("gbk", errors="replace")
            result = ("拒绝访问" in text) or ("Access is denied" in text)
    except (OSError, subprocess.TimeoutExpired):
        result = False
    _installed_cache = (now, result)
    return result


def install(cfg) -> tuple[bool, str]:
    """创建系统级计划任务并立即启动（需要 UAC 确认）。返回 (成功?, 详情)。"""
    if sys.platform != "win32":
        return False, "windows only"
    cfg_path = write_service_config(cfg)
    exe, args = _exe_and_args(str(cfg_path))
    script = (
        f"  $action = New-ScheduledTaskAction -Execute '{exe}' -Argument '{args}'" + chr(10)
        + "  $trigger = New-ScheduledTaskTrigger -AtStartup" + chr(10)
        + "  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)" + chr(10)
        + f"  Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force -ErrorAction Stop | Out-Null" + chr(10)
        + f"  Start-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue" + chr(10)
        + f"  Start-Process -FilePath '{exe}' -ArgumentList '{args}' -WindowStyle Hidden -ErrorAction SilentlyContinue" + chr(10)
    )
    ok, detail = _run_elevated_ps(script)
    if not ok:
        return False, detail
    return (True, "installed") if is_installed(max_age=0) else (False, "task not found")


def uninstall() -> tuple[bool, str]:
    """停止并删除系统级计划任务（需要 UAC 确认）。"""
    if sys.platform != "win32":
        return False, "windows only"
    script = (
        f"  Stop-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue" + chr(10)
        + f"  Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false -ErrorAction SilentlyContinue" + chr(10)
    )
    ok, detail = _run_elevated_ps(script)
    if not ok:
        return False, detail
    try:
        (service_config_dir() / "config.json").unlink(missing_ok=True)
    except OSError:
        pass
    return (True, "removed") if not is_installed(max_age=0) else (False, "task still present")
