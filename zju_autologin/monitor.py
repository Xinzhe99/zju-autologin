"""后台网络监控：定时检测在线状态，掉线时自动重新认证。

基于 QObject + QThread：worker 移动到工作线程，内部 QTimer 驱动检测循环。
UI 与 worker 之间全部通过信号-槽（跨线程排队调用）交互，不阻塞界面。

另负责：
- GitHub Releases 更新检查（每 24 小时一次）
- 登录连续失败 / 设备数超限时的推送通知（notify.py）
- 每日定时主动重登（应对固定时刻强制过期的场景）
- 网络事件（状态切换）记录到 events.jsonl 供统计面板展示
"""

from __future__ import annotations

import time
import urllib.request
from pathlib import Path

from PyQt6.QtCore import QMetaObject, QObject, QTimer, QThread, Qt, pyqtSignal, pyqtSlot

from . import updates
from .config import Config, append_event, append_usage_snapshot
from .net import build_opener, probe_internet
from .power import on_battery
from .i18n import tr
from .notify import send_notification
from .srun import SrunClient, SrunError

# 状态含义（UI 据此着色）：
#   online              已认证，外网可用
#   authed_no_internet  已认证但外网不可用（校园网内部故障）
#   offline             门户可达但未认证（需要登录）
#   no_campus           门户不可达（不在校园网 / 网线没插 / 无线未连接）
#   need_config         未认证且尚未配置账号
#   auth_error          认证被拒（密码错误/设备数超限），不再自动重试
#   login_fail          自动登录失败（临时性错误，退避后重试）

_AUTH_ERRORS = {"password_error", "username_error", "E1002", "access_denied",
                "user_must_modify_password"}
_UPDATE_INTERVAL = 24 * 3600
_HEARTBEAT_INTERVAL = 300  # 死信开关 ping 间隔（秒）


def _interface_signature() -> str:
    """网卡集合指纹(名称+状态+地址), 变化即网络拓扑变化。纯本地调用。"""
    try:
        from PyQt6.QtNetwork import QNetworkInterface

        parts = []
        for iface in QNetworkInterface.allInterfaces():
            addrs = ",".join(e.ip().toString() for e in iface.addressEntries())
            parts.append(f"{iface.name()}:{int(iface.flags())}:{addrs}")
        return "|".join(sorted(parts))
    except Exception:  # noqa: BLE001 - QtNetwork 缺失时退化为纯轮询
        return ""


