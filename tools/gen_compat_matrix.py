"""从 portals.json 生成 README 兼容性矩阵表格。CI/手动运行均可。"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTALS = ROOT / "zju_autologin" / "portals.json"
README = ROOT / "README.md"
MARK = "<!-- COMPAT-MATRIX -->"


def build_table() -> str:
    portals = json.loads(PORTALS.read_text(encoding="utf-8"))["portals"]
    rows = ["| 学校 / University | 门户 | 状态 |", "| --- | --- | --- |"]
    for p in portals:
        state = f"✅ {p['verified']} 验证" if p.get("verified") else "🧪 待验证"
        rows.append(f"| {p['name']} | `{p['base_url']}` | {state} |")
    rows.append("| 为你的学校添加一行 → [portals.json](zju_autologin/portals.json) | | |")
    return chr(10).join(rows)


def main() -> int:
    table = build_table()
    text = README.read_text(encoding="utf-8")
    if MARK not in text:
        anchor = "## 校园网认证机制解析"
        block = "## 学校兼容性" + chr(10) + chr(10) + MARK + chr(10) + table + chr(10) + chr(10) + anchor
        text = text.replace(anchor, block)
    else:
        text = re.sub(re.escape(MARK) + r"[\s\S]*?(?=\n## )", MARK + "\n" + table, text)
    README.write_text(text, encoding="utf-8")
    print("matrix updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
