"""ZJU 校园网自动登录 —— 程序入口。

用法：
    python main.py              打开主窗口
    python main.py --minimized  启动后最小化到托盘（开机自启用）
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QLockFile, QTemporaryDir
from PyQt6.QtWidgets import QApplication

from zju_autologin.config import Config
from zju_autologin.monitor import Monitor
from zju_autologin.ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ZJUAutoLogin")
    app.setApplicationDisplayName("ZJU 校园网自动登录")
    app.setQuitOnLastWindowClosed(False)

    # 单实例保护
    temp_dir = QTemporaryDir()
    lock = QLockFile(f"{temp_dir.path()}/zju-autologin.lock")
    if not lock.tryLock(100):
        print("已有实例在运行（托盘图标处查看）。")
        return 0

    config = Config()
    monitor = Monitor(config)
    window = MainWindow(config, monitor)
    monitor.start()

    if "--minimized" in sys.argv and config.username:
        window.hide()
    else:
        window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
