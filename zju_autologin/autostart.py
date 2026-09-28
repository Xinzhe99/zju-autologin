"""开机自启：Windows 注册表 Run 项 / macOS LaunchAgent（均无需管理员权限）。"""

from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ZJUAutoLogin"

PLIST_ID = "com.zju.autologin"


def _command() -> list[str] | str:
    if getattr(sys, "frozen", False):  # PyInstaller 打包
        return sys.executable if sys.platform != "win32" else f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    interpreter = pythonw if sys.platform == "win32" and os.path.isfile(pythonw) else sys.executable
    main_py = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")
    if sys.platform == "win32":
        return f'"{interpreter}" "{main_py}" --minimized'
    return [interpreter, main_py, "--minimized"]


# ---------------------------------------------------------------- Windows

def _win_is_enabled() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            val, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(val)
    except (FileNotFoundError, OSError, ImportError):
        return False


def _win_set(enable: bool) -> bool:
    import winreg

    try:
        if enable:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ macOS

def _mac_plist_path() -> str:
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", f"{PLIST_ID}.plist")


def _mac_is_enabled() -> bool:
    return os.path.isfile(_mac_plist_path())


def _mac_set(enable: bool) -> bool:
    path = _mac_plist_path()
    try:
        if enable:
            from xml.sax.saxutils import escape

            plist_dir = os.path.dirname(path)
            os.makedirs(plist_dir, exist_ok=True)
            program = _command()
            args = program if isinstance(program, list) else [program]
            args = [escape(str(x)) for x in args]
            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>{PLIST_ID}</string>
    <key>ProgramArguments</key>
    <array>{''.join(f'<string>{a}</string>' for a in args)}
    </array>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><false/>
</dict>
</plist>
"""
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(plist)
        else:
            if os.path.isfile(path):
                os.remove(path)
        return True
    except OSError:
        return _mac_is_enabled()


# ------------------------------------------------------------------ 对外

def is_enabled() -> bool:
    if sys.platform == "win32":
        return _win_is_enabled()
    if sys.platform == "darwin":
        return _mac_is_enabled()
    return False


def set_enabled(enable: bool) -> bool:
    """设置开机自启，返回实际生效状态。"""
    if sys.platform == "win32":
        if _win_set(enable):
            return enable
        return _win_is_enabled()
    if sys.platform == "darwin":
        if _mac_set(enable):
            return enable
        return _mac_is_enabled()
    return False
