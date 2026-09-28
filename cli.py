"""无界面的命令行模式（适合配合 Windows 任务计划 / SSH 场景）。

用法：
    python cli.py check          查询当前在线状态
    python cli.py login          立即登录一次
    python cli.py watch [秒]     常驻守护（默认间隔取自配置文件）
"""

from __future__ import annotations

import sys
import time

from zju_autologin.config import Config
from zju_autologin.monitor import probe_internet
from zju_autologin.srun import SrunClient, SrunError

STATE_TEXT = {
    "online": "已认证，外网可用",
    "authed_no_internet": "已认证，但外网不可用",
    "offline": "门户可达，未认证",
    "no_campus": "门户不可达（不在校园网或网络未连接）",
}


def cmd_check(cfg: Config) -> int:
    client = SrunClient(base_url=cfg.base_url)
    try:
        status = client.get_status()
    except SrunError as exc:
        print(f"[x] {exc}")
        return 2
    if not status["online"]:
        print(f"[!] {STATE_TEXT['offline']}  base_url={cfg.base_url}")
        return 1
    ok = probe_internet()
    print(f"[ok] 在线  账号={status['username']}  IP={status['ip']}  "
          f"上线时间={status.get('login_time') or '-'}  外网={'正常' if ok else '不可用'}")
    return 0 if ok else 1


def cmd_login(cfg: Config) -> int:
    if not cfg.username or not cfg.get_password():
        print("[x] 尚未配置账号密码，请先运行 GUI 版保存设置，或手动编辑：")
        print(f"    {cfg.path}")
        return 2
    client = SrunClient(base_url=cfg.base_url)
    result = client.login(cfg.username, cfg.get_password(), domain=cfg.domain)
    print(("[ok] " if result["ok"] else "[x] ") + result["msg"])
    return 0 if result["ok"] else 1


def cmd_watch(cfg: Config, interval: int | None) -> int:
    seconds = interval or cfg.interval
    print(f"守护模式启动，每 {seconds} 秒检测一次（Ctrl+C 退出）")
    while True:
        try:
            code = cmd_check(cfg)
            if code != 0:
                result = SrunClient(base_url=cfg.base_url).login(
                    cfg.username, cfg.get_password(), domain=cfg.domain)
                print(("[ok] 自动登录：" if result["ok"] else "[x] 自动登录失败：") + result["msg"])
        except KeyboardInterrupt:
            print("已退出")
            return 0
        except Exception as exc:  # noqa: BLE001 - 守护进程不因单次异常退出
            print(f"[x] {exc}")
        time.sleep(seconds)


def main() -> int:
    cfg = Config()
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    if action == "check":
        return cmd_check(cfg)
    if action == "login":
        return cmd_login(cfg)
    if action == "watch":
        interval = int(sys.argv[2]) if len(sys.argv) > 2 else None
        return cmd_watch(cfg, interval)
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
