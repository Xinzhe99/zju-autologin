"""原地自更新：便携包解出 exe 与安装版判定。"""

import os
import zipfile

import pytest
from PyQt6.QtWidgets import QApplication
from zju_autologin.ui import MainWindow, _is_installed_win


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_extract_win_exe(tmp_path):
    zip_path = tmp_path / "ZJUAutoLogin-9.9.9-windows-portable.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("ZJUAutoLogin.exe", b"MZ fake binary")
    exe = MainWindow._extract_win_exe(str(zip_path))
    assert os.path.basename(exe) == "ZJUAutoLogin.exe"
    assert os.path.isfile(exe)


def test_extract_win_exe_missing_raises(tmp_path):
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("readme.txt", "x")
    try:
        MainWindow._extract_win_exe(str(zip_path))
    except OSError:
        return
    raise AssertionError("缺少 exe 的包应报错而非静默继续")


def test_source_mode_is_not_installed():
    assert _is_installed_win() is False  # 未 frozen(源码运行)不视为安装版


def test_pkg_version_parsed():
    assert MainWindow._pkg_version(
        "/tmp/ZJUAutoLogin-1.16.0-windows-portable.zip") == "1.16.0"
    assert MainWindow._pkg_version("/tmp/update.bin") == ""


def test_installer_launch_failure_restores_ui(qapp, tmp_path):
    """拉起安装器失败(被杀软拦截/文件缺失)不得异常逸出, 且要留下面向用户的提示。"""
    from zju_autologin.config import Config
    from zju_autologin.monitor import Monitor
    from zju_autologin.ui import MainWindow

    cfg = Config(str(tmp_path / "cfg.json"))
    cfg.load()
    win = MainWindow(cfg, Monitor(cfg))
    win._update_url = "https://example.invalid/releases/latest"
    win._update_downloaded(str(tmp_path / "ZJUAutoLogin-9.9.9-windows-setup.exe"))
    assert win._update_pkg == ""
    assert win._update_banner.text()
    assert "example.invalid" in list(win._log_buffer)[-1]


def _iss_text() -> str:
    root = os.path.join(os.path.dirname(__file__), "..")
    with open(os.path.join(root, "installer.iss"), encoding="utf-8") as f:
        return f.read()


def test_installer_delays_silent_relaunch():
    """静默更新由安装器侧的延迟 helper 拉起(兼容旧版本发起的更新), 不直接启动 exe。"""
    iss = _iss_text()
    run_section = iss.split("\n[Run]\n", 1)[1].split("\n[UninstallRun]\n", 1)[0]
    assert "postinstall skipifsilent" in run_section
    assert "update-relaunch.ps1" in run_section
    assert "skipifnotsilent" in run_section
    # 不能再用裸 exe 作为静默启动项
    assert 'Filename: "{app}\ZJUAutoLogin.exe"; Flags: nowait runasoriginaluser skipifnotsilent' not in run_section
    assert "Start-Sleep -Seconds 12" in iss
    # Inno 的自动关闭/重启会与 helper 形成双开, 加剧 onefile 解包竞态
    assert "RestartApplications=no" in iss
    assert "CloseApplications=no" in iss


def test_updater_uses_relaunch_helper_for_portable_only():
    src = os.path.join(os.path.dirname(__file__), "..", "zju_autologin", "ui.py")
    with open(src, encoding="utf-8") as f:
        ui_src = f.read()
    assert "/RESTARTAPPLICATIONS" not in ui_src
    assert '"/SILENT", "/CLOSEAPPLICATIONS"' not in ui_src
    # 便携版原地替换后仍由应用侧 helper 延迟启动
    assert "_schedule_relaunch_after(0, str(cur)" in ui_src
