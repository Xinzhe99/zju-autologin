"""浙江大学校园网认证协议（深澜 srun 门户）实现。

协议细节逆向自门户登录页 JS（https://net.zju.edu.cn/srun_portal_pc?ac_id=80&theme=zju）：

1. 获取挑战值
   GET /cgi-bin/get_challenge?callback=cb&username={user}&ip={ip}
   -> JSONP: {"challenge": "<64位hex token>", "error": "ok", ...}

2. 构造认证参数（登录页 Portal.js _loginAccount）
   hmd5   = HMAC-MD5(key=token, msg=password)                       # blueimp md5(msg, key)
   info   = '{SRBX1}' + b64_custom(XXTEA(json_info, token))         # json_info 紧凑序列化
   chksum = SHA1(token+username + token+hmd5 + token+ac_id
                 + token+ip + token+n + token+type + token+info)
   其中 json_info = {"username","password","ip","acid","enc_ver"}，acid="80"，
   enc_ver="srun_bx1"，n=200，type=1，double_stack=0。

3. 登录
   GET /cgi-bin/srun_portal?callback=cb&action=login
       &username={user}&password={MD5}+{hmd5}&os=Windows NT&name=Windows
       &double_stack=0&chksum={sha1}&info={info}&ac_id=80&ip={ip}&n=200&type=1

4. 在线状态
   GET /cgi-bin/rad_user_info -> 在线时返回逗号分隔字段（第 1 列用户名、
   第 2 列登录时间戳、第 9 列 IP），未认证时返回 "not_online"。

b64_custom：标准 base64 字母表替换为
'LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA'，带 '=' 填充。
XXTEA：标准 XXTEA（delta=0x9E3779B9），输入按 UTF-16 码元打包（ASCII 场景等同字节）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import socket
import time
import urllib.parse
import urllib.request

from .i18n import tr

__all__ = [
    "SrunClient",
    "SrunError",
    "DEFAULT_BASE_URL",
    "DEFAULT_AC_ID",
    "friendly_error",
]

DEFAULT_BASE_URL = "https://net.zju.edu.cn"
DEFAULT_AC_ID = "80"
DEFAULT_ENC_VER = "srun_bx1"

_BASE64_ALPHA = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"
_BASE64_STD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_DELTA = 0x9E3779B9
_MASK = 0xFFFFFFFF

# 登录页 rad_user_info 字段里我们关心的下标
_IDX_USERNAME = 0
_IDX_LOGIN_TIME = 1
_IDX_IP = 8


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """阻止自动跟随 302，用于捕获 captive portal 重定向地址。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


class SrunError(Exception):
    """门户请求失败（网络不通、响应异常等）。"""


def friendly_error(resp: dict) -> str:
    """把 srun 的错误响应翻译成本地化提示。"""
    from .i18n import tr

    err = str(resp.get("error", ""))
    msg = str(resp.get("error_msg", "") or "").strip()
    keys = {
        "E2620": "err.E2620",
        "E2901": "err.E2901",
        "ip_already_online_error": "err.ip_already_online_error",
        "password_error": "err.password_error",
        "E1002": "err.E1002",
        "username_error": "err.username_error",
        "not_online_error": "err.not_online_error",
        "access_denied": "err.access_denied",
        "nonce_error": "err.nonce_error",
        "traffic_mismatch_error": "err.traffic_mismatch_error",
    }
    key = keys.get(err) or keys.get(msg)
    text = tr(key) if key else ""
    if msg and msg != err:
        if text:
            return tr("err.detail_fmt", text=text, code=err or msg, msg=msg)
        return msg
    return text or err or tr("err.unknown")


def _b64_custom(data: bytes) -> str:
    """标准 base64 编码后按 srun 自定义字母表替换。"""
    return base64.b64encode(data).decode("ascii").translate(
        str.maketrans(_BASE64_STD, _BASE64_ALPHA)
    )


def _pack_words(text: str, append_len: bool) -> list[int]:
    """对应 JS 的 s(str, include_len)：按 UTF-16 码元小端打包成 32 位字。

    JS 里越界 charCodeAt 返回 NaN，按位或后等价于 0，因此缺位补 0。
    （账号/密码/IP 均为 ASCII，码元即字节；含 BMP 之外字符时与 JS 有差异，
    属于边界情况，不影响校园网登录。）
    """
    codes = [ord(ch) & 0xFFFF for ch in text]
    words: list[int] = []
    for i in range(0, len(codes), 4):
        chunk = codes[i : i + 4]
        chunk += [0] * (4 - len(chunk))
        words.append(chunk[0] | chunk[1] << 8 | chunk[2] << 16 | chunk[3] << 24)
    if append_len:
        words.append(len(codes))
    return words


