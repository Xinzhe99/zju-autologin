"""离屏渲染首次引导向导截图（自检/文档用）。"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from zju_autologin.config import Config  # noqa: E402
from zju_autologin.wizard import SetupWizard  # noqa: E402


def main() -> int:
    page = sys.argv[1] if len(sys.argv) > 1 else "welcome"
    app = QApplication(sys.argv)
    config = Config()
    config.data["username"] = ""
    wizard = SetupWizard(config)
    wizard.show()
    app.processEvents()

    if page == "account":
        wizard._stack.setCurrentIndex(1)
        wizard._update_nav()
        wizard._edit_user.setText("3230104321")
    else:
        wizard._detect_label.setText(
            "检测到你当前已在线（账号 3230104321），已自动填入下方账号。请确认账号无误并设置密码。")
    app.processEvents()

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"wizard_{page}.png")
    wizard.grab().save(out)
    print("saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
