"""v1.25.0 测试: DDNS / webhook / 钩子 / 开机推送 / 月报。"""

import time
from pathlib import Path
from unittest.mock import patch

import zju_autologin.ddns as DD
import zju_autologin.monitor as M
import zju_autologin.notify as N
from zju_autologin.config import Config


def _cfg(tmp_path, **kw):
    cfg = Config(str(Path(tmp_path) / "c.json"))
    cfg.username = "u"
    cfg.set_password("p")
    cfg.password_backend = "file"
    cfg.data.update(kw)
    return cfg


def test_ddns_disabled_by_default(tmp_path):
    assert DD.ddns_enabled(_cfg(tmp_path)) is False


def test_ddns_cloudflare_update_chain(tmp_path):
    cfg = _cfg(tmp_path, ddns_provider="cloudflare", ddns_domain="lab.example.com",
               ddns_token="zone1", ddns_secret="tok")
    calls = []

    def fake_json(url, payload=None, headers=None, method="GET", timeout=10.0, opener=None):
        calls.append((method, payload))
        if method == "GET":
            return 200, {"result": [{"id": "r1", "content": "1.1.1.1"}]}
        return 200, {"success": True}

    with patch.object(DD, "_http_json", fake_json):
        ok, _ = DD.push_ddns(cfg, "10.9.9.9")
    assert ok
    assert calls[0][0] == "GET" and calls[1][0] == "PUT"
    assert calls[1][1]["content"] == "10.9.9.9"


def test_ddns_cloudflare_creates_missing_record(tmp_path):
    """记录不存在时应当 POST 新建, 而不是报 "query failed: HTTP 200"。"""
    cfg = _cfg(tmp_path, ddns_provider="cloudflare", ddns_domain="new.example.com",
               ddns_token="zone1", ddns_secret="tok")
    calls = []

    def fake_json(url, payload=None, headers=None, method="GET", timeout=10.0, opener=None):
        calls.append((method, url))
        if method == "GET":
            return 200, {"result": []}          # 记录不存在
        return 200, {"success": True}

    with patch.object(DD, "_http_json", fake_json):
        ok, detail = DD.push_ddns(cfg, "10.9.9.9")
    assert ok and detail == "created"
    assert calls[1][0] == "POST"
    assert calls[1][1].endswith("/dns_records")


def test_ddns_proxy_opener_is_used(tmp_path):
    """DDNS 必须走调用方给的 opener(与探测/更新同一套代理策略)。"""
    cfg = _cfg(tmp_path, ddns_provider="cloudflare", ddns_domain="lab.example.com",
               ddns_token="zone1", ddns_secret="tok")
    seen = []

    def fake_json(url, payload=None, headers=None, method="GET", timeout=10.0, opener=None):
        seen.append(opener)
        if method == "GET":
            return 200, {"result": [{"id": "r1", "content": "1.1.1.1"}]}
        return 200, {"success": True}

    sentinel = object()
    with patch.object(DD, "_http_json", fake_json):
        DD.push_ddns(cfg, "10.9.9.9", opener=sentinel)
    assert seen and all(o is sentinel for o in seen)


def test_ddns_worker_pushes_on_ip_change(tmp_path):
    cfg = _cfg(tmp_path, ddns_provider="cloudflare", ddns_domain="lab.x.com",
               ddns_token="z", ddns_secret="s")
    worker = M.MonitorWorker(cfg)
    calls = []
    with patch.object(M, "push_ddns",
                      side_effect=lambda c, ip, opener=None: calls.append(ip) or (True, "ok")):
        worker._push_ddns_if_changed("10.0.0.1")
        worker._push_ddns_if_changed("10.0.0.1")  # 同 IP 不重复
        worker._push_ddns_if_changed("10.0.0.2")
    assert calls == ["10.0.0.1", "10.0.0.2"]


def test_ddns_worker_retries_after_failure(tmp_path):
    """推送失败不能记账: 否则域名会一直停在旧 IP 上再也不会重试。"""
    cfg = _cfg(tmp_path, ddns_provider="cloudflare", ddns_domain="lab.x.com",
               ddns_token="z", ddns_secret="s")
    worker = M.MonitorWorker(cfg)
    calls = []
    results = [(False, "boom"), (True, "ok"), (True, "ok")]

    def fake_push(c, ip, opener=None):
        calls.append(ip)
        return results.pop(0)

    with patch.object(M, "push_ddns", side_effect=fake_push):
        worker._push_ddns_if_changed("10.0.0.1")   # 失败
        worker._push_ddns_if_changed("10.0.0.1")   # 必须重试
        worker._push_ddns_if_changed("10.0.0.1")   # 成功记账后不再重复
    assert calls == ["10.0.0.1", "10.0.0.1"]


def test_webhook_channel_payload(tmp_path):
    cfg = _cfg(tmp_path, notify_provider="webhook", notify_key="https://hooks.example/x")
    sent = {}

    def fake_hj(url, payload=None, timeout=6.0, opener=None):
        sent.update(payload or {})
        return True, "ok"

    with patch.object(N, "_http_json", fake_hj):
        ok, _ = N.send_notification(cfg, "标题", "正文")
    assert ok and sent["title"] == "标题" and sent["source"] == "zju-autologin"


def test_hooks_run_and_log(tmp_path):
    cfg = _cfg(tmp_path, hook_on_online="echo OK123")
    worker = M.MonitorWorker(cfg)
    logs = []
    worker.logLine.connect(logs.append)
    worker._run_hooks("online")
    time.sleep(0.5)
    assert any("OK123" in l or "rc=0" in l for l in logs)


