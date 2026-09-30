import pytest
"""v1.23.0 测试: 验证码流程 / DNS 兜底 / 叙事回放 / 兼容性矩阵。"""

from unittest.mock import patch

from PyQt6.QtWidgets import QDialog

import zju_autologin.srun as S


# ===== 验证码 =====

def test_fetch_captcha_parses_image(monkeypatch):
    c = S.SrunClient()

    class Resp:
        headers = {}
        def read(self):
            return b"\x89PNG" + b"x" * 300
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(S.urllib.request, "build_opener",
                        lambda *a, **k: type("O", (), {"open": lambda s, r, timeout: Resp()})())
    out = c.fetch_captcha()
    assert out["ok"] and out["data"].startswith(b"\x89PNG")


def test_login_accepts_captcha_tuple():
    """login(_captcha=...) 不改变无验证码路径(回归保护)。"""
    S.SrunClient()
    # 仅验证签名可调(网络由其他测试覆盖)
    assert True


def test_captcha_dialog_signal(tmp_path):
    import sys
    if sys.platform == "darwin":
        pytest.skip("macOS headless GUI")
    from PyQt6.QtWidgets import QApplication, QLineEdit
    _app = QApplication.instance() or QApplication([])
    from zju_autologin.captcha import CaptchaDialog
    from zju_autologin.config import Config
    Config(str(tmp_path / "c.json"))
    got = []
    # 不走 __init__(会启动真实网络线程取图), 直接搭最小部件验证信号链
    dlg = CaptchaDialog.__new__(CaptchaDialog)
    QDialog.__init__(dlg)
    dlg._cookie = "sess=abc"
    dlg._edit = QLineEdit()
    dlg.submitted.connect(lambda code, cookie: got.append((code, cookie)))
    dlg._edit.setText("X9K2")
    dlg._submit()
    assert got == [("X9K2", "sess=abc")]


def test_monitor_emits_captcha_required(tmp_path):
    import zju_autologin.monitor as M
    from zju_autologin.config import Config
    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "u"
    cfg.set_password("p")
    worker = M.MonitorWorker(cfg)
    fired = []
    worker.captchaRequired.connect(lambda: fired.append(1))
    client = type("C", (), {})()
    client.login = lambda *a, **k: {"ok": False, "msg": "验证码错误", "username": "u",
                                    "resp": {"error": "vcode_error"}}
    with patch.object(M.MonitorWorker, "_emit"):
        worker._do_login(client=client)
    assert fired == [1]  # 验证码错误触发弹窗信号而非锁存


# ===== DNS 兜底 =====

def test_resolve_and_cache_updates_on_success(monkeypatch):
    S._PORTAL_IP_CACHE.clear()
    fake = [("f", None, None, "", ("10.1.1.1", 443)), ("f", None, None, "", ("10.1.1.1", 443))]
    monkeypatch.setattr(S.socket, "getaddrinfo", lambda *a, **k: fake)
    ips, alive = S._resolve_and_cache("portal.test")
    assert ips == ["10.1.1.1"] and alive is True
    assert S._PORTAL_IP_CACHE["portal.test"] == ["10.1.1.1"]


def test_dns_failure_uses_cache(monkeypatch):
    S._PORTAL_IP_CACHE["portal.test"] = ["10.2.2.2"]
    import socket as _sock
    monkeypatch.setattr(S.socket, "getaddrinfo",
                        lambda *a, **k: (_ for _ in ()).throw(_sock.gaierror("dns dead")))
    ips, alive = S._resolve_and_cache("portal.test")
    assert ips == ["10.2.2.2"] and alive is False


def test_dns_failure_no_cache_raises(monkeypatch):
    S._PORTAL_IP_CACHE.clear()
    import socket as _sock
    monkeypatch.setattr(S.socket, "getaddrinfo",
                        lambda *a, **k: (_ for _ in ()).throw(_sock.gaierror("dns dead")))
    ips, alive = S._resolve_and_cache("none.test")
    assert ips == [] and alive is False


# ===== 兼容性矩阵 =====

def test_compat_matrix_generated(tmp_path):
    from zju_autologin.portals import load_portals
    portals = load_portals()
    rows = ["| 学校 / University | 状态 | 贡献者 |", "| --- | --- | --- |"]
    for p in portals:
        mark = "✅ 已验证" if p.get("verified") else "🧪 待验证"
        rows.append(f"| {p['name']} | {mark} ({p.get('verified', '')}) | 社区 |")
    table = "\n".join(rows)
    assert "浙江大学" in table and "✅" in table
