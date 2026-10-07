"""新安装会话强制引导 + 向导已存密码可留空。"""

import pytest


import zju_autologin.gui as G
from zju_autologin.config import Config


def test_install_session_empty_when_not_frozen():
    assert G._install_session() == ""


def test_install_session_reads_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(G.sys, "frozen", True, raising=False)
    exe = tmp_path / "ZJUAutoLogin.exe"
    exe.write_bytes(b"MZ")
    (tmp_path / ".install-session").write_text("20260930120000", encoding="ascii")
    monkeypatch.setattr(G.sys, "executable", str(exe))
    assert G._install_session() == "20260930120000"


def test_wizard_page_flow_and_blank_password(tmp_path, qapp):
    """分页导航 + 已存密码可留空。

    回归点(v1.25.4): 校验曾经挂在"学校页"(index 1)上, 而账号输入框在
    index 2 —— 全新安装的用户还没见到输入框就被要求填账号密码, 向导成了
    死胡同(旧测试把这个错误行为当成了预期)。
    """
    import sys as _s
    if _s.platform == "darwin":
        pytest.skip("macOS runner 无窗口服务, QPixmap 初始化会 Abort")
    from zju_autologin.wizard import SetupWizard
    from unittest.mock import patch as _p

    def _fake_detect(status):
        return _p("zju_autologin.wizard._DetectThread.run",
                  lambda self: self.detected.emit(status))

    def _build(cfg, status):
        with _fake_detect(status):
            return SetupWizard(cfg)

    # --- 已存密码: 学校页放行, 账号页留空也放行(保持原密码) ---
    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "3230104321"
    cfg.set_password("saved")
    cfg.password_backend = "file"
    wz = _build(cfg, {"portal_ok": True, "online": True, "username": "3230104321",
                      "ip": "", "raw": "", "discovered_portal": {}})
    try:
        assert wz._has_saved_password is True
        wz._stack.setCurrentIndex(1)          # 学校页
        wz._go_next()
        assert wz._stack.currentIndex() == 2  # 必须能进账号页(修复前卡在 1)
        wz._edit_pwd.setText("")
        wz._go_next()
        assert wz._stack.currentIndex() == 3
    finally:
        wz.reject()

    # --- 新用户: 学校页放行, 账号页缺账号/密码则拦截 ---
    cfg2 = Config(str(tmp_path / "c2.json"))
    cfg2._plain_password = ""
    cfg2.password_backend = "none"
    cfg2.username = ""
    wz2 = _build(cfg2, {"portal_ok": True, "online": False, "username": "", "ip": "",
                        "raw": "", "discovered_portal": {}})
    try:
        assert wz2._has_saved_password is False
        wz2._stack.setCurrentIndex(1)
        wz2._go_next()
        assert wz2._stack.currentIndex() == 2   # 学校页不该拦人
        wz2._edit_user.setText("")
        wz2._edit_pwd.setText("")
        wz2._go_next()
        assert wz2._stack.currentIndex() == 2   # 账号页拦住(空账号)
        wz2._edit_user.setText("3230104321")
        wz2._go_next()
        assert wz2._stack.currentIndex() == 2   # 仍缺密码
        wz2._edit_pwd.setText("pw")
        wz2._go_next()
        assert wz2._stack.currentIndex() == 3
    finally:
        wz2.reject()


def test_wizard_cancel_rolls_back_detected_portal(tmp_path, qapp):
    """取消向导必须还原配置: 自动识别出的门户没被确认就不该落盘。"""
    import sys as _s
    if _s.platform == "darwin":
        pytest.skip("macOS runner 无窗口服务, QPixmap 初始化会 Abort")
    from unittest.mock import patch as _p
    from zju_autologin.wizard import SetupWizard

    cfg = Config(str(tmp_path / "c.json"))
    before = dict(cfg.data)
    with _p("zju_autologin.wizard._DetectThread.run", lambda self: None):
        wz = SetupWizard(cfg)
    try:
        wz._on_detected({"portal_ok": True, "online": False, "username": "", "ip": "",
                         "raw": "",
                         "discovered_portal": {"base_url": "https://portal.other.edu.cn",
                                               "ac_id": "99"}})
        assert wz._pending_base_url == "https://portal.other.edu.cn"
        assert cfg.data["base_url"] != "https://portal.other.edu.cn"  # 未确认不落盘
    finally:
        wz.reject()
    assert cfg.data == before
