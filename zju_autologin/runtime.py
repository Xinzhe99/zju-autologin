"""运行期单例锁与进程级状态的共享位（避免循环导入）。"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QLockFile

app_lock: Optional[QLockFile] = None
