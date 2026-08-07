# -*- coding: utf-8 -*-
"""記事に使える一次情報を出す（自社実績＋自サイトの実測データ）

使い方: python scripts/facts.py <site_id> [KW]

AI検索が最も引用したがるのは「そこにしかない数値」。外部統計の引き写しだけでは
どのサイトでも書ける記事になり、引用先に選ばれない。
自社実績と自サイトのGSC実測を、出典と時点つきで提示する。
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "first_party_facts.json"
RANKS = ROOT / "data" / "ranks"


def own_data_facts(site_id):
    """自サイトの実測から言えること（記事に書ける形にして返す）"""
    f = RANKS / f"{site_id}.json"
    if not f.is_file():
        return []
    hist = json.loads(f.read_text(encoding="utf-8"))
    if not hist:
        return []
    rows = hist[sorted(hist)[-1]]
    if not rows:
        return []
    top = sorted(rows, key=lambda r: -r["imp"])[:3]
    total = sum(r["imp"] for r in rows)
    return [{
        "id": "own-gsc",
        "claim": f"当サイトの実測では、直近28日で{len(rows)}個の検索語から"
                 f"のべ{total:,}回表示されました（最多は「{top[0]['kw']}」）",
        "source": "自社サイトのSearch Console実測",
        "as_of": date.today().strftime("%Y-%m"), "verifiable": True,
    }]


def main():
    if len(sys.argv) < 2:
        raise SystemExit("使い方: python scripts/facts.py <site_id> [KW]")
    site_id = sys.argv[1]
    kw = sys.argv[2] if len(sys.argv) > 2 else ""

    data = json.loads(SRC.read_text(encoding="utf-8"))
    picked = [f for f in data["facts"] if site_id in f["sites"]]
    if kw:
        # KWに関係するものを先に出す（関係ないファクトを無理に入れると不自然になる）
        picked.sort(key=lambda f: -sum(1 for t in f["topic"] if t in kw))
    picked += own_data_facts(site_id)

    print(f"■ {site_id} で使える一次情報（記事に最低1つ入れること）")
    for f in picked:
        print(f"\n  ・{f['claim']}")
        print(f"    出典: {f['source']}（{f['as_of']}時点）")
    if data.get("pending"):
        print("\n  ＜まだ書けない数値＞")
        for p in data["pending"]:
            print(f"    - {p['note']}")
    print("\n  ※ ここに無い自社数値は書かないこと。確認できない数値は信頼を失う")


if __name__ == "__main__":
    main()
