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
    import ai_cite_check as AC
    deadline = t0 + a.minutes * 60

    def thin(slug):
        """集計はあるが、ChatGPT の回答が半分に満たない（利用上限で取れなかった）"""
        p = ROOT / "data" / "research" / f"{slug}-summary.json"
        if not p.is_file():
            return False
        s = json.loads(p.read_text(encoding="utf-8"))
        return (s.get("answered") or {}).get("ChatGPT", 0) < s.get("questions", 50) / 2

    def wait_limit():
        """サブスクの利用上限が明けるまで待つ。時間内に明けなければ False（次の実行で続ける）"""
        until = AC.limit_until("ChatGPT")
        if not until:
            return True
        if until.timestamp() > deadline - 20 * 60:
            return False
        print(f"   ChatGPT の利用上限が明けるまで待ちます（{until:%H:%M}）", flush=True)
        time.sleep(max(0, until.timestamp() - time.time()))
        return True

    for slug, name, *_ in RX.INDUSTRIES:
        if slug not in RX.load():
            continue
        if (ROOT / "data" / "research" / f"{slug}-summary.json").is_file() and not thin(slug):
            continue
        if (time.time() - t0) / 60 > a.minutes - 20 or not wait_limit():   # 1業種に約15〜20分かかる
            print(f"RESEARCH_RUN=paused 残り時間が足りないので次の実行で続ける（済: {done}）")
            return 0
        print(f"■ {name}（{slug}）{'（ChatGPT の聞き直し）' if thin(slug) else ''}", flush=True)
        # Claude・Gemini の答えは30日キャッシュされるので、聞き直しで課金や二重の負荷は出ない
        # 生の回答がある業種は欠けた問いだけを聞き足す。--sub で聞き直すと生の回答を丸ごと書き直し、
        # その回に聞かなかった Gemini・Perplexity の答えが消えていた（2026-10-05 に6業種）
        mode = "--refill" if (ROOT / "data" / "research" / f"{slug}-raw.json").is_file() else "--sub"
        r = subprocess.run([sys.executable, "scripts/industry_ai_sources.py", "--industry", slug, mode], cwd=ROOT,
                           text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 and (ROOT / "data" / "research" / f"{slug}-summary.json").is_file():
            done.append(slug)
    left = [s for s, *_ in RX.INDUSTRIES if thin(s)]
    print(f"RESEARCH_RUN=done 今回集計した業種: {done}" + (f" / ChatGPT が足りない業種: {left}" if left else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
