"""首次打开的引导向导：检测当前网络 → 确认/填写账号密码 → 完成设置。

若用户打开向导时已经登录着校园网，会从门户在线状态中自动读出账号并填入，
用户只需确认账号、补一次密码（密码在门户侧不可获取，任何工具都拿不到）。
"""

from __future__ import annotations

import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import autostart, i18n, theme
from .config import Config
from .i18n import tr
from .srun import SrunClient, SrunError
from .ui import _load_pixmap


class _DetectThread(QThread):
    detected = pyqtSignal(dict)

    def run(self) -> None:
        try:
            self.detected.emit(SrunClient(timeout=3.0).get_status())
        except SrunError as exc:
            self.detected.emit({"portal_ok": False, "online": False, "username": "",
                                "ip": "", "raw": str(exc)})


class SetupWizard(QDialog):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self._config = config
        self._initial_lang = config.language
        self._detect_thread: _DetectThread | None = None

        self.setStyleSheet(theme.get_qss(config.theme))
        self.setWindowTitle(tr("wiz.title"))
        self.setModal(True)
        self.setFixedWidth(520)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_welcome_page())
        self._stack.addWidget(self._build_account_page())
        self._stack.addWidget(self._build_done_page())

        # 底部导航
        nav = QHBoxLayout()
        self._btn_back = QPushButton()
        self._btn_back.setObjectName("secondary")
        self._btn_back.clicked.connect(self._go_back)
        self._btn_next = QPushButton()
        self._btn_next.setObjectName("primary")
        self._btn_next.clicked.connect(self._go_next)
        self._lang = QComboBox()
        for lang in ("auto", "zh-CN", "en-US"):
            self._lang.addItem(self._lang_label(lang), lang)
        idx = self._lang.findData(config.language if config.language in ("auto", "zh-CN", "en-US") else "auto")
        self._lang.setCurrentIndex(max(0, idx))
        self._lang.currentIndexChanged.connect(self._on_lang_changed)
        nav.addWidget(self._lang)
        nav.addStretch(1)
        nav.addWidget(self._btn_back)
        nav.addWidget(self._btn_next)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(14)
        root.addWidget(self._stack, 1)
        root.addLayout(nav)

        # 已保存过账号(如重装/密码丢失恢复)时直接预填
        if config.username:
            self._edit_user.setText(config.username)
            self._edit_domain.setText(config.domain)

        self.retranslate_ui()
        self._stack.setCurrentIndex(0)
        self._start_detect()

    # ------------------------------------------------------------------ 页面

    def _build_welcome_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        logo = _load_pixmap("zju_logo_blue.png")
        if not logo.isNull():
            logo_label = QLabel()
            logo_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            logo_label.setPixmap(logo.scaledToHeight(64, Qt.TransformationMode.SmoothTransformation))
            lay.addSpacing(6)
            lay.addWidget(logo_label)
        self._welcome_title = QLabel()
        self._welcome_title.setObjectName("statusText")
        self._welcome_title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._welcome_title)
        self._intro = QLabel()
        self._intro.setWordWrap(True)
        self._intro.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._intro)
        lay.addSpacing(4)
        self._detect_label = QLabel()
        self._detect_label.setObjectName("statusDetail")
        self._detect_label.setWordWrap(True)
        self._detect_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._detect_label)
        lay.addStretch(1)
        return page

    def _build_account_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(10)
        self._account_title = QLabel()
        self._account_title.setObjectName("cardTitle")
        lay.addWidget(self._account_title)

        self._edit_user = QLineEdit()
        self._edit_user.setPlaceholderText(tr("ph.username"))
        self._edit_domain = QLineEdit()
        self._edit_domain.setPlaceholderText(tr("ph.domain"))
        self._edit_pwd = QLineEdit()
        self._edit_pwd.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit_pwd.setPlaceholderText(tr("ph.password"))

        pwd_row = QHBoxLayout()
        self._eye = QToolButton()
        self._eye.setObjectName("eye")
        self._eye.setCheckable(True)
        from .config import resource_path
        eye_icon_path = resource_path("icon_eye.png")
        if os.path.isfile(eye_icon_path):
            self._eye.setIcon(QIcon(eye_icon_path))
        else:
            self._eye.setText("👁")
        self._eye.setFixedWidth(34)
        self._eye.toggled.connect(
            lambda on: self._edit_pwd.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        pwd_row.addWidget(self._edit_pwd, 1)
        pwd_row.addWidget(self._eye)

        self._lbl_user = QLabel()
        self._lbl_domain = QLabel()
        self._lbl_pwd = QLabel()
        for label, child in ((self._lbl_user, self._edit_user),
                             (self._lbl_domain, self._edit_domain),
                             (self._lbl_pwd, pwd_row)):
            row = QHBoxLayout()
            label.setObjectName("fieldKey")
            label.setFixedWidth(72)
            row.addWidget(label)
            if isinstance(child, QWidget):
                row.addWidget(child, 1)
            else:
                row.addLayout(child, 1)
            lay.addLayout(row)

        self._pwd_note = QLabel()
        self._pwd_note.setObjectName("statusDetail")
        self._pwd_note.setWordWrap(True)
        lay.addWidget(self._pwd_note)
        self._account_error = QLabel()
        self._account_error.setObjectName("statusDetail")
        self._account_error.setStyleSheet("color: #ef4444;")
        self._account_error.setWordWrap(True)
        self._account_error.hide()
        lay.addWidget(self._account_error)
        self._chk_boot = QCheckBox()
        lay.addWidget(self._chk_boot)
        self._boot_hint = QLabel()
        self._boot_hint.setObjectName("statusDetail")
        self._boot_hint.setWordWrap(True)
        lay.addWidget(self._boot_hint)
        lay.addStretch(1)
        return page

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setSpacing(12)
        lay.addStretch(1)
        self._done_text = QLabel()
        self._done_text.setWordWrap(True)
        self._done_text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self._done_text)
        lay.addStretch(1)
        return page

    # ------------------------------------------------------------------ 导航

    def _go_back(self) -> None:
        idx = self._stack.currentIndex()
        if idx > 0:
            self._stack.setCurrentIndex(idx - 1)
        self._update_nav()

    def _go_next(self) -> None:
        idx = self._stack.currentIndex()
        if idx == 1 and (not self._edit_user.text().strip() or not self._edit_pwd.text()):
            self._account_error.setText(tr("wiz.error_need"))
            self._account_error.show()
            return
        if idx < self._stack.count() - 1:
            self._stack.setCurrentIndex(idx + 1)
        else:
            self._finish()
        self._update_nav()

    def _update_nav(self) -> None:
        idx = self._stack.currentIndex()
        self._btn_back.setVisible(idx > 0)
        self._btn_next.setText(tr("wiz.finish") if idx == self._stack.count() - 1 else tr("wiz.next"))
        if idx == 1:
            self._account_error.hide()

    def _finish(self) -> None:
        cfg = self._config
        cfg.username = self._edit_user.text()
        cfg.domain = self._edit_domain.text()
        cfg.language = self._lang.currentData() or "auto"
        if self._edit_pwd.text():
            cfg.set_password(self._edit_pwd.text())
        boot_ok = autostart.set_enabled(self._chk_boot.isChecked())
        cfg.autostart = boot_ok
        cfg.save()
        self.accept()

    # ------------------------------------------------------------------ 检测

    def _start_detect(self) -> None:
        self._detect_label.setText(tr("wiz.detecting"))
        self._detect_thread = _DetectThread(self)  # 挂父对象, 防止悬空销毁
        self._detect_thread.detected.connect(self._on_detected)
        self._detect_thread.start()

    def _on_detected(self, status: dict) -> None:
        if status.get("online") and status.get("username"):
            if not self._edit_user.text().strip():
                self._edit_user.setText(status["username"])
            self._detect_label.setText(tr("wiz.detected_online", username=status["username"]))
        elif status.get("portal_ok"):
            self._detect_label.setText(tr("wiz.detected_offline"))
        else:
            self._detect_label.setText(tr("wiz.detected_no_campus"))

    # ------------------------------------------------------------------ 语言

    @staticmethod
    def _lang_label(lang: str) -> str:
        if lang == "auto":
            return ("跟随系统 / Follow system"
                    if i18n.detect_system_lang() == "zh-CN" else "Follow system / 跟随系统")
        return i18n.LANG_LABELS.get(lang, lang)

    def _on_lang_changed(self) -> None:
        i18n.set_lang(self._lang.currentData() or "auto")
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(tr("wiz.title"))
        self._welcome_title.setText(tr("wiz.welcome"))
        self._intro.setText(tr("wiz.intro"))
        for i in range(self._lang.count()):
            self._lang.setItemText(i, self._lang_label(self._lang.itemData(i)))
        self._account_title.setText(tr("wiz.step_account"))
        self._lbl_user.setText(tr("field.username"))
        self._lbl_domain.setText(tr("field.domain"))
        self._lbl_pwd.setText(tr("field.password"))
        self._edit_user.setPlaceholderText(tr("ph.username"))
        self._edit_domain.setPlaceholderText(tr("ph.domain"))
        self._edit_pwd.setPlaceholderText(tr("ph.password"))
        self._pwd_note.setText(tr("wiz.pwd_note"))
        self._account_error.setText("")
        self._chk_boot.setText(tr("chk.autostart"))
        self._boot_hint.setText(tr("wiz.autostart_hint"))
        self._done_text.setText(tr("wiz.done_text", app=tr("app.name")))
        self._btn_back.setText(tr("wiz.prev"))
        self._update_nav()

    def done(self, result: int) -> None:  # noqa: N802
        # 取消向导时回滚界面语言，避免与未保存的配置不一致
        if result != QDialog.DialogCode.Accepted:
            i18n.set_lang(self._initial_lang)
        if self._detect_thread is not None and self._detect_thread.isRunning():
            self._detect_thread.wait(6000)  # 检测超时 3s, 留足余量防悬空线程
        super().done(result)
