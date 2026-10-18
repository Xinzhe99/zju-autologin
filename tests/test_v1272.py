"""v1.27.2 回归测试：数据安全 / serve / 网络状态机 / watch / 设置页。"""
from __future__ import annotations

import io
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

import pytest

from zju_autologin.config import Config, _DEFAULTS, read_events


def make_cfg(tmp_path, name="config.json", **kw):
    cfg = Config(str(tmp_path / name))
    cfg.username = "3230104321"
    cfg.set_password("test-pass")
    cfg.data["notify_provider"] = "none"
    cfg.data.update(kw)
    return cfg


# ------------------------------------------------------------------ 配置安全

def test_unreadable_config_keeps_values_and_refuses_save(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(str(path))
    cfg.username = "12434001"
    cfg.password_backend = "file"
    cfg._plain_password = "secret"
    assert cfg.save()
    before = path.read_text(encoding="utf-8")

    real_open = open

    def deny(p, *a, **k):
        if str(p) == str(path):
            raise PermissionError("locked by antivirus")
        return real_open(p, *a, **k)

    with patch("builtins.open", deny):
        cfg.load()
        assert cfg._load_failed
        assert cfg.username == "12434001"      # 内存旧值保留
        assert cfg.get_password() == "secret"
        assert cfg.save() is False             # 锁定期间拒绝覆盖
        assert path.read_text(encoding="utf-8") == before

        # 新建实例遇到不可读文件: 也不能把空配置写回去
        fresh = Config(str(path))
        assert fresh._load_failed
        assert fresh.save() is False
        assert path.read_text(encoding="utf-8") == before

    # 文件恢复可读后, 下一次保存先重新加载, 用户无需重启
    assert cfg.save() is True
    assert json.loads(path.read_text(encoding="utf-8"))["username"] == "12434001"


def test_defaults_are_deep_copied():
    base = list(_DEFAULTS["campus_bypass_applied"])
    cfg = Config()
    cfg.data["campus_bypass_applied"].append("*.evil.cn")
    assert _DEFAULTS["campus_bypass_applied"] == base
    other = Config()
    assert other.data["campus_bypass_applied"] == base


def test_read_events_uses_requested_directory(tmp_path):
    from zju_autologin import config as C
    d = tmp_path / "svc"
    d.mkdir()
    C.append_event("offline", "svc-only", d)
    assert any(e.get("detail") == "svc-only" for e in read_events(50, d))


# ------------------------------------------------------------------ serve

def _serve(cfg, token):
    from zju_autologin.webui import ThreadingHTTPServer, make_handler
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cfg, token))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _get(url, data=None):
    req = urllib.request.Request(url, data=data)
    return urllib.request.urlopen(req, timeout=10)


def test_webui_requires_token_and_validates(tmp_path):
    from zju_autologin import webui as W
    from zju_autologin import i18n
    i18n.set_lang("zh-CN")
    cfg = Config(str(tmp_path / "c.json"))
    srv = _serve(cfg, "tok")
    port = srv.server_port
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"http://127.0.0.1:{port}/")
        assert exc.value.code == 403

        with _get(f"http://127.0.0.1:{port}/?t=tok") as r:
            html = r.read().decode()
        assert "当前配置文件" in html and "必填" in html

        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"http://127.0.0.1:{port}/save", b"username=x")
        assert exc.value.code == 403

        base = {"token": "tok", "domain": "", "base_url": ""}
        with patch.object(W.SrunClient, "get_status", return_value={"online": False}):
            body = urllib.parse.urlencode({**base, "username": "", "password": "x"}).encode()
            with _get(f"http://127.0.0.1:{port}/save", body) as r:
                assert "请输入学号" in r.read().decode()

            body = urllib.parse.urlencode({**base, "username": "u1", "password": ""}).encode()
            with _get(f"http://127.0.0.1:{port}/save", body) as r:
                assert "首次配置必须输入密码" in r.read().decode()

            body = urllib.parse.urlencode({**base, "username": "u1", "password": "pw"}).encode()
            with _get(f"http://127.0.0.1:{port}/save", body) as r:
                assert "已保存" in r.read().decode()
        assert cfg.username == "u1" and cfg.get_password() == "pw"

        # 写盘失败必须如实报错, 不能显示"已保存"
        with patch.object(W.SrunClient, "get_status", return_value={"online": False}), \
             patch.object(type(cfg), "save", return_value=False):
            body = urllib.parse.urlencode({**base, "username": "u2", "password": "pw"}).encode()
            with _get(f"http://127.0.0.1:{port}/save", body) as r:
                assert "保存失败" in r.read().decode()
        assert cfg.username == "u1" or cfg.username == "u2"  # 内存可改, 但页面必须报错
    finally:
        srv.shutdown()
        srv.server_close()


