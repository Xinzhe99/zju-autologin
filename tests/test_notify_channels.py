"""六种推送渠道的请求构造实测：FakeOpener 捕获请求逐字段断言，不发真实网络。

渠道对照（官方格式）：
- Bark:      GET  https://api.day.app/{key}/{title}/{body}     （路径段需 URL 编码）
- Server酱:  POST https://sctapi.ftqq.com/{key}.send           form: title, desp
- 企业微信:  POST webhook  {"msgtype":"text","text":{"content":"..."}}
- 钉钉:      POST webhook  {"msgtype":"text","text":{"content":"..."}}
- 飞书:      POST webhook  {"msg_type":"text","content":{"text":"..."}}
- SMTP:      EmailMessage  Subject/From/To + 正文
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from zju_autologin.config import Config
from zju_autologin.notify import send_notification


class FakeResp:
    status = 200

    def __init__(self, body=b'{"code":0}', status=200):
        self._body, self.status = body, status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    """捕获 open() 收到的请求。"""

    def __init__(self, body=b'{"code":0}', status=200):
        self.sent = None
        self._body, self._status = body, status

    def open(self, req, timeout=None):
        self.sent = {
            "full_url": req.full_url,
            "data": req.data,
            "headers": dict(req.header_items()),
            "method": req.get_method(),
        }
        return FakeResp(self._body, self._status)


def make_cfg(**overrides) -> Config:
    # 不要用 "/tmp/...": Windows 上会解析成当前盘的 \tmp\..., 落到预期之外的位置。
    # 配置目录已由 conftest 沙箱化, 这里给个纯内存路径即可。
    cfg = Config(path=os.path.join(tempfile.gettempdir(), "_zju_notify_test.json"))
    cfg.data["notify_provider"] = "none"
    cfg.data.update(overrides)
    return cfg


def test_bark_url_encoded():
    cfg = make_cfg(notify_provider="bark", notify_key="AbCdEf123")
    opener = FakeOpener()
    ok, _ = send_notification(cfg, "校园网 掉线", "原因: 10053", opener=opener)
    assert ok
    url = opener.sent["full_url"]
    assert url.startswith("https://api.day.app/AbCdEf123/")
    # 路径段必须编码（含空格与中文）
    assert " " not in url and "%" in url


def test_bark_custom_server():
    cfg = make_cfg(notify_provider="bark", notify_key="https://my.bark.local/push")
    opener = FakeOpener()
    ok, _ = send_notification(cfg, "t", "b", opener=opener)
    assert ok and opener.sent["full_url"].startswith("https://my.bark.local/push/")


def test_serverchan_form():
    cfg = make_cfg(notify_provider="serverchan", notify_key="SCT123456")
    opener = FakeOpener()
    ok, _ = send_notification(cfg, "标题t", "正文b", opener=opener)
    assert ok
    assert opener.sent["full_url"] == "https://sctapi.ftqq.com/SCT123456.send"
    assert opener.sent["method"] == "POST"
    body = opener.sent["data"].decode()
    assert "title=" in body and "%E6%A0%87%E9%A2%98t" in body  # 标题t URL 编码


def test_wecom_json():
    cfg = make_cfg(notify_provider="wecom",
                   notify_key="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc")
    opener = FakeOpener()
    ok, _ = send_notification(cfg, "T", "B", opener=opener)
    assert ok
    payload = json.loads(opener.sent["data"])
    assert payload == {"msgtype": "text", "text": {"content": "T\nB"}}


def test_dingtalk_json():
    cfg = make_cfg(notify_provider="dingtalk",
                   notify_key="https://oapi.dingtalk.com/robot/send?access_token=xyz")
    opener = FakeOpener()
    ok, _ = send_notification(cfg, "T", "B", opener=opener)
    assert ok
    payload = json.loads(opener.sent["data"])
    assert payload == {"msgtype": "text", "text": {"content": "T\nB"}}


def test_feishu_json():
    cfg = make_cfg(notify_provider="feishu",
                   notify_key="https://open.feishu.cn/open-apis/bot/v2/hook/tok")
    opener = FakeOpener()
    ok, _ = send_notification(cfg, "T", "B", opener=opener)
    assert ok
    payload = json.loads(opener.sent["data"])
    assert payload == {"msg_type": "text", "content": {"text": "T\nB"}}


def test_wecom_key_missing():
    cfg = make_cfg(notify_provider="wecom", notify_key="not-a-url")
    ok, msg = send_notification(cfg, "t", "b", opener=FakeOpener())
    assert not ok and "webhook" in msg


def test_provider_none_disabled():
    cfg = make_cfg(notify_provider="none", notify_key="whatever")
    ok, _ = send_notification(cfg, "t", "b", opener=FakeOpener())
    assert not ok


def test_smtp_message_fields():
    cfg = make_cfg(notify_provider="smtp", smtp_host="smtp.test.local",
                   smtp_user="a@test.local", smtp_pass="pw", smtp_to="b@test.local")
    server = MagicMock()
    with patch("zju_autologin.notify.smtplib.SMTP_SSL", return_value=server) as cls:
        ok, msg = send_notification(cfg, "校园网告警", "正文内容")
    assert ok and msg == "sent"
    assert cls.call_count == 1
    args, kwargs = cls.call_args
    assert args == ("smtp.test.local", 465)
    assert kwargs["timeout"] == 8
    assert kwargs["context"] is not None  # 显式 SSL context，校验证书
    server.login.assert_called_once_with("a@test.local", "pw")
    sent_msg = server.send_message.call_args[0][0]
    assert sent_msg["Subject"] == "校园网告警"
    assert sent_msg["From"] == "a@test.local"
    assert sent_msg["To"] == "b@test.local"
    assert "正文内容" in sent_msg.get_content()


def test_smtp_port587_uses_starttls():
    cfg = make_cfg(notify_provider="smtp", smtp_host="smtp.test.local",
                   smtp_port=587, smtp_user="a@test.local", smtp_pass="pw",
                   smtp_to="b@test.local")
    server = MagicMock()
    with patch("zju_autologin.notify.smtplib.SMTP", return_value=server) as cls:
        ok, _ = send_notification(cfg, "t", "b")
    assert ok
    cls.assert_called_once_with("smtp.test.local", 587, timeout=8)
    server.starttls.assert_called_once()
