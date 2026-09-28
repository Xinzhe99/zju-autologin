"""系统级保活（Windows 服务模式）：以 SYSTEM 账户计划任务实现"开机即认证"。

与普通"开机自启"的区别：不需要任何用户登录到桌面，重启/停电后停在登录界面
也能自动完成校园网认证，远程桌面始终可达。

实现方式：
- 全局配置写入 C:\\ProgramData\\ZJUAutoLogin\\config.json（SYSTEM 账户可读）
- 计划任务 `ZJUAutoLogin`，触发器 onstart，账户 SYSTEM，运行 `<exe> watch --config ...`
- 创建/删除任务需要管理员权限，通过 UAC 提权执行 schtasks

macOS 的等价能力由 LaunchAgent（用户级）提供，系统级需手写 LaunchDaemon，见 README。
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

from .config import service_config_dir

TASK_NAME = "ZJUAutoLogin"


def _exe_path() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    main_py = Path(__file__).parent.parent / "main.py"
    if pythonw.is_file() and main_py.is_file():
        return f'"{pythonw}" "{main_py}"'
    return f'"{sys.executable}"'


def write_service_config(cfg) -> Path:
    """把凭据/参数写入全局配置（SYSTEM 账户可读；密码混淆存储）。"""
    from .config import _DEFAULTS

    sdir = service_config_dir()
    sdir.mkdir(parents=True, exist_ok=True)
    payload = {"password_backend": "file"}
    for key in _DEFAULTS:
        if key.startswith(("notify_", "smtp_")):
            continue  # 服务模式不推送，避免读取全局隐私配置
        payload[key] = cfg.data.get(key, _DEFAULTS[key])
    payload["password_b64"] = base64.b64encode(cfg.get_password().encode("utf-8")).decode("ascii")
    payload["autostart"] = True
    path = sdir / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _run_elevated(command: str) -> bool:
    """通过 UAC 提权执行命令并等待完成。"""
    ps = (
        "Start-Process cmd -Verb RunAs -Wait -WindowStyle Hidden "
        f"-ArgumentList '/c {command} & exit /b %ERRORLEVEL%'"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=120,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def is_installed() -> bool:
    """检查系统级计划任务是否存在（含主配置中记录的状态）。"""
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME],
            capture_output=True, timeout=15,
        )
        return out.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def install(cfg) -> tuple[bool, str]:
    """创建系统级计划任务（需要 UAC 确认）。返回 (成功?, 说明)。"""
    if sys.platform != "win32":
        return False, "windows only"
    exe = _exe_path()
    cfg_path = write_service_config(cfg)
    inner = f'"{exe}" watch --config "{cfg_path}"'
    # schtasks /tr 里不能再含双引号转义，改用 cmd 包装并转义内部引号
    tr_value = inner.replace('"', '\\"')
    cmd = (
        f"schtasks /create /f /tn {TASK_NAME} "
        f"/sc onstart /ru SYSTEM /rl HIGHEST /tr \"{tr_value}\""
    )
    if not _run_elevated(cmd):
        return False, "elevation failed"
    return (True, "installed") if is_installed() else (False, "task not found")


def uninstall() -> tuple[bool, str]:
    """删除系统级计划任务（需要 UAC 确认）。"""
    if sys.platform != "win32":
        return False, "windows only"
    cmd = f"schtasks /delete /f /tn {TASK_NAME}"
    if not _run_elevated(cmd):
        return False, "elevation failed"
    try:
        (service_config_dir() / "config.json").unlink(missing_ok=True)
    except OSError:
        pass
    return (True, "removed") if not is_installed() else (False, "task still present")
