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
    """ぶつかった箇所だけ両方の行を残す（先に入った側の行 → こちらの行のうち先に入った側に無いもの）。
    ぶつかっていない行は触らない（ファイル全体で同じ行を1つにすると、別々に足した同じ内容の行や、
    消した行まで変わる）。diff3 の元の版（||||||| 〜 =======）は捨てる"""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    out, ours, theirs, part = [], [], [], None
    for ln in lines:
        if ln.startswith("<<<<<<<"):
            part, ours, theirs = "ours", [], []
        elif ln.startswith("|||||||") and part == "ours":
            part = "base"
        elif ln.startswith("=======") and part in ("ours", "base"):
            part = "theirs"
        elif ln.startswith(">>>>>>>") and part == "theirs":
            out += ours + [x for x in theirs if x not in ours]
            part = None
        elif part == "ours":
            ours.append(ln)
        elif part == "theirs":
            theirs.append(ln)
        elif part is None:
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
        elif st == "UA":
            # 先に入った側には無く、こちらだけが足したファイル。checkout --ours は版が無いので失敗する。こちらの版を残す
            git("add", "--", path, check=True)
            continue
        else:
            git("checkout", "--ours", "--", path, check=True)
            git("add", "--", path, check=True)
        dropped.append(path)
    return dropped


def skip_if_empty():
    """続けられないコミットを飛ばすのは、中身が空（全部が先に入った側と同じ）のときだけ。
    rebase --skip はコミットを丸ごと捨てるので、中身があるのに飛ばすと直しを黙って失い「成功」と出る。
    飛ばしたら True、中身があって飛ばさなかったら False（呼び出し側は中止して失敗を返す）"""
    if git("diff", "--cached", "--quiet").returncode == 0 and git("diff", "--quiet").returncode == 0:
        git("rebase", "--skip")
        return True
    print(f"::warning::取り込みが進まず、中身のあるコミットを飛ばせないため中止します: {git('status', '--short').stdout[:300]}")
    return False


def pull_rebase(branch, max_steps=50):
    dropped = []
    r = git("pull", "--rebase", "origin", branch)
    steps = 0
    while in_rebase() and steps < max_steps:
        steps += 1
        if not conflicted():
            r = git("-c", "core.editor=true", "rebase", "--continue")
            if r.returncode and not conflicted() and not skip_if_empty():
                break
            continue
        dropped += resolve()
        env = dict(os.environ, GIT_EDITOR="true")
        r = subprocess.run(["git", "rebase", "--continue"], capture_output=True, text=True, env=env,
                           encoding="utf-8", errors="replace")
        if r.returncode and not conflicted() and in_rebase() and not skip_if_empty():
            break
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
