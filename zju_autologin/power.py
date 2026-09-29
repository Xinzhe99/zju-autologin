"""电源状态检测（笔记本电池智能降频用）。"""

from __future__ import annotations

import glob
import sys


def on_battery() -> bool:
    """是否使用电池供电；无法判断时返回 False（视作插电）。"""
    if sys.platform == "win32":
        try:
            import ctypes

            class POWER_STATUS(ctypes.Structure):
                _fields_ = [
                    ("ACLineStatus", ctypes.c_byte),
                    ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte),
                    ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_uint32),
                    ("BatteryFullLifeTime", ctypes.c_uint32),
                ]

            status = POWER_STATUS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                # 0 = 电池, 1 = 已接通电源, 255 = 未知
                return status.ACLineStatus == 0
        except Exception:  # noqa: BLE001
            return False
    elif sys.platform.startswith("linux"):
        # 适配器(AC/ADP)只有 online 文件，status 在电池(BAT*)上
        try:
            for path in glob.glob("/sys/class/power_supply/BAT*/status"):
                with open(path, encoding="ascii") as fh:
                    if fh.read().strip() == "Discharging":
                        return True
        except OSError:
            return False
    return False  # macOS 简化：视作插电
