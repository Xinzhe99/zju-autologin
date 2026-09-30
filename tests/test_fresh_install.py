"""新安装会话强制引导 + 向导已存密码可留空。"""


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


def test_wizard_allows_blank_password_when_saved(tmp_path):
    from PyQt6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from zju_autologin.wizard import SetupWizard
    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "3230104321"
    cfg.set_password("saved")
    cfg.password_backend = "file"
    wz = SetupWizard(cfg)
    assert wz._has_saved_password is True
    wz._stack.setCurrentIndex(1)
    wz._edit_pwd.setText("")  # 留空 → 允许下一步(保持原密码)
    wz._go_next()
    assert wz._stack.currentIndex() == 2
    # 无已存密码时留空 → 拦截（stub store 同测试内共享, 白盒清空模拟新用户）
    cfg2 = Config(str(tmp_path / "c2.json"))
    cfg2._plain_password = ""
    cfg2.password_backend = "none"
    cfg2.username = ""
    wz2 = SetupWizard(cfg2)
    assert wz2._has_saved_password is False
    wz2._stack.setCurrentIndex(1)
    wz2._edit_user.setText("x")
    wz2._edit_pwd.setText("")
    wz2._go_next()
    assert wz2._stack.currentIndex() == 1  # 被拦截
