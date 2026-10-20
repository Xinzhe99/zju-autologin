"""v1.29.0 回归：一键清理、更新回滚、服务自检、门户缓存共享。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from zju_autologin.config import Config


# ---------------------------------------------------------------- 一键清理

def test_reset_turns_flags_off_before_removing(tmp_path, monkeypatch):
    from zju_autologin import autostart, campus, reset, routes, service, watchdog

    cfg = Config(str(tmp_path / "c.json"))
    cfg.campus_direct = True
    cfg.portal_route_added = True
    cfg.data["campus_bypass_applied"] = ["*.zju.edu.cn"]
    cfg.autostart = True


    seen = {}

    def fake_remove(cfg):
        seen["campus_direct"] = cfg.campus_direct
        return True

    monkeypatch.setattr(campus, "remove_bypass", fake_remove)
    monkeypatch.setattr(routes, "remove_direct_routes", lambda cfg: (True, "ok"))
    monkeypatch.setattr(service, "is_installed", lambda max_age=60.0: True)
    monkeypatch.setattr(service, "uninstall", lambda: (True, "removed"))
    monkeypatch.setattr(watchdog, "is_installed", lambda: True)
    monkeypatch.setattr(watchdog, "uninstall", lambda: True)
    monkeypatch.setattr(autostart, "set_enabled", lambda on: True)
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)

    results = reset.cleanup(cfg)

    assert all(ok for _step, ok, _detail in results), results
    # 清理前必须先关开关, 否则监控 3 秒后会把例外写回去
    assert seen["campus_direct"] is False
    assert cfg.campus_direct is False
    assert cfg.portal_route_added is False
    assert cfg.portal_route_ips == []
    assert cfg.autostart is False
    saved = json.loads(Path(cfg.path).read_text(encoding="utf-8"))
    assert saved["campus_direct"] is False


def test_reset_isolates_failures(tmp_path, monkeypatch):
    from zju_autologin import autostart, campus, reset, routes, service, watchdog

    cfg = Config(str(tmp_path / "c.json"))
    monkeypatch.setattr(campus, "remove_bypass", lambda cfg: True)
    monkeypatch.setattr(routes, "remove_direct_routes", lambda cfg: (True, "ok"))
    monkeypatch.setattr(service, "is_installed", lambda max_age=60.0: False)
    monkeypatch.setattr(watchdog, "is_installed", lambda: False)
    monkeypatch.setattr(autostart, "set_enabled",
                        lambda on: (_ for _ in ()).throw(OSError("denied")))

    results = dict((step, ok) for step, ok, _ in reset.cleanup(cfg))
    assert results[reset.STEP_CAMPUS] is True
    assert results[reset.STEP_AUTOSTART] is False


# ---------------------------------------------------------------- 更新回滚

@pytest.fixture
def fake_exe(tmp_path, monkeypatch):
    from zju_autologin import update_health

    exe = tmp_path / "ZJUAutoLogin.exe"
    exe.write_bytes(b"new")
    old = tmp_path / "ZJUAutoLogin.old.exe"
    old.write_bytes(b"old")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(update_health, "_pending_path",
                        lambda: tmp_path / "update-pending.json")
    return update_health, exe, old


def test_health_attempts_grow_and_reset(fake_exe):
    update_health, exe, old = fake_exe
    update_health.prepare_update("1.28.0")
    update_health.begin_pending("1.28.0")
    assert update_health.attempts() == 1
    update_health.begin_pending("1.28.0")
    assert update_health.attempts() == 2
    assert update_health.needs_rollback() is True

    update_health.mark_healthy()
    assert update_health.attempts() == 0
    assert update_health.needs_rollback() is False
    # 健康后旧 exe 必须清理, 否则白占 40MB+
    assert not old.exists()


def test_rollback_swaps_binaries(fake_exe):
    update_health, exe, old = fake_exe
    update_health.prepare_update("1.28.0")
    update_health.begin_pending("1.28.0")
    update_health.begin_pending("1.28.0")
    assert update_health.needs_rollback() is True

    ok, detail = update_health.rollback()
    assert (ok, detail) == (True, "rolled-back")
    assert exe.read_bytes() == b"old"
    assert update_health.attempts() == 0
    assert not old.exists()


def test_no_rollback_without_old_exe(fake_exe):
    update_health, _exe, old = fake_exe
    old.unlink()
    update_health.prepare_update("")
    update_health.begin_pending("")
    update_health.begin_pending("")
    assert update_health.needs_rollback() is False


# ---------------------------------------------------------------- 服务自检

def test_ensure_running_starts_once_per_day(tmp_path, monkeypatch):
    from zju_autologin import service

    monkeypatch.setattr(service, "service_config_dir", lambda: tmp_path)
    monkeypatch.setattr(service, "is_installed", lambda max_age=60.0: True)
    monkeypatch.setattr(service, "heartbeat_age", lambda: None)
    calls = []
    monkeypatch.setattr(service, "_run_elevated_ps",
                        lambda script: calls.append(script) or (True, "ok"))

    ok, detail = service.ensure_running()
    assert (ok, detail) == (True, "started")
    assert calls and "Start-ScheduledTask" in calls[0]

    # 同一天再启动不应再次弹 UAC
    ok2, detail2 = service.ensure_running()
    assert (ok2, detail2) == (False, "needs-admin")
    assert len(calls) == 1


def test_ensure_running_noop_when_heartbeat_fresh(tmp_path, monkeypatch):
    from zju_autologin import service

    monkeypatch.setattr(service, "service_config_dir", lambda: tmp_path)
    monkeypatch.setattr(service, "is_installed", lambda max_age=60.0: True)
    monkeypatch.setattr(service, "heartbeat_age", lambda: 12.0)
    calls = []
    monkeypatch.setattr(service, "_run_elevated_ps",
                        lambda script: calls.append(script) or (True, "ok"))

    assert service.ensure_running() == (True, "running")
    assert calls == []


def test_heartbeat_age(tmp_path, monkeypatch):
    import time

    from zju_autologin import service

    monkeypatch.setattr(service, "service_config_dir", lambda: tmp_path)
    (tmp_path / "service.heartbeat").write_text(str(time.time() - 42), encoding="ascii")
    age = service.heartbeat_age()
    assert age is not None and 40 <= age <= 60


# ---------------------------------------------------------------- 门户缓存

def test_cache_dir_override(tmp_path, monkeypatch):
    import zju_autologin.srun as srun

    monkeypatch.setattr(srun, "_PORTAL_IP_CACHE", {})
    try:
        srun.set_cache_dir(tmp_path)
        srun._PORTAL_IP_CACHE["net.zju.edu.cn"] = ["10.50.254.11"]
        srun._save_ip_cache()
        assert (tmp_path / "portal_ips.json").is_file()

        srun._PORTAL_IP_CACHE.clear()
        srun._load_ip_cache()
        assert srun._PORTAL_IP_CACHE["net.zju.edu.cn"] == ["10.50.254.11"]
    finally:
        srun.set_cache_dir(None)


def test_cache_uses_programdata_when_available(tmp_path, monkeypatch):
    import zju_autologin.srun as srun

    monkeypatch.setattr(srun, "sys", type("S", (), {"platform": "win32"}))
    monkeypatch.setattr("zju_autologin.config.service_config_dir", lambda: tmp_path)
    try:
        srun.set_cache_dir(None)
        assert srun._ip_cache_path() == tmp_path / "portal_ips.json"
    finally:
        srun.set_cache_dir(None)
