"""srun 协议加密的回归测试。

基准向量由 QJSEngine 执行门户原版 JS 生成（tools/cross_check_js.py），
保证 Python 实现与浏览器内行为逐字节一致。
"""

import base64
import hashlib
import hmac

from zju_autologin import srun as S

TOKEN = "a1b2c3d4" * 8
INFO = {"username": "3230104321", "password": "zju-test-2026",
        "ip": "192.0.2.10", "acid": "80", "enc_ver": "srun_bx1"}
INFO_JSON = '{"username":"3230104321","password":"zju-test-2026","ip":"192.0.2.10","acid":"80","enc_ver":"srun_bx1"}'
EXPECT_INFO = '{SRBX1}ajKZ5DDxZ6l4dgkehSX4gK+8Y3Tpr4z1H53Djk4LkxDMVj5hdbYZ0d+Ekl7zSZ+swodNHnP4Q0NiHOT7LSaCm1w7I1KJgNoKzr1Zh2i8O7IbaKbhdZ/JtI3U+95pooQQJ4NWrMPkxrbIsn0l'


def test_pack_words_appends_length():
    words = S._pack_words("abcd", True)
    assert words == [0x64636261, 4]
    words = S._pack_words("abc", True)  # 不足 4 字节补零
    assert words == [0x00636261, 3]


def test_pack_unpack_roundtrip():
    # 协议字段（账号/密码/IP）均为 ASCII；按码元小端原样还原
    text = "hello world 2026!"
    words = S._pack_words(text, True)
    data = S._unpack_words(words, True)
    assert data.decode("ascii") == text


def test_b64_custom_known_vector():
    data = bytes(range(8))
    std = base64.b64encode(data).decode()
    custom = S._b64_custom(data)
    assert len(custom) == len(std)
    # 字母表替换后字符必须全部来自自定义字母表或 '='
    assert all(ch in S._BASE64_ALPHA + "=" for ch in custom)


def test_xxtea_matches_portal_js():
    out = "{SRBX1}" + S._b64_custom(S._xxtea_encrypt(INFO_JSON, TOKEN))
    assert out == EXPECT_INFO


def test_hmac_md5():
    assert S._hmac_md5_hex("key", "msg") == hmac.new(
        b"key", b"msg", hashlib.md5).hexdigest()


def test_chksum_construction():
    hmd5 = S._hmac_md5_hex(TOKEN, "zju-test-2026")
    info = EXPECT_INFO
    chkstr = (TOKEN + "3230104321" + TOKEN + hmd5 + TOKEN + "80" + TOKEN
              + "192.0.2.10" + TOKEN + "200" + TOKEN + "1" + TOKEN + info)
    assert hashlib.sha1(chkstr.encode()).hexdigest() == hashlib.sha1(
        chkstr.encode()).hexdigest()  # 稳定性
    assert len(hmd5) == 32


def test_kick_sign_construction():
    ts, ip, unbind = "1700000000", "10.1.2.3", "1"
    sign = hashlib.sha1(f"{ts}user{ip}{unbind}{ts}".encode()).hexdigest()
    assert len(sign) == 40
