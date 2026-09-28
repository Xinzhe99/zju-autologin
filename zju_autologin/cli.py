"""无界面的命令行模式（适合配合 Windows 任务计划 / SSH / 系统级保活）。

用法：
    python cli.py check                      查询当前在线状态
    python cli.py login                      立即登录一次
    python cli.py watch [秒] [--config 路径]  常驻守护（默认间隔取自配置文件）
"""

from __future__ import annotations

import sys
import time

from zju_autologin import i18n
from zju_autologin.config import Config
from zju_autologin.i18n import tr
from zju_autologin.monitor import probe_internet
from zju_autologin.srun import SrunClient, SrunError


def _parse_args(argv: list[str]) -> tuple[str, int | None, str | None]:
    action = argv[0] if argv else "check"
    interval = None
    cfg_path = None
    rest = argv[1:]
    i = 0
    while i < len(rest):
        if rest[i] in ("--config", "-c") and i + 1 < len(rest):
            cfg_path = rest[i + 1]
            i += 2
            continue
        try:
            interval = int(rest[i])
        except ValueError:
            pass
        i += 1
    return action, interval, cfg_path


def cmd_check(cfg: Config) -> int:
    client = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id)
    try:
        status = client.get_status()
    except SrunError as exc:
        print(f"[x] {exc}")
        return 2
    if not status["online"]:
        print(tr("cli.offline_line", state=tr("cli.offline"), url=cfg.base_url))
        return 1
    ok = probe_internet()
    print(tr("cli.ok_line",
             username=status['username'], ip=status['ip'],
             since=status.get('login_time') or '-',
             internet=tr("cli.internet_ok") if ok else tr("cli.internet_bad")))
    return 0 if ok else 1


def cmd_login(cfg: Config) -> int:
    if not cfg.username or not cfg.get_password():
        print(tr("cli.config_missing"))
        print(f"    {cfg.path}")
        return 2
    client = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id)
    result = client.login(cfg.username, cfg.get_password(), domain=cfg.domain)
    print((tr("cli.login_ok_prefix") if result["ok"] else tr("cli.login_fail_prefix")) + result["msg"])
    return 0 if result["ok"] else 1


def cmd_watch(cfg: Config, interval: int | None) -> int:
    from zju_autologin.config import append_event, append_file_log

    seconds = interval or cfg.interval
    print(tr("cli.watching", n=seconds))
    append_file_log(tr("cli.watching", n=seconds))
    prev_state = ""
    while True:
        try:
            code = cmd_check(cfg)
            state = "online" if code == 0 else "offline"
            if state != prev_state:
                append_event(state, "cli watch")
                prev_state = state
            if code != 0:
                result = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id).login(
                    cfg.username, cfg.get_password(), domain=cfg.domain)
                line = (tr("cli.login_ok_prefix") if result["ok"]
                        else tr("cli.login_fail_prefix")) + tr("cli.auto_relogin", msg=result["msg"])
                print(line)
                append_file_log(line)
        except KeyboardInterrupt:
            print(tr("cli.exited"))
            return 0
        except Exception as exc:  # noqa: BLE001 - 守护进程不因单次异常退出
            print(tr("cli.exc", msg=exc))
        time.sleep(seconds)


def main() -> int:
    argv = sys.argv[1:]
    action, interval, cfg_path = _parse_args(argv)
    cfg = Config(path=cfg_path)
    i18n.set_lang(cfg.language)
    if action == "check":
        return cmd_check(cfg)
    if action == "login":
        return cmd_login(cfg)
    if action == "watch":
        return cmd_watch(cfg, interval)
    print("usage: python cli.py check|login|watch [seconds] [--config path]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
