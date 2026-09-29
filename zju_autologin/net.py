"""网络出口选择：门户认证强制直连（保活前提），其余流量按代理设置路由。

proxy_mode:
  - "system": 跟随系统代理（默认，符合 Clash/v2ray 等用户的真实上网路径）
  - "direct": 强制直连
  - "custom": 使用 proxy_url 指定的 HTTP(S) 代理（如 http://127.0.0.1:7890）
"""

from __future__ import annotations

import functools
import http.client
import ipaddress
import socket
import ssl
import urllib.request

PROXY_MODES = ("system", "direct", "custom")


def build_opener(proxy_mode: str = "system", proxy_url: str = "") -> urllib.request.OpenerDirector:
    if proxy_mode == "direct":
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    if proxy_mode == "custom" and proxy_url.strip():
        url = proxy_url.strip()
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": url, "https": url})
        )
    return urllib.request.build_opener()  # 跟随系统代理设置


# ---------------------------------------------------------------- 接口绑定

def candidate_source_ips() -> list[str]:
    """枚举本机候选出口 IPv4（校园网网段优先），用于源地址绑定绕过 TUN 路由。

    过滤：回环/链路本地/Clash TUN fake-ip(198.18.0.0/15)；排序：10/8 优先
    （浙大校园网网段），其次其他内网，最后公网。
    """
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    fake_pool = ipaddress.ip_network("198.18.0.0/15")
    campus_pool = ipaddress.ip_network("10.0.0.0/8")
    seen: set[str] = set()
    pools: dict[str, list[str]] = {"campus": [], "private": [], "other": []}
    for info in infos:
        ip = info[4][0]
        if ip in seen:
            continue
        seen.add(ip)
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local or addr in fake_pool:
            continue
        if addr in campus_pool:
            pools["campus"].append(ip)
        elif addr.is_private:
            pools["private"].append(ip)
        else:
            pools["other"].append(ip)
    return pools["campus"] + pools["private"] + pools["other"]


def _connect_ipv4(host, port, timeout, source_address):
    """解析目标为 IPv4 并以指定源地址建立连接。

    源地址绑定的是 IPv4 网卡, 若让 create_connection 自行解析出 IPv6 目标,
    会出现 v4 源 + v6 目标的组合并报 WSAEINVAL, 因此这里显式限定 AF_INET。
    """
    infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    last_exc: OSError | None = None
    for _, _, _, _, sa in infos:
        try:
            return socket.create_connection(sa[:2], timeout, source_address)
        except OSError as exc:
            last_exc = exc
    raise last_exc or OSError(f"cannot resolve {host!r}")


class _BoundHTTPConnection(http.client.HTTPConnection):
    """绑定源地址的 HTTP 连接（绕过 TUN 默认路由，从指定网卡直发）。"""

    def __init__(self, host, port=None, timeout=None, source_address=None):
        super().__init__(host, port, timeout=timeout)
        self._bound_source = source_address

    def connect(self):
        self.sock = _connect_ipv4(self.host, self.port, self.timeout, self._bound_source)


class _BoundHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port=None, timeout=None, source_address=None, context=None):
        super().__init__(host, port, timeout=timeout, context=context)
        self._bound_source = source_address

    def connect(self):
        sock = _connect_ipv4(self.host, self.port, self.timeout, self._bound_source)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def bound_opener(source_ip: str) -> urllib.request.OpenerDirector:
    """构造把 TCP 源地址绑定到指定网卡 IP 的 opener。"""

    class _H(urllib.request.HTTPHandler):
        def http_open(self, req):
            cls = functools.partial(
                _BoundHTTPConnection, source_address=(source_ip, 0))
            return self.do_open(cls, req)

    class _HS(urllib.request.HTTPSHandler):
        def __init__(self):
            super().__init__(context=ssl.create_default_context())

        def https_open(self, req):
            cls = functools.partial(
                _BoundHTTPSConnection,
                source_address=(source_ip, 0), context=self._context)
            return self.do_open(cls, req)

    return urllib.request.build_opener(_H(), _HS())
