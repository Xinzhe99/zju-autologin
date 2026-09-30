"""pytest 全局夹具：隔离 keyring，测试绝不读写真实系统凭据库。

历史教训(v1.11.0 与今日)：测试调用 Config.set_password 会写入真实
Windows 凭据管理器，覆盖用户真密码。此 conftest 使所有测试使用
进程内存字典替代 keyring。
"""

import pytest


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