def test_webui_empty_body_does_not_wipe_account(tmp_path):
    from zju_autologin.webui import ThreadingHTTPServer, make_handler
    from zju_autologin import i18n
    i18n.set_lang("zh-CN")
    cfg = make_cfg(tmp_path, name="c2.json")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cfg, "tok"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with _get(f"http://127.0.0.1:{srv.server_port}/save?t=tok", b"") as r:
            assert "请输入学号" in r.read().decode()
        assert cfg.username == "3230104321"
    finally:
        srv.shutdown()
        srv.server_close()


def test_cli_config_prefers_service_when_installed(tmp_path, monkeypatch):
    import zju_autologin.service as service
    from zju_autologin import cli
    svc_dir = tmp_path / "svc"
    svc_dir.mkdir()
    svc_cfg = Config(str(svc_dir / "config.json"))
    svc_cfg.username = "svc-user"
    svc_cfg.save()
    monkeypatch.setattr(service, "is_installed", lambda max_age=60.0: True)
    monkeypatch.setattr(cli, "service_config_dir", lambda: svc_dir)
    cfg = cli._load_cli_config()
    assert cfg.path == str(svc_dir / "config.json")
    assert cfg.username == "svc-user"
    explicit = cli._load_cli_config(str(tmp_path / "other.json"))
    assert explicit.path == str(tmp_path / "other.json")


# ------------------------------------------------------------------ CLI

def test_cli_arg_errors():
    from zju_autologin import cli
    assert cli._parse_args(["check", "--bogus"])[3]
    assert cli._parse_args(["check", "--config"])[3]
    assert cli._parse_args(["watch", "30"]) == ("watch", 30, None, None)


def test_cli_help_exit_zero(monkeypatch, capsys):
    from zju_autologin import cli
    monkeypatch.setattr(sys, "argv", ["zju-autologin", "--help"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower() or "用法" in out


# ------------------------------------------------------------------ 网络

def test_resolve_treats_any_oserror_as_dns_down(monkeypatch):
    from zju_autologin import srun as S
    S._PORTAL_IP_CACHE.pop("net.zju.edu.cn", None)
    monkeypatch.setattr(S, "_load_ip_cache", lambda: None)
    with patch.object(socket, "getaddrinfo", side_effect=OSError("getaddrinfo failed: transient")):
        ips, mode = S._resolve("net.zju.edu.cn")
    assert ips == [] and mode == "down"


def test_auth_rejected_uses_error_message(monkeypatch):
    from zju_autologin import srun as S
    from zju_autologin import i18n
    i18n.set_lang("zh-CN")
    assert S.is_auth_rejected({"error": "E2901"})
    assert S.is_auth_rejected({"error": "E9999", "error_msg": "password_error"})
    assert not S.is_auth_rejected({"error": "INFO failed, BAS respond timeout."})


def test_pinned_http400_body_returned_without_cooldown(monkeypatch):
    from zju_autologin import srun as S

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"error":"E2901"}'

    class Opener:
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(
                "https://net.zju.edu.cn/x", 400, "bad", {}, io.BytesIO(b'{"error":"E2901"}'))

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: Opener())
    client = S.SrunClient()
    body = client._request_pinned("https://net.zju.edu.cn/x", "net.zju.edu.cn",
                                  ["10.50.254.11"], {}, None)
    assert "E2901" in body


