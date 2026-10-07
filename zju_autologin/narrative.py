"""掉线叙事回放: 把 events.jsonl 讲成人话。

"14:03 网络环境变化 → 14:03 认证失效 → 14:04 自动重登成功, 中断 8 秒"
"""

from __future__ import annotations

import time

from .config import read_events
from .i18n import tr

# 最后一条事件超过这个时长就认为"已经不在掉线状态"(程序可能关了几天)
_STILL_DOWN_WINDOW = 30 * 60


def _describe(event: str, detail: str) -> str:
    mapping = {
        "online": tr("nar.online"),
        "offline": tr("nar.offline"),
        "no_campus": tr("nar.no_campus"),
        "auth_error": tr("nar.auth_error"),
        "login_fail": tr("nar.login_fail"),
        "need_config": tr("nar.need_config"),
        "authed_no_internet": tr("nar.authed_no_internet"),
        "checking": tr("nar.checking"),
    }
    base = mapping.get(event, event)
    if detail and detail not in base:
        return f"{base}（{detail}）"
    return base


def build_narrative(limit: int = 40) -> str:
    """把最近事件编译成可读故事。"""
    events = read_events(limit * 2)
    if not events:
        return tr("nar.empty")
    lines = []
    prev_online: bool | None = None
    outage_start: float | None = None
    last_ts = 0.0
    for e in events:
        event = str(e.get("event", ""))
        ts = float(e.get("ts") or 0)
        last_ts = max(last_ts, ts)
        stamp = time.strftime("%m-%d %H:%M:%S", time.localtime(ts))
        if event in ("online", "authed_no_internet"):
            if outage_start is not None:
                secs = int(ts - outage_start)
                lines.append(tr("nar.recovered", secs=secs))
                outage_start = None
            prev_online = True
        elif event in ("offline", "no_campus", "login_fail") and prev_online is not False:
            outage_start = ts
            prev_online = False
        lines.append(f"{stamp} {_describe(event, str(e.get('detail', ''))[:60])}")
    if outage_start is not None:
        # 只在"确实还在掉线"时才说还在掉: 程序关了一周再打开, 文件最后一条仍是
        # offline, 原样输出会宣称"已持续掉线 168 小时", 而网络其实早好了
        if time.time() - last_ts <= _STILL_DOWN_WINDOW:
            secs = int(time.time() - outage_start)
            lines.append(tr("nar.still_down", secs=secs))
    # 输出最近 N 行
    return chr(10).join(lines[-limit:])
