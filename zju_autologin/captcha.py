"""验证码输入对话框: 显示门户验证码图片, 用户输入后带码重登。

支持两种远程场景:
- GUI 在场: 直接弹窗
- 推送提醒: captchaRequired 同时发系统通知, 远程用户可 RDP/VNC 回来输入
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .config import Config
from .i18n import tr
from .srun import SrunClient


class _CaptchaThread(QThread):
    """后台取验证码图片。"""
    fetched = pyqtSignal(object)  # dict{ok,cookie,data} 或 Exception

    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self._cfg = cfg

    def run(self) -> None:
        try:
            client = SrunClient(base_url=self._cfg.base_url,
                                ac_id=self._cfg.ac_id, timeout=8.0)
            self.fetched.emit(client.fetch_captcha())
        except Exception as exc:  # noqa: BLE001
            self.fetched.emit(exc)


class CaptchaDialog(QDialog):
    """验证码输入弹窗: 图片 + 输入框 + 刷新。完成时 cookie/captcha 由调用方提交。"""

    submitted = pyqtSignal(str, str)  # captcha, cookie

    def __init__(self, cfg: Config, parent=None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._cookie = ""
        self._thread: _CaptchaThread | None = None
        self.setWindowTitle(tr("captcha.title"))
        self.setModal(True)
        self.setFixedWidth(360)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        self._hint = QLabel()
        self._hint.setWordWrap(True)
        self._hint.setObjectName("statusDetail")
        lay.addWidget(self._hint)

        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._image.setMinimumHeight(64)
        lay.addWidget(self._image)

        self._edit = QLineEdit()
        self._edit.setPlaceholderText(tr("captcha.ph"))
        self._edit.returnPressed.connect(self._submit)
        lay.addWidget(self._edit)

        row = QHBoxLayout()
        self._btn_refresh = QPushButton()
        self._btn_refresh.setObjectName("secondary")
        self._btn_refresh.clicked.connect(self.load)
        self._btn_ok = QPushButton()
        self._btn_ok.setObjectName("primary")
        self._btn_ok.clicked.connect(self._submit)
        row.addWidget(self._btn_refresh)
        row.addStretch(1)
        row.addWidget(self._btn_ok)
        lay.addLayout(row)
        self.retranslate()
        self.load()

    def retranslate(self) -> None:
        self._hint.setText(tr("captcha.hint"))
        self._btn_refresh.setText(tr("captcha.refresh"))
        self._btn_ok.setText(tr("captcha.ok"))

    def load(self) -> None:
        self._image.setText(tr("captcha.loading"))
        self._btn_ok.setEnabled(False)
        if self._thread is not None and self._thread.isRunning():
            return

        def done(result):
            if isinstance(result, Exception) or not result.get("ok"):
                msg = result.get("msg", str(result)) if isinstance(result, dict) else str(result)
                self._image.setText(tr("captcha.load_fail", msg=str(msg)[:80]))
                return
            self._cookie = result["cookie"]
            pix = QPixmap()
            if pix.loadFromData(result["data"]):
                self._image.setPixmap(pix.scaledToWidth(
                    300, Qt.TransformationMode.SmoothTransformation))
                self._btn_ok.setEnabled(True)
                self._edit.setFocus()
            else:
                self._image.setText(tr("captcha.load_fail", msg="bad image"))

        self._thread = _CaptchaThread(self._cfg, self)
        self._thread.fetched.connect(done)
        self._thread.start()

    def _submit(self) -> None:
        code = self._edit.text().strip()
        if not code:
            return
        self.submitted.emit(code, self._cookie)
        self.accept()
