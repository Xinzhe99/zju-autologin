"""v1.30.0 回归: 门户返回未知状态码时不得误判离线, 设备列表需兼容新响应形状。

背景(线上实测):
- ZJU 门户在限速状态下 rad_user_info 返回 {"error": "speed_limit_error"}。
  旧实现把它当"未认证", 于是 GUI 与服务守护每分钟各拿真实账号登录一次;
  门户回 ip_already_online_error, 下一轮又被判离线 —— events.jsonl 里
  offline/online 每 62 秒交替一次, 累计 50 次, 有触发账号锁定的风险。
- /v1/srun_portal_online 新版返回 {"code":0,"message":"Success","data":[...]},
  旧实现只认 {"error":"ok"}, 导致设备列表与 E2620 自动踢号永远为空。
"""

import json

import pytest

from zju_autologin.srun import SrunClient


def make_client(monkeypatch, body: str) -> SrunClient:
    client = SrunClient()
    monkeypatch.setattr(client, "_get", lambda path, params, **kw: body)
    return client


def _jsonp(payload: dict) -> str:
    return f"cb({json.dumps(payload)})"


SPEED_LIMITED = _jsonp({
    "client_ip": "10.92.107.70", "ecode": 0, "error": "speed_limit_error",
    "error_msg": "", "online_ip": "", "res": "speed_limit_error",
})


# ---------------------------------------------------------------- 未知状态

def test_speed_limit_is_unknown_not_offline(monkeypatch):
    """限速时门户不给在线状态: 必须标记 unknown, 不能当离线触发重登。"""
    info = make_client(monkeypatch, SPEED_LIMITED).get_status()
    assert info["online"] is False
    assert info["unknown"] is True
    assert info["portal_error"] == "speed_limit_error"


def test_unknown_does_not_relogin_with_online_host(monkeypatch):
    """unknown + 外网通 → watch 判 online, 不发起登录。"""
    from zju_autologin import cli

    client = make_client(monkeypatch, SPEED_LIMITED)
    monkeypatch.setattr(cli, "SrunClient", lambda **kw: client)
    monkeypatch.setattr(cli, "probe_internet", lambda *a, **kw: True)
    monkeypatch.setattr(client, "login", _fail("不该在 unknown 且外网通时登录"))

    state = cli._watch_tick(_cfg(), cli._WatchState(), lambda line, dedupe=True: None)
    assert state == "online"


def test_unknown_without_internet_still_logs_in(monkeypatch):
    """unknown 且外网不通 → 关闭登录通道会让人再也连不上: 必须照常重登。"""
    from zju_autologin import cli

    client = make_client(monkeypatch, SPEED_LIMITED)
    calls = []

    def login(*a, **kw):
        calls.append(1)
        return {"ok": True, "msg": "ok", "resp": {"error": "ok"}}

    monkeypatch.setattr(cli, "SrunClient", lambda **kw: client)
    monkeypatch.setattr(cli, "probe_internet", lambda *a, **kw: False)
    monkeypatch.setattr(client, "login", login)

    state = cli._watch_tick(_cfg(), cli._WatchState(), lambda line, dedupe=True: None)
    assert state == "online" and calls


def test_explicit_offline_stays_offline(monkeypatch):
    """明确的 not_online_error 仍是离线(不能因为新加的 unknown 变成保守放行)。"""
    info = make_client(monkeypatch, _jsonp({"error": "not_online_error"})).get_status()
    assert info["online"] is False
    assert info.get("unknown") is False


def test_check_exits_zero_when_unknown_but_online(monkeypatch, capsys):
    from zju_autologin import cli

    client = make_client(monkeypatch, SPEED_LIMITED)
    monkeypatch.setattr(cli, "SrunClient", lambda **kw: client)
    monkeypatch.setattr(cli, "probe_internet", lambda *a, **kw: True)
    assert cli.cmd_check(_cfg()) == 0
    assert "在线" in capsys.readouterr().out


# ---------------------------------------------------------------- 设备列表

DEVICES = {
    "code": 0, "message": "Success",
    "data": [
        {"add_time": "2026-10-20 13:45:01", "client_type": "1", "ip": "10.92.107.70",
         "os_name": "Windows 10", "user_name": "12434001"},
        {"add_time": "2026-10-21 20:14:16", "client_type": "2", "ip": "10.92.203.244",
         "os_name": "iPhone", "user_name": "12434001"},
    ],
}


def test_device_list_parses_code_response(monkeypatch):
    """新版 {"code":0,...} 形状必须能解析出来, 否则踢号功能静默失效。"""
    devices = make_client(monkeypatch, _jsonp(DEVICES)).list_online_devices("12434001", "pw")
    assert [d["ip"] for d in devices] == ["10.92.107.70", "10.92.203.244"]
    assert devices[0]["os_name"] == "Windows 10"
    # 字符串时间要转成排序用的纪元秒, 否则 min(add_time) 会抛 TypeError
    assert devices[0]["add_time"] < devices[1]["add_time"] > 0


def test_device_list_accepts_legacy_error_ok(monkeypatch):
    legacy = {"error": "ok", "data": [{"ip": "1.2.3.4", "add_time": 1700000000}]}
    devices = make_client(monkeypatch, _jsonp(legacy)).list_online_devices("u", "pw")
    assert devices and devices[0]["add_time"] == 1700000000