def _unpack_words(words: list[int], trim_len: bool) -> bytes:
    """对应 JS 的 l(v, include_len)：32 位字小端还原为字节串。"""
    if trim_len:
        declared = words[-1]
        max_len = (len(words) - 1) << 2
        if declared < max_len - 3 or declared > max_len:
            raise SrunError(tr("srun.xxtea_fail"))
        limit = declared
    else:
        limit = len(words) << 2
    out = bytearray()
    for word in words:
        out += bytes((word & 0xFF, (word >> 8) & 0xFF, (word >> 16) & 0xFF, (word >> 24) & 0xFF))
    return bytes(out[:limit])


def _xxtea_encrypt(text: str, key: str) -> bytes:
    """标准 XXTEA 加密，忠实复刻登录页 encode() 的位运算。"""
    v = _pack_words(text, True)
    k = _pack_words(key, False)
    k += [0] * max(0, 4 - len(k))
    if len(v) < 2:  # 明文不足 2 个字时按 JS 行为补空字，保证可加密
        v += [0] * (2 - len(v))

    n = len(v) - 1
    q = 6 + 52 // (n + 1)
    z, y, d = v[n], v[0], 0
    while q > 0:
        q -= 1
        d = (d + _DELTA) & _MASK
        e = (d >> 2) & 3
        for p in range(n):
            y = v[p + 1]
            m = (z >> 5) ^ ((y << 2) & _MASK)
            m = (m + (((y >> 3) ^ ((z << 4) & _MASK)) ^ (d ^ y))) & _MASK
            m = (m + (k[(p & 3) ^ e] ^ z)) & _MASK
            z = v[p] = (v[p] + m) & _MASK
        y = v[0]
        m = (z >> 5) ^ ((y << 2) & _MASK)
        m = (m + (((y >> 3) ^ ((z << 4) & _MASK)) ^ (d ^ y))) & _MASK
        # JS for 循环结束后 p == n（Python range 循环结束后 p == n-1，须显式用 n）
        m = (m + (k[(n & 3) ^ e] ^ z)) & _MASK
        z = v[n] = (v[n] + m) & _MASK
    return _unpack_words(v, False)


def _hmac_md5_hex(key: str, msg: str) -> str:
    return hmac.new(key.encode(), msg.encode(), hashlib.md5).hexdigest()


def _parse_jsonp(text: str) -> dict:
    """解析 JSONP 响应（cb({...}) 或纯 JSON）。"""
    text = text.strip()
    start, end = text.find("("), text.rfind(")")
    if start != -1 and end > start:
        text = text[start + 1 : end]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SrunError(tr("srun.parse_failed", raw=text[:120])) from exc
    if not isinstance(data, dict):
        raise SrunError(tr("srun.response_bad"))
    return data


