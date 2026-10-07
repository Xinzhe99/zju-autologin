"""pytest 全局夹具：隔离 keyring 与用户真实配置目录。

历史教训(v1.11.0)：测试调用 Config.set_password 会写入真实
Windows 凭据管理器，覆盖用户真密码。此 conftest 使所有测试使用
进程内存字典替代 keyring。

同类教训(2026-10-07)：测试跑 MainWindow 的更新/日志路径时会经
append_file_log 写进用户真实的 %APPDATA%/ZJUAutoLogin/app.log，
污染线上运行日志。故所有测试的 config_dir 一律指向临时目录。
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path_factory, monkeypatch):
    """把配置目录沙箱化: 测试绝不写用户真实 %APPDATA%/ZJUAutoLogin。"""
    import zju_autologin.config as cfgmod

    sandbox = tmp_path_factory.mktemp("cfgdir")
    monkeypatch.setattr(cfgmod, "config_dir", lambda: sandbox)
    monkeypatch.setattr(cfgmod, "config_path", lambda: str(sandbox / "config.json"))
    yield sandbox


@pytest.fixture(autouse=True)
def _stub_keyring(monkeypatch):
    store: dict[tuple[str, str], str] = {}

    class FakeKeyring:
        @staticmethod
        def set_password(service, username, value):
            store[(service, username)] = value

        @staticmethod
        def get_password(service, username):
            return store.get((service, username))

        @staticmethod
        def delete_password(service, username):
            store.pop((service, username), None)

    fake = FakeKeyring()
    monkeypatch.setattr("keyring.set_password", fake.set_password, raising=False)
    monkeypatch.setattr("keyring.get_password", fake.get_password, raising=False)
    monkeypatch.setattr("keyring.delete_password", fake.delete_password, raising=False)
    # Config 内部 import keyring 的路径也一并替换
    import sys
    monkeypatch.setitem(sys.modules, "keyring", fake)
    yield store


def _gui_headless_abort() -> bool:
    """macOS 无窗口环境下构造 QWidget 会 Abort(Fatal), 提前识别。"""
    import sys
    if sys.platform != "darwin":
        return False
    import os
    return not os.environ.get("DISPLAY") and not os.environ.get("ALLOW_MAC_GUI_TESTS")


GUI_CAPABLE = not _gui_headless_abort()


@pytest.fixture(scope="session")
def qapp():
    """会话级 QApplication。

    必须显式长期持有: 每个测试各自 QApplication([]) 再被 GC, 会连带把其它
    测试里存活的 QObject(如 MonitorWorker)的 C++ 对象一起销毁, 表现为
    "wrapped C/C++ object has been deleted" 的随机跨文件失败。
    """
    if not GUI_CAPABLE:
        pytest.skip("无窗口环境, 跳过需要 GUI 的用例")
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])
