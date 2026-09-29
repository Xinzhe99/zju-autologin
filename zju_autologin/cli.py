"""无界面的命令行模式（Linux systemd / Windows 任务计划 / SSH 通用）。

核心用法（Linux 一行启用系统级保活）：
    sudo zju-autologin enable -u 学号 -p 密码        # 装服务+写凭据+启动
    zju-autologin status                             # 查看服务与网络状态
    zju-autologin diagnose                           # 一键网络自诊断
    sudo zju-autologin disable                       # 停止并卸载服务

其他：
    zju-autologin check                              # 查询当前在线状态
    zju-autologin login                              # 立即登录一次
    zju-autologin watch [秒] [--config 路径]         # 前台常驻守护
"""

from __future__ import annotations

import getpass
import os
import sys
import time

from zju_autologin import i18n
from zju_autologin.config import Config
from zju_autologin.i18n import tr
from zju_autologin.net import probe_internet
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
    from pathlib import Path

    from zju_autologin.config import append_event, append_file_log

    heartbeat_file = Path(cfg.path).parent / "service.heartbeat"

    def touch_heartbeat() -> None:
        try:
            heartbeat_file.write_text(str(time.time()), encoding="ascii")
        except OSError:
            pass

    seconds = interval or cfg.interval
    print(tr("cli.watching", n=seconds))
    append_file_log(tr("cli.watching", n=seconds))
    touch_heartbeat()
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
        touch_heartbeat()
        time.sleep(seconds)


# ================================================================ systemd 保活

USAGE_ENABLE = """usage: zju-autologin enable -u USER [-p PASS] [options]

  -u, --user USER        学号/工号
  -p, --pass PASS        密码(命令行可见于 ps, 更安全用 --pass-stdin/--pass-env)
      --pass-stdin       从标准输入读密码(echo SECRET | sudo zju-autologin enable -u X --pass-stdin)
      --pass-env VAR     从环境变量读密码(默认 ZJU_PASS)
  -d, --domain SUF       运营商服务后缀(如 @cmcc, 一般留空)
  -i, --interval SEC     检测间隔(默认 60)
      --base-url URL     门户地址(默认 https://net.zju.edu.cn)
      --ac-id ID         ac_id(默认 80)"""


def _read_enable_options(argv: list[str]) -> dict | None:
    """解析 enable 子命令参数; 非法时打印用法返回 None。"""
    opts = {"user": "", "password": "", "domain": "", "interval": 60,
            "base_url": "https://net.zju.edu.cn", "ac_id": "80",
            "pass_stdin": False, "pass_env": "ZJU_PASS"}
    i = 0
    rest = argv
    while i < len(rest):
        a = rest[i]
        if a in ("-u", "--user") and i + 1 < len(rest):
            opts["user"] = rest[i + 1]; i += 2
        elif a in ("-p", "--pass") and i + 1 < len(rest):
            opts["password"] = rest[i + 1]; i += 2
        elif a == "--pass-stdin":
            opts["pass_stdin"] = True; i += 1
        elif a == "--pass-env" and i + 1 < len(rest):
            opts["pass_env"] = rest[i + 1]; i += 2
        elif a in ("-d", "--domain") and i + 1 < len(rest):
            opts["domain"] = rest[i + 1]; i += 2
        elif a in ("-i", "--interval") and i + 1 < len(rest):
            try:
                opts["interval"] = int(rest[i + 1])
            except ValueError:
                pass
            i += 2
        elif a == "--base-url" and i + 1 < len(rest):
            opts["base_url"] = rest[i + 1]; i += 2
        elif a == "--ac-id" and i + 1 < len(rest):
            opts["ac_id"] = rest[i + 1]; i += 2
        else:
            print(f"unknown option: {a}")
            print(USAGE_ENABLE)
            return None
        continue
    return opts


def _require_root() -> bool:
    if not (sys.platform.startswith("linux") or sys.platform == "darwin"):
        print("enable 仅支持 Linux/macOS（Windows 请用 GUI 的系统级保活）")
        return False
    import shutil

    if getattr(os, "geteuid", lambda: -1)() == 0:
        return True
    if shutil.which("pkexec"):
        return True  # 非 root 但有 pkexec: service 层会弹密码框提权
    print("需要 root: 请用 sudo 运行（系统服务要写入 /etc 与 systemd）")
    return False


