"""后台网络监控：定时检测在线状态，掉线时自动重新认证。

基于 QObject + QThread：worker 移动到工作线程，内部 QTimer 驱动检测循环。
UI 与 worker 之间全部通过信号-槽（跨线程排队调用）交互，不阻塞界面。
"""

from __future__ import annotations

import time
import urllib.request

from PyQt6.QtCore import QMetaObject, QObject, QTimer, QThread, Qt, pyqtSignal, pyqtSlot

from .config import Config
from .srun import SrunClient, SrunError

# 状态含义（UI 据此着色）：
#   online              已认证，外网可用
#   authed_no_internet  已认证但外网不可用（校园网内部故障）
#   offline             门户可达但未认证（需要登录）
#   no_campus           门户不可达（不在校园网 / 网线没插 / 无线未连接）
#   need_config         未认证且尚未配置账号
#   auth_error          认证被拒（密码错误/设备数超限），不再自动重试
#   login_fail          自动登录失败（临时性错误，退避后重试）

_AUTH_ERRORS = {"password_error", "username_error", "E1002", "access_denied"}
_PROBE_URLS = (
    ("http://www.msftconnecttest.com/connecttest.txt", "Microsoft Connect Test"),
    ("http://connect.rom.miui.com/generate_204", None),
)


def probe_internet(timeout: float = 4.0) -> bool:
    """探测外网连通性；captive portal 劫持的响应会被内容校验识破。"""
    for url, expect_body in _PROBE_URLS:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 204:
                    return True
                if expect_body and expect_body in resp.read(256).decode("utf-8", "replace"):
                    return True
                if resp.status == 200 and not expect_body:
                    return True
        except Exception:  # noqa: BLE001
            continue
    return False


