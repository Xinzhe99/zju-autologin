"""原地自更新：便携包解出 exe 与安装版判定。"""

import os
import zipfile

from zju_autologin.ui import MainWindow, _is_installed_win


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
