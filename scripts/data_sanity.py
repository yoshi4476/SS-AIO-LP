# -*- coding: utf-8 -*-
"""数字を報告する前に、その数字が信じられるかを確かめる。

このセッションで、次の誤りを続けて出した。いずれも1つの出所だけを見て、
検算せずに報告し、その上に次の判断を重ねたことが原因だった。

  - 「送信10件・転換率5.7%」→ 実際は4件・2.3%
    （site.js が1回の送信で form_submit と lead_capture の両方を発火させており、
     両方を足していた）
  - 「9%はGoogle広告」→ 広告は出していない。国も取れない不正な流入だった
  - 「コーポレートは73%達成」→ クリック17回のうち15回が指名検索だった

見る観点は4つ。どれも「数えた結果」ではなく「数え方が壊れていないか」を見る。

  1. 同時に飛ぶイベントを重ねて数えていないか（二重計上）
  2. 実ユーザーでない流入が混ざっていないか（国が取れない・1ページに集中）
  3. GA4とGSCの数字が食い違っていないか（片方だけ壊れていれば分かる）
  4. 指名検索を除いても同じ結論になるか（ブランド名で水増しされていないか）

  python scripts/data_sanity.py            # 3サイトぶん確かめる
  python scripts/data_sanity.py --site ai-lab
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 同時に飛ぶイベント。足すと同じ行動を2回数える
CO_FIRED = [
    ("form_submit", "lead_capture"),
    ("form_submit", "lead_newsletter"),
    ("cta_click", "diagnosis_click"),
]


def ga(prop, dims, mets, days=28, filt=None):
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Metric,
                                                    RunReportRequest)
    cl = BetaAnalyticsDataClient(credentials=gcreds.load(
        ROOT / "indexing-service-account.json",
        ["https://www.googleapis.com/auth/analytics.readonly"]))
    r = cl.run_report(RunReportRequest(
        property=f"properties/{prop}",
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="yesterday")],
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name=m) for m in mets], limit=500,
        dimension_filter=filt))
    return r.rows


def check_double_count(prop, days, out):
    """同時に飛ぶイベントを重ねて数えていないか"""
    rows = ga(prop, ["eventName"], ["eventCount"], days)
    ev = {x.dimension_values[0].value: int(x.metric_values[0].value) for x in rows}
    for a, b in CO_FIRED:
        if ev.get(a) and ev.get(b):
            out.append(("注意", f"{a}({ev[a]}) と {b}({ev[b]}) が両方出ています。"
                                f"足すと同じ行動を2回数えます"))
    return ev


def check_invalid(prop, days, out):
    """実ユーザーでない流入が混ざっていないか"""
    rows = ga(prop, ["sessionSourceMedium", "country"], ["sessions"], days)
    tot = bad = 0
    worst = {}
    for x in rows:
        s = int(x.metric_values[0].value)
        tot += s
        if x.dimension_values[1].value in ("(not set)", ""):
            bad += s
            worst[x.dimension_values[0].value] = worst.get(
                x.dimension_values[0].value, 0) + s
    if bad:
        top = max(worst.items(), key=lambda kv: kv[1])
        out.append(("注意", f"国が取れない流入 {bad}/{tot}セッション"
                            f"（{bad / max(1, tot) * 100:.0f}%）。"
                            f"最多は {top[0]} の {top[1]}件。実ユーザーとは限りません"))
    return tot, bad


def total_clicks(sc, domain, start, end):
    """クリック・表示の合計は必ず「次元なし」で取る（CLAUDE.md 0.1）。

    query次元は検索数の少ない語を返さないため、合計が大きく減る。実測（28日・
    2026-08-23〜09-19）では query次元 4/17/2回 に対し、次元なしは 25/43/51回だった。
    補助金は実際の3.9%しか見えておらず、毎週「GA4と食い違う」と誤報していた。
    """
    # 2通りで一致したものだけを使う（measure 経由）。
    # 次元つきで数えて誤報を出し続けた経緯があるため、書き方で守る
    import measure
    try:
        return measure.gsc_totals(domain, start, end)[1]
    except measure.Disagree as e:
        print(f"  注意 {domain}: 計測が一致しません → {e}")
        return None
    except Exception as e:
        # 0 を返すと「GA4と食い違う」「指名検索の検査を飛ばす」に化ける
        print(f"  注意 {domain}: GSCから取得できず確かめられません → {str(e)[:60]}")
        return None


def check_ga_vs_gsc(sid, cfg, prop, days, out):
    """GA4の自然検索セッションと、GSCのクリック数が近いか。

    片方だけが壊れていれば、ここで食い違いが出る。
    完全一致はしない（GA4はセッション・GSCはクリック）が、桁が違えば異常。
    """
    import gsc_detail as G
    rows = ga(prop, ["sessionSourceMedium"], ["sessions"], days)
    organic = sum(int(x.metric_values[0].value) for x in rows
                  if x.dimension_values[0].value.endswith("/ organic"))
    sc = G.client()
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    clicks = total_clicks(sc, cfg["domain"], start, end)
    if clicks is None or (organic == 0 and clicks == 0):
        return organic, clicks
    big, small = max(organic, clicks), min(organic, clicks)
    if small == 0 or big / max(1, small) >= 3:
        out.append(("注意", f"GA4の自然検索 {organic}セッション と "
                            f"GSCのクリック {clicks}回 が食い違っています"
                            f"（どちらかの計測が壊れている可能性）"))
    return organic, clicks


def check_brand_share(cfg, days, out):
    """クリックのうち、指名検索が占める割合。

    指名検索が大半なら、その数字は記事の力ではない。
    「コーポレートは73%達成」と報告したが、クリック17回のうち15回が
    指名検索だった。記事の実力とは別物として扱う。
    """
    import brand_search as B
    import gsc_detail as G
    sc = G.client()
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    try:
        rows = G.q(sc, cfg["domain"], str(start), str(end), ["query"], 25000, raise_errors=True)
    except Exception:
        return None, None
    # 分母は必ず次元なしの合計。query次元の合計を分母にすると指名の割合が跳ね上がる
    # （実測: コーポレートは 15/17=88% と出たが、本当は 15/43=35% 以下だった）
    tot = total_clicks(sc, cfg["domain"], start, end)
    if tot is None:
        return None, None
    brand = sum(r["clicks"] for r in rows if B.BRAND.search(r["keys"][0]))
    if tot and brand / tot >= 0.5:
        out.append(("注意", f"クリック{tot}回のうち{brand}回以上が指名検索です"
                            f"（{brand / tot * 100:.0f}%以上）。"
                            f"記事の実力を語るなら指名検索を除いて数えてください"))
    return tot, brand


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args()
    import sites as S

    print("■ 数字を信じてよいかの確認\n")
    total_warn = 0
    for sid, cfg in S.load_all().items():
        if a.site and sid != a.site:
            continue
        prop = cfg.get("ga4_property_id")
        print(f"  {cfg['name'][:22]}")
        out = []
        try:
            check_double_count(prop, a.days, out)
            tot, bad = check_invalid(prop, a.days, out)
            org, clicks = check_ga_vs_gsc(sid, cfg, prop, a.days, out)
            tc, bc = check_brand_share(cfg, a.days, out)
            gsc = (f"GSCクリック{clicks}（うち指名{bc}）" if clicks is not None and bc is not None
                   else "GSCは取得できず確かめられません")
            print(f"     セッション{tot}（うち国不明{bad}）/ 自然検索{org} / {gsc}")
            if clicks is None or bc is None:
                # 確かめられなかった（計測の不一致を含む）ものを「崩れなし」と出さない
                out.append(("注意", "GSCのクリック合計を確かめられず、GA4との照合と指名検索の割合を見ていません"))
        except Exception as e:
            print(f"     注意 確認できません: {str(e)[:60]}")
            total_warn += 1
            continue
        for lv, msg in out:
            print(f"     {lv} {msg}")
            total_warn += 1
        if not out:
            print("     OK  数え方に崩れは見つかりませんでした")
        print()
    print(f"  注意 {total_warn}件")
    print("SANITY_OK=" + ("no" if total_warn else "yes"))
    print("  ※ ここで注意が出た数字は、そのまま報告しないこと。"
          "原因を確かめてから使う")
    return 0


if __name__ == "__main__":
    sys.exit(main())
