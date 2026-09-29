"""掉线/恢复推送通知：Bark、Server酱、企业微信机器人、钉钉机器人、SMTP 邮件。

统一入口 send_notification(config, title, body)；网络失败静默返回错误信息，不抛异常。
"""

from __future__ import annotations

import json
import smtplib
import ssl
import urllib.parse
import urllib.request

PROVIDERS = ("none", "bark", "serverchan", "wecom", "dingtalk", "feishu", "smtp")

import re as _re

_URL_RE = _re.compile(r"https?://\S+")


def _sanitize_error(text: str) -> str:
    """异常文本常含完整 URL(webhook 携带 sendkey/token), 入日志前替换为域名。"""
    def _mask(match: "_re.Match[str]") -> str:
        url = match.group(0)
        host = url.split("//", 1)[-1].split("/", 1)[0]
        return f"<{host}>"
    return _URL_RE.sub(_mask, text)


def _http_json(url: str, payload: dict | None = None, timeout: float = 6.0,
               opener: urllib.request.OpenerDirector | None = None) -> tuple[bool, str]:
    try:
        data = None
        headers = {"User-Agent": "ZJU-AutoLogin"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers)
        if opener is None:
            opener = urllib.request.build_opener()
        with opener.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(body)
        except ValueError:
            return resp.status < 400, body[:200]
        detail = json.dumps(result, ensure_ascii=False)[:200]
        if isinstance(result, dict):
            # 企业微信/钉钉/飞书 errcode≠0 的 200 也是失败；Bark 成功为 code=200
            code = result.get("errcode")
            if code is None:
                code = result.get("code")
                if code == 200:
                    code = 0
            if isinstance(code, (int, float)) and code != 0:
                return False, detail
        return resp.status < 400, detail
    except Exception as exc:  # noqa: BLE001 - 通知失败不应影响主流程
        return False, _sanitize_error(str(exc))


def _smtp_send(cfg, title: str, body: str) -> tuple[bool, str]:
    try:
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = cfg.smtp_user
        msg["To"] = cfg.smtp_to
        msg.set_content(body)
        if cfg.smtp_port == 465:
            server = smtplib.SMTP_SSL(cfg.smtp_host, 465, timeout=8,
                                      context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=8)
            try:
                server.starttls(context=ssl.create_default_context())
            except smtplib.SMTPNotSupportedError:
                # 明文降级会把授权码暴露给链路窃听者, 拒绝而非静默继续
                server.quit()
                return False, "STARTTLS not supported by server"
        with server:
            if cfg.smtp_user:
                server.login(cfg.smtp_user, cfg.smtp_pass)
            server.send_message(msg)
        return True, "sent"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def send_notification(cfg, title: str, body: str,
                      opener: urllib.request.OpenerDirector | None = None) -> tuple[bool, str]:
    """按配置发送通知，返回 (成功?, 说明)。opener 控制代理路由。"""
    provider = getattr(cfg, "notify_provider", "none") or "none"
    key = (getattr(cfg, "notify_key", "") or "").strip()
    if provider == "none":
        return False, "notify disabled"

    if provider == "bark":
        # key 支持填设备 key 或自建服务完整地址
        if key.startswith("http"):
            base = key.rstrip("/")
            url = f"{base}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
        else:
            url = ("https://api.day.app/" + urllib.parse.quote(key)
                   + f"/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}")
        return _http_json(url, opener=opener)

    if provider == "serverchan":
        url = f"https://sctapi.ftqq.com/{urllib.parse.quote(key)}.send"
        data = urllib.parse.urlencode({"title": title, "desp": body}).encode()
        try:
            req = urllib.request.Request(url, data=data)
            if opener is None:
                opener = urllib.request.build_opener()
            with opener.open(req, timeout=6) as resp:
                return resp.status < 400, resp.read().decode("utf-8", "replace")[:200]
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    if provider == "wecom":
        if not key.startswith("http"):
            return False, "wecom webhook url required"
        return _http_json(key, {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}, opener=opener)

    if provider == "dingtalk":
        if not key.startswith("http"):
            return False, "dingtalk webhook url required"
        return _http_json(key, {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}, opener=opener)

    if provider == "feishu":
        if not key.startswith("http"):
            return False, "feishu webhook url required"
        return _http_json(key, {"msg_type": "text", "content": {"text": f"{title}\n{body}"}},
                          opener=opener)

    if provider == "smtp":
        if not cfg.smtp_host or not cfg.smtp_to:
            return False, "smtp host/to required"
        return _smtp_send(cfg, title, body)

    return False, f"unknown provider: {provider}"
