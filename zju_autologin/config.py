"""配置持久化：JSON 文件 + Windows 凭据管理器（keyring，可选）存密码。

密码优先写入系统凭据管理器（keyring → Windows Credential Locker）；
keyring 不可用时退化为 base64 混淆存放在配置文件中（并在 loaded_from 中标记）。
"""

from __future__ import annotations

import base64
import json
import os
import sys

APP_ID = "ZJUAutoLogin"
KEYRING_SERVICE = "ZJUAutoLogin"

_DEFAULTS = {
    "username": "",
    "domain": "",
    "interval": 60,          # 检测间隔（秒）
    "auto_login": True,      # 掉线后自动登录
    "minimize_to_tray": True,  # 关闭窗口时最小化到托盘
    "autostart": False,      # 开机自启
    "base_url": "https://net.zju.edu.cn",
}


def config_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    if base == os.path.expanduser("~"):
        base = os.path.join(base, ".zju-autologin")
    else:
        base = os.path.join(base, "ZJUAutoLogin")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "config.json")


class Config:
    def __init__(self) -> None:
        self.path = config_path()
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
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

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

    def __getattr__(self, name: str):
        if name in _DEFAULTS:
            return self.data.get(name)
        raise AttributeError(name)

    def __setattr__(self, name, value) -> None:
        if name in _DEFAULTS:
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

    def password_backend_label(self) -> str:
        return {
            "keyring": "Windows 凭据管理器",
            "file": "配置文件（混淆存储）",
            "none": "未保存",
        }.get(self.password_backend, self.password_backend)


def resource_path(relative: str) -> str:
    """兼容 PyInstaller 打包后的资源定位。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "resources", relative)
