# -*- coding: utf-8 -*-
"""取り込み（pull --rebase）でぶつかっても、ぶつからなかった直しを捨てずに送り出す（2026-10-19）。

週次の工程（約70分）の間に毎日の記事の枠が同じ記事を書き換えると、送り出しのやり直しが3回とも
同じ所でぶつかり、週次の直しが全部失われていた（2026-10-19: 記事2本と作業の記録がぶつかり、97ファイルの直しを失った）。

ぶつかったファイルの解き方:
  - 行を足していくだけの記録（*.jsonl）: 両方の行を残す（同じ行は1つに）
  - それ以外（記事など）: 先に入った側（取り込み先）を残し、こちらの直しはそのファイルだけ見送る。
    両方を混ぜない（記事の中身が壊れる）。見送ったファイルは警告に出し、次の回の直しが拾う

    python scripts/rebase_push.py [--branch master] [--tries 3]
終了コード: 送り出せたら 0、送り出せなければ 1。
"""
import argparse
import os
import subprocess
import sys
import time

MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def git(*a, check=False):
    r = subprocess.run(["git", *a], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(a)}: {r.stderr.strip()[:300]}")
    return r


def in_rebase():
    gd = git("rev-parse", "--git-dir").stdout.strip()
    return any(os.path.isdir(os.path.join(gd, d)) for d in ("rebase-merge", "rebase-apply"))


def conflicted():
    """[(状態の2文字, パス)]"""
    out = []
    for ln in git("status", "--porcelain").stdout.splitlines():
        st, path = ln[:2], ln[3:].strip()
        if st in ("UU", "AA", "DU", "UD", "AU", "UA", "DD"):
            out.append((st, path))
    return out


def union_lines(path):
    """衝突の印を外し、両方の行を残す（重複は1つに）。行を足すだけの記録向け"""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    seen, out = set(), []
    for ln in lines:
        if ln.startswith(MARKERS):
            continue
        if ln not in seen:
            seen.add(ln)
            out.append(ln)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + ("\n" if out else ""))


def resolve():
    """いまの rebase の停止を解く。見送ったファイルを返す"""
    dropped = []
    for st, path in conflicted():
        if path.endswith(".jsonl") and st in ("UU", "AA"):
            union_lines(path)
            git("add", "--", path, check=True)
            continue
        # rebase では「ours」が取り込み先（先に入った側）。こちらの直しはこのファイルだけ見送る。
        # DU・DD: 先に入った側で消されている → 消したまま。UD: 先に入った側に残っている → 残す
        if st in ("DU", "DD"):
            git("rm", "-q", "--", path)
        else:
            git("checkout", "--ours", "--", path, check=True)
            git("add", "--", path, check=True)
        dropped.append(path)
    return dropped


def pull_rebase(branch, max_steps=50):
    dropped = []
    r = git("pull", "--rebase", "origin", branch)
    steps = 0
    while in_rebase() and steps < max_steps:
        steps += 1
        if not conflicted():
            r = git("-c", "core.editor=true", "rebase", "--continue")
            if r.returncode and not conflicted():
                # 空になったコミット（全部が先に入った側と同じ）は飛ばす
                r = git("rebase", "--skip")
            continue
        dropped += resolve()
        env = dict(os.environ, GIT_EDITOR="true")
        r = subprocess.run(["git", "rebase", "--continue"], capture_output=True, text=True, env=env,
                           encoding="utf-8", errors="replace")
        if r.returncode and not conflicted() and in_rebase():
            git("rebase", "--skip")
    if in_rebase():
        git("rebase", "--abort")
        return False, dropped
    return True, dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--branch", default=os.environ.get("GITHUB_REF_NAME") or "master")
    ap.add_argument("--tries", type=int, default=3)
    a = ap.parse_args()
    all_dropped = []
    for i in range(a.tries):
        ok, dropped = pull_rebase(a.branch)
        all_dropped += dropped
        if ok and git("push").returncode == 0:
            for p in sorted(set(all_dropped)):
                print(f"::warning::ぶつかったため、{p} のこちらの直しを見送りました（先に入った側を残し、次の回で直します）")
            print(f"REBASE_PUSH=ok（見送り {len(set(all_dropped))}件）")
            return 0
        time.sleep(5)
    print("REBASE_PUSH=failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