def test_device_list_rejects_error_response(monkeypatch):
    bad = {"code": 1, "message": "fail", "data": []}
    assert make_client(monkeypatch, _jsonp(bad)).list_online_devices("u", "pw") == []


# ---------------------------------------------------------------- 辅助

def _cfg():
    from zju_autologin.config import Config

    cfg = Config.__new__(Config)
    cfg.data = {"username": "12434001", "base_url": "https://net.zju.edu.cn", "ac_id": "80",
                "interval": 60, "auto_login": True, "password_backend": "none",
                "domain": "", "notify_provider": "none", "campus_direct": False,
                "proxy_mode": "system", "proxy_url": "", "check_updates": False}
    cfg.path = "config.json"
    cfg.password_backend = "none"
    cfg._plain_password = "pw"
    cfg._load_failed = False
    cfg.refresh_password = lambda: True
    cfg.get_password = lambda: "pw"
    cfg.username = "12434001"
    cfg.domain = ""
    cfg.base_url = "https://net.zju.edu.cn"
    cfg.ac_id = "80"
    cfg.interval = 60
    return cfg


def _fail(message: str):
    def _raise(*a, **kw):
        raise AssertionError(message)
    return _raise


# ---------------------------------------------------------------- 守护进程不带 Qt

def test_watch_entry_does_not_import_qt():
    """系统级保活入口不得把 PyQt6 拉进守护进程。

    历史问题: gui.main() 在顶层 import QApplication/MainWindow, watch 分支
    在 import 之后才分流, 于是无界面的 SYSTEM 守护也常驻了整套 Qt 运行时。
    """
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(root)!r});"
        "import zju_autologin.gui;"          # 守护模式走的入口模块
        "import zju_autologin.runtime;"
        "import zju_autologin.cli;"
        "print([m for m in sys.modules if m.startswith('PyQt6')])"
    )
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, timeout=120, check=False)
    assert out.returncode == 0, out.stderr[-800:]
    assert out.stdout.strip() == "[]", f"watch 入口加载了 Qt: {out.stdout.strip()}"


# ---------------------------------------------------------------- 配置读不出来时拒绝

def test_check_refuses_unreadable_config(monkeypatch, capsys):
    """配置读不出来时不能拿空配置继续跑并打印 [ok]。"""
    from zju_autologin import cli

    cfg = _cfg()
    cfg._load_failed = True
    cfg.path = "C:/ProgramData/ZJUAutoLogin/config.json"
    monkeypatch.setattr(cli, "SrunClient",
                        lambda **kw: pytest.fail("不该在配置不可读时访问门户"))

    assert cli.cmd_check(cfg) == 2
    err = capsys.readouterr().err
    assert "无法读取配置文件" in err


def test_login_refuses_unreadable_config(monkeypatch, capsys):
    from zju_autologin import cli

    cfg = _cfg()
    cfg._load_failed = True
    cfg.path = "/etc/zju-autologin/config.json"
    monkeypatch.setattr(cli, "SrunClient",
                        lambda **kw: pytest.fail("不该在配置不可读时尝试登录"))

    assert cli.cmd_login(cfg) == 2
    assert "无法读取配置文件" in capsys.readouterr().err


# ---------------------------------------------------------------- 配置导入

_KEEPALIVE: list = []


def _settings_window(tmp_path, monkeypatch):
    """构建一个只用于导入逻辑的 SettingsWindow(离屏, 沙箱配置)。"""
    pytest.importorskip("PyQt6.QtWidgets")
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    from zju_autologin.config import Config
    from zju_autologin.monitor import Monitor
    from zju_autologin.ui import MainWindow, SettingsWindow

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"username": "u", "base_url": "https://net.zju.edu.cn",
                                "notify_key": "", "proxy_url": ""}), encoding="utf-8")
    cfg = Config(str(path))
    mon = Monitor(cfg)
    mon.config_updated = lambda: None
    mon.check_once = lambda: None
    win = MainWindow(cfg, mon)
    sw = SettingsWindow(cfg, mon, win)
    # 必须持有引用: 局部变量出栈后 Qt 会销毁 C++ 对象, 再调方法就 RuntimeError
    _KEEPALIVE.extend([app, win, sw, mon])
    return sw, cfg


def test_import_own_export_skips_sensitive_prompt(tmp_path, monkeypatch):
    """导入自身导出的备份(敏感键被剔除)不该弹安全确认。"""
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    sw, cfg = _settings_window(tmp_path, monkeypatch)
    payload = {"username": "u2", "interval": 120, "_exported_by": "ZJU-AutoLogin v0"}
    src = tmp_path / "backup.json"
    src.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(src), "")))
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: (asked.append(1),
                                                      QMessageBox.StandardButton.Yes)[1]))
    sw._import_config()
    assert asked == [], "导入不含敏感键的备份不应要求确认"
    assert cfg.interval == 120


def test_import_sensitive_change_still_prompts(tmp_path, monkeypatch):
    """文件里真的改了 base_url 时必须确认(防凭据被重定向)。"""
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    sw, cfg = _settings_window(tmp_path, monkeypatch)
    src = tmp_path / "evil.json"
    src.write_text(json.dumps({"base_url": "https://evil.example.com"}), encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(src), "")))
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: (asked.append(1),
                                                      QMessageBox.StandardButton.No)[1]))
    sw._import_config()
    assert asked, "敏感字段变更必须询问"
    assert cfg.base_url == "https://net.zju.edu.cn"
