# -*- coding: utf-8 -*-
"""リッチリザルトの取りこぼしを毎週見る（FAQ・動画・HowTo が検索結果に出ているか）。

**なぜ要るか**: FAQ・HowTo・動画のリッチリザルトは、同じ順位でクリックを増やす。
構造化データは全記事に出しているが、「実際に検索結果で表示されているか」は見ていなかった。
GSC の searchAppearance で絞って、表示回数が十分あるのにリッチリザルトが一度も出ない
記事を出す。原因が JSON-LD の壊れ（parse できない・FAQ の問答が本文と食い違う）なら、
機械で直せる分は直す（build のやり直し）。

  python scripts/rich_check.py
出す印: RICH_OK=yes/no（no は JSON-LD が壊れている記事があるとき）
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SITE = ROOT / "site"
APPEARANCES = {"RICH_SNIPPET": "リッチスニペット（FAQ等）", "VIDEO": "動画", "REVIEW_SNIPPET": "レビュー"}
MIN_IMP = 50


def appearances(sc, domain, start, end):
    """検索での見え方ごとの表示・クリック。**searchAppearance は単独でしか取れない**
    （page と組むと 400。実測 2026-09-24）。ページ単位の取りこぼしは分からないので、
    サイト単位の有無と、こちら側で確かめられる JSON-LD の壊れを見る"""
    body = {"startDate": start, "endDate": end, "dimensions": ["searchAppearance"], "rowLimit": 50}
    try:
        rows = sc.searchanalytics().query(siteUrl=f"https://{domain}/", body=body).execute().get("rows", [])
    except Exception as e:
        print(f"   {domain}: 見え方を取れません（{str(e)[:50]}）")
        return None
    return {r["keys"][0]: (int(r["impressions"]), int(r["clicks"])) for r in rows}


def jsonld_ok(html):
    """JSON-LD が全部 parse できるか（壊れていれば表示されない）"""
    for s in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            json.loads(s)
        except ValueError:
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args()
    import gsc_detail as G
    import sites as S
    end = (date.today() - timedelta(days=3)).isoformat()
    start = (date.today() - timedelta(days=3 + a.days)).isoformat()
    try:
        sc = G.client()
    except Exception as e:
        print(f"GSC を読めません（{str(e)[:60]}）\nRICH_OK=unknown")
        return 0
    broken, missing = [], 0
    for sid, cfg in S.load_all().items():
        ap_ = appearances(sc, cfg["domain"], start, end)
        if ap_ is None:
            continue
        total = sum(int(r["impressions"]) for r in G.q(sc, cfg["domain"], start, end, None, 1))
        rich_imp = sum(v[0] for k, v in ap_.items() if k != "AMP_BLUE_LINK")
        print(f"■ {cfg['name']}: 表示{total:,}回のうち、リッチリザルト付きの表示 {rich_imp:,}回"
              + (" / " + "・".join(f"{APPEARANCES.get(k, k)} {v[0]:,}回" for k, v in sorted(ap_.items(), key=lambda kv: -kv[1][0]))
                 if ap_ else " / 見え方の記録なし（FAQ・動画のリッチリザルトが一度も出ていない）"))
        if not ap_ and total >= MIN_IMP:
            missing += 1
    # こちら側で確かめられる原因: JSON-LD の壊れ（parse できなければ表示されない）
    n_pages = 0
    for path in SITE.glob("*/*/index.html"):
        if path.parts[-3] in ("glossary", "compare", "topics", "industry", "data"):
            continue
        n_pages += 1
        if not jsonld_ok(path.read_text(encoding="utf-8", errors="ignore")):
            broken.append("/".join(path.parts[-3:-1]))
    print(f"■ JSON-LD の検査: {n_pages}ページ / 壊れ {len(broken)}ページ")
    for u in broken[:10]:
        print(f"要対応: JSON-LD が壊れています（リッチリザルトが出ません）: /{u}/")
    if missing:
        # FAQ と HowTo のリッチリザルトは Google が 2023年に一般サイト向けの表示をやめている
        # （FAQ は行政・医療の権威サイトだけ、HowTo は全廃）。出ないこと自体は異常ではないので
        # 要対応にしない。効くのは動画（VideoObject）とレビュー。動画が付いた記事が増えたら VIDEO を見る
        print(f"（参考）リッチリザルト付きの表示が無いサイト {missing}つ。FAQ/HowTo は Google が一般サイトへの表示を"
              "やめているため異常ではない。動画埋め込みが増えたら VIDEO の表示を見る")
    print(f"RICH_MISSING={missing}")
    print(f"RICH_OK={'no' if broken else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
