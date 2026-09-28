"""用 QtQml 的 QJSEngine 执行门户原版 JS 加密代码，与 Python 实现逐字节对比。"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "..")
sys.path.insert(0, ".")

from PyQt6.QtQml import QJSEngine

from zju_autologin import srun as S
from zju_autologin.srun import SrunClient

# —— 以下 JS 为 Portal.js _encodeUserInfo 的原样摘录（仅去掉闭包外壳）——
JS = r"""
function makeEncoder() {
    var _ALPHA = 'LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA';
    var _PADCHAR = '=';
    function _getbyte(s, i) { var x = s.charCodeAt(i); return x; }
    function _encode(s) {
        s = String(s);
        var i, b10, x = [], imax = s.length - s.length % 3;
        if (s.length === 0) { return s; }
        for (i = 0; i < imax; i += 3) {
            b10 = (_getbyte(s, i) << 16) | (_getbyte(s, i+1) << 8) | _getbyte(s, i+2);
            x.push(_ALPHA.charAt(b10 >> 18));
            x.push(_ALPHA.charAt((b10 >> 12) & 63));
            x.push(_ALPHA.charAt((b10 >> 6) & 63));
            x.push(_ALPHA.charAt(b10 & 63));
        }
        switch (s.length - imax) {
            case 1:
                b10 = _getbyte(s, i) << 16;
                x.push(_ALPHA.charAt(b10 >> 18) + _ALPHA.charAt((b10 >> 12) & 63) + _PADCHAR + _PADCHAR);
                break;
            case 2:
                b10 = (_getbyte(s, i) << 16) | (_getbyte(s, i+1) << 8);
                x.push(_ALPHA.charAt(b10 >> 18) + _ALPHA.charAt((b10 >> 12) & 63) + _ALPHA.charAt((b10 >> 6) & 63) + _PADCHAR);
                break;
        }
        return x.join('');
    }
    function encode(str, key) {
        if (str === '') return '';
        var v = s(str, true);
        var k = s(key, false);
        if (k.length < 4) k.length = 4;
        var n = v.length - 1, z = v[n], y = v[0], c = 0x86014019 | 0x183639A0,
            m, e, p, q = Math.floor(6 + 52 / (n + 1)), d = 0;
        while (0 < q--) {
            d = d + c & (0x8CE0D9BF | 0x731F2640);
            e = d >>> 2 & 3;
            for (p = 0; p < n; p++) {
                y = v[p + 1];
                m = z >>> 5 ^ y << 2;
                m += y >>> 3 ^ z << 4 ^ (d ^ y);
                m += k[p & 3 ^ e] ^ z;
                z = v[p] = v[p] + m & (0xEFB8D130 | 0x10472ECF);
            }
            y = v[0];
            m = z >>> 5 ^ y << 2;
            m += y >>> 3 ^ z << 4 ^ (d ^ y);
            m += k[p & 3 ^ e] ^ z;
            z = v[n] = v[n] + m & (0xBB390742 | 0x44C6F8BD);
        }
        return l(v, false);
    }
    function s(a, b) {
        var c = a.length;
        var v = [];
        for (var i = 0; i < c; i += 4) {
            v[i >> 2] = a.charCodeAt(i) | a.charCodeAt(i+1) << 8 | a.charCodeAt(i+2) << 16 | a.charCodeAt(i+3) << 24;
        }
        if (b) v[v.length] = c;
        return v;
    }
    function l(a, b) {
        var d = a.length;
        var c = d - 1 << 2;
        if (b) {
            var m = a[d - 1];
            if (m < c - 3 || m > c) return null;
            c = m;
        }
        for (var i = 0; i < d; i++) {
            a[i] = String.fromCharCode(a[i] & 0xff, a[i] >>> 8 & 0xff, a[i] >>> 16 & 0xff, a[i] >>> 24 & 0xff);
        }
        return b ? a.join('').substring(0, c) : a.join('');
    }
    return function (info, token) {
        return '{SRBX1}' + _encode(encode(JSON.stringify(info), token));
    };
}
var encodeUserInfo = makeEncoder();
"""

TESTS = [
    {"username": "zjuaul_probe_user", "password": "probe-pass-123",
     "ip": "192.0.2.10", "acid": "80", "enc_ver": "srun_bx1"},
    {"username": "3230104321", "password": "abc123", "ip": "192.0.2.10",
     "acid": "80", "enc_ver": "srun_bx1"},
    {"username": "3230104321", "password": "p@ss w0rd+/", "ip": "10.181.90.1",
     "acid": "80", "enc_ver": "srun_bx1"},
]
TOKEN = "0123456789abcdef" * 4 + "00112233"


def js_encode(engine: QJSEngine, info: dict, token: str) -> str:
    info_js = json.dumps(info, separators=(",", ":"), ensure_ascii=False)
    expr = f"encodeUserInfo({info_js}, '{token}')"
    result = engine.evaluate(expr)
    if result.isError():
        raise RuntimeError("JS error: " + result.toString())
    return result.toString()


def py_encode(info: dict, token: str) -> str:
    info_json = json.dumps(info, separators=(",", ":"))
    return "{SRBX1}" + S._b64_custom(S._xxtea_encrypt(info_json, token))


def main() -> int:
    from PyQt6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    engine = QJSEngine()
    ok = engine.evaluate(JS)
    if engine.hasError() or ok.isError():
        print("JS 执行失败:", ok.toString())
        return 1

    all_match = True
    for i, info in enumerate(TESTS):
        got_js = js_encode(engine, info, TOKEN)
        got_py = py_encode(info, TOKEN)
        match = got_js == got_py
        all_match &= match
        print(f"test{i}: JS==PY -> {match}")
        if not match:
            print("  JS:", got_js[:120], "...")
            print("  PY:", got_py[:120], "...")
            print("  JS json:", json.dumps(info, separators=(",", ":"))[:100])
            print("  PY json:", json.dumps(info, separators=(",", ":"))[:100])
    return 0 if all_match else 1


if __name__ == "__main__":
    raise SystemExit(main())
