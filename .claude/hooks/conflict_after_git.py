# -*- coding: utf-8 -*-
"""git の pull / rebase / merge / stash pop の直後に、3つのリポジトリの衝突を調べて知らせる。

2026-09-29 に衝突の印を17本の記事に残したまま3サイトへ公開し、2026-10-03 にも
--autostash の戻しで衝突した（台帳と生成ページ）。「必ず確かめる」と書いても抜けたので、
統合の操作をしたら機械が毎回見る。印が残っていれば、次の操作の前に Claude へ返す。
"""
import json
import os
import re
import subprocess
import sys

try:
    cmd = (json.load(sys.stdin).get("tool_input") or {}).get("command", "")
except Exception:
    sys.exit(0)

if not re.search(r"\bgit\b[^|;&]*\b(pull|rebase|merge|cherry-pick)\b|\bstash\s+(pop|apply)\b", cmd):
    sys.exit(0)

root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
repos = [root] + [os.path.join(root, ".publish-work", d) for d in ("corporate", "subsidy")]
found = []
for repo in repos:
    if not os.path.isdir(os.path.join(repo, ".git")):
        continue

    def git(*a):
        r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, encoding="utf-8", errors="ignore")
        return [l for l in r.stdout.splitlines() if l.strip()]

    name = os.path.basename(repo) if repo != root else "main"
    for f in git("diff", "--name-only", "--diff-filter=U"):
        found.append(f"{name}: 未解決 {f}")
    # 作業中のファイルだけを見る（全履歴の検索は重い）
    for f in git("grep", "-l", "-I", "-E", "-e", "^<<<<<<< ", "-e", "^>>>>>>> ")[:20]:
        found.append(f"{name}: 衝突の印 {f}")
    if os.path.isdir(os.path.join(repo, ".git", "rebase-merge")) or os.path.isdir(os.path.join(repo, ".git", "rebase-apply")):
        found.append(f"{name}: rebase が途中で止まっている")

if found:
    print("git の統合のあとに衝突が残っています。build・commit・push の前に解いてください:\n  "
          + "\n  ".join(dict.fromkeys(found)), file=sys.stderr)
    sys.exit(2)
sys.exit(0)
