"""绑定源地址连接的管道测试：本地 HTTP 服务器 + 127.0.0.1 源绑定。"""

import http.server
import threading

from zju_autologin.net import _BoundHTTPConnection, bound_opener, candidate_source_ips


def _start_server():
    handler = http.server.BaseHTTPRequestHandler
    handler.log_message = lambda *a, **k: None

    class H(handler):
        def do_GET(self):
            body = b"portal-ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    return srv, th


def test_bound_connection_reaches_local_server():
    srv, th = _start_server()
    try:
        port = srv.server_address[1]
        # 以 127.0.0.1 为源绑定（本机必有, 且可连本地服务器）
        conn = _BoundHTTPConnection("127.0.0.1", port, timeout=3,
                                    source_address=("127.0.0.1", 0))
        conn.request("GET", "/")
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.read() == b"portal-ok"
        conn.close()
    finally:
        srv.server_close()


def test_bound_opener_constructs():
    opener = bound_opener("127.0.0.1")
    assert opener is not None


def test_candidates_exclude_loopback_and_fakeip():
    ips = candidate_source_ips()
    for ip in ips:
        assert not ip.startswith("127.") and not ip.startswith("198.18.")
