"""首次引导：三大核心功能必须可见、可确认，并落到配置。"""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from zju_autologin import i18n
from zju_autologin.config import Config


@pytest.fixture
def wizard(tmp_path, qapp, monkeypatch):
    if sys.platform == "darwin":
        pytest.skip("macOS runner 无窗口服务")
    from zju_autologin import autostart, service
    from zju_autologin.wizard import SetupWizard

    i18n.set_lang("zh-CN")
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart, "set_enabled", lambda value: value)
    monkeypatch.setattr(service, "is_installed", lambda max_age=60.0: False)
    calls = []
    monkeypatch.setattr(service, "install",
                        lambda cfg: (calls.append("install") or (True, "installed")))
    monkeypatch.setattr(service, "uninstall",
                        lambda: (calls.append("uninstall") or (True, "removed")))

    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "3230104321"
    cfg.set_password("pw")
    with patch("zju_autologin.wizard._DetectThread.run", lambda self: None):
        wz = SetupWizard(cfg)
    yield wz, cfg, calls
    wz.reject()


def test_features_page_defaults_and_choices(wizard):
    wz, cfg, calls = wizard
    assert wz._stack.count() == 5  # welcome / school / account / features / done
    assert wz._stack.currentIndex() == 0
    assert wz._chk_keepalive.isChecked()   # 保活默认开
    assert wz._chk_campus.isChecked()      # 代理共存默认开
    assert not wz._chk_service.isChecked()  # 系统级需要用户主动确认

    # 用户确认：保留保活，关掉代理例外，开启系统级保活
    wz._chk_campus.setChecked(False)
    wz._chk_service.setChecked(True)
    wz._stack.setCurrentIndex(3)
    wz._go_next()
    assert wz._stack.currentIndex() == 4
    text = wz._done_text.text()
    assert "自动保活" in text
    assert "系统级保活" in text
    assert "代理下校内直连" not in text

    wz._finish()
    assert cfg.auto_login is True
    assert cfg.campus_direct is False
    assert calls == ["install"]


def test_features_page_service_not_requested(wizard):
    wz, cfg, calls = wizard
    # 新用户不勾系统级：完成时不能弹 UAC/装任务
    wz._chk_service.setChecked(False)
    wz._finish()
    assert cfg.auto_login is True
    assert cfg.campus_direct is True
    assert calls == []
