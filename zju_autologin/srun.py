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
import contextlib
import hashlib
import hmac
import http.client
import json
import re
import socket
import time
import urllib.parse
import urllib.request

from .i18n import tr
from .net import bound_opener, candidate_source_ips

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


def _safe_int(value) -> int:
    """字段类型突变(字符串科学计数/None)时兜底为 0, 不让异常逸出。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        try:
            return int(float(value))
        except (TypeError, ValueError, OverflowError):
            return 0


def _safe_localtime(ts: int) -> str:
    """纪元秒→可读时间; 13 位毫秒/越界值兜底为空串而非抛 OSError。"""
    if not ts:
        return ""
    if ts > 10**12:  # 毫秒纪元
        ts //= 1000
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return ""


def _login_outcome(username: str, ip: str, resp: dict) -> dict:
    """把门户的登录响应翻译成统一结果(便于单测直接喂响应体)。

    "本机 IP 已在线" 属成功语义, 但不同部署把它放在 suc_msg 或 error 里。
    只认 suc_msg 会把有效会话判成登录失败: 用户收到"登录失败"推送、界面转红,
    重试还被退避到 10 分钟 —— 双登录/设备超限场景下的典型误报。
    """
    ok = resp.get("error") == "ok"
    suc_msg = str(resp.get("suc_msg", "") or "")
    already = (suc_msg == "ip_already_online_error"
               or str(resp.get("error", "")) == "ip_already_online_error")
    if already:
        msg = tr("srun.already_online")
    elif ok:
        msg = tr("srun.login_ok")
    else:
        msg = friendly_error(resp)
    return {"ok": ok or already, "msg": msg, "username": username, "ip": ip, "resp": resp}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """阻止自动跟随 302，用于捕获 captive portal 重定向地址。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TCP 连到指定 IP, 但 TLS 按 verify_hostname 校验证书。

    注意 verify_hostname 必须由调用方显式给出: 走 IP 直连时 URL 的 host 就是
    IP, 只按 self.host 校验会变成"校验证书对 IP 有效", 那是永远失败的。
    """

    def __init__(self, host: str, pinned_ip: str, verify_hostname: str = "", **kwargs) -> None:
        super().__init__(host, **kwargs)
        self._pinned_ip = pinned_ip
        self._verify_hostname = verify_hostname or host

    def connect(self) -> None:  # noqa: D102 - 复刻 HTTPSConnection.connect, 只换目标地址
        sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout,
            getattr(self, "source_address", None))
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
            server_hostname = self._tunnel_host
        else:
            server_hostname = self._verify_hostname
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """把 https 请求钉到指定 IP, 证书仍按原始主机名校验。"""

    def __init__(self, pinned_ip: str, hostname: str, context=None) -> None:
        super().__init__(context=context)
        self._pinned_ip = pinned_ip
        self._hostname = hostname

    def https_open(self, req):  # noqa: D102
        def factory(host, **kwargs):
            kwargs.pop("check_hostname", None)
            return _PinnedHTTPSConnection(host, self._pinned_ip,
                                          verify_hostname=self._hostname,
                                          context=self._context, **kwargs)

        return self.do_open(factory, req)


# 绕过系统代理的直连 opener（门户与认证 API 只应走校园网直连）
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 门户 IP 直连缓存（host -> [ip...]）: 校园 DNS 故障时按缓存 IP + Host 头直连
_PORTAL_IP_CACHE: dict[str, list[str]] = {}


def _resolve_and_cache(host: str) -> tuple[list[str], bool]:
    """解析门户 IP。返回 (IP 列表, DNS 是否存活)。

    DNS 正常时刷新缓存; DNS 故障(gaierror)时返回缓存旧值供兜底直连。
    """
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        ips = sorted({info[4][0] for info in infos})
        if ips:
            _PORTAL_IP_CACHE[host] = ips
        return ips, True
    except socket.gaierror:
        return list(_PORTAL_IP_CACHE.get(host, [])), False


# 门户连接策略缓存（host -> "策略|协议"）：命中后跳过全部失败尝试
_STRATEGY_CACHE: dict[str, str] = {}
# 全链失败负缓存（host -> 失败时间戳）：如门户整体不可达（掉校外），
# 5 分钟内只尝试直连策略，避免每轮检测空耗几十秒
_NEG_CACHE: dict[str, float] = {}
_NEG_TTL = 300.0


class SrunError(Exception):
    """门户请求失败（网络不通、响应异常等）。"""


def friendly_error(resp: dict) -> str:
    """把 srun 的错误响应翻译成本地化提示。"""
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
        "user_must_modify_password": "err.user_must_modify_password",
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
    if not text.startswith("{"):
        # 仅当确为 callback( 前缀时剥壳, 避免截断 error_msg 里出现的括号
        m = re.match(r"^[\w$.]+\(", text)
        end = text.rfind(")")
        if m and end > m.end():
            text = text[m.end():end]
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
        self._extra_headers: dict = {}

    # ------------------------------------------------------------------ HTTP

    def _request_once(self, url: str, opener: urllib.request.OpenerDirector | None = None) -> str:
        """单次请求。opener 缺省为直连（门户必须在校园网内直达，
        显式绕过系统代理——Clash/v2ray 等会拦截发往门户的 TLS 连接）。"""
        headers = {"User-Agent": "Mozilla/5.0 ZJU-AutoLogin"}
        headers.update(getattr(self, "_extra_headers", {}) or {})
        host = urllib.parse.urlsplit(url).netloc.split("@")[-1].split(":")[0]
        ips, dns_alive = _resolve_and_cache(host)
        if not ips:
            raise SrunError(tr("srun.dns_down"))
        if not dns_alive:
            # DNS 故障兜底: 按缓存 IP 直连, Host 头保留虚拟主机。
            # 关键: 证书校验不降级 —— 以前这里关掉校验(verify_mode=CERT_NONE),
            # 而登录查询串里就带着口令摘要与 XXTEA 密钥(密钥是同串里的明文
            # challenge), 等于把密码交给路上的任何人。现在改为把 TCP 钉到缓存
            # IP、TLS 仍按原主机名验证: 中间人拿不出有效证书, 直接失败。
            import ssl

            ctx = ssl.create_default_context()
            parts = urllib.parse.urlsplit(url)
            port = parts.port
            host_header = host if port is None else f"{host}:{port}"
            last_exc: Exception | None = None
            for ip in ips[:2]:
                netloc = ip if port is None else f"{ip}:{port}"
                fallback_url = urllib.parse.urlunsplit(parts._replace(netloc=netloc))
                headers["Host"] = host_header
                try:
                    req = urllib.request.Request(fallback_url, headers=headers)
                    if parts.scheme == "https":
                        ip_opener = urllib.request.build_opener(
                            urllib.request.ProxyHandler({}),
                            _PinnedHTTPSHandler(ip, host, context=ctx))
                    else:
                        ip_opener = urllib.request.build_opener(
                            urllib.request.ProxyHandler({}))
                    with ip_opener.open(req, timeout=self.timeout) as resp:
                        return resp.read().decode("utf-8", errors="replace")
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
            raise SrunError(tr("srun.dns_down")) from last_exc
        req = urllib.request.Request(url, headers=headers)
        opener = opener or _DIRECT_OPENER
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            # srun 的部分错误以 HTTP 400 + JSONP 错误体返回，需读出内容;
            # read 本身也可能因 socket 超时抛 OSError, 统一转 SrunError
            try:
                with contextlib.closing(exc):
                    body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            except OSError as rd_exc:
                raise SrunError(tr("srun.request_failed", err=rd_exc)) from rd_exc
            if body:
                return body
            raise SrunError(tr("srun.request_failed", err=exc)) from exc
        except Exception as exc:  # noqa: BLE001 - 统一转成 SrunError
            raise SrunError(tr("srun.request_failed", err=exc)) from exc

    def _strategies(self) -> list[tuple[str, urllib.request.OpenerDirector, str]]:
        """门户连接策略候选（标识, opener, 协议），命中缓存的排最前。

        顺序：系统代理绕过直连 → 绑定校园网网卡源地址直发（绕过 TUN 默认路由）
        × HTTPS/HTTP 双协议。VPN(TUN) 在 IP 层劫持时，绑定通常仍可从物理网卡直发。
        """
        host = urllib.parse.urlsplit(self.base_url).netloc
        pairs: list[tuple[str, urllib.request.OpenerDirector, str]] = [
            ("direct", _DIRECT_OPENER, "https"),
            ("direct", _DIRECT_OPENER, "http"),
        ]
        recently_failed = time.time() - _NEG_CACHE.get(host, 0.0) < _NEG_TTL
        ips = candidate_source_ips()
        if recently_failed:
            # 负缓存期仍留一条 bind 兜底: Wi-Fi 重连后 bind 可能已恢复, 全走 direct 会必败
            ips = ips[:1]
        for ip in ips:
            opener = bound_opener(ip)
            pairs.append((f"bind:{ip}", opener, "https"))
            pairs.append((f"bind:{ip}", opener, "http"))
        cached = _STRATEGY_CACHE.get(host)
        if cached:
            key, scheme = cached.rsplit("|", 1)
            opener = (bound_opener(key[len("bind:"):])
                      if key.startswith("bind:") else _DIRECT_OPENER)
            rest = [p for p in pairs if f"{p[0]}|{p[2]}" != cached]
            return [(key, opener, scheme)] + rest
        return pairs

    def _get(self, path: str, params: dict,
             https_only: bool = False, deadline: float | None = None) -> str:
        """按策略链请求门户。

        https_only: 带凭据的端点(登录/设备管理)限制 https 策略, 防止口令摘要
            经降级 http 明文传输。
        deadline: 策略链总时间预算(monotonic 秒), 超限停止尝试剩余策略,
            防止多网卡机器单轮检测阻塞数分钟。
        validate: 由调用方负责 -- _jsonp 在解析失败时会清除本 host 的策略
            缓存并重试(见 _jsonp), 避免错误页毒化缓存。
        """
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        host = urllib.parse.urlsplit(self.base_url).netloc
        first_exc: SrunError | None = None
        for key, opener, scheme in self._strategies():
            if https_only and scheme != "https":
                continue
            if deadline is not None and time.monotonic() > deadline:
                break
            base = f"{scheme}://{host}"
            try:
                body = self._request_once(f"{base}{path}?{query}", opener)
            except SrunError as exc:
                first_exc = first_exc or exc
                continue
            self.base_url = base
            _STRATEGY_CACHE[host] = f"{key}|{scheme}"
            _NEG_CACHE.pop(host, None)
            return body
        _NEG_CACHE[host] = time.time()
        raise first_exc or SrunError(tr("srun.request_failed", err="all strategies failed"))

    def _jsonp(self, path: str, params: dict | None = None,
               https_only: bool = False,
               extra_headers: dict | None = None,
               captcha: str | None = None) -> dict:
        self._callback_seq += 1
        params = dict(params or {}, callback=f"zjulogin{int(time.time() * 1000)}{self._callback_seq}")
        if captcha:
            params["captcha"] = captcha
        host = urllib.parse.urlsplit(self.base_url).netloc
        last_exc: SrunError | None = None
        # 最多两轮: 第一轮解析失败说明当前策略拿到的是错误页(代理劫持/网关 502/
        # 维护页), 摘掉策略缓存后按自然顺序再试一次, 而不是像以前那样直接抛错
        # 并把坏策略留在缓存里继续毒化后续每一次请求。
        for attempt in range(2):
            if extra_headers:
                self._extra_headers = dict(extra_headers)
            try:
                body = self._get(path, params, https_only=https_only,
                                 deadline=time.monotonic() + 25.0)
            finally:
                self._extra_headers = {}
            try:
                return _parse_jsonp(body)
            except SrunError as exc:
                last_exc = exc
                cached = _STRATEGY_CACHE.pop(host, None)
                if attempt or not cached:
                    break
        raise last_exc or SrunError(tr("srun.response_bad"))

    # ------------------------------------------------------------------ 状态

    @staticmethod
    def _offline_status(raw: str = "") -> dict:
        return {"portal_ok": True, "online": False, "username": "", "ip": "",
                "login_time": "", "billing": "", "all_bytes": 0, "raw": raw}

    def get_status(self) -> dict:
        """查询门户在线状态（富形态：含套餐/累计流量；自动回退纯文本形态）。

        返回 {portal_ok, online, username, ip, login_time, billing, all_bytes, raw}
        """
        # 1) JSONP 富形态（带 callback 时返回 JSON，含套餐/流量/余额）
        t0 = time.perf_counter()
        deadline = time.monotonic() + 25.0  # 与 _jsonp 同一预算, 防多网卡机器单轮阻塞数分钟
        body = self._get("/cgi-bin/rad_user_info",
                         {"callback": "zjulogin_status"}, deadline=deadline).strip()
        latency = int((time.perf_counter() - t0) * 1000)
        if body.endswith(")") and "(" in body:
            try:
                data = json.loads(body[body.find("(") + 1: body.rfind(")")])
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                if data.get("error") == "ok" and data.get("user_name"):
                    try:
                        login_ts = int(float(data.get("add_time") or 0))
                    except (TypeError, ValueError):
                        login_ts = 0
                    return {
                        "portal_ok": True,
                        "online": True,
                        "username": str(data.get("user_name") or ""),
                        "ip": str(data.get("user_ip") or data.get("online_ip") or ""),
                        "login_time": _safe_localtime(login_ts),
                        "domain": str(data.get("domain") or ""),
                        "billing": str(data.get("billing_name") or ""),
                        "all_bytes": _safe_int(data.get("all_bytes")),
                        "latency_ms": latency,
                        "raw": body,
                    }
                if data.get("error") in ("not_online_error", "login_error") or                         "not_online" in str(data.get("error_msg", "")):
                    return self._offline_status(body)

        # 2) 纯文本形态：逗号分隔（第 1 列用户名、第 2 列上线时间戳、第 9 列 IP）
        body = self._get("/cgi-bin/rad_user_info", {}, deadline=deadline).strip()
        if body.startswith("not_online"):
            return self._offline_status(body)
        fields = body.split(",")
        if len(fields) < 10:
            return self._offline_status(body)
        # 字段形状校验: 用户名非空且 IP 列为合法 IPv4, 否则按垃圾页(未在线)处理
        if not fields[_IDX_USERNAME].strip() or not re.fullmatch(
                r"\d{1,3}(?:\.\d{1,3}){3}", fields[_IDX_IP].strip()):
            return self._offline_status(body)
        login_ts = _safe_int(fields[_IDX_LOGIN_TIME])
        return {
            "portal_ok": True,
            "online": True,
            "username": fields[_IDX_USERNAME],
            "ip": fields[_IDX_IP],
            "login_time": _safe_localtime(login_ts),
            "billing": "",
            "all_bytes": 0,
            "raw": body,
        }

    def get_status_detail(self) -> dict:
        """向后兼容别名：get_status 现已自带套餐/流量字段。"""
        return self.get_status()

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

    def parse_portal_config(self) -> dict:
        """解析门户的 acid 与服务端识别的本机 IP。

        门户首页可能是跳转壳：CONFIG 不在首页，而是带着 ac_id 链到
        srun_portal_pc 登录页 —— 此时跟进登录页再解析 CONFIG。
        """
        body = self._get("/index_1.html", {})
        result = {"acid": "", "ip": ""}
        match = re.search(r'acid\s*:\s*"?(\w+)"?', body)
        if match:
            result["acid"] = match.group(1)
        match = re.search(r"ip\s*:\s*\"(\d{1,3}(?:\.\d{1,3}){3})\"", body)
        if match:
            result["ip"] = match.group(1)
        if not result["acid"]:
            idx = body.find("srun_portal_pc")
            if idx != -1:
                match = re.search(r"ac_id=(\w+)", body[idx:idx + 300])
            else:
                match = None
            if match:
                result["acid"] = match.group(1)
                try:
                    page = self._get(f"/srun_portal_pc?ac_id={match.group(1)}", {})
                    match = re.search(r"ip\s*:\s*\"(\d{1,3}(?:\.\d{1,3}){3})\"", page)
                    if match:
                        result["ip"] = match.group(1)
                except SrunError:
                    pass
        return result

    def get_portal_ip(self) -> str:
        """从门户首页 CONFIG 里读取服务端识别到的本机 IP（最可靠）。"""
        return self.parse_portal_config().get("ip", "")

    def fetch_captcha(self) -> dict:
        """获取登录验证码图片。返回 {ok, cookie, data(bytes), token} 或 {ok:False, msg}。

        深澜验证码: GET /v2/srun_portal_captcha_image?... 返回图片并 Set-Cookie 会话,
        提交登录时须回带该 Cookie + captcha 参数。
        """
        import http.cookiejar
        import urllib.parse as _up

        self._callback_seq += 1
        qs = _up.urlencode({"username": "captcha", "ip": "",
                            "callback": f"zjucap{int(time.time() * 1000)}{self._callback_seq}"})
        url = f"{self.base_url}/v2/srun_portal_captcha_image?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ZJU-AutoLogin"})
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                data = resp.read()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "msg": str(exc)}
        cookie = "; ".join(f"{c.name}={c.value}" for c in jar)
        if not data or len(data) < 100:
            return {"ok": False, "msg": "empty captcha image"}
        return {"ok": True, "cookie": cookie, "data": data}

    def login_with_captcha(self, username: str, password: str, captcha: str,
                           cookie: str = "", ip: str = "", domain: str = "") -> dict:
        """带验证码登录: 在标准 login 流程的提交参数上加 captcha + Cookie。"""
        result = self.login(username, password, ip=ip, domain=domain, _captcha=(captcha, cookie))
        return result

    def check_captcha(self) -> bool:
        """探测门户是否开启登录验证码（开启则无头登录不可用, 需明确告知用户）。"""
        try:
            resp = self._jsonp("/v2/srun_portal_captcha_image_info",
                               {"username": "probe", "ip": ""})
            data = resp if isinstance(resp, dict) else {}
            return str(data.get("enable_captcha") or data.get("captcha") or "") in ("1", "true", "True")
        except Exception:  # noqa: BLE001 - 接口不存在(多数部署)视为无验证码
            return False

    def probe_portal(self, username: str = "probe", ip: str = "") -> dict:
        """探测当前门户可用性（接入向导用）：CONFIG 解析 + challenge 实测。"""
        try:
            cfg = self.parse_portal_config()
        except SrunError as exc:
            return {"ok": False, "acid": "", "ip": "", "challenge_ok": False, "msg": str(exc)}
        acid = cfg.get("acid") or ""
        ip = ip or cfg.get("ip") or self.get_local_ip()
        challenge_ok = False
        if acid:
            try:
                resp = self._jsonp("/cgi-bin/get_challenge", {"username": username, "ip": ip})
                challenge_ok = resp.get("error") == "ok"
            except SrunError:
                challenge_ok = False
        ok = bool(acid) and challenge_ok
        msg = "ok" if ok else ("no acid" if not acid else "challenge failed")
        return {"ok": ok, "acid": acid, "ip": ip, "challenge_ok": challenge_ok, "msg": msg}

    def resolve_ac_id(self) -> str:
        """ac_id 配置为 auto 时，从 captive portal 重定向自动探测（其他 srun 学校可用）。"""
        if self.ac_id not in ("", "auto"):
            return self.ac_id
        if self._resolved_ac_id:
            return self._resolved_ac_id
        ac_id = self.detect_portal_ac_id()
        self._resolved_ac_id = ac_id or DEFAULT_AC_ID
        return self._resolved_ac_id

    @staticmethod
    def discover_portal(timeout: float = 4.0) -> dict:
        """通过 captive portal 重定向发现本网段的深澜门户（零输入识别）。

        未认证时任何 HTTP 请求都会被 302 到登录页; 通用版不预设 base_url,
        从重定向目标提取门户根地址与 ac_id。只认含 srun 特征的目标,
        避免把其他认证系统(锐捷/Dr.COM)误当深澜。
        """
        probe = "http://www.msftconnecttest.com/redirect"
        location = ""
        try:
            req = urllib.request.Request(probe, headers={"User-Agent": "Mozilla/5.0 ZJU-AutoLogin"})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(req, timeout=timeout) as resp:
                location = resp.headers.get("Location", "")
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location", "") if exc.headers else ""
        except Exception:  # noqa: BLE001
            return {}
        # captive portal 常用相对 Location(RFC 7231 允许), 与 detect_portal_ac_id
        # 保持一致先补全; 早期直接判 "http" not in location 会漏掉这类门户
        location = urllib.parse.urljoin(probe, location)
        if not location or "http" not in location:
            return {}
        split = urllib.parse.urlsplit(location)
        if not split.scheme.startswith("http"):
            return {}
        low = location.lower()
        if "srun_portal" not in low and "cgi-bin" not in low:
            return {}
        base = f"{split.scheme}://{split.netloc}"
        query = urllib.parse.parse_qs(split.query)
        ac_id = (query.get("ac_id") or query.get("ac-id") or [""])[0]
        ip = (query.get("user_ip") or query.get("ip") or [""])[0]
        return {"base_url": base, "ac_id": str(ac_id), "ip": str(ip), "login_url": location}

    def detect_portal_ac_id(self) -> str:
        """访问一个 HTTP 探针，从门户劫持重定向 URL 中解析 ac_id / ip。"""
        probe = "http://www.msftconnecttest.com/redirect"
        try:
            req = urllib.request.Request(probe, headers={"User-Agent": "Mozilla/5.0 ZJU-AutoLogin"})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(req, timeout=self.timeout) as resp:
                location = resp.headers.get("Location", "")
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location", "") if exc.headers else ""
        except Exception:  # noqa: BLE001
            return ""
        if not location:
            return ""
        if not urllib.parse.urlsplit(location).scheme:
            # 相对 Location（含无前导 / 的形式）按门户地址补全
            location = urllib.parse.urljoin(self.base_url + "/", location)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        ac_ids = query.get("ac_id") or query.get("ac-id") or []
        return str(ac_ids[0]) if ac_ids else ""


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
                https_only=True, deadline=time.monotonic() + 25.0,
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
                "add_time": _safe_int(it.get("add_time")),
            }
            for it in items if isinstance(it, dict)
        ]

    def kick_device(self, username: str, target_ip: str, domain: str = "") -> tuple[bool, str]:
        """把账号在 target_ip 上的在线设备踢下线（设备数超限时使用）。

        domain 必须与 list_online_devices 用同一口径: 运营商后缀账号
        (如 3230104321@cmcc) 少了后缀会导致签名/账号对不上, 踢号永远失败。
        """
        username = (username + domain).strip()
        ts = str(int(time.time()))
        unbind = "1"
        sign = hashlib.sha1(f"{ts}{username}{target_ip}{unbind}{ts}".encode()).hexdigest()
        try:
            resp = self._jsonp(
                "/cgi-bin/rad_user_dm",
                https_only=True,
                params={"ip": target_ip, "username": username, "time": ts, "unbind": unbind, "sign": sign},
            )
        except SrunError as exc:
            return False, str(exc)
        ok = resp.get("error") == "ok"
        return ok, (tr("srun.login_ok") if ok else friendly_error(resp))

    # ------------------------------------------------------------------ 认证

    def login(self, username: str, password: str, ip: str = "", domain: str = "",
              _captcha: tuple[str, str] | None = None) -> dict:
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
                "/cgi-bin/get_challenge", {"username": username, "ip": ip}, https_only=True
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
                https_only=True,
                params={
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
                extra_headers=({"Cookie": _captcha[1]} if _captcha and _captcha[1] else None),
                captcha=_captcha[0] if _captcha else None,
            )
        except SrunError as exc:
            return {"ok": False, "msg": str(exc), "username": username, "ip": ip, "resp": {}}

        return _login_outcome(username, ip, resp)
