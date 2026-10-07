"""校园网阻断 git 协议时的推送通道: 用 GitHub REST API 推 main 与 tag。

背景: 本机 `git push` 到 github.com:443 会被重置(Recv failure), 而
api.github.com 正常, 所以发版走 API。

用法(在仓库根目录, 先本地 git commit):
    python tools/api_push.py                 # 只推 main
    python tools/api_push.py v1.25.4         # 推 main 并打标签(标签已存在则报错退出)
    python tools/api_push.py v1.25.4 --dry-run

Token: 优先读环境变量 GH_TOKEN; 没有就向 git credential manager 要
(不会打印到终端)。安全约束: 只做"本地 HEAD 是远端 main 的快进"这一种推送,
父提交不匹配立即退出, 绝不回退/强推任何已有提交。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = "Xinzhe99/zju-autologin"
API = f"https://api.github.com/repos/{REPO}"


def _token() -> str:
    token = (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        return token
    # git credential manager: 不落地、不回显
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    sys.exit("no GitHub token: set GH_TOKEN or store credentials via git credential manager")


TOKEN = _token()


def api(method: str, path: str, body: dict | None = None, ok_codes=(200, 201)):
    last = ""
    for attempt in range(4):
        req = urllib.request.Request(
            f"{API}/{path}", method=method,
            headers={"Authorization": f"token {TOKEN}",
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json"},
            data=json.dumps(body).encode() if body else None)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            if e.code in ok_codes:
                return {}
            if e.code < 500 or attempt == 3:
                sys.exit(f"HTTP {e.code} {method} {path}: {detail}")
            last = f"HTTP {e.code} {path}: {detail}"
            print(f"{last} - retrying")
            time.sleep(3)
    sys.exit(last or "api failed")


def api_optional(method: str, path: str):
    """GET 一个可能不存在的资源: 404 返回 None, 其它错误照旧退出。"""
    req = urllib.request.Request(
        f"{API}/{path}", method=method,
        headers={"Authorization": f"token {TOKEN}",
                 "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        detail = e.read().decode(errors="replace")[:200]
        sys.exit(f"HTTP {e.code} {method} {path}: {detail}")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True,
                          check=True).stdout.decode().strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?", default="", help="要创建的标签, 如 v1.25.4")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    local = git("rev-parse", "HEAD")
    parent = git("rev-parse", "HEAD^")
    print(f"local HEAD = {local[:9]}  parent = {parent[:9]}")

    remote = api("GET", "git/ref/heads/main")["object"]["sha"]
    print(f"remote main = {remote[:9]}")
    if remote != parent:
        # 同一份内容在本地与远端可能是两个不同的提交对象(例如远端提交由 API 生成),
        # 这时不能只看 sha。判据: 本地父提交的 tree 与远端 main 的 tree 完全一致
        # → 内容没有分叉, 可以安全地以远端 main 为父重建本地提交。
        local_parent_tree = git("rev-parse", f"{parent}^{{tree}}")
        remote_tree = api("GET", f"git/commits/{remote}")["tree"]["sha"]
        if local_parent_tree != remote_tree:
            sys.exit("拒绝推送: 本地与远端 main 内容已分叉(需要先同步/变基), 绝不强推")
        print(f"注意: 远端 main 与本地父提交内容一致(tree {local_parent_tree[:9]}), "
              f"仅提交对象不同 → 以远端 main 为父重建提交")

    if args.tag and api_optional("GET", f"git/ref/tags/{args.tag}"):
        sys.exit(f"标签 {args.tag} 已存在, 拒绝覆盖")

    changed = git("diff", "--name-only", parent, local).splitlines()
    print(f"changed files: {len(changed)}")

    if args.dry_run:
        print("dry-run: 不做任何写操作")
        return 0

    for path in changed:
        local_sha = git("rev-parse", f"{local}:{path}")
        raw = subprocess.run(["git", "cat-file", "-p", local_sha],
                             capture_output=True, check=True).stdout
        remote_sha = api("POST", "git/blobs", {
            "content": base64.b64encode(raw).decode(), "encoding": "base64"})["sha"]
        if remote_sha != local_sha:
            sys.exit(f"blob 字节不一致: {path}")
        print(f"blob ok {path}")

    entries = []
    for line in git("ls-tree", "-r", local).splitlines():
        meta, path = line.split("\t", 1)
        mode, typ, sha = meta.split()
        entries.append({"path": path.replace('"', ""), "mode": mode,
                        "type": typ, "sha": sha})
    tree = api("POST", "git/trees", {"tree": entries})["sha"]
    local_tree = git("rev-parse", f"{local}^{{tree}}")
    if tree != local_tree:
        sys.exit(f"tree 不一致: local={local_tree} remote={tree}")
    print(f"tree ok {tree} ({len(entries)} 条目)")

    message = git("log", "-1", "--format=%B", local)
    commit = api("POST", "git/commits",
                 {"message": message, "tree": tree, "parents": [remote]})["sha"]
    if commit != local:
        print(f"注意: 远端提交 sha {commit[:9]} 与本地 {local[:9]} 不同(元数据差异), 内容一致")
    api("PATCH", "git/refs/heads/main", {"sha": commit, "force": False})
    print(f"main -> {commit[:9]}")

    if args.tag:
        api("POST", "git/tags", {"tag": args.tag, "message": message,
                                 "object": commit, "type": "commit"})
        api("POST", "git/refs", {"ref": f"refs/tags/{args.tag}", "sha": commit})
        print(f"tag ok {args.tag} -> 触发 Release 工作流")
    return 0


if __name__ == "__main__":
    sys.exit(main())
