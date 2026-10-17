"""版本比较与错误文案测试。"""

from zju_autologin import srun as S
from zju_autologin import i18n as i18n_mod
from zju_autologin.updates import _version_tuple


def test_version_tuple():
    assert _version_tuple("v1.2.3") == (1, 2, 3, 0)
    assert _version_tuple("1.10.0") > _version_tuple("1.9.9")
    assert _version_tuple("") == (0,)
    # 段数不齐不能被误判为更新, 四段版本号末段不可丢弃
    assert _version_tuple("1.15") == _version_tuple("1.15.0")
    assert _version_tuple("1.15.0.1") > _version_tuple("1.15.0")


def test_friendly_error_known_code():
    i18n_mod.set_lang("zh-CN")
    text = S.friendly_error({"error": "password_error", "error_msg": ""})
    assert "密码" in text
    text = S.friendly_error({"error": "E2620", "error_msg": "too many"})
    assert "在线" in text and "too many" in text


def test_friendly_error_unknown():
    text = S.friendly_error({"error": "weird_code", "error_msg": ""})
    assert text == "weird_code"


def test_bas_timeout_is_transient_not_credentials():
    """issue #1: "INFO failed, BAS respond timeout." 是门户侧临时故障,
    文案要说清是超时/重试, 不能原样甩英文报文, 更不能当密码错。"""
    i18n_mod.set_lang("zh-CN")
    resp = {"error": "INFO failed, BAS respond timeout.", "error_msg": ""}
    assert S.is_transient_portal_error(resp)
    text = S.friendly_error(resp)
    assert "BAS" in text and "临时" in text
    assert not S.is_transient_portal_error({"error": "password_error"})
    assert not S.is_transient_portal_error({"error": "E2901"})
    assert not S.is_transient_portal_error(None)


def test_parse_jsonp():
    assert S._parse_jsonp('cb({"a": 1})') == {"a": 1}
    assert S._parse_jsonp('{"a": 2}') == {"a": 2}
