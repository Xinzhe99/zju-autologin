"""离屏渲染主窗口截图（开发期自检 UI 用）。

    python tools/render_ui.py [online|need_config|auth_error]
"""

from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication  # noqa: E402

from zju_autologin.config import Config  # noqa: E402
from zju_autologin.monitor import Monitor  # noqa: E402
from zju_autologin.ui import MainWindow  # noqa: E402

SCENARIOS = {
    "online": {
        "state": "online", "username": "3230104321", "ip": "192.0.2.10",
        "login_time": "2026-09-17 21:49", "detail": "网络正常", "ts": 0,
    },
    "need_config": {
        "state": "need_config", "username": "", "ip": "",
        "login_time": "", "detail": "未配置账号，请在下方填写学号密码并保存", "ts": 0,
    },
    "auth_error": {
        "state": "auth_error", "username": "3230104321", "ip": "192.0.2.10",
        "login_time": "", "detail": "账号或密码错误", "ts": 0,
    },
}


def main() -> int:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "online"
    app = QApplication(sys.argv)
    config = Config(os.environ.get("ZJU_RENDER_CFG")) if os.environ.get("ZJU_RENDER_CFG") else Config()
    monitor = Monitor(config)
    win = MainWindow(config, monitor)
    win.show()
    app.processEvents()
    win._on_status(SCENARIOS[scenario])
    for line in ("监控已启动，每 60 秒检测一次",
                 "[16:40:12] 网络正常（IP 192.0.2.10）",
                 "[16:41:12] 网络正常（IP 192.0.2.10）"):
        win._append_log(line)
    app.processEvents()

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"screenshot_{scenario}.png")
    win.grab().save(out)
    print("saved:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
