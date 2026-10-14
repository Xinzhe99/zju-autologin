"""v1.27.0: 保活与校内直连的稳定性大修。

覆盖:
- 校内直连: TUN 误判(Teredo)不再让例外失效 / 门户为 IP 或二级域名时不乱推导 /
  额外域名粘贴网址自动取主机名 / 删掉的额外域名会从例外列表清掉 / 大小写不敏感
- 监控: 更新检查失败只挂一个重试 / Clash 反复改写时日志节流 + 一次性守卫提示
- watch 守护(系统级保活): 认证被拒锁存 / 门户不可达不空打登录 / 改配置即解锁
- TUN fake-ip: 假地址不进 DNS 兜底缓存 / 有真实缓存时绕开 fake-ip
- 启动: 静默升级与开机自启不被引导向导拦住
- 向导: 自启勾选沿用当前状态(重走向导不再悄悄关掉开机自启)
- 看护: 用户主动退出后不被拉起
"""

from __future__ import annotations

import os
import re
import time

import pytest

from zju_autologin import campus
from zju_autologin.config import Config


def make_cfg(tmp_path, **kw):
    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "12434001"
    cfg.set_password("p")
    cfg.data.update(kw)
    return cfg


class FakeRegistry:
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


# ------------------------------------------------------------------ 校内直连

@pytest.mark.parametrize("name,hit", [
    ("Teredo Tunneling Pseudo-Interface", False),   # 几乎每台 Windows 都有
    ("Microsoft IP-HTTPS Platform Adapter", False),
    ("Metadata Adapter", False),
    ("Mihomo", True),
    ("Clash Meta", True),
    ("Meta", True),
    ("sing-box tun", True),
    ("utun3", True),
    ("tun0", True),
    ("wintun Userspace Tunnel", True),
])
def test_tun_name_matching_avoids_teredo(name, hit):
    assert bool(campus._TUN_NAME.search(name)) is hit


@pytest.mark.parametrize("base,expect", [
    ("https://net.zju.edu.cn", ["zju.edu.cn"]),
    ("http://10.0.0.1", []),            # 门户写成 IP: 没有域名可推导
    ("http://10.0.0.1:8080/", []),
    ("https://portal.cn", []),          # 只剩顶级域: 推导出来等于整个 .cn 绕过代理
])
def test_campus_suffix_derivation_guards(tmp_path, base, expect):
    cfg = make_cfg(tmp_path, base_url=base)
    assert campus.campus_suffixes(cfg) == expect


def test_extra_domains_accept_pasted_urls(tmp_path):
    cfg = make_cfg(tmp_path, campus_bypass_extra="https://www.CC98.org/forum, *.lib.x.edu.cn;bad entry")
    suffixes = campus.campus_suffixes(cfg)
    assert "www.cc98.org" in suffixes and "lib.x.edu.cn" in suffixes
    assert all(" " not in s for s in suffixes)


def test_removed_extra_domain_is_cleaned_up(reg, tmp_path):
    cfg = make_cfg(tmp_path, campus_direct=True, campus_bypass_extra="cc98.org")
    assert campus.ensure(cfg) == "applied"
    assert "*.cc98.org" in reg.values["ProxyOverride"]
    cfg.data["campus_bypass_extra"] = ""
    assert campus.ensure(cfg) == "applied"  # 发生了写入(清掉了过期条目)
    value = reg.values["ProxyOverride"]
    assert "cc98.org" not in value and "*.zju.edu.cn" in value
    assert value.startswith("localhost;127.*;<local>")
    assert not any("cc98" in e for e in cfg.data["campus_bypass_applied"])


def test_case_insensitive_presence(reg, tmp_path):
    reg.values["ProxyOverride"] = "localhost;*.ZJU.EDU.CN;ZJU.edu.cn;10.*"
    cfg = make_cfg(tmp_path, campus_direct=True)
    assert campus.ensure(cfg) == ""  # Clash 改了大小写也算在位, 不重复写
    assert reg.writes == []


def test_status_reports_states(reg, tmp_path, monkeypatch):
    monkeypatch.setattr(campus, "_winreg", lambda: object())
    cfg = make_cfg(tmp_path, campus_direct=True)
    assert campus.status(cfg, tun=False) == "pending"
    campus.ensure(cfg, detect_tun=False)
    assert campus.status(cfg, tun=False) == "active"
    reg.values["ProxyEnable"] = False
    assert campus.status(cfg, tun=False) == "idle"
    assert campus.status(cfg, tun=True) == "tun"
    reg.values["AutoConfigURL"] = "http://x/pac"
    assert campus.status(cfg, tun=False) == "pac"
    cfg.data["campus_direct"] = False
    assert campus.status(cfg) == "off"


