"""ZJU 校园网自动登录 —— 程序入口。

用法：
    python main.py                       打开主窗口（首次运行先进入引导向导）
    python main.py --minimized           启动后最小化到托盘（开机自启用）
    python main.py watch [--config 路径]  无界面守护（系统级保活计划任务使用）
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication

from zju_autologin import i18n
from zju_autologin.config import Config, config_dir
from zju_autologin.monitor import Monitor
from zju_autologin.ui import MainWindow
from zju_autologin.wizard import SetupWizard


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("watch", "--watch"):
        from zju_autologin.cli import main as cli_main
        return cli_main()

    app = QApplication(sys.argv)
    app.setApplicationName("ZJUAutoLogin")
    app.setApplicationDisplayName("ZJU 校园网自动登录")
    app.setQuitOnLastWindowClosed(False)

    # 单实例保护（固定锁路径，跨进程互斥）
    lock = QLockFile(str(Path(config_dir()) / "app.lock"))
    if not lock.tryLock(100):
        print("已有实例在运行（托盘图标处查看）。")
        return 0

    config = Config()
    i18n.set_lang(config.language)

    # 首次使用 → 引导向导（含在线账号自动检测）
    if not config.username:
        wizard = SetupWizard(config)
        wizard.exec()
        i18n.set_lang(config.language)

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
