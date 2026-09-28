"""PyQt6 界面：主窗口（状态 + 设置 + 日志）与系统托盘。"""

from __future__ import annotations

import os
import time

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QIcon, QPainter, QPixmap, QBrush, QColor, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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
    QSpinBox,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, autostart, i18n
from .config import Config, resource_path
from .i18n import tr
from .monitor import Monitor
from .theme import QSS

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
# 出现这些状态 → 状态突然恢复 online 时弹"已自动重登"通知
_NOTIFY_RELOGIN_FROM = {"offline", "auth_error", "login_fail", "authed_no_internet"}

REPO_URL = "https://github.com/Xinzhe99/zju-autologin"
LOG_FILE_MAX = 256 * 1024


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


def append_file_log(line: str) -> None:
    """滚动追加到本地日志文件（用于远程排查问题）。"""
    from .config import config_dir

    try:
        path = config_dir() / "app.log"
        if path.exists() and path.stat().st_size > LOG_FILE_MAX:
            content = path.read_text(encoding="utf-8", errors="replace")
            path.write_text(content[-64 * 1024:], encoding="utf-8")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


class MainWindow(QMainWindow):
    def __init__(self, config: Config, monitor: Monitor) -> None:
        super().__init__()
        self._config = config
        self._monitor = monitor
        self._force_quit = False
        self._warned_auth_error = False
        self._tray_state = ""
        self._last_status: dict = {"state": "checking", "detail": ""}
        self._update_url = ""

        self.setWindowTitle(tr("app.name"))
        icon_path = resource_path("zju.ico")
        self.setWindowIcon(QIcon(icon_path if os.path.isfile(icon_path)
                                 else resource_path("zju_seal_blue.png")))
        self.resize(780, 764)
        self.setMinimumSize(740, 700)
        self.setStyleSheet(QSS)

        self._build_ui()
        self._build_tray()
        self.retranslate_ui()
        self._load_settings_into_ui()

        monitor.statusChanged.connect(self._on_status)
        monitor.logLine.connect(self._append_log)
        monitor.updateAvailable.connect(self._on_update_available)

    # ------------------------------------------------------------------ UI

    def _card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        return frame

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
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
        slay.addWidget(self._status_detail)

        grid_host = QFrame()
        grid_lay = QGridLayout(grid_host)
        grid_lay.setContentsMargins(0, 6, 0, 0)
        grid_lay.setHorizontalSpacing(28)
        grid_lay.setVerticalSpacing(4)
        self._fields: dict[str, QLabel] = {}
        self._field_labels: dict[str, QLabel] = {}
        for col, key in enumerate(("account", "ip", "login_time", "last_check")):
            klabel = QLabel()
            klabel.setObjectName("fieldKey")
            vlabel = QLabel("—")
            vlabel.setObjectName("fieldValue")
            vlabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid_lay.addWidget(klabel, 0, col)
            grid_lay.addWidget(vlabel, 1, col)
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
        form.setVerticalSpacing(12)

        def add_row(row: int, key: str, widget: QWidget) -> None:
            label = QLabel()
            label.setObjectName("fieldKey")
            form.addWidget(label, row, 0)
            form.addWidget(widget, row, 1)
            self._form_labels[key] = label

        self._form_labels: dict[str, QLabel] = {}

        self._edit_user = QLineEdit()
        self._edit_user.setPlaceholderText(tr("ph.username"))
        add_row(0, "username", self._edit_user)

        self._edit_domain = QLineEdit()
        self._edit_domain.setPlaceholderText(tr("ph.domain"))
        add_row(1, "domain", self._edit_domain)

        pwd_host = QFrame()
        pwd_lay = QHBoxLayout(pwd_host)
        pwd_lay.setContentsMargins(0, 0, 0, 0)
        pwd_lay.setSpacing(2)
        self._edit_pwd = QLineEdit()
        self._edit_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_pwd.setPlaceholderText(tr("ph.password"))
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
        add_row(2, "password", pwd_host)

        self._spin_interval = QSpinBox()
        self._spin_interval.setRange(10, 600)
        self._spin_interval.setToolTip(tr("tip.interval"))
        self._spin_interval.setSuffix(f" {tr('unit.seconds', n='')}".rstrip())
        add_row(3, "interval", self._spin_interval)

        self._combo_lang = QComboBox()
        for lang in ("auto", "zh-CN", "en-US"):
            self._combo_lang.addItem(self._lang_label(lang), lang)
        add_row(4, "language", self._combo_lang)

        opts_host = QFrame()
        opts_lay = QHBoxLayout(opts_host)
        opts_lay.setContentsMargins(0, 0, 0, 0)
        opts_lay.setSpacing(18)
        self._chk_auto = QCheckBox()
        self._chk_tray = QCheckBox()
        self._chk_boot = QCheckBox()
        self._chk_updates = QCheckBox()
        for chk in (self._chk_auto, self._chk_tray, self._chk_boot, self._chk_updates):
            opts_lay.addWidget(chk)
        opts_lay.addStretch(1)
        form.addWidget(opts_host, 5, 0, 1, 2)
        glay.addLayout(form)

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
        self._log_title = QLabel()
        self._log_title.setObjectName("cardTitle")
        llay.addWidget(self._log_title)
        self._log = QPlainTextEdit()
        self._log.setObjectName("log")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(400)
        self._log.setFixedHeight(132)
        llay.addWidget(self._log)
        root.addWidget(log_card, 1)

        self._tip = QLabel()
        self._tip.setObjectName("statusDetail")
        root.addWidget(self._tip)

    @staticmethod
    def _lang_label(lang: str) -> str:
        if lang == "auto":
            return ("跟随系统 / Follow system"
                    if i18n.detect_system_lang() == "zh-CN" else "Follow system / 跟随系统")
        return i18n.LANG_LABELS.get(lang, lang)

    def retranslate_ui(self) -> None:
        """运行时切换语言后刷新全部文本。"""
        self.setWindowTitle(tr("app.name"))
        self._version_label.setText(tr("app.header_badge", version=__version__))
        self._btn_check.setText(tr("btn.check_now"))
        self._btn_login.setText(tr("btn.login_now"))
        self._btn_save.setText(tr("btn.save"))
        self._settings_title.setText(tr("card.settings"))
        self._log_title.setText(tr("card.log"))
        self._tip.setText(tr("tip.footer"))
        self._save_hint.setText("")

        for key, label in self._field_labels.items():
            label.setText(tr(f"field.{key}"))
        self._form_labels["username"].setText(tr("field.username"))
        self._form_labels["domain"].setText(tr("field.domain"))
        self._form_labels["password"].setText(tr("field.password"))
        self._form_labels["interval"].setText(tr("field.interval"))
        self._form_labels["language"].setText(tr("field.language"))

        self._edit_user.setPlaceholderText(tr("ph.username"))
        self._edit_domain.setPlaceholderText(tr("ph.domain"))
        self._edit_pwd.setPlaceholderText(tr("ph.password"))
        self._spin_interval.setSuffix(f" {tr('unit.seconds', n='')}".rstrip())

        self._chk_auto.setText(tr("chk.auto_login"))
        self._chk_tray.setText(tr("chk.minimize_tray"))
        self._chk_boot.setText(tr("chk.autostart"))
        self._chk_updates.setText(tr("chk.check_updates"))

        for i in range(self._combo_lang.count()):
            self._combo_lang.setItemText(i, self._lang_label(self._combo_lang.itemData(i)))

        for act, key in ((self._act_show, "tray.show"), (self._act_check, "tray.check"),
                         (self._act_login, "tray.login"), (self._act_about, "tray.about"),
                         (self._act_quit, "tray.quit")):
            act.setText(tr(key))
        self._tray_boot.setText(tr("tray.autostart"))

        # 恢复最近一次状态文本
        self._set_status_ui(self._last_status.get("state", "checking"),
                            self._last_status.get("detail", ""))
        self._refresh_tray_tooltip()

    # ---------------------------------------------------------- 语言/托盘

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(make_tray_icon("checking"), self)
        self._refresh_tray_tooltip()

        menu = QMenu(self)
        self._act_show = QAction(menu)
        self._act_check = QAction(menu)
        self._act_login = QAction(menu)
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
        idx = self._combo_lang.findData(lang)
        self._combo_lang.setCurrentIndex(max(0, idx))
        self._chk_boot.setChecked(autostart.is_enabled())
        self._tray_boot.setChecked(autostart.is_enabled())
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

        # 语言实时切换
        if i18n.current_lang() != cfg.language:
            i18n.set_lang(cfg.language)
        self.retranslate_ui()

        self._monitor.config_updated()
        self._save_hint.setText(tr("hint.save_ok"))
        QTimer.singleShot(2500, lambda: self._save_hint.setText(""))
        self._append_log(tr("log.settings_saved",
                            backend=tr(f"password.storage.{cfg.password_backend_key()}")))
        self._monitor.check_once()

    def _toggle_autostart_from_tray(self, on: bool) -> None:
        result = autostart.set_enabled(on)
        self._chk_boot.setChecked(result)
        self._tray_boot.setChecked(result)
        self._config.autostart = result
        self._config.save()
        self._append_log(tr("log.autostart_on") if result else tr("log.autostart_off"))

    def show_normal(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._force_quit = True
        self._monitor.stop()
        self._tray.hide()
        QApplication.quit()

    # ---------------------------------------------------------------- 状态

    def _set_status_ui(self, state: str, detail: str) -> None:
        self._dot.setStyleSheet(f"background: {DOT_COLORS.get(state, '#94a3b8')}; border-radius: 7px;")
        self._status_text.setText(tr(f"status.{state}", ) if state in STATUS_KEYS else state)
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

    def _on_update_available(self, version: str, url: str) -> None:
        self._update_url = url
        self._tray.showMessage(
            tr("tray.msg_update_title", version=version),
            tr("tray.msg_update_body", current=__version__),
            QSystemTrayIcon.MessageIcon.Information, 8000)

    def _on_message_clicked(self) -> None:
        if self._update_url:
            QDesktopServices.openUrl(QUrl(self._update_url))
            self._update_url = ""

    def _append_log(self, line: str) -> None:
        self._log.appendPlainText(line)
        append_file_log(line)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_normal()

    # ---------------------------------------------------------------- 关闭

    def closeEvent(self, event) -> None:  # noqa: N802
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