# ------------------------------------------------------------------ 监控

def _worker(tmp_path, **kw):
    pytest.importorskip("PyQt6.QtCore")
    import zju_autologin.monitor as M
    cfg = make_cfg(tmp_path, **kw)
    return M, M.MonitorWorker(cfg), cfg


def test_update_retry_is_deduplicated(tmp_path, monkeypatch):
    M, worker, _ = _worker(tmp_path)
    import zju_autologin.updates as U
    scheduled = []
    monkeypatch.setattr(M.QTimer, "singleShot",
                        staticmethod(lambda ms, fn: scheduled.append(fn)))

    def fake_check(**kw):
        U.LAST_CHECK_ERROR = "HTTP 403"
        return False, "", "x"

    monkeypatch.setattr(U, "check_newer", fake_check)
    for _ in range(5):  # 每日定时检查 + 手动检查反复失败
        worker._check_updates(manual=False)
        worker._check_updates(manual=True)
    assert len(scheduled) == 1  # 同一时刻只挂一个重试
    scheduled[0]()               # 重试触发 → 失败 → 再挂一个
    assert len(scheduled) == 2


def test_campus_heal_logs_are_throttled_and_guard_hinted(tmp_path, monkeypatch):
    M, worker, cfg = _worker(tmp_path, campus_direct=True)
    fake = FakeRegistry(override="localhost")
    monkeypatch.setattr(campus, "_read_value", fake.read)
    monkeypatch.setattr(campus, "_write_override", fake.write)
    logs = []
    worker.logLine.connect(logs.append)
    for _ in range(6):  # Clash「系统代理守卫」反复整段重写
        fake.values["ProxyOverride"] = "localhost"
        worker._ensure_campus_direct(detect_tun=False)
    applied = [line for line in logs if "*.zju.edu.cn" in line and "10.*" in line]
    guard = [line for line in logs if "10 " in line or "10 minutes" in line]
    assert len(fake.writes) == 6            # 每次都补回了
    assert len(applied) <= 2                # 但日志没有刷屏
    assert len(guard) == 1                  # 守卫提示只出现一次


def test_campus_ledger_saved_only_on_change(tmp_path, monkeypatch):
    M, worker, cfg = _worker(tmp_path, campus_direct=True)
    fake = FakeRegistry(override="localhost")
    monkeypatch.setattr(campus, "_read_value", fake.read)
    monkeypatch.setattr(campus, "_write_override", fake.write)
    saves = []
    monkeypatch.setattr(cfg, "save", lambda: saves.append(1) or True)
    worker._ensure_campus_direct(detect_tun=False)
    assert len(saves) == 1
    for _ in range(3):  # 例外在位 / 被重写后补回: 记账不变, 不写盘
        worker._ensure_campus_direct(detect_tun=False)
        fake.values["ProxyOverride"] = "localhost"
    assert len(saves) == 1


def test_refresh_password_rereads_keyring(tmp_path):
    import keyring
    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "u"
    cfg.save()
    assert not cfg.get_password()
    keyring.set_password("ZJUAutoLogin", "account", "late-secret")  # 凭据服务晚就绪
    assert cfg.refresh_password() is True
    assert cfg.get_password() == "late-secret"


# ------------------------------------------------------------------ watch 守护

class _Stop(Exception):
    pass


def _run_watch(monkeypatch, cfg, client_cls, ticks):
    from zju_autologin import cli
    calls = {"n": 0}

    def fake_sleep(sec):
        calls["n"] += 1
        if calls["n"] >= ticks:
            raise _Stop

    monkeypatch.setattr(cli, "SrunClient", client_cls)
    monkeypatch.setattr(cli, "probe_internet", lambda **k: True)
    monkeypatch.setattr(cli.time, "sleep", fake_sleep)
    with pytest.raises(_Stop):
        cli.cmd_watch(cfg, 10)


def test_watch_latches_on_auth_error(tmp_path, monkeypatch):
    """密码错误不能每分钟重试一次 —— 门户可能因此锁号(GUI 早已修, 服务模式漏了)。"""
    cfg = make_cfg(tmp_path)
    logins = []

    class Client:
        def __init__(self, *a, **k):
            pass

        def get_status(self):
            return {"online": False}

        def login(self, *a, **k):
            logins.append(1)
            return {"ok": False, "msg": "E2901: ldap_bind error",
                    "resp": {"error": "E2901"}}

    _run_watch(monkeypatch, cfg, Client, ticks=8)
    assert len(logins) == 1


