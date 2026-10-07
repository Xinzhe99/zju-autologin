"""v1.25.4 回归: 看护任务注册(v1.24.0 起一直没建成)。

历史事故: install() 把整段脚本塞进
`powershell -Command "schtasks ... /TR \"<脚本>\""` 两层引号再交给 schtasks。
PowerShell 不认 `\\"`, 命令在解析阶段就整个失败(退出码 -1、零输出),
于是计划任务从未创建 —— "GUI 崩溃看护"实际上一直是空转的。
另: schtasks /TR 有 261 字符上限, 而脚本本身约 400 字符。

这里的守卫:
1. 注册用 argv 直调 schtasks, 不再套一层 PowerShell
2. /TR 是短引用(指向落盘的 .ps1), 且不超长
3. 脚本文件真的写出来了, 且行为(双条件判断)正确
4. 生成的 PowerShell 语法有效(Windows 上真跑一遍解析器)
"""

from __future__ import annotations

import subprocess
import sys

import pytest

import zju_autologin.watchdog as W


@pytest.fixture
def wd_env(tmp_path, monkeypatch):
    """看护模块指向临时配置目录, 并视为已启用(frozen+win32)。"""
    monkeypatch.setattr(W, "_enabled", lambda: True)
    import zju_autologin.config as cfgmod
    monkeypatch.setattr(cfgmod, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(W.sys, "executable", r"C:\app\ZJUAutoLogin.exe", raising=False)
    return tmp_path


class _FakeRun:
    """捕获 subprocess.run 的调用参数, 不真的去动计划任务。"""

    def __init__(self, returncode: int = 0):
        self.calls: list[list[str]] = []
        self.returncode = returncode

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return type("R", (), {"returncode": self.returncode,
                              "stdout": b"", "stderr": b""})()


def test_install_uses_short_task_action_and_argv(wd_env, monkeypatch):
    fake = _FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)
    assert W.install() is True

    argv = fake.calls[-1]
    assert argv[0] == "schtasks"                    # 直调, 不经过 PowerShell
    action = argv[argv.index("/TR") + 1]
    # 动作是短引用(指向脚本文件), 既躲开引号解析地狱也满足 /TR 长度上限
    assert action.startswith("powershell ")
    assert str(W.script_path()) in action
    assert '\\"' not in action                      # 不能出现 \" 这类转义
    assert action.count('"') == 2                   # 只有包裹脚本路径的一对引号
    assert len(action) <= W.MAX_TASK_ACTION
    assert "/F" in argv and "/SC" in argv and "5" in argv


def test_install_writes_runnable_script(wd_env, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _FakeRun())
    W.install()
    script = W.script_path()
    assert script.is_file()
    text = script.read_text(encoding="utf-8-sig")
    assert "gui.alive" in text and "watchdog.pause" in text
    assert "-le 10" in text and "-le 15" in text        # 双阈值
    assert "if (-not $f -and -not $u)" in text          # 双条件
    assert "--minimized" in text and "ZJUAutoLogin.exe" in text


def test_script_quotes_paths_with_single_quote(tmp_path, monkeypatch):
    """用户名带 ' 时不能把 PowerShell 字符串截断。"""
    weird = tmp_path / "O'Brien"
    weird.mkdir()
    monkeypatch.setattr(W, "_enabled", lambda: True)
    import zju_autologin.config as cfgmod
    monkeypatch.setattr(cfgmod, "config_dir", lambda: weird)
    text = W._ps_script()
    assert "O''Brien" in text
    assert "O'Brien';" not in text


def test_uninstall_returns_false_when_task_delete_fails(wd_env, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _FakeRun(returncode=1))
    assert W.uninstall() is False           # 以前无论成败都返回 True


def test_refresh_without_task_only_writes_script(wd_env, monkeypatch):
    """存量机器没任务: 只补脚本, 不擅自注册(是否该装由调用方判断)。"""
    fake = _FakeRun(returncode=1)           # schtasks /Query 未找到
    monkeypatch.setattr(subprocess, "run", fake)
    assert W.refresh_if_installed() is False
    assert W.script_path().is_file()
    assert all("/Create" not in call for call in fake.calls)


@pytest.mark.skipif(sys.platform != "win32", reason="需要 PowerShell 解析器")
def test_generated_script_is_valid_powershell(wd_env, monkeypatch):
    """语法与变量绑定都要真能跑通(本机 PowerShell 5.1 / pwsh 均可)。"""
    monkeypatch.setattr(subprocess, "run", _FakeRun())
    W.touch_alive()                          # 心跳新鲜 → 脚本必须什么都不做
    W.install()
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(W.script_path())],
        capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, f"脚本执行失败: {r.stderr[:300]}"