def test_boot_notify_once(tmp_path):
    cfg = _cfg(tmp_path, notify_provider="webhook", notify_key="https://x/y")
    worker = M.MonitorWorker(cfg)
    pushed = []
    worker._maybe_push = lambda t, b: pushed.append(t)
    worker._boot_notify({"ip": "10.1.1.1"})
    worker._boot_notify({"ip": "10.1.1.1"})
    assert pushed == ["notify.boot_title"]  # 只推一次


def test_monthly_report_guard(tmp_path, monkeypatch):
    """月报只在每月 1 日、且上月确有事件时才推。"""
    import time as _t
    fixed = _t.struct_time((2026, 11, 1, 9, 0, 0, 5, 305, 0))

    class FakeTime:
        """只把"当前时间"钉在 11 月 1 日; 带参数调用照旧走真实实现。

        以前直接 patch 掉整个 time.localtime, 于是连事件时间戳的换算也返回
        固定值 —— 上月的判断被悄悄破坏, 断言只能靠日志时间戳里恰好有个 "1"
        才通过(20:03:47 这种时刻就会红)。
        """

        def __getattr__(self, name):
            return getattr(_t, name)

        def localtime(self, *args):
            if not args:
                return fixed
            return _t.localtime(*args)

    cfg = _cfg(tmp_path, monthly_report=True)
    worker = M.MonitorWorker(cfg)

    # 非 1 日(用真实时间): 什么都不做
    if _t.localtime().tm_mday != 1:      # 恰好在 1 号跑测试时这条不适用
        worker._maybe_monthly_report()
        assert cfg.data.get("last_month_report") in ("", None)

    monkeypatch.setattr(M, "time", FakeTime())

    # 1 日 + 无事件: 记账但不推
    with patch("zju_autologin.config.read_events", return_value=[]), \
         patch.object(M.MonitorWorker, "_maybe_push") as push:
        worker._maybe_monthly_report()
        push.assert_not_called()  # 无事件不推
    assert cfg.data["last_month_report"] == "2026-11"  # 但标记已处理(不重试)

    # 1 日 + 上月有掉线: 推送, 数字只算上月
    sub = tmp_path / "second"
    sub.mkdir()
    cfg2 = _cfg(sub, monthly_report=True)
    worker2 = M.MonitorWorker(cfg2)
    prev = _t.mktime((2026, 10, 15, 12, 0, 0, 0, 0, -1))
    other = _t.mktime((2026, 9, 15, 12, 0, 0, 0, 0, -1))  # 更早的月份不该被算进来
    events = [{"ts": prev, "event": "offline"}, {"ts": prev, "event": "online"},
              {"ts": other, "event": "offline"}, {"ts": other, "event": "offline"}]
    logs = []
    worker2.logLine.connect(logs.append)
    with patch("zju_autologin.config.read_events", return_value=events), \
         patch.object(M.MonitorWorker, "_maybe_push") as push:
        worker2._maybe_monthly_report()
    assert cfg2.data["last_month_report"] == "2026-11"
    # 断言真实文案而不是"日志里出现过 1": 上月只有 1 次掉线(不是 3 次)
    assert any("掉线 1 次" in line or "1 drops" in line for line in logs), logs


def test_ddns_duckdns_chain(tmp_path):
    cfg = _cfg(tmp_path, ddns_provider="duckdns", ddns_domain="myname.duckdns.org",
               ddns_secret="tok-123")
    calls = []

    def fake_open(url, timeout=10):
        calls.append(url)

        class R:
            def read(self):
                return b"OK"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R()

    class _Opener:
        def open(self, url, timeout=10):
            return fake_open(url, timeout)

    # DuckDNS 现在走调用方给的 opener(未传时才回落到 build_opener)
    with patch.object(DD.urllib.request, "build_opener", lambda *a, **k: _Opener()):
        ok, detail = DD.push_ddns(cfg, "10.1.2.3")
    assert ok and "updated" in detail
    assert "domains=myname" in calls[0] and "token=tok-123" in calls[0]
    assert "ip=10.1.2.3" in calls[0]


def test_ddns_duckdns_ipv6_uses_ipv6_param(tmp_path):
    """IPv6 值必须走 ipv6= 参数, 塞进 ip= 会被 DuckDNS 直接忽略。"""
    cfg = _cfg(tmp_path, ddns_provider="duckdns", ddns_domain="myname.duckdns.org",
               ddns_secret="tok")

    class _Resp:
        def read(self):
            return b"OK"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Opener:
        def __init__(self):
            self.urls = []

        def open(self, url, timeout=10):
            self.urls.append(url)
            return _Resp()

    op = _Opener()
    ok, _ = DD.push_ddns(cfg, "2001:db8::1", opener=op)
    assert ok and "ipv6=2001%3Adb8%3A%3A1" in op.urls[0]
    assert "&ip=" not in op.urls[0]


def test_ddns_duckdns_bare_name(tmp_path):
    cfg = _cfg(tmp_path, ddns_provider="duckdns", ddns_domain="myname",
               ddns_secret="t")
    calls = []

    class _Resp:
        def read(self):
            return b"OK"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Opener:
        def open(self, url, timeout=10):
            calls.append(url)
            return _Resp()

    with patch.object(DD.urllib.request, "build_opener", lambda *a, **k: _Opener()):
        ok, _ = DD.push_ddns(cfg, "1.2.3.4")
    assert ok and "domains=myname&" in calls[0]  # 裸名也可
