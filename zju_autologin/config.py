"""配置持久化：JSON 文件 + 系统凭据管理器（keyring，可选）存密码。

- 路径跨平台：Windows %APPDATA%/ZJUAutoLogin，macOS ~/Library/Application Support/ZJUAutoLogin，
  Linux ~/.config/zju-autologin
- 密码优先写入系统凭据管理器（Windows Credential Locker / macOS Keychain）；
  keyring 不可用时退化为 base64 混淆存放在配置文件中
- 另含运行日志（app.log，滚动截断）与网络事件（events.jsonl）记录
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from pathlib import Path

APP_ID = "ZJUAutoLogin"
KEYRING_SERVICE = "ZJUAutoLogin"

_DEFAULTS = {
    "username": "",
    "domain": "",
    "interval": 60,            # 检测间隔（秒）
    "auto_login": True,        # 掉线后自动登录
    "minimize_to_tray": True,  # 关闭窗口时最小化到托盘
    "autostart": False,        # 开机自启（用户级）
    "language": "auto",        # auto / zh-CN / en-US
    "check_updates": True,     # 自动检查更新
    "base_url": "https://net.zju.edu.cn",
    "ac_id": "80",             # 门户接入控制器 ID；"auto" 为自动探测
    "theme": "auto",           # auto / light / dark
    # 定时主动重登（应对固定时刻强制过期）
    "proactive_relogin": False,
    "proactive_time": "03:00",
    # 掉线推送通知
    "notify_provider": "none",  # none / bark / serverchan / wecom / dingtalk / smtp
    "notify_key": "",
    "notify_threshold": 3,      # 连续失败 N 次后推送
    "notify_recovery": True,    # 恢复后推送
    "smtp_host": "",
    "smtp_port": 465,
    "smtp_user": "",
    "smtp_pass": "",
    "smtp_to": "",
    # 流量月度上限提醒（GB，0 = 关闭）
    "traffic_limit_gb": 0,
    "last_traffic_alert": "",  # 已提醒的 "YYYY-MM"
    # 窗口位置记忆
    "win_geometry": "",
    # 心跳死信开关（healthchecks.io 等；本机在线时定期 ping，机器失联由外部服务报警）
    "heartbeat_url": "",
    # 网络出口：门户认证始终直连；探测/更新/推送按此设置路由
    # system=跟随系统代理, direct=强制直连, custom=使用 proxy_url
    "proxy_mode": "system",
    "proxy_url": "",
    # 门户直连路由（Windows 管理员添加的持久化 /32 路由，绕过 TUN/VPN）
    "portal_route_added": False,
    "portal_route_ips": [],
    # 笔记本电池供电时自动放慢检测节奏
    "battery_mode": True,
}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home())
        path = base / "ZJUAutoLogin"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "ZJUAutoLogin"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
        path = base / "zju-autologin"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> str:
    return str(config_dir() / "config.json")


def service_config_dir() -> Path:
    """服务模式（系统级保活）使用的全局配置目录（Windows: ProgramData）。"""
    if sys.platform == "win32":
        path = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "ZJUAutoLogin"
    elif sys.platform == "darwin":
        path = Path("/Library/Application Support/ZJUAutoLogin")
    else:
        path = Path("/etc/zju-autologin")
    return path


LOG_FILE_MAX = 256 * 1024


def append_file_log(line: str, directory: Path | None = None) -> None:
    """滚动追加运行日志（用于远程排查问题）。directory 默认为用户配置目录。"""
    try:
        path = (directory or config_dir()) / "app.log"
        if path.exists() and path.stat().st_size > LOG_FILE_MAX:
            content = path.read_text(encoding="utf-8", errors="replace")
            path.write_text(content[-64 * 1024:], encoding="utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("[%Y-%m-%d %H:%M:%S] ") + line + "\n")
    except OSError:
        pass


def append_event(kind: str, detail: str = "", directory: Path | None = None) -> None:
    """记录网络事件（events.jsonl，一行一个 JSON），供统计面板使用。"""
    try:
        base = directory or config_dir()
        base.mkdir(parents=True, exist_ok=True)
        with open(base / "events.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "event": kind, "detail": detail},
                                ensure_ascii=False) + "\n")
    except OSError:
        pass


def append_usage_snapshot(all_bytes: int, directory: Path | None = None) -> None:
    """记录每日流量读数（usage.jsonl，一天一行，保留最近 60 天）。"""
    if all_bytes <= 0:
        return
    try:
        base = directory or config_dir()
        base.mkdir(parents=True, exist_ok=True)
        path = base / "usage.jsonl"
        today = time.strftime("%Y-%m-%d")
        rows: list[dict] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
        rows = [r for r in rows if r.get("date") != today]
        rows.append({"date": today, "bytes": int(all_bytes)})
        rows = rows[-60:]
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + chr(10) for r in rows),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def read_usage(limit: int = 40, directory: Path | None = None) -> list[dict]:
    try:
        path = (directory or config_dir()) / "usage.jsonl"
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows[-limit:]
    except OSError:
        return []


def read_events(limit: int = 200, directory: Path | None = None) -> list[dict]:
    try:
        path = (directory or config_dir()) / "events.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        out = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
    except OSError:
        return []


class Config:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or config_path()
        self.data: dict = dict(_DEFAULTS)
        self.password_backend = "none"
        self._plain_password = ""
        self.load()

    # ------------------------------------------------------------- 生命周期

    def load(self) -> None:
        if os.path.isfile(self.path):
            try:
                with open(self.path, encoding="utf-8") as fh:
                    stored = json.load(fh)
                for key, default in _DEFAULTS.items():
                    self.data[key] = stored.get(key, default)
                self.password_backend = stored.get("password_backend", "none")
                if self.password_backend == "file":
                    self._plain_password = base64.b64decode(
                        stored.get("password_b64", "")
                    ).decode("utf-8", errors="replace")
            except (OSError, ValueError):
                self.data = dict(_DEFAULTS)
        else:
            self.data = dict(_DEFAULTS)
        if self.password_backend != "file":
            self._plain_password = self._load_password_keyring()

    def save(self) -> None:
        payload = dict(self.data)
        payload["password_backend"] = self.password_backend
        payload.pop("password", None)
        payload.pop("password_b64", None)
        if self.password_backend == "file":
            payload["password_b64"] = base64.b64encode(
                self._plain_password.encode("utf-8")
            ).decode("ascii")
        try:
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass

    # --------------------------------------------------------------- 字段

    @property
    def username(self) -> str:
        return str(self.data.get("username", ""))

    @username.setter
    def username(self, value: str) -> None:
        self.data["username"] = value.strip()

    @property
    def domain(self) -> str:
        value = str(self.data.get("domain", "")).strip()
        if value and not value.startswith("@"):
            value = "@" + value
        return value

    @domain.setter
    def domain(self, value: str) -> None:
        self.data["domain"] = value.strip()

    @property
    def interval(self) -> int:
        try:
            return max(10, min(600, int(self.data.get("interval", 60))))
        except (TypeError, ValueError):
            return 60

    @interval.setter
    def interval(self, value: int) -> None:
        self.data["interval"] = max(10, min(600, int(value)))

    @property
    def notify_threshold(self) -> int:
        try:
            return max(1, min(10, int(self.data.get("notify_threshold", 3))))
        except (TypeError, ValueError):
            return 3

    @notify_threshold.setter
    def notify_threshold(self, value: int) -> None:
        self.data["notify_threshold"] = max(1, min(10, int(value)))

    @property
    def smtp_port(self) -> int:
        try:
            return max(1, min(65535, int(self.data.get("smtp_port", 465))))
        except (TypeError, ValueError):
            return 465

    def __getattr__(self, name: str):
        if name in _DEFAULTS:
            return self.data.get(name)
        raise AttributeError(name)

    def __setattr__(self, name, value) -> None:
        if name in _DEFAULTS:
            # 若存在 property setter（username/domain 等），先走规范化逻辑
            prop = type(self).__dict__.get(name)
            if isinstance(prop, property) and prop.fset is not None:
                prop.fset(self, value)
            else:
                self.data[name] = value
        else:
            super().__setattr__(name, value)

    # --------------------------------------------------------------- 密码

    def _load_password_keyring(self) -> str:
        try:
            import keyring

            pwd = keyring.get_password(KEYRING_SERVICE, "account")
            return pwd or ""
        except Exception:  # noqa: BLE001 - keyring 缺失或后端不可用
            return ""

    def get_password(self) -> str:
        return self._plain_password

    def set_password(self, password: str) -> None:
        self._plain_password = password
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, "account", password)
            self.password_backend = "keyring"
        except Exception:  # noqa: BLE001
            self.password_backend = "file"  # 退化为混淆存储

    def password_backend_key(self) -> str:
        """返回 'keyring' / 'file' / 'none'，由 UI 翻译成可见文案。"""
        return self.password_backend


def resource_path(relative: str) -> str:
    """兼容 PyInstaller 打包后的资源定位。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "resources", relative)
