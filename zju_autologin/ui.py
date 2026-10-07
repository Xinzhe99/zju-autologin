"""PyQt6 界面：紧凑主窗（状态）+ 独立的设置窗口与日志窗口 + 系统托盘。"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile
import time
from collections import deque

from PyQt6.QtCore import Qt, QThread, QTime, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QPainter, QPixmap, QBrush, QColor, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
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
    QSizePolicy,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, autostart, crash, i18n, runtime, service, theme, updates
from .config import (
    Config,
    append_file_log,
    read_events,
    read_usage,
    resource_path,
)
from .i18n import tr
from .monitor import Monitor
from .net import build_opener
from .portals import load_portals
from .srun import SrunClient

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
_NOTIFY_RELOGIN_FROM = {"offline", "auth_error", "login_fail"}

REPO_URL = "https://github.com/Xinzhe99/zju-autologin"


def _is_installed_win() -> bool:
    """Windows 安装版判定: Inno 安装目录 / Program Files / 目录不可写。"""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    # Inno 每用户安装目录带 unins*.exe(目录可写, 曾被误判为便携版)
    if glob.glob(os.path.join(os.path.dirname(sys.executable), "unins*.exe")):
        return True
    exe_dir = os.path.normcase(os.path.dirname(sys.executable))
    for env in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env)
        if root and exe_dir.startswith(os.path.normcase(root)):
            return True
    return not os.access(os.path.dirname(sys.executable), os.W_OK)


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

    def __init__(self, proxy_mode: str = "system", proxy_url: str = "",
                 installed: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._proxy_mode = proxy_mode
        self._proxy_url = proxy_url
        self._installed = installed
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        import json as _json
        import urllib.request

        path = ""
        try:
            req = urllib.request.Request(
                updates.REPO_API,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "ZJU-AutoLogin"},
            )
            api_opener = build_opener(self._proxy_mode, self._proxy_url)
            with api_opener.open(req, timeout=10) as resp:
                data = _json.load(resp)
            target = None
            if sys.platform == "win32":
                # 便携版下 zip 走原地替换; 安装版下 setup.exe 走 /SILENT 安装
                suffix = "-windows-setup.exe" if self._installed else "-windows-portable.zip"
            else:
                suffix = "-macos-portable.zip"
            for asset in data.get("assets") or []:
                name = str(asset.get("name", ""))
                if name.endswith(suffix):
                    target = asset
                    break
            if not target:
                self.finished_err.emit("asset not found")
                return
            url = str(target.get("browser_download_url") or "")
            name = str(target.get("name") or "update.bin")
            total = int(target.get("size") or 0)
            digest = str(target.get("digest") or "")  # GitHub API: "sha256:..."
            if not digest.startswith("sha256:"):
                # 校验信息缺失即拒绝安装(fail-closed), 不静默跳过校验
                self.finished_err.emit("missing sha256 digest")
                return
            self.progress.emit(0)
            req = urllib.request.Request(url, headers={"User-Agent": "ZJU-AutoLogin"})
            # 随机临时名: 降低包在 %TEMP% 停留期间被替换的 TOCTOU 面。
            # 保留原始资产名: _pkg_version 要靠它识别版本, 否则"下到一半又发了
            # 新版就丢弃旧包"的判断永远拿不到版本号, 会装成旧版
            fd, path = tempfile.mkstemp(prefix="zju_aul_pkg_",
                                        suffix="-" + os.path.basename(name))
            os.close(fd)
            got = 0
            opener = build_opener(self._proxy_mode, self._proxy_url)
            with opener.open(req, timeout=30) as resp, open(path, "wb") as fh:
                while True:
                    if self._stop:
                        fh.close()
                        try:
                            os.remove(path)  # 中断的半截包不留在 %TEMP%
                        except OSError:
                            pass
                        return
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if total:
                        self.progress.emit(int(got * 100 / total))
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
            if path:
                try:
                    os.remove(path)  # 失败/超时同样不留半截包
                except OSError:
                    pass
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
        self._status.setWordWrap(True)
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
        # 不在 UI 线程 wait 后台请求: 信号随对话框销毁自动断开
        super().closeEvent(event)

    # ------------------------------------------------------------------

    def reload(self) -> None:
        self._status.setText("…")
        self._btn_kick.setEnabled(False)
        self._reload_gen = getattr(self, "_reload_gen", 0) + 1  # 代计数: 丢弃过期响应
        cfg = self._config

        def work():
            client = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id)
            return client.list_online_devices(cfg.username, cfg.get_password(), cfg.domain)

        self._apply_gen = self._reload_gen
        self._load_thread = _FnThread(work, self)
        self._load_thread.done.connect(self._apply_devices)
        self._load_thread.finished.connect(self._load_thread.deleteLater)
        self._load_thread.start()

    def _apply_devices(self, devices) -> None:
        if getattr(self, "_reload_gen", 1) != getattr(self, "_apply_gen", 0):
            return  # 过期响应(期间又点过刷新), 丢弃防覆盖新结果
        if isinstance(devices, Exception):
            self._status.setText(tr("devices.load_fail"))
            self._table.setRowCount(0)
            return
        if not devices:
            self._status.setText(tr("devices.empty"))
            self._table.setRowCount(0)
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
            return client.kick_device(cfg.username, ip, domain=cfg.domain)

        self._kick_thread = _FnThread(work, self)
        self._kick_thread.done.connect(self._kick_done)
        self._kick_thread.finished.connect(self._kick_thread.deleteLater)
        self._kick_thread.start()

    def _kick_done(self, result) -> None:
        if isinstance(result, Exception):
            self._status.setText(tr("update.failed", msg=result))
            self._btn_kick.setEnabled(True)
            return
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

    def __init__(self, main: "MainWindow", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._main = main
        self.setWindowTitle(tr("stats.title"))
        self.setModal(True)
        self.resize(560, 500)
        lay = QVBoxLayout(self)
        events = read_events(300)

        # 掉线回放: 把事件流讲成人话(这项功能此前只在 README 里存在, 没有调用点)
        try:
            from .narrative import build_narrative
            story = build_narrative(12)
        except Exception:  # noqa: BLE001 - 叙事只是锦上添花, 不能拖垮统计窗
            story = ""
        if story:
            narrative_lbl = QLabel(story)
            narrative_lbl.setObjectName("statusDetail")
            narrative_lbl.setWordWrap(True)
            narrative_lbl.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(narrative_lbl)

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
        login_time = main._last_status.get("login_time") or ""
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
        # 已知高校预设(社区共建 portals.json)
        self._combo_preset = QComboBox()
        self._combo_preset.addItem(tr("portal.custom"), "")
        for p in load_portals():
            self._combo_preset.addItem(p.get("name", "?"), p.get("base_url", ""))
        self._combo_preset.currentIndexChanged.connect(self._on_preset)
        lay.addWidget(self._combo_preset)
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

    def _on_preset(self) -> None:
        url = self._combo_preset.currentData()
        if url:
            self._edit_url.setText(url)

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
        self._thread.finished.connect(self._thread.deleteLater)
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


class SettingsWindow(QDialog):
    """独立设置窗口：账号 / 选项 / 掉线通知 / 高级选项。"""

    def __init__(self, config: Config, monitor: Monitor, main: "MainWindow") -> None:
        super().__init__(main)
        self._config = config
        self._monitor = monitor
        self._main = main
        self._route_thread: _FnThread | None = None
        self._service_thread: _FnThread | None = None
        self.setWindowTitle(tr("card.settings"))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(760, 780)
        self.setMinimumSize(700, 560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        self.setStyleSheet(theme.get_qss(config.theme))

        card = QFrame()
        card.setObjectName("card")
        glay = QVBoxLayout(card)
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
        eye_icon_path = resource_path("icon_eye.png")
        if os.path.isfile(eye_icon_path):
            self._eye.setIcon(QIcon(eye_icon_path))
        else:
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

        # 主题：分段胶囊（点击即时生效）
        seg_host = QFrame()
        seg_host.setObjectName("segHost")
        seg_host.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        seg_lay = QHBoxLayout(seg_host)
        seg_lay.setContentsMargins(2, 2, 2, 2)
        seg_lay.setSpacing(2)
        self._seg_buttons: dict[str, QPushButton] = {}
        self._seg_group = QButtonGroup(self)
        self._seg_group.setExclusive(True)
        for mode in ("auto", "light", "dark"):
            btn = QPushButton()
            btn.setObjectName("seg")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, m=mode: self._apply_theme(m))
            self._seg_group.addButton(btn)
            self._seg_buttons[mode] = btn
            seg_lay.addWidget(btn)
        self._seg_buttons["auto"].setChecked(True)

        add_row(0, "username", self._edit_user)
        add_row(1, "domain", self._edit_domain)
        add_row(2, "password", pwd_host)
        add_row(3, "interval", self._spin_interval)
        add_row(4, "language", self._combo_lang)
        add_row(5, "theme", seg_host)
        glay.addLayout(form)

        self._chk_auto = QCheckBox()
        self._chk_tray = QCheckBox()
        self._chk_updates = QCheckBox()
        self._chk_boot = QCheckBox()
        self._chk_service = QCheckBox()
        self._chk_service.toggled.connect(self._on_service_toggled)
        self._service_busy = False
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
        if sys.platform in ("win32", "darwin") or sys.platform.startswith("linux"):
            self._hb_timer.start()

        self._notify_title = QLabel()
        self._notify_title.setObjectName("cardTitle")
        glay.addWidget(self._notify_title)
        self._notify_hint = QLabel()
        self._notify_hint.setObjectName("statusDetail")
        self._notify_hint.setWordWrap(True)
        glay.addWidget(self._notify_hint)
        notify_grid = QGridLayout()
        notify_grid.setHorizontalSpacing(10)
        notify_grid.setVerticalSpacing(8)
        self._combo_provider = QComboBox()
        for pid in ("none", "bark", "serverchan", "wecom", "dingtalk", "feishu", "webhook", "smtp"):
            self._combo_provider.addItem(self._provider_label(pid), pid)
        self._edit_key = QLineEdit()
        self._btn_notify_test = QPushButton()
        self._btn_notify_test.setObjectName("secondary")
        self._btn_notify_test.clicked.connect(self._monitor.notify_test)
        self._combo_provider.currentIndexChanged.connect(self._on_provider_changed)
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

        # SMTP 表单（仅邮件渠道显示）
        self._smtp_frame = QFrame()
        smtp_grid = QGridLayout(self._smtp_frame)
        smtp_grid.setContentsMargins(0, 0, 0, 0)
        smtp_grid.setHorizontalSpacing(10)
        smtp_grid.setVerticalSpacing(8)
        self._edit_smtp_host = QLineEdit()
        self._edit_smtp_host.setPlaceholderText("smtp.qq.com")
        self._spin_smtp_port = QSpinBox()
        self._spin_smtp_port.setRange(1, 65535)
        self._spin_smtp_port.setValue(465)
        self._edit_smtp_user = QLineEdit()
        self._edit_smtp_user.setPlaceholderText("you@qq.com")
        self._edit_smtp_pass = QLineEdit()
        self._edit_smtp_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_smtp_pass.setPlaceholderText(tr("smtp.pass_ph"))
        self._edit_smtp_to = QLineEdit()
        self._edit_smtp_to.setPlaceholderText("you@qq.com")
        self._smtp_labels: list[QLabel] = []
        smtp_rows = (
            ("smtp.host", self._edit_smtp_host),
            ("smtp.port", self._spin_smtp_port),
            ("smtp.user", self._edit_smtp_user),
            ("smtp.pass", self._edit_smtp_pass),
            ("smtp.to", self._edit_smtp_to),
        )
        for row, (key, widget) in enumerate(smtp_rows):
            label = QLabel()
            label.setObjectName("fieldKey")
            label.setFixedWidth(110)
            smtp_grid.addWidget(label, row, 0)
            smtp_grid.addWidget(widget, row, 1)
            self._smtp_labels.append(label)
        self._smtp_frame.setVisible(False)
        glay.addWidget(self._smtp_frame)

        # 渠道教程链接
        self._lbl_guide = QLabel()
        self._lbl_guide.setObjectName("statusDetail")
        self._lbl_guide.setOpenExternalLinks(True)
        self._lbl_guide.setText(
            f'<a href="{REPO_URL}/blob/main/docs/notifications.md" style="color:#5b8fd9;">{tr("notify.guide")}</a>')
        glay.addWidget(self._lbl_guide)

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
        self._combo_proxy = QComboBox()
        for pid in ("system", "direct", "custom"):
            self._combo_proxy.addItem(tr(f"net.proxy.{pid}"), pid)
        self._combo_proxy.currentIndexChanged.connect(self._on_proxy_mode_changed)
        self._chk_proactive = QCheckBox()
        self._time_proactive = QTimeEdit(QTime(3, 0))
        self._time_proactive.setDisplayFormat("HH:mm")
        self._chk_auto_kick = QCheckBox()
        self._adv_labels: list[QLabel] = []
        for row, (label_key, widget) in enumerate((
            ("field.base_url", self._edit_base),
            ("field.ac_id", self._edit_acid),
            ("hb.url", self._edit_heartbeat),
            ("net.proxy", self._combo_proxy),
        )):
            label = QLabel()
            label.setObjectName("fieldKey")
            adv_grid.addWidget(label, row, 0)
            adv_grid.addWidget(widget, row, 1)
            self._adv_labels.append(label)
        self._edit_proxy_url = QLineEdit()
        self._edit_proxy_url.setPlaceholderText("http://127.0.0.1:7890")
        self._edit_proxy_url.setEnabled(False)
        self._lbl_proxy_url = QLabel()
        self._lbl_proxy_url.setObjectName("fieldKey")
        adv_grid.addWidget(self._lbl_proxy_url, 4, 0)
        adv_grid.addWidget(self._edit_proxy_url, 4, 1)
        # DDNS 区块
        self._ddns_title = QLabel()
        self._ddns_title.setObjectName("cardTitle")
        glay.addWidget(self._ddns_title)
        ddns_grid = QGridLayout()
        ddns_grid.setHorizontalSpacing(10)
        ddns_grid.setVerticalSpacing(8)
        self._combo_ddns = QComboBox()
        for pid, name in (("off", tr("ddns.off")), ("duckdns", tr("ddns.duckdns")), ("cloudflare", tr("ddns.cloudflare")), ("aliyun", tr("ddns.aliyun"))):
            self._combo_ddns.addItem(name, pid)
        self._edit_ddns_domain = QLineEdit()
        self._edit_ddns_domain.setPlaceholderText(tr("ddns.domain_ph") + " / " + tr("ddns.duckdns_ph_domain"))
        self._edit_ddns_token = QLineEdit()
        self._edit_ddns_token.setPlaceholderText(tr("ddns.token_ph"))
        self._edit_ddns_secret = QLineEdit()
        self._edit_ddns_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_ddns_secret.setPlaceholderText(tr("ddns.secret_ph") + " / " + tr("ddns.duckdns_ph_secret"))
        self._ddns_labels = []
        for row, (key, w) in enumerate((("ddns.provider_lbl", self._combo_ddns), ("field.domain", self._edit_ddns_domain), ("ddns.token_ph", self._edit_ddns_token), ("ddns.secret_ph", self._edit_ddns_secret))):
            lbl = QLabel()
            lbl.setObjectName("fieldKey")
            ddns_grid.addWidget(lbl, row, 0)
            ddns_grid.addWidget(w, row, 1)
            self._ddns_labels.append((lbl, key))
        self._chk_monthly = QCheckBox()
        ddns_grid.addWidget(self._chk_monthly, 4, 0, 1, 2)
        glay.addLayout(ddns_grid)

        # 状态钩子
        self._hooks_title = QLabel()
        self._hooks_title.setObjectName("cardTitle")
        glay.addWidget(self._hooks_title)
        self._edit_hook_on = QLineEdit()
        self._edit_hook_on.setPlaceholderText(tr("hook.online_ph"))
        self._edit_hook_off = QLineEdit()
        self._edit_hook_off.setPlaceholderText(tr("hook.offline_ph"))
        hook_grid = QGridLayout()
        hook_grid.setVerticalSpacing(8)
        self._hook_labels = []
        for row, (w, key) in enumerate(((self._edit_hook_on, "hook.online_ph"), (self._edit_hook_off, "hook.offline_ph"))):
            lbl = QLabel()
            lbl.setObjectName("fieldKey")
            hook_grid.addWidget(lbl, row, 0)
            hook_grid.addWidget(w, row, 1)
            self._hook_labels.append((lbl, key))
        glay.addLayout(hook_grid)

        prow = QHBoxLayout()
        prow.addWidget(self._chk_proactive)
        prow.addWidget(self._time_proactive)
        prow.addSpacing(14)
        prow.addWidget(self._chk_auto_kick)
        prow.addStretch(1)
        self._btn_export = QPushButton()
        self._btn_export.setObjectName("secondary")
        self._btn_export.clicked.connect(self._export_config)
        self._btn_import = QPushButton()
        self._btn_import.setObjectName("secondary")
        self._btn_import.clicked.connect(self._import_config)
        self._btn_portal = QPushButton()
        self._btn_portal.setObjectName("secondary")
        self._btn_portal.clicked.connect(self._show_portal_wizard)
        self._btn_route = QPushButton()
        self._btn_route.setObjectName("secondary")
        self._btn_route.clicked.connect(self._toggle_portal_route)
        prow.addWidget(self._btn_export)
        prow.addWidget(self._btn_import)
        prow.addWidget(self._btn_portal)
        prow.addWidget(self._btn_route)
        adv_grid.addLayout(prow, 5, 0, 1, 2)
        self._advanced_host.setVisible(False)
        self._btn_advanced.toggled.connect(self._advanced_host.setVisible)
        glay.addWidget(self._advanced_host)

        save_row = QHBoxLayout()
        self._save_hint = QLabel("")
        self._save_hint.setObjectName("statusDetail")
        self._save_hint.setWordWrap(True)
        self._btn_save = QPushButton()
        self._btn_save.setObjectName("primary")
        self._btn_save.clicked.connect(self._save_settings)
        save_row.addStretch(1)
        save_row.addWidget(self._save_hint)
        save_row.addSpacing(10)
        save_row.addWidget(self._btn_save)
        glay.addLayout(save_row)
        root.addWidget(card)
        root.addStretch(1)

        self._load_settings_into_ui()
        self.retranslate_ui()

    # ---------------- 静态文案 ----------------

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
            "feishu": ("飞书机器人", "Feishu bot"),
            "webhook": ("通用 Webhook", "Generic webhook"),
            "smtp": ("邮件 (SMTP)", "Email (SMTP)"),
        }
        zh, en = names.get(pid, (pid, pid))
        return zh if i18n.current_lang().startswith("zh") else en

    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("card.settings"))
        self._settings_title.setText(tr("card.settings"))
        self._btn_save.setText(tr("btn.save"))
        self._save_hint.setText("")
        for key, label in self._form_labels.items():
            label.setText(tr(f"field.{key}"))
        self._form_labels["theme"].setText(tr("settings.theme"))
        self._edit_user.setPlaceholderText(tr("ph.username"))
        self._edit_domain.setPlaceholderText(tr("ph.domain"))
        # 已存密码时保留"已保存到 X"的提示: 以前这里无条件盖成通用占位符,
        # 让 _load_settings_into_ui/_save_settings 写的后端提示永远看不见
        if self._config.get_password():
            self._edit_pwd.setPlaceholderText(tr(
                "ph.password_saved",
                backend=tr(f"password.storage.{self._config.password_backend_key()}")))
        else:
            self._edit_pwd.setPlaceholderText(tr("ph.password"))
        self._edit_key.setPlaceholderText(tr("notify.key"))
        self._edit_base.setPlaceholderText("https://net.zju.edu.cn")
        self._edit_acid.setPlaceholderText("80 / auto")
        self._edit_heartbeat.setToolTip(tr("hb.hint"))
        self._spin_interval.setSuffix(" " + tr("unit.seconds", n="").strip())
        self._chk_auto.setText(tr("chk.auto_login"))
        self._chk_tray.setText(tr("chk.minimize_tray"))
        self._chk_updates.setText(tr("chk.check_updates"))
        self._chk_boot.setText(tr("chk.autostart"))
        self._chk_service.setText(tr("service.chk"))
        self._service_hint.setText(tr("service.hint"))
        self._notify_title.setText(tr("settings.notify"))
        self._notify_hint.setText(tr("notify.keyword_hint"))
        self._chk_recovery.setText(tr("notify.recovery"))
        self._lbl_threshold.setText(tr("notify.threshold"))
        self._lbl_traffic.setText(tr("settings.traffic_limit"))
        self._spin_traffic.setSuffix(" GB")
        self._btn_notify_test.setText(tr("btn.notify_test"))
        self._btn_advanced.setText(tr("settings.advanced"))
        self._chk_proactive.setText(tr("chk.proactive"))
        self._chk_auto_kick.setText(tr("chk.auto_kick"))
        for i in range(self._combo_lang.count()):
            self._combo_lang.setItemText(i, self._lang_label(self._combo_lang.itemData(i)))
        for data, btn in self._seg_buttons.items():
            btn.setText(tr(f"theme.{data}"))
        for i in range(self._combo_provider.count()):
            pid = self._combo_provider.itemData(i)
            self._combo_provider.setItemText(i, self._provider_label(pid))
        for label, key in zip(self._notify_labels, ("notify.provider", "notify.key")):
            label.setText(tr(key))
        for label, key in zip(self._adv_labels, ("field.base_url", "field.ac_id", "hb.url", "net.proxy")):
            label.setText(tr(key))
        self._lbl_proxy_url.setText(tr("net.proxy.url"))
        for i in range(self._combo_proxy.count()):
            pid = self._combo_proxy.itemData(i)
            self._combo_proxy.setItemText(i, tr(f"net.proxy.{pid}"))
        self._ddns_title.setText(tr("settings.ddns"))
        self._hooks_title.setText(tr("settings.hooks"))
        # DDNS 下拉与占位符也要跟着语言走(以前只在 __init__ 里设过一次,
        # 切语言后这一块保持旧语言, 与旁边已刷新的控件混在一起)
        for i in range(self._combo_ddns.count()):
            pid = self._combo_ddns.itemData(i)
            self._combo_ddns.setItemText(i, tr(f"ddns.{pid}"))
        self._edit_ddns_domain.setPlaceholderText(
            tr("ddns.domain_ph") + " / " + tr("ddns.duckdns_ph_domain"))
        self._edit_ddns_token.setPlaceholderText(tr("ddns.token_ph"))
        self._edit_ddns_secret.setPlaceholderText(
            tr("ddns.secret_ph") + " / " + tr("ddns.duckdns_ph_secret"))
        self._edit_hook_on.setPlaceholderText(tr("hook.online_ph"))
        self._edit_hook_off.setPlaceholderText(tr("hook.offline_ph"))
        for lbl, key in self._ddns_labels:
            lbl.setText(tr(key))
        for lbl, key in self._hook_labels:
            lbl.setText(tr(key))
        self._chk_monthly.setText(tr("chk.monthly"))
        self._btn_export.setText(tr("btn.export_cfg"))
        self._btn_import.setText(tr("btn.import_cfg"))
        self._btn_portal.setText(tr("btn.portal_wizard"))
        self._btn_route.setText(tr("route.remove" if self._config.portal_route_added else "route.add"))
        self._btn_route.setToolTip(tr("route.hint"))
        if sys.platform != "win32":
            # 直连路由为 Windows 专属; 系统级保活在 macOS 由 LaunchDaemon 提供
            self._btn_route.setVisible(False)
        self._lbl_guide.setText(
            f'<a href="{REPO_URL}/blob/main/docs/notifications.md" style="color:#5b8fd9;">{tr("notify.guide")}</a>')
        for label, key in zip(self._smtp_labels, ("smtp.host", "smtp.port", "smtp.user", "smtp.pass", "smtp.to")):
            label.setText(tr(key))
        self._edit_smtp_pass.setPlaceholderText(tr("smtp.pass_ph"))

    def _apply_theme(self, mode: str) -> None:
        qss = theme.get_qss(mode)
        self.setStyleSheet(qss)
        self._main.setStyleSheet(qss)
        if self._main._logs_window is not None:
            self._main._logs_window.setStyleSheet(qss)
        # 胶囊切换即时生效, 同步落盘避免未点保存时重启回跳
        if self._config.theme != mode:
            self._config.theme = mode
            self._config.save()

    def _on_proxy_mode_changed(self) -> None:
        custom = self._combo_proxy.currentData() == "custom"
        self._edit_proxy_url.setEnabled(custom)

    def _on_provider_changed(self) -> None:
        self._smtp_frame.setVisible(self._combo_provider.currentData() == "smtp")

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
        self._set_seg_theme(cfg.theme if cfg.theme in ("auto", "light", "dark") else "auto")
        self._chk_boot.setChecked(autostart.is_enabled())
        # setChecked 会触发已连接的 _on_service_toggled(误弹 UAC), 先屏蔽信号
        self._chk_service.blockSignals(True)
        self._chk_service.setChecked(service.is_installed())
        self._chk_service.blockSignals(False)
        self._combo_provider.setCurrentIndex(
            max(0, self._combo_provider.findData(cfg.notify_provider or "none")))
        self._edit_key.setText(cfg.notify_key or "")
        self._spin_threshold.setValue(cfg.notify_threshold)
        self._chk_recovery.setChecked(bool(cfg.notify_recovery))
        try:
            self._spin_traffic.setValue(int(float(cfg.traffic_limit_gb or 0)))
        except (TypeError, ValueError):
            # 手改/导入的配置可能是 ""/"unlimited": 以前直接 int() 抛异常会
            # 让整个设置页(乃至启动流程)崩掉
            self._spin_traffic.setValue(0)
        self._edit_base.setText(cfg.base_url or "")
        self._edit_acid.setText(str(cfg.ac_id or "80"))
        self._edit_heartbeat.setText(cfg.heartbeat_url or "")
        idx = self._combo_ddns.findData(cfg.ddns_provider if cfg.ddns_provider in ("off", "duckdns", "cloudflare", "aliyun") else "off")
        self._combo_ddns.setCurrentIndex(max(0, idx))
        self._edit_ddns_domain.setText(cfg.ddns_domain or "")
        self._edit_ddns_token.setText(cfg.ddns_token or "")
        self._edit_ddns_secret.setText(cfg.ddns_secret or "")
        self._chk_monthly.setChecked(bool(cfg.monthly_report))
        self._edit_hook_on.setText(cfg.data.get("hook_on_online") or "")
        self._edit_hook_off.setText(cfg.data.get("hook_on_offline") or "")
        self._edit_smtp_host.setText(cfg.smtp_host or "")
        self._spin_smtp_port.setValue(cfg.smtp_port)
        self._edit_smtp_user.setText(cfg.smtp_user or "")
        self._edit_smtp_pass.setText(cfg.smtp_pass or "")
        self._edit_smtp_to.setText(cfg.smtp_to or "")
        self._smtp_frame.setVisible((cfg.notify_provider or "none") == "smtp")
        pm = cfg.proxy_mode if cfg.proxy_mode in ("system", "direct", "custom") else "system"
        self._combo_proxy.setCurrentIndex(max(0, self._combo_proxy.findData(pm)))
        self._edit_proxy_url.setText(cfg.proxy_url or "")
        self._edit_proxy_url.setEnabled(pm == "custom")
        self._chk_proactive.setChecked(bool(cfg.proactive_relogin))
        self._chk_auto_kick.setChecked(bool(cfg.auto_kick))
        try:
            hh, mm = str(cfg.proactive_time or "03:00").split(":")
            self._time_proactive.setTime(QTime(int(hh) % 24, int(mm) % 60))
        except (ValueError, AttributeError):
            pass
        if cfg.get_password():
            self._edit_pwd.setPlaceholderText(
                tr("ph.password_saved", backend=tr(f"password.storage.{cfg.password_backend_key()}")))

    def _set_seg_theme(self, data: str) -> None:
        btn = self._seg_buttons.get(data if data in ("auto", "light", "dark") else "auto")
        if btn is not None:
            btn.setChecked(True)

    def _seg_theme_data(self) -> str:
        for data, btn in self._seg_buttons.items():
            if btn.isChecked():
                return data
        return "auto"

    # ---------------- 动作 ----------------

    def _save_settings(self) -> None:
        cfg = self._config
        pwd = self._edit_pwd.text()
        # 先校验再写内存配置: 避免校验失败时已赋值的字段不落盘却生效
        if not pwd and not cfg.get_password() and self._edit_user.text():
            self._save_hint.setText(tr("hint.need_password"))
            return
        cfg.username = self._edit_user.text()
        cfg.domain = self._edit_domain.text()
        cfg.interval = self._spin_interval.value()
        cfg.auto_login = self._chk_auto.isChecked()
        cfg.minimize_to_tray = self._chk_tray.isChecked()
        cfg.check_updates = self._chk_updates.isChecked()
        cfg.language = self._combo_lang.currentData() or "auto"
        cfg.theme = self._seg_theme_data()
        cfg.notify_provider = self._combo_provider.currentData() or "none"
        cfg.notify_key = self._edit_key.text().strip()
        cfg.smtp_host = self._edit_smtp_host.text().strip()
        cfg.smtp_port = self._spin_smtp_port.value()
        cfg.smtp_user = self._edit_smtp_user.text().strip()
        cfg.smtp_pass = self._edit_smtp_pass.text()
        cfg.smtp_to = self._edit_smtp_to.text().strip()
        cfg.notify_threshold = self._spin_threshold.value()
        cfg.notify_recovery = self._chk_recovery.isChecked()
        cfg.traffic_limit_gb = self._spin_traffic.value()
        cfg.base_url = self._edit_base.text().strip() or "https://net.zju.edu.cn"
        cfg.ac_id = self._edit_acid.text().strip() or "80"
        cfg.heartbeat_url = self._edit_heartbeat.text().strip()
        cfg.ddns_provider = self._combo_ddns.currentData() or "off"
        cfg.ddns_domain = self._edit_ddns_domain.text().strip()
        cfg.ddns_token = self._edit_ddns_token.text().strip()
        cfg.ddns_secret = self._edit_ddns_secret.text()
        cfg.monthly_report = self._chk_monthly.isChecked()
        cfg.data["hook_on_online"] = self._edit_hook_on.text().strip()
        cfg.data["hook_on_offline"] = self._edit_hook_off.text().strip()
        cfg.proxy_mode = self._combo_proxy.currentData() or "system"
        cfg.proxy_url = self._edit_proxy_url.text().strip()
        cfg.proactive_relogin = self._chk_proactive.isChecked()
        cfg.auto_kick = self._chk_auto_kick.isChecked()
        cfg.proactive_time = self._time_proactive.time().toString("HH:mm")

        pwd = self._edit_pwd.text()
        if pwd:
            cfg.set_password(pwd)
            self._edit_pwd.clear()
            self._eye.setChecked(False)  # 清空后别把下一个密码明文显示出来
            self._edit_pwd.setPlaceholderText(
                tr("ph.password_saved", backend=tr(f"password.storage.{cfg.password_backend_key()}")))

        boot_ok = autostart.set_enabled(self._chk_boot.isChecked())
        self._chk_boot.setChecked(boot_ok)
        cfg.autostart = boot_ok
        saved = cfg.save()
        self._main._load_settings_into_ui()  # 回填托盘 自动登录/开机自启 勾选

        # 系统级保活在勾选时已即时生效; 此处仅校正异常状态不一致
        actual = service.is_installed()
        if self._chk_service.isChecked() != actual:
            self._chk_service.blockSignals(True)
            self._chk_service.setChecked(actual)
            self._chk_service.blockSignals(False)

        # 语言/主题实时切换（含主窗与日志窗）
        if i18n.current_lang() != cfg.language:
            i18n.set_lang(cfg.language)
        self._apply_theme(cfg.theme)
        self.retranslate_ui()
        self._main.retranslate_ui()
        if self._main._logs_window is not None:
            self._main._logs_window.retranslate_ui()

        self._monitor.config_updated()
        # 落盘失败必须说清楚: 以前不管写没写成功都提示"已保存"
        self._save_hint.setText(tr("hint.save_ok") if saved else tr("hint.save_fail"))
        QTimer.singleShot(2500, lambda: self._save_hint.setText(""))
        self._main._append_log(tr("log.settings_saved",
                                  backend=tr(f"password.storage.{cfg.password_backend_key()}")))
        self._monitor.check_once()

    def _on_service_toggled(self, on: bool) -> None:
        if self._service_busy:
            return
        self._apply_service_toggle(on)

    def _apply_service_toggle(self, enable: bool) -> None:
        cfg = self._config
        self._service_busy = True
        self._chk_service.setEnabled(False)

        def work():
            from . import watchdog
            result = service.install(cfg) if enable else service.uninstall()
            if enable:
                watchdog.install()   # GUI 看护任务随系统级保活一起装
            else:
                watchdog.uninstall()
            return result

        def done(result):
            self._service_busy = False
            ok = not isinstance(result, Exception) and bool(result and result[0])
            self._chk_service.setEnabled(True)
            self._chk_service.blockSignals(True)
            self._chk_service.setChecked(ok if enable else not ok)
            self._chk_service.blockSignals(False)
            self._refresh_service_heartbeat()
            if enable:
                self._main._append_log(tr("service.on_ok") if ok else tr("service.on_fail"))
            else:
                self._main._append_log(tr("service.off_ok") if ok else tr("service.on_fail"))

        self._service_thread = _FnThread(work, self)
        self._service_thread.done.connect(done)
        self._service_thread.finished.connect(self._service_thread.deleteLater)
        self._service_thread.start()

    def _toggle_portal_route(self) -> None:
        cfg = self._config
        want_add = not cfg.portal_route_added
        self._btn_route.setEnabled(False)

        def work():
            import zju_autologin.routes as routes
            return routes.add_direct_routes(cfg) if want_add else routes.remove_direct_routes(cfg)

        def done(result):
            ok = not isinstance(result, Exception) and bool(result and result[0])
            self._btn_route.setEnabled(True)
            if ok:
                self._btn_route.setText(tr("route.remove" if want_add else "route.add"))
                self._main._append_log(tr("route.add_ok") if want_add else tr("route.remove_ok"))
            else:
                self._main._append_log(tr("route.add_fail") if want_add else tr("route.remove_fail"))

        self._route_thread = _FnThread(work, self)
        self._route_thread.done.connect(done)
        self._route_thread.finished.connect(self._route_thread.deleteLater)
        self._route_thread.start()

    def _show_portal_wizard(self) -> None:
        self._portal_dlg = PortalWizardDialog(self._config, self)
        self._portal_dlg.exec()

    def _export_config(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        from .config import _DEFAULTS

        path, _ = QFileDialog.getSaveFileName(
            self, tr("btn.export_cfg"), "zju-autologin-config.json", "JSON (*.json)")
        if not path:
            return
        payload = {"_exported_by": f"ZJU-AutoLogin v{__version__}"}
        for key in _DEFAULTS:
            # 位置 + 密钥类字段不导出: 导出文件是给排障用的, 会被贴到 issue 里。
            # ddns_token/ddns_secret 是 Cloudflare API Token / 阿里云 AccessKey Secret,
            # 早期漏在名单外, 等于把云 DNS 的写权限一起送出去。
            if key in ("win_geometry", "notify_key", "smtp_pass", "smtp_user", "smtp_to",
                       "heartbeat_url", "proxy_url", "ddns_token", "ddns_secret"):
                continue
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
        # 敏感字段(base_url/代理/通知/心跳)变更需用户确认: 恶意配置文件可把
        # 编码后的凭据重定向到任意主机
        sensitive = [k for k in ("base_url", "ac_id", "proxy_mode", "proxy_url",
                                 "notify_provider", "notify_key", "heartbeat_url",
                                 "smtp_host", "smtp_user", "smtp_to")
                     if payload.get(k) != self._config.data.get(k)]
        if sensitive:
            answer = QMessageBox.question(
                self, tr("btn.import_cfg"),
                tr("import.sensitive_confirm", keys=", ".join(sensitive)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self._save_hint.setText(tr("msg.cfg_import_cancel"))
                QTimer.singleShot(3500, lambda: self._save_hint.setText(""))
                return
        for key in _DEFAULTS:
            if key != "win_geometry" and key in payload:
                self._config.data[key] = payload[key]
        self._config.save()
        self._load_settings_into_ui()
        self._apply_theme(self._config.theme)
        if i18n.current_lang() != self._config.language:
            i18n.set_lang(self._config.language)
        self.retranslate_ui()
        # 托盘菜单的勾选状态在主窗里: 不重新载入会与导入的值不一致, 用户点一下
        # 就把刚导入的设置又改回去
        self._main._load_settings_into_ui()
        self._main.retranslate_ui()
        autostart.set_enabled(bool(self._config.autostart))
        self._monitor.config_updated()
        self._save_hint.setText(tr("msg.cfg_imported"))
        QTimer.singleShot(3500, lambda: self._save_hint.setText(""))
        self._monitor.check_once()

    def _refresh_service_heartbeat(self) -> None:
        """显示系统级保活服务的心跳状态（watch 进程每轮写入时间戳）。"""
        # 缓存 5 分钟: schtasks 子进程超时可达 15s, 每分钟查一次会周期性卡界面
        if not service.is_installed(max_age=300):
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
        elif mins <= max(10, (self._config.interval * 3) // 60):
            self._service_heartbeat.setText(tr("service.heartbeat_ok", mins=mins))
        else:
            self._service_heartbeat.setText(tr("service.heartbeat_stale", mins=mins))

    def closeEvent(self, event) -> None:  # noqa: N802
        # 只隐藏, 保留实例与累积状态; 退出程序由主窗 quit_app 统一收尾
        event.ignore()
        self.hide()


class LogsWindow(QDialog):
    """独立日志窗口：运行日志 + 统计 + 诊断。"""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__(main)
        self._main = main
        self.setWindowTitle(tr("card.log"))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(760, 520)
        self.setMinimumSize(600, 400)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        card = QFrame()
        card.setObjectName("card")
        llay = QVBoxLayout(card)
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
        self._btn_stats.clicked.connect(lambda: StatsDialog(self._main, self).exec())
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
        llay.addWidget(self._log, 1)
        root.addWidget(card, 1)

        # 预加载跨重启的历史日志(最近 80 行), 再叠加本次会话缓冲。
        # 本次会话的每一行都已经写进 app.log, 直接拼接会把最近几十行显示两遍,
        # 所以历史段只取"缓冲里还没有的"那部分。
        try:
            from .config import config_dir
            app_log = config_dir() / "app.log"
            if app_log.exists():
                history = app_log.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
                buffered = set(main._log_buffer)
                for line in history:
                    if line not in buffered:
                        self._log.appendPlainText(line)
        except OSError:
            pass
        for line in main._log_buffer:
            self._log.appendPlainText(line)
        self.retranslate_ui()

    def append(self, line: str) -> None:
        self._log.appendPlainText(line)

    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("card.log"))
        self._log_title.setText(tr("card.log"))
        self._btn_diag.setText(tr("btn.copy_diag"))
        self._btn_stats.setText(tr("btn.stats"))
        self._btn_openlog.setText(tr("btn.open_log"))

    def _open_log_folder(self) -> None:
        from .config import config_dir

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config_dir())))

    def _copy_diagnostics(self) -> None:
        cfg = self._main._config
        user = cfg.username or ""
        # 打码账号: 诊断文本常被直接贴给他人, 明文账号即半截凭据
        masked = f"{user[:2]}{'*' * 3}{user[-1:]}" if len(user) > 4 else ("***" if user else "—")
        lines = [
            f"ZJU-AutoLogin v{__version__}",
            f"Python {sys.version.split()[0]} @ {sys.platform}",
            f"portal: {cfg.base_url} ac_id={cfg.ac_id}",
            f"account: {masked}{cfg.domain}",
            f"state: {self._main._last_status.get('state')} ip={self._main._last_status.get('ip')}",
            f"notify: {cfg.notify_provider}",
            "", "---- last logs ----",
        ]
        tail = self._log.toPlainText().splitlines()[-50:]
        if len(user) > 4:  # 尾段日志含完整账号, 与头部打码保持一致
            tail = [ln.replace(user, masked) for ln in tail]
        lines += tail
        QApplication.clipboard().setText("\n".join(lines))
        self._main._append_log(tr("diag.copied"))

    def closeEvent(self, event) -> None:  # noqa: N802
        event.ignore()
        self.hide()


class MainWindow(QMainWindow):
    """紧凑主窗：只放状态卡与常用操作; 设置/日志各自独立窗口。"""

    _LOG_BUFFER = 200

    def __init__(self, config: Config, monitor: Monitor) -> None:
        super().__init__()
        self._config = config
        self._monitor = monitor
        self._force_quit = False
        self._session_end = False
        self._warned_auth_error = False
        self._tray_state = ""
        self._last_status: dict = {"state": "checking", "detail": ""}
        self._update_version = ""
        self._update_url = ""
        self._update_pkg: str = ""          # 预下载完成的新版本包路径
        self._notified_update_version = ""  # 本次运行已弹过托盘通知的版本(去重)
        self._tray_msg_kind = ""            # 最近一条托盘气泡类型: "update" 或其他
        self._downloader: UpdateDownloadThread | None = None
        self._settings_window: SettingsWindow | None = None
        self._logs_window: LogsWindow | None = None
        self._captcha_dlg = None
        self._banner_mode = ""              # available / downloading / ready
        self._watchdog_checked = False
        self._log_buffer: deque[str] = deque(maxlen=self._LOG_BUFFER)

        self.setWindowTitle(tr("app.name"))
        icon_path = resource_path("zju.ico")
        self.setWindowIcon(QIcon(icon_path if os.path.isfile(icon_path)
                                 else resource_path("zju_seal_blue.png")))
        self.resize(640, 372)
        self.setMinimumSize(600, 340)
        self.setStyleSheet(theme.get_qss(config.theme))
        self._restore_geometry()

        self._build_ui()
        self._build_tray()
        self.retranslate_ui()
        self._load_settings_into_ui()

        monitor.statusChanged.connect(self._on_status)
        monitor.logLine.connect(self._append_log)
        monitor.updateAvailable.connect(self._on_update_available)
        monitor.captchaRequired.connect(self._on_captcha_required)
        crash.UiHolder.window = self

        # 关机/注销: 系统发起会话结束时必须放行关闭, 否则托盘常驻会拖住关机
        app = QApplication.instance()
        if app is not None:
            app.commitDataRequest.connect(self._on_commit_data)

        # 预创建设置/日志窗口(隐藏): 首次点击瞬时显示, 无一次性构建等待
        self._settings_window = SettingsWindow(self._config, self._monitor, self)
        self._logs_window = LogsWindow(self)

        # 看护任务协作: 清上轮更新的暂停标记 → 立即心跳 → 存量老脚本趁机升级;
        # 之后每 5 分钟心跳一次(阈值 10 分钟, 双倍冗余)
        from . import watchdog
        watchdog.resume()
        watchdog.touch_alive()
        # schtasks/PowerShell 是同步子进程(超时合计可达 45s), 放在 __init__ 里会
        # 让窗口迟迟不出现(像卡死); 推迟到事件循环起来之后再做, 且一次运行只做一次
        QTimer.singleShot(0, self._ensure_watchdog_task)
        self._alive_timer = QTimer(self)
        self._alive_timer.timeout.connect(watchdog.touch_alive)
        self._alive_timer.start(5 * 60 * 1000)

    def _ensure_watchdog_task(self) -> None:
        """启动后补装/升级 GUI 看护任务(不阻塞界面构建)。"""
        if self._watchdog_checked:
            return
        self._watchdog_checked = True
        from . import watchdog
        try:
            if watchdog.refresh_if_installed():
                return
            if sys.platform == "win32" and service.is_installed():
                # v1.25.3 及更早: schtasks 注册命令被引号解析吃掉, 任务从未建成。
                # 保活开着却没看护任务的存量机器, 启动时补装一次。
                watchdog.install()
        except Exception as exc:  # noqa: BLE001 - 看护装不上不影响主功能
            self._append_log(f"watchdog: {exc}")

    # ------------------------------------------------------------------ UI

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        return frame

    def _restore_geometry(self) -> None:
        """只恢复窗口位置; 主窗尺寸恒定紧凑, 不沿用历史大窗宽高。"""
        geo = str(self._config.win_geometry or "")
        if not geo:
            return
        try:
            x, y, _w, _h = (int(v) for v in geo.split(","))
            # 校验所有屏幕: 副屏拔除后避免恢复到屏幕外
            if any(s.availableGeometry().contains(x + 100, y + 20)
                   for s in QApplication.screens()):
                self.move(max(0, x), max(0, y))
        except (ValueError, TypeError):
            pass

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # ---- 顶栏（小校徽 + 应用名 + 版本）----
        topbar = QHBoxLayout()
        seal = _load_pixmap("zju_seal_blue.png")
        seal_label = QLabel()
        if not seal.isNull():
            seal_label.setPixmap(seal.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        topbar.addWidget(seal_label)
        self._topbar_title = QLabel()
        self._topbar_title.setObjectName("sidebarTitle")
        topbar.addWidget(self._topbar_title)
        self._topbar_sub = QLabel()
        self._topbar_sub.setObjectName("sidebarSub")
        topbar.addWidget(self._topbar_sub)
        topbar.addStretch(1)
        self._version_label = QLabel()
        self._version_label.setObjectName("sidebarHint")
        topbar.addWidget(self._version_label)
        root.addLayout(topbar)

        # ---- 更新横幅 ----
        self._update_banner = QPushButton()
        self._update_banner.setObjectName("primary")
        self._update_banner.clicked.connect(self._do_update)
        self._update_banner.hide()
        root.addWidget(self._update_banner)

        # ---- 状态卡片 ----
        card = self._card()
        slay = QVBoxLayout(card)
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
        grid_lay.setHorizontalSpacing(24)
        grid_lay.setVerticalSpacing(4)
        self._fields: dict[str, QLabel] = {}
        self._field_labels: dict[str, QLabel] = {}
        keys = ("account", "ip", "login_time", "last_check")
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

        btn_row = QHBoxLayout()
        self._btn_settings = QPushButton()
        self._btn_settings.setObjectName("secondary")
        self._btn_settings.clicked.connect(self._open_settings)
        self._btn_logs = QPushButton()
        self._btn_logs.setObjectName("secondary")
        self._btn_logs.clicked.connect(self._open_logs)
        self._btn_reconfig = QPushButton()
        self._btn_reconfig.setObjectName("secondary")
        self._btn_reconfig.clicked.connect(self._start_reconfig)
        self._btn_openportal = QPushButton()
        self._btn_openportal.setObjectName("secondary")
        self._btn_openportal.clicked.connect(self._open_portal_page)
        self._btn_diag = QPushButton()
        self._btn_diag.setObjectName("secondary")
        self._btn_diag.clicked.connect(self._run_diagnosis)
        btn_row.addWidget(self._btn_settings)
        btn_row.addWidget(self._btn_logs)
        btn_row.addWidget(self._btn_reconfig)
        btn_row.addStretch(1)
        btn_row.addWidget(self._btn_diag)
        btn_row.addWidget(self._btn_openportal)
        slay.addLayout(btn_row)
        root.addWidget(card)

        self._tip = QLabel()
        self._tip.setObjectName("statusDetail")
        root.addWidget(self._tip)

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(make_tray_icon("checking"), self)
        self._refresh_tray_tooltip()

        menu = QMenu(self)
        self._act_show = QAction(menu)
        self._act_check = QAction(menu)
        self._act_login = QAction(menu)
        self._act_openportal = QAction(menu)
        self._act_openportal.triggered.connect(self._open_portal_page)
        self._act_settings = QAction(menu)
        self._act_settings.triggered.connect(self._open_settings)
        self._act_logs = QAction(menu)
        self._act_logs.triggered.connect(self._open_logs)
        self._act_reconfig = QAction(menu)
        self._act_reconfig.triggered.connect(self._start_reconfig)
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
        for act in (self._act_show, self._act_check, self._act_login, self._act_openportal,
                    self._act_settings, self._act_logs, self._act_reconfig):
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
        state = self._last_status.get("state", "checking")
        status = tr(f"status.{state}") if state in STATUS_KEYS else state
        ip = self._last_status.get("ip") or ""
        traffic = self._last_status.get("all_bytes") or 0
        if traffic:
            status += f" · {_fmt_bytes(traffic)}"
        self._tray.setToolTip(
            tr("tray.tooltip_ip", app=tr("app.name"), status=status, ip=ip)
            if ip else tr("tray.tooltip", app=tr("app.name"), status=status))

    def _load_settings_into_ui(self) -> None:
        cfg = self._config
        # setChecked 会触发 toggled 槽(误写配置/注册表), 先屏蔽信号
        for act, checked in ((self._tray_boot, autostart.is_enabled()),
                             (self._act_auto, bool(cfg.auto_login))):
            act.blockSignals(True)
            act.setChecked(checked)
            act.blockSignals(False)

    # ---------------------------------------------------------------- 动作

    def _open_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self._config, self._monitor, self)
        self._settings_window._refresh_service_heartbeat()  # 立即刷新, 不等首个 60s 定时
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _open_logs(self) -> None:
        if self._logs_window is None:
            self._logs_window = LogsWindow(self)
        self._logs_window.show()
        self._logs_window.raise_()
        self._logs_window.activateWindow()

    def _open_portal_page(self) -> None:
        """在浏览器打开校园网认证登录页。"""
        QDesktopServices.openUrl(QUrl(self._config.base_url))

    def _on_captcha_required(self) -> None:
        """门户要求验证码: 弹窗输入(同时推系统通知提醒远程用户)。

        已有一个待输入弹窗时直接忽略: worker 每轮检测都会重发该信号,
        不管不顾会叠出一摞模态框, 还会把主窗反复顶到前台。
        """
        from .captcha import CaptchaDialog
        if self._captcha_dlg is not None and self._captcha_dlg.isVisible():
            return
        self.show_normal()
        dlg = CaptchaDialog(self._config, self)
        dlg.submitted.connect(self._submit_captcha)
        self._captcha_dlg = dlg
        try:
            dlg.exec()
        finally:
            self._captcha_dlg = None

    def _submit_captcha(self, code: str, cookie: str) -> None:
        self._monitor.login_with_captcha(code, cookie)

    def _run_diagnosis(self) -> None:
        """一键网络自诊断: 后台执行, 结果弹窗并可复制。"""
        cfg = self._config
        self._btn_diag.setEnabled(False)

        def work():
            from .diag import format_report
            return format_report(cfg)

        def done(report):
            self._btn_diag.setEnabled(True)
            if isinstance(report, Exception):
                QMessageBox.warning(self, tr("diag.title"), str(report))
                return
            box = QMessageBox(self)
            box.setWindowTitle(tr("diag.title"))
            box.setText(report)
            box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            copy_btn = box.addButton(tr("btn.copy_diag"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("btn.close"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            # 自定义按钮 exec() 返回 2/3, 关闭(含 Esc)返回 0 —— 用 == 0 判断会把
            # "取消"当成"复制", 而真正的复制按钮永远不生效
            if box.clickedButton() is copy_btn:
                QApplication.clipboard().setText(report)

        self._diag_thread = _FnThread(work, self)
        self._diag_thread.done.connect(done)
        self._diag_thread.finished.connect(self._diag_thread.deleteLater)
        self._diag_thread.start()

    def _start_reconfig(self) -> None:
        """一键重新配置：清除已存凭据并重启进入引导向导。"""
        answer = QMessageBox.question(
            self, tr("reconfig.title"), tr("reconfig.confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        # 真正删除凭据管理器的条目, 而不是用空密码顶掉(会留下一条空记录,
        # 且后端拒绝空值时旧密码其实还在, 界面却提示已清除)
        self._config.forget_password()
        self._config.save()
        self._append_log(tr("reconfig.cleared"))
        self._force_quit = True
        self._save_geometry()
        if self._downloader is not None:
            self._downloader.stop()
            self._downloader.wait(200)
        self._monitor.stop()
        self._tray.hide()
        # 重启自身：凭据已空, 启动即进入引导向导（重新配置场景不静默启动）
        if getattr(sys, "frozen", False):
            subprocess.Popen([sys.executable])
        else:
            main_py = Path(__file__).parent.parent / "main.py"
            subprocess.Popen([sys.executable, str(main_py)])
        QApplication.quit()

    def _show_devices(self) -> None:
        # 持有引用: 防局部变量 GC 后其后台线程仍在飞行
        self._devices_dlg = DevicesDialog(self._config, self._last_status.get("ip") or "", self)
        dlg = self._devices_dlg
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg._kicked_ip:
            self._append_log(tr("devices.kicked", ip=dlg._kicked_ip))
            self._monitor.login_now()

    def _on_login_clicked(self) -> None:
        if not self._config.username or not self._config.get_password():
            self._open_settings()
            self._status_detail.setText(tr("detail.fill_creds"))
            return
        self._set_status_ui("checking", tr("detail.logging_in"))
        self._monitor.login_now()

    def _toggle_auto_login(self, on: bool) -> None:
        self._config.auto_login = on
        self._config.save()
        if self._settings_window is not None:
            self._settings_window._chk_auto.setChecked(on)  # 与设置窗复选框保持同步
        self._append_log(tr("log.auto_login_on") if on else tr("log.auto_login_off"))

    def _toggle_autostart_from_tray(self, on: bool) -> None:
        result = autostart.set_enabled(on)
        if self._settings_window is not None:
            self._settings_window._chk_boot.setChecked(result)  # 与设置窗复选框保持同步
        self._append_log(tr("log.autostart_on") if result else tr("log.autostart_off"))

    # ---------------------------------------------------------------- 更新

    def _on_update_available(self, version: str, url: str) -> None:
        if version != self._update_version and self._update_pkg:
            # 检测到比预下载包更新的版本: 丢弃旧包, 避免装到旧版
            try:
                os.remove(self._update_pkg)
            except OSError:
                pass
            self._update_pkg = ""
        self._update_version = version
        self._update_url = url
        self._set_banner("available")
        if version != self._notified_update_version:
            self._notified_update_version = version
            self._tray_msg_kind = "update"
            self._tray.showMessage(
                tr("tray.msg_update_title", version=version),
                tr("tray.msg_update_body", current=__version__),
                QSystemTrayIcon.MessageIcon.Information, 8000)
        self._predownload_update()

    def _predownload_update(self) -> None:
        """发现新版本即后台预下载：用户点「更新」时直接替换重启，零等待。

        预下载静默进行，失败只记日志，不影响任何功能。
        """
        if self._downloader is not None or self._update_pkg:
            return
        if not getattr(sys, "frozen", False):
            return  # 源码模式无自更新
        self._downloader = UpdateDownloadThread(
            self._config.proxy_mode, self._config.proxy_url,
            installed=_is_installed_win(), parent=self)
        self._downloader.finished_ok.connect(self._predownload_done)
        self._downloader.finished_err.connect(self._predownload_fail)
        self._downloader.start()

    def _set_banner(self, mode: str, percent: int = 0) -> None:
        """按状态渲染更新横幅: available / downloading / ready / failed。

        以前每次 retranslate_ui 都无条件写回"更新到 vX", 预下载完成后的
        "立即重启更新"和下载中的百分比都会被一次语言/主题切换抹掉。
        """
        self._banner_mode = mode
        if mode == "available":
            self._update_banner.setText(tr("btn.update_now", version=self._update_version))
        elif mode == "downloading":
            self._update_banner.setText(tr("update.downloading", percent=percent))
        elif mode == "ready":
            self._update_banner.setText(tr("btn.update_ready", version=self._update_version))
        self._update_banner.show()

    def _render_banner(self) -> None:
        """重新翻译后按当前状态重画横幅。"""
        if not self._update_banner.isVisible():
            return
        mode = self._banner_mode or "available"
        self._set_banner("available" if mode == "failed" else mode)

    def _predownload_fail(self, error: str) -> None:
        # 复位引用, 否则非 None 守卫永远 return, 更新功能静默永久失效
        self._downloader = None
        self._append_log(tr("update.predl_fail", msg=error))
        if self._banner_mode == "downloading":
            # 用户已经点了更新(横幅切到百分比)却等来一个静默失败:
            # 必须把错误显示出来, 否则横幅永远停在某个百分比
            self._update_banner.setText(tr("update.failed", msg=error or "?"))
            self._banner_mode = "failed"

    def _predownload_done(self, path: str) -> None:
        self._downloader = None
        self._update_pkg = path
        self._pkg_verified = True  # 下载线程已做 SHA256 校验
        # 预下载完成：横幅提示即点即更
        if self._update_banner.isVisible():
            self._set_banner("ready")
        self._append_log(tr("update.predl_done"))

    def _do_update(self) -> None:
        # 预下载已就绪 → 直接替换重启（零等待）
        if self._update_pkg:
            self._update_downloaded(self._update_pkg)
            return
        if self._downloader is not None:
            # 预下载进行中: 横幅接入进度反馈(只接一次, 防重复点击累积连接)
            if not getattr(self._downloader, "_ui_attached", False):
                self._downloader._ui_attached = True
                self._set_banner("downloading", 0)
                self._downloader.progress.connect(
                    lambda p: self._set_banner("downloading", p))
            return
        if not getattr(sys, "frozen", False):
            QDesktopServices.openUrl(QUrl(self._update_url or updates.RELEASE_PAGE))
            return
        # 预下载未完成（或失败）→ 现场下载, 横幅显示进度
        self._set_banner("downloading", 0)
        self._downloader = UpdateDownloadThread(
            self._config.proxy_mode, self._config.proxy_url,
            installed=_is_installed_win(), parent=self)
        self._downloader.progress.connect(
            lambda p: self._set_banner("downloading", p))
        self._downloader.finished_ok.connect(self._update_downloaded)
        self._downloader.finished_err.connect(self._update_failed)
        self._downloader.start()

    def _update_failed(self, error: str) -> None:
        self._downloader = None
        self._update_pkg = ""
        self._update_banner.setText(tr("update.failed", msg=error or "?"))
        self._banner_mode = "failed"
        self._tray.show()  # 下载失败也要恢复托盘, 否则用户失去唯一操作入口

    def _update_downloaded(self, path: str) -> None:
        self._downloader = None
        # 下载期间可能又发了新版: 丢弃旧包按最新重下, 否则「更新」反而降级
        pkg_ver = self._pkg_version(path)
        if pkg_ver and updates._version_tuple(pkg_ver) < updates._version_tuple(
                self._update_version):
            try:
                os.remove(path)
            except OSError:
                pass
            self._update_pkg = ""
            self._predownload_update()
            return
        self._append_log(tr("update.downloaded"))
        self._tray.hide()
        # 更新期间 GUI 会退出、exe 被覆写: 暂停看护任务, 防止其在安装中途拉起
        # 写了一半的 exe(表现为 Failed to load Python DLL); 新版启动时会自动恢复
        from . import watchdog
        watchdog.pause_for_update()
        # 原地自更新（Codex 式体验, 无需安装器）:
        #   Windows 便携版: 解压 zip 出 exe → 重命名运行中的 exe → 新版归位 → 重启
        #   macOS .app 包: 解压 zip 得新 .app → 移动覆盖旧 .app → 重启
        # Windows 安装版(setup.exe)不做原地替换, 直接走下方 /SILENT 安装
        if getattr(sys, "frozen", False) and (
                sys.platform == "darwin" or path.lower().endswith(".zip")):
            try:
                if sys.platform == "darwin":
                    self._inplace_swap_mac(path)
                else:
                    self._inplace_swap(self._extract_win_exe(path))
                return
            except Exception as exc:  # noqa: BLE001 - 坏包/目录不可写等
                # 清理残留坏包并恢复界面, 允许用户重试
                self._update_pkg = ""
                try:
                    os.remove(path)
                except OSError:
                    pass
                self._tray.show()
                self._update_banner.setText(tr("update.failed", msg=exc))
                self._append_log(tr("update.failed", msg=exc))
                return
        try:
            if sys.platform == "win32":
                # 不带重启已关程序的安装器参数: 它只对被安装器强关的进程生效, 而本
                # 应用是自退出的; 静默装完的拉起由 installer.iss 的 skipifnotsilent 项负责
                subprocess.Popen([path, "/SILENT", "/CLOSEAPPLICATIONS"])
            elif not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                raise OSError(tr("update.open_fail"))
        except Exception as exc:  # noqa: BLE001 - 安装器被杀软拦截/文件被占用等
            # 托盘已隐藏, 这里是 hide 之后唯一不退出进程的出口: 必须恢复入口
            self._update_pkg = ""
            self._tray.show()
            self._update_banner.setText(tr("update.failed", msg=exc))
            self._append_log(tr("update.launch_fail",
                                url=self._update_url or updates.RELEASE_PAGE))
            return
        QApplication.quit()

    @staticmethod
    def _pkg_version(path: str) -> str:
        """从包名 ZJUAutoLogin-1.16.0-windows-portable.zip 取版本号, 取不到返回空。"""
        import re

        m = re.search(r"(\d+(?:\.\d+)+)", os.path.basename(path or ""))
        return m.group(1) if m else ""

    @staticmethod
    def _extract_win_exe(zip_path: str) -> str:
        """从便携 zip 解出 ZJUAutoLogin.exe 到临时目录, 返回 exe 路径。"""
        import zipfile

        staging = tempfile.mkdtemp(prefix="zju_aul_upd_")
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if os.path.basename(name) == "ZJUAutoLogin.exe":
                    zf.extract(name, staging)
                    return os.path.join(staging, name)
        raise OSError("no ZJUAutoLogin.exe in update archive")

    def _inplace_swap_mac(self, zip_path: str) -> None:
        """macOS 原地替换 .app：解压 → 用新 .app 覆盖旧 .app → 重启。

        POSIX 语义下移动覆盖正在运行的 .app 是安全的: 已运行进程持有
        旧可执行文件的 inode, 替换目录不影响其继续执行。
        """
        import shutil
        import tempfile
        import zipfile

        staging = tempfile.mkdtemp(prefix="zju_aul_upd_")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(staging)
            # Python zipfile 不恢复权限位: 主二进制无 +x 则更新后无法启动
            for info in zf.infolist():
                if info.external_attr and (info.external_attr >> 16) & 0o111:
                    target = os.path.join(staging, info.filename)
                    try:
                        os.chmod(target, 0o755)
                    except OSError:
                        pass
        # zip 内为 ZJUAutoLogin.app/（便携 zip 由 CI 的 zip -r 打包）
        new_app = None
        for entry in os.listdir(staging):
            if entry.endswith(".app"):
                new_app = os.path.join(staging, entry)
                break
        if not new_app:
            raise OSError("no .app in update archive")
        # 主二进制强制可执行(部分打包流程不带权限位)
        macos_bin = os.path.join(new_app, "Contents", "MacOS")
        if os.path.isdir(macos_bin):
            for fn in os.listdir(macos_bin):
                try:
                    os.chmod(os.path.join(macos_bin, fn), 0o755)
                except OSError:
                    pass

        # 定位当前 .app：运行中的二进制位于 <App>.app/Contents/MacOS/
        cur_app = Path(sys.executable)
        for _ in range(4):
            cur_app = cur_app.parent
            if cur_app.suffix == ".app":
                break
        else:
            raise OSError("not running from a .app bundle")

        backup = cur_app.with_suffix(".app.old")
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        os.rename(cur_app, backup)
        shutil.move(new_app, str(cur_app))
        try:
            shutil.rmtree(backup, ignore_errors=True)
            shutil.rmtree(staging, ignore_errors=True)
            os.remove(zip_path)
        except OSError:
            pass
        if runtime.app_lock is not None:
            runtime.app_lock.unlock()
        self._append_log(tr("update.swapped"))
        subprocess.Popen(["open", "-n", str(cur_app)])
        QApplication.quit()

    def _inplace_swap(self, new_path: str) -> None:
        cur = Path(sys.executable)
        old = cur.with_suffix(".old.exe")
        if old.exists():
            old.unlink()
        os.rename(cur, old)  # Windows 允许重命名正在运行的 exe
        try:
            shutil.move(new_path, str(cur))
        except Exception:
            # 新 exe 没就位就必须把旧的搬回去: 以前异常只被上层改成"更新失败"
            # 提示, 磁盘上却已经没有可执行文件了(下次开机什么都起不来)
            try:
                if not cur.exists():
                    os.rename(old, cur)
            except OSError:
                pass
            raise
        # 释放单实例锁后重启新版本
        if runtime.app_lock is not None:
            runtime.app_lock.unlock()
        self._append_log(tr("update.swapped"))
        # 解压用的临时目录也一并清掉(以前只清 macOS 那一支)
        staging = Path(new_path).parent
        if staging.name.startswith("zju_aul_upd_"):
            shutil.rmtree(staging, ignore_errors=True)
        # 保持更新前的窗口状态: 原本开着窗就别重启进托盘
        cmd = [str(cur)] if self.isVisible() else [str(cur), "--minimized"]
        subprocess.Popen(cmd,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._cleanup_update_files()
        QApplication.quit()

    def _cleanup_update_files(self) -> None:
        """清理下载包与解压残留(Windows 侧以前会一直留在 %TEMP%)。"""
        pkg = self._update_pkg
        self._update_pkg = ""
        for path in (pkg,):
            if not path:
                continue
            try:
                os.remove(path)
            except OSError:
                pass

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
        self._btn_devices.setVisible(state == "auth_error" and info.get("ecode") == "E2620")

        icon_state = state if state in DOT_COLORS else "checking"
        if icon_state != self._tray_state:
            self._tray_state = icon_state
            self._tray.setIcon(make_tray_icon(icon_state))
        self._refresh_tray_tooltip()

        if state == "auth_error" and not self._warned_auth_error:
            self._warned_auth_error = True
            self._tray_msg_kind = "auth_error"
            self._tray.showMessage(
                tr("tray.msg_auth_failed_title"),
                str(info.get("detail") or tr("tray.msg_auth_failed_body")),
                QSystemTrayIcon.MessageIcon.Critical, 6000)
        elif state == "online":
            self._warned_auth_error = False
            if prev in _NOTIFY_RELOGIN_FROM:
                self._tray_msg_kind = "relogin"
                self._tray.showMessage(
                    tr("tray.msg_relogin_title"),
                    tr("tray.msg_relogin_body", ip=info.get("ip") or ""),
                    QSystemTrayIcon.MessageIcon.Information, 5000)

    def _on_message_clicked(self) -> None:
        # 仅更新类气泡点击触发更新; 其他气泡点击只唤起主窗
        if self._tray_msg_kind == "update" and self._update_url:
            self._do_update()
        else:
            self.show_normal()

    def _append_log(self, line: str) -> None:
        self._log_buffer.append(line)
        append_file_log(line)
        if self._logs_window is not None:
            self._logs_window.append(line)

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
        self._shutdown_background()
        self._tray.hide()
        QApplication.quit()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("app.name"))
        self._topbar_title.setText(tr("app.name"))
        self._topbar_sub.setText(tr("app.tagline"))
        self._version_label.setText(tr("app.header_badge", version=__version__))
        self._btn_check.setText(tr("btn.check_now"))
        self._btn_login.setText(tr("btn.login_now"))
        self._btn_openportal.setText(tr("btn.open_portal"))
        self._btn_diag.setText(tr("btn.diagnose"))
        self._btn_reconfig.setText(tr("btn.reconfig"))
        self._btn_settings.setText(tr("btn.settings"))
        self._btn_logs.setText(tr("btn.logs"))
        self._btn_devices.setText(tr("btn.devices"))
        self._tip.setText(tr("tip.footer"))

        for key, label in self._field_labels.items():
            label.setText(tr(f"field.{key}"))

        for act, key in ((self._act_show, "tray.show"), (self._act_check, "tray.check"),
                         (self._act_login, "tray.login"), (self._act_openportal, "btn.open_portal"),
                         (self._act_settings, "btn.settings"), (self._act_logs, "btn.logs"),
                         (self._act_reconfig, "btn.reconfig"),
                         (self._act_about, "tray.about"), (self._act_quit, "tray.quit")):
            act.setText(tr(key))
        self._act_auto.setText(tr("chk.auto_login"))
        self._tray_boot.setText(tr("tray.autostart"))

        if self._update_banner.isVisible():
            self._render_banner()

        self._set_status_ui(self._last_status.get("state", "checking"),
                            self._last_status.get("detail", ""))
        self._refresh_tray_tooltip()
        if self._settings_window is not None:
            self._settings_window.retranslate_ui()
            self._settings_window._refresh_service_heartbeat()
        if self._logs_window is not None:
            self._logs_window.retranslate_ui()

    # ---------------------------------------------------------------- 关闭

    def _save_geometry(self) -> None:
        g = self.geometry()
        self._config.win_geometry = f"{g.x()},{g.y()},{g.width()},{g.height()}"
        self._config.save()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_geometry()
        # 关机/注销时必须放行: 隐藏到托盘会拖住系统会话结束
        if self._session_end or self._force_quit or not self._config.minimize_to_tray:
            # 关窗即退出: 只 accept() 而不 quit() 会留下一个僵尸托盘进程 ——
            # 事件循环还在, 但 monitor 线程已被 stop(), 保活静默失效, 界面
            # 重新打开也是死的(按钮全无反应)。托盘图标必须一并收掉。
            self._tray.hide()
            self._shutdown_background()
            event.accept()
            QApplication.quit()
            return
        event.ignore()
        self.hide()
        if not getattr(self, "_hinted_tray", False):
            self._hinted_tray = True
            self._tray.showMessage(
                tr("tray.msg_background_title"),
                tr("tray.msg_background_body"),
                QSystemTrayIcon.MessageIcon.Information, 4000)

    def _shutdown_background(self) -> None:
        if self._downloader is not None:
            self._downloader.stop()
            self._downloader.wait(200)
        self._monitor.stop()

    def _on_commit_data(self, *_args) -> None:
        self._session_end = True
        self._shutdown_background()
        QApplication.quit()
