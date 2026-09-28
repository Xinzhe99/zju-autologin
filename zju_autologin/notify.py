"""掉线/恢复推送通知：Bark、Server酱、企业微信机器人、钉钉机器人、SMTP 邮件。

统一入口 send_notification(config, title, body)；网络失败静默返回错误信息，不抛异常。
"""

from __future__ import annotations

import json
import smtplib
import ssl
import urllib.parse
import urllib.request

PROVIDERS = ("none", "bark", "serverchan", "wecom", "dingtalk", "smtp")


def _http_json(url: str, payload: dict | None = None, timeout: float = 6.0) -> tuple[bool, str]:
    try:
        data = None
        headers = {"User-Agent": "ZJU-AutoLogin"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        try:
            result = json.loads(body)
        except ValueError:
            return resp.status < 400, body[:200]
        return resp.status < 400, json.dumps(result, ensure_ascii=False)[:200]
    except Exception as exc:  # noqa: BLE001 - 通知失败不应影响主流程
        return False, str(exc)


def _smtp_send(cfg, title: str, body: str) -> tuple[bool, str]:
    try:
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = cfg.smtp_user
        msg["To"] = cfg.smtp_to
        msg.set_content(body)
        if cfg.smtp_port == 465:
            server = smtplib.SMTP_SSL(cfg.smtp_host, 465, timeout=8)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=8)
            try:
                server.starttls(context=ssl.create_default_context())
            except smtplib.SMTPNotSupportedError:
                pass
        with server:
            if cfg.smtp_user:
                server.login(cfg.smtp_user, cfg.smtp_pass)
            server.send_message(msg)
        return True, "sent"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def send_notification(cfg, title: str, body: str) -> tuple[bool, str]:
    """按配置发送通知，返回 (成功?, 说明)。"""
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
        return _http_json(url)

    if provider == "serverchan":
        url = f"https://sctapi.ftqq.com/{urllib.parse.quote(key)}.send"
        data = urllib.parse.urlencode({"title": title, "desp": body}).encode()
        try:
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=6) as resp:
                return resp.status < 400, resp.read().decode("utf-8", "replace")[:200]
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    if provider == "wecom":
        if not key.startswith("http"):
            return False, "wecom webhook url required"
        return _http_json(key, {"msgtype": "text", "text": {"content": f"{title}\n{body}"}})

    if provider == "dingtalk":
        if not key.startswith("http"):
            return False, "dingtalk webhook url required"
        return _http_json(key, {"msgtype": "text", "text": {"content": f"{title}\n{body}"}})

    if provider == "smtp":
        if not cfg.smtp_host or not cfg.smtp_to:
            return False, "smtp host/to required"
        return _smtp_send(cfg, title, body)

    return False, f"unknown provider: {provider}"
