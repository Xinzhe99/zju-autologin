"""PyQt6 界面：主窗口（状态 + 设置 + 日志）与系统托盘。"""

from __future__ import annotations

import os
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QIcon, QPainter, QPixmap, QBrush, QColor, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
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

from . import autostart
from .config import Config, resource_path
from .monitor import Monitor
from .theme import QSS

# 状态 → (展示文本, 圆点颜色, 托盘点颜色)
STATE_META = {
    "online": ("网络正常", "#22c55e"),
    "authed_no_internet": ("外网不可用", "#f59e0b"),
    "offline": ("未认证", "#ef4444"),
    "need_config": ("待配置", "#94a3b8"),
    "auth_error": ("认证失败", "#ef4444"),
    "login_fail": ("登录失败", "#f59e0b"),
    "no_campus": ("无校园网连接", "#94a3b8"),
    "checking": ("检测中…", "#3b82f6"),
}

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
    color = QColor(DOT_COLORS.get(state, "#94a3b8"))
    painter.setPen(QPen(QColor("#ffffff"), 2))
    painter.setBrush(QBrush(color))
    painter.drawEllipse(size - 22, size - 22, 18, 18)
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self, config: Config, monitor: Monitor) -> None:
        super().__init__()
        self._config = config
        self._monitor = monitor
        self._force_quit = False
        self._warned_auth_error = False
        self._tray_state = ""

        self.setWindowTitle("ZJU 校园网自动登录")
        self.setWindowIcon(QIcon(str(resource_path("zju.ico").replace("\\", "/"))
                                 if os.path.isfile(resource_path("zju.ico")) else
                                 resource_path("zju_seal_blue.png")))
        self.resize(780, 764)
        self.setMinimumSize(740, 700)
        self.setStyleSheet(QSS)

        self._build_ui()
        self._build_tray()
        self._load_settings_into_ui()

        monitor.statusChanged.connect(self._on_status)
        monitor.logLine.connect(self._append_log)

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
        version = QLabel(f"v{self._version()} · 后台保活中")
        version.setObjectName("headerHint")
        hlay.addWidget(version)
        root.addWidget(header)

        # ---- 状态卡片 ----
        status_card = self._card()
        slay = QVBoxLayout(status_card)
        slay.setContentsMargins(20, 16, 20, 16)
        slay.setSpacing(8)

        status_row = QHBoxLayout()
        self._dot = QLabel()
        self._dot.setFixedSize(14, 14)
        self._status_text = QLabel("检测中…")
        self._status_text.setObjectName("statusText")
        status_row.addWidget(self._dot)
        status_row.addSpacing(10)
        status_row.addWidget(self._status_text)
        status_row.addStretch(1)
        self._btn_check = QPushButton("立即检测")
        self._btn_check.setObjectName("secondary")
        self._btn_check.clicked.connect(self._monitor.check_once)
        self._btn_login = QPushButton("立即登录")
        self._btn_login.setObjectName("primary")
        self._btn_login.clicked.connect(self._on_login_clicked)
        status_row.addWidget(self._btn_check)
        status_row.addSpacing(8)
        status_row.addWidget(self._btn_login)
        slay.addLayout(status_row)

        self._status_detail = QLabel("正在检查校园网状态…")
        self._status_detail.setObjectName("statusDetail")
        slay.addWidget(self._status_detail)

        grid_host = QFrame()
        grid_lay = QGridLayout(grid_host)
        grid_lay.setContentsMargins(0, 6, 0, 0)
        grid_lay.setHorizontalSpacing(28)
        grid_lay.setVerticalSpacing(4)
        self._fields: dict[str, QLabel] = {}
        for col, (key, title) in enumerate((("account", "认证账号"), ("ip", "本机 IP"),
                                            ("login_time", "上线时间"), ("last_check", "上次检测"))):
            klabel = QLabel(title)
            klabel.setObjectName("fieldKey")
            vlabel = QLabel("—")
            vlabel.setObjectName("fieldValue")
            vlabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid_lay.addWidget(klabel, 0, col)
            grid_lay.addWidget(vlabel, 1, col)
            self._fields[key] = vlabel
        slay.addWidget(grid_host)
        root.addWidget(status_card)

        # ---- 设置卡片 ----
        settings_card = self._card()
        glay = QVBoxLayout(settings_card)
        glay.setContentsMargins(20, 16, 20, 16)
        glay.setSpacing(10)
        title = QLabel("账号设置")
        title.setObjectName("cardTitle")
        glay.addWidget(title)

        form = QGridLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)

        def add_row(row: int, text: str, widget: QWidget, span: int = 1) -> None:
            label = QLabel(text)
            label.setObjectName("fieldKey")
            form.addWidget(label, row, 0)
            form.addWidget(widget, row, 1, 1, span)

        self._edit_user = QLineEdit()
        self._edit_user.setPlaceholderText("学号或工号")
        add_row(0, "账号", self._edit_user)

        self._edit_domain = QLineEdit()
        self._edit_domain.setPlaceholderText("一般留空；运营商用户填 @cmcc 等")
        add_row(1, "服务后缀", self._edit_domain)

        pwd_host = QFrame()
        pwd_lay = QHBoxLayout(pwd_host)
        pwd_lay.setContentsMargins(0, 0, 0, 0)
        pwd_lay.setSpacing(2)
        self._edit_pwd = QLineEdit()
        self._edit_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_pwd.setPlaceholderText("校园网密码（与信息门户一致）")
        eye = QToolButton()
        eye.setObjectName("eye")
        eye.setCheckable(True)
        eye.setText("👁")
        eye.setCursor(Qt.CursorShape.PointingHandCursor)
        eye.setFixedWidth(34)
        eye.toggled.connect(
            lambda on: self._edit_pwd.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        pwd_lay.addWidget(self._edit_pwd, 1)
        pwd_lay.addWidget(eye)
        add_row(2, "密码", pwd_host)

        self._spin_interval = QSpinBox()
        self._spin_interval.setRange(10, 600)
        self._spin_interval.setSuffix(" 秒")
        self._spin_interval.setToolTip("每隔多久检查一次在线状态；掉线后会自动重新登录")
        add_row(3, "检测间隔", self._spin_interval)

        opts_host = QFrame()
        opts_lay = QHBoxLayout(opts_host)
        opts_lay.setContentsMargins(0, 0, 0, 0)
        opts_lay.setSpacing(22)
        self._chk_auto = QCheckBox("掉线后自动登录")
        self._chk_tray = QCheckBox("关闭窗口时最小化到托盘")
        self._chk_boot = QCheckBox("开机自启")
        opts_lay.addWidget(self._chk_auto)
        opts_lay.addWidget(self._chk_tray)
        opts_lay.addWidget(self._chk_boot)
        opts_lay.addStretch(1)
        form.addWidget(opts_host, 4, 0, 1, 2)
        glay.addLayout(form)

        save_row = QHBoxLayout()
        self._save_hint = QLabel("")
        self._save_hint.setObjectName("statusDetail")
        btn_save = QPushButton("保存设置")
        btn_save.setObjectName("primary")
        btn_save.clicked.connect(self._save_settings)
        save_row.addStretch(1)
        save_row.addWidget(self._save_hint)
        save_row.addSpacing(10)
        save_row.addWidget(btn_save)
        glay.addLayout(save_row)
        root.addWidget(settings_card)

        # ---- 日志卡片 ----
        log_card = self._card()
        llay = QVBoxLayout(log_card)
        llay.setContentsMargins(20, 14, 20, 14)
        llay.setSpacing(6)
        log_title = QLabel("运行日志")
        log_title.setObjectName("cardTitle")
        llay.addWidget(log_title)
        self._log = QPlainTextEdit()
        self._log.setObjectName("log")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(400)
        self._log.setFixedHeight(132)
        llay.addWidget(self._log)
        root.addWidget(log_card, 1)

        tip = QLabel("提示：关闭窗口后程序会留在托盘继续保活；右键托盘图标可退出。")
        tip.setObjectName("statusDetail")
        root.addWidget(tip)

    @staticmethod
    def _version() -> str:
        from . import __version__
        return __version__

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(make_tray_icon("checking"), self)
        self._tray.setToolTip("ZJU 校园网自动登录")

        menu = QMenu(self)
        act_show = QAction("显示主窗口", menu)
        act_show.triggered.connect(self.show_normal)
        act_check = QAction("立即检测", menu)
        act_check.triggered.connect(self._monitor.check_once)
        act_login = QAction("立即登录", menu)
        act_login.triggered.connect(self._on_login_clicked)
        self._tray_boot = QAction("开机自启", menu)
        self._tray_boot.setCheckable(True)
        self._tray_boot.toggled.connect(self._toggle_autostart_from_tray)
        act_quit = QAction("退出", menu)
        act_quit.triggered.connect(self.quit_app)
        for act in (act_show, act_check, act_login):
            menu.addAction(act)
        menu.addSeparator()
        menu.addAction(self._tray_boot)
        menu.addSeparator()
        menu.addAction(act_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _load_settings_into_ui(self) -> None:
        cfg = self._config
        self._edit_user.setText(cfg.username)
        self._edit_domain.setText(cfg.domain)
        self._spin_interval.setValue(cfg.interval)
        self._chk_auto.setChecked(bool(cfg.auto_login))
        self._chk_tray.setChecked(bool(cfg.minimize_to_tray))
        self._chk_boot.setChecked(autostart.is_enabled())
        self._tray_boot.setChecked(autostart.is_enabled())
        if cfg.get_password():
            self._edit_pwd.setPlaceholderText("已保存到系统凭据管理器，留空则不修改")

    # ---------------------------------------------------------------- 动作

    def _on_login_clicked(self) -> None:
        if not self._config.username or not self._config.get_password():
            self._save_settings()
        if not self._config.username or not self._config.get_password():
            self._status_detail.setText("请先填写账号和密码并保存")
            return
        self._set_status_ui("checking", "正在登录…")
        self._monitor.login_now()

    def _save_settings(self) -> None:
        cfg = self._config
        cfg.username = self._edit_user.text()
        cfg.domain = self._edit_domain.text()
        cfg.interval = self._spin_interval.value()
        cfg.auto_login = self._chk_auto.isChecked()
        cfg.minimize_to_tray = self._chk_tray.isChecked()

        pwd = self._edit_pwd.text()
        if pwd:
            cfg.set_password(pwd)
            self._edit_pwd.clear()
            self._edit_pwd.setPlaceholderText("已保存到" + cfg.password_backend_label() + "，留空则不修改")
        if not cfg.get_password() and cfg.username:
            self._save_hint.setText("⚠ 请填写密码")
            return

        boot_ok = autostart.set_enabled(self._chk_boot.isChecked())
        self._chk_boot.setChecked(boot_ok)
        self._tray_boot.setChecked(boot_ok)
        cfg.autostart = boot_ok
        cfg.save()

        self._monitor.config_updated()
        self._save_hint.setText("已保存 ✓")
        QTimer.singleShot(2500, lambda: self._save_hint.setText(""))
        self._append_log("设置已保存（密码存储于：" + cfg.password_backend_label() + "）")
        self._monitor.check_once()

    def _toggle_autostart_from_tray(self, on: bool) -> None:
        result = autostart.set_enabled(on)
        self._chk_boot.setChecked(result)
        self._tray_boot.setChecked(result)
        self._config.autostart = result
        self._config.save()
        self._append_log("开机自启已" + ("开启" if result else "关闭"))

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
        text, color = STATE_META.get(state, (state, "#94a3b8"))
        self._dot.setStyleSheet(
            f"background: {color}; border-radius: 7px;")
        self._status_text.setText(text)
        self._status_detail.setText(detail)

    def _on_status(self, info: dict) -> None:
        state = info.get("state", "")
        self._set_status_ui(state, info.get("detail") or "")
        self._fields["account"].setText(info.get("username") or "—")
        self._fields["ip"].setText(info.get("ip") or "—")
        self._fields["login_time"].setText(info.get("login_time") or "—")
        self._fields["last_check"].setText(time.strftime("%H:%M:%S"))
        if info.get("ip") and state == "online":
            self._fields["login_time"].setText(info.get("login_time") or "—")

        icon_state = state if state in DOT_COLORS else "checking"
        if icon_state != self._tray_state:
            self._tray_state = icon_state
            self._tray.setIcon(make_tray_icon(icon_state))
        self._tray.setToolTip(
            f"ZJU 校园网自动登录\n{STATE_META.get(state, (state,))[0]}"
            + (f"（{info['ip']}）" if info.get("ip") else ""))

        if state == "auth_error" and not self._warned_auth_error:
            self._warned_auth_error = True
            self._tray.showMessage(
                "校园网认证失败",
                str(info.get("detail") or "请打开主窗口检查账号密码"),
                QSystemTrayIcon.MessageIcon.Critical, 6000)
        elif state == "online":
            self._warned_auth_error = False

    def _append_log(self, line: str) -> None:
        self._log.appendPlainText(line)

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
                "仍在后台运行",
                "ZJU 校园网自动登录将继续保活，右键托盘图标可退出。",
                QSystemTrayIcon.MessageIcon.Information, 4000)