class MonitorWorker(QObject):
    statusChanged = pyqtSignal(dict)
    logLine = pyqtSignal(str)
    updateAvailable = pyqtSignal(str, str)  # 最新版本号, 下载页

    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._log_dir = Path(config.path).parent  # 服务模式下日志落在配置所在目录
        self._timer: QTimer | None = None
        self._update_timer: QTimer | None = None
        self._busy = False
        self._auth_error = ""
        self._fail_count = 0
        self._fail_streak = 0
        self._notify_sent = False
        self._prev_state = ""
        self._opener = None
        self._last_login_attempt = 0.0
        self._last_proactive_date = ""
        self._if_sig = ""
        self._last_heartbeat = 0.0
        self._usage_date = ""
        self._battery_mode_on = False
        self._running = True

    # ------------------------------------------------------------- 线程入口

    @pyqtSlot()
    def start(self) -> None:
        self._timer = QTimer()
        self._timer.setInterval(self._config.interval * 1000)
        self._timer.timeout.connect(self.check_once)
        self._timer.start()
        # 事件驱动网络响应: 2s 轻量监听网卡集合变化(本地系统调用, 零网络流量),
        # Wi-Fi 切换/插拔网线/VPN 起落 → 立即检测, 重登从分钟级降到秒级
        self._if_sig = _interface_signature()
        self._if_timer = QTimer()
        self._if_timer.setInterval(2000)
        self._if_timer.timeout.connect(self._on_interface_change)
        self._if_timer.start()
        self.log(tr("log.monitor_started", n=self._config.interval))
        self.check_once()  # 首次状态检测优先, 不被更新检查的网络等待拖慢
        if self._config.check_updates:
            # 排队执行而非同步调用: 保证 stop() 事件能尽快插入事件循环
            QTimer.singleShot(3000, self.check_updates)
        self._update_timer = QTimer()
        self._update_timer.setInterval(_UPDATE_INTERVAL * 1000)
        self._update_timer.timeout.connect(self.check_updates)
        self._update_timer.start()

    @pyqtSlot()
    def stop(self) -> None:
        self._running = False
        for timer in (self._timer, self._update_timer, getattr(self, "_if_timer", None)):
            if timer is not None:
                timer.stop()

    # ------------------------------------------------------- UI 触发的槽

    @pyqtSlot()
    def check_once(self) -> None:
        self._do_check(manual=False)

    @pyqtSlot()
    def check_manual(self) -> None:
        self._do_check(manual=True)

    def _on_interface_change(self) -> None:
        """网卡集合变化(切 Wi-Fi/插拔网线/VPN 起落) → 立即检测。"""
        if self._busy or not self._running:
            return
        sig = _interface_signature()
        if sig and sig != self._if_sig:
            self._if_sig = sig
            self.log(tr("log.net_changed"))
            self._do_check(manual=False)

    @pyqtSlot()
    def login_now(self) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self._auth_error = ""
            self._fail_count = 0
            self._do_login()
        finally:
            self._busy = False

    @pyqtSlot()
    def notify_test(self) -> None:
        _ok, msg = send_notification(self._config, tr("app.name"), tr("notify.test_body"))
        self.log(tr("notify.test_done", msg=msg))

    @pyqtSlot(int)
    def apply_interval(self, seconds: int) -> None:
        seconds = max(10, min(600, int(seconds)))
        if self._timer is not None:
            self._timer.setInterval(seconds * 1000)
        self.log(tr("log.interval_changed", n=seconds))

    @pyqtSlot()
    def clear_auth_error(self) -> None:
        self._auth_error = ""

    def _ping_heartbeat(self) -> None:
        """死信开关：在线时定期 ping 外部 URL，机器失联由外部服务报警。"""
        url = (self._config.heartbeat_url or "").strip()
        if not url:
            return
        now = time.time()
        if now - self._last_heartbeat < _HEARTBEAT_INTERVAL:
            return
        self._last_heartbeat = now
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZJU-AutoLogin"})
            (self._opener or build_opener(self._config.proxy_mode, self._config.proxy_url)) \
                .open(req, timeout=6).close()
        except Exception as exc:  # noqa: BLE001 - 心跳失败仅记录
            self.log(tr("log.heartbeat_fail", msg=exc))

    def _adjust_interval_for_power(self) -> None:
        """笔记本电池供电时把检测间隔放慢一倍，插电恢复。"""
        if not self._config.battery_mode or self._timer is None:
            return
        base = self._config.interval
        want = base * 2 if on_battery() else base
        if want != self._timer.interval() // 1000:
            self._timer.setInterval(want * 1000)
        if want != base and not self._battery_mode_on:
            self.log(tr("log.battery_mode", n=want))
            self._battery_mode_on = True
        elif want == base and self._battery_mode_on:
            self.log(tr("log.plugged_mode", n=base))
            self._battery_mode_on = False

    @pyqtSlot()
    def check_updates(self) -> None:
        if not self._config.check_updates:
            return
        newer, version, url = updates.check_newer(
            opener=build_opener(self._config.proxy_mode, self._config.proxy_url))
        if newer:
            self.log(tr("log.update_found", version=version))
            self.updateAvailable.emit(version, url)

    # --------------------------------------------------------------- 内部

    def _client(self) -> SrunClient:
        return SrunClient(base_url=self._config.base_url, ac_id=self._config.ac_id)

    def _maybe_push(self, title_key: str, body: str) -> None:
        if self._notify_sent:
            return
        ok, msg = send_notification(self._config, tr(title_key), body, opener=self._opener)
        if ok:
            self._notify_sent = True
            self.log(tr("notify.sent"))
        else:
            self.log(tr("notify.failed", msg=msg))

    def _reset_notify(self) -> None:
        self._notify_sent = False
        self._fail_streak = 0

    def _should_proactive_relogin(self) -> bool:
        cfg = self._config
        if not cfg.proactive_relogin:
            return False
        try:
            hh, mm = str(cfg.proactive_time or "03:00").split(":")
            target = time.strptime(f"{int(hh):02d}:{int(mm):02d}", "%H:%M")
        except (ValueError, AttributeError):
            return False
        now = time.localtime()
        now_mark = f"{now.tm_year:04d}-{now.tm_mon:02d}-{now.tm_mday:02d}"
        if self._last_proactive_date == now_mark:
            return False
        now_secs = now.tm_hour * 3600 + now.tm_min * 60
        target_secs = target.tm_hour * 3600 + target.tm_min * 60
        return now_secs >= target_secs

    def _do_check(self, manual: bool) -> None:
        if self._busy or not self._running:
            return
        self._busy = True
        try:
            self._adjust_interval_for_power()
            self._opener = build_opener(self._config.proxy_mode, self._config.proxy_url)
            client = self._client()
            try:
                status = client.get_status()
            except SrunError as first_exc:
                # VPN 切换线路等瞬断: 1.5s 后快速重试一次, 仍失败才判定无校园网
                self.log(tr("log.portal_retry"))
                time.sleep(1.5)
                try:
                    status = client.get_status()
                except SrunError:
                    self._emit("no_campus", detail=str(first_exc))
                    return

            if not status["online"]:
                if not self._config.username or not self._config.get_password():
                    self._emit("need_config", detail=tr("detail.need_config"))
                    return
                if not self._config.auto_login and not manual:
                    self._emit("offline", detail=tr("detail.offline_manual"))
                    return
                if self._auth_error and not manual:
                    self._emit("auth_error", detail=self._auth_error)
                    return
                # 连续失败后指数退避（60s 起步，封顶 10 分钟）
                backoff = min(60 * (2 ** min(self._fail_count, 4)), 600)
                if not manual and time.time() - self._last_login_attempt < backoff:
                    self._emit("offline", detail=tr("detail.wait_retry"))
                    return
                self._last_login_attempt = time.time()
                self._emit("checking", detail=tr("detail.logging_in"))
                self._do_login(client=client)
                return

            # 已认证：校验外网连通性（按代理设置路由）
            if probe_internet(opener=self._opener):
                self._fail_count = 0
                self._auth_error = ""
                self._ping_heartbeat()
                all_bytes = int(status.get("all_bytes") or 0)
                if all_bytes > 0:
                    today = time.strftime("%Y-%m-%d")
                    if today != self._usage_date:
                        self._usage_date = today
                        append_usage_snapshot(all_bytes, self._log_dir)
                if self._notify_sent and self._config.notify_recovery:
                    self._maybe_push_recovery(status.get("ip") or "")
                self._reset_notify()
                # 每日定时主动重登（成功后走登录路径刷新状态）
                if self._should_proactive_relogin():
                    self.log(tr("log.proactive"))
                    if self._do_login(client=client):
                        # 成功才记日期: 失败则当天后续检测继续重试
                        self._last_proactive_date = time.strftime("%Y-%m-%d")
                    return
                self._check_traffic_limit(int(status.get("all_bytes") or 0))
                latency_ms = status.get("latency_ms")
                detail_online = tr("detail.online_ok")
                if latency_ms is not None:
                    detail_online += f" · {latency_ms}ms"
                self._emit(
                    "online",
                    username=status["username"],
                    ip=status["ip"],
                    login_time=status.get("login_time", ""),
                    detail=detail_online,
                    billing=status.get("billing", ""),
                    all_bytes=status.get("all_bytes", 0),
                )
            else:
                self._emit(
                    "authed_no_internet",
                    username=status["username"],
                    ip=status["ip"],
                    detail=tr("detail.authed_no_internet"),
                )
        except Exception as exc:  # noqa: BLE001 - 兜底: 异常逸出 Qt slot 会终止 worker 线程
            self.log(f"{tr('err.unknown')}: {exc}")
        finally:
            self._busy = False

    def _maybe_push_recovery(self, ip: str) -> None:
        send_notification(
            self._config,
            tr("notify.recovery_title"),
            tr("notify.recovery_body", ip=ip or "-"),
            opener=self._opener,
        )
        self.log(tr("notify.recovery_sent"))

    def _auto_kick_and_retry(self, client: SrunClient, current_ip: str) -> bool:
        """设备超限时自动踢掉最旧的其他在线设备并重登一次。

        本机设备永不踢; 每轮最多踢一台, 避免连环误伤。
        """
        try:
            devices = client.list_online_devices(
                self._config.username, self._config.get_password(), self._config.domain)
        except Exception:  # noqa: BLE001
            return False
        others = [d for d in devices
                  if d.get("ip") and d.get("ip") != current_ip]
        if not others:
            return False
        oldest = min(others, key=lambda d: d.get("add_time") or 0)
        ip = oldest.get("ip", "")
        ok, _detail = client.kick_device(self._config.username + self._config.domain, ip)
        if not ok:
            return False
        since = time.strftime("%m-%d %H:%M", time.localtime(oldest.get("add_time") or 0))
        self.log(tr("log.autokick", ip=ip, since=since))
        result = client.login(self._config.username, self._config.get_password(),
                              domain=self._config.domain)
        if result.get("ok"):
            self._fail_count = 0
            self._auth_error = ""
            self.log(tr("log.login_ok"))
            self._emit("online", username=result.get("username") or self._config.username,
                       ip=result.get("ip") or current_ip,
                       detail=tr("detail.just_logged"))
            return True
        return False

    def _do_login(self, client: SrunClient | None = None) -> bool:
        client = client or self._client()
        self.log(tr("log.logging_in", username=self._config.username + self._config.domain))
        try:
            result = client.login(
                self._config.username,
                self._config.get_password(),
                domain=self._config.domain,
            )
        except SrunError as exc:
            result = {"ok": False, "msg": str(exc), "username": "", "ip": "", "resp": {}}
        except Exception as exc:  # noqa: BLE001 - keyring/OSError 等兜底, 防异常逸出 slot
            result = {"ok": False, "msg": str(exc), "username": "", "ip": "", "resp": {}}
        self._last_login_attempt = time.time()

        if result["ok"]:
            self._fail_count = 0
            self._auth_error = ""
            self.log(tr("log.login_ok"))
            try:
                status = client.get_status()
            except SrunError:
                status = {}
            self._emit(
                "online",
                username=status.get("username") or result["username"],
                ip=status.get("ip") or result.get("ip") or "",
                login_time=status.get("login_time", ""),
                detail=tr("detail.just_logged"),
                billing=status.get("billing", ""),
                all_bytes=status.get("all_bytes", 0),
            )
            return True

        resp = result.get("resp", {})
        err_code = str(resp.get("error", ""))
        msg = result["msg"]
        self.log(tr("log.login_failed", msg=msg))
        self._fail_streak += 1

        if err_code == "E2620":
            # 设备数超限: 自动踢号(可选)踢掉最旧的其他设备后重试一次
            if self._config.auto_kick and client is not None:
                if self._auto_kick_and_retry(client, result.get("ip", "")):
                    return True
            self._auth_error = msg
            self._fail_count = 0
            self._emit("auth_error", username=result["username"], detail=msg, ecode="E2620")
            self._maybe_push("notify.limit_title", tr("notify.limit_body", msg=msg))
            return False
        if err_code in _AUTH_ERRORS or tr("err.password_error") in msg or tr("err.username_error") in msg:
            self._auth_error = msg
            self._fail_count = 0
            self._emit("auth_error", username=result["username"], detail=msg)
            self._maybe_push("notify.fail_title", tr("notify.fail_body", msg=msg))
            return False

        self._fail_count += 1
        if self._fail_streak >= self._config.notify_threshold:
            self._maybe_push("notify.fail_title", tr("notify.fail_body", msg=msg))
        self._emit("login_fail", username=result["username"], detail=msg)
        return False

    def _check_traffic_limit(self, all_bytes: int) -> None:
        """月度流量上限提醒：超过用户设定值时每月推送一次。"""
        cfg = self._config
        limit_gb = float(cfg.traffic_limit_gb or 0)
        if limit_gb <= 0 or all_bytes <= 0:
            return
        used_gb = all_bytes / 1024 ** 3
        if used_gb < limit_gb:
            return
        month = time.strftime("%Y-%m")
        if cfg.last_traffic_alert == month:
            return
        cfg.last_traffic_alert = month
        cfg.save()
        used = f"{used_gb:.2f} GB"
        self.log(tr("log.traffic_alert", used=used, limit=f"{limit_gb:g} GB"))
        self._maybe_push("notify.traffic_title",
                         tr("notify.traffic_body", used=used, limit=f"{limit_gb:g} GB"))

    def _emit(self, state: str, username: str = "", ip: str = "",
              login_time: str = "", detail: str = "", ecode: str = "",
              billing: str = "", all_bytes: int = 0) -> None:
        if state != self._prev_state:
            append_event(state, detail, self._log_dir)
            self._prev_state = state
        self.statusChanged.emit({
            "state": state,
            "username": username or (self._config.username + self._config.domain),
            "ip": ip,
            "login_time": login_time,
            "detail": detail,
            "ecode": ecode,
            "billing": billing,
            "all_bytes": all_bytes,
            "ts": time.time(),
        })

    def log(self, message: str) -> None:
        self.logLine.emit(time.strftime("[%H:%M:%S] ") + message)


