"""v1.17.0 审查修复补丁 A：ui.py（更新链路/下载线程/对话框）+ monitor.py（线程安全）。

来源：5 个子 agent 审查（🔴9 🟡30）中的 ui/monitor 部分。
"""

import ast

# ================================ ui.py ================================
u = open('zju_autologin/ui.py', encoding='utf-8').read()
n0 = len(u)

# ---- [🔴#1] 预下载失败后 _downloader 永不复位 → 更新永久失效 ----
old = '''        self._downloader.finished_ok.connect(self._predownload_done)
        self._downloader.finished_err.connect(
            lambda err: self._append_log(tr("update.predl_fail", msg=err)))
        self._downloader.start()'''
new = '''        self._downloader.finished_ok.connect(self._predownload_done)
        self._downloader.finished_err.connect(self._predownload_fail)
        self._downloader.start()'''
assert u.count(old) == 1, "A1"
u = u.replace(old, new)

# _predownload_fail 槽（复位线程引用, 允许后续重试; 横幅若可见则提示）
old = '''    def _predownload_done(self, path: str) -> None:
        self._downloader = None
        self._update_pkg = path'''
new = '''    def _predownload_fail(self, error: str) -> None:
        # 复位引用, 否则 _predownload_update/_do_update 的非 None 守卫会
        # 永远 return, 更新功能静默永久失效
        self._downloader = None
        self._append_log(tr("update.predl_fail", msg=error))

    def _predownload_done(self, path: str) -> None:
        self._downloader = None
        self._update_pkg = path'''
assert u.count(old) == 1, "A2"
u = u.replace(old, new)

# 预下载进行中重复点击 progress lambda 累积 → 只接一次
old = '''        if self._downloader is not None:
            # 预下载进行中: 横幅接入进度反馈而非静默忽略
            self._update_banner.setText(tr("update.downloading", percent=0))
            self._downloader.progress.connect(
                lambda p: self._update_banner.setText(tr("update.downloading", percent=p)))
            return'''
new = '''        if self._downloader is not None:
            # 预下载进行中: 横幅接入进度反馈而非静默忽略(只接一次, 防累积)
            if not getattr(self._downloader, "_ui_attached", False):
                self._downloader._ui_attached = True
                self._update_banner.setText(tr("update.downloading", percent=0))
                self._downloader.progress.connect(
                    lambda p: self._update_banner.setText(tr("update.downloading", percent=p)))
            return'''
assert u.count(old) == 1, "A3"
u = u.replace(old, new)

# ---- [🟡] 更新包 digest 缺失 fail-open → fail-closed; 临时文件名随机化+basename ----
old = '''            url = str(target.get("browser_download_url") or "")
            name = str(target.get("name") or "update.bin")
            total = int(target.get("size") or 0)
            digest = str(target.get("digest") or "")  # GitHub API: "sha256:..."
            self.progress.emit(0)
            req = urllib.request.Request(url, headers={"User-Agent": "ZJU-AutoLogin"})
            path = os.path.join(tempfile.gettempdir(), name)'''
new = '''            url = str(target.get("browser_download_url") or "")
            name = os.path.basename(str(target.get("name") or "update.bin"))
            total = int(target.get("size") or 0)
            digest = str(target.get("digest") or "")  # GitHub API: "sha256:..."
            if not digest.startswith("sha256:"):
                # 校验信息缺失即拒绝安装(fail-closed), 不静默跳过校验
                self.finished_err.emit("missing sha256 digest")
                return
            self.progress.emit(0)
            req = urllib.request.Request(url, headers={"User-Agent": "ZJU-AutoLogin"})
            # 随机临时名: 降低预下载包在 %TEMP% 停留期间被替换的 TOCTOU 面
            fd, path = tempfile.mkstemp(prefix="zju_aul_pkg_", suffix=os.path.splitext(name)[1])
            os.close(fd)'''
assert u.count(old) == 1, "A4"
u = u.replace(old, new)

# digest 校验从 if 改为必然执行（上方已 fail-closed）
old = '''            if digest.startswith("sha256:"):
                import hashlib

                sha = hashlib.sha256()
                with open(path, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                        sha.update(chunk)
                if sha.hexdigest() != digest.split(":", 1)[1]:'''
new = '''            import hashlib

            sha = hashlib.sha256()
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                    sha.update(chunk)
            if True:
                if sha.hexdigest() != digest.split(":", 1)[1]:'''
assert u.count(old) == 1, "A5"
u = u.replace(old, new)

# ---- [🟢] DevicesDialog _status 自动换行 ----
old = '''        self._status = QLabel("")
        self._status.setObjectName("statusDetail")
        lay.addWidget(self._status)'''
