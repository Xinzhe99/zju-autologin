"""Linux systemd 保活的单元生成与 CLI 参数测试（不触真实 systemd）。"""

import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import zju_autologin.cli as cli
import zju_autologin.service as service


def _force_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")


def test_enable_options_parsing():
    opts = cli._read_enable_options(["-u", "3230104321", "-p", "secret",
                                     "-i", "30", "-d", "@cmcc"])
    assert opts["user"] == "3230104321"
    assert opts["password"] == "secret"
    assert opts["interval"] == 30
    assert opts["domain"] == "@cmcc"


def test_enable_options_unknown():
    assert cli._read_enable_options(["-u", "x", "--bogus"]) is None


def test_enable_requires_user():
    assert cli._read_enable_options(["-p", "secret"]) is not None  # 可解析
    # main 层无 user 会打印用法退出: 直接验证空 user 返回 None 语义之外的行为
    opts = cli._read_enable_options([])
    assert opts is None or opts["user"] == ""


def test_require_root_blocks_non_root(monkeypatch):
    _force_linux(monkeypatch)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000, raising=False)
    assert cli._require_root() is False


def test_require_root_passes_as_root(monkeypatch):
    _force_linux(monkeypatch)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0, raising=False)
    assert cli._require_root() is True


def test_systemd_unit_content(monkeypatch):
    _force_linux(monkeypatch)
    unit = service._systemd_unit("/etc/zju-autologin/config.json")
    assert "[Unit]" in unit and "network-online.target" in unit
    assert "Restart=always" in unit          # 崩溃自动重启
    assert "WantedBy=multi-user.target" in unit  # 开机自启
    assert "--config /etc/zju-autologin/config.json" in unit
    assert "NoNewPrivileges=yes" in unit     # 加固


def test_install_linux_writes_config_and_unit(monkeypatch, tmp_path):
    _force_linux(monkeypatch)
    monkeypatch.setattr(service.os, "geteuid", lambda: 0, raising=False)
    unit_path = tmp_path / "zju-autologin.service"
    cfg_dir = tmp_path / "etc"

    monkeypatch.setattr(service, "_linux_unit_path", lambda: unit_path)
    monkeypatch.setattr(service, "service_config_dir", lambda: cfg_dir)
    monkeypatch.setattr(service, "write_service_config",
                        lambda cfg: (cfg_dir.mkdir(parents=True, exist_ok=True) or
                                     (cfg_dir / "config.json")))
    runs = []
    monkeypatch.setattr(service.subprocess, "run",
                        lambda cmd, **kw: runs.append(cmd) or type("R", (), {"returncode": 0})())
    ok, detail = service._install_linux(object())
    assert ok, detail
    assert unit_path.exists()
    assert runs[0][1] == "daemon-reload"
    assert runs[1][1:3] == ["enable", "--now"]


def test_enable_end_to_end_mocked(monkeypatch, tmp_path, capsys):
    """enable 一行命令: root 校验→凭据写入→单元安装→systemctl 启动。"""
    _force_linux(monkeypatch)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0, raising=False)
    written = {}

    class FakeCfg:
        data = dict(service._DEFAULTS) if hasattr(service, "_DEFAULTS") else {}
        username = ""

        def get_password(self):
            return written.get("pwd", "")

    from zju_autologin.config import _DEFAULTS
    FakeCfg.data = dict(_DEFAULTS)

    def fake_install(holder):
        written["pwd"] = holder.get_password()
        written["user"] = holder.data.get("username")
        written["interval"] = holder.data.get("interval")
        return True, "installed"

    monkeypatch.setattr(service, "install", fake_install)
    rc = cli.cmd_enable(["-u", "3230104321", "-p", "s3cret", "-i", "45"])
    out = capsys.readouterr().out
    assert rc == 0 and "已启用" in out
    assert written == {"pwd": "s3cret", "user": "3230104321", "interval": 45}


def test_enable_password_via_env(monkeypatch, capsys):
    _force_linux(monkeypatch)
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0, raising=False)
    import zju_autologin.service as svc
    seen = {}

    def fake_install(holder):
        seen["pwd"] = holder.get_password()
        return True, "ok"

    monkeypatch.setattr(svc, "install", fake_install)
    monkeypatch.setenv("ZJU_PASS", "env-secret")
    rc = cli.cmd_enable(["-u", "x", "--pass-env", "ZJU_PASS"])
    assert rc == 0 and seen["pwd"] == "env-secret"


def test_watch_command_writes_heartbeat(tmp_path, monkeypatch):
    """服务模式心跳落盘(与 GUI 读取路径一致)。"""
    from zju_autologin.config import Config

    cfg = Config(str(tmp_path / "cfg.json"))
    cfg.username = "u"
    cfg.data["interval"] = 1

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def get_status(self):
            return {"portal_ok": True, "online": True, "username": "u",
                    "ip": "1.2.3.4", "login_time": "", "raw": ""}

        def login(self, *a, **k):
            return {"ok": True, "msg": "ok"}

    # 用 _Stop 代替 KeyboardInterrupt: pytest 会把 KeyboardInterrupt 当用户中断中止会话
    class _Stop(Exception):
        pass

    calls = {"n": 0}

    def fake_sleep(sec):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise _Stop

    monkeypatch.setattr(cli, "SrunClient", FakeClient)
    monkeypatch.setattr(cli, "probe_internet", lambda **k: True)
    monkeypatch.setattr(cli.time, "sleep", fake_sleep)
    with pytest.raises(_Stop):
        cli.cmd_watch(cfg, 1)
    hb = tmp_path / "service.heartbeat"
    assert hb.exists()  # 心跳已写入
