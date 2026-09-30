"""Linux 桌面覆盖测试: XDG 自启 / GUI 入口 / pkexec 提权脚本（mock, 不触真实系统）。"""

import sys

import zju_autologin.autostart as autostart
import zju_autologin.service as service


def _linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")


def test_xdg_desktop_entry_content(monkeypatch):
    _linux(monkeypatch)
    entry = autostart._xdg_desktop_entry()
    assert entry.startswith("[Desktop Entry]")
    assert "Type=Application" in entry
    assert "--minimized" in entry          # 自启收进托盘
    assert "Terminal=false" in entry


def test_xdg_autostart_enable_disable(monkeypatch, tmp_path):
    _linux(monkeypatch)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    assert autostart.set_enabled(True) is True   # 返回结果状态
    p = tmp_path / "autostart" / "zju-autologin.desktop"
    assert p.exists()
    assert "[Desktop Entry]" in p.read_text(encoding="utf-8")
    assert autostart.set_enabled(False) is False  # 关闭后返回 False(结果状态)
    assert not p.exists()


def test_gui_entry_importable():
    from zju_autologin import gui
    assert callable(gui.main)


def test_pkexec_script_content(monkeypatch, tmp_path):
    """非 root 安装: 生成的提权脚本只做搬运+systemctl, 不含密码。"""
    _linux(monkeypatch)
    monkeypatch.setattr(service.os, "geteuid", lambda: 1000, raising=False)
    # 让 write_service_config 落到临时目录
    monkeypatch.setattr(service, "service_config_dir", lambda: tmp_path)
    from zju_autologin.config import _DEFAULTS
    holder = type("C", (), {"data": dict(_DEFAULTS), "get_password": lambda s: "x"})()
    holder.data["username"] = "3230104321"  # 守卫要求非空凭据
    runs = {}

    def fake_elev(script):
        runs["s"] = script
        return True, "ok"

    monkeypatch.setattr(service, "_linux_elevated_sh", fake_elev)
    monkeypatch.setattr(service, "is_installed", lambda max_age=0: True)
    ok, _ = service._install_linux(holder)
    assert ok
    script = runs["s"]
    assert "systemctl enable --now" in script
    assert "x" != script  # 密码不出现在脚本
    assert "chmod 600" in script


def test_linux_unit_exec_uses_cli_module(monkeypatch):
    _linux(monkeypatch)
    unit = service._systemd_unit("/etc/zju-autologin/config.json")
    assert "zju_autologin.cli" in unit   # GUI 无关的 watch 守护
    assert "Restart=always" in unit
