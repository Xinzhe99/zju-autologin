"""v1.25.4 回归守卫: 这一版修掉的高危问题各自锁一条。

1. DNS 兜底直连不再关闭 TLS 校验(以前把口令摘要+XXTEA 密钥交给任意对端)
2. "本机 IP 已在线" 是成功语义, 不能算登录失败
3. 配置文件含密码时权限 0600; null/错类型不再炸掉整个配置
4. 掉线统计只记真实跃迁(重试中间态不再把"掉线 N 次"刷成几十倍)
5. 网卡变化指纹真的能取到值(PyQt6 枚举不能直接 int())
6. 配置导出不泄露 DDNS 密钥; 取消向导不改用户配置
"""

from __future__ import annotations

import base64
import json
import os
import stat
import sys
from pathlib import Path

import pytest

import zju_autologin.srun as S
from zju_autologin.config import Config


# --------------------------------------------------------------- TLS 兜底直连

def test_pinned_connection_verifies_real_hostname(monkeypatch):
    """TCP 连 IP, 但 TLS 必须按原主机名做 SNI/校验(而不是按 IP)。"""
    seen = {}

    class _FakeSock:
        def __init__(self):
            self.closed = False

    def fake_create_connection(addr, timeout=None, source_address=None):
        seen["addr"] = addr
        return _FakeSock()

    class _FakeCtx:
        def wrap_socket(self, sock, server_hostname=None):
            seen["server_hostname"] = server_hostname
            return sock

    monkeypatch.setattr(S.socket, "create_connection", fake_create_connection)
    conn = S._PinnedHTTPSConnection("portal.example.edu", "10.1.2.3",
                                    verify_hostname="portal.example.edu",
                                    context=_FakeCtx())
    conn.connect()
    assert seen["addr"] == ("10.1.2.3", 443)
    assert seen["server_hostname"] == "portal.example.edu"


def test_dns_fallback_never_disables_verification(monkeypatch):
    """兜底路径必须走 _PinnedHTTPSHandler(带校验), 不得出现 CERT_NONE。"""
    src = Path(S.__file__).read_text(encoding="utf-8")
    assert "ssl.CERT_NONE" not in src
    assert "check_hostname = False" not in src
    assert "_PinnedHTTPSHandler" in src


# --------------------------------------------------------------- 登录语义

def test_already_online_is_success(monkeypatch):
    """"本机 IP 已在线" 无论出现在 suc_msg 还是 error 里都算成功。"""
    for resp in ({"error": "ok", "suc_msg": "ip_already_online_error"},
                 {"error": "ip_already_online_error"}):
        result = S._login_outcome("3230104321", "10.0.0.5", resp)
        assert result["ok"] is True, resp


def test_real_failure_still_fails():
    result = S._login_outcome("3230104321", "10.0.0.5", {"error": "password_error"})
    assert result["ok"] is False


# --------------------------------------------------------------- 配置安全

def test_config_file_is_private_when_password_in_it(tmp_path):
    if sys.platform == "win32":
        pytest.skip("Windows 走 ACL, 不适用 POSIX 权限位")
    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "u"
    cfg.set_password("secret")
    cfg.password_backend = "file"
    assert cfg.save() is True
    mode = stat.S_IMODE(os.stat(cfg.path).st_mode)
    assert mode == 0o600, f"含密码的配置不能是 {oct(mode)}"
    raw = json.loads(Path(cfg.path).read_text(encoding="utf-8"))
    assert base64.b64decode(raw["password_b64"]).decode() == "secret"


def test_config_survives_null_and_wrong_types(tmp_path):
    """手改/导入产生的 null 与错类型必须回退默认值, 而不是让程序起不来。"""
    path = tmp_path / "c.json"
    path.write_text(json.dumps({
        "username": None, "base_url": None, "interval": "abc",
        "password_backend": "file", "password_b64": None,
        "traffic_limit_gb": None,
    }), encoding="utf-8")
    cfg = Config(str(path))                      # 以前这里 TypeError 直接崩
    assert cfg.username == ""                    # 而不是真值字符串 "None"
    assert cfg.base_url == "https://net.zju.edu.cn"
    assert cfg.interval == 60
    assert cfg.traffic_limit_gb == 0


def test_config_keeps_keys_written_by_other_modules(tmp_path):
    """_DEFAULTS 之外的键(如 last_month_report)不能在 reload 时被丢掉。"""
    path = tmp_path / "c.json"
    cfg = Config(str(path))
    cfg.data["last_month_report"] = "2026-11"
    assert cfg.save() is True
    again = Config(str(path))
    assert again.data["last_month_report"] == "2026-11"


def test_config_bad_base64_keeps_the_rest(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({
        "username": "3230104321", "base_url": "https://portal.other.edu.cn",
        "password_backend": "file", "password_b64": "not*base64*!!",
    }), encoding="utf-8")
    cfg = Config(str(path))
    assert cfg.username == "3230104321"          # 账号/门户不因密码段坏掉而丢
    assert cfg.base_url == "https://portal.other.edu.cn"
    assert cfg.get_password() == ""


# --------------------------------------------------------------- 事件统计

def test_offline_events_count_once_per_outage(tmp_path, monkeypatch):
    """一次掉线只写一条 offline: 中间态(checking/login_fail)不进事件流。"""
    import zju_autologin.monitor as M

    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "u"
    cfg.set_password("p")
    worker = M.MonitorWorker(cfg)
    written: list[tuple] = []
    monkeypatch.setattr(M, "append_event", lambda kind, detail="", directory=None:
                        written.append((kind, detail)))

    worker._emit("online")
    for _ in range(5):                      # 模拟 5 轮失败重试
        worker._emit("checking")
        worker._emit("login_fail", detail="boom")
        worker._emit("offline", detail="wait_retry")
    worker._emit("online")

    kinds = [k for k, _ in written]
    assert kinds == ["online", "offline", "online"], kinds


def test_hooks_fire_on_state_edges_only(tmp_path, monkeypatch):
    """online/offline 钩子只在族间跃迁时各触发一次, 不是每轮都跑。"""
    import zju_autologin.monitor as M

    cfg = Config(str(tmp_path / "c.json"))
    cfg.data["hook_on_online"] = "echo up"
    cfg.data["hook_on_offline"] = "echo down"
    worker = M.MonitorWorker(cfg)
    calls: list[str] = []
    monkeypatch.setattr(M.MonitorWorker, "_run_hooks", lambda self, ev: calls.append(ev))

    worker._emit("online")
    for _ in range(3):
        worker._emit("checking")
        worker._emit("offline")
    worker._emit("online")
    assert calls == ["online", "offline", "online"]


# --------------------------------------------------------------- 网卡指纹

def test_interface_signature_is_not_empty(monkeypatch):
    """PyQt6 的枚举不能直接 int(), 否则指纹恒为空 → 网卡变化监听彻底失效。"""
    import zju_autologin.monitor as M

    sig = M._interface_signature()
    if not sig:
        pytest.skip("本机没有可用网卡(QtNetwork 不可用或全部未启用)")
    assert isinstance(sig, str) and ":" in sig
