"""配置读写与字段规范化测试。"""

import json

from zju_autologin.config import Config


def test_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(path=str(path))
    cfg.username = " 3230104321 "
    cfg.domain = "cmcc"
    cfg.interval = 5            # 低于下限，应被夹到 10
    cfg.data["traffic_limit_gb"] = 80
    cfg.set_password("pwd-1")
    cfg.password_backend = "file"  # 测试环境直接用文件后端
    cfg.save()

    cfg2 = Config(path=str(path))
    assert cfg2.username == "3230104321"
    assert cfg2.domain == "@cmcc"
    assert cfg2.interval == 10
    assert cfg2.get_password() == "pwd-1"
    assert cfg2.traffic_limit_gb == 80


def test_defaults_and_clamps(tmp_path):
    cfg = Config(path=str(tmp_path / "c.json"))
    assert cfg.base_url == "https://net.zju.edu.cn"
    assert cfg.ac_id == "80"
    assert cfg.language == "auto"
    assert cfg.theme == "auto"
    cfg.interval = 99999
    assert cfg.interval == 600
    cfg.notify_threshold = 0
    assert cfg.notify_threshold == 1


def test_password_file_backend(tmp_path):
    path = tmp_path / "c.json"
    cfg = Config(path=str(path))
    cfg.set_password("secret")
    cfg.password_backend = "file"
    cfg.save()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "password" not in raw  # 明文绝不落盘
    cfg2 = Config(path=str(path))
    cfg2.password_backend = "file"
    cfg2.load()
    assert cfg2.get_password() == "secret"
