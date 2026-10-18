"""配置持久化：JSON 文件 + 系统凭据管理器（keyring，可选）存密码。

- 路径跨平台：Windows %APPDATA%/ZJUAutoLogin，macOS ~/Library/Application Support/ZJUAutoLogin，
  Linux ~/.config/zju-autologin
- 密码优先写入系统凭据管理器（Windows Credential Locker / macOS Keychain）；
  keyring 不可用时退化为 base64 混淆存放在配置文件中
- 另含运行日志（app.log，滚动截断）与网络事件（events.jsonl）记录
"""

from __future__ import annotations

import base64
import copy
import json
import os
import sys
import tempfile
import threading
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
    # DDNS 动态域名: IP 变化自动更新解析(off/cloudflare/aliyun)
    "ddns_provider": "off",   # off/duckdns/cloudflare/aliyun
    "ddns_domain": "",      # 如 lab.example.com
    "ddns_token": "",       # cloudflare=Zone ID; aliyun=AccessKey ID
    "ddns_secret": "",      # cloudflare=API Token; aliyun=AccessKey Secret
    # 状态变化钩子: online/offline 时执行的自定义命令(空=禁用)
    "hook_on_online": "",
    "hook_on_offline": "",
    # 月度网络报告: 每月首日推送上月统计
    "monthly_report": True,
    # 网络出口：门户认证始终直连；探测/更新/推送按此设置路由
    # system=跟随系统代理, direct=强制直连, custom=使用 proxy_url
    "proxy_mode": "system",
    "proxy_url": "",
    # 校内直连(Clash 系统代理兼容): 把校内域名/私网加入 Windows 代理例外,
    # 开着 Clash 也能访问统一认证/校内论坛/邮箱; 被 Clash 重写后自动补回。
    # 默认开启: 无 Clash 时例外条目静默闲置, 有 Clash 才起作用; 设置里可关闭。
    "campus_direct": True,
    "campus_bypass_extra": "",    # 额外校内域名后缀, 逗号分隔(如 cc98.org)
    "campus_bypass_applied": [],  # 记账: 我们写入的例外条目(撤销时只删自己的)
    # 门户直连路由（Windows 管理员添加的持久化 /32 路由，绕过 TUN/VPN）
    "portal_route_added": False,
    "portal_route_ips": [],
    # 笔记本电池供电时自动放慢检测节奏
    "battery_mode": True,
    # 设备数超限(E2620)时自动踢掉最旧的其他设备并重登
    "auto_kick": False,
    # 最近一次已确认的安装会话(安装器写入 .install-session, 强制新装弹引导一次)
    "install_session": "",
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


_EVENTS_FILE_MAX = 1024 * 1024  # events.jsonl 超限后仅保留尾部 5000 行
_EVENTS_KEEP_LINES = 5000


