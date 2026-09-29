"""网络自诊断：一键回答"为什么上不了网"，输出 问题→原因→建议 报告。

诊断序列（由浅入深）：
  1. 系统代理设置     → 代理可能劫持门户连接
  2. 门户可达性       → 是否在校园网内 / 门户是否响应
  3. 认证状态         → 在线 / 离线
  4. （离线）登录测试 → 密码错误 / 设备超限 / 门户拒绝
  5. （在线）外网探测 → 已认证但无外网（DNS/计费/劫持）
  6. 网卡与路由概览   → 供报告附带环境信息

纯标准库 + srun 客户端, CLI 与 GUI 共用。
"""

from __future__ import annotations

import urllib.request

from .config import Config
from .i18n import tr
from .net import candidate_source_ips
from .srun import SrunClient, SrunError


def _proxy_env() -> list[str]:
    """可见的系统/环境代理（仅报告, 不改变行为）。"""
    import os

    found = []
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy"):
        val = os.environ.get(var)
        if val:
            found.append(f"{var}={val}")
    try:
        proxies = urllib.request.getproxies()
        for scheme, url in proxies.items():
            found.append(f"{scheme}={url}")
    except Exception:  # noqa: BLE001
        pass
    return sorted(set(found))


def run_diagnosis(cfg: Config) -> tuple[str, list[dict]]:
    """执行诊断。返回 (总结论文本, 明细行列表[{"item","result","advice"}])。"""
    rows: list[dict] = []

    def row(item: str, result: str, advice: str = "") -> None:
        rows.append({"item": item, "result": result, "advice": advice})

    # 1) 系统代理
    proxies = _proxy_env()
    if proxies:
        row(tr("diag.proxy"), ", ".join(proxies[:3]),
            tr("diag.proxy_advice"))
    else:
        row(tr("diag.proxy"), tr("diag.none"))

    client = SrunClient(base_url=cfg.base_url, ac_id=cfg.ac_id)

    # 2) 门户可达性
    try:
        status = client.get_status()
        row(tr("diag.portal"), tr("diag.portal_ok"),
            tr("diag.portal_latency", ms=status.get("latency_ms", "?")))
    except SrunError as exc:
        row(tr("diag.portal"), tr("diag.portal_fail", err=str(exc)[:80]),
            tr("diag.portal_fail_advice", base_url=cfg.base_url))
        return tr("diag.summary_no_portal"), rows

    # 3) 认证状态
    if not status.get("online"):
        # 4) 登录测试
        if not cfg.username or not cfg.get_password():
            row(tr("diag.auth"), tr("diag.offline_no_cred"),
                tr("diag.offline_no_cred_advice"))
            return tr("diag.summary_no_cred"), rows
        row(tr("diag.auth"), tr("diag.offline"))
        result = client.login(cfg.username, cfg.get_password(), domain=cfg.domain)
        err = str(result.get("resp", {}).get("error", ""))
        if result.get("ok"):
            row(tr("diag.login_test"), tr("diag.login_test_ok"))
            return tr("diag.summary_login_ok"), rows
        if err == "E2620":
            row(tr("diag.login_test"), tr("diag.login_test_limit"),
                tr("diag.login_test_limit_advice"))
            return tr("diag.summary_limit"), rows
        if err in ("password_error", "E1002", "username_error",
                   "user_must_modify_password"):
            row(tr("diag.login_test"), result.get("msg", err),
                tr("diag.login_test_cred_advice"))
            return tr("diag.summary_cred"), rows
        row(tr("diag.login_test"), result.get("msg", err),
            tr("diag.login_test_other_advice"))
        return tr("diag.summary_other"), rows

    # 5) 已认证 → 外网探测
    row(tr("diag.auth"), tr("diag.online"),
        tr("diag.online_detail", user=status.get("username", ""),
           ip=status.get("ip", "")))
    from .monitor import probe_internet
    if probe_internet():
        row(tr("diag.internet"), tr("diag.internet_ok"))
        return tr("diag.summary_all_ok"), rows
    row(tr("diag.internet"), tr("diag.internet_fail"),
        tr("diag.internet_fail_advice"))
    return tr("diag.summary_no_internet"), rows


def format_report(cfg: Config) -> str:
    """生成纯文本诊断报告（CLI 输出 / GUI 弹窗 / 复制诊断 共用）。"""
    from . import __version__

    summary, rows = run_diagnosis(cfg)
    lines = [
        f"== ZJU-AutoLogin v{__version__} " + tr("diag.title") + " ==",
        summary,
        "",
    ]
    for r in rows:
        lines.append(f"[{r['item']}] {r['result']}")
        if r.get("advice"):
            lines.append(f"  → {r['advice']}")
    lines.append("")
    lines.append(f"portal: {cfg.base_url} ac_id={cfg.ac_id}")
    ips = candidate_source_ips()
    if ips:
        lines.append("nic: " + ", ".join(ips[:4]))
    return "\n".join(lines)
