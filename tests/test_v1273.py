"""v1.27.3 回归测试：安装版更新后的可靠重启（PyInstaller onefile 解包竞态）。"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_relaunch_script_waits_for_installer_then_delays():
    from zju_autologin import ui
    text = ui._relaunch_script()
    assert "Get-Process -Id $InstallerPid" in text
    assert "Start-Sleep -Seconds 8" in text
    assert "Start-Process -FilePath $Exe" in text
    assert "'--minimized'" in text
    assert "Remove-Item -LiteralPath $PSCommandPath" in text


def test_schedule_relaunch_spawns_detached_helper(monkeypatch):
    from zju_autologin import ui
    calls = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(ui.subprocess, "Popen", FakePopen)
    script = ui._schedule_relaunch_after(
        4321, r"C:\Users\me\AppData\Local\Programs\ZJUAutoLogin\ZJUAutoLogin.exe",
        minimized=True)
    try:
        assert calls, "必须启动 relaunch helper"
        args, kwargs = calls[0]
        assert args[0] == "powershell"
        assert "-File" in args and script in args
        assert str(4321) in args
        assert args[-1] == "min"
        assert kwargs.get("creationflags", 0) & subprocess.CREATE_NO_WINDOW
        text = Path(script).read_text(encoding="utf-8-sig")
        assert "Start-Sleep -Seconds 8" in text
    finally:
        try:
            os.unlink(script)
        except OSError:
            pass


def test_installer_delays_silent_relaunch_without_restarting_apps():
    text = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert "RestartApplications=no" in text
    assert "CloseApplications=no" in text
    # 静默更新由安装器侧延迟 helper 拉起（兼容旧版本应用发起的更新）
    assert "update-relaunch.ps1" in text
    assert "Start-Sleep -Seconds 12" in text
    assert r'Filename: "{app}\ZJUAutoLogin.exe"; Flags: nowait runasoriginaluser skipifnotsilent' not in text
    assert "skipifsilent" in text


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell syntax check")
def test_relaunch_script_is_valid_powershell(tmp_path):
    from zju_autologin import ui
    p = tmp_path / "relaunch.ps1"
    p.write_text(ui._relaunch_script(), encoding="utf-8-sig")
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"[void][ScriptBlock]::Create((Get-Content -Raw '{p}'))"],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
