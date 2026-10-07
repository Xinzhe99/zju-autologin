"""开机自启：Windows 注册表 Run 项 / macOS LaunchAgent（均无需管理员权限）。"""

from __future__ import annotations

import os
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ZJUAutoLogin"

PLIST_ID = "com.zju.autologin"


def gui_argv() -> list[str]:
    """启动 GUI 的 argv(不含 --minimized)。

    解析顺序: 打包 exe > console script > 源码树 main.py > -m 模块。
    早期实现把 `<包目录>/gui.py` 当脚本跑: 那样 sys.path[0] 是包目录本身,
    `from zju_autologin import ...` 必 ImportError, 源码用户的开机自启
    从来没能启动过(而且没人看得到错误)。
    """
    if getattr(sys, "frozen", False):  # PyInstaller 打包
        return [sys.executable]
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    interpreter = pythonw if sys.platform == "win32" and os.path.isfile(pythonw) else sys.executable
    import shutil as _sh

    exe = _sh.which("zju-autologin-gui")
    if exe:
        return [exe]
    repo_main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "main.py")
    if os.path.isfile(repo_main):
        return [interpreter, repo_main]
    return [interpreter, "-m", "zju_autologin.gui"]


def _command() -> list[str] | str:
    """自启命令: 统一在 GUI argv 后追加 --minimized。"""
    args = [*gui_argv(), "--minimized"]
    if sys.platform == "win32":
        # 注册表 Run 项存的是命令行字符串; 带空格的路径必须加引号
        return " ".join(f'"{a}"' if " " in a else a for a in args)
    return args


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


# ------------------------------------------------------------------ Linux

XDG_DESKTOP_ID = "zju-autologin"


def _xdg_autostart_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "autostart", f"{XDG_DESKTOP_ID}.desktop")


def _xdg_desktop_entry() -> str:
    import shlex

    program = _command()
    args = program if isinstance(program, list) else [program]
    # desktop 规范要求参数按 shell 规则转义: 路径含空格时
    # `Exec=/opt/My Apps/zju-autologin` 会被当成"程序 /opt/My + 参数 Apps/..."
    # 静默启动失败。--minimized 已由 _command() 统一追加, 这里不再重复。
    argv = " ".join(shlex.quote(str(a)) for a in args)
    return ("[Desktop Entry]" + chr(10)
            + "Type=Application" + chr(10)
            + "Name=ZJU AutoLogin" + chr(10)
            + "Name[zh_CN]=ZJU 校园网自动登录" + chr(10)
            + "Comment=Campus network keep-alive" + chr(10)
            + "Exec=" + argv + chr(10)
            + "Terminal=false" + chr(10)
            + "Categories=Network;" + chr(10)
            + "StartupNotify=false" + chr(10))


def _linux_is_enabled() -> bool:
    return os.path.isfile(_xdg_autostart_path())


def _linux_set(enable: bool) -> bool:
    try:
        path = _xdg_autostart_path()
        if enable:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(_xdg_desktop_entry())
        elif os.path.exists(path):
            os.remove(path)
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ 对外

def is_enabled() -> bool:
    if sys.platform == "win32":
        return _win_is_enabled()
    if sys.platform == "darwin":
        return _mac_is_enabled()
    if sys.platform.startswith("linux"):
        return _linux_is_enabled()
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
    if sys.platform.startswith("linux"):
        if _linux_set(enable):
            return enable
        return _linux_is_enabled()
    return False
