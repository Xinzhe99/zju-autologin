"""v1.26.0: 校内直连(Clash 系统代理兼容) —— 例外列表的注入/记账/撤销/自愈。

用可注入的注册表读写函数测试, 不碰真实注册表。
"""

from __future__ import annotations

import pytest

from zju_autologin import campus
from zju_autologin.config import Config

pytest.importorskip("PyQt6.QtCore", reason="需要 PyQt6")


class FakeRegistry:
    """内存版 ProxyOverride/ProxyEnable/AutoConfigURL。"""

    def __init__(self, override="", proxy_enable=True, pac=""):
        self.values = {"ProxyOverride": override, "ProxyEnable": proxy_enable,
                       "AutoConfigURL": pac}
        self.writes: list[str] = []

    def read(self, name):
        return self.values.get(name)

    def write(self, value):
        self.values["ProxyOverride"] = value
        self.writes.append(value)
        return True


@pytest.fixture
def reg(monkeypatch):
    fake = FakeRegistry(override="localhost;127.*;<local>")
    monkeypatch.setattr(campus, "_read_value", fake.read)
    monkeypatch.setattr(campus, "_write_override", fake.write)
    return fake


def make_cfg(tmp_path, **kw):
    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "12434001"
    cfg.set_password("p")
    cfg.data.update(kw)
    return cfg


def test_desired_entries_derived_from_portal_and_extras(tmp_path):
    cfg = make_cfg(tmp_path, campus_bypass_extra="cc98.org, *.lib.example.edu.cn ,,")
    entries = campus.desired_entries(cfg)
    assert "*.zju.edu.cn" in entries and "zju.edu.cn" in entries
    assert "*.cc98.org" in entries and "*.lib.example.edu.cn" in entries
    assert "10.*" in entries
    assert len(entries) == len(set(entries))  # 去重


def test_apply_appends_without_touching_existing(reg, tmp_path):
    cfg = make_cfg(tmp_path)
    wrote, missing = campus.apply_bypass(cfg)
    assert wrote and "*.zju.edu.cn" in missing
    value = reg.values["ProxyOverride"]
    assert value.startswith("localhost;127.*;<local>")  # 原有条目保留在前
    assert "*.zju.edu.cn" in value and "zju.edu.cn;" in value and value.endswith("10.*")
    assert cfg.data["campus_bypass_applied"] == missing  # 记账


def test_apply_is_idempotent(reg, tmp_path):
    cfg = make_cfg(tmp_path)
    campus.apply_bypass(cfg)
    wrote, missing = campus.apply_bypass(cfg)
    assert not wrote and not missing


def test_clash_rewrite_is_healed_by_ensure(reg, tmp_path):
    """Clash 重开系统代理会整段重写例外列表 —— ensure 必须能补回。"""
    cfg = make_cfg(tmp_path, campus_direct=True)
    campus.ensure(cfg)
    assert "*.zju.edu.cn" in reg.values["ProxyOverride"]

    reg.values["ProxyOverride"] = "localhost;<local>"  # Clash 重写, 我们的条目没了
    event = campus.ensure(cfg)
    assert event == "applied"
    assert "*.zju.edu.cn" in reg.values["ProxyOverride"]


def test_disable_removes_only_our_entries(reg, tmp_path):
    cfg = make_cfg(tmp_path, campus_direct=True)
    campus.ensure(cfg)
    reg.values["ProxyOverride"] = "clash-bypass;localhost;*.zju.edu.cn;10.*"
    cfg.data["campus_direct"] = False
    event = campus.ensure(cfg)
    assert event == "removed"
    assert reg.values["ProxyOverride"] == "clash-bypass;localhost"  # 别人的原样保留
    assert cfg.data["campus_bypass_applied"] == []


def test_ensure_skips_when_proxy_off(reg, tmp_path):
    reg.values["ProxyEnable"] = False
    cfg = make_cfg(tmp_path, campus_direct=True)
    assert campus.ensure(cfg) == ""
    assert reg.values["ProxyOverride"] == "localhost;127.*;<local>"  # 未写入


def test_pac_and_tun_modes_reported(reg, tmp_path):
    reg.values["AutoConfigURL"] = "http://127.0.0.1:9999/proxy.pac"
    cfg = make_cfg(tmp_path, campus_direct=True)
    assert campus.ensure(cfg) == "pac"

    reg.values["AutoConfigURL"] = ""
    monkey_tun = pytest.MonkeyPatch()
    monkey_tun.setattr(campus, "tun_mode", lambda: True)
    try:
        assert campus.ensure(cfg) == "tun"
    finally:
        monkey_tun.undo()


def test_monitor_wires_campus_ensure(tmp_path, monkeypatch):
    """监控循环要真的调 ensure(与 _do_check 相同的入口), 且日志/记账生效。"""
    import zju_autologin.monitor as M

    fake = FakeRegistry(override="localhost")
    monkeypatch.setattr(campus, "_read_value", fake.read)
    monkeypatch.setattr(campus, "_write_override", fake.write)

    cfg = make_cfg(tmp_path, campus_direct=True)
    worker = M.MonitorWorker(cfg)
    logs = []
    worker.logLine.connect(logs.append)
    worker._ensure_campus_direct()
    # 断言条目本身而不是界面语言文案(Windows 中文/Linux 英文都要过)
    assert any("*.zju.edu.cn" in line for line in logs), logs
    assert cfg.data["campus_bypass_applied"]

    # 关掉开关 → 下一轮自动撤销
    cfg.data["campus_direct"] = False
    worker._ensure_campus_direct()
    assert fake.values["ProxyOverride"] == "localhost"
    assert len(logs) >= 2          # 撤销也记了一条日志
    assert cfg.data["campus_bypass_applied"] == []