def test_watch_backoff_on_transient_failures(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    logins = []

    class Client:
        def __init__(self, *a, **k):
            pass

        def get_status(self):
            return {"online": False}

        def login(self, *a, **k):
            logins.append(1)
            return {"ok": False, "msg": "timeout", "resp": {}}

    _run_watch(monkeypatch, cfg, Client, ticks=8)  # 8 轮几乎同时发生: 退避生效
    assert len(logins) == 1


def test_watch_does_not_login_without_portal(tmp_path, monkeypatch):
    from zju_autologin.srun import SrunError
    cfg = make_cfg(tmp_path)
    logins = []

    class Client:
        def __init__(self, *a, **k):
            pass

        def get_status(self):
            raise SrunError("unreachable")

        def login(self, *a, **k):
            logins.append(1)
            return {"ok": False, "msg": "x", "resp": {}}

    _run_watch(monkeypatch, cfg, Client, ticks=3)
    assert logins == []
    events = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert "no_campus" in events


def test_watch_config_change_clears_latch(tmp_path, monkeypatch):
    from zju_autologin import cli
    cfg = make_cfg(tmp_path)
    cfg.password_backend = "file"
    cfg.save()
    st = cli._WatchState()
    cli._watch_reload(cfg, st)
    st.latch_msg, st.latch_until = "E2901", time.time() + 3600
    cfg.set_password("new")
    cfg.password_backend = "file"
    cfg.save()
    os.utime(cfg.path, (time.time() + 5, time.time() + 5))
    cli._watch_reload(cfg, st)
    assert st.latch_msg == ""
    assert cfg.get_password() == "new"


# ------------------------------------------------------------------ fake-ip

def _fake_getaddrinfo(ips):
    return lambda *a, **k: [("f", None, None, "", (ip, 443)) for ip in ips]


def test_fake_ip_not_cached_and_bypassed(monkeypatch):
    from zju_autologin import srun as S
    S._PORTAL_IP_CACHE.clear()
    monkeypatch.setattr(S, "_ip_cache_loaded", True)
    monkeypatch.setattr(S, "_save_ip_cache", lambda: None)
    monkeypatch.setattr(S.socket, "getaddrinfo", _fake_getaddrinfo(["198.18.0.7"]))
    ips, mode = S._resolve("net.zju.edu.cn")
    assert (ips, mode) == (["198.18.0.7"], "ok")       # 无缓存: 照常交给 TUN
    assert "net.zju.edu.cn" not in S._PORTAL_IP_CACHE  # 假地址绝不入缓存

    monkeypatch.setattr(S.socket, "getaddrinfo", _fake_getaddrinfo(["10.0.0.9"]))
    assert S._resolve("net.zju.edu.cn") == (["10.0.0.9"], "ok")
    monkeypatch.setattr(S.socket, "getaddrinfo", _fake_getaddrinfo(["198.18.0.7"]))
    assert S._resolve("net.zju.edu.cn") == (["10.0.0.9"], "fake")  # 用真实缓存绕开


def test_ip_cache_persists(monkeypatch):
    from zju_autologin import srun as S
    S._PORTAL_IP_CACHE.clear()
    monkeypatch.setattr(S.socket, "getaddrinfo", _fake_getaddrinfo(["10.3.3.3"]))
    S._resolve("portal.example.edu.cn")
    S._PORTAL_IP_CACHE.clear()
    monkeypatch.setattr(S, "_ip_cache_loaded", False)
    S._load_ip_cache()
    assert S._PORTAL_IP_CACHE.get("portal.example.edu.cn") == ["10.3.3.3"]


def test_fake_mode_falls_back_to_tun_path(monkeypatch):
    """缓存的真实 IP 钉不通时, 退回常规路径(交给 TUN), 并进入冷却期。"""
    from zju_autologin import srun as S
    monkeypatch.setattr(S, "_resolve", lambda host: (["10.9.9.9"], "fake"))
    S._PINNED_FAIL.clear()
    client = S.SrunClient(base_url="https://net.zju.edu.cn")
    pinned = []

    def boom(*a, **k):
        pinned.append(1)
        raise OSError("unreachable")

    monkeypatch.setattr(client, "_request_pinned", boom)

    class Resp:
        def read(self):
            return b"ok-body"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Opener:
        def open(self, req, timeout=None):
            return Resp()

    assert client._request_once("https://net.zju.edu.cn/x", Opener()) == "ok-body"
    assert client._request_once("https://net.zju.edu.cn/x", Opener()) == "ok-body"
    assert len(pinned) == 1  # 冷却期内不再白等超时


def test_local_ip_never_returns_tun_address(monkeypatch):
    from zju_autologin import srun as S

    class Sock:
        def __init__(self, *a):
            pass

        def settimeout(self, t):
            pass

        def connect(self, addr):
            pass

        def getsockname(self):
            return ("198.18.0.1", 5555)

        def close(self):
            pass

    monkeypatch.setattr(S.socket, "socket", Sock)
    monkeypatch.setattr(S, "candidate_source_ips", lambda: ["10.12.34.56"])
    assert S.SrunClient().get_local_ip() == "10.12.34.56"


# ------------------------------------------------------------------ 启动 / 向导 / 看护

def test_need_wizard_rules(tmp_path):
    pytest.importorskip("PyQt6.QtWidgets")
    import zju_autologin.gui as G
    cfg = make_cfg(tmp_path)
    # 已配置 + 静默升级: 不弹(以前每次应用内更新都被向导拦住)
    assert not G.need_wizard(cfg, "20261014120000-silent", True, ["x"])
    # 已配置 + 手动重装: 弹一次
    assert G.need_wizard(cfg, "20261014120000", True, ["x"])
    # 开机自启 + 有账号但密码暂缺(凭据服务晚就绪): 不弹, 保活先跑起来
    cfg2 = Config(str(tmp_path / "c2.json"))
    cfg2.username = "u"
    cfg2.forget_password()  # 测试进程内的假凭据库与 cfg 共享, 清掉
    assert not G.need_wizard(cfg2, "", False, ["x", "--minimized"])
    assert G.need_wizard(cfg2, "", False, ["x"])
    # 全新用户: 弹
    cfg3 = Config(str(tmp_path / "c3.json"))
    cfg3.forget_password()
    assert G.need_wizard(cfg3, "", False, ["x", "--minimized"])


def test_watchdog_script_respects_user_quit():
    import zju_autologin.watchdog as W
    text = W._ps_script()
    assert "gui.quit" in text
    assert re.search(r"if \(Test-Path '[^']*gui\.quit'\) \{ exit \}", text)


def test_wizard_keeps_existing_autostart(tmp_path, qapp, monkeypatch):
    import sys as _s
    if _s.platform == "darwin":
        pytest.skip("macOS runner 无窗口服务")
    from unittest.mock import patch
    from zju_autologin import autostart
    from zju_autologin.wizard import SetupWizard

    monkeypatch.setattr(autostart, "is_enabled", lambda: True)
    cfg = make_cfg(tmp_path)
    with patch("zju_autologin.wizard._DetectThread.run",
               lambda self: self.detected.emit({"portal_ok": False, "online": False,
                                                "discovered_portal": {}})):
        wz = SetupWizard(cfg)
    assert wz._chk_boot.isChecked()
    wz.done(0)

    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    fresh = Config(str(tmp_path / "fresh.json"))
    with patch("zju_autologin.wizard._DetectThread.run",
               lambda self: self.detected.emit({"portal_ok": False, "online": False,
                                                "discovered_portal": {}})):
        wz2 = SetupWizard(fresh)
    assert wz2._chk_boot.isChecked()  # 新用户默认开机自启
    wz2.done(0)


def test_tray_update_check_fires_once(tmp_path, qapp):
    import sys as _s
    if _s.platform == "darwin":
        pytest.skip("macOS runner 无窗口服务")
    from zju_autologin.monitor import Monitor
    from zju_autologin.ui import MainWindow
    cfg = make_cfg(tmp_path)
    mon = Monitor(cfg)
    hits = []
    mon.updateCheckRequested.connect(lambda: hits.append(1))
    win = MainWindow(cfg, mon)
    win._act_check_updates.trigger()
    assert hits == [1]  # 以前信号连了两次, 一次点击检查两遍
    win._tray.hide()


def test_settings_offers_service_sync(tmp_path, qapp, monkeypatch):
    import sys as _s
    if _s.platform == "darwin":
        pytest.skip("macOS runner 无窗口服务")
    from PyQt6.QtWidgets import QMessageBox
    from zju_autologin import service
    import zju_autologin.ui as U
    from zju_autologin.monitor import Monitor

    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(service, "is_installed", lambda max_age=60.0: True)
    win = U.MainWindow(cfg, Monitor(cfg))
    sw = win._settings_window
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(1) or QMessageBox.StandardButton.No))
    sw._save_settings()            # 什么都没改: 不打扰
    assert asked == []
    sw._edit_pwd.setText("new-password")
    sw._save_settings()            # 改了密码: 服务那份过期了, 必须提示同步
    assert asked == [1]
    win._tray.hide()
