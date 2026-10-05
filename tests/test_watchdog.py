"""看护任务更新竞态(v1.25.2 更新失败事故): 心跳缺失导致看护任务无条件拉起,
安装器覆写 exe 中途被启动 → Failed to load Python DLL。回归守卫:
1. GUI 必须真正写心跳(修复前 touch_alive 无任何调用方)
2. 更新拉起安装器前必须先写暂停标记
3. 看护脚本必须双条件判断(心跳新鲜 或 暂停未过期 → 不拉起)
"""

from pathlib import Path
import sys

import pytest
from PyQt6.QtWidgets import QApplication

import zju_autologin.watchdog as W


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def wd_env(tmp_path, monkeypatch):
    """看护模块指向临时配置目录, 并视为已启用(frozen+win32)。"""
    monkeypatch.setattr(W, "_enabled", lambda: True)
    import zju_autologin.config as cfgmod
    monkeypatch.setattr(cfgmod, "config_dir", lambda: tmp_path)
    return tmp_path


def test_touch_alive_writes_marker(wd_env):
    W.touch_alive()
    assert (wd_env / "gui.alive").is_file()


def test_pause_resume_cycle(wd_env):
    W.pause_for_update()
    assert (wd_env / "watchdog.pause").is_file()
    W.resume()
    assert not (wd_env / "watchdog.pause").exists()


def test_ps_script_double_guard(wd_env, monkeypatch):
    """脚本必须: 两标记都查、双阈值、且只有「不新鲜且未暂停」才拉起。"""
    monkeypatch.setattr("sys.executable", r"C:\app\ZJUAutoLogin.exe")
    ps = W._ps_script()
    assert "gui.alive" in ps and "watchdog.pause" in ps
    assert "-le 10" in ps              # 心跳过期阈值
    assert "-le 15" in ps              # 暂停标记 TTL
    assert "if (-not $f -and -not $u)" in ps
    assert "--minimized" in ps and r"C:\app\ZJUAutoLogin.exe" in ps


def test_update_pauses_watchdog_before_launch(qapp, tmp_path, monkeypatch):
    """更新流程: 暂停看护必须发生在拉起安装器之前(顺序守卫)。"""
    from zju_autologin.config import Config
    from zju_autologin.monitor import Monitor
    from zju_autologin.ui import MainWindow

    order: list[str] = []
    monkeypatch.setattr("zju_autologin.watchdog.pause_for_update",
                        lambda: order.append("pause"))
    import subprocess

    def spy_popen(args, *a, **kw):
        order.append("popen")
        raise OSError("blocked by test")

    cfg = Config(str(tmp_path / "cfg.json"))
    cfg.load()
    win = MainWindow(cfg, Monitor(cfg))
    # 只观测更新流程本身(初始化阶段可能有无关的网络探测 Popen)
    order.clear()
    monkeypatch.setattr(subprocess, "Popen", spy_popen)
    win._update_downloaded(str(tmp_path / "ZJUAutoLogin-9.9.9-windows-setup.exe"))
    assert order and order[0] == "pause"      # 暂停必须最先发生
    if sys.platform == "win32":
        assert order[1] == "popen"            # 且在拉起安装器之前


def test_gui_wires_alive_heartbeat():
    """MainWindow 必须接线: 启动恢复+心跳, 周期 touch(修复前无人调用)。"""
    src = (Path(__file__).resolve().parent.parent / "zju_autologin" / "ui.py")
    text = src.read_text(encoding="utf-8")
    assert "watchdog.resume()" in text
    assert "watchdog.touch_alive()" in text
    assert "_alive_timer" in text
    assert "watchdog.pause_for_update()" in text
