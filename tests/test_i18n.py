"""i18n 完整性：各语言键集合一致、格式化占位符一致。"""

import json
import re
from pathlib import Path

import zju_autologin.i18n as i18n

LANG_DIR = Path(i18n.__file__).parent / "i18n"


def _load(lang: str) -> dict:
    return json.loads((LANG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def test_all_supported_langs_present():
    for lang in i18n.SUPPORTED_LANGS:
        data = _load(lang)
        assert len(data) > 100, f"{lang} 翻译条目过少"


def test_key_sets_identical():
    ref = set(_load("zh-CN"))
    for lang in i18n.SUPPORTED_LANGS[1:]:
        assert set(_load(lang)) == ref, f"{lang} 与 zh-CN 键集合不一致"


def test_format_placeholders_identical():
    ph = re.compile(r"\{(\w+)\}")
    zh = _load("zh-CN")
    en = _load("en-US")
    for key, text in zh.items():
        assert set(ph.findall(text)) == set(ph.findall(en[key])), f"占位符不一致: {key}"


def test_tr_fallback_and_format():
    i18n.set_lang("zh-CN")
    assert i18n.tr("nonexistent.key.xyz") == "nonexistent.key.xyz"
    assert i18n.tr("log.monitor_started", n=30) == "监控已启动，每 30 秒检测一次"
    i18n.set_lang("en-US")
    assert i18n.tr("log.monitor_started", n=30) == "Monitor started, checking every 30 s"
    i18n.set_lang("zh-CN")
