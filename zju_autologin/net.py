"""网络出口选择：门户认证强制直连（保活前提），其余流量按代理设置路由。

proxy_mode:
  - "system": 跟随系统代理（默认，符合 Clash/v2ray 等用户的真实上网路径）
  - "direct": 强制直连
  - "custom": 使用 proxy_url 指定的 HTTP(S) 代理（如 http://127.0.0.1:7890）
"""

from __future__ import annotations

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
