"""GitHub Releases 更新检查（轻量，失败静默）。"""

from __future__ import annotations

import json
import re
import urllib.request

from . import __version__

REPO_API = "https://api.github.com/repos/Xinzhe99/zju-autologin/releases/latest"
RELEASE_PAGE = "https://github.com/Xinzhe99/zju-autologin/releases/latest"


def _version_tuple(v: str) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", v or "")]
    if not nums:
        return (0,)
    # 补齐到 4 段: 否则 (1,15) < (1,15,0) 成立, 且四段版本号第 4 位被截断漏报
    return tuple((nums + [0, 0, 0, 0])[:4])


def check_newer(timeout: float = 5.0, opener: urllib.request.OpenerDirector | None = None) -> tuple[bool, str, str]:
    """检查是否有新版本，返回 (是否有新版, 最新版本号, 下载页链接)。失败静默。"""
    try:
        req = urllib.request.Request(
            REPO_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "ZJU-AutoLogin"},
        )
        if opener is None:
            opener = urllib.request.build_opener()
        with opener.open(req, timeout=timeout) as resp:
            data = json.load(resp)
        tag = str(data.get("tag_name") or "").lstrip("vV")
        url = str(data.get("html_url") or RELEASE_PAGE)
        if tag and _version_tuple(tag) > _version_tuple(__version__):
            return True, tag, url
    except Exception:  # noqa: BLE001 - 无网/限流时静默跳过
        pass
    return False, "", RELEASE_PAGE