class SrunClient:
    """深澜 srun 门户客户端（线程安全：每个线程各自实例化即可）。"""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        ac_id: str = DEFAULT_AC_ID,
        enc_ver: str = DEFAULT_ENC_VER,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ac_id = str(ac_id)
        self.enc_ver = enc_ver
        self.timeout = timeout
        self._callback_seq = 0
        self._resolved_ac_id: str | None = None

    # ------------------------------------------------------------------ HTTP

    def _get(self, path: str, params: dict) -> str:
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        url = f"{self.base_url}{path}?{query}"
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 ZJU-AutoLogin"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            # srun 的部分错误以 HTTP 400 + JSONP 错误体返回，需读出内容
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if body:
                return body
            raise SrunError(tr("srun.request_failed", err=exc)) from exc
        except Exception as exc:  # noqa: BLE001 - 统一转成 SrunError
            raise SrunError(tr("srun.request_failed", err=exc)) from exc

    def _jsonp(self, path: str, params: dict) -> dict:
        self._callback_seq += 1
        params = dict(params, callback=f"zjulogin{int(time.time() * 1000)}{self._callback_seq}")
        return _parse_jsonp(self._get(path, params))

    # ------------------------------------------------------------------ 状态

    def get_status(self) -> dict:
        """查询门户在线状态。

        返回 {
            portal_ok: 门户是否可达（即本机是否处于校园网内）,
            online:    是否已认证在线,
            username, ip, login_time(可读), raw
        }
        """
        body = self._get("/cgi-bin/rad_user_info", {}).strip()
        raw = body
        if body.startswith("not_online"):
            return {"portal_ok": True, "online": False, "username": "", "ip": "", "raw": raw}

        if body.startswith("{"):
            # 带 callback 时门户返回 JSON 形态
            try:
                data = json.loads(body[body.find("(") + 1 : body.rfind(")")] if "(" in body else body)
            except json.JSONDecodeError:
                data = {}
            online = data.get("error") == "ok" and bool(data.get("user_name"))
            login_ts = int(data.get("add_time") or 0)
            return {
                "portal_ok": True,
                "online": online,
                "username": str(data.get("user_name") or ""),
                "ip": str(data.get("user_ip") or data.get("online_ip") or ""),
                "login_time": time.strftime("%Y-%m-%d %H:%M", time.localtime(login_ts)) if login_ts else "",
                "raw": raw,
            }

        # 纯文本形态：逗号分隔字段（第 1 列用户名、第 2 列上线时间戳、第 9 列 IP）
        fields = body.split(",")
        if len(fields) < 10:
            return {"portal_ok": True, "online": False, "username": "", "ip": "", "raw": raw}
        login_ts = int(fields[_IDX_LOGIN_TIME]) if fields[_IDX_LOGIN_TIME].isdigit() else 0
        return {
            "portal_ok": True,
            "online": True,
            "username": fields[_IDX_USERNAME],
            "ip": fields[_IDX_IP],
            "login_time": time.strftime("%Y-%m-%d %H:%M", time.localtime(login_ts)) if login_ts else "",
            "raw": raw,
        }

    def get_local_ip(self) -> str:
        """探测本机在校园网的 IPv4 地址（路由到门户所在网段）。"""
        try:
            host = urllib.parse.urlsplit(self.base_url).hostname or "net.zju.edu.cn"
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            try:
                sock.connect((host, 443))
                ip = sock.getsockname()[0]
            finally:
                sock.close()
            if ip and not ip.startswith("0."):
                return ip
        except OSError:
            pass
        return ""

    def get_portal_ip(self) -> str:
        """从门户首页 CONFIG 里读取服务端识别到的本机 IP（最可靠）。"""
        body = self._get("/index_1.html", {})
        match = re.search(r"ip\s*:\s*\"(\d{1,3}(?:\.\d{1,3}){3})\"", body)
        return match.group(1) if match else ""

    def resolve_ac_id(self) -> str:
        """ac_id 配置为 auto 时，从 captive portal 重定向自动探测（其他 srun 学校可用）。"""
        if self.ac_id not in ("", "auto"):
            return self.ac_id
        if self._resolved_ac_id:
            return self._resolved_ac_id
        ac_id = self.detect_portal_ac_id()
        self._resolved_ac_id = ac_id or DEFAULT_AC_ID
        return self._resolved_ac_id

    def detect_portal_ac_id(self) -> str:
        """访问一个 HTTP 探针，从门户劫持重定向 URL 中解析 ac_id / ip。"""
        probe = "http://www.msftconnecttest.com/redirect"
        try:
            req = urllib.request.Request(probe, headers={"User-Agent": "Mozilla/5.0 ZJU-AutoLogin"})
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(req, timeout=self.timeout) as resp:
                location = resp.headers.get("Location", "")
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location", "") if exc.headers else ""
        except Exception:  # noqa: BLE001
            return ""
        if not location:
            return ""
        if "http" not in location and location.startswith("/"):
            location = self.base_url + location
        host = urllib.parse.urlsplit(location)
        if host.scheme and "zju.edu.cn" not in host.netloc:
            # 其他学校：仍可复用其门户地址
            pass
        query = urllib.parse.parse_qs(host.query)
        ac_ids = query.get("ac_id") or query.get("ac-id") or []
        return str(ac_ids[0]) if ac_ids else ""

    def get_status_detail(self) -> dict:
        """带用量/套餐的富在线状态（门户 JSONP 形态），失败时退回 get_status。"""
        try:
            body = self._get("/cgi-bin/rad_user_info", {"callback": "zjulogin_detail"})
            text = body.strip()
            if text.startswith("{") or "(" in text:
                raw = text[text.find("(") + 1 : text.rfind(")")] if "(" in text else text
                data = json.loads(raw)
            else:
                data = {}
        except (SrunError, json.JSONDecodeError):
            data = {}
        base = self.get_status()
        if data.get("error") == "ok" and data.get("user_name"):
            base.update({
                "online": True,
                "username": str(data.get("user_name") or base.get("username", "")),
                "ip": str(data.get("user_ip") or data.get("online_ip") or base.get("ip", "")),
                "billing": str(data.get("billing_name") or ""),
                "all_bytes": int(data.get("all_bytes") or 0),
                "bytes_in": int(data.get("bytes_in") or 0),
                "bytes_out": int(data.get("bytes_out") or 0),
                "balance": data.get("user_balance"),
            })
        return base

    # ------------------------------------------------------- 在线设备管理

    def list_online_devices(self, username: str, password: str, domain: str = "") -> list[dict]:
        """获取账号的在线设备列表（用于 E2620 设备数超限时自助踢号）。

        门户接口使用密码的普通 MD5 作为凭据（与 portal 登录页一致）。
        """
        user = (username + domain).strip()
        pwd_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
        try:
            body = self._get(
                "/v1/srun_portal_online",
                {"user_name": user, "password": pwd_md5},
            )
            data = _parse_jsonp(body)
        except SrunError:
            return []
        if str(data.get("error", "")) != "ok":
            return []
        items = data.get("data") or []
        return [
            {
                "ip": str(it.get("ip") or ""),
                "user_name": str(it.get("user_name") or ""),
                "os_name": str(it.get("os_name") or ""),
                "client_type": str(it.get("client_type") or ""),
                "add_time": int(it.get("add_time") or 0),
            }
            for it in items if isinstance(it, dict)
        ]

    def kick_device(self, username: str, target_ip: str) -> tuple[bool, str]:
        """把账号在 target_ip 上的在线设备踢下线（设备数超限时使用）。"""
        ts = str(int(time.time()))
        unbind = "1"
        sign = hashlib.sha1(f"{ts}{username}{target_ip}{unbind}{ts}".encode()).hexdigest()
        try:
            resp = self._jsonp(
                "/cgi-bin/rad_user_dm",
                {"ip": target_ip, "username": username, "time": ts, "unbind": unbind, "sign": sign},
            )
        except SrunError as exc:
            return False, str(exc)
        ok = resp.get("error") == "ok"
        return ok, (tr("srun.login_ok") if ok else friendly_error(resp))

    # ------------------------------------------------------------------ 认证

    def login(self, username: str, password: str, ip: str = "", domain: str = "") -> dict:
        """执行门户认证。

        domain: 运营商服务后缀（如 '@cmcc'），校园网默认留空。
        返回 {"ok": bool, "msg": str, "username": str, "ip": str, "resp": dict}
        """
        username = (username + domain).strip()
        if not username:
            return {"ok": False, "msg": tr("srun.no_account"), "username": "", "ip": ip, "resp": {}}
        if not ip:
            ip = self.get_portal_ip() or self.get_local_ip()

        try:
            challenge = self._jsonp(
                "/cgi-bin/get_challenge", {"username": username, "ip": ip}
            )
            if challenge.get("error") != "ok" or not challenge.get("challenge"):
                return {
                    "ok": False,
                    "msg": friendly_error(challenge) or tr("srun.challenge_fail"),
                    "username": username,
                    "ip": ip,
                    "resp": challenge,
                }
            token = challenge["challenge"]

            ac_id = self.resolve_ac_id()
            info_json = json.dumps(
                {
                    "username": username,
                    "password": password,
                    "ip": ip,
                    "acid": ac_id,
                    "enc_ver": self.enc_ver,
                },
                separators=(",", ":"),
            )
            info = "{SRBX1}" + _b64_custom(_xxtea_encrypt(info_json, token))
            hmd5 = _hmac_md5_hex(token, password)
            n, t = 200, 1
            chkstr = (
                token + username
                + token + hmd5
                + token + ac_id
                + token + ip
                + token + str(n)
                + token + str(t)
                + token + info
            )
            chksum = hashlib.sha1(chkstr.encode()).hexdigest()

            resp = self._jsonp(
                "/cgi-bin/srun_portal",
                {
                    "action": "login",
                    "username": username,
                    "password": "{MD5}" + hmd5,
                    "os": "Windows NT",
                    "name": "Windows",
                    "double_stack": 0,
                    "chksum": chksum,
                    "info": info,
                    "ac_id": ac_id,
                    "ip": ip,
                    "n": n,
                    "type": t,
                },
            )
        except SrunError as exc:
            return {"ok": False, "msg": str(exc), "username": username, "ip": ip, "resp": {}}

        ok = resp.get("error") == "ok"
        suc_msg = str(resp.get("suc_msg", "") or "")
        if ok and suc_msg == "ip_already_online_error":
            msg = tr("srun.already_online")
        elif ok:
            msg = tr("srun.login_ok")
        else:
            msg = friendly_error(resp)
        return {"ok": ok, "msg": msg, "username": username, "ip": ip, "resp": resp}
