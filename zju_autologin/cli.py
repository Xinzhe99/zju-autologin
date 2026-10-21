"""无界面的命令行模式（Linux systemd / Windows 任务计划 / SSH 通用）。

核心用法（Linux 一行启用系统级保活）：
    sudo zju-autologin enable -u 学号 -p 密码        # 装服务+写凭据+启动
    zju-autologin status                             # 查看服务与网络状态
    zju-autologin diagnose                           # 一键网络自诊断
    zju-autologin serve [--port 8734]                # 无头设备 Web 配置页(仅本机)
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
from zju_autologin.config import Config, service_config_dir
from zju_autologin.i18n import tr
from zju_autologin.net import probe_internet
from zju_autologin.srun import (SrunClient, SrunError, is_auth_rejected,
                                is_transient_portal_error)


def _parse_args(argv: list[str]) -> tuple[str, int | None, str | None, str | None]:
    """解析子命令后的参数, 返回 (action, interval, cfg_path, error)。

    以前未知选项被静默忽略: `--confg x.json` 会不动声色地跑默认配置,
    用户以为读了自己的文件。现在一律报错。
    """
    action = argv[0] if argv else "check"
    interval = None
    cfg_path = None
    rest = argv[1:]
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg in ("--config", "-c"):
            if i + 1 >= len(rest):
                return action, None, None, f"{arg} 需要一个文件路径"
            cfg_path = rest[i + 1]
            i += 2
            continue
        if arg.startswith("-"):
            return action, None, None, f"未知选项: {arg}"
        try:
            interval = int(arg)
        except ValueError:
            return action, None, None, f"无法识别的参数: {arg}"
        i += 1
    return action, interval, cfg_path, None


def _scan_config(argv: list[str]) -> tuple[str | None, str | None]:
    """从子命令参数中取出 --config; 返回 (path, error)。"""
    i = 0
    while i < len(argv):
        if argv[i] in ("--config", "-c"):
            if i + 1 >= len(argv):
                return None, f"{argv[i]} 需要一个文件路径"
            return argv[i + 1], None
        i += 1
    return None, None


def _share_ip_cache(cfg: Config) -> None:
    """让门户 IP 缓存跟随当前配置目录(GUI 与服务模式共用一份)。"""
    from pathlib import Path

    import zju_autologin.srun as srun

    srun.set_cache_dir(Path(cfg.path).parent)


def _load_cli_config(cfg_path: str | None = None, prefer_service: bool = True) -> Config:
    """CLI 用哪份配置: 显式 --config > 已安装的系统级保活 > 用户配置。

    serve/diagnose/check 以前固定读用户配置, 而 systemd/SYSTEM 服务读的是
    /etc 或 ProgramData 下的服务配置 —— 无头设备上用户在网页里填的凭据
    服务永远读不到, 诊断还会建议去填一份服务不读的配置。
    """
    import zju_autologin.service as service

    if cfg_path:
        cfg = Config(path=cfg_path)
        _share_ip_cache(cfg)
        return cfg
    if prefer_service:
        try:
            if service.is_installed(max_age=60):
                svc = service_config_dir() / "config.json"
                if svc.is_file():
                    cfg = Config(str(svc))
                    # 读不出来时不在这里报错: 各子命令入口统一用
                    # _refuse_if_unreadable() 拒绝并给出非零退出码, 避免同一条
                    # 警告打印两遍、也避免拿空配置继续跑
                    _share_ip_cache(cfg)
                    return cfg
        except Exception:  # noqa: BLE001 - 查询服务状态不能拖垮 CLI
            pass
    cfg = Config()
    _share_ip_cache(cfg)
    return cfg


def _refuse_if_unreadable(cfg: Config) -> bool:
    """配置读不出来时明确失败, 不要拿空配置往下跑。

    非提权用户读 SYSTEM 的 ProgramData 配置会 Permission denied; 以前
    check/status 只打一行 stderr 警告就继续, 用空 base_url/无账号的配置去
    探测, 最后还打印一行 [ok] 并 exit 0 —— 用户以为一切正常, 实际什么
    都没查。serve 早就这么拒绝了, 这里对齐。
    """
    if not cfg._load_failed:
        return False
    print(f"[x] 无法读取配置文件 {cfg.path}（权限不足?）", file=sys.stderr)
    print("    请用管理员权限运行，或: zju-autologin <命令> --config <可读路径>",
          file=sys.stderr)
    return True


def cmd_check(cfg: Config) -> int:
    if _refuse_if_unreadable(cfg):
        return 2
    client = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id)
    try:
        status = client.get_status()
    except (SrunError, OSError) as exc:
        print(f"[x] {exc}")
        return 2
    if not status["online"]:
        if status.get("unknown"):
            # 门户没给在线状态但外网通: 这台机器实际是在线的
            if probe_internet():
                print(tr("cli.portal_unknown"))
                return 0
        print(tr("cli.offline_line", state=tr("cli.offline"), url=cfg.base_url))
        return 1
    ok = probe_internet()
    print(tr("cli.ok_line",
             username=status['username'], ip=status['ip'],
             since=status.get('login_time') or '-',
             internet=tr("cli.internet_ok") if ok else tr("cli.internet_bad")))
    return 0 if ok else 1


def cmd_login(cfg: Config) -> int:
    if _refuse_if_unreadable(cfg):
        return 2
    if not cfg.username or not cfg.refresh_password():
        print(tr("cli.config_missing"))
        print(f"    {cfg.path}")
        return 2
    client = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id)
    result = client.login(cfg.username, cfg.get_password(), domain=cfg.domain)
    print((tr("cli.login_ok_prefix") if result["ok"] else tr("cli.login_fail_prefix")) + result["msg"])
    return 0 if result["ok"] else 1


class _WatchState:
    """watch 守护的跨轮状态(退避 / 认证锁存 / 配置热加载)。"""

    def __init__(self) -> None:
        self.fail_count = 0
        self.last_attempt = 0.0
        self.latch_msg = ""        # 认证被拒的原因; 非空即锁存
        self.latch_until = 0.0
        self.cfg_mtime = 0.0
        self.last_note = ""        # 上一条写进 app.log 的提示(去重, 不刷屏)


# 认证被拒后的冷静期: 无界面守护没人点"保存设置"来解除锁存, 所以不能像 GUI 那样
# 永久停手 —— 每小时试一次(远低于任何门户的锁号阈值), 配置文件一改立即解除
_WATCH_LATCH_SECS = 3600


def _watch_reload(cfg: Config, st: _WatchState) -> None:
    """配置文件变化(GUI 同步了新密码 / 手工编辑)时热加载并解除锁存。

    以前 watch 一直用启动时读到的凭据: 改密码后服务进程拿着旧密码每分钟 bind
    一次, 直到重启 —— 门户的账号锁定策略可能因此把账号锁死。
    """
    try:
        mtime = os.path.getmtime(cfg.path)
    except OSError:
        return
    if st.cfg_mtime and mtime != st.cfg_mtime:
        cfg.load()
        st.latch_msg = ""
        st.fail_count = 0
        st.last_attempt = 0.0
    st.cfg_mtime = mtime


def _watch_tick(cfg: Config, st: _WatchState, note) -> str:
    """执行一轮检测/登录, 返回状态: online / offline / no_campus / auth_error。"""
    client = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id)
    try:
        status = client.get_status()
    except (SrunError, OSError) as exc:
        # 门户不可达(不在校园网/网线没插): 登录必然失败, 不再每轮空打一次
        print(f"[x] {exc}")
        return "no_campus"
    if status.get("online"):
        st.fail_count = 0
        st.latch_msg = ""
        ok = probe_internet()
        print(tr("cli.ok_line",
                 username=status.get("username", ""), ip=status.get("ip", ""),
                 since=status.get("login_time") or "-",
                 internet=tr("cli.internet_ok") if ok else tr("cli.internet_bad")))
        return "online"
    if status.get("unknown") and probe_internet():
        # 门户没给出在线状态(如限速), 但外网通 → 视为在线, 不重登真实账号
        st.fail_count = 0
        st.latch_msg = ""
        print(tr("cli.portal_unknown"))
        return "online"
    print(tr("cli.offline_line", state=tr("cli.offline"), url=cfg.base_url))
    if not cfg.username or not cfg.refresh_password():
        # keyring 可能比守护进程晚就绪: 每轮重试一次, 不能永久停在"未配置"
        note(tr("cli.config_missing") + f" {cfg.path}")
        return "offline"
    now = time.time()
    if st.latch_msg and now < st.latch_until:
        return "auth_error"
    # 连续失败指数退避(60s 起步, 封顶 10 分钟), 与 GUI 监控一致
    backoff = min(60 * (2 ** min(st.fail_count, 4)), 600)
    if st.fail_count and now - st.last_attempt < backoff:
        return "offline"
    st.last_attempt = now
    result = client.login(cfg.username, cfg.get_password(), domain=cfg.domain)
    if not result["ok"] and is_transient_portal_error(result.get("resp")):
        # 与 GUI 一致: BAS 应答超时是门户侧临时故障, 2 秒后快速重试一次,
        # 不要落进 60 秒起步的指数退避。系统级保活占保活流量的绝大多数,
        # 1.27.1 只修了 GUI, 服务模式仍会白等一分钟。
        note(tr("log.portal_busy_retry"), dedupe=False)
        time.sleep(2.0)
        result = client.login(cfg.username, cfg.get_password(), domain=cfg.domain)
    line = (tr("cli.login_ok_prefix") if result["ok"]
            else tr("cli.login_fail_prefix")) + tr("cli.auto_relogin", msg=result["msg"])
    print(line)
    note(line, dedupe=False)
    if result["ok"]:
        st.fail_count = 0
        st.latch_msg = ""
        return "online"
    resp = result.get("resp") or {}
    err = str(resp.get("error", ""))
    if is_auth_rejected(resp, str(result.get("msg") or "")):
        st.latch_msg = str(result.get("msg") or err)
        st.latch_until = now + _WATCH_LATCH_SECS
        st.fail_count = 0
        note(tr("cli.auth_latched", msg=st.latch_msg, mins=_WATCH_LATCH_SECS // 60))
        return "auth_error"
    st.fail_count += 1
    return "offline"


def cmd_watch(cfg: Config, interval: int | None) -> int:
    from pathlib import Path

    from zju_autologin.config import append_event, append_file_log

    # 日志/事件写到 --config 所在目录, 与 GUI 的 _log_dir 一致:
    # 服务模式下配置文件在 /etc/zju-autologin(或 ProgramData), 而 append_* 的
    # 默认目录是"当前用户的 config_dir" —— 服务以 root/SYSTEM 运行时会写到
    # /root/.config 或系统配置目录, 用户永远看不到, 排障时等于没有日志。
    log_dir = Path(cfg.path).parent
    heartbeat_file = log_dir / "service.heartbeat"
    st = _WatchState()

    def touch_heartbeat() -> None:
        try:
            heartbeat_file.write_text(str(time.time()), encoding="ascii")
        except OSError:
            pass

    def note(line: str, dedupe: bool = True) -> None:
        if dedupe and line == st.last_note:
            return
        st.last_note = line
        append_file_log(line, log_dir)

    seconds = max(10, min(600, int(interval))) if interval else cfg.interval
    print(tr("cli.watching", n=seconds))
    append_file_log(tr("cli.watching", n=seconds), log_dir)
    touch_heartbeat()
    prev_state = ""
    while True:
        try:
            _watch_reload(cfg, st)
            state = _watch_tick(cfg, st, note)
            if state != prev_state:
                # 事件按 online/offline/no_campus 记录(统计面板与月报按此计数)
                append_event("offline" if state == "auth_error" else state,
                             "cli watch", log_dir)
                if state == "online" and prev_state:
                    st.last_note = ""
                prev_state = state
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

    from zju_autologin import service
    from zju_autologin.config import service_config_dir

    i18n.set_lang(Config().language)  # 别让 status 的输出语言和 check 不一致
    installed = service.is_installed(max_age=0)
    if not installed:
        print("系统级保活: 未安装（sudo zju-autologin enable -u 学号 -p 密码 启用）")
    elif sys.platform.startswith("linux"):
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
    else:
        # macOS LaunchDaemon / Windows 计划任务: 之前一律报"未安装"
        where = "LaunchDaemon" if sys.platform == "darwin" else "计划任务 ZJUAutoLogin"
        print(f"系统级保活: 已安装（{where}）")
    # 网络状态（不需要 root）; 配置读不出来时由 cmd_check 统一拒绝并给出
    # 非零退出码, 这里不再重复打印同一份警告
    cfg = Config(str(service_config_dir() / "config.json")) if installed else Config()
    return cmd_check(cfg)


def main() -> int:
    argv = sys.argv[1:]
    action = argv[0] if argv else "check"
    rest = argv[1:]

    if action in ("-h", "--help", "help"):
        print(__doc__ or "usage: zju-autologin check|login|watch|enable|disable|status")
        return 0
    if action in ("version", "--version", "-V"):
        from zju_autologin import __version__
        print(f"zju-autologin {__version__}")
        return 0

    if action.startswith("-"):
        print(f"未知选项: {action}")
        print(__doc__ or "usage: zju-autologin check|login|watch|enable|disable|status")
        return 2
    i18n.set_lang(Config().language)  # 所有子命令统一语言(含 enable/status/diagnose)

    # enable/disable/status 不走通用 --config 解析（enable 自带参数体系）
    if action == "enable":
        return cmd_enable(rest)
    if action == "disable":
        return cmd_disable()
    if action == "status":
        return cmd_status()
    if action == "serve":
        port = 8734
        cfg_path, err = _scan_config(rest)
        i = 0
        while i < len(rest):
            arg = rest[i]
            if arg in ("--config", "-c"):
                i += 2
                continue
            if arg in ("--port", "-p"):
                if i + 1 >= len(rest):
                    err = f"{arg} 需要一个端口"
                    break
                try:
                    port = int(rest[i + 1])
                except ValueError:
                    err = f"端口不合法: {rest[i + 1]}"
                    break
                i += 2
                continue
            err = f"无法识别的参数: {arg}"
            break
        if err:
            print(err)
            return 2
        if not (1 <= port <= 65535):
            print(f"端口不合法: {port}（应为 1-65535）")
            return 2
        from zju_autologin.webui import cmd_serve
        cfg = _load_cli_config(cfg_path)
        return cmd_serve(cfg, port)
    if action == "diagnose":
        from zju_autologin.diag import format_report
        cfg_path, err = _scan_config(rest)
        if err:
            print(err)
            return 2
        i = 0
        while i < len(rest):
            if rest[i] in ("--config", "-c"):
                i += 2
                continue
            err = f"无法识别的参数: {rest[i]}"
            break
        if err:
            print(err)
            return 2
        cfg = _load_cli_config(cfg_path)
        print(format_report(cfg))
        return 0

    action, interval, cfg_path, err = _parse_args(argv)
    if err:
        print(err)
        print(__doc__ or "usage: zju-autologin check|login|watch|enable|disable|status")
        return 2
    if cfg_path and not os.path.isfile(cfg_path):
        # 手滑写错路径时以前会静默用默认配置跑, 用户看不出"根本没读你的文件"
        print(f"配置文件不存在: {cfg_path}")
        return 2
    cfg = _load_cli_config(cfg_path)
    if action == "check":
        return cmd_check(cfg)
    if action == "login":
        return cmd_login(cfg)
    if action == "watch":
        return cmd_watch(cfg, interval)
    # 未知子命令必须给非零退出码: 以前打印用法后 return 0, 脚本/CI 以为执行成功
    print(__doc__ or "usage: zju-autologin check|login|watch|enable|disable|status")
    return 2


if __name__ == "__main__":
    sys.exit(main())
