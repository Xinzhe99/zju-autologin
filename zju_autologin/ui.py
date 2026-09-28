"""PyQt6 界面：主窗口（状态 + 设置 + 日志）与系统托盘。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time

from PyQt6.QtCore import Qt, QThread, QTime, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QPainter, QPixmap, QBrush, QColor, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, autostart, crash, i18n, service, theme, updates
from .config import (
    Config,
    append_file_log,
    read_events,
    read_usage,
    resource_path,
)
from .i18n import tr
from .monitor import Monitor
from .srun import SrunClient, SrunError

STATUS_KEYS = (
    "online", "authed_no_internet", "offline", "need_config",
    "auth_error", "login_fail", "no_campus", "checking",
)
DOT_COLORS = {
    "online": "#22c55e",
    "authed_no_internet": "#f59e0b",
    "offline": "#ef4444",
    "need_config": "#94a3b8",
    "auth_error": "#ef4444",
    "login_fail": "#f59e0b",
    "no_campus": "#94a3b8",
    "checking": "#3b82f6",
}
# 出现这些状态 → 状态恢复 online 时弹"已自动重登"通知
_NOTIFY_RELOGIN_FROM = {"offline", "auth_error", "login_fail", "authed_no_internet"}

REPO_URL = "https://github.com/Xinzhe99/zju-autologin"


def _load_pixmap(name: str) -> QPixmap:
    path = resource_path(name)
    if not os.path.isfile(path):
        return QPixmap()
    return QPixmap(path)


def make_tray_icon(state: str) -> QIcon:
    """校徽方形图标 + 右下角状态色点。"""
    base = _load_pixmap("zju_seal_blue.png")
    if base.isNull():
        base = QPixmap(64, 64)
        base.fill(QColor("#0e4192"))
    size = 64
    pixmap = base.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#ffffff"), 2))
    painter.setBrush(QBrush(QColor(DOT_COLORS.get(state, "#94a3b8"))))
    painter.drawEllipse(size - 22, size - 22, 18, 18)
    painter.end()
    return QIcon(pixmap)


def _fmt_bytes(num: int) -> str:
    value = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.2f} TB"


class _FnThread(QThread):
    """在后台线程执行 fn()，结果经信号回传到 UI 线程。"""

    done = pyqtSignal(object)

    def __init__(self, fn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001
            result = exc
        self.done.emit(result)


class UpdateDownloadThread(QThread):
    """下载新版本安装包（frozen 版一键更新）。"""

    progress = pyqtSignal(int)
    finished_ok = pyqtSignal(str)  # 本地文件路径
    finished_err = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        import json as _json
        import urllib.request

        try:
            req = urllib.request.Request(
                updates.REPO_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "ZJU-AutoLogin"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = _json.load(resp)
            target = None
            for asset in data.get("assets") or []:
                name = str(asset.get("name", ""))
                if sys.platform == "win32" and name.endswith("-windows-setup.exe"):
                    target = asset
                    break
                if sys.platform == "darwin" and name.endswith("-macos.dmg"):
                    target = asset
                    break
            if not target:
                self.finished_err.emit("asset not found")
                return
            url = str(target.get("browser_download_url") or "")
            name = str(target.get("name") or "update.bin")
            total = int(target.get("size") or 0)
            digest = str(target.get("digest") or "")  # GitHub API: "sha256:..."
            self.progress.emit(0)
            req = urllib.request.Request(url, headers={"User-Agent": "ZJU-AutoLogin"})
            path = os.path.join(tempfile.gettempdir(), name)
            got = 0
            with urllib.request.urlopen(req, timeout=30) as resp, open(path, "wb") as fh:
                while True:
                    if self._stop:
                        return
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        self.progress.emit(int(got * 100 / total))
            if digest.startswith("sha256:"):
                import hashlib

                sha = hashlib.sha256()
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                        sha.update(chunk)
                if sha.hexdigest() != digest.split(":", 1)[1]:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                    self.finished_err.emit(tr("update.hash_fail"))
                    return
            self.finished_ok.emit(path)
        except Exception as exc:  # noqa: BLE001
            self.finished_err.emit(str(exc))


class DevicesDialog(QDialog):
    """在线设备管理：设备数超限时查看/踢掉其他设备（本机受保护，踢前确认）。"""

    def __init__(self, config: Config, current_ip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._current_ip = current_ip
        self._devices: list[dict] = []
        self._kicked_ip = ""
        self._load_thread: _FnThread | None = None
        self.setWindowTitle(tr("devices.title"))
        self.setModal(True)
        self.resize(560, 380)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        hint = QLabel(tr("devices.hint"))
        hint.setObjectName("statusDetail")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels([
            tr("devices.col_ip"), tr("devices.col_user"), tr("devices.col_os"),
            tr("devices.col_client"), tr("devices.col_since"),
        ])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 130)
        self._table.setColumnWidth(1, 110)
        self._table.setColumnWidth(2, 110)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self._table, 1)

        self._status = QLabel("")
        self._status.setObjectName("statusDetail")
        lay.addWidget(self._status)

        btns = QHBoxLayout()
        btn_refresh = QPushButton(tr("devices.refresh"))
        btn_refresh.setObjectName("secondary")
        btn_refresh.clicked.connect(self.reload)
        self._btn_kick = QPushButton(tr("devices.kick"))
        self._btn_kick.setObjectName("primary")
        self._btn_kick.clicked.connect(self._kick)
        btn_close = QPushButton(tr("btn.close"))
        btn_close.setObjectName("secondary")
        btn_close.clicked.connect(self.reject)
        btns.addWidget(btn_refresh)
        btns.addStretch(1)
        btns.addWidget(self._btn_kick)
        btns.addSpacing(8)
        btns.addWidget(btn_close)
        lay.addLayout(btns)

        self.reload()

    def closeEvent(self, event) -> None:  # noqa: N802
        for thread in (self._load_thread, getattr(self, "_kick_thread", None)):
            if thread is not None and thread.isRunning():
                thread.wait(4000)
        super().closeEvent(event)

    # ------------------------------------------------------------------

    def reload(self) -> None:
        self._status.setText("…")
        self._btn_kick.setEnabled(False)
        cfg = self._config

        def work():
            client = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id)
            return client.list_online_devices(cfg.username, cfg.get_password(), cfg.domain)

        self._load_thread = _FnThread(work, self)
        self._load_thread.done.connect(self._apply_devices)
        self._load_thread.start()

    def _apply_devices(self, devices) -> None:
        if isinstance(devices, Exception) or not devices:
            self._status.setText(tr("devices.load_fail"))
            self._table.setRowCount(0)
            self._btn_kick.setEnabled(bool(devices) and not isinstance(devices, Exception))
            return
        self._devices = list(devices)
        self._table.setRowCount(len(self._devices))
        for row, item in enumerate(self._devices):
            is_local = bool(self._current_ip) and item.get("ip") == self._current_ip
            since = time.strftime("%m-%d %H:%M", time.localtime(item.get("add_time") or 0))
            ip_text = (item.get("ip", "") + (" " + tr("devices.this_machine")
                                             if is_local else ""))
            for col, text in enumerate((
                ip_text, item.get("user_name", ""), item.get("os_name", ""),
                item.get("client_type", ""), since,
            )):
                self._table.setItem(row, col, QTableWidgetItem(text))
        self._status.setText("")
        self._btn_kick.setEnabled(True)

    def _kick(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._devices):
            return
        device = self._devices[row]
        ip = device.get("ip", "")
        if self._current_ip and ip == self._current_ip:
            self._status.setText(tr("devices.cant_kick_self"))
            return
        answer = QMessageBox.question(
            self, tr("devices.confirm_title"), tr("devices.confirm_kick", ip=ip),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._pending_ip = ip
        self._btn_kick.setEnabled(False)
        cfg = self._config

        def work():
            client = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id)
            return client.kick_device(cfg.username, ip)

        self._kick_thread = _FnThread(work, self)
        self._kick_thread.done.connect(self._kick_done)
        self._kick_thread.start()

    def _kick_done(self, result) -> None:
        ok = bool(result and result[0])
        if ok:
            self._kicked_ip = self._pending_ip
            self.accept()
        else:
            self._status.setText(tr("update.failed", msg=result[1] if result else ""))
            self._btn_kick.setEnabled(True)


class UsageChart(QWidget):
    """近 30 天每日流量柱状图（QPainter 手绘，不引第三方依赖）。"""

    def __init__(self, values: list[float]) -> None:
        super().__init__()
        self._values = values  # 每日增量 GB
        self.setMinimumHeight(110)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PyQt6.QtGui import QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if not self._values:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, tr("stats.no_data"))
            return
        peak = max(self._values) or 1.0
        n = len(self._values)
        gap = 3
        bar_w = max(2, (w - 8 - gap * (n - 1)) / n)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1a5ec4"))
        for i, v in enumerate(self._values):
            bh = max(2, (h - 18) * v / peak)
            x = 4 + i * (bar_w + gap)
            painter.drawRoundedRect(int(x), int(h - 14 - bh), int(bar_w), int(bh), 2, 2)
        painter.setPen(QColor("#8ba1bd" if self.palette().color(
            self.backgroundRole()).lightness() < 128 else "#7a8aa2"))
        painter.drawText(4, h - 2, f"max {peak:.2f} GB")
        painter.drawText(w - 90, h - 2, f"{n} days")


class StatsDialog(QDialog):
    """网络事件时间线、近 7 天掉线统计与每日流量曲线。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("stats.title"))
        self.setModal(True)
        self.resize(560, 500)
        lay = QVBoxLayout(self)
        events = read_events(300)

        # 每日流量增量
        usage = read_usage(40)
        deltas: list[float] = []
        for i, row in enumerate(usage):
            prev = usage[i - 1]["bytes"] if i > 0 else 0
            delta = row["bytes"] - prev
            if delta < 0:  # 计费周期重置
                delta = row["bytes"]
            deltas.append(delta / 1024 ** 3)
        if deltas:
            usage_title = QLabel(tr("stats.usage_title"))
            usage_title.setObjectName("cardTitle")
            lay.addWidget(usage_title)
            lay.addWidget(UsageChart(deltas[-30:]), 1)

        # 会话在线天数
        main = parent if isinstance(parent, MainWindow) else None
        login_time = (main._last_status.get("login_time") or "") if main else ""
        days = 0
        if login_time:
            try:
                ts = time.mktime(time.strptime(login_time, "%Y-%m-%d %H:%M"))
                days = int((time.time() - ts) / 86400) + 1
            except (ValueError, OverflowError):
                days = 0
        if days:
            head = QLabel(tr("stats.online_days", days=days))
            head.setObjectName("cardTitle")
            lay.addWidget(head)

        drops_title = QLabel(tr("stats.drop_count", n=sum(
            1 for e in events if e.get("event") == "offline" and e.get("ts", 0) >= time.time() - 7 * 86400)))
        drops_title.setObjectName("cardTitle")
        lay.addWidget(drops_title)
        table = QTableWidget(0, 3)
        week_ago = time.time() - 7 * 86400

        table.setHorizontalHeaderLabels(["#", tr("field.last_check"), tr("status.offline")])
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 40)
        table.setColumnWidth(1, 150)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        for e in reversed(events):
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            table.setItem(row, 1, QTableWidgetItem(time.strftime(
                "%m-%d %H:%M:%S", time.localtime(e.get("ts") or 0))))
            table.setItem(row, 2, QTableWidgetItem(str(e.get("detail") or e.get("event") or "")))
        if table.rowCount() == 0:
            table.insertRow(0)
            table.setItem(0, 0, QTableWidgetItem("-"))
            table.setItem(0, 1, QTableWidgetItem(tr("stats.empty")))
        lay.addWidget(table, 1)


