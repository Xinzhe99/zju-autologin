"""系统级保活（Windows 服务模式）：以 SYSTEM 账户计划任务实现"开机即认证"。

与普通"开机自启"的区别：不需要任何用户登录到桌面，重启/停电后停在登录界面
也能自动完成校园网认证，远程桌面始终可达。

实现方式：
- 全局配置写入 C:\\ProgramData\\ZJUAutoLogin\\config.json（SYSTEM 账户可读）
- 计划任务 ZJUAutoLogin，触发器 onstart，账户 SYSTEM，
  通过 PowerShell Register-ScheduledTask 注册
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
    from .autostart import gui_argv

    argv = gui_argv()
    rest = [*argv[1:], "watch", "--config", config_path]
    return argv[0], " ".join(f'"{a}"' if " " in a else a for a in rest)


def _lockdown_windows_acl(path: Path) -> None:
    """去掉继承 ACL, 只留 SYSTEM/Administrators。失败即视为事故(绝不留下可读的密码)。"""
    r = subprocess.run(["icacls", str(path), "/inheritance:r",
                        "/grant", "SYSTEM:F", "/grant", "Administrators:F"],
                       capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        detail = (r.stdout + r.stderr).decode("gbk", errors="replace").strip()[:200]
        raise PermissionError(f"icacls failed ({r.returncode}): {detail}")


def _write_private(path: Path, text: str) -> None:
    """0600 原子写: 同目录临时文件 + fsync + replace。

    直接 write_text 有两个坑: 崩在中途留下半截 JSON(下次启动静默回退默认配置,
    保活无声失效), 以及 umask 决定的 0644 窗口内密码可被同机其他用户读到。
    """
    tmp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if sys.platform == "win32":
            _lockdown_windows_acl(tmp)
        else:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def write_service_config(cfg) -> Path:
    """把凭据/参数写入全局配置（SYSTEM 账户可读；密码混淆存储）。"""
    from .config import _DEFAULTS

    # 防呆: 空账号/空密码的服务配置会让保活无声失效(实例: 曾被写入空 username
    # 导致 14 天到期时 watch 无法登录), 凭据不完整直接拒绝
    if not str(cfg.data.get("username") or "").strip() or not cfg.get_password():
        raise ValueError("refusing to write service config without username/password")
    sdir = service_config_dir()
    payload = {"password_backend": "file"}
    for key in _DEFAULTS:
        if key.startswith(("notify_", "smtp_", "traffic_limit")):
            continue  # 服务模式不推送，避免读取全局隐私配置
        payload[key] = cfg.data.get(key, _DEFAULTS[key])
    payload["password_b64"] = base64.b64encode(cfg.get_password().encode("utf-8")).decode("ascii")
    payload["autostart"] = True
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        sdir.mkdir(parents=True, exist_ok=True)
        path = sdir / "config.json"
        _write_private(path, text)
    except PermissionError:
        if sys.platform == "win32":
            raise  # Windows 计划任务必须指向全局配置, 落到临时文件会让服务读不到凭据
        # macOS/Linux 需 root：先写临时文件(600)，由提权命令搬运到目标目录
        fd, tmp_name = tempfile.mkstemp(prefix="zju_svc_cfg_", suffix=".json")
        os.close(fd)
        path = Path(tmp_name)
        _write_private(path, text)
    return path


def _elevate_log_path() -> Path:
    return service_config_dir() / "elevate.log"


def _run_elevated_ps(script: str) -> tuple[bool, str]:
    """把脚本写入临时文件并经 UAC 提权执行。

    标记文件写入 'ok' 视为成功；否则读取标记/提权日志中的错误文本返回
    （错误同时追加到 ProgramData\\ZJUAutoLogin\\elevate.log 便于排查）。
    """
    import uuid

    script_path = Path(tempfile.gettempdir()) / f"zju_aul_{os.getpid()}_{uuid.uuid4().hex[:8]}.ps1"
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


PLIST_ID = "com.zju.autologin"


def _darwin_plist_path() -> Path:
    return Path("/Library/LaunchDaemons") / f"{PLIST_ID}.plist"


def _darwin_plist_content(exe: str, args: str, config_path: str) -> str:
    """macOS LaunchDaemon plist：root 常驻, 开机即运行 + 崩溃自动重启(KeepAlive)。"""
    import html
    import shlex

    # shlex.split 保留带引号参数的空格（配置路径必含 "Application Support" 空格）
    program_args = "".join(
        f"<string>{html.escape(a)}</string>" for a in ([exe] + shlex.split(args))
    )
    nl = chr(10)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>' + nl
        + '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        + '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">' + nl
        + '<plist version="1.0">' + nl + '<dict>' + nl
        + f"  <key>Label</key><string>{PLIST_ID}</string>" + nl
        + "  <key>ProgramArguments</key>" + nl + "  <array>" + nl
        + program_args + nl + "  </array>" + nl
        + "  <key>RunAtLoad</key><true/>" + nl
        + "  <key>KeepAlive</key><true/>" + nl
        + "  <key>StandardOutPath</key><string>/Library/Logs/ZJUAutoLogin/watch.log</string>" + nl
        + "</dict>" + nl + "</plist>" + nl
    )


def is_installed(max_age: float = 60.0) -> bool:
    """检查系统级保活是否已安装（Windows 计划任务 / macOS LaunchDaemon）。"""
    global _installed_cache
    now = time.time()
    if _installed_cache is not None and now - _installed_cache[0] < max_age:
        return _installed_cache[1]
    if sys.platform.startswith("linux"):
        result = _linux_unit_path().exists()
        _installed_cache = (now, result)
        return result
    if sys.platform == "darwin":
        result = _darwin_plist_path().exists()
        _installed_cache = (now, result)
        return result
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.run(
            ["schtasks", "/query", "/tn", TASK_NAME],
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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
    """创建系统级保活并立即启动（Linux systemd / Windows UAC / macOS 管理员密码）。"""
    if sys.platform.startswith("linux"):
        return _install_linux(cfg)
    if sys.platform == "darwin":
        return _install_darwin(cfg)
    cfg_path = write_service_config(cfg)
    exe, args = _exe_and_args(str(cfg_path))
    # PowerShell 单引号字符串内 ' 需写成 ''
    exe_ps, args_ps = exe.replace("'", "''"), args.replace("'", "''")
    script = (
        f"  $action = New-ScheduledTaskAction -Execute '{exe_ps}' -Argument '{args_ps}'" + chr(10)
        + "  $trigger = New-ScheduledTaskTrigger -AtStartup" + chr(10)
        + "  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)" + chr(10)
        + f"  Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $action -Trigger $trigger -Settings $settings -User 'SYSTEM' -RunLevel Highest -Force -ErrorAction Stop | Out-Null" + chr(10)
        + f"  Start-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue" + chr(10)
    )
    ok, detail = _run_elevated_ps(script)
    if not ok:
        return False, detail
    return (True, "installed") if is_installed(max_age=0) else (False, "task not found")


def uninstall() -> tuple[bool, str]:
    """停止并删除系统级保活（Linux systemd / Windows UAC / macOS 管理员密码）。"""
    if sys.platform.startswith("linux"):
        return _uninstall_linux()
    if sys.platform == "darwin":
        return _uninstall_darwin()
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


# ------------------------------------------------------------------ Linux

UNIT_NAME = "zju-autologin"


def _linux_unit_path() -> Path:
    return Path("/etc/systemd/system") / f"{UNIT_NAME}.service"


def _cli_argv(config_path: str) -> tuple[str, str]:
    """返回 systemd ExecStart 的 (程序, 参数)。

    冻结版(PyInstaller)的 sys.executable 就是二进制本身, 再加 `-m zju_autologin.cli`
    会被当成位置参数 → cli.main 认不出, 打印用法后 return 0, 认证永远不会发生,
    而 Restart=always 会把 systemd 拖进启动限流。
    """
    if getattr(sys, "frozen", False):
        return sys.executable, f'watch --config "{config_path}"'
    return sys.executable, f'-m zju_autologin.cli watch --config "{config_path}"'


def _systemd_unit(cfg_path: str) -> str:
    """systemd 服务单元: 开机自启 + 崩溃自动重启（对应 Windows SYSTEM 计划任务）。"""
    program, args = _cli_argv(cfg_path)
    return f"""[Unit]
