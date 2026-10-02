"""DDNS 动态域名：IP 变化时自动更新 DNS 解析（Cloudflare / 阿里云 DNS）。

远程桌面/SSH 用户的核心痛点：校园网 DHCP 换 IP 后目标失联。本模块在
网卡监视器检测到 IP 变化、或登录成功拿到新 IP 时，把当前公网/内网 IP
推送到 DNS 服务商，保证 `lab.example.com` 始终指向这台机器。

支持的服务商:
- cloudflare: 需要 API Token(Zone:DNS:Edit 权限) + Zone ID + 域名
- aliyun:     需要 AccessKey ID/Secret + 域名(解析在默认 Zone 查询)

纯标准库; 失败静默记日志, 绝不影响保活主流程。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request



def ddns_enabled(cfg) -> bool:
    return bool(cfg.ddns_provider != "off" and cfg.ddns_domain and cfg.ddns_secret)


def _http_json(url: str, payload: dict | None = None, headers: dict | None = None,
               method: str = "GET", timeout: float = 10.0) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, (json.loads(body) if body.strip().startswith(("{", "[")) else {})
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        try:
            return exc.code, json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return exc.code, {}
    except Exception:  # noqa: BLE001
        return 0, {}


# ---------------------------------------------------------------- Cloudflare

def _cf_headers(cfg) -> dict:
    return {"Authorization": f"Bearer {cfg.ddns_secret}"}


def _cf_zone_id(cfg) -> str:
    return (cfg.ddns_token or "").strip()


def _cf_find_record(cfg, host: str) -> tuple[str, str] | None:
    """返回 (record_id, current_ip) 或 None。"""
    zone = _cf_zone_id(cfg)
    if not zone:
        return None
    name = host.split(".")[0]
    status, data = _http_json(
        f"https://api.cloudflare.com/client/v4/zones/{zone}/dns_records"
        f"?type={'AAAA' if ':' in (cfg._ddns_last_ip or '') else 'A'}&name={urllib.parse.quote(host)}",
        headers=_cf_headers(cfg))
    if status == 200 and data.get("result"):
        rec = data["result"][0]
        return rec["id"], rec.get("content", "")
    return None


def update_cloudflare(cfg, host: str, ip: str) -> tuple[bool, str]:
    zone = _cf_zone_id(cfg)
    if not zone:
        return False, "missing zone id (ddns_token)"
    rec_type = "AAAA" if ":" in ip else "A"
    status, data = _http_json(
        f"https://api.cloudflare.com/client/v4/zones/{zone}/dns_records"
        f"?type={rec_type}&name={urllib.parse.quote(host)}",
        headers=_cf_headers(cfg))
    if status != 200 or not data.get("result"):
        return False, f"query failed: HTTP {status}"
    rec = data["result"][0]
    if rec.get("content") == ip:
        return True, "unchanged"
    status, data = _http_json(
        f"https://api.cloudflare.com/client/v4/zones/{zone}/dns_records/{rec['id']}",
        payload={"type": rec_type, "name": host, "content": ip, "ttl": 60, "proxied": False},
        headers=_cf_headers(cfg), method="PUT")
    if status == 200 and data.get("success"):
        return True, "updated"
    return False, f"update failed: HTTP {status} {json.dumps(data)[:120]}"


# ------------------------------------------------------------------ 阿里云

def _ali_sign(cfg, params: dict) -> dict:
    """阿里云 DNS OpenAPI 签名(RPC 风格, HMAC-SHA1)。"""
    import base64
    import hashlib
    import hmac

    access_id = (cfg.ddns_token or "").strip()
    secret = (cfg.ddns_secret or "").strip()
    common = {
        "Format": "JSON", "Version": "2015-01-09", "AccessKeyId": access_id,
        "SignatureMethod": "HMAC-SHA1", "SignatureVersion": "1.0",
        "SignatureNonce": str(int(__import__("time").time() * 1000)),
        "Timestamp": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
    }
    all_p = {**common, **params}
    query = "&".join(f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
                     for k, v in sorted(all_p.items()))
    sign_str = f"GET&%2F&{urllib.parse.quote(query, safe='')}"
    sig = base64.b64encode(
        hmac.new((secret + "&").encode(), sign_str.encode(), hashlib.sha1).digest()).decode()
    all_p["Signature"] = sig
    return all_p


def update_aliyun(cfg, host: str, ip: str) -> tuple[bool, str]:
    rr, _, domain = host.partition(".")
    if not domain:
        return False, "host must be like sub.example.com"
    # 查记录 ID
    p = _ali_sign(cfg, {"Action": "DescribeSubDomainRecords",
                        "SubDomain": host, "Type": "A"})
    status, data = _http_json(
        "https://alidns.aliyuncs.com/?" + urllib.parse.urlencode(p))
    if status != 200:
        return False, f"query failed: HTTP {status} {json.dumps(data)[:120]}"
    records = data.get("DomainRecords", {}).get("Record", [])
    if not records:
        p2 = _ali_sign(cfg, {"Action": "AddDomainRecord", "DomainName": domain,
                             "RR": rr, "Type": "A", "Value": ip})
        status, data = _http_json(
            "https://alidns.aliyuncs.com/?" + urllib.parse.urlencode(p2))
        return (status == 200, f"add: HTTP {status}" if status != 200 else "created")
    rec = records[0]
    if rec.get("Value") == ip:
        return True, "unchanged"
    p3 = _ali_sign(cfg, {"Action": "UpdateDomainRecord", "RecordId": rec["RecordId"],
                          "RR": rr, "Type": "A", "Value": ip})
    status, data = _http_json(
        "https://alidns.aliyuncs.com/?" + urllib.parse.urlencode(p3))
    return (status == 200, f"update: HTTP {status}" if status != 200 else "updated")


# ------------------------------------------------------------------ 入口

def push_ddns(cfg, ip: str) -> tuple[bool, str]:
    """把 ip 更新到配置的域名。由 monitor 在 IP 变化/登录成功时调用。"""
    if not ip or not ddns_enabled(cfg):
        return False, "disabled"
    host = cfg.ddns_domain.strip()
    provider = cfg.ddns_provider
    if provider == "cloudflare":
        return update_cloudflare(cfg, host, ip)
    if provider == "aliyun":
        return update_aliyun(cfg, host, ip)
    return False, f"unknown provider {provider}"
