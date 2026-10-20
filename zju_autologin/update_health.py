"""启动健康检查与自更新回滚（仅用于应用内原地更新）。

问题：就地更新把旧 exe 改名为 `.old.exe`，新进程启动后 gui.py 会立刻删掉它。
如果新版本能启动但主窗口/监控很快崩溃，用户既没有旧版本可退，也可能再也
打不开界面——远程机器尤其致命。

做法：
- **只有应用内原地更新**才调用 `prepare_update()` 写入 armed 标记。
- 新版本启动时 `begin_pending()` 只在 armed 状态下累计启动次数。
- 窗口与首轮检测稳定 60 秒后 `mark_healthy()` 清除标记与 `.old.exe`。
- armed 且连续两次启动都没达到健康状态 → `needs_rollback()` 为真，
  由 gui.py 换回 `.old.exe`。

普通安装包更新（registry 版本号变化）不写 armed 标记，因此永远不会误回滚。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PENDING_NAME = "update-pending.json"
FAIL_LIMIT = 2


def _pending_path():
    from .config import config_dir

    return config_dir() / PENDING_NAME


def _old_exe() -> Path:
    return Path(sys.executable).with_suffix(".old.exe")


def _read() -> dict:
    try:
        data = json.loads(_pending_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(state: dict) -> None:
    try:
        path = _pending_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def prepare_update(previous_version: str = "") -> None:
    """应用内原地更新前调用：置 armed 标记并清零计数。"""
    if not getattr(sys, "frozen", False):
        return
    _write({"exe": str(sys.executable), "previous": previous_version,
            "attempts": 0, "armed": True, "since": time.time()})


def is_tracking() -> bool:
    """当前是否处于一次应用内更新的观察期。"""
    state = _read()
    return bool(state.get("armed")) and state.get("exe") == str(sys.executable)


def begin_pending(previous_version: str = "") -> None:
    """新版本每次启动调用一次；只有处于观察期时才累计次数。"""
    if not getattr(sys, "frozen", False):
        return
    state = _read()
    if not state.get("armed") or state.get("exe") != str(sys.executable):
        return
    from . import __version__

    state.update({
        "version": __version__,
        "attempts": int(state.get("attempts") or 0) + 1,
        "since": time.time(),
    })
    if previous_version:
        state["previous"] = previous_version
    _write(state)


def attempts() -> int:
    state = _read()
    try:
        return int(state.get("attempts") or 0)
    except (TypeError, ValueError):
        return 0


def needs_rollback() -> bool:
    """观察期内连续多次启动都未达到健康状态，且旧 exe 仍在。"""
    return is_tracking() and attempts() >= FAIL_LIMIT and _old_exe().is_file()


def mark_healthy() -> None:
    """界面与首轮检测稳定：本次更新视为成功，清理标记与旧 exe。"""
    if not is_tracking():
        return  # 普通启动不碰任何回滚状态
    try:
        _pending_path().unlink(missing_ok=True)
    except OSError:
        pass
    # 旧版本已无用途: 不删会一直占着 40MB+, 下次更新也会先删它
    for path in (_old_exe(), Path(sys.executable).with_suffix(".failed.exe")):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def rollback() -> tuple[bool, str]:
    """把 `.old.exe` 换回当前 exe（下次启动即回到旧版本）。"""
    cur = Path(sys.executable)
    old = _old_exe()
    if not old.is_file():
        return False, "no-old-exe"
    failed_attempts = attempts()
    try:
        backup = cur.with_suffix(".failed.exe")
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass
        os.replace(cur, backup)
        try:
            os.replace(old, cur)
        except OSError:
            os.replace(backup, cur)
            raise
    except OSError as exc:
        return False, str(exc)
    mark_healthy()
    from .config import append_file_log

    try:
        append_file_log(
            f"update health check failed {failed_attempts}x; "
            "rolled back to previous build")
    except Exception:  # noqa: BLE001 - 回滚日志失败不影响结果
        pass
    return True, "rolled-back"
