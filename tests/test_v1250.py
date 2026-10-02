"""v1.25.0 测试: DDNS / webhook / 钩子 / 开机推送 / 月报。"""

import tempfile
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

    def fake_json(url, payload=None, headers=None, method="GET", timeout=10.0):
        calls.append((method, payload))
        if method == "GET":
            return 200, {"result": [{"id": "r1", "content": "1.1.1.1"}]}
        return 200, {"success": True}

    with patch.object(DD, "_http_json", fake_json):
        ok, _ = DD.push_ddns(cfg, "10.9.9.9")
    assert ok
    assert calls[0][0] == "GET" and calls[1][0] == "PUT"
    assert calls[1][1]["content"] == "10.9.9.9"


def test_ddns_worker_pushes_on_ip_change(tmp_path):
    cfg = _cfg(tmp_path, ddns_provider="cloudflare", ddns_domain="lab.x.com",
               ddns_token="z", ddns_secret="s")
    worker = M.MonitorWorker(cfg)
    calls = []
    with patch.object(M, "push_ddns", side_effect=lambda c, ip: calls.append(ip) or (True, "ok")):
        worker._push_ddns_if_changed("10.0.0.1")
        worker._push_ddns_if_changed("10.0.0.1")  # 同 IP 不重复
        worker._push_ddns_if_changed("10.0.0.2")
    assert calls == ["10.0.0.1", "10.0.0.2"]


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


def test_monthly_report_guard(tmp_path):
    cfg = _cfg(tmp_path, monthly_report=True)
    worker = M.MonitorWorker(cfg)
    with patch("zju_autologin.config.read_events", return_value=[]), \
         patch.object(M.MonitorWorker, "_maybe_push") as push:
        worker._maybe_monthly_report()
        push.assert_not_called()  # 无事件不推
    assert cfg.data["last_month_report"]  # 但标记已处理(不重试)


def test_ddns_duckdns_chain(tmp_path):
    cfg = _cfg(tmp_path, ddns_provider="duckdns", ddns_domain="myname.duckdns.org",
               ddns_secret="tok-123")
    calls = []

    def fake_open(url, timeout=10):
        from urllib.error import HTTPError
        calls.append(url)

        class R:
            def read(self):
                return b"OK"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return R()

    with patch.object(DD.urllib.request, "urlopen", fake_open):
        ok, detail = DD.push_ddns(cfg, "10.1.2.3")
    assert ok and "updated" in detail
    assert "domains=myname" in calls[0] and "token=tok-123" in calls[0]
    assert "ip=10.1.2.3" in calls[0]


def test_ddns_duckdns_bare_name(tmp_path):
    cfg = _cfg(tmp_path, ddns_provider="duckdns", ddns_domain="myname",
               ddns_secret="t")
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

    with patch.object(DD.urllib.request, "urlopen", fake_open):
        ok, _ = DD.push_ddns(cfg, "1.2.3.4")
    assert ok and "domains=myname&" in calls[0]  # 裸名也可
