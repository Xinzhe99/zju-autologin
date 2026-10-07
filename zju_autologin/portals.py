"""社区共建的深澜门户预设加载（zju_autologin/portals.json）。"""

from __future__ import annotations

import json
import os
import sys


def load_portals() -> list[dict]:
    """读取内置预设; 解析失败返回空列表(向导仍可手填)。"""
    candidates = []
    base = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(base, "portals.json"))
    if getattr(sys, "frozen", False):  # PyInstaller
        candidates.append(os.path.join(sys._MEIPASS, "zju_autologin", "portals.json"))  # noqa: SLF001
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                # 根节点不是对象(截断/坏合并后的合法 JSON)时 data.get 会
                # AttributeError 逸出, 违背"解析失败返回空列表"的约定
                continue
            portals = data.get("portals")
            if isinstance(portals, list):
                return [p for p in portals if isinstance(p, dict) and p.get("base_url")]
        except (OSError, ValueError, AttributeError):
            continue
    return []