Description=ZJU Campus Network AutoLogin (srun keepalive)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={program} {args}
Restart=always
RestartSec=15
# 无缓冲输出: 否则 print 被块缓冲, journalctl 里长时间什么都看不到
Environment=PYTHONUNBUFFERED=1
# 加固: 服务不需要新权限与真实 /tmp /home
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ReadWritePaths=/etc/zju-autologin

[Install]
WantedBy=multi-user.target
"""


def _linux_elevated_sh(script: str) -> tuple[bool, str]:
    """非 root 时经 pkexec（桌面环境的图形/终端密码框）提权执行 shell 脚本。"""
    import shutil
    import subprocess
    import tempfile

    if sys.platform != "win32" and getattr(os, "geteuid", lambda: 1)() == 0:
        r = subprocess.run(["/bin/sh", "-c", script],
                           capture_output=True, text=True, timeout=120)
        return r.returncode == 0, (r.stdout + r.stderr).strip()[:200]
    pkexec = shutil.which("pkexec")
    if not pkexec:
        return False, "需要 root: 请用 sudo 运行（或安装 pkexec, 桌面环境通常自带）"
    fd, path = tempfile.mkstemp(prefix="zju_aul_svc_", suffix=".sh")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        os.chmod(path, 0o700)
        r = subprocess.run([pkexec, "/bin/sh", path],
                           capture_output=True, text=True, timeout=300)
        return r.returncode == 0, (r.stdout + r.stderr).strip()[:200]
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _install_linux(cfg) -> tuple[bool, str]:
    """写入凭据与 systemd 单元并 enable --now（root 直装 / 桌面经 pkexec）。"""
    import shlex
    import subprocess

    cfg_path = write_service_config(cfg)  # root: 直接落 /etc; 非 root: 落临时文件待搬
    unit = _systemd_unit(str(cfg_path if str(cfg_path).startswith("/etc/") else
                             "/etc/zju-autologin/config.json"))
    non_root = sys.platform != "win32" and getattr(os, "geteuid", lambda: 1)() != 0
    if non_root:
        # 凭据/单元先写本地临时文件(600), 提权脚本仅做搬运与 systemctl
        import tempfile

        fd, unit_tmp = tempfile.mkstemp(prefix="zju_aul_unit_", suffix=".service")
        os.close(fd)
        with open(unit_tmp, "w", encoding="utf-8") as fh:
            fh.write(unit)
        os.chmod(unit_tmp, 0o644)
        nl = chr(10)
        script = (
            "set -e" + nl
            + "mkdir -p /etc/zju-autologin /etc/systemd/system" + nl
            + f"mv {shlex.quote(str(cfg_path))} /etc/zju-autologin/config.json" + nl
            + "chmod 600 /etc/zju-autologin/config.json" + nl
            + f"mv {shlex.quote(unit_tmp)} {shlex.quote(str(_linux_unit_path()))}" + nl
            + "systemctl daemon-reload" + nl
            + f"systemctl enable --now {UNIT_NAME}" + nl
        )
        ok, detail = _linux_elevated_sh(script)
        if not ok:
            return False, detail
        return (True, "installed") if is_installed(max_age=0) else (False, "unit not found")

    _linux_unit_path().write_text(unit, encoding="utf-8")
    for cmd in (["systemctl", "daemon-reload"],
                ["systemctl", "enable", "--now", UNIT_NAME]):
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return False, (r.stdout + r.stderr).strip()[:200] or " ".join(cmd)
    return (True, "installed") if is_installed(max_age=0) else (False, "unit not found")


def _uninstall_linux() -> tuple[bool, str]:
    import shlex
    import subprocess

    if sys.platform != "win32" and getattr(os, "geteuid", lambda: 1)() != 0:
        script = (
            f"systemctl disable --now {UNIT_NAME} 2>/dev/null; "
            f"systemctl stop {UNIT_NAME} 2>/dev/null; "
            f"rm -f {shlex.quote(str(_linux_unit_path()))}; "
            f"rm -f {shlex.quote(str(service_config_dir() / 'config.json'))}; "
            "systemctl daemon-reload"
        )
        ok, detail = _linux_elevated_sh(script)
        if not ok:
            return False, detail
        return (True, "removed") if not _linux_unit_path().exists() else (False, detail or "unit remains")

    for cmd in (["systemctl", "disable", "--now", UNIT_NAME],
                ["systemctl", "stop", UNIT_NAME]):
        subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    try:
        _linux_unit_path().unlink(missing_ok=True)
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True, timeout=30)
        (service_config_dir() / "config.json").unlink(missing_ok=True)
    except OSError as exc:
        return False, str(exc)
    return (True, "removed") if not _linux_unit_path().exists() else (False, "unit still present")


# ------------------------------------------------------------------ macOS


def _mac_elevated(sh_command: str) -> tuple[bool, str]:
    """通过 osascript 以管理员权限执行 shell 命令（弹出系统管理员密码框）。"""
    # AppleScript 字符串只认双引号，需转义 \ 与 "
    as_string = sh_command.replace("\\", "\\\\").replace('"', '\\"')
    proc = subprocess.run(
        ["osascript", "-e",
         f'do shell script "{as_string}" with administrator privileges'],
        capture_output=True, timeout=300,
    )
    out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace").strip()
    return proc.returncode == 0, out


def _install_darwin(cfg) -> tuple[bool, str]:
    """注册 root LaunchDaemon（开机即认证 + KeepAlive 崩溃自动重启）。"""
    svc_dir = service_config_dir()
    final_cfg = svc_dir / "config.json"
    cfg_path = write_service_config(cfg)  # 普通用户无权限时落在临时目录
    exe, args = _exe_and_args(str(final_cfg))
    plist = _darwin_plist_path()
    tmp_plist = Path(tempfile.gettempdir()) / f"{PLIST_ID}.plist"
    tmp_plist.write_text(_darwin_plist_content(exe, args, str(final_cfg)), encoding="utf-8")
    copy_cfg = (f"cp '{cfg_path}' '{final_cfg}' && chmod 600 '{final_cfg}' && "
                if cfg_path != final_cfg else "")
    sh = (
        f"mkdir -p '{svc_dir}' && "
        + copy_cfg
        + f"cp '{tmp_plist}' '{plist}' && "
        f"chown root:wheel '{plist}' && chmod 644 '{plist}' && "
        f"launchctl bootstrap system '{plist}' 2>/dev/null || launchctl load -w '{plist}'"
    )
    ok, out = _mac_elevated(sh)
    for p in (tmp_plist, cfg_path if cfg_path != final_cfg else None):
        if p is None:
            continue
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    if not ok:
        return False, out or "elevation failed"
    installed = is_installed(max_age=0)
    return (True, "installed") if installed else (False, out or "plist not found")


def _uninstall_darwin() -> tuple[bool, str]:
    plist = _darwin_plist_path()
    sh = (
        f"launchctl bootout system '{plist}' 2>/dev/null; "
        f"launchctl unload -w '{plist}' 2>/dev/null; "
        f"rm -f '{plist}'"
    )
    ok, out = _mac_elevated(sh)
    try:
        (service_config_dir() / "config.json").unlink(missing_ok=True)
    except OSError:
        pass
    return (True, "removed") if not _darwin_plist_path().exists() else (False, out)
