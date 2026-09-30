import pytest
"""v1.22.0 通用化测试: 门户发现 / 学校页 / 验证码探测 / domain 回读。"""

import sys
from unittest.mock import patch

import pytest

import zju_autologin.srun as S


def _force(monkeypatch, platform_="linux"):
    monkeypatch.setattr(sys, "platform", platform_)


def test_discover_portal_srun_signature(monkeypatch):
    """重定向到 srun 登录页 → 提取 base_url/ac_id。"""
    class Resp:
        headers = {"Location": "https://portal.foo.edu.cn/srun_portal_pc?ac_id=12&user_ip=10.1.2.3"}
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    with patch.object(S.urllib.request, "build_opener",
                      return_value=type("O", (), {"open": lambda self, req, timeout: Resp()})()):
        out = S.SrunClient.discover_portal()
    assert out["base_url"] == "https://portal.foo.edu.cn"
    assert out["ac_id"] == "12"
    assert out["ip"] == "10.1.2.3"


def test_discover_portal_rejects_non_srun(monkeypatch):
    """锐捷/Dr.COM 等其他认证系统的重定向不误判。"""
    class Resp:
        headers = {"Location": "http://1.1.1.1/drcom/login?u=xx"}
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    with patch.object(S.urllib.request, "build_opener",
                      return_value=type("O", (), {"open": lambda self, req, timeout: Resp()})()):
        assert S.SrunClient.discover_portal() == {}


def test_discover_portal_no_redirect(monkeypatch):
    """已认证(无重定向) → 空结果。"""
    class Resp:
        headers = {}
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    with patch.object(S.urllib.request, "build_opener",
                      return_value=type("O", (), {"open": lambda self, req, timeout: Resp()})()):
        assert S.SrunClient.discover_portal() == {}


def test_check_captcha_disabled_by_default(monkeypatch):
    """接口不存在(多数部署) → False(无验证码)。"""
    c = S.SrunClient()
    def boom(*a, **k):
        raise S.SrunError("404")
    c._jsonp = boom
    assert c.check_captcha() is False


def test_check_captcha_enabled(monkeypatch):
    c = S.SrunClient()
    c._jsonp = lambda *a, **k: {"enable_captcha": "1"}
    assert c.check_captcha() is True


def test_get_status_includes_domain():
    c = S.SrunClient()
    import json as _j
    body = "cb(" + _j.dumps({"error": "ok", "user_name": "u", "user_ip": "1.2.3.4",
                            "add_time": 1789652994, "domain": "cmcc",
                            "billing_name": "b", "all_bytes": 1}) + ")"
    c._get = lambda path, params, **kw: body
    st = c.get_status()
    assert st.get("domain") == "cmcc"


def test_wizard_school_page_exists(tmp_path):
    import sys
    if sys.platform == "darwin":
        pytest.skip("macOS headless GUI")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from zju_autologin.config import Config
    from zju_autologin.wizard import SetupWizard
    cfg = Config(str(tmp_path / "c.json"))
    wz = SetupWizard(cfg)
    assert wz._stack.count() == 4          # welcome / school / account / done
    assert wz._school_combo.count() >= 2   # 自定义 + 浙大种子
    # 预设选择联动(屏蔽真实网络探测线程, 防阻塞解释器退出)
    wz._probe_school = lambda: None
    wz._school_combo.setCurrentIndex(1)
    assert "zju.edu.cn" in wz._school_url.text()