def test_pinned_cooldown_is_per_source_ip(monkeypatch):
    from zju_autologin import srun as S
    S._PINNED_FAIL.clear()
    S._PORTAL_IP_CACHE["net.zju.edu.cn"] = ["10.50.254.11"]
    client = S.SrunClient(base_url="https://net.zju.edu.cn")
    attempts = []

    def pin(url, host, ips, headers, source_ip):
        attempts.append(source_ip)
        if source_ip is None:
            raise OSError("direct pinned blocked")
        return '{"error":"ok"}'

    monkeypatch.setattr(client, "_request_pinned", pin)
    monkeypatch.setattr(S, "_resolve", lambda host: (["198.18.0.5"], "fake"))

    class BadDirect:
        zju_source_ip = None

        def open(self, req, timeout=None):
            raise OSError("direct blocked")

    class Bind:
        zju_source_ip = "10.5.6.7"

        def open(self, req, timeout=None):
            raise OSError("fallback blocked")

    with pytest.raises(S.SrunError):
        client._request_once("https://net.zju.edu.cn/x", BadDirect())
    # 第一路只冷却 (host, "")，绑源地址这一路仍必须尝试钉 IP
    assert S._PINNED_FAIL.get(("net.zju.edu.cn", ""))
    body = client._request_once("https://net.zju.edu.cn/x", Bind())
    assert body == '{"error":"ok"}'
    assert attempts == [None, "10.5.6.7"]


# ------------------------------------------------------------------ watch

def _watch_cfg(tmp_path):
    cfg = make_cfg(tmp_path, name="watch.json")
    cfg.password_backend = "file"
    cfg.save()
    return cfg


def test_watch_retries_transient_and_latches_message_only_error(tmp_path, monkeypatch):
    from zju_autologin import cli
    cfg = _watch_cfg(tmp_path)
    st = cli._WatchState()

    class Client:
        def __init__(self, *a, **k):
            self.logins = 0

        def get_status(self):
            return {"online": False}

        def login(self, *a, **k):
            self.logins += 1
            if self.logins == 1:
                return {"ok": False, "msg": "busy",
                        "resp": {"error": "INFO failed, BAS respond timeout."}}
            return {"ok": True, "msg": "ok", "resp": {}}

    client = Client()
    monkeypatch.setattr(cli, "SrunClient", lambda *a, **k: client)
    monkeypatch.setattr(cli, "probe_internet", lambda **k: True)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    assert cli._watch_tick(cfg, st, lambda *a, **k: None) == "online"
    assert client.logins == 2

    class Bad:
        def __init__(self, *a, **k):
            pass

        def get_status(self):
            return {"online": False}

        def login(self, *a, **k):
            return {"ok": False, "msg": "自定义错误",
                    "resp": {"error": "E9999", "error_msg": "password_error"}}

    monkeypatch.setattr(cli, "SrunClient", Bad)
    st2 = cli._WatchState()
    assert cli._watch_tick(cfg, st2, lambda *a, **k: None) == "auth_error"
    assert st2.latch_msg


def test_watch_refreshes_late_keyring_password(tmp_path, monkeypatch):
    import keyring
    from zju_autologin import cli
    cfg = make_cfg(tmp_path, name="watch2.json")
    cfg.password_backend = "keyring"
    cfg._plain_password = ""
    keyring.set_password("ZJUAutoLogin", "account", "late-pass")
    seen = []

    class Client:
        def __init__(self, *a, **k):
            pass

        def get_status(self):
            return {"online": False}

        def login(self, username, password, domain=""):
            seen.append(password)
            return {"ok": True, "msg": "ok", "resp": {}}

    monkeypatch.setattr(cli, "SrunClient", Client)
    monkeypatch.setattr(cli, "probe_internet", lambda **k: True)
    st = cli._WatchState()
    assert cli._watch_tick(cfg, st, lambda *a, **k: None) == "online"
    assert seen == ["late-pass"]


# ------------------------------------------------------------------ campus

def test_extra_domain_port_and_ip_entries(tmp_path):
    from zju_autologin import campus
    cfg = make_cfg(tmp_path, name="campus.json", campus_bypass_extra="cc98.org:8080, 10.1.2.3/24")
    suffixes = campus.campus_suffixes(cfg)
    assert "cc98.org" in suffixes
    entries = campus.desired_entries(cfg)
    assert "10.1.2.3" in entries
    assert not any(e.startswith("*.") and e.split("*.", 1)[1][0].isdigit() for e in entries)
    assert not any(":" in e for e in entries)


