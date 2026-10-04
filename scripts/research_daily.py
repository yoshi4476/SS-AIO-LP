# -*- coding: utf-8 -*-
"""業種調査の ChatGPT の聞き直しを、このパソコンで毎日続けて回し、集まった集計を公開する（タスクスケジューラが呼ぶ）。

ChatGPT はサブスク（Codex）でしか聞かないため CI では動かせず、手元で一度止まると続きを回すものが無かった
（2026-10-04 13:39 に止まり、約12時間なにも動いていなかった）。毎日起動して research_run に続きを任せる。

- 前の回がまだ動いていれば何もしない（同じ問いを二重に聞かない）
- 集計は origin の最新に重ねて push する。手元のブランチは使わない（手元の未公開の変更を混ぜない）
- 聞き直す業種が無くなれば research_run がすぐ終わり、公開するものも無い

    python scripts/research_daily.py            # 回して公開する
    python scripts/research_daily.py --minutes 60
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "automation" / "logs" / "research_daily.lock"
LOG = ROOT / "automation" / "logs" / "research_daily.log"


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M} {msg}\n")


def alive(pid):
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, errors="replace")
    return str(pid) in r.stdout


def running_elsewhere():
    """ロックを通さずに起動した research_run（手で起動した回）も見る。重なると同じ問いを二重に聞いて枠を食う"""
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                        "Where-Object { $_.CommandLine -like '*research_run.py*' } | Measure-Object | "
                        "Select-Object -ExpandProperty Count"], capture_output=True, text=True, errors="replace")
    return (r.stdout.strip() or "0") != "0"


def git(*a, cwd=ROOT, check=True):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def publish():
    """data/research の集計を origin の最新に重ねて push する。衝突・失敗なら何も残さない"""
    git("fetch", "-q", "origin", "master")
    tmp = Path(tempfile.mkdtemp(prefix="research-pub-"))
    wt = tmp / "wt"
    try:
        git("worktree", "add", "-q", "--detach", str(wt), "origin/master")
        for p in (ROOT / "data" / "research").glob("*.json"):
            shutil.copy2(p, wt / "data" / "research" / p.name)
        git("add", "data/research", cwd=wt)
        if not git("diff", "--cached", "--name-only", cwd=wt).stdout.strip():
            return "変更なし"
        git("-c", "user.name=AIO Pipeline Bot", "-c", "user.email=noreply@7senses.co.jp", "commit", "-q", "-m",
            f"業種調査の ChatGPT の聞き直し分を足す（{datetime.now():%Y-%m-%d}・手元のサブスクで回した分）", cwd=wt)
        r = git("push", "-q", "origin", "HEAD:master", cwd=wt, check=False)
        return "push しました" if r.returncode == 0 else f"push できませんでした: {r.stderr[-160:]}"
    finally:
        git("worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=1380)
    a = ap.parse_args()
    if LOCK.is_file():
        pid = LOCK.read_text(encoding="utf-8").strip()
        if pid.isdigit() and alive(int(pid)):
            log(f"前の回（PID {pid}）が動いているので何もしません")
            return 0
    if running_elsewhere():
        log("research_run が別に動いているので何もしません")
        return 0
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    LOCK.write_text(str(os.getpid()), encoding="utf-8")
    try:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        with (ROOT / "automation" / "logs" / "research_refill.log").open("a", encoding="utf-8") as out:
            r = subprocess.run([sys.executable, "scripts/research_run.py", "--minutes", str(a.minutes)],
                               cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, env=env)
        log(f"research_run 終了（{r.returncode}）")
        log(f"公開: {publish()}")
    finally:
        LOCK.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
