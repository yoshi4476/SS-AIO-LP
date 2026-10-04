# -*- coding: utf-8 -*-
"""1件ずつ別の作業場所（git worktree）で処理を並べる部品。

検算は「その1本以外が変わっていないか」をリポジトリ全体で見るため、同じ作業場所で並べると
互いの変更を「別の記事まで変わった」と数えて止まる。作業場所を分ければ検算はそのまま通る。
作り方を工程ごとに書くと、鍵の写し忘れ・消し忘れが工程ごとに起きるので、ここ1か所に置く。
"""
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".publish-work"
# Git で管理していない鍵（Search Console・管制塔）。無いと食い合いの検査（kw_guard）が
# GSC を読めずに止まり、12本中8本が「食い合う」で戻された（2026-10-04）。作業場所ごと消すので残らない
KEYS = ("indexing-service-account.json", ".env")


def _remove(w):
    subprocess.run(["git", "worktree", "remove", "--force", str(w)], cwd=ROOT, capture_output=True)


def run_in_worktrees(items, build_cmd, inputs=lambda item: (), outputs=None, workers=4,
                     name=lambda item: str(item), timeout=3600, on_result=None):
    """items を1件ずつ別の作業場所で処理し、[(item, err, value), ...] を items の順で返す。

    build_cmd(item) → 作業場所で走らせるコマンド。inputs(item) → 写すコミットしていない入力の相対パス。
    outputs(item, w, proc) → 作業場所から結果を本体へ戻し、値を返す（作業場所を消す前に呼ぶ）。
    err は作業場所を作れなかったときだけ入る（value は None）。on_result(item, err, value) は
    終わった順ではなく items の順に、呼び出し元のスレッドで1件ずつ呼ぶ"""
    def one(item):
        w = WORK / f"wt-{name(item)}"
        _remove(w)  # 前回落ちて残った同名の作業場所があると add が失敗する
        r = subprocess.run(["git", "worktree", "add", "--detach", str(w), "HEAD"], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            return item, f"作業場所を作れません（{r.stderr[-120:]}）", None
        try:
            for rel in (*inputs(item), *KEYS):
                if (ROOT / rel).is_file():
                    (w / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(ROOT / rel, w / rel)
            proc = subprocess.run(build_cmd(item), cwd=w, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=timeout)
            return item, "", (outputs(item, w, proc) if outputs else proc)
        finally:
            _remove(w)

    out = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for res in ex.map(one, items):
            # 台帳への書き込みは呼び出し側の1本の流れで行う（並列で同じファイルを書かせない）
            if on_result:
                on_result(*res)
            out.append(res)
    return out


if __name__ == "__main__":
    sys.exit("部品です。migrate_legacy.py --rewrite <slug...> --parallel N などから使います")