class MonitorWorker(QObject):
    statusChanged = pyqtSignal(dict)
    logLine = pyqtSignal(str)

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._timer: QTimer | None = None
        self._busy = False
        self._auth_error = ""
        self._fail_count = 0
        self._last_login_attempt = 0.0
        self._running = True

    # ------------------------------------------------------------- 线程入口

    @pyqtSlot()
    def start(self) -> None:
        self._timer = QTimer()
        self._timer.setInterval(self._config.interval * 1000)
        self._timer.timeout.connect(self.check_once)
        self._timer.start()
        self.log(f"监控已启动，每 {self._config.interval} 秒检测一次")
        self.check_once()

    @pyqtSlot()
    def stop(self) -> None:
        self._running = False
        if self._timer is not None:
            self._timer.stop()

    # ------------------------------------------------------- UI 触发的槽

    @pyqtSlot()
    def check_once(self) -> None:
        self._do_check(manual=False)

    @pyqtSlot()
    def check_manual(self) -> None:
        self._do_check(manual=True)

    @pyqtSlot()
    def login_now(self) -> None:
        if self._busy:
            self.log("当前有检测正在进行，请稍候")
            return
        self._busy = True
        try:
            self._auth_error = ""
            self._fail_count = 0
            self._do_login()
        finally:
            self._busy = False

    @pyqtSlot(int)
    def apply_interval(self, seconds: int) -> None:
        seconds = max(10, min(600, int(seconds)))
        if self._timer is not None:
            self._timer.setInterval(seconds * 1000)
        self.log(f"检测间隔已调整为 {seconds} 秒")

    @pyqtSlot()
    def clear_auth_error(self) -> None:
        self._auth_error = ""

    # --------------------------------------------------------------- 内部

    def _do_check(self, manual: bool) -> None:
        if self._busy or not self._running:
            return
        self._busy = True
        try:
            client = SrunClient(base_url=self._config.base_url)
            try:
                status = client.get_status()
            except SrunError as exc:
                self._emit("no_campus", detail=str(exc))
                return

            if not status["online"]:
                if not self._config.username or not self._config.get_password():
                    self._emit("need_config", detail="未配置账号，请在下方填写学号密码并保存")
                    return
                if not self._config.auto_login and not manual:
                    self._emit("offline", detail="门户未认证（自动登录已关闭）")
                    return
                if self._auth_error and not manual:
                    self._emit("auth_error", detail=self._auth_error)
                    return
                # 连续失败后指数退避（60s 起步，封顶 10 分钟）
                backoff = min(60 * (2 ** min(self._fail_count, 4)), 600)
                if not manual and time.time() - self._last_login_attempt < backoff:
                    self._emit("offline", detail="登录暂未成功，稍后自动重试")
                    return
                self._last_login_attempt = time.time()
                self._do_login(client=client)
                return

            # 已认证：校验外网连通性
            if probe_internet():
                self._fail_count = 0
                self._auth_error = ""
                self._emit(
                    "online",
                    username=status["username"],
                    ip=status["ip"],
                    login_time=status.get("login_time", ""),
                    detail="网络正常",
                )
            else:
                self._emit(
                    "authed_no_internet",
                    username=status["username"],
                    ip=status["ip"],
                    detail="校园网已认证，但外网不可用",
                )
        finally:
            self._busy = False

    def _do_login(self, client: SrunClient | None = None) -> None:
        client = client or SrunClient(base_url=self._config.base_url)
        self.log(f"正在登录校园网（{self._config.username}{self._config.domain}）…")
        try:
            result = client.login(
                self._config.username,
                self._config.get_password(),
                domain=self._config.domain,
            )
        except SrunError as exc:
            result = {"ok": False, "msg": str(exc), "username": "", "ip": "", "resp": {}}
        self._last_login_attempt = time.time()

        if result["ok"]:
            self._fail_count = 0
            self._auth_error = ""
            self.log("登录成功 ✓")
            try:
                status = client.get_status()
            except SrunError:
                status = {}
            self._emit(
                "online",
                username=status.get("username") or result["username"],
                ip=status.get("ip") or result.get("ip") or "",
                login_time=status.get("login_time", ""),
                detail="刚刚完成认证",
            )
            return

        resp = result.get("resp", {})
        err_code = str(resp.get("error", ""))
        msg = result["msg"]
        self.log(f"登录失败：{msg}")
        if err_code in _AUTH_ERRORS or "密码错误" in msg or "账号不存在" in msg:
            self._auth_error = msg
            self._fail_count = 0
            self._emit("auth_error", username=result["username"], detail=msg)
            return
        self._fail_count += 1
        self._emit("login_fail", username=result["username"], detail=msg)

    def _emit(self, state: str, username: str = "", ip: str = "",
              login_time: str = "", detail: str = "") -> None:
        self.statusChanged.emit({
            "state": state,
            "username": username or (self._config.username + self._config.domain),
            "ip": ip,
            "login_time": login_time,
            "detail": detail,
            "ts": time.time(),
        })

    def log(self, message: str) -> None:
        self.logLine.emit(time.strftime("[%H:%M:%S] ") + message)


class Monitor(QObject):
    """对 UI 暴露的控制器：封装 worker 线程生命周期，全部走信号-槽。"""

    statusChanged = pyqtSignal(dict)
    logLine = pyqtSignal(str)

    def __init__(self, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread(self)
        self._worker = MonitorWorker(config)
        self._worker.moveToThread(self._thread)

        self._worker.statusChanged.connect(self.statusChanged)
        self._worker.logLine.connect(self.logLine)

        self.checkRequested.connect(self._worker.check_manual)
        self.loginRequested.connect(self._worker.login_now)
        self.intervalChanged.connect(self._worker.apply_interval)
        self.credentialsChanged.connect(self._worker.clear_auth_error)
        self._thread.started.connect(self._worker.start)

    checkRequested = pyqtSignal()
    loginRequested = pyqtSignal()
    intervalChanged = pyqtSignal(int)
    credentialsChanged = pyqtSignal()

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        # 先在工作线程内同步停掉定时器，再退出线程，避免跨线程 killTimer
        QMetaObject.invokeMethod(self._worker, "stop", Qt.ConnectionType.BlockingQueuedConnection)
        self._thread.quit()
        self._thread.wait(3000)

    # UI 调用的公开方法（发信号 → 排队到工作线程执行）

    def check_once(self) -> None:
        self.checkRequested.emit()

    def login_now(self) -> None:
        self.loginRequested.emit()

    def config_updated(self) -> None:
        self.intervalChanged.emit(self._config.interval)
        self.credentialsChanged.emit()
