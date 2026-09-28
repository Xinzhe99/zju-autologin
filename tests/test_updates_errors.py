"""版本比较与错误文案测试。"""

from zju_autologin import srun as S
from zju_autologin import i18n as i18n_mod
from zju_autologin.updates import _version_tuple


def test_version_tuple():
    assert _version_tuple("v1.2.3") == (1, 2, 3)
    assert _version_tuple("1.10.0") > _version_tuple("1.9.9")
    assert _version_tuple("") == (0,)


def test_friendly_error_known_code():
    i18n_mod.set_lang("zh-CN")
    text = S.friendly_error({"error": "password_error", "error_msg": ""})
    assert "密码" in text
    text = S.friendly_error({"error": "E2620", "error_msg": "too many"})
    assert "在线" in text and "too many" in text


def test_friendly_error_unknown():
    text = S.friendly_error({"error": "weird_code", "error_msg": ""})
    assert text == "weird_code"


def test_parse_jsonp():
    assert S._parse_jsonp('cb({"a": 1})') == {"a": 1}
    assert S._parse_jsonp('{"a": 2}') == {"a": 2}
