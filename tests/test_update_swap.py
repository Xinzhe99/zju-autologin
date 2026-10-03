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


def test_installer_runs_after_silent_update():
    """静默更新装完必须拉起程序: 安装脚本需含 skipifnotsilent 启动项(回归守卫)。"""
    iss = _iss_text()
    run_section = iss.split("[Run]")[1].split("[UninstallRun]")[0]
    # 可见安装: 完成页复选框; 静默安装(应用内更新): 直接启动
    assert "postinstall skipifsilent" in run_section
    assert "skipifnotsilent" in run_section
    assert run_section.count("ZJUAutoLogin.exe") >= 2


def test_updater_no_restartapplications_flag():
    """应用是自退出的, /RESTARTAPPLICATIONS 无效; 静默拉起交给安装脚本。"""
    src = os.path.join(os.path.dirname(__file__), "..", "zju_autologin", "ui.py")
    with open(src, encoding="utf-8") as f:
        ui_src = f.read()
    assert "/RESTARTAPPLICATIONS" not in ui_src
    assert '"/SILENT", "/CLOSEAPPLICATIONS"' in ui_src
