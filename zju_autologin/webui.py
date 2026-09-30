"""无头设备迷你 Web 配置页（仅绑定 127.0.0.1, 纯标准库）。

用法: zju-autologin serve [--port 8734]
浏览器打开 http://127.0.0.1:8734 查看/修改配置并启用保活。
安全性: 仅本机回环可访问; 写操作需页面内确认。
"""

from __future__ import annotations

import html
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .i18n import set_lang, tr
from .srun import SrunClient


def _page(cfg: Config, msg: str = "") -> str:
    safe_user = html.escape(cfg.username)
    safe_domain = html.escape(cfg.domain)
    safe_portal = html.escape(cfg.base_url)
    note = f"<p class='msg'>{html.escape(msg)}</p>" if msg else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>ZJU AutoLogin</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:520px;margin:48px auto;padding:0 16px;color:#1c2b41}}
h1{{font-size:20px}} label{{display:block;margin:12px 0 4px;color:#666;font-size:13px}}
input{{width:100%;padding:8px;border:1px solid #ccc;border-radius:8px;box-sizing:border-box}}
button{{margin-top:16px;padding:9px 22px;border:none;border-radius:8px;background:#0d0d0d;color:#fff;cursor:pointer}}
.msg{{background:#e8f5e9;padding:8px 12px;border-radius:8px}}
code{{background:#f4f4f4;padding:2px 6px;border-radius:4px}}
</style></head><body>
<h1>ZJU AutoLogin · Web 配置</h1>{note}
<form method="post" action="/save">
<label>学号/账号</label><input name="username" value="{safe_user}" required>
<label>密码</label><input name="password" type="password" placeholder="(已保存则留空)">
<label>运营商后缀(可空)</label><input name="domain" value="{safe_domain}">
<label>门户地址</label><input name="base_url" value="{safe_portal}">
<button type="submit">保存并立即检测</button>
</form>
<p style="color:#888;font-size:12px">仅本机 127.0.0.1 可访问 · 启用系统级保活请在终端
<code>sudo zju-autologin enable</code></p>
</body></html>"""


def make_handler(cfg: Config) -> type:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # 静默
            pass

        def do_GET(self) -> None:  # noqa: N802
            if urllib.parse.urlsplit(self.path).path != "/":
                self.send_error(404)
                return
            body = _page(cfg).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            if urllib.parse.urlsplit(self.path).path != "/save":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", 0))
            data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            cfg.username = (data.get("username", [""])[0] or "").strip()
            cfg.domain = (data.get("domain", [""])[0] or "").strip()
            cfg.base_url = (data.get("base_url", [""])[0] or "").strip() or cfg.base_url
            pwd = (data.get("password", [""])[0] or "")
            if pwd:
                cfg.set_password(pwd)
            cfg.save()
            # 保存后立即探测
            try:
                status = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id).get_status()
                if status.get("online"):
                    msg = tr("web.saved_online")
                else:
                    msg = tr("web.saved_offline")
            except Exception as exc:  # noqa: BLE001
                msg = tr("web.saved_portal_err", err=str(exc)[:60])
            body = _page(cfg, msg).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def cmd_serve(cfg: Config, port: int) -> int:
    set_lang(cfg.language)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg))
    print(f"Web 配置页: http://127.0.0.1:{port} (Ctrl+C 退出)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0