new = '''        self._status = QLabel("")
        self._status.setObjectName("statusDetail")
        self._status.setWordWrap(True)
        lay.addWidget(self._status)'''
assert u.count(old) == 1, "A6"
u = u.replace(old, new)

# ---- [🔴 agent4] 设备/门户对话框: 持有引用防 GC + 向导线程等待 ----
old = '''    def _show_devices(self) -> None:
        dlg = DevicesDialog(self._config, self._last_status.get("ip") or "", self)'''
new = '''    def _show_devices(self) -> None:
        # 持有引用: 避免局部变量 GC 后线程仍在运行的风险
        self._devices_dlg = DevicesDialog(self._config, self._last_status.get("ip") or "", self)
        dlg = self._devices_dlg'''
assert u.count(old) == 1, "A7"
u = u.replace(old, new)

old = '''    def _show_portal_wizard(self) -> None:
        PortalWizardDialog(self._config, self).exec()'''
new = '''    def _show_portal_wizard(self) -> None:
        self._portal_dlg = PortalWizardDialog(self._config, self)
        self._portal_dlg.exec()'''
assert u.count(old) == 1, "A8"
u = u.replace(old, new)

# ---- [🟡] 退出/关机 UI 线程等待 3000→200ms（下载中断无害, 进程级兜底） ----
u = u.replace("self._downloader.stop()\n            self._downloader.wait(3000)",
              "self._downloader.stop()\n            self._downloader.wait(200)")
u = u.replace("self._downloader.stop()\n            self._downloader.wait(2000)",
              "self._downloader.stop()\n            self._downloader.wait(200)")
u = u.replace("self._downloader.stop()\n        self._downloader.wait(3000)",
              "self._downloader.stop()\n        self._downloader.wait(200)")

# ---- [🟡] macOS 心跳定时器 darwin 也启动 ----
old = '''        if sys.platform == "win32":
            self._hb_timer.start()'''
new = '''        if sys.platform in ("win32", "darwin"):
            self._hb_timer.start()'''
assert u.count(old) == 1, "A9"
u = u.replace(old, new)

# ---- [🟡] 心跳阈值随检测间隔缩放, 防止 600s 间隔时 ok/stale 抖动 ----
old = '''        elif mins <= 10:'''
new = '''        elif mins <= max(10, (self._config.interval * 3) // 60):'''
assert u.count(old) == 1, "A10"
u = u.replace(old, new)

# ---- [🟡] 诊断复制: 日志尾段账号脱敏 ----
old = '''        lines += self._log.toPlainText().splitlines()[-50:]
        QApplication.clipboard().setText("\\n".join(lines))'''
new = '''        tail = self._log.toPlainText().splitlines()[-50:]
        if cfg.username:  # 日志尾段含完整账号, 与头部打码保持一致
            tail = [re.sub(re.escape(cfg.username), masked, ln) for ln in tail]
        lines += tail
        QApplication.clipboard().setText("\\n".join(lines))'''
assert u.count(old) == 1, "A11"
u = u.replace(old, new)

# masked 变量与 re 导入确认
if "import re\n" not in u.split("class ")[0]:
    u = u.replace("import json\nimport os\n", "import json\nimport os\nimport re\n", 1)
if "masked = " not in u:
    # 头部打码行补 masked 局部变量
    old = '''        lines = [
            f"ZJU-AutoLogin v{__version__}",'''
    new2 = '''        user = cfg.username
        masked = f"{user[:2]}{'*'*3}{user[-1:]}" if len(user) > 3 else "***"
        lines = [
            f"ZJU-AutoLogin v{__version__}",'''
    assert u.count(old) == 1, "A12"
    u = u.replace(old, new2)

# ---- [🟡] 导出脱敏补 heartbeat_url / proxy_url ----
old = '''            if key in ("win_geometry", "notify_key", "smtp_pass"):
                continue  # 位置/密钥类字段不导出'''
new = '''            if key in ("win_geometry", "notify_key", "smtp_pass",
                       "heartbeat_url", "proxy_url"):
                continue  # 位置/密钥类字段不导出(心跳UUID与代理URL同为凭据)'''
assert u.count(old) == 1, "A13"
u = u.replace(old, new)

# ---- [🟢] 导入配置后立即应用主题/语言, 选中态与界面一致 ----
old = '''        self._config.save()
        self._load_settings_into_ui()
        self._monitor.config_updated()
        self._save_hint.setText(tr("msg.cfg_imported"))'''
new = '''        self._config.save()
        self._load_settings_into_ui()
        self._apply_theme(self._config.theme)
        if i18n.current_lang() != self._config.language:
            i18n.set_lang(self._config.language)
        self.retranslate_ui()
        self._main.retranslate_ui()
        self._monitor.config_updated()
        self._save_hint.setText(tr("msg.cfg_imported"))'''
