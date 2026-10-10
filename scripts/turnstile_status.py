# -*- coding: utf-8 -*-
"""ロボットよけ（Cloudflare Turnstile）の記録を読む。断る段階へ切り替える前に、本物の送信が ok になっているかを見る。

記録は管制塔の「ロボットよけ」タブ（contact.hub.gs の botLog_）。個人の情報は入っていない（サイト・経路・種別・結果・ドメインだけ）。
  経路 … ページから直接（補助金・コーポレート。管制塔が Cloudflare に確かめる）／サーバーで確認（AI集客ラボの受付が確かめた結果）
  結果 … ok / none（答えが無い）/ invalid / error（確かめられない）

    python scripts/turnstile_status.py            # 直近7日
    python scripts/turnstile_status.py --days 30
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    import hub_client as HC
    r = HC._post({"action": "bot_status", "days": a.days}) or {}
    if not r.get("ok"):
        print(f"記録を読めませんでした: {r.get('error', '応答なし')}")
        return 1
    print(f"管制塔: 断る={'はい' if r.get('enforce') else 'いいえ（記録だけ）'}／確かめの鍵={'あり' if r.get('secret') else 'なし'}")
    print(f"直近{r.get('days')}日（サイト｜経路｜結果｜疎通確認｜処置: 件数）")
    for k, n in sorted((r.get("counts") or {}).items()):
        print(f"  {k}: {n}")
    print("最近の記録")
    for row in r.get("recent") or []:
        print("  " + " / ".join(str(x) for x in row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
