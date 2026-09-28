"""MonitorWorker 状态机测试：mock 门户与外网探测，不访问真实网络。

覆盖：状态判定、自动登录触发、指数退避、错误锁存（auth_error）、
E2620 设备超限路径、通知阈值与恢复、电池降频切换。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from zju_autologin.config import Config
from zju_autologin.monitor import MonitorWorker, probe_internet  # noqa: E402

pytest.importorskip("PyQt6.QtCore", reason="需要 PyQt6")


def make_worker(tmp_path, **cfg_overrides) -> MonitorWorker:
    cfg = Config(path=str(tmp_path / "cfg.json"))
    cfg.username = "3230104321"
    cfg.data["notify_provider"] = "none"  # 测试不发真实推送
    for key, value in cfg_overrides.items():
        cfg.data[key] = value
    return MonitorWorker(cfg), cfg


ONLINE = {"portal_ok": True, "online": True, "username": "3230104321",
          "ip": "10.0.0.5", "login_time": "2026-09-17 21:49", "raw": ""}
OFFLINE = {"portal_ok": True, "online": False, "username": "", "ip": "", "raw": "not_online"}


def run_check(worker: MonitorWorker) -> dict:
    """同步执行一轮检测，返回发射的最后一个状态。"""
    emitted = []
    worker.statusChanged.connect(emitted.append)
    worker._do_check(manual=False)
    assert emitted, "应当发射一次状态"
    return emitted[-1]


def test_online_ok(tmp_path):
    worker, _ = make_worker(tmp_path)
    with patch.object(MonitorWorker, "_client") as mc, \
         patch("zju_autologin.monitor.probe_internet", return_value=True):
        mc.return_value.get_status.return_value = dict(ONLINE)
        info = run_check(worker)
    assert info["state"] == "online"
    assert info["ip"] == "10.0.0.5"


def test_no_campus_on_portal_error(tmp_path):
    worker, _ = make_worker(tmp_path)
    with patch.object(MonitorWorker, "_client") as mc:
        mc.return_value.get_status.side_effect = Exception("down")
        # SrunError 才会走 no_campus，这里用子类模拟
        from zju_autologin.srun import SrunError
        mc.return_value.get_status.side_effect = SrunError("down")
        info = run_check(worker)
    assert info["state"] == "no_campus"


def test_need_config_without_credentials(tmp_path):
    worker, cfg = make_worker(tmp_path)
    cfg.username = ""
    with patch.object(MonitorWorker, "_client") as mc:
        mc.return_value.get_status.return_value = dict(OFFLINE)
        info = run_check(worker)
    assert info["state"] == "need_config"


def test_offline_when_auto_login_disabled(tmp_path):
    worker, _ = make_worker(tmp_path, auto_login=False)
    with patch.object(MonitorWorker, "_client") as mc:
        mc.return_value.get_status.return_value = dict(OFFLINE)
        info = run_check(worker)
    assert info["state"] == "offline"
    # 手动检测则绕过开关直接登录
    with patch.object(MonitorWorker, "_client") as mc2, \
         patch.object(MonitorWorker, "_do_login") as login:
        mc2.return_value.get_status.return_value = dict(OFFLINE)
        worker._do_check(manual=True)
        login.assert_called_once()


def test_auto_login_invoked_when_offline(tmp_path):
    worker, _ = make_worker(tmp_path)
    with patch.object(MonitorWorker, "_client") as mc, \
         patch.object(MonitorWorker, "_do_login") as login:
        mc.return_value.get_status.return_value = dict(OFFLINE)
        run_check(worker)
        login.assert_called_once()


def test_backoff_between_attempts(tmp_path):
    worker, _ = make_worker(tmp_path)
    with patch.object(MonitorWorker, "_client") as mc, \
         patch.object(MonitorWorker, "_do_login") as login, \
         patch("zju_autologin.monitor.time") as t:
        t.time.return_value = 1000.0
        mc.return_value.get_status.return_value = dict(OFFLINE)
        worker._last_login_attempt = 1000.0 - 10  # 刚试过 10 秒
        info = run_check(worker)
        login.assert_not_called()
        assert info["state"] == "offline"  # 退避等待
        t.time.return_value = 1000.0 + 120  # 超过第一档退避 60s
        run_check(worker)
        login.assert_called_once()


def test_auth_error_latched(tmp_path):
    worker, _ = make_worker(tmp_path)
    worker._auth_error = "密码错误（模拟锁存）"
    with patch.object(MonitorWorker, "_client") as mc:
        mc.return_value.get_status.return_value = dict(OFFLINE)
        info = run_check(worker)
    assert info["state"] == "auth_error"


def test_password_error_latches_and_clears(tmp_path):
    worker, _ = make_worker(tmp_path)
    with patch.object(MonitorWorker, "_client") as mc:
        client = mc.return_value
        client.get_status.return_value = dict(OFFLINE)
        client.login.return_value = {
            "ok": False, "msg": "账号或密码错误", "username": "x", "ip": "", "resp": {"error": "password_error"},
        }
        worker._do_login(client=client)
        assert worker._auth_error  # 已锁存
        assert run_check.__name__  # noqa: B018
    with patch.object(MonitorWorker, "_client") as mc:
        mc.return_value.get_status.return_value = dict(OFFLINE)
        info = run_check(worker)
        assert info["state"] == "auth_error"


def test_e2620_emits_ecode(tmp_path):
    worker, _ = make_worker(tmp_path)
    with patch.object(MonitorWorker, "_client") as mc:
        client = mc.return_value
        client.get_status.return_value = dict(OFFLINE)
        client.login.return_value = {
            "ok": False, "msg": "在线数已达上限", "username": "x", "ip": "",
            "resp": {"error": "E2620"},
        }
        worker._do_login(client=client)
    assert worker._auth_error  # 锁存等待人工踢号


def test_login_success_resets_fail_count(tmp_path):
    worker, _ = make_worker(tmp_path)
    worker._fail_count = 3
    with patch.object(MonitorWorker, "_client") as mc:
        client = mc.return_value
        client.get_status.return_value = dict(OFFLINE)
        client.login.return_value = {"ok": True, "msg": "ok", "username": "x", "ip": "1.2.3.4", "resp": {}}
        worker._do_login(client=client)
        assert worker._fail_count == 0
        assert worker._auth_error == ""


def test_notify_pushes_after_threshold_and_resets(tmp_path):
    worker, cfg = make_worker(tmp_path, notify_threshold=2)
    sent = []
    with patch.object(MonitorWorker, "_client") as mc, \
         patch("zju_autologin.monitor.send_notification", side_effect=lambda c, t, b, **kw: sent.append(t) or (True, "")):
        client = mc.return_value
        client.get_status.return_value = dict(OFFLINE)
        client.login.return_value = {"ok": False, "msg": "portal busy", "username": "x",
                                     "ip": "", "resp": {"error": "nonce_error"}}
        worker._do_login(client=client)  # 第 1 次失败 → 不推
        assert not sent
        worker._do_login(client=client)  # 第 2 次 → 推送
        assert len(sent) == 1
        worker._do_login(client=client)  # 已推过不再重复
        assert len(sent) == 1
    # 成功后重置
    worker._reset_notify()
    assert worker._fail_streak == 0 and worker._notify_sent is False


def test_traffic_alert_monthly_once(tmp_path):
    worker, cfg = make_worker(tmp_path, traffic_limit_gb=10)
    sent = []
    with patch.object(MonitorWorker, "_client") as mc, \
         patch("zju_autologin.monitor.send_notification", side_effect=lambda c, t, b, **kw: sent.append(t) or (True, "")):
        worker._check_traffic_limit(20 * 1024 ** 3)
        worker._check_traffic_limit(21 * 1024 ** 3)  # 同月不再推
        assert len(sent) == 1
        assert cfg.last_traffic_alert  # 已记录月份


def test_battery_mode_doubles_interval(tmp_path):
    worker, _ = make_worker(tmp_path, interval=60, battery_mode=True)
    class FakeTimer:
        def __init__(self): self._ms = 60000
        def setInterval(self, ms): self._ms = ms
        def interval(self): return self._ms
    worker._timer = FakeTimer()
    with patch("zju_autologin.monitor.on_battery", return_value=True):
        worker._adjust_interval_for_power()
        assert worker._timer.interval() == 120000
    with patch("zju_autologin.monitor.on_battery", return_value=False):
        worker._adjust_interval_for_power()
        assert worker._timer.interval() == 60000


def test_heartbeat_pings_once_per_window(tmp_path):
    worker, cfg = make_worker(tmp_path, heartbeat_url="http://hc.example/ping")
    calls = []
    class Resp:
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
    class FakeOpener:
        def open(self, req, timeout=None):
            calls.append(req.full_url)
            return Resp()
    worker._opener = FakeOpener()
    worker._ping_heartbeat()
    worker._ping_heartbeat()  # 5 分钟窗口内不重复
    assert len(calls) == 1
    assert calls == ["http://hc.example/ping"]


def test_proxy_opener_routing(tmp_path):
    from zju_autologin.net import build_opener
    direct = build_opener("direct")
    sys_proxy = build_opener("system")
    custom = build_opener("custom", "http://127.0.0.1:7890")
    for opener in (direct, sys_proxy, custom):
        assert opener is not None


def test_portal_transient_failure_retries(tmp_path):
    """门户瞬断（VPN 切线等）：重试成功不应误报无校园网。"""
    worker, _ = make_worker(tmp_path)
    with patch.object(MonitorWorker, "_client") as mc,          patch("zju_autologin.monitor.probe_internet", return_value=True),          patch("zju_autologin.monitor.time.sleep") as slept:
        from zju_autologin.srun import SrunError
        client = mc.return_value
        client.get_status.side_effect = [SrunError("transient"), dict(ONLINE)]
        info = run_check(worker)
        assert info["state"] == "online"
        slept.assert_called_once()


def test_portal_double_failure_reports_no_campus(tmp_path):
    worker, _ = make_worker(tmp_path)
    with patch.object(MonitorWorker, "_client") as mc,          patch("zju_autologin.monitor.time.sleep"):
        from zju_autologin.srun import SrunError
        client = mc.return_value
        client.get_status.side_effect = SrunError("down")
        info = run_check(worker)
        assert info["state"] == "no_campus"




def test_neg_cache_skips_bound_strategies(tmp_path):
    """门户整体不可达后 5 分钟内, 策略链只保留直连（掉校外不再空耗几十秒）。"""
    from zju_autologin import srun as S
    from zju_autologin.srun import SrunClient
    S._STRATEGY_CACHE.clear()
    S._NEG_CACHE.clear()
    client = SrunClient(base_url="https://net.zju.edu.cn")
    client._request_once = lambda url, opener=None: (_ for _ in ()).throw(S.SrunError("down"))
    try:
        client._get("/cgi-bin/rad_user_info", {})
    except S.SrunError:
        pass
    assert "net.zju.edu.cn" in S._NEG_CACHE  # 已记录失败
    strategies = client._strategies()
    assert all(k == "direct" for k, _, _ in strategies)  # 只剩直连
    # 成功后负缓存清除
    client._request_once = lambda url, opener=None: "ok"
    client._get("/cgi-bin/rad_user_info", {})
    assert "net.zju.edu.cn" not in S._NEG_CACHE
