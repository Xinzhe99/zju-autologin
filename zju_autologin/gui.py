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

from zju_autologin import crash, i18n, runtime
from zju_autologin.config import Config, config_dir

# Qt 与 UI 模块刻意不在模块顶层导入: 系统级保活走的是本模块的 main() →
# "watch" 分支, 那条路径完全不需要 Qt, 早期顶层 import 让 SYSTEM 守护也
# 拉起整套 PyQt6(实测 commit 7.5→24MB, 且长期驻留), 纯属浪费。
# 需要这些符号的调用方(测试/入口)继续按模块属性访问, 见文件末尾的懒加载别名。
def _qt():
    """按需导入 Qt 与 UI 依赖, 返回 (QApplication, QLockFile, MainWindow, SetupWizard, Monitor)。"""
    from PyQt6.QtCore import QLockFile
    from PyQt6.QtWidgets import QApplication

    from zju_autologin.monitor import Monitor
    from zju_autologin.ui import MainWindow
    from zju_autologin.wizard import SetupWizard

    return QApplication, QLockFile, MainWindow, SetupWizard, Monitor


def _install_session() -> str:
    """安装版目录下的 .install-session 内容(安装器每次安装写入); 便携/源码为空。"""
    if not getattr(sys, "frozen", False):
        return ""
    try:
        from pathlib import Path

        marker = Path(sys.executable).parent / ".install-session"
        return marker.read_text(encoding="ascii", errors="replace").strip()
    except OSError:
        return ""


def need_wizard(config: Config, session: str, fresh_install: bool, argv: list[str]) -> bool:
    """启动时是否弹引导向导。

    - 首次使用 / 凭据不全 → 弹(开机自启且已有账号时除外: 向导是模态的, 开机后
      没人点它保活就一直不启动; 凭据真缺失时主窗会显示「未配置」引导去设置)
    - 新安装会话 → 手动安装弹一次; 静默安装(应用内更新/winget, 标记带 -silent)
      且已配置好的用户不弹 —— 以前每次升级都被向导拦住
    """
    configured = bool(config.username and config.get_password())
    if fresh_install and not (configured and session.endswith("silent")):
        return True
    quiet_boot = "--minimized" in argv and bool(config.username)
    return not configured and not quiet_boot


def _instance_key() -> str:
    """单实例唤起通道名(按配置目录区分用户, 多用户机器互不串门)。"""
    import hashlib

    return "ZJUAutoLogin-" + hashlib.sha1(str(config_dir()).encode("utf-8")).hexdigest()[:12]


def _activate_running_instance() -> None:
    try:
        from PyQt6.QtNetwork import QLocalSocket
    except ImportError:
        return
    sock = QLocalSocket()
    sock.connectToServer(_instance_key())
    if sock.waitForConnected(1000):
        sock.write(b"show\n")
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()


def _serve_activation(window) -> None:
    """监听后来者的唤起请求: 第二次启动 = 把已运行的主窗口带到前台。"""
    try:
        from PyQt6.QtNetwork import QLocalServer
    except ImportError:
        return
    name = _instance_key()
    QLocalServer.removeServer(name)  # 已持有单实例锁: 残留的旧通道(崩溃遗留)可安全清掉
    server = QLocalServer(window)
    if not server.listen(name):
        return

    def on_connection() -> None:
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.disconnected.connect(conn.deleteLater)
                conn.close()
        window.show_normal()

    server.newConnection.connect(on_connection)
    window._activation_server = server  # 持有引用


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ("watch", "--watch"):
        # 先分流再碰 Qt: 守护模式不需要图形栈(crash.install 依赖托盘气泡,
        # 由 CLI 自己的异常处理覆盖)。见文件顶部 Qt 懒加载说明。
        from zju_autologin.cli import main as cli_main
        return cli_main()

    crash.install()  # 全局异常钩子：写日志 + 托盘提示，避免无声退出
    QApplication, QLockFile, MainWindow, SetupWizard, Monitor = _qt()
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
        # 已有实例: 用户双击图标却什么都没发生, 只会以为程序坏了 —— 唤起已在运行
        # 的窗口(开机自启/看护任务带 --minimized 拉起时保持安静, 不打扰)
        if "--minimized" not in sys.argv:
            _activate_running_instance()
        print("已有实例在运行（托盘图标处查看）。")
        return 0
    runtime.app_lock = lock

    # 应用内原地更新的健康检查（普通安装包更新不参与，见 update_health）。
    from zju_autologin import update_health
    if getattr(sys, "frozen", False) and update_health.is_tracking():
        update_health.begin_pending()
        if update_health.needs_rollback():
            ok, detail = update_health.rollback()
            print(f"[ZJUAutoLogin] update rollback: {ok} {detail}")
            if ok:
                # 换回旧版后必须把它拉起来, 否则用户看到的仍是"程序没打开"
                import subprocess
                subprocess.Popen(
                    [sys.executable],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                os._exit(0)
            # 换不回去就继续正常启动新版本, 不能把用户直接踢出程序

    if getattr(sys, "frozen", False):
        # 安装器在 SYSTEM 保活占用 exe 时会把它改名为 `.exe.old` 再落新版；
        # 旧镜像已不再需要，启动时清掉（失败也无妨，下次再清）。
        _exe = Path(sys.executable)
        for _leftover in (Path(str(_exe) + ".old"), _exe.with_suffix(".failed.exe")):
            try:
                _leftover.unlink(missing_ok=True)
            except OSError:
                pass

    config = Config()
    i18n.set_lang(config.language)

    # 新安装会话检测: 安装器每次安装写入 .install-session 标记,
    # 首启发现未确认过的新会话 → 弹一次引导(规则见 need_wizard;
    # 便携/源码无标记, 行为不变)
    session = _install_session()
    fresh_install = bool(session) and session != config.install_session
    if fresh_install:
        config.data["install_session"] = session  # 先记 seen, 取消也不纠缠
        config.save()
    if need_wizard(config, session, fresh_install, sys.argv):
        wizard = SetupWizard(config)
        wizard.exec()
        i18n.set_lang(config.language)

    monitor = Monitor(config)
    window = MainWindow(config, monitor)
    monitor.start()
    _serve_activation(window)

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
