# -*- coding: utf-8 -*-
"""1ページ目まであと一歩の語を、記事ごとにまとめて出す。

11〜20位は「露出はあるのに選ばれていない」層で、新規記事より速く成果が出る。
狙う語ではなく実際に順位を持っている語で拾うため、書き手の思い込みが入らない。

  python scripts/rewrite_list.py                 # 3サイトぶんの作業リスト
  python scripts/rewrite_list.py --site ai-lab   # 1サイトだけ
  python scripts/rewrite_list.py --json out.json # 機械が読む形で書き出す
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gsc_detail as G

LOW, HIGH = 10.5, 20.5   # 2ページ目の帯。10.5から拾うのは、境目が日で揺れるため


def articles():
    """slug → 記事の情報。URLの末尾で引けるようにする"""
    out = {}
    for f in sorted((ROOT / "articles").glob("*.md")):
        raw = f.read_text(encoding="utf-8-sig")
        if not raw.startswith("---"):
            continue
        fm = raw.split("---", 2)[1]
        g = lambda k: (re.search(rf"^{k}:\s*(.+)$", fm, re.M) or [0, ""])[1].strip().strip('"')
        out[f.stem] = {"slug": f.stem, "title": g("title"), "kw": g("keyword"),
                       "cat": g("category"), "date": g("date"), "path": str(f)}
    return out


def cat_to_site():
    """カテゴリ → サイト。記事の所属はカテゴリで決まる"""
    out = {}
    for f in (ROOT / "sites").glob("*.json"):
        c = json.loads(f.read_text(encoding="utf-8"))
        for k in (c.get("categories") or {}):
            out[k] = f.stem
    return out


def collect(site, conf, arts):
    """ページ×クエリで引き、あと一歩の語を記事ごとにまとめる"""
    cat_site = cat_to_site()
    from datetime import date, timedelta
    sc = G.client()
    end = date.today() - timedelta(days=3)      # 確定分だけを見る
    start = end - timedelta(days=27)
    rows = G.q(sc, conf["domain"], str(start), str(end),
               dims=["page", "query"], limit=25000)
    by_page = defaultdict(list)
    for r in rows:
        pos = r["position"]
        if not (LOW <= pos <= HIGH):
            continue
        page, query = r["keys"][0], r["keys"][1]
        by_page[page].append({"q": query, "pos": round(pos, 1),
                              "imp": r["impressions"], "clk": r["clicks"]})
    out = []
    for page, qs in by_page.items():
        slug = page.rstrip("/").rsplit("/", 1)[-1]
        a = arts.get(slug)
        # 301で移した記事は、旧ドメインの実績として出る。所属はカテゴリで決める
        if a and a.get("cat"):
            site = cat_site.get(a["cat"], site)
        qs.sort(key=lambda x: -x["imp"])
        out.append({"site": site, "page": page, "slug": slug,
                    "title": (a or {}).get("title", "（記事が見つかりません）"),
                    "kw": (a or {}).get("kw", ""), "path": (a or {}).get("path", ""),
                    "date": (a or {}).get("date", ""),
                    "queries": qs, "imp": sum(x["imp"] for x in qs),
                    "clk": sum(x["clk"] for x in qs), "n": len(qs)})
    out.sort(key=lambda x: -x["imp"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", help="1サイトだけ見る")
    ap.add_argument("--json", help="機械が読む形で書き出す先")
    ap.add_argument("--top", type=int, default=0, help="上位いくつまで出すか")
    a = ap.parse_args()

    conf = json.loads((ROOT / "sites" / "_all.json").read_text(encoding="utf-8")) \
        if (ROOT / "sites" / "_all.json").exists() else {
            p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "sites").glob("*.json")}
    arts = articles()
    allrows = []
    for site, c in conf.items():
        if a.site and site != a.site:
            continue
        try:
            allrows += collect(site, c, arts)
        except Exception as e:
            print(f"  {site}: 取得できません（{type(e).__name__}: {e}）")

    allrows.sort(key=lambda x: -x["imp"])
    rows = allrows[:a.top] if a.top else allrows
    total_q = sum(r["n"] for r in allrows)
    print(f"\n1ページ目まであと一歩の語: {total_q}語 / 対象記事 {len(allrows)}本"
          f"（表示合計 {sum(r['imp'] for r in allrows):,}・クリック {sum(r['clk'] for r in allrows)}）")
    print("表示が多い記事ほど、直したときの伸びが大きい。上から着手する。\n")
    for i, r in enumerate(rows, 1):
        print(f"{i:2d}. [{r['site']}] {r['title'][:38]}")
        print(f"    {r['page']}")
        print(f"    表示 {r['imp']:,} / クリック {r['clk']} / あと一歩の語 {r['n']}件")
        for x in r["queries"][:5]:
            print(f"       {x['pos']:>5}位  表示{x['imp']:>4}  {x['q'][:44]}")
        if r["n"] > 5:
            print(f"       ほか {r['n']-5}語")
        print()

    if a.json:
        Path(a.json).write_text(json.dumps(allrows, ensure_ascii=False, indent=1),
                                encoding="utf-8", newline="")
        print(f"書き出し: {a.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