def test_campus_status_prefers_tun_and_remove_failure(tmp_path, monkeypatch):
    from zju_autologin import campus
    cfg = make_cfg(tmp_path, name="c2.json", campus_direct=True)
    monkeypatch.setattr(campus, "_winreg", lambda: object())
    monkeypatch.setattr(campus, "pac_mode", lambda: False)
    monkeypatch.setattr(campus, "proxy_enabled", lambda: True)
    monkeypatch.setattr(campus, "tun_mode", lambda: True)
    monkeypatch.setattr(campus, "_read_value", lambda n: ";".join(campus.desired_entries(cfg)))
    assert campus.status(cfg) == "tun"

    cfg.data["campus_direct"] = False
    cfg.data["campus_bypass_applied"] = ["*.zju.edu.cn", "zju.edu.cn", "10.*"]
    monkeypatch.setattr(campus, "_write_override", lambda v: False)
    assert campus.ensure(cfg) == "remove_failed"
    assert cfg.data["campus_bypass_applied"]


# ------------------------------------------------------------------ monitor

def test_monitor_survives_non_srun_dns_oserror(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6.QtCore")
    import zju_autologin.monitor as M
    worker = M.MonitorWorker(make_cfg(tmp_path, name="mon.json"))
    emitted = []
    worker.statusChanged.connect(emitted.append)
    monkeypatch.setattr(M.SrunClient, "get_status",
                        lambda self: (_ for _ in ()).throw(OSError("getaddrinfo failed")))
    monkeypatch.setattr(M, "probe_internet", lambda **k: True)
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    worker._do_check(manual=False)
    assert emitted and emitted[-1]["state"] == "no_campus"


def test_monitor_latched_ecode_survives_next_tick(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6.QtCore")
    import zju_autologin.monitor as M
    worker = M.MonitorWorker(make_cfg(tmp_path, name="mon2.json"))
    worker._auth_error = "设备超限"
    worker._auth_ecode = "E2620"
    emitted = []
    worker.statusChanged.connect(emitted.append)
    monkeypatch.setattr(M.SrunClient, "get_status", lambda self: {"online": False, "raw": ""})
    worker._do_check(manual=False)
    assert emitted[-1]["state"] == "auth_error"
    assert emitted[-1]["ecode"] == "E2620"


# ------------------------------------------------------------------ diag

def test_diag_report_masks_account(tmp_path):
    from zju_autologin import diag
    cfg = make_cfg(tmp_path, name="diag.json", username="12434001")
    fake = {"portal_ok": True, "online": True, "username": "12434001",
            "ip": "10.92.1.2", "login_time": "2026-10-18 10:00",
            "latency_ms": 12, "raw": ""}
    with patch.object(diag.SrunClient, "get_status", return_value=fake), \
         patch("zju_autologin.net.probe_internet", return_value=True):
        report = diag.format_report(cfg)
    assert "12434001" not in report
    assert "12***1" in report


# ------------------------------------------------------------------ GUI

def _gui_cfg(tmp_path, **kw):
    cfg = Config(str(tmp_path / "gui.json"))
    cfg.username = "3230104321"
    cfg.set_password("old-pass")
    cfg.data["notify_provider"] = "none"
    cfg.data.update(kw)
    cfg.save()
    return cfg


@pytest.fixture
def gui(tmp_path, qapp, monkeypatch):
    pytest.importorskip("PyQt6.QtWidgets")
    if sys.platform == "darwin":
        pytest.skip("macOS runner 无窗口服务")
    import zju_autologin.service as service
    import zju_autologin.watchdog as watchdog
    import zju_autologin.autostart as autostart
    monkeypatch.setattr(service, "is_installed", lambda max_age=60.0: False)
    monkeypatch.setattr(service, "install", lambda cfg: (False, "cancelled"))
    monkeypatch.setattr(service, "uninstall", lambda: (False, "cancelled"))
    monkeypatch.setattr(watchdog, "resume", lambda: None)
    monkeypatch.setattr(watchdog, "touch_alive", lambda: None)
    monkeypatch.setattr(watchdog, "mark_user_quit", lambda: None)
    monkeypatch.setattr(watchdog, "refresh_if_installed", lambda: False)
    monkeypatch.setattr(watchdog, "install", lambda: False)
    monkeypatch.setattr(watchdog, "uninstall", lambda: False)
    monkeypatch.setattr(autostart, "is_enabled", lambda: True)
    monkeypatch.setattr(autostart, "set_enabled", lambda e: e)
    from zju_autologin.monitor import Monitor
    from zju_autologin.ui import MainWindow
    cfg = _gui_cfg(tmp_path)
    mon = Monitor(cfg)
    win = MainWindow(cfg, mon)
    win._tray.hide()
    win._settings_window.show()
    qapp.processEvents()
    yield win, cfg, mon, qapp
    win._tray.hide()
    win._settings_window.hide()


def test_settings_enter_saves_instead_of_reconfig(gui):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    win, cfg, mon, app = gui
    sw = win._settings_window
    saved, reconfig = [], []
    orig_save = cfg.save
    cfg.save = lambda: saved.append(1) or True
    win._start_reconfig = lambda: reconfig.append(1)
    sw._edit_pwd.setFocus()
    QTest.keyClick(sw._edit_pwd, Qt.Key.Key_Return)
    app.processEvents()
    assert saved and not reconfig


def test_settings_rejects_empty_username(gui):
    win, cfg, mon, app = gui
    sw = win._settings_window
    from zju_autologin import i18n
    i18n.set_lang("zh-CN")
    sw._edit_user.setText("")
    sw._edit_pwd.clear()
    sw._save_settings()
    assert "请输入学号" in sw._save_hint.text()
    assert cfg.username == "3230104321"


def test_campus_toggle_shows_unsaved_state(gui):
    win, cfg, mon, app = gui
    if sys.platform != "win32":
        pytest.skip("校内直连仅 Windows")
    from zju_autologin import i18n
    i18n.set_lang("zh-CN")
    sw = win._settings_window
    cfg.data["campus_direct"] = False
    sw._load_settings_into_ui()
    assert "未保存" not in sw._campus_status.text()
    mon._campus_state = "off"
    sw._chk_campus.setChecked(True)
    app.processEvents()
    assert "未保存" in sw._campus_status.text()


def test_notify_test_uses_current_inputs(gui, monkeypatch):
    win, cfg, mon, app = gui
    sw = win._settings_window
    captured = []
    monkeypatch.setattr(mon, "notify_test", lambda overrides=None: captured.append(dict(overrides or {})))
    sw._combo_provider.setCurrentIndex(sw._combo_provider.findData("dingtalk"))
    sw._edit_key.setText("https://example.invalid/hook")
    sw._btn_notify_test.click()
    assert captured and captured[0]["notify_key"] == "https://example.invalid/hook"


def test_device_button_survives_latched_auth_error(gui):
    win, cfg, mon, app = gui
    win._on_status({"state": "auth_error", "detail": "E2620", "ecode": "E2620"})
    win._on_status({"state": "auth_error", "detail": "E2620", "ecode": "E2620"})
    assert not win._btn_devices.isHidden()


def test_close_to_quit_marks_watchdog(gui, monkeypatch):
    win, cfg, mon, app = gui
    marked = []
    import zju_autologin.watchdog as watchdog
    monkeypatch.setattr(watchdog, "mark_user_quit", lambda: marked.append(1))
    cfg.minimize_to_tray = False

    class Ev:
        def accept(self):
            pass

        def ignore(self):
            pass

    win.closeEvent(Ev())
    assert marked == [1]


def test_watchdog_not_installed_when_service_fails(gui, monkeypatch):
    win, cfg, mon, app = gui
    import zju_autologin.watchdog as watchdog
    installed = []
    monkeypatch.setattr(watchdog, "install", lambda: installed.append(1) or True)
    sw = win._settings_window
    sw._apply_service_toggle(True)
    for _ in range(200):
        app.processEvents()
        if not sw._service_busy:
            break
        time.sleep(0.01)
    assert installed == []


def test_package_resources_present():
    from zju_autologin.config import resource_path
    path = resource_path("zju.ico")
    assert os.path.isfile(path)
    assert "zju_autologin" in path.replace("\\", "/")
