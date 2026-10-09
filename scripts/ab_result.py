# -*- coding: utf-8 -*-
"""A/Bテストの結果を読む。どちらの文言が押されたかを実測で決める。

記事のCTAは、記事を見た544件に対しクリック38件しか出ていなかった。
どの文言なら押されるかは推測では決まらない。半々で出し分けて数える。

  A案: いま記事に書かれている文言
  B案: build.py の data-ab-b で当てている文言

見るのは2つの出来事。
  ab_impression … その文言が表示された回数（ab_variant で a / b が分かる）
  cta_click     … 押された回数（同じく ab_variant が付く）

差が小さいうちは判定しない。少ない回数で決めると、次の週に逆転する。

  python scripts/ab_result.py            # 直近28日
  python scripts/ab_result.py --days 14
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
MIN_SAMPLE = 100          # これ未満は判定しない


def pull(prop, days):
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Metric,
                                                    RunReportRequest)
    cl = BetaAnalyticsDataClient(credentials=gcreds.load(
        ROOT / "indexing-service-account.json",
        ["https://www.googleapis.com/auth/analytics.readonly"]))
    out = {}
    # パラメータ（ab_variant）はGA4の管理画面で登録しないと集計できない。
    # 出来事の名前にA/Bを入れてあるので、登録なしで数えられる
    r = cl.run_report(RunReportRequest(
        property="properties/" + str(prop),
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="yesterday")],
        dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="eventCount")], dimension_filter=event_filter(), limit=1000))
    for x in r.rows:
        out[x.dimension_values[0].value] = int(x.metric_values[0].value)
    return out


PREFIXES = ("ab_impression_", "cta_click_")


def event_filter():
    """A/B の出来事だけに絞る。全イベント名を上限つきで取ると、名前が増えたときに ab_impression_* を取りこぼす"""
    from google.analytics.data_v1beta.types import Filter, FilterExpression, FilterExpressionList
    return FilterExpression(or_group=FilterExpressionList(expressions=[
        FilterExpression(filter=Filter(field_name="eventName", string_filter=Filter.StringFilter(
            match_type=Filter.StringFilter.MatchType.BEGINS_WITH, value=p)))
        for p in PREFIXES]))


def tests():
    """試験の一覧（名前, 表示の出来事, 押下の出来事の頭）。記事CTAは試験名の無い古い名前のまま"""
    import build as B
    t = [("記事CTA", "ab_impression_", "cta_click_")]
    for key, _b in sorted(set(B.STICKY_AB.values())):
        t.append((f"固定ボタン {key}", f"ab_impression_{key}_", f"cta_click_{key}_"))
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / "scripts"))
    import sites as S               # 計測の ID はお客様の社だと非公開の置き場にある（load_all が重ねる）
    conf = S.load_all()
    for site, c in sorted(conf.items()):
        prop = c.get("ga4_property_id")
        if not prop:
            continue
        try:
            d = pull(prop, a.days)
        except Exception as e:
            print(f"■ {c.get('name', site)}: 取得できません（{str(e)[:70]}）")
            continue
        print(f"\n■ {c.get('name', site)}（直近{a.days}日）")
        for name, imp, clk in tests():
            judge(name, d.get(imp + "a", 0), d.get(imp + "b", 0), d.get(clk + "a", 0), d.get(clk + "b", 0))
    return 0


def judge(name, imp_a, imp_b, clk_a, clk_b):
    if not (imp_a or imp_b):
        print(f"   {name}: この期間の表示がありません")
        return
    ra = clk_a / imp_a * 100 if imp_a else 0
    rb = clk_b / imp_b * 100 if imp_b else 0
    print(f"   {name}")
    print(f"     A案  表示{imp_a:5,}  クリック{clk_a:4,}  {ra:5.2f}%")
    print(f"     B案  表示{imp_b:5,}  クリック{clk_b:4,}  {rb:5.2f}%")
    if imp_a + imp_b < MIN_SAMPLE:
        print(f"     → まだ判定しません（合計表示 {imp_a + imp_b} 件。{MIN_SAMPLE}件を超えてから読みます）")
    elif abs(ra - rb) < max(ra, rb) * 0.2:
        print("     → 差が小さく、どちらとも言えません")
    else:
        print(f"     → いまのところ {'B案' if rb > ra else 'A案'} が優勢です。もう1週同じ傾向なら、勝った文言に寄せます")


if __name__ == "__main__":
    sys.exit(main())
