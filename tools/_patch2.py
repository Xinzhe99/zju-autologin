"""一次性补丁：流量快照/记录 + 门户探测（跑完即删）。"""

import ast

# ---- config.py: 每日流量快照 ----
c = open('zju_autologin/config.py', encoding='utf-8').read()
anchor = 'def read_events(limit: int = 200, directory: Path | None = None) -> list[dict]:'
usage_code = '''def append_usage_snapshot(all_bytes: int, directory: Path | None = None) -> None:
    """记录每日流量读数（usage.jsonl，一天一行，保留最近 60 天）。"""
    if all_bytes <= 0:
        return
    try:
        base = directory or config_dir()
        base.mkdir(parents=True, exist_ok=True)
        path = base / "usage.jsonl"
        today = time.strftime("%Y-%m-%d")
        rows: list[dict] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
        rows = [r for r in rows if r.get("date") != today]
        rows.append({"date": today, "bytes": int(all_bytes)})
        rows = rows[-60:]
        tmp = path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + chr(10) for r in rows),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def read_usage(limit: int = 40, directory: Path | None = None) -> list[dict]:
    try:
        path = (directory or config_dir()) / "usage.jsonl"
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows[-limit:]
    except OSError:
        return []


'''
assert "def append_usage_snapshot" not in c
assert c.count(anchor) == 1
c = c.replace(anchor, usage_code + anchor)
open('zju_autologin/config.py', 'w', encoding='utf-8').write(c)
ast.parse(c)

# ---- monitor: 在线时记录快照 ----
m = open('zju_autologin/monitor.py', encoding='utf-8').read()
m = m.replace('from .config import Config, append_event',
              'from .config import Config, append_event, append_usage_snapshot')
m = m.replace('''        self._last_heartbeat = 0.0
        self._battery_mode_on = False''',
'''        self._last_heartbeat = 0.0
        self._usage_date = ""
        self._battery_mode_on = False''')
m = m.replace('''            # 已认证：校验外网连通性
            if probe_internet():
                self._fail_count = 0
                self._auth_error = ""
                self._ping_heartbeat()''',
'''            # 已认证：校验外网连通性
            if probe_internet():
                self._fail_count = 0
                self._auth_error = ""
                self._ping_heartbeat()
                all_bytes = int(status.get("all_bytes") or 0)
                if all_bytes > 0:
                    today = time.strftime("%Y-%m-%d")
                    if today != self._usage_date:
                        self._usage_date = today
                        append_usage_snapshot(all_bytes, self._log_dir)''')
open('zju_autologin/monitor.py', 'w', encoding='utf-8').write(m)
ast.parse(m)

# ---- srun: 门户配置解析 + 探测 ----
s = open('zju_autologin/srun.py', encoding='utf-8').read()
old_ip = '''    def get_portal_ip(self) -> str:
        """从门户首页 CONFIG 里读取服务端识别到的本机 IP（最可靠）。"""
        body = self._get("/index_1.html", {})
        match = re.search(r"ip\\s*:\\s*\\"(\\d{1,3}(?:\\.\\d{1,3}){3})\\"", body)
        return match.group(1) if match else ""'''
new_code = '''    def parse_portal_config(self) -> dict:
        """从门户首页 CONFIG 块解析 acid 与服务端识别的本机 IP。"""
        body = self._get("/index_1.html", {})
        result = {"acid": "", "ip": ""}
        match = re.search(r"ip\\s*:\\s*\\"(\\d{1,3}(?:\\.\\d{1,3}){3})\\"", body)
        if match:
            result["ip"] = match.group(1)
        match = re.search(r'acid\\s*:\\s*"?(\\w+)"?', body)
        if match:
            result["acid"] = match.group(1)
        return result

    def get_portal_ip(self) -> str:
        """从门户首页 CONFIG 里读取服务端识别到的本机 IP（最可靠）。"""
        return self.parse_portal_config().get("ip", "")

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
        return {"ok": ok, "acid": acid, "ip": ip, "challenge_ok": challenge_ok, "msg": msg}'''
assert s.count(old_ip) == 1, s.count(old_ip)
s = s.replace(old_ip, new_code)
open('zju_autologin/srun.py', 'w', encoding='utf-8').write(s)
ast.parse(s)
print("patched OK")
