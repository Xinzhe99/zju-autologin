"""一键清理本工具对系统做的改动（不删除账号/密码/用户配置）。

覆盖：系统代理例外、门户直连路由、系统级保活任务、GUI 看护任务、开机自启。
每一步独立执行并返回结果，单项失败不会阻断其余步骤。
"""

from __future__ import annotations

from typing import Callable

from .config import Config

STEP_CAMPUS = "campus"
STEP_ROUTE = "route"
STEP_SERVICE = "service"
STEP_WATCHDOG = "watchdog"
STEP_AUTOSTART = "autostart"

STEPS = (STEP_CAMPUS, STEP_ROUTE, STEP_SERVICE, STEP_WATCHDOG, STEP_AUTOSTART)


def _cleanup_campus(cfg: Config) -> tuple[bool, str]:
    from . import campus

    if not cfg.data.get("campus_bypass_applied"):
        return True, ""
    ok = campus.remove_bypass(cfg)
    return bool(ok), "" if ok else "remove failed"


def _cleanup_route(cfg: Config, had_route: bool, ips: list[str]) -> tuple[bool, str]:
    from . import routes

    if not had_route:
        return True, ""
    # 恢复记录过的 IP: 清标志位时已把列表清空, 只靠 portal_ips() 重新解析
    # 可能删错/漏删(门户换了 IP 时旧路由就永远留着)
    cfg.portal_route_ips = list(ips)
    try:
        ok, detail = routes.remove_direct_routes(cfg)
    finally:
        cfg.portal_route_ips = []
    return bool(ok), "" if ok else str(detail)


def _cleanup_service() -> tuple[bool, str]:
    from . import service

    if not service.is_installed(max_age=0):
        return True, ""
    ok, detail = service.uninstall()
    return bool(ok), "" if ok else str(detail)


def _cleanup_watchdog() -> tuple[bool, str]:
    from . import watchdog

    if not watchdog.is_installed():
        return True, ""
    ok = watchdog.uninstall()
    return bool(ok), "" if ok else "remove failed"


def _cleanup_autostart() -> tuple[bool, str]:
    from . import autostart

    ok = autostart.set_enabled(False)
    return bool(ok) and not autostart.is_enabled(), ""


def cleanup(cfg: Config) -> list[tuple[str, bool, str]]:
    """依次清理系统改动；返回 [(step, ok, detail)]。"""
    had_route = bool(cfg.portal_route_added)
    route_ips = list(cfg.portal_route_ips or [])
    # 先关掉开关再清条目：否则校园网监控 3 秒后就会把例外重新写回去。
    cfg.campus_direct = False
    cfg.portal_route_added = False
    cfg.portal_route_ips = []
    cfg.autostart = False
    cfg.save()

    handlers: dict[str, Callable[[], tuple[bool, str]]] = {
        STEP_CAMPUS: lambda: _cleanup_campus(cfg),
        STEP_ROUTE: lambda: _cleanup_route(cfg, had_route, route_ips),
        STEP_SERVICE: _cleanup_service,
        STEP_WATCHDOG: _cleanup_watchdog,
        STEP_AUTOSTART: _cleanup_autostart,
    }
    results: list[tuple[str, bool, str]] = []
    for step in STEPS:
        try:
            ok, detail = handlers[step]()
        except Exception as exc:  # noqa: BLE001 - 单项失败不阻断其余清理
            ok, detail = False, str(exc) or exc.__class__.__name__
        results.append((step, bool(ok), detail))
    return results