class Monitor(QObject):
    """对 UI 暴露的控制器：封装 worker 线程生命周期，全部走信号-槽。"""

    statusChanged = pyqtSignal(dict)
    logLine = pyqtSignal(str)
    updateAvailable = pyqtSignal(str, str)

    checkRequested = pyqtSignal()
    loginRequested = pyqtSignal()
    intervalChanged = pyqtSignal(int)
    credentialsChanged = pyqtSignal()
    notifyTestRequested = pyqtSignal()

    def __init__(self, config: Config, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._thread = QThread(self)
        self._worker = MonitorWorker(config)
        self._worker.moveToThread(self._thread)

        self._worker.statusChanged.connect(self.statusChanged)
        self._worker.logLine.connect(self.logLine)
        self._worker.updateAvailable.connect(self.updateAvailable)

        self.checkRequested.connect(self._worker.check_manual)
        self.loginRequested.connect(self._worker.login_now)
        self.intervalChanged.connect(self._worker.apply_interval)
        self.credentialsChanged.connect(self._worker.clear_auth_error)
        self.notifyTestRequested.connect(self._worker.notify_test)
        self._thread.started.connect(self._worker.start)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        # 异步请求停止: 绝不在主线程同步等待工作线程的长网络操作
        # (否则托盘退出时界面冻结数秒到数十秒); 残留线程由 main.py 的
        # 进程级退出兜底, 所有数据均已即时落盘。
        QMetaObject.invokeMethod(self._worker, "stop", Qt.ConnectionType.QueuedConnection)
        self._thread.quit()
        # 不 terminate: TerminateThread 可能在持 GIL/写盘中途打断, 造成进程
        # 假死或文件损坏; 残留线程由 main.py 的 os._exit 进程级兜底
        self._thread.wait(300)

    # UI 调用的公开方法（发信号 → 排队到工作线程执行）

    def check_once(self) -> None:
        self.checkRequested.emit()

    def login_now(self) -> None:
        self.loginRequested.emit()

    def notify_test(self) -> None:
        self.notifyTestRequested.emit()

    def config_updated(self) -> None:
        self.intervalChanged.emit(self._config.interval)
        self.credentialsChanged.emit()