def cmd_enable(argv: list[str]) -> int:
    import zju_autologin.service as service

    opts = _read_enable_options(argv)
    if opts is None:
        return 2
    if not opts["user"]:
        print(USAGE_ENABLE)
        return 2
    if not _require_root():
        return 2
    # 密码获取: 参数 > stdin > 环境变量 > 交互式提示
    password = opts["password"]
    if not password and opts["pass_stdin"]:
        password = sys.stdin.readline().rstrip("\n")
    if not password:
        password = os.environ.get(opts["pass_env"] or "", "")
    if not password and sys.stdin.isatty():
        password = getpass.getpass("校园网密码: ")
    if not password:
        print("未提供密码: 用 -p / --pass-stdin / --pass-env 或交互输入")
        return 2

    # 凭据写入服务配置（root:600, base64 混淆）
    from zju_autologin.config import _DEFAULTS

    holder = type("Cfg", (), {})()
    holder.data = {k: v for k, v in _DEFAULTS.items()}
    holder.data.update({"username": opts["user"], "domain": opts["domain"],
                        "interval": opts["interval"], "base_url": opts["base_url"],
                        "ac_id": opts["ac_id"]})
    holder.get_password = lambda: password
    try:
        ok, detail = service.install(holder)
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, str(exc)
    if not ok:
        print(f"启用失败: {detail}")
        return 1
    print("✓ 系统级保活已启用（systemd: zju-autologin.service, 开机自启+崩溃自动重启）")
    print("  凭据: /etc/zju-autologin/config.json (root:600)")
    print("  查看状态: zju-autologin status | 日志: journalctl -u zju-autologin -f")
    return 0


def cmd_disable() -> int:
    import zju_autologin.service as service

    if not _require_root():
        return 2
    ok, detail = service.uninstall()
    if not ok:
        print(f"停用失败: {detail}")
        return 1
    print("✓ 已停止并卸载系统级保活（凭据文件已删除）")
    return 0


def cmd_status() -> int:
    import subprocess
    from pathlib import Path

    from zju_autologin.config import service_config_dir

    unit = Path("/etc/systemd/system/zju-autologin.service")
    if not unit.exists():
        print("系统级保活: 未安装（sudo zju-autologin enable -u 学号 -p 密码 启用）")
    else:
        try:
            r = subprocess.run(["systemctl", "is-active", "zju-autologin"],
                               capture_output=True, text=True, timeout=10)
            state = r.stdout.strip() or "unknown"
        except Exception as exc:  # noqa: BLE001
            state = f"查询失败({exc})"
        hb = service_config_dir() / "service.heartbeat"
        beat = "无心跳文件"
        if hb.exists():
            try:
                age = int(time.time() - float(hb.read_text(encoding="ascii").strip()))
                beat = f"{age} 秒前"
            except (OSError, ValueError):
                pass
        print(f"系统级保活: 已安装 | systemd 状态: {state} | 心跳: {beat}")
    # 网络状态（不需要 root）
    cfg = Config(str(service_config_dir() / "config.json")) if unit.exists() else Config()
    return cmd_check(cfg)


def main() -> int:
    argv = sys.argv[1:]
    action = argv[0] if argv else "check"
    rest = argv[1:]

    # enable/disable/status 不走 --config 解析（enable 自带参数体系）
    if action == "enable":
        return cmd_enable(rest)
    if action == "disable":
        return cmd_disable()
    if action == "status":
        return cmd_status()
    if action == "diagnose":
        from zju_autologin.diag import format_report
        cfg = Config()
        i18n.set_lang(cfg.language)
        print(format_report(cfg))
        return 0
    if action in ("version", "--version", "-V"):
        from zju_autologin import __version__
        print(f"zju-autologin {__version__}")
        return 0

    action, interval, cfg_path = _parse_args(argv)
    cfg = Config(path=cfg_path)
    i18n.set_lang(cfg.language)
    if action == "check":
        return cmd_check(cfg)
    if action == "login":
        return cmd_login(cfg)
    if action == "watch":
        return cmd_watch(cfg, interval)
    print(__doc__ or "usage: zju-autologin check|login|watch|enable|disable|status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
