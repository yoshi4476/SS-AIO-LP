# -*- coding: utf-8 -*-
"""research_all.cmd の続き。下書きに落ちた業種を、同じファイルへの同時書き込みを避けて順番にやり直す。
1) 最初の下書きが終わる（research_run が始まる）まで待つ → 2) 落ちた業種の下書き → 3) 最初の実行の完了を待つ → 4) 残りを集計"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "automation" / "research_all.log"
OUT = ROOT / "automation" / "research_followup.log"


def wait(marker, hours=20):
    t0 = time.time()
    while time.time() - t0 < hours * 3600:
        if LOG.is_file() and marker in LOG.read_text(encoding="utf-8", errors="ignore"):
            return True
        time.sleep(60)
    return False


def run(*args):
    with OUT.open("a", encoding="utf-8") as f:
        subprocess.run([sys.executable, *args], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)


wait("■")
run("scripts/research_extra.py", "--draft")
wait("RESEARCH_ALL_DONE")
run("scripts/research_run.py", "--minutes", "1400")
with OUT.open("a", encoding="utf-8") as f:
    f.write("RESEARCH_FOLLOWUP_DONE\n")
