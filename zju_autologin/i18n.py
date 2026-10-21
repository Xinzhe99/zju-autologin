"""轻量 i18n：JSON 词典 + 跟随系统语言，支持运行时切换。

- 翻译文件位于 zju_autologin/i18n/{lang}.json（key 为扁平点号命名）
- 语言列表由目录里的词典自动发现, 新增语言只需放一个 <BCP-47>.json
- 语言选择顺序：config 覆盖 > 系统语言 > zh-CN
  （缺失 key 依次回退 en-US → 中文 → key 本身，绝不显示空白）
- 线程安全：词典整体替换（GIL 保证读取一致性），可在任意线程调用
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_LANG = "zh-CN"
FALLBACK_ORDER = ("en-US", DEFAULT_LANG)

# 各语言的自称。没列到的语言直接用词典里的 lang.native_name / 语言码。
LANG_LABELS = {
    "zh-CN": "简体中文",
    "zh-TW": "繁體中文",
    "en-US": "English",
    "ja-JP": "日本語",
    "ko-KR": "한국어",
    "de-DE": "Deutsch",
    "fr-FR": "Français",
    "es-ES": "Español",
    "ru-RU": "Русский",
    "pt-BR": "Português",
}

_current = DEFAULT_LANG
_dicts: dict[str, dict] = {}
_supported: list[str] = []


def _candidates() -> list[Path]:
    base = Path(__file__).parent / "i18n"
    if getattr(sys, "frozen", False):
        return [Path(sys._MEIPASS) / "zju_autologin" / "i18n", base]
    return [base]


def _discover() -> list[str]:
    """扫描词典目录, 返回可用语言代码(去重, 默认语言与英文在最前)。"""
    found: list[str] = []
    for root in _candidates():
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            code = path.stem
            if len(code) < 2 or code in found:
                continue
            found.append(code)
    ordered = [lang for lang in (DEFAULT_LANG, "en-US") if lang in found]
    ordered += [lang for lang in found if lang not in ordered]
    return ordered or [DEFAULT_LANG]


def supported_langs() -> list[str]:
    """当前安装包实际带有词典的语言(按显示顺序)。"""
    if not _supported:
        _supported.extend(_discover())
    return list(_supported)


def _load(lang: str) -> dict:
    for root in _candidates():
        path = root / f"{lang}.json"
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
    return {}


def lang_label(lang: str) -> str:
    """语言在界面上的显示名(优先词典自带的自称)。"""
    native = _dicts.get(lang, {}).get("lang.native_name")
    return LANG_LABELS.get(lang) or native or lang


def detect_system_lang() -> str:
    """探测系统语言；未安装对应词典时回退到默认语言。"""
    try:
        from PyQt6.QtCore import QLocale

        name = QLocale.system().name()  # 如 zh_CN / en_US
        code = name.replace("_", "-")
    except Exception:  # noqa: BLE001
        import locale
        import os

        env = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
        code = env.split(".")[0].replace("_", "-") or (locale.getlocale()[0] or "")
    return _match(code)


def _match(code: str) -> str:
    """把 "zh_CN"/"zh"/"pt-BR" 之类的输入对齐到已安装的词典代码。"""
    langs = supported_langs()
    norm = (code or "").replace("_", "-").strip()
    if not norm:
        return DEFAULT_LANG
    if norm in langs:
        return norm
    lower = norm.lower()
    for lang in langs:
        if lang.lower() == lower:
            return lang
    # 同语言不同地区(如 zh-HK → zh-TW / zh-CN, en-GB → en-US)
    prefix = lower.split("-")[0]
    same = [lang for lang in langs if lang.lower().split("-")[0] == prefix]
    if same:
        # 繁简不能混: 中文优先同文字体系, 其余取第一个
        if prefix == "zh":
            for lang in same:
                if lower.endswith(("-tw", "-hk", "-mo")) == lang.endswith("zh-TW"):
                    return lang
        return same[0]
    return DEFAULT_LANG


def set_lang(lang: str) -> None:
    """设置当前语言；''/'auto' 表示跟随系统, 未知语言回退默认语言。"""
    resolved = detect_system_lang() if lang in ("", "auto", None) else _match(str(lang))
    global _current
    _current = resolved
    if resolved not in _dicts:
        _dicts[resolved] = _load(resolved)
    for lang_code in FALLBACK_ORDER:
        if lang_code not in _dicts:
            _dicts[lang_code] = _load(lang_code)


def current_lang() -> str:
    return _current


def tr(key: str, **kwargs) -> str:
    """取翻译；回退顺序 当前语言 → en-US → zh-CN → key。"""
    text = _dicts.get(_current, {}).get(key)
    if text is None:
        for lang in FALLBACK_ORDER:
            text = _dicts.get(lang, {}).get(key)
            if text is not None:
                break
    if text is None:
        text = key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


set_lang(DEFAULT_LANG)  # 导入即加载默认词典，保证任何入口都能拿到翻译
