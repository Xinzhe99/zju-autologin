"""全局崩溃捕获：未捕获异常写入日志并托盘提示，避免程序无声退出。

PyQt6 中槽函数抛出的未捕获异常默认会调用 sys.excepthook —— 装上钩子后
既留痕又能让程序继续运行，而不是直接 abort。
"""

from __future__ import annotations

import sys
import threading
import traceback

from .config import append_file_log


def _notify_user() -> None:
    """若主窗口/托盘已就绪，弹一条托盘提示（延迟导入避免循环依赖）。"""
    try:
        from PyQt6.QtCore import QTimer
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtWidgets import QSystemTrayIcon

        from .i18n import tr

        app = QApplication.instance()
        if app is None:
            return
        main = getattr(UiHolder, "window", None)
        tray = getattr(main, "_tray", None) if main else None
        if tray is None:
            return

        def show() -> None:
            if tray.isVisible():
                tray.showMessage(
                    tr("crash.tray_title"),
                    tr("crash.tray_body"),
                    QSystemTrayIcon.MessageIcon.Warning, 6000)

        QTimer.singleShot(0, show)
    except Exception:  # noqa: BLE001 - 崩溃处理自身不能再抛
        pass


class UiHolder:
    """持有主窗口引用，供崩溃钩子访问托盘（避免循环导入）。"""

    window = None


def _format(exc_type, exc_value, exc_tb) -> str:
    return "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).strip()


def install() -> None:
    """安装全局异常钩子（主线程 + 子线程），重复调用安全。"""
    prev_hook = sys.excepthook

    def sys_hook(exc_type, exc_value, exc_tb):
        try:
            append_file_log("CRASH (main thread):\n" + _format(exc_type, exc_value, exc_tb))
        except Exception:  # noqa: BLE001
            pass
        _notify_user()
        if prev_hook is not None and prev_hook is not sys.__excepthook__:
            prev_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = sys_hook

    prev_thread_hook = getattr(threading, "excepthook", None)

    def thread_hook(args):
        try:
            append_file_log(
                f"CRASH (thread {getattr(args, 'thread', None)}):\n"
                + _format(args.exc_type, args.exc_value, args.exc_traceback))
        except Exception:  # noqa: BLE001
            pass
        _notify_user()
        if prev_thread_hook is not None:
            prev_thread_hook(args)

    threading.excepthook = thread_hook
