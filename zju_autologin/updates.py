"""GitHub Releases 更新检查（轻量）。

检查失败不再无声无息: 原因记入 LAST_CHECK_ERROR, 由调用方决定提示与重试节奏。
(以前失败被静默吞掉, 用户要白等 24 小时才发现为什么一直没有更新提示。)
"""

from __future__ import annotations

import json
import re
import urllib.request

from . import __version__

REPO_API = "https://api.github.com/repos/Xinzhe99/zju-autologin/releases/latest"
RELEASE_PAGE = "https://github.com/Xinzhe99/zju-autologin/releases/latest"

# 最近一次检查失败的原因("" = 成功)
LAST_CHECK_ERROR = ""


def _version_tuple(v: str) -> tuple:
    nums = [int(x) for x in re.findall(r"\d+", v or "")]
    if not nums:
        return (0,)
    # 补齐到 4 段: 否则 (1,15) < (1,15,0) 成立, 且四段版本号第 4 位被截断漏报
    return tuple((nums + [0, 0, 0, 0])[:4])


def check_newer(timeout: float = 5.0, opener: urllib.request.OpenerDirector | None = None) -> tuple[bool, str, str]:
    """检查是否有新版本，返回 (是否有新版, 最新版本号, 下载页链接)。失败静默。"""
    global LAST_CHECK_ERROR
    LAST_CHECK_ERROR = ""
    try:
        req = urllib.request.Request(
            REPO_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "ZJU-AutoLogin"},
        )
        if opener is None:
            opener = urllib.request.build_opener()
        with opener.open(req, timeout=timeout) as resp:
            data = json.load(resp)
        tag_raw = str(data.get("tag_name") or "")
        if "-" in tag_raw:  # 预发布(v1.2.4-beta.1)不作为更新目标
            return False, "", RELEASE_PAGE
        tag = tag_raw.lstrip("vV")
        url = str(data.get("html_url") or RELEASE_PAGE)
        if tag and _version_tuple(tag) > _version_tuple(__version__):
            return True, tag, url
    except Exception as exc:  # noqa: BLE001 - 网络失败转成可读原因
        LAST_CHECK_ERROR = str(exc)[:120]
    return False, "", RELEASE_PAGE
