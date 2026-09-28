"""门户直连路由的脚本生成与 IP 过滤测试（不触网络/不提权）。"""

import socket
from unittest.mock import patch

from zju_autologin import routes


def test_portal_ips_filters_private():
    fake = [(socket.AF_INET, None, None, None, ("210.32.1.1", 0)),
            (socket.AF_INET, None, None, None, ("10.92.1.1", 0)),
            (socket.AF_INET, None, None, None, ("127.0.0.1", 0))]
    with patch.object(socket, "getaddrinfo", return_value=fake):
        assert routes.portal_ips("https://net.zju.edu.cn") == ["210.32.1.1"]


def test_portal_ips_dns_fail():
    with patch.object(socket, "getaddrinfo", side_effect=socket.gaierror):
        assert routes.portal_ips("https://x.example") == []


def test_route_script_add():
    s = routes.route_script(["210.32.1.1"])
    assert "New-NetRoute" in s and "'210.32.1.1/32'" in s
    assert "PersistentStore" in s
    assert "notmatch" in s  # 排除虚拟网卡


def test_route_script_remove():
    s = routes.route_script(["210.32.1.1"], remove=True)
    assert "Remove-NetRoute" in s and "New-NetRoute" not in s


def test_candidate_source_ips_filters_fakeip(monkeypatch):
    from zju_autologin.net import candidate_source_ips
    fake = [(socket.AF_INET, None, None, None, ("10.92.107.70", 0)),
            (socket.AF_INET, None, None, None, ("198.18.0.1", 0)),
            (socket.AF_INET, None, None, None, ("127.0.0.1", 0)),
            (socket.AF_INET, None, None, None, ("169.254.9.9", 0))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: fake)
    assert candidate_source_ips() == ["10.92.107.70"]
