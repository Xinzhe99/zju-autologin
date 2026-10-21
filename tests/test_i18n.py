"""i18n 完整性：所有词典键集合一致、占位符一致、发现与回退机制可用。"""

import json
import re
from pathlib import Path

import pytest

from zju_autologin import i18n

LANG_DIR = Path(i18n.__file__).parent / "i18n"


def _load(lang: str) -> dict:
    return json.loads((LANG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _all_langs() -> list[str]:
    return sorted(p.stem for p in LANG_DIR.glob("*.json"))


def test_lang_files_discovered():
    """词典目录里的每个语言都必须被自动发现(新增语言无需改代码)。"""
    files = _all_langs()
    assert "zh-CN" in files and "en-US" in files
    discovered = i18n.supported_langs()
    assert set(files) == set(discovered), f"未被发现: {set(files) - set(discovered)}"
    assert discovered[0] == "zh-CN"  # 默认语言排最前


def test_all_supported_langs_present():
    for lang in i18n.supported_langs():
        data = _load(lang)
        assert len(data) > 100, f"{lang} 翻译条目过少"


def test_key_sets_identical():
    ref = set(_load("zh-CN"))
    for lang in _all_langs():
        if lang == "zh-CN":
            continue
        missing = ref - set(_load(lang))
        assert not missing, f"{lang} 缺少 {len(missing)} 个键, 例如 {sorted(missing)[:5]}"


def test_no_empty_translations():
    """空字符串会显示成一片空白, 比缺键更难排查。"""
    for lang in _all_langs():
        empty = [k for k, v in _load(lang).items() if not str(v).strip()]
        assert not empty, f"{lang} 有空翻译: {empty[:5]}"


def test_format_placeholders_identical():
    ph = re.compile(r"\{(\w+)\}")
    ref = _load("zh-CN")
    for lang in _all_langs():
        if lang == "zh-CN":
            continue
        data = _load(lang)
        for key, text in ref.items():
            got = data.get(key)
            if got is None:
                continue  # 由 test_key_sets_identical 负责
            assert set(ph.findall(text)) == set(ph.findall(got)), \
                f"{lang}: 占位符不一致 {key}"


def test_tr_fallback_and_format():
    i18n.set_lang("zh-CN")
    assert i18n.tr("nonexistent.key.xyz") == "nonexistent.key.xyz"
    assert i18n.tr("log.monitor_started", n=30) == "监控已启动，每 30 秒检测一次"
    i18n.set_lang("en-US")
    assert i18n.tr("log.monitor_started", n=30) == "Monitor started, checking every 30 s"
    i18n.set_lang("zh-CN")


@pytest.mark.parametrize("code,expected", [
    ("zh_CN", "zh-CN"),
    ("zh", "zh-CN"),
    ("en_GB", "en-US"),      # 没有 en-GB 词典时退到英文, 而不是中文
    ("pt-BR", "zh-CN"),      # 未安装的语言回退默认语言
    ("", "zh-CN"),
    ("xx-YY", "zh-CN"),
])
def test_system_lang_matching(code, expected):
    assert i18n._match(code) == expected


def test_unknown_lang_falls_back_to_default():
    # 用确定没有词典的语言码: 之前写死 ja-JP, 后来真的加了日语词典, 断言就失效了
    missing = next(code for code in ("tlh", "xx-YY", "qqq", "zz-ZZ")
                   if code not in i18n.supported_langs())
    i18n.set_lang(missing)
    assert i18n.current_lang() == i18n.DEFAULT_LANG
    assert i18n.tr("status.online")
    i18n.set_lang("zh-CN")


def test_missing_key_falls_back_to_english(monkeypatch):
    """当前语言缺键时必须回退英文, 不能把 key 直接甩给用户。"""
    partial = {"only.in.en": "English text", "status.online": "Online"}
    monkeypatch.setitem(i18n._dicts, "en-US", dict(i18n._dicts.get("en-US", {}), **partial))
    monkeypatch.setitem(i18n._dicts, "zh-CN", {"status.online": "网络正常"})
    monkeypatch.setattr(i18n, "_current", "zh-CN")
    assert i18n.tr("only.in.en") == "English text"
    assert i18n.tr("status.online") == "网络正常"
