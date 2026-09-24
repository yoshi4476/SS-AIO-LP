# -*- coding: utf-8 -*-
"""国別の表示・クリック・順位を出す（GSC の country 次元・無料）。

**なぜ要るか**: 多言語の要約ページや訪日客向けの記事が、米国・台湾・韓国・中国・香港で
どう出ているかは、国で分けないと見えない（全体の数字に日本が埋もれる）。
言語ページ（/en/ /zh/ /ko/）がある社は、そのページだけの国別も出す。

  python scripts/country_rank.py                  # 全サイト（直近28日）
  python scripts/country_rank.py --site ai-lab --days 90
出す印: COUNTRY_OK=yes。結果: docs/country-<site>.md
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DOCS = ROOT / "docs"
NAMES = {"jpn": "日本", "usa": "米国", "twn": "台湾", "kor": "韓国", "chn": "中国", "hkg": "香港",
         "tha": "タイ", "sgp": "シンガポール", "aus": "オーストラリア", "gbr": "英国", "can": "カナダ",
         "phl": "フィリピン", "vnm": "ベトナム", "mys": "マレーシア", "idn": "インドネシア", "fra": "フランス", "deu": "ドイツ"}
FOCUS = ("usa", "twn", "kor", "chn", "hkg")      # 訪日客の多い国（必ず表に出す）


def query(sc, domain, start, end, filt=None):
    body = {"startDate": start, "endDate": end, "dimensions": ["country"], "rowLimit": 250}
    if filt:
        body["dimensionFilterGroups"] = [{"filters": [{"dimension": "page", "operator": "contains", "expression": filt}]}]
    try:
        return sc.searchanalytics().query(siteUrl=f"https://{domain}/", body=body).execute().get("rows", [])
    except Exception as e:
        print(f"   {domain}: 取れません（{str(e)[:60]}）")
        return None


def table(rows, title):
    rows = sorted(rows, key=lambda r: -r["impressions"])
    top = rows[:12] + [r for r in rows[12:] if r["keys"][0] in FOCUS]
    lines = [f"### {title}", "", "| 国 | 表示 | クリック | CTR | 平均順位 |", "|:--|--:|--:|--:|--:|"]
    for r in top:
        c = r["keys"][0]
        lines.append(f"| {NAMES.get(c, c)} | {int(r['impressions']):,} | {int(r['clicks']):,} | "
                     f"{r['clicks'] / r['impressions'] * 100 if r['impressions'] else 0:.1f}% | {r['position']:.1f} |")
    return lines + [""]


def main():
    import gsc_detail as G
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args()
    end = (date.today() - timedelta(days=3)).isoformat()
    start = (date.today() - timedelta(days=3 + a.days)).isoformat()
    try:
        sc = G.client()
    except Exception as e:
        print(f"GSC を読めません（{str(e)[:60]}）\nCOUNTRY_OK=unknown")
        return 0
    DOCS.mkdir(exist_ok=True)
    for sid, cfg in S.load_all().items():
        if a.site and sid != a.site:
            continue
        rows = query(sc, cfg["domain"], start, end)
        if rows is None:
            continue
        total = sum(r["impressions"] for r in rows)
        abroad = sum(r["impressions"] for r in rows if r["keys"][0] != "jpn")
        lines = [f"# 国別の検索（{cfg['name']}・{start}〜{end}）", "",
                 f"表示 {int(total):,}回のうち、日本以外 {int(abroad):,}回（{abroad / total * 100 if total else 0:.1f}%）", ""]
        lines += table(rows, "サイト全体")
        for lg in (cfg.get("languages") or []):
            lr = query(sc, cfg["domain"], start, end, f"/{lg}/")
            if lr:
                lines += table(lr, f"{lg} の要約ページだけ")
        (DOCS / f"country-{sid}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"■ {cfg['name']}: 表示 {int(total):,}回 / 日本以外 {abroad / total * 100 if total else 0:.1f}%"
              + "".join(f" / {NAMES[c]} {int(sum(r['impressions'] for r in rows if r['keys'][0] == c)):,}" for c in FOCUS
                        if any(r["keys"][0] == c for r in rows)))
    print("COUNTRY_OK=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
