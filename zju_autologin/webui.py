"""无头设备迷你 Web 配置页（仅绑定 127.0.0.1, 纯标准库）。

用法: zju-autologin serve [--port 8734] [--config 路径]
启动后终端会打印带一次性 token 的地址, 用浏览器打开该地址修改配置。
已安装系统级保活时默认编辑服务配置(否则编辑用户配置)。
安全性: 仅回环可访问; 写操作需启动时打印的 token, 防同机其他用户改写凭据。
"""

from __future__ import annotations

import html
import json
import secrets
import sys
import urllib.parse
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Config
from .i18n import set_lang, tr
from .srun import SrunClient


def _stat_js() -> str:
    """实时状态面板脚本; 打包漏带该静态文件时降级为空(配置功能不受影响)。"""
    try:
        return (Path(__file__).parent / "webui_stat.js").read_text(encoding="utf-8")
    except OSError:
        return ""


def _page(cfg: Config, msg: str = "", username: str | None = None,
          token: str = "") -> str:
    safe_user = html.escape(cfg.username if username is None else username)
    safe_domain = html.escape(cfg.domain)
    safe_portal = html.escape(cfg.base_url)
    safe_path = html.escape(str(cfg.path))
    note = f"<p class='msg'>{html.escape(msg)}</p>" if msg else ""
    # 占位文案必须反映真实状态: 全新设备上写"已保存则留空"会诱导用户
    # 不填密码直接提交, 保存成功却永远登录不上。
    pwd_ph = "留空则保留已保存的密码" if cfg.get_password() else "必填"
    token_input = (f'<input type="hidden" name="token" value="{html.escape(token)}">'
                   if token else "")
    token_js = f'<script>window.__ZJU_TOKEN={json.dumps(token)};</script>' if token else ""
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
{token_input}
<label>学号/账号</label><input name="username" value="{safe_user}" required>
<label>密码</label><input name="password" type="password" placeholder="{pwd_ph}">
<label>运营商后缀(可空)</label><input name="domain" value="{safe_domain}">
<label>门户地址</label><input name="base_url" value="{safe_portal}">
<button type="submit">保存并立即检测</button>
</form>
<p style="color:#666;font-size:12px">当前配置文件：<code>{safe_path}</code></p>
__STAT_BLOCK__
<p style="color:#888;font-size:12px">仅本机 127.0.0.1 可访问 · 启用系统级保活请在终端
<code>sudo zju-autologin enable</code></p>
{token_js}
</body></html>""".replace("__STAT_BLOCK__", _stat_js())


def _status_json(cfg: Config) -> str:
    """实时状态(只读): 在线状态/延迟/今日掉线/最近事件。"""
    import time as _t

    from .config import read_events
    from .srun import SrunClient, SrunError
    from .net import probe_internet

    info = {"ts": _t.time(), "online": False, "latency_ms": None, "drops_today": 0,
            "recent": [], "internet": False}
    try:
        st = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id, timeout=4.0).get_status()
        info["online"] = bool(st.get("online"))
        info["latency_ms"] = st.get("latency_ms")
        info["ip"] = st.get("ip", "")
        if info["online"]:
            info["internet"] = probe_internet(timeout=3.0)
    except SrunError:
        pass
    today = _t.strftime("%Y-%m-%d")
    # 与服务同目录: 无头设备的事件写在 <config>/events.jsonl, 不是调用者的
    # 用户配置目录。以前这里读默认目录, "今日掉线"永远显示 0。
    events = read_events(5000, cfg.log_dir)
    info["recent"] = [
        {"time": _t.strftime("%m-%d %H:%M:%S", _t.localtime(e.get("ts") or 0)),
         "event": e.get("event", ""), "detail": str(e.get("detail", ""))[:40]}
        for e in events[-10:]]
    info["drops_today"] = sum(
        1 for e in events
        if e.get("event") in ("offline", "no_campus")
        and _t.strftime("%Y-%m-%d", _t.localtime(e.get("ts") or 0)) == today)
    return json.dumps(info, ensure_ascii=False)


MAX_BODY = 64 * 1024


def _local_hosts(port: int) -> set[str]:
    return {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}", "127.0.0.1", "localhost"}


class _Server(ThreadingHTTPServer):
    """Windows 上 SO_REUSEADDR 允许两个进程绑同一端口(互相劫持);

    配置页必须独占端口, 否则第二次 serve 会静默"成功"但请求落到另一个实例。
    """
    allow_reuse_address = sys.platform != "win32"


def make_handler(cfg: Config, token: str = "") -> type:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # 静默
            pass

        def _send_page(self, body: str, status: int = 200) -> None:
            raw = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _local_request(self) -> bool:
            """只认本机来源: 防 DNS rebinding(恶意域名解析到 127.0.0.1)与跨站表单写入。

            仅绑定回环还不够 —— 浏览器会替攻击者页面把请求送到 127.0.0.1,
            所以必须自己校验 Host 与 Origin/Referer。
            """
            port = self.server.server_port
            host = (self.headers.get("Host") or "").strip().lower()
            if host and host not in _local_hosts(port):
                return False
            origin = (self.headers.get("Origin") or "").strip().lower()
            if origin:
                return any(origin == f"http://{h}" for h in _local_hosts(port))
            referer = (self.headers.get("Referer") or "").strip().lower()
            if referer:
                return any(referer.startswith(f"http://{h}/") for h in _local_hosts(port))
            return True  # 非浏览器客户端(curl 等)无这两个头

        def _token_ok(self, value: str | None) -> bool:
            """启动时生成的一次性 token; 防止同机其他用户 curl 改写凭据。"""
            if not token:
                return True  # 测试/嵌入式使用
            return bool(value) and secrets.compare_digest(str(value), token)

        def _query_token(self) -> str:
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return (query.get("t") or [""])[0]

        def do_GET(self) -> None:  # noqa: N802
            if not self._local_request():
                self.send_error(403, "forbidden")
                return
            path = urllib.parse.urlsplit(self.path).path
            if path == "/api/status":
                if not self._token_ok(self._query_token()):
                    self.send_error(403, "bad token")
                    return
                body = _status_json(cfg).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path != "/":
                self.send_error(404)
                return
            if not self._token_ok(self._query_token()):
                self._send_page(
                    "<h1>需要访问令牌</h1><p>请使用启动时终端里打印的完整地址"
                    "（包含 <code>?t=...</code>）打开本页。</p>", 403)
                return
            self._send_page(_page(cfg, token=token))

        def do_POST(self) -> None:  # noqa: N802
            if urllib.parse.urlsplit(self.path).path != "/save":
                self.send_error(404)
                return
            if not self._local_request():
                self.send_error(403, "forbidden")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length < 0 or length > MAX_BODY:
                self.send_error(413, "too large")
                return
            data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            supplied_token = (data.get("token", [""])[0] or "") or self._query_token()
            if not self._token_ok(supplied_token):
                self.send_error(403, "bad token")
                return
            new_user = (data.get("username", [""])[0] or "").strip()
            pwd = (data.get("password", [""])[0] or "")
            if not new_user:
                self._send_page(_page(cfg, tr("web.need_username"), username=new_user,
                                      token=token))
                return
            if not pwd and not cfg.get_password():
                self._send_page(_page(cfg, tr("web.need_password"), username=new_user,
                                      token=token))
                return
            if (not pwd and cfg.get_password()
                    and new_user != cfg.username.strip()):
                # 改了学号却沿用旧密码: 旧密码属于旧账号, 门户会一直报认证被拒。
                body = _page(cfg, tr("web.account_pwd_needed"), username=new_user,
                             token=token)
                self._send_page(body)
                return
            cfg.username = new_user
            cfg.domain = (data.get("domain", [""])[0] or "").strip()
            cfg.base_url = (data.get("base_url", [""])[0] or "").strip() or cfg.base_url
            if pwd:
                cfg.set_password(pwd)
            saved = cfg.save()
            if not saved:
                # 写盘失败必须如实告诉用户, 不能显示"已保存"然后重启丢配置
                self._send_page(_page(cfg, tr("web.save_failed"), token=token))
                return
            # 保存后立即探测
            try:
                status = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id).get_status()
                if status.get("online"):
                    msg = tr("web.saved_online")
                else:
                    msg = tr("web.saved_offline")
            except Exception as exc:  # noqa: BLE001
                msg = tr("web.saved_portal_err", err=str(exc)[:60])
            self._send_page(_page(cfg, msg, token=token))

    return Handler


def cmd_serve(cfg: Config, port: int) -> int:
    set_lang(cfg.language)
    if cfg._load_failed:
        print(f"无法读取配置文件: {cfg.path}（权限不足?）")
        print("请用 sudo 运行，或: zju-autologin serve --config <可读路径>")
        return 1
    # 一次性 token: 同机其他用户/进程即使能访问 127.0.0.1 也无法改写凭据。
    # 只能从启动它的终端看到; 页面里的表单与状态接口都校验它。
    token = secrets.token_urlsafe(18)
    try:
        server = _Server(("127.0.0.1", port), make_handler(cfg, token))
    except OSError as exc:
        print(f"无法监听 127.0.0.1:{port}: {exc}")
        print("端口被占用? 换一个: zju-autologin serve --port 8735")
        return 1
    url = f"http://127.0.0.1:{port}/?t={token}"
    print(f"Web 配置页: {url}")
    print(f"配置文件: {cfg.path}")
    print("只在本机可用；请不要把上面的地址（含 token）发给别人。Ctrl+C 退出。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0
