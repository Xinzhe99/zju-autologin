"""一键恢复真实密码到系统凭据管理器。

背景: 2026-09-30 前的测试套件会把假密码写进真实 keyring(v1.21.0 已根治)。
真实密码仍完整保存于 SYSTEM 服务配置 C:\\ProgramData\\ZJUAutoLogin\\config.json
(password_b64, ACL 仅 SYSTEM/管理员可读)。本脚本提权读取该文件并写回
当前用户的凭据管理器, 修复被污染的 keyring 条目。

用法(会弹一次 UAC):
    python tools/restore_keyring.py
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import uuid

SVC_CFG = r"C:\ProgramData\ZJUAutoLogin\config.json"


def main() -> int:
    if sys.platform != "win32":
        print("仅 Windows")
        return 1
    # 提权读取服务配置(仅取 password 字段, 其余不落地)
    out_tmp = os.path.join(tempfile.gettempdir(), f"zju_pwd_{uuid.uuid4().hex[:8]}.json")
    script = (
        "Set-ExecutionPolicy Bypass -Scope Process -Force\n"
        f"$c = Get-Content '{SVC_CFG}' -Raw | ConvertFrom-Json\n"
        f"Set-Content -Path '{out_tmp}' -Value $c.password_b64\n"
    )
    from zju_autologin.service import _run_elevated_ps

    ok, detail = _run_elevated_ps(script)
    try:
        if not ok:
            print("读取失败:", detail)
            return 1
        b64 = open(out_tmp, encoding="ascii").read().strip()
        password = base64.b64decode(b64).decode("utf-8")
    finally:
        try:
            os.remove(out_tmp)
        except OSError:
            pass
    if not password:
        print("服务配置中无密码(可能未启用系统级保活)")
        return 1

    import keyring

    keyring.set_password("ZJUAutoLogin", "account", password)
    print(f"✓ 已恢复真实密码到凭据管理器(长度 {len(password)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
