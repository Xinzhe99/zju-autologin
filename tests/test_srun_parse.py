"""srun 协议解析边界用例：不访问网络，纯解析逻辑。"""

import json

from zju_autologin import srun as S
from zju_autologin.srun import SrunClient, SrunError

TEXT_ONLINE = "3230104321,1789652994,1790584648,13486503943,10642704885,0,3596264953420,77983090,192.0.2.10,0,,0,0,0,0,0,0,0,0,0,0,1.01.20260624"
JSON_ONLINE = json.dumps({
    "error": "ok", "user_name": "3230104321", "user_ip": "192.0.2.10",
    "online_ip": "192.0.2.10", "add_time": 1789652994, "all_bytes": 24139097390,
})
JSON_OFFLINE = json.dumps({"error": "not_online_error", "error_msg": ""})


def make_client(monkeypatch, body: str) -> SrunClient:
    client = SrunClient()
    monkeypatch.setattr(client, "_get", lambda path, params: body)
    return client


def test_status_text_online(monkeypatch):
    info = make_client(monkeypatch, TEXT_ONLINE).get_status()
    assert info["online"] and info["username"] == "3230104321"
    assert info["ip"] == "192.0.2.10"
    assert "2026" in info["login_time"]


def test_status_text_offline(monkeypatch):
    info = make_client(monkeypatch, "not_online_error").get_status()
    assert not info["online"]


def test_status_json_online(monkeypatch):
    info = make_client(monkeypatch, f"cb1({JSON_ONLINE})").get_status()
    assert info["online"] and info["username"] == "3230104321"


def test_status_json_offline(monkeypatch):
    info = make_client(monkeypatch, f"cb1({JSON_OFFLINE})").get_status()
    assert not info["online"]


def test_status_garbage(monkeypatch):
    info = make_client(monkeypatch, "<html>gateway error</html>").get_status()
    assert not info["online"]  # 坏包按未在线处理，不抛异常


def test_status_short_fields(monkeypatch):
    info = make_client(monkeypatch, "a,b,c").get_status()
    assert not info["online"]


def test_parse_jsonp_variants():
    assert S._parse_jsonp('cb({"a":1})') == {"a": 1}
    assert S._parse_jsonp('  {"a":2}  ') == {"a": 2}
    assert S._parse_jsonp('cb({"a":1})') ["a"] == 1


def test_parse_jsonp_bad():
    import pytest
    with pytest.raises(SrunError):
        S._parse_jsonp("not json at all")


def test_ac_id_resolution_direct():
    assert SrunClient(ac_id="99").resolve_ac_id() == "99"


def test_ac_id_auto_caches_probe(monkeypatch):
    client = SrunClient(ac_id="auto")
    calls = []
    monkeypatch.setattr(client, "detect_portal_ac_id", lambda: calls.append(1) or "42")
    assert client.resolve_ac_id() == "42"
    assert client.resolve_ac_id() == "42"  # 第二次走缓存
    assert len(calls) == 1


def test_parse_portal_config_follows_login_link(monkeypatch):
    client = SrunClient()
    index = 'location.href="./srun_portal_pc?ac_id=77&theme=xx"'
    page = 'var CONFIG = { acid : "77", ip : "10.1.2.3" };'

    def fake_get(path, params):
        if "srun_portal_pc" in path:
            return page
        return index

    monkeypatch.setattr(client, "_get", fake_get)
    cfg = client.parse_portal_config()
    assert cfg["acid"] == "77"
    assert cfg["ip"] == "10.1.2.3"


def test_friendly_error_empty():
    assert S.friendly_error({}) == "unknown" or S.friendly_error({}) != ""
