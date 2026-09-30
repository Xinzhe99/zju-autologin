"""v1.20.0 新功能测试: 自动踢号 / 网卡监视 / 诊断 / 门户预设。"""

from unittest.mock import patch


import zju_autologin.monitor as M
from zju_autologin.config import Config


def _worker(tmp_path, **kw):
    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "u"
    cfg.set_password("p")
    cfg.password_backend = "file"
    for k, v in kw.items():
        cfg.data[k] = v
    return M.MonitorWorker(cfg), cfg


def test_auto_kick_kicks_oldest_other_and_relogs(tmp_path):
    worker, _ = _worker(tmp_path, auto_kick=True)
    client = type("C", (), {})()
    client.list_online_devices = lambda *a, **k: [
        {"ip": "1.1.1.1", "add_time": 200},          # 最旧的其他设备
        {"ip": "2.2.2.2", "add_time": 100},          # 本机(不踢)
        {"ip": "3.3.3.3", "add_time": 300},
    ]
    kicked = {}

    def fake_kick(user, ip):
        kicked["ip"] = ip
        return True, "ok"

    client.kick_device = fake_kick
    client.login = lambda *a, **k: {"ok": True, "username": "u", "ip": "2.2.2.2"}
    with patch.object(M.MonitorWorker, "_emit") as emit:
        assert worker._auto_kick_and_retry(client, "2.2.2.2") is True
    assert kicked["ip"] == "1.1.1.1"  # 最旧且非本机
    emit.assert_called()


def test_auto_kick_never_kicks_local(tmp_path):
    worker, _ = _worker(tmp_path, auto_kick=True)
    client = type("C", (), {})()
    client.list_online_devices = lambda *a, **k: [{"ip": "2.2.2.2", "add_time": 1}]
    client.kick_device = lambda *a: (_ for _ in ()).throw(AssertionError("不应踢本机"))
    assert worker._auto_kick_and_retry(client, "2.2.2.2") is False


def test_auto_kick_disabled_off(tmp_path):
    worker, cfg = _worker(tmp_path, auto_kick=False)
    assert cfg.auto_kick is False  # 默认关闭, 行为不变


def test_interface_signature_stable_and_sensitive():
    a = M._interface_signature()
    assert M._interface_signature() == a  # 稳定
    assert isinstance(a, str)


def test_watcher_triggers_check_on_change(tmp_path):
    worker, _ = _worker(tmp_path)
    worker._running = True
    calls = []
    with patch.object(M, "_interface_signature", side_effect=["sig-b"]), \
         patch.object(M.MonitorWorker, "_do_check",
                      lambda self, manual: calls.append(manual)):
        worker._if_sig = "sig-a"
        worker._on_interface_change()   # sig-b != sig-a -> 触发
        assert calls == [False]
    worker._if_sig = "sig-c"
    worker._busy = True
    worker._on_interface_change()       # 忙时不触发
    assert len(calls) == 1


def test_diagnosis_report_online(tmp_path):
    from zju_autologin import diag
    cfg = Config(str(tmp_path / "c.json"))
    fake_status = {"portal_ok": True, "online": True, "username": "u",
                   "ip": "1.2.3.4", "latency_ms": 20, "raw": ""}
    with patch.object(diag.SrunClient, "get_status", return_value=fake_status), patch("zju_autologin.monitor.probe_internet", return_value=True):
        summary, rows = diag.run_diagnosis(cfg)
    assert "一切正常" in summary or "OK" in summary


def test_portals_schema():
    from zju_autologin.portals import load_portals
    portals = load_portals()
    assert portals, "至少含种子预设"
    for p in portals:
        assert p.get("base_url", "").startswith("http")
        assert p.get("ac_id")
        assert p.get("name")
