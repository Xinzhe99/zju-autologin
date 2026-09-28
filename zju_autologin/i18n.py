"""轻量 i18n：JSON 词典 + 跟随系统语言，支持运行时切换。

- 翻译文件位于 zju_autologin/i18n/{lang}.json（key 为扁平点号命名）
- 语言选择顺序：config 覆盖 > 系统语言 > zh-CN（缺失 key 依次回退 en-US → key 本身）
- 线程安全：词典整体替换（GIL 保证读取一致性），可在任意线程调用
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SUPPORTED_LANGS = ["zh-CN", "en-US"]
LANG_LABELS = {"zh-CN": "简体中文", "en-US": "English"}
DEFAULT_LANG = "zh-CN"

_current = DEFAULT_LANG
_dicts: dict[str, dict] = {}


def _candidates() -> list[Path]:
    base = Path(__file__).parent / "i18n"
    if getattr(sys, "frozen", False):
        return [Path(sys._MEIPASS) / "zju_autologin" / "i18n", base]  # noqa: SLF001
    return [base]


def _load(lang: str) -> dict:
    for root in _candidates():
        path = root / f"{lang}.json"
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
    return {}


def detect_system_lang() -> str:
    """探测系统语言（优先 Qt，其次环境变量）。"""
    try:
        from PyQt6.QtCore import QLocale

        name = QLocale.system().name()  # 如 zh_CN / en_US
        code = name.replace("_", "-")
    except Exception:  # noqa: BLE001
        import locale
        import os

        env = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
        code = env.split(".")[0].replace("_", "-") or (locale.getdefaultlocale()[0] or "")
    if code.lower().startswith("zh"):
        return "zh-CN"
    return "en-US"


def set_lang(lang: str) -> None:
    """设置当前语言；'auto' 表示跟随系统。"""
    resolved = detect_system_lang() if lang in ("", "auto", None) else lang
    if resolved not in SUPPORTED_LANGS:
        resolved = DEFAULT_LANG
    global _current
    _current = resolved
    if resolved not in _dicts:
        _dicts[resolved] = _load(resolved)
    if "en-US" not in _dicts:
        _dicts["en-US"] = _load("en-US")


def current_lang() -> str:
    return _current


def tr(key: str, **kwargs) -> str:
    """取翻译；回退顺序 当前语言 → en-US → key。"""
    text = _dicts.get(_current, {}).get(key)
    if text is None:
        text = _dicts.get("en-US", {}).get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


set_lang(DEFAULT_LANG)  # 导入即加载默认词典，保证任何入口都能拿到翻译
