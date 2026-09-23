# -*- coding: utf-8 -*-
"""枠に割り当てるサイトの並び順を出す。優先度の小さい順、同じなら名前順。

**なぜ要るか**: 以前は名前順だけで並べていた。3サイトでは偶然 ai-lab が先頭に
来ていたが、「abc-」で始まるクライアントを1社足すだけで、いちばん伸ばしたい
サイトが後ろの枠へ押し出される。枠0（JST 08:00）は最も早く公開できる枠なので、
優先度は設定に明示して持つ（sites/<id>.json の priority。小さいほど先）。

    python scripts/site_order.py          # 1行1サイト
    python scripts/site_order.py --show   # 優先度つきで見る
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "sites"
DEFAULT = 99   # priority を書いていないサイトは後ろへ


def order():
    rows = []
    for p in sorted(SITES.glob("*.json")):
        if p.stem == "sample":
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        n = d.get("priority")
        rows.append((n if isinstance(n, int) else DEFAULT, p.stem))
    return [s for _, s in sorted(rows)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if not a.show:
        for s in order():
            print(s)
        return 0
    print("■ 枠に割り当てる順（priority が小さいほど先。枠0は JST 08:00）")
    for i, s in enumerate(order()):
        try:
            d = json.loads((SITES / f"{s}.json").read_text(encoding="utf-8"))
        except Exception:
            d = {}
        n = d.get("priority", "(未設定)")
        print(f"  {i}番目  {s:<12} priority={n}  枠{i} と 枠{i + len(order())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