assert u.count(old) == 1, "A14"
u = u.replace(old, new)

# ---- [🟢] authed_no_internet 恢复不应弹"已自动重登"(未发生重登) ----
old = '''_NOTIFY_RELOGIN_FROM = {"offline", "auth_error", "login_fail", "authed_no_internet"}'''
new = '''_NOTIFY_RELOGIN_FROM = {"offline", "auth_error", "login_fail"}'''
assert u.count(old) == 1, "A15"
u = u.replace(old, new)

# ---- [🟢] 托盘 tooltip 未知状态防护 ----
old = '''    def _refresh_tray_tooltip(self) -> None:
        status = tr(f"status.{self._last_status.get('state', 'checking')}")'''
new = '''    def _refresh_tray_tooltip(self) -> None:
        state = self._last_status.get("state", "checking")
        status = tr(f"status.{state}") if state in STATUS_KEYS else state'''
assert u.count(old) == 1, "A16"
u = u.replace(old, new)

# ---- [🟢] spinbox 后缀双空格 ----
old = '''        self._spin_interval.setSuffix(f" {tr('unit.seconds', n='')}".rstrip())'''
new = '''        self._spin_interval.setSuffix(" " + tr("unit.seconds", n="").strip())'''
assert u.count(old) == 1, "A17"
u = u.replace(old, new)

# ---- [🟢] 服务心跳加入 retranslate ----
old = '''        self._set_status_ui(self._last_status.get("state", "checking"),
                            self._last_status.get("detail", ""))
        self._refresh_tray_tooltip()
        if self._settings_window is not None:'''
new = '''        self._set_status_ui(self._last_status.get("state", "checking"),
                            self._last_status.get("detail", ""))
        self._refresh_tray_tooltip()
        if self._settings_window is not None:
            self._settings_window._refresh_service_heartbeat()'''
assert u.count(old) == 1, "A18"
u = u.replace(old, new)

# ---- [🟡] 安装版误判便携: 增加 unins*.exe 探测 ----
old = '''def _is_installed_win() -> bool:
    """Windows 安装版判定: 位于 Program Files 或 exe 目录不可写(不可原地替换)。"""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False'''
new = '''def _is_installed_win() -> bool:
    """Windows 安装版判定: Inno 安装目录 / Program Files / 目录不可写。"""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    if glob.glob(os.path.join(os.path.dirname(sys.executable), "unins*.exe")):
        return True  # Inno 每用户安装目录特征({localappdata}\Programs 可写, 曾被误判便携)'''
assert u.count(old) == 1, "A19"
u = u.replace(old, new)
if "import glob
" not in u.split("class ")[0]:
    u = u.replace("import json
import os
", "import glob
import json
import os
", 1)

open('zju_autologin/ui.py', 'w', encoding='utf-8').write(u)
ast.parse(u)
print(f"ui.py patched: {n0} -> {len(u)} bytes")

# ================================ monitor.py ================================
m = open('zju_autologin/monitor.py', encoding='utf-8').read()

# ---- [🔴] 删除 terminate 分支: TerminateThread 可致 GIL 死锁, 比退出慢更糟 ----
old = '''        QMetaObject.invokeMethod(self._worker, "stop", Qt.ConnectionType.QueuedConnection)
        self._thread.quit()
        if not self._thread.wait(300):
            self._thread.terminate()
            self._thread.wait(300)'''
new = '''        QMetaObject.invokeMethod(self._worker, "stop", Qt.ConnectionType.QueuedConnection)
        self._thread.quit()
        # 不做 terminate: TerminateThread 可能在持 GIL/写盘中途打断, 造成
        # 进程假死或文件损坏; 残留线程由 main.py 的 os._exit 进程级兜底
        self._thread.wait(300)'''
assert m.count(old) == 1, "M1"
m = m.replace(old, new)

# ---- [🟡] start() 首次更新检查改排队, 不阻塞 worker 事件循环 ----
old = '''        self.check_once()  # 首次状态检测优先, 不被更新检查的网络等待拖慢首屏
        if self._config.check_updates:
            self.check_updates()'''
new = '''        self.check_once()  # 首次状态检测优先, 不被更新检查的网络等待拖慢首屏
        if self._config.check_updates:
            # 排队执行而非同步调用: 保证 stop() 事件能尽快插入事件循环
            QTimer.singleShot(3000, self.check_updates)'''
assert m.count(old) == 1, "M2"
m = m.replace(old, new)

open('zju_autologin/monitor.py', 'w', encoding='utf-8').write(m)
ast.parse(m)
print("monitor.py patched")
