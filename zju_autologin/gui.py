"""ZJU 校园网自动登录 —— GUI 入口（pip 安装后命令: zju-autologin-gui）。

用法：
    python main.py                       打开主窗口（首次运行先进入引导向导）
    python main.py --minimized           启动后最小化到托盘（开机自启用）
    python main.py watch [--config 路径]  无界面守护（系统级保活计划任务使用）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication

from zju_autologin import crash, i18n, runtime
from zju_autologin.config import Config, config_dir
from zju_autologin.monitor import Monitor
from zju_autologin.ui import MainWindow
from zju_autologin.wizard import SetupWizard


def main() -> int:
    crash.install()  # 全局异常钩子：写日志 + 托盘提示，避免无声退出
    if len(sys.argv) > 1 and sys.argv[1] in ("watch", "--watch"):
        from zju_autologin.cli import main as cli_main
        return cli_main()

    app = QApplication(sys.argv)
    app.setApplicationName("ZJUAutoLogin")
    app.setApplicationDisplayName("ZJU 校园网自动登录")
    app.setQuitOnLastWindowClosed(False)

    # 单实例保护（固定锁路径, 跨进程互斥）; 原地自更新重启时旧实例
    # 短暂仍持有锁, 这里最多等 5 秒
    lock = QLockFile(str(Path(config_dir()) / "app.lock"))
    locked = False
    for _ in range(50):
        if lock.tryLock(100):
            locked = True
            break
    if not locked:
        print("已有实例在运行（托盘图标处查看）。")
        return 0
    runtime.app_lock = lock

    # 原地自更新的残留: 清理上一版本的 .old.exe（正在运行时无法删除, 此时必已退出）
    if getattr(sys, "frozen", False):
        old_exe = Path(sys.executable).with_suffix(".old.exe")
        try:
            old_exe.unlink(missing_ok=True)
        except OSError:
            pass

    config = Config()
    i18n.set_lang(config.language)

    # 首次使用或凭据不全 → 引导向导（含在线账号自动检测）
    # 密码缺失(重装/清理)时同样进入向导, 向导会带出账号并要求补一次密码
    if not config.username or not config.get_password():
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

    ret = app.exec()
    # 保活等后台线程可能仍卡在长网络操作中, 令进程退出被拖住形成"假死";
    # 所有配置/日志均为即时落盘, 此处以进程退出兜底, 保证托盘退出即时响应
    os._exit(ret)


if __name__ == "__main__":
    sys.exit(main())
