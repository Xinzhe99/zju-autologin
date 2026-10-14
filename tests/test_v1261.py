"""v1.26.1: 手动检查更新 + 失败不再静默 24 小时。"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from zju_autologin.config import Config

pytest.importorskip("PyQt6.QtCore", reason="需要 PyQt6")

import zju_autologin.monitor as M  # noqa: E402
import zju_autologin.updates as U  # noqa: E402


class FakeResp:
    def __init__(self, obj):
        self._b = json.dumps(obj).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, obj=None, exc=None):
        self._obj, self._exc = obj, exc

    def open(self, req, timeout=None):
        if self._exc is not None:
            raise self._exc
        return FakeResp(self._obj)


def make_worker(tmp_path, **kw):
    cfg = Config(str(tmp_path / "c.json"))
    cfg.username = "u"
    cfg.set_password("p")
    cfg.data["notify_provider"] = "none"
    cfg.data.update(kw)
    return M.MonitorWorker(cfg), cfg


# ------------------------------------------------- updates.py 的失败可观测性

def test_failed_check_sets_last_error(monkeypatch):
    monkeypatch.setattr(U.urllib.request, "build_opener",
                        lambda *a, **k: FakeOpener(exc=OSError("HTTP 403")))
    newer, version, url = U.check_newer()
    assert newer is False
    assert U.LAST_CHECK_ERROR == "HTTP 403"


def test_successful_check_clears_last_error(monkeypatch):
    monkeypatch.setattr(U.urllib.request, "build_opener",
                        lambda *a, **k: FakeOpener(obj={"tag_name": "v0.0.1"}))
    U.LAST_CHECK_ERROR = "stale"
    newer, version, url = U.check_newer()
    assert newer is False
    assert U.LAST_CHECK_ERROR == ""


# ------------------------------------------------- 监控侧的提示与重试

def test_manual_check_reports_latest(tmp_path, monkeypatch):
    """手动检查: 已是最新也要给出明确结果, 而不是无声无息。"""
    worker, _ = make_worker(tmp_path, check_updates=False)  # 关自动检查也能手动查

    def fake_check(**kw):
        U.LAST_CHECK_ERROR = ""
        return False, "", "http://x"

    logs = []
    worker.logLine.connect(logs.append)
    monkeypatch.setattr(U, "check_newer", fake_check)
    worker._check_updates(manual=True)
    assert any("v" + M.__version__ in line for line in logs), logs


def test_manual_check_reports_failure(tmp_path, monkeypatch):
    worker, _ = make_worker(tmp_path, check_updates=False)
    scheduled = []
    monkeypatch.setattr(M.QTimer, "singleShot",
                        staticmethod(lambda ms, fn: scheduled.append(ms)))

    def fake_check(**kw):
        U.LAST_CHECK_ERROR = "HTTP 403"
        return False, "", "http://x"

    logs = []
    worker.logLine.connect(logs.append)
    monkeypatch.setattr(U, "check_newer", fake_check)
    worker._check_updates(manual=True)
    assert any("HTTP 403" in line for line in logs), logs
    assert scheduled == [3600 * 1000]  # 1 小时后重试


def test_auto_check_failure_logged_once_only(tmp_path, monkeypatch):
    """自动模式失败只记一次(之后每小时重试但不刷屏)。"""
    worker, _ = make_worker(tmp_path)
    scheduled = []
    monkeypatch.setattr(M.QTimer, "singleShot",
                        staticmethod(lambda ms, fn: scheduled.append(ms)))

    def fake_check(**kw):
        U.LAST_CHECK_ERROR = "HTTP 403"
        return False, "", "http://x"

    logs = []
    worker.logLine.connect(logs.append)
    monkeypatch.setattr(U, "check_newer", fake_check)
    worker._check_updates(manual=False)
    worker._check_updates(manual=False)
    fails = [line for line in logs if "HTTP 403" in line]
    assert len(fails) == 1, logs


def test_update_found_resets_fail_log(tmp_path, monkeypatch):
    worker, _ = make_worker(tmp_path)
    worker._update_fail_logged = True

    def fake_check(**kw):
        U.LAST_CHECK_ERROR = ""
        return True, "9.9.9", "http://x"

    monkeypatch.setattr(U, "check_newer", fake_check)
    with patch.object(M.MonitorWorker, "updateAvailable") as sig:
        worker._check_updates(manual=False)
    assert worker._update_fail_logged is False
    sig.emit.assert_called_once()


def test_manual_check_works_even_when_auto_disabled(tmp_path):
    """关掉自动检查的用户仍可手动检查(以前直接 return)。"""
    worker, cfg = make_worker(tmp_path, check_updates=False)
    assert cfg.check_updates is False
    with patch("zju_autologin.updates.check_newer",
               return_value=(False, "", "http://x")) as cn, \
         patch.object(U, "LAST_CHECK_ERROR", ""):
        worker._check_updates(manual=True)
    assert cn.called