def append_event(kind: str, detail: str = "", directory: Path | None = None) -> None:
    """记录网络事件（events.jsonl，一行一个 JSON，超限自动截断）。"""
    try:
        base = directory or config_dir()
        base.mkdir(parents=True, exist_ok=True)
        path = base / "events.jsonl"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": time.time(), "event": kind, "detail": detail},
                                ensure_ascii=False) + "\n")
        if path.exists() and path.stat().st_size > _EVENTS_FILE_MAX:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-_EVENTS_KEEP_LINES:]
            tmp = path.with_suffix(".tmp")
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            tmp.replace(path)
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
        self._lock = threading.Lock()  # UI 与 monitor 线程会并发读写
        self.path = path or config_path()
        self.data: dict = copy.deepcopy(_DEFAULTS)
        self.password_backend = "none"
        self._plain_password = ""
        self._load_failed = False
        self.load()

    @property
    def log_dir(self) -> Path:
        """日志/事件/统计与配置文件同目录（服务模式下即 /etc 或 ProgramData）。"""
        return Path(self.path).parent

    # ------------------------------------------------------------- 生命周期

    def load(self) -> None:
        with self._lock:
            self._load_failed = False
            if not os.path.isfile(self.path):
                self.data = copy.deepcopy(_DEFAULTS)
                self.password_backend = "none"
                self._plain_password = ""
            else:
                stored: dict | None = None
                try:
                    # utf-8-sig: 记事本另存为"UTF-8 带 BOM"时 json.load 会直接抛错,
                    # 早期实现据此把整份配置当损坏文件改名备份, 用户账号/门户全丢
                    with open(self.path, encoding="utf-8-sig") as fh:
                        loaded = json.load(fh)
                    if not isinstance(loaded, dict):
                        raise ValueError("config root is not an object")
                    stored = loaded
                except ValueError:
                    # 配置损坏：改名备份再回退默认，避免用户名等无声丢失
                    try:
                        backup = f"{self.path}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
                        os.replace(self.path, backup)
                        print(f"[ZJUAutoLogin] config corrupted, backed up to {backup}",
                              file=sys.stderr)
                    except OSError:
                        pass
                except OSError as exc:
                    # 文件被占用/权限不足: 绝不能回退默认值。否则下一次 save 会把
                    # 磁盘上完好的账号密码覆盖成空配置(真实数据丢失路径)。
                    # 保留内存中的旧数据, 并禁止写入, 等下次读取成功再恢复。
                    self._load_failed = True
                    print(f"[ZJUAutoLogin] warning: cannot read config ({exc}); "
                          "keeping in-memory values and refusing to overwrite it",
                          file=sys.stderr)
                    return
                if stored is not None:
                    # 合并而非逐键覆盖: monitor 等模块会写 _DEFAULTS 之外的键
                    # (如 last_month_report), 逐键覆盖会让它们每次重启后消失
                    self.data = copy.deepcopy(_DEFAULTS)
                    self.data.update(stored)
                    for key, default in _DEFAULTS.items():
                        value = self.data.get(key)
                        self.data[key] = self._coerce_default(key, value, default)
                    self.password_backend = str(stored.get("password_backend") or "none")
                    if self.password_backend == "file":
                        try:
                            self._plain_password = base64.b64decode(
                                str(stored.get("password_b64") or "")
                            ).decode("utf-8", errors="replace")
                        except (ValueError, TypeError):
                            # 只有密码这一段坏了: 丢密码即可, 不要连账号门户一起丢
                            self._plain_password = ""
                            self.password_backend = "none"
        if self.password_backend != "file":
            self._plain_password = self._load_password_keyring()

    @staticmethod
    def _coerce_default(key: str, value, default):
        """类型校验: 只接受与默认值同类的值, 否则回退默认。

        不用 isinstance(value, type(default)): bool 是 int 的子类, interval=true
        会被放行; 而 traffic_limit_gb 允许用户写 0.5。
        """
        if isinstance(default, bool):
            return value if isinstance(value, bool) else default
        if isinstance(default, (int, float)):
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default
        if isinstance(default, list):
            return copy.deepcopy(value) if isinstance(value, list) else copy.deepcopy(default)
        if isinstance(default, dict):
            return copy.deepcopy(value) if isinstance(value, dict) else copy.deepcopy(default)
        if isinstance(default, str):
            return value if isinstance(value, str) else default
        return default

    def save(self) -> bool:
        """原子落盘; 返回是否写成功(调用方据此提示用户, 别再无脑报"已保存")。"""
        if self._load_failed:
            # 文件被临时占用后恢复: 先重试读取。仍失败才拒绝写入, 避免把好配置
            # 覆盖成空; 成功则继续保存(用户不必重启程序)。
            self.load()
            if self._load_failed:
                print("[ZJUAutoLogin] warning: config could not be read earlier; "
                      "refusing to overwrite it", file=sys.stderr)
                return False
        payload = copy.deepcopy(self.data)
        payload["password_backend"] = self.password_backend
        payload.pop("password", None)
        payload.pop("password_b64", None)
        if self.password_backend == "file":
            payload["password_b64"] = base64.b64encode(
                self._plain_password.encode("utf-8")
            ).decode("ascii")
        try:
            with self._lock:
                # 临时文件 + 原子替换，避免并发写产生截断 JSON。
                # 唯一文件名: GUI 与 `serve` 是两个进程, 固定 xxx.tmp 会互相踩;
                # 0600: 这份文件可能含 password_b64(base64 不是加密), 早期按 umask
                # 落成 0644, 同机任何用户都能读走校园网密码
                directory = os.path.dirname(os.path.abspath(self.path)) or "."
                os.makedirs(directory, exist_ok=True)
                fd, tmp = tempfile.mkstemp(prefix=".zju-cfg-", suffix=".tmp", dir=directory)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        json.dump(payload, fh, ensure_ascii=False, indent=2)
                        fh.flush()
                        os.fsync(fh.fileno())
                    if sys.platform != "win32":
                        os.chmod(tmp, 0o600)
                    os.replace(tmp, self.path)
                except BaseException:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
            return True
        except OSError as exc:
            print(f"[ZJUAutoLogin] warning: failed to save config: {exc}", file=sys.stderr)
            return False

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

    def refresh_password(self) -> bool:
        """内存里没有密码时重读系统凭据管理器; 返回是否拿到了密码。

        开机自启时凭据服务偶尔比本程序晚就绪, 启动那一刻读到的是空 ——
        以前会一直停在「未配置账号」直到手动重启程序。
        """
        if self._plain_password:
            return True
        if self.password_backend == "file" or not self.data.get("username"):
            return False
        pwd = self._load_password_keyring()
        if pwd:
            self._plain_password = pwd
            if self.password_backend == "none":
                self.password_backend = "keyring"
        return bool(pwd)

    def set_password(self, password: str) -> None:
        self._plain_password = password
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, "account", password)
            self.password_backend = "keyring"
        except Exception:  # noqa: BLE001
            self.password_backend = "file"  # 退化为混淆存储

    def forget_password(self) -> None:
        """清除已保存的凭据(内存 + 系统凭据管理器 + 配置里的混淆副本)。

        早期实现用 set_password("") 顶掉条目: 凭据管理器里会留下一条空记录,
        而且后端拒绝空值时旧密码仍在, 界面却已提示"已清除"。
        """
        self._plain_password = ""
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, "account")
        except Exception:  # noqa: BLE001 - 条目不存在或后端不支持删除
            pass
        self.password_backend = "none"
        self.data.pop("password_b64", None)

    def password_backend_key(self) -> str:
        """返回 'keyring' / 'file' / 'none'，由 UI 翻译成可见文案。"""
        return self.password_backend


def resource_path(relative: str) -> str:
    """资源定位: 包内 resources → PyInstaller 解包目录 → 仓库根 resources。

    以前只看仓库根/PyInstaller 的 resources/，wheel 里没有这个目录
    (pyproject 只打包 zju_autologin 包)，pip 安装的 GUI 因此没有图标。
    """
    package_base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(sys._MEIPASS, "zju_autologin", "resources"))
        candidates.append(os.path.join(sys._MEIPASS, "resources"))
    candidates.append(package_base)
    if not getattr(sys, "frozen", False):
        candidates.append(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "resources"))
    for base in candidates:
        candidate = os.path.join(base, relative)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(candidates[0], relative)
