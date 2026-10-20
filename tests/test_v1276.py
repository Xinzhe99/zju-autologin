"""v1.27.6 回归：服务配置必须先把临时文件 rename 到位，再收紧 ACL。

旧实现先对临时文件执行 icacls /inheritance:r，当前非提权用户随即失去对源文件的
DELETE 权限，os.replace 报 WinError 5，系统级保活勾选后立刻失败（UI 还误报成
"请在 UAC 弹窗确认"）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from zju_autologin import service


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACL ordering")
def test_write_private_renames_before_acl_lockdown(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    calls: list[tuple[str, str]] = []
    real_replace = os.replace

    def fake_replace(src, dst):
        calls.append(("replace", Path(src).name))
        real_replace(src, dst)

    def fake_lockdown(p):
        calls.append(("acl", Path(p).name))
        assert Path(p).exists(), "收紧 ACL 时文件必须已经 rename 到目标路径"

    monkeypatch.setattr(service.os, "replace", fake_replace)
    monkeypatch.setattr(service, "_lockdown_windows_acl", fake_lockdown)

    service._write_private(path, '{"x": 1}')

    assert path.read_text(encoding="utf-8") == '{"x": 1}'
    assert calls == [("replace", "config.json.tmp"), ("acl", "config.json")]
