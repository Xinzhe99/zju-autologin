"""v1.25.8 回归: 改学号沿用旧密码的陷阱 + E2901 锁存 + 通知未配置不刷失败。

真实事故(2026-10-09): 用户在向导里改了学号, 密码框因显示「已保存——留空则保持
不变」而留空 → 应用沿用旧账号的旧密码 → 门户连续报 E2901(ldap_bind error),
且因 E2901 不在认证错误名单里, 应用拿着错误密码按退避反复 bind —— LDAP 连续
失败可能触发账号锁定。
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from zju_autologin.config import Config

pytest.importorskip("PyQt6.QtCore", reason="需要 PyQt6")

import zju_autologin.monitor as M  # noqa: E402


def make_worker(tmp_path, **overrides):
    cfg = Config(str(tmp_path / "cfg.json"))
    cfg.username = "12434001"
    cfg.set_password("old-account-pass")
    cfg.data["notify_provider"] = "none"
    cfg.data.update(overrides)
    return M.MonitorWorker(cfg), cfg


def test_e2901_latches_auth_error(tmp_path):
    """E2901 是认证被拒: 必须锁存, 不能拿错误密码按退避反复 bind(会锁账号)。"""
    worker, _ = make_worker(tmp_path)
    with patch.object(M.MonitorWorker, "_client") as mc:
        client = mc.return_value
        client.get_status.return_value = {
            "portal_ok": True, "online": False, "username": "", "ip": "", "raw": ""}
        client.login.return_value = {
            "ok": False, "msg": "认证被拒（E2901）", "username": "u", "ip": "",
            "resp": {"error": "E2901"}}
        worker._do_login(client=client)
        assert worker._auth_error, "E2901 必须置认证错误锁存"

        # 锁存后, 非手动检测不再自动重试
        attempts = []
        client.login.side_effect = lambda *a, **k: attempts.append(1) or {
            "ok": False, "msg": "x", "username": "u", "ip": "", "resp": {}}
        emitted = []
        worker.statusChanged.connect(emitted.append)
        worker._do_check(manual=False)
        client.get_status.return_value = {
            "portal_ok": True, "online": False, "username": "", "ip": "", "raw": ""}
        worker._do_check(manual=False)
        assert not attempts, "锁存期间不应再发起登录"
        assert emitted and emitted[-1]["state"] == "auth_error"


def test_saving_credentials_clears_auth_error(tmp_path):
    """用户改完密码保存设置 → credentialsChanged → clear_auth_error → 恢复自动重试。"""
    worker, _ = make_worker(tmp_path)
    worker._auth_error = "E2901"
    worker.clear_auth_error()  # Monitor.credentialsChanged 连接的就是它
    assert worker._auth_error == ""


def test_no_push_failure_log_without_provider(tmp_path):
    """未配置通知渠道是正常状态: 不该记「通知推送失败: notify disabled」。"""
    worker, cfg = make_worker(tmp_path)  # notify_provider = none
    logs = []
    worker.logLine.connect(logs.append)
    worker._maybe_push("notify.fail_title", "body")
    assert not any("推送失败" in line or "notify disabled" in line for line in logs), logs


def test_push_failure_still_logged_with_provider(tmp_path):
    """配了渠道但推送失败时, 失败仍然要记录(排障需要)。"""
    worker, cfg = make_worker(tmp_path, notify_provider="bark", notify_key="k")
    logs = []
    worker.logLine.connect(logs.append)
    with patch("zju_autologin.notify.send_notification",
               side_effect=lambda *a, **k: (False, "boom")):
        worker._maybe_push("notify.fail_title", "body")
    assert any("推送失败" in line or "失败" in line for line in logs), logs


def test_wizard_blocks_account_change_with_old_password(tmp_path, qapp):
    """改学号 + 密码留空(沿用旧密码) → 必须拦下要求重输。"""
    if sys.platform == "darwin":
        pytest.skip("macOS runner 无窗口服务, QPixmap 初始化会 Abort")
    from unittest.mock import patch as _p
    from zju_autologin.wizard import SetupWizard

    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "3230104321"
    cfg.set_password("old-pass")
    with _p("zju_autologin.wizard._DetectThread.run", lambda self: None):
        wz = SetupWizard(cfg)
    try:
        assert wz._has_saved_password is True
        wz._stack.setCurrentIndex(2)
        wz._edit_user.setText("12434001")   # 换了学号
        wz._edit_pwd.setText("")            # 密码留空 = 沿用旧密码
        wz._go_next()
        assert wz._stack.currentIndex() == 2, "必须拦在账号页要求重输密码"
        assert wz._account_error.text() != ""

        # 输了密码 → 放行
        wz._edit_pwd.setText("new-account-pass")
        wz._go_next()
        assert wz._stack.currentIndex() == 3
    finally:
        wz.reject()


def test_wizard_allows_same_account_with_saved_password(tmp_path, qapp):
    """学号没变 + 密码留空 = 正常的「保持原密码」, 不能拦。"""
    if sys.platform == "darwin":
        pytest.skip("macOS runner 无窗口服务, QPixmap 初始化会 Abort")
    from unittest.mock import patch as _p
    from zju_autologin.wizard import SetupWizard

    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "3230104321"
    cfg.set_password("saved-pass")
    with _p("zju_autologin.wizard._DetectThread.run", lambda self: None):
        wz = SetupWizard(cfg)
    try:
        wz._stack.setCurrentIndex(2)
        wz._edit_user.setText("3230104321")  # 学号未变
        wz._edit_pwd.setText("")             # 留空 = 保持
        wz._go_next()
        assert wz._stack.currentIndex() == 3
    finally:
        wz.reject()
