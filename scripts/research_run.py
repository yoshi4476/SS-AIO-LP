# -*- coding: utf-8 -*-
"""業種調査を、まだ集計の無い業種から順に、サブスクと無料枠だけで回す（課金APIは使わない）。

1回の実行は --minutes で打ち切り、次の実行で続きから（答えは30日キャッシュされるので、途中まで聞いた分は聞き直さない）。

    python scripts/research_run.py --minutes 110
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=110)
    a = ap.parse_args()
    import research_extra as RX
    t0 = time.time()
    done = []
    for slug, name, *_ in RX.INDUSTRIES:
        if slug not in RX.load():
            continue
        if (ROOT / "data" / "research" / f"{slug}-summary.json").is_file():
            continue
        if (time.time() - t0) / 60 > a.minutes - 20:          # 1業種に約15〜20分かかる
            print(f"RESEARCH_RUN=paused 残り時間が足りないので次の実行で続ける（済: {done}）")
            return 0
        print(f"■ {name}（{slug}）", flush=True)
        r = subprocess.run([sys.executable, "scripts/industry_ai_sources.py", "--industry", slug, "--sub"], cwd=ROOT,
                           text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and (ROOT / "data" / "research" / f"{slug}-summary.json").is_file():
            done.append(slug)
    print(f"RESEARCH_RUN=done 今回集計した業種: {done}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
