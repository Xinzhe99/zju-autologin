"""运行期单例锁与进程级状态的共享位（避免循环导入）。

刻意不在顶层 import PyQt6: 系统级保活(watch)走的是同一入口模块, 那条路径
不需要图形栈。持有锁的一方(GUI)自己从 _qt() 取类型。
"""

from __future__ import annotations

from typing import Any

app_lock: Any | None = None