class PortalWizardDialog(QDialog):
    """其他深澜高校门户接入向导：填门户地址 → 自动探测 ac_id/IP → 保存。"""

    def __init__(self, config: Config, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._thread: _FnThread | None = None
        self._detected_acid = ""
        self.setWindowTitle(tr("portal.title"))
        self.setModal(True)
        self.setFixedWidth(480)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        self._lbl_url = QLabel()
        self._lbl_url.setObjectName("fieldKey")
        lay.addWidget(self._lbl_url)
        self._edit_url = QLineEdit()
        self._edit_url.setPlaceholderText("https://xxx.edu.cn")
        lay.addWidget(self._edit_url)

        self._result = QLabel("")
        self._result.setObjectName("statusDetail")
        self._result.setWordWrap(True)
        lay.addWidget(self._result)

        btns = QHBoxLayout()
        self._btn_detect = QPushButton(tr("portal.detect"))
        self._btn_detect.setObjectName("secondary")
        self._btn_detect.clicked.connect(self._detect)
        self._btn_save = QPushButton(tr("portal.save"))
        self._btn_save.setObjectName("primary")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._save)
        btn_close = QPushButton(tr("btn.close"))
        btn_close.setObjectName("secondary")
        btn_close.clicked.connect(self.reject)
        btns.addWidget(self._btn_detect)
        btns.addStretch(1)
        btns.addWidget(self._btn_save)
        btns.addSpacing(8)
        btns.addWidget(btn_close)
        lay.addLayout(btns)

    def _detect(self) -> None:
        base = self._edit_url.text().strip().rstrip("/")
        if not base.startswith("http"):
            self._result.setText(tr("msg.cfg_import_fail", msg="URL"))
            return
        self._btn_detect.setEnabled(False)
        self._result.setText(tr("portal.detecting"))

        def work():
            client = SrunClient(base_url=base, timeout=8)
            return base, client.probe_portal()

        self._thread = _FnThread(work, self)
        self._thread.done.connect(self._apply)
        self._thread.start()

    def _apply(self, result) -> None:
        self._btn_detect.setEnabled(True)
        if isinstance(result, Exception):
            self._result.setText(tr("portal.result_fail", msg=result))
            return
        base, probe = result
        self._detected_base = base
        if probe.get("ok"):
            self._detected_acid = probe.get("acid", "")
            self._result.setText(tr("portal.result_ok",
                                    acid=probe.get("acid", "?"), ip=probe.get("ip", "?")))
            self._btn_save.setEnabled(True)
        else:
            self._result.setText(tr("portal.result_fail", msg=probe.get("msg", "?")))

    def _save(self) -> None:
        self._config.base_url = getattr(self, "_detected_base", "")
        self._config.ac_id = self._detected_acid or "80"
        self._config.save()
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, config: Config, monitor: Monitor) -> None:
        super().__init__()
        self._config = config
        self._monitor = monitor
        self._force_quit = False
        self._warned_auth_error = False
        self._tray_state = ""
        self._last_status: dict = {"state": "checking", "detail": ""}
        self._update_version = ""
        self._update_url = ""
        self._downloader: UpdateDownloadThread | None = None

        self.setWindowTitle(tr("app.name"))
        icon_path = resource_path("zju.ico")
        self.setWindowIcon(QIcon(icon_path if os.path.isfile(icon_path)
                                 else resource_path("zju_seal_blue.png")))
        self.resize(800, 860)
        self.setMinimumSize(740, 700)
        geo = str(config.win_geometry or "")
        if geo:
            try:
                x, y, w, h = (int(v) for v in geo.split(","))
                screen = QApplication.primaryScreen().availableGeometry()
                if w >= self.minimumWidth() and h >= self.minimumHeight()                         and screen.contains(x + w // 2, y + 20):
                    self.setGeometry(x, y, w, h)
                else:
                    self.resize(w, h)
            except (ValueError, TypeError):
                pass
        self.setStyleSheet(theme.get_qss(config.theme))

        self._build_ui()
        self._build_tray()
        self.retranslate_ui()
        self._load_settings_into_ui()

        monitor.statusChanged.connect(self._on_status)
        monitor.logLine.connect(self._append_log)
        monitor.updateAvailable.connect(self._on_update_available)
        crash.UiHolder.window = self

    # ------------------------------------------------------------------ UI

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        return frame

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(12)

        # ---- 头部（深蓝渐变 + 官方白色校徽）----
        header = QFrame()
        header.setObjectName("header")
        header.setFixedHeight(88)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(20, 12, 20, 12)
        logo = _load_pixmap("zju_logo.png")
        logo_label = QLabel()
        if not logo.isNull():
            logo_label.setPixmap(logo.scaledToHeight(52, Qt.TransformationMode.SmoothTransformation))
        hlay.addWidget(logo_label)
        hlay.addStretch(1)
        self._version_label = QLabel()
        self._version_label.setObjectName("headerHint")
        hlay.addWidget(self._version_label)
        root.addWidget(header)

        # ---- 更新横幅（有新版本时显示）----
        self._update_banner = QPushButton()
        self._update_banner.setObjectName("primary")
        self._update_banner.clicked.connect(self._do_update)
        self._update_banner.hide()
        root.addWidget(self._update_banner)

        # ---- 状态卡片 ----
        status_card = self._card()
        slay = QVBoxLayout(status_card)
        slay.setContentsMargins(20, 16, 20, 16)
        slay.setSpacing(8)

        status_row = QHBoxLayout()
        self._dot = QLabel()
        self._dot.setFixedSize(14, 14)
        self._status_text = QLabel()
        self._status_text.setObjectName("statusText")
        status_row.addWidget(self._dot)
        status_row.addSpacing(10)
        status_row.addWidget(self._status_text)
        status_row.addStretch(1)
        self._btn_devices = QPushButton()
        self._btn_devices.setObjectName("secondary")
        self._btn_devices.clicked.connect(self._show_devices)
        self._btn_devices.hide()
        status_row.addWidget(self._btn_devices)
        self._btn_check = QPushButton()
        self._btn_check.setObjectName("secondary")
        self._btn_check.clicked.connect(self._monitor.check_once)
        self._btn_login = QPushButton()
        self._btn_login.setObjectName("primary")
        self._btn_login.clicked.connect(self._on_login_clicked)
        status_row.addWidget(self._btn_check)
        status_row.addSpacing(8)
        status_row.addWidget(self._btn_login)
        slay.addLayout(status_row)

        self._status_detail = QLabel()
        self._status_detail.setObjectName("statusDetail")
        self._status_detail.setWordWrap(True)
        slay.addWidget(self._status_detail)

        grid_host = QFrame()
        grid_lay = QGridLayout(grid_host)
        grid_lay.setContentsMargins(0, 6, 0, 0)
        grid_lay.setHorizontalSpacing(28)
        grid_lay.setVerticalSpacing(4)
        self._fields: dict[str, QLabel] = {}
        self._field_labels: dict[str, QLabel] = {}
        keys = ("account", "ip", "login_time", "last_check", "billing", "traffic")
        for idx, key in enumerate(keys):
            klabel = QLabel()
            klabel.setObjectName("fieldKey")
            vlabel = QLabel(tr("statuscard.never"))
            vlabel.setObjectName("fieldValue")
            vlabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid_lay.addWidget(klabel, (idx // 4) * 2, idx % 4)
            grid_lay.addWidget(vlabel, (idx // 4) * 2 + 1, idx % 4)
            self._fields[key] = vlabel
            self._field_labels[key] = klabel
        slay.addWidget(grid_host)
        root.addWidget(status_card)

        # ---- 设置卡片 ----
        settings_card = self._card()
        glay = QVBoxLayout(settings_card)
        glay.setContentsMargins(20, 16, 20, 16)
        glay.setSpacing(10)
        self._settings_title = QLabel()
        self._settings_title.setObjectName("cardTitle")
        glay.addWidget(self._settings_title)

        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self._form_labels: dict[str, QLabel] = {}

        def add_row(row: int, key: str, widget: QWidget) -> None:
            label = QLabel()
            label.setObjectName("fieldKey")
            label.setFixedWidth(110)
            form.addWidget(label, row, 0)
            form.addWidget(widget, row, 1)
            self._form_labels[key] = label

        self._edit_user = QLineEdit()
        self._edit_domain = QLineEdit()
        pwd_host = QFrame()
        pwd_lay = QHBoxLayout(pwd_host)
        pwd_lay.setContentsMargins(0, 0, 0, 0)
        pwd_lay.setSpacing(2)
        self._edit_pwd = QLineEdit()
        self._edit_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._eye = QToolButton()
        self._eye.setObjectName("eye")
        self._eye.setCheckable(True)
        self._eye.setText("👁")
        self._eye.setCursor(Qt.CursorShape.PointingHandCursor)
        self._eye.setFixedWidth(34)
        self._eye.toggled.connect(
            lambda on: self._edit_pwd.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        pwd_lay.addWidget(self._edit_pwd, 1)
        pwd_lay.addWidget(self._eye)

        self._spin_interval = QSpinBox()
        self._spin_interval.setRange(10, 600)
        self._combo_lang = QComboBox()
        for lang in ("auto", "zh-CN", "en-US"):
            self._combo_lang.addItem(self._lang_label(lang), lang)
        self._combo_theme = QComboBox()
        for mode in ("auto", "light", "dark"):
            self._combo_theme.addItem(tr(f"theme.{mode}"), mode)

        add_row(0, "username", self._edit_user)
        add_row(1, "domain", self._edit_domain)
        add_row(2, "password", pwd_host)
        add_row(3, "interval", self._spin_interval)
        add_row(4, "language", self._combo_lang)
        add_row(5, "theme", self._combo_theme)
        glay.addLayout(form)

        # 选项行
        self._chk_auto = QCheckBox()
        self._chk_tray = QCheckBox()
        self._chk_updates = QCheckBox()
        self._chk_boot = QCheckBox()
        self._chk_service = QCheckBox()
        opts = QHBoxLayout()
        opts.setSpacing(16)
        for chk in (self._chk_auto, self._chk_tray, self._chk_updates, self._chk_boot):
            opts.addWidget(chk)
        opts.addStretch(1)
        glay.addLayout(opts)
        glay.addWidget(self._chk_service)
        self._service_hint = QLabel()
        self._service_hint.setObjectName("statusDetail")
        self._service_hint.setWordWrap(True)
        glay.addWidget(self._service_hint)
        self._service_heartbeat = QLabel()
        self._service_heartbeat.setObjectName("statusDetail")
        glay.addWidget(self._service_heartbeat)
        self._hb_timer = QTimer(self)
        self._hb_timer.setInterval(60_000)
        self._hb_timer.timeout.connect(self._refresh_service_heartbeat)
        self._hb_timer.start()

        # 通知区
        self._notify_title = QLabel()
        self._notify_title.setObjectName("cardTitle")
        glay.addWidget(self._notify_title)
        notify_grid = QGridLayout()
        notify_grid.setHorizontalSpacing(10)
        notify_grid.setVerticalSpacing(8)
        self._combo_provider = QComboBox()
        for pid in ("none", "bark", "serverchan", "wecom", "dingtalk", "smtp"):
            self._combo_provider.addItem(self._provider_label(pid), pid)
        self._edit_key = QLineEdit()
        self._btn_notify_test = QPushButton()
        self._btn_notify_test.setObjectName("secondary")
        self._btn_notify_test.clicked.connect(self._monitor.notify_test)
        self._spin_threshold = QSpinBox()
        self._spin_threshold.setRange(1, 10)
        self._spin_traffic = QSpinBox()
        self._spin_traffic.setRange(0, 2048)
        self._chk_recovery = QCheckBox()
        self._notify_labels: list[QLabel] = []
        for col, (label_key, widget) in enumerate((
            ("notify.provider", self._combo_provider),
            ("notify.key", self._edit_key),
        )):
            label = QLabel()
            label.setObjectName("fieldKey")
            notify_grid.addWidget(label, 0, col * 2)
            notify_grid.addWidget(widget, 0, col * 2 + 1)
            self._notify_labels.append(label)
        actions = QHBoxLayout()
        self._lbl_threshold = QLabel()
        self._lbl_threshold.setObjectName("fieldKey")
        self._lbl_recovery = QLabel()
        self._lbl_recovery.setObjectName("fieldKey")
        actions.addWidget(self._lbl_threshold)
        actions.addWidget(self._spin_threshold)
        actions.addSpacing(14)
        actions.addWidget(self._chk_recovery)
        actions.addSpacing(14)
        self._lbl_traffic = QLabel()
        self._lbl_traffic.setObjectName("fieldKey")
        actions.addWidget(self._lbl_traffic)
        actions.addWidget(self._spin_traffic)
        actions.addStretch(1)
        actions.addWidget(self._btn_notify_test)
        notify_grid.addLayout(actions, 1, 0, 1, 4)
        glay.addLayout(notify_grid)

        # 高级选项
        self._btn_advanced = QToolButton()
        self._btn_advanced.setObjectName("eye")
        self._btn_advanced.setCheckable(True)
        self._btn_advanced.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._btn_advanced.setFixedHeight(24)
        glay.addWidget(self._btn_advanced)
        self._advanced_host = QFrame()
        adv_grid = QGridLayout(self._advanced_host)
        adv_grid.setContentsMargins(0, 0, 0, 0)
        adv_grid.setHorizontalSpacing(10)
        adv_grid.setVerticalSpacing(8)
        self._edit_base = QLineEdit()
        self._edit_acid = QLineEdit()
        self._edit_heartbeat = QLineEdit()
        self._edit_heartbeat.setToolTip(tr("hb.hint"))
        self._chk_proactive = QCheckBox()
        self._time_proactive = QTimeEdit(QTime(3, 0))
        self._time_proactive.setDisplayFormat("HH:mm")
        self._adv_labels: list[QLabel] = []
        for row, (label_key, widget) in enumerate((
            ("field.base_url", self._edit_base),
            ("field.ac_id", self._edit_acid),
            ("hb.url", self._edit_heartbeat),
        )):
            label = QLabel()
            label.setObjectName("fieldKey")
            adv_grid.addWidget(label, row, 0)
            adv_grid.addWidget(widget, row, 1)
            self._adv_labels.append(label)
        prow = QHBoxLayout()
        prow.addWidget(self._chk_proactive)
        prow.addWidget(self._time_proactive)
        prow.addStretch(1)
        self._btn_export = QPushButton()
        self._btn_export.setObjectName("secondary")
        self._btn_export.clicked.connect(self._export_config)
        self._btn_import = QPushButton()
        self._btn_import.setObjectName("secondary")
        self._btn_import.clicked.connect(self._import_config)
        prow.addWidget(self._btn_export)
        prow.addWidget(self._btn_import)
        self._btn_portal = QPushButton()
        self._btn_portal.setObjectName("secondary")
        self._btn_portal.clicked.connect(self._show_portal_wizard)
        prow.addWidget(self._btn_portal)
        adv_grid.addLayout(prow, 2, 0, 1, 2)
        self._advanced_host.setVisible(False)
        self._btn_advanced.toggled.connect(self._advanced_host.setVisible)
        glay.addWidget(self._advanced_host)

        # 保存行
        save_row = QHBoxLayout()
        self._save_hint = QLabel("")
        self._save_hint.setObjectName("statusDetail")
        self._btn_save = QPushButton()
        self._btn_save.setObjectName("primary")
        self._btn_save.clicked.connect(self._save_settings)
        save_row.addStretch(1)
        save_row.addWidget(self._save_hint)
        save_row.addSpacing(10)
        save_row.addWidget(self._btn_save)
        glay.addLayout(save_row)
        root.addWidget(settings_card)

        # ---- 日志卡片 ----
        log_card = self._card()
        llay = QVBoxLayout(log_card)
        llay.setContentsMargins(20, 14, 20, 14)
        llay.setSpacing(6)
        log_head = QHBoxLayout()
        self._log_title = QLabel()
        self._log_title.setObjectName("cardTitle")
        log_head.addWidget(self._log_title)
        log_head.addStretch(1)
        self._btn_diag = QPushButton()
        self._btn_diag.setObjectName("secondary")
        self._btn_diag.clicked.connect(self._copy_diagnostics)
        self._btn_stats = QPushButton()
        self._btn_stats.setObjectName("secondary")
        self._btn_stats.clicked.connect(lambda: StatsDialog(self).exec())
        self._btn_openlog = QPushButton()
        self._btn_openlog.setObjectName("secondary")
        self._btn_openlog.clicked.connect(self._open_log_folder)
        log_head.addWidget(self._btn_diag)
        log_head.addWidget(self._btn_stats)
        log_head.addWidget(self._btn_openlog)
        llay.addLayout(log_head)
        self._log = QPlainTextEdit()
        self._log.setObjectName("log")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(400)
        self._log.setFixedHeight(120)
        llay.addWidget(self._log)
        root.addWidget(log_card, 1)

        self._tip = QLabel()
        self._tip.setObjectName("statusDetail")
        root.addWidget(self._tip)

    # ------------------------------------------------------ 标签/文案辅助

    @staticmethod
    def _lang_label(lang: str) -> str:
        if lang == "auto":
            return ("跟随系统 / Follow system"
                    if i18n.detect_system_lang() == "zh-CN" else "Follow system / 跟随系统")
        return i18n.LANG_LABELS.get(lang, lang)

    @staticmethod
    def _provider_label(pid: str) -> str:
        names = {
            "none": ("不启用", "Disabled"),
            "bark": ("Bark (iOS)", "Bark (iOS)"),
            "serverchan": ("Server酱", "ServerChan"),
            "wecom": ("企业微信机器人", "WeCom bot"),
            "dingtalk": ("钉钉机器人", "DingTalk bot"),
            "smtp": ("邮件 (SMTP)", "Email (SMTP)"),
        }
        zh, en = names.get(pid, (pid, pid))
        return zh if i18n.current_lang().startswith("zh") else en

    def retranslate_ui(self) -> None:
        """运行时切换语言后刷新全部文本。"""
        self.setWindowTitle(tr("app.name"))
        self._version_label.setText(tr("app.header_badge", version=__version__))
        self._btn_check.setText(tr("btn.check_now"))
        self._btn_login.setText(tr("btn.login_now"))
        self._btn_save.setText(tr("btn.save"))
        self._btn_devices.setText(tr("btn.devices"))
        self._settings_title.setText(tr("card.settings"))
        self._log_title.setText(tr("card.log"))
        self._tip.setText(tr("tip.footer"))
        self._save_hint.setText("")
        self._btn_diag.setText(tr("btn.copy_diag"))
        self._btn_stats.setText(tr("btn.stats"))
        self._btn_openlog.setText(tr("btn.open_log"))

        for key, label in self._field_labels.items():
            if key == "billing":
                label.setText(tr("field.billing"))
            elif key == "traffic":
                label.setText(tr("field.traffic"))
            else:
                label.setText(tr(f"field.{key}"))
        self._form_labels["username"].setText(tr("field.username"))
        self._form_labels["domain"].setText(tr("field.domain"))
        self._form_labels["password"].setText(tr("field.password"))
        self._form_labels["interval"].setText(tr("field.interval"))
        self._form_labels["language"].setText(tr("field.language"))
        self._form_labels["theme"].setText(tr("settings.theme"))

        self._edit_user.setPlaceholderText(tr("ph.username"))
        self._edit_domain.setPlaceholderText(tr("ph.domain"))
        self._edit_pwd.setPlaceholderText(tr("ph.password"))
        self._edit_key.setPlaceholderText(tr("notify.key"))
        self._edit_base.setPlaceholderText("https://net.zju.edu.cn")
        self._edit_acid.setPlaceholderText("80 / auto")
        self._edit_heartbeat.setToolTip(tr("hb.hint"))
        self._spin_interval.setSuffix(f" {tr('unit.seconds', n='')}".rstrip())

        self._chk_auto.setText(tr("chk.auto_login"))
        self._chk_tray.setText(tr("chk.minimize_tray"))
        self._chk_updates.setText(tr("chk.check_updates"))
        self._chk_boot.setText(tr("chk.autostart"))
        self._chk_service.setText(tr("service.chk"))
        self._service_hint.setText(tr("service.hint"))
        self._notify_title.setText(tr("settings.notify"))
        self._chk_recovery.setText(tr("notify.recovery"))
        self._lbl_threshold.setText(tr("notify.threshold"))
        self._lbl_traffic.setText(tr("settings.traffic_limit"))
        self._spin_traffic.setSuffix(" GB")
        self._btn_notify_test.setText(tr("btn.notify_test"))
        self._btn_advanced.setText(tr("settings.advanced"))
        self._chk_proactive.setText(tr("chk.proactive"))
        for i in range(self._combo_lang.count()):
            self._combo_lang.setItemText(i, self._lang_label(self._combo_lang.itemData(i)))
        for i in range(self._combo_theme.count()):
            mode = self._combo_theme.itemData(i)
            self._combo_theme.setItemText(i, tr(f"theme.{mode}"))
        for i in range(self._combo_provider.count()):
            pid = self._combo_provider.itemData(i)
            self._combo_provider.setItemText(i, self._provider_label(pid))
        for label, key in zip(self._notify_labels, ("notify.provider", "notify.key")):
            label.setText(tr(key))
        for label, key in zip(self._adv_labels, ("field.base_url", "field.ac_id", "hb.url")):
            label.setText(tr(key))
        self._btn_export.setText(tr("btn.export_cfg"))
        self._btn_import.setText(tr("btn.import_cfg"))
        self._btn_portal.setText(tr("btn.portal_wizard"))

        for act, key in ((self._act_show, "tray.show"), (self._act_check, "tray.check"),
                         (self._act_login, "tray.login"), (self._act_about, "tray.about"),
                         (self._act_quit, "tray.quit")):
            act.setText(tr(key))
        self._act_auto.setText(tr("chk.auto_login"))
        self._tray_boot.setText(tr("tray.autostart"))

        if self._update_banner.isVisible():
            self._update_banner.setText(tr("btn.update_now", version=self._update_version))

        self._set_status_ui(self._last_status.get("state", "checking"),
                            self._last_status.get("detail", ""))
        self._refresh_tray_tooltip()

    # ---------------------------------------------------------- 托盘

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(make_tray_icon("checking"), self)
        self._refresh_tray_tooltip()

        menu = QMenu(self)
        self._act_show = QAction(menu)
        self._act_check = QAction(menu)
        self._act_login = QAction(menu)
        self._act_auto = QAction(menu)
        self._act_auto.setCheckable(True)
        self._act_auto.toggled.connect(self._toggle_auto_login)
        self._tray_boot = QAction(menu)
        self._tray_boot.setCheckable(True)
        self._act_about = QAction(menu)
        self._act_quit = QAction(menu)
        self._act_show.triggered.connect(self.show_normal)
        self._act_check.triggered.connect(self._monitor.check_once)
        self._act_login.triggered.connect(self._on_login_clicked)
        self._tray_boot.toggled.connect(self._toggle_autostart_from_tray)
        self._act_about.triggered.connect(self._show_about)
        self._act_quit.triggered.connect(self.quit_app)
        for act in (self._act_show, self._act_check, self._act_login):
            menu.addAction(act)
        menu.addAction(self._act_auto)
        menu.addSeparator()
        menu.addAction(self._tray_boot)
        menu.addSeparator()
        menu.addAction(self._act_about)
        menu.addAction(self._act_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.messageClicked.connect(self._on_message_clicked)
        self._tray.show()

    def _show_about(self) -> None:
        QMessageBox.about(
            self, tr("about.title"),
            tr("about.text", app=tr("app.name"), version=__version__, url=REPO_URL))

    def _refresh_tray_tooltip(self) -> None:
        status = tr(f"status.{self._last_status.get('state', 'checking')}")
        ip = self._last_status.get("ip") or ""
        traffic = self._last_status.get("all_bytes") or 0
        if traffic:
            status += f" · {_fmt_bytes(traffic)}"
        self._tray.setToolTip(
            tr("tray.tooltip_ip", app=tr("app.name"), status=status, ip=ip)
            if ip else tr("tray.tooltip", app=tr("app.name"), status=status))

    def _load_settings_into_ui(self) -> None:
        cfg = self._config
        self._edit_user.setText(cfg.username)
        self._edit_domain.setText(cfg.domain)
        self._spin_interval.setValue(cfg.interval)
        self._chk_auto.setChecked(bool(cfg.auto_login))
        self._chk_tray.setChecked(bool(cfg.minimize_to_tray))
        self._chk_updates.setChecked(bool(cfg.check_updates))
        lang = cfg.language if cfg.language in ("auto", "zh-CN", "en-US") else "auto"
        self._combo_lang.setCurrentIndex(max(0, self._combo_lang.findData(lang)))
        theme_mode = cfg.theme if cfg.theme in ("auto", "light", "dark") else "auto"
        self._combo_theme.setCurrentIndex(max(0, self._combo_theme.findData(theme_mode)))
        self._chk_boot.setChecked(autostart.is_enabled())
        self._chk_service.setChecked(service.is_installed())
        self._combo_provider.setCurrentIndex(
            max(0, self._combo_provider.findData(cfg.notify_provider or "none")))
        self._edit_key.setText(cfg.notify_key or "")
        self._spin_threshold.setValue(cfg.notify_threshold)
        self._chk_recovery.setChecked(bool(cfg.notify_recovery))
        self._spin_traffic.setValue(int(cfg.traffic_limit_gb or 0))
        self._edit_base.setText(cfg.base_url or "")
        self._edit_acid.setText(str(cfg.ac_id or "80"))
        self._edit_heartbeat.setText(cfg.heartbeat_url or "")
        self._chk_proactive.setChecked(bool(cfg.proactive_relogin))
        try:
            hh, mm = str(cfg.proactive_time or "03:00").split(":")
            self._time_proactive.setTime(QTime(int(hh) % 24, int(mm) % 60))
        except (ValueError, AttributeError):
            pass
        self._tray_boot.setChecked(autostart.is_enabled())
        self._act_auto.setChecked(bool(cfg.auto_login))
        if cfg.get_password():
            self._edit_pwd.setPlaceholderText(
                tr("ph.password_saved", backend=tr(f"password.storage.{cfg.password_backend_key()}")))

    # ---------------------------------------------------------------- 动作

    def _on_login_clicked(self) -> None:
        if not self._config.username or not self._config.get_password():
            self._save_settings()
        if not self._config.username or not self._config.get_password():
            self._status_detail.setText(tr("detail.fill_creds"))
            return
        self._set_status_ui("checking", tr("detail.logging_in"))
        self._monitor.login_now()

    def _save_settings(self) -> None:
        cfg = self._config
        cfg.username = self._edit_user.text()
        cfg.domain = self._edit_domain.text()
        cfg.interval = self._spin_interval.value()
        cfg.auto_login = self._chk_auto.isChecked()
        cfg.minimize_to_tray = self._chk_tray.isChecked()
        cfg.check_updates = self._chk_updates.isChecked()
        cfg.language = self._combo_lang.currentData() or "auto"
        cfg.theme = self._combo_theme.currentData() or "auto"
        cfg.notify_provider = self._combo_provider.currentData() or "none"
        cfg.notify_key = self._edit_key.text().strip()
        cfg.notify_threshold = self._spin_threshold.value()
        cfg.notify_recovery = self._chk_recovery.isChecked()
        cfg.traffic_limit_gb = self._spin_traffic.value()
        cfg.base_url = self._edit_base.text().strip() or "https://net.zju.edu.cn"
        cfg.ac_id = self._edit_acid.text().strip() or "80"
        cfg.heartbeat_url = self._edit_heartbeat.text().strip()
        cfg.proactive_relogin = self._chk_proactive.isChecked()
        cfg.proactive_time = self._time_proactive.time().toString("HH:mm")

        pwd = self._edit_pwd.text()
        if pwd:
            cfg.set_password(pwd)
            self._edit_pwd.clear()
            self._edit_pwd.setPlaceholderText(
                tr("ph.password_saved", backend=tr(f"password.storage.{cfg.password_backend_key()}")))
        if not cfg.get_password() and cfg.username:
            self._save_hint.setText(tr("hint.need_password"))
            return

        boot_ok = autostart.set_enabled(self._chk_boot.isChecked())
        self._chk_boot.setChecked(boot_ok)
        self._tray_boot.setChecked(boot_ok)
        cfg.autostart = boot_ok
        cfg.save()

        # 系统级保活
        if self._chk_service.isChecked() != service.is_installed():
            if self._chk_service.isChecked():
                ok, _ = service.install(cfg)
                self._append_log(tr("service.on_ok") if ok else tr("service.on_fail"))
                self._chk_service.setChecked(ok)
            else:
                ok, _ = service.uninstall()
                self._append_log(tr("service.off_ok") if ok else tr("service.on_fail"))
                self._chk_service.setChecked(not ok)

        # 语言实时切换
        if i18n.current_lang() != cfg.language:
            i18n.set_lang(cfg.language)
        self.retranslate_ui()
        # 主题实时切换
        self.setStyleSheet(theme.get_qss(cfg.theme))

        self._monitor.config_updated()
        self._save_hint.setText(tr("hint.save_ok"))
        QTimer.singleShot(2500, lambda: self._save_hint.setText(""))
        self._append_log(tr("log.settings_saved",
                            backend=tr(f"password.storage.{cfg.password_backend_key()}")))
        self._monitor.check_once()

    def _apply_service_toggle(self, enable: bool) -> None:
        """后台线程安装/卸载系统级计划任务，完成后回填状态。"""
        cfg = self._config
        self._chk_service.setEnabled(False)

        def work():
            return service.install(cfg) if enable else service.uninstall()

        def done(result):
            ok = bool(result and result[0])
            self._chk_service.setEnabled(True)
            self._chk_service.setChecked(ok if enable else not ok)
            if enable:
                self._append_log(tr("service.on_ok") if ok else tr("service.on_fail"))
            else:
                self._append_log(tr("service.off_ok") if ok else tr("service.on_fail"))

        self._service_thread = _FnThread(work, self)
        self._service_thread.done.connect(done)
        self._service_thread.start()

    def _toggle_auto_login(self, on: bool) -> None:
        self._config.auto_login = on
        self._config.save()
        self._chk_auto.setChecked(on)
        self._append_log(tr("log.auto_login_on") if on else tr("log.auto_login_off"))

    def _toggle_autostart_from_tray(self, on: bool) -> None:
        result = autostart.set_enabled(on)
        self._chk_boot.setChecked(result)
        self._tray_boot.setChecked(result)
        self._config.autostart = result
        self._config.save()
        self._append_log(tr("log.autostart_on") if result else tr("log.autostart_off"))

    def _copy_diagnostics(self) -> None:
        cfg = self._config
        lines = [
            f"ZJU-AutoLogin v{__version__}",
            f"Python {sys.version.split()[0]} @ {sys.platform}",
            f"portal: {cfg.base_url} ac_id={cfg.ac_id}",
            f"account: {cfg.username}{cfg.domain}",
            f"state: {self._last_status.get('state')} ip={self._last_status.get('ip')}",
            f"notify: {cfg.notify_provider}",
            "", "---- last logs ----",
        ]
        lines += self._log.toPlainText().splitlines()[-50:]
        QApplication.clipboard().setText("\n".join(lines))
        self._save_hint.setText(tr("diag.copied"))
        QTimer.singleShot(2500, lambda: self._save_hint.setText(""))

    def _export_config(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        from .config import _DEFAULTS

        path, _ = QFileDialog.getSaveFileName(
            self, tr("btn.export_cfg"), "zju-autologin-config.json", "JSON (*.json)")
        if not path:
            return
        payload = {"_exported_by": f"ZJU-AutoLogin v{__version__}"}
        for key in _DEFAULTS:
            if key != "win_geometry":
                payload[key] = self._config.data.get(key)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            self._save_hint.setText(tr("msg.cfg_exported", path=os.path.basename(path)))
        except OSError as exc:
            self._save_hint.setText(tr("msg.cfg_import_fail", msg=exc))
        QTimer.singleShot(3500, lambda: self._save_hint.setText(""))

    def _import_config(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        from .config import _DEFAULTS

        path, _ = QFileDialog.getOpenFileName(self, tr("btn.import_cfg"), "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
                payload = json.load(fh)
            if not isinstance(payload, dict):
                raise ValueError("bad format")
        except (OSError, ValueError) as exc:
            self._save_hint.setText(tr("msg.cfg_import_fail", msg=exc))
            QTimer.singleShot(3500, lambda: self._save_hint.setText(""))
            return
        for key in _DEFAULTS:
            if key != "win_geometry" and key in payload:
                self._config.data[key] = payload[key]
        self._config.save()
        self._load_settings_into_ui()
        self._monitor.config_updated()
        self._save_hint.setText(tr("msg.cfg_imported"))
        QTimer.singleShot(3500, lambda: self._save_hint.setText(""))
        self._monitor.check_once()

    def _refresh_service_heartbeat(self) -> None:
        """显示系统级保活服务的心跳状态（watch 进程每轮写入时间戳）。"""
        if not service.is_installed():
            self._service_heartbeat.setText(tr("service.heartbeat_off"))
            return
        from .config import service_config_dir

        try:
            raw = (service_config_dir() / "service.heartbeat").read_text(encoding="ascii").strip()
            mins = int((time.time() - float(raw)) / 60)
        except (OSError, ValueError):
            mins = -1
        if mins < 0:
            self._service_heartbeat.setText(tr("service.heartbeat_stale", mins="∞"))
        elif mins <= 10:
            self._service_heartbeat.setText(tr("service.heartbeat_ok", mins=mins))
        else:
            self._service_heartbeat.setText(tr("service.heartbeat_stale", mins=mins))

    def _open_log_folder(self) -> None:
        from .config import config_dir
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_dir())))

    def _show_portal_wizard(self) -> None:
        PortalWizardDialog(self._config, self).exec()

    def _show_devices(self) -> None:
        dlg = DevicesDialog(self._config, self._last_status.get("ip") or "", self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg._kicked_ip:
            self._append_log(tr("devices.kicked", ip=dlg._kicked_ip))
            self._monitor.login_now()

    # ---------------------------------------------------------------- 更新

    def _on_update_available(self, version: str, url: str) -> None:
        self._update_version = version
        self._update_url = url
        self._update_banner.setText(tr("btn.update_now", version=version))
        self._update_banner.show()
        self._tray.showMessage(
            tr("tray.msg_update_title", version=version),
            tr("tray.msg_update_body", current=__version__),
            QSystemTrayIcon.MessageIcon.Information, 8000)

    def _do_update(self) -> None:
        if self._downloader is not None:
            return
        if not getattr(sys, "frozen", False):
            QDesktopServices.openUrl(QUrl(self._update_url or updates.RELEASE_PAGE))
            return
        self._update_banner.setText(tr("update.downloading", percent=0))
        self._downloader = UpdateDownloadThread(self)
        self._downloader.progress.connect(
            lambda p: self._update_banner.setText(tr("update.downloading", percent=p)))
        self._downloader.finished_ok.connect(self._update_downloaded)
        self._downloader.finished_err.connect(self._update_failed)
        self._downloader.start()

    def _update_failed(self, error: str) -> None:
        self._downloader = None
        self._update_banner.setText(tr("update.failed", msg=error or "?"))

    def _update_downloaded(self, path: str) -> None:
        self._downloader = None
        self._append_log(tr("update.downloaded"))
        self._tray.hide()
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - 启动官方安装包
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        QApplication.quit()

    # ---------------------------------------------------------------- 状态

    def _set_status_ui(self, state: str, detail: str) -> None:
        self._dot.setStyleSheet(f"background: {DOT_COLORS.get(state, '#94a3b8')}; border-radius: 7px;")
        self._status_text.setText(tr(f"status.{state}") if state in STATUS_KEYS else state)
        self._status_detail.setText(detail)

    def _on_status(self, info: dict) -> None:
        state = info.get("state", "")
        prev = self._last_status.get("state", "")
        self._last_status = dict(info)
        self._set_status_ui(state, info.get("detail") or "")
        self._fields["account"].setText(info.get("username") or "—")
        self._fields["ip"].setText(info.get("ip") or "—")
        self._fields["login_time"].setText(info.get("login_time") or "—")
        self._fields["last_check"].setText(time.strftime("%H:%M:%S"))
        billing = info.get("billing") or ""
        self._fields["billing"].setText(billing or "—")
        self._fields["traffic"].setText(
            _fmt_bytes(info.get("all_bytes") or 0) if info.get("all_bytes") else "—")
        self._btn_devices.setVisible(state == "auth_error" and info.get("ecode") == "E2620")

        icon_state = state if state in DOT_COLORS else "checking"
        if icon_state != self._tray_state:
            self._tray_state = icon_state
            self._tray.setIcon(make_tray_icon(icon_state))
        self._refresh_tray_tooltip()

        if state == "auth_error" and not self._warned_auth_error:
            self._warned_auth_error = True
            self._tray.showMessage(
                tr("tray.msg_auth_failed_title"),
                str(info.get("detail") or tr("tray.msg_auth_failed_body")),
                QSystemTrayIcon.MessageIcon.Critical, 6000)
        elif state == "online":
            self._warned_auth_error = False
            if prev in _NOTIFY_RELOGIN_FROM:
                self._tray.showMessage(
                    tr("tray.msg_relogin_title"),
                    tr("tray.msg_relogin_body", ip=info.get("ip") or ""),
                    QSystemTrayIcon.MessageIcon.Information, 5000)

    def _on_message_clicked(self) -> None:
        if self._update_url:
            self._do_update()

    def _append_log(self, line: str) -> None:
        self._log.appendPlainText(line)
        append_file_log(line)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_normal()

    def show_normal(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._force_quit = True
        self._save_geometry()
        self._monitor.stop()
        self._tray.hide()
        QApplication.quit()

    # ---------------------------------------------------------------- 关闭

    def _save_geometry(self) -> None:
        g = self.geometry()
        self._config.win_geometry = f"{g.x()},{g.y()},{g.width()},{g.height()}"
        self._config.save()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_geometry()
        if self._force_quit or not self._config.minimize_to_tray:
            self._monitor.stop()
            event.accept()
            return
        event.ignore()
        self.hide()
        if not getattr(self, "_hinted_tray", False):
            self._hinted_tray = True
            self._tray.showMessage(
                tr("tray.msg_background_title"),
                tr("tray.msg_background_body"),
                QSystemTrayIcon.MessageIcon.Information, 4000)
