# -*- coding: utf-8 -*-
"""リードに至るまでの各段階を測り、どこで落ちているかを出す。

「導線を入れた」だけでは伸びない。入れた導線が押されているのか、
押した先で離脱しているのかが分からないと、次に直す場所が決まらない。
実際、記事のCTAはクリックが記録されておらず、効いているか判断できなかった。

段階は5つ。前の段階に対する割合で見る。

  1. 記事を見た      page_view（記事ページ）
  2. CTAを押した     cta_click / diagnosis_click
  3. フォームを開いた  form_start
  4. 送信した        form_submit / contact_intent

段階は入れ子になっていないため、通過率が100%を超えることがある。
診断結果のメール送信のように、フォームを開かずに送信まで至る経路があるため。

  python scripts/funnel.py            # 直近28日
  python scripts/funnel.py --days 7   # 期間を変える
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STEPS = [
    ("記事を見た", ("page_view",)),
    ("CTAを押した", ("cta_click", "diagnosis_click", "contact_intent")),
    ("フォームを開いた", ("form_start",)),
    ("送信した", ("form_submit", "lead_form_submit", "lead_capture")),
]


def events(prop, days):
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Metric,
                                                    RunReportRequest)
    cl = BetaAnalyticsDataClient(credentials=gcreds.load(
        ROOT / "indexing-service-account.json",
        ["https://www.googleapis.com/auth/analytics.readonly"]))
    r = cl.run_report(RunReportRequest(
        property="properties/" + str(prop),
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="yesterday")],
        dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="eventCount")], limit=200))
    return {x.dimension_values[0].value: int(x.metric_values[0].value) for x in r.rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args()

    conf = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "sites").glob("*.json")}
    worst = []
    for site, c in sorted(conf.items()):
        prop = c.get("ga4_property_id")
        if not prop:
            continue
        try:
            ev = events(prop, a.days)
        except Exception as e:
            print(f"■ {c.get('name', site)}: 取得できません（{str(e)[:60]}）")
            continue
        print(f"\n■ {c.get('name', site)}（直近{a.days}日）")
        prev = None
        for label, names in STEPS:
            n = sum(ev.get(x, 0) for x in names)
            if prev is None:
                rate = ""
            elif prev == 0:
                rate = "  前段階が0"
            else:
                r = n / prev * 100
                rate = f"  前段階の {r:.1f}%"
                if r > 100:
                    # 段階は入れ子になっていない。診断結果のメール送信など、
                    # フォームを開かずに送信まで至る経路がある
                    rate += "（別経路からの流入あり）"
                elif r < 10 and prev >= 20:
                    worst.append((prev - n, site, label, r))
            missing = "  ※この出来事がまだ記録されていません" if n == 0 and any(
                x not in ev for x in names) else ""
            print(f"   {label:<12} {n:6,}{rate}{missing}")
            prev = n

    if worst:
        worst.sort(reverse=True)
        print("\n■ 最も落ちている段階")
        for lost, site, label, r in worst[:3]:
            print(f"   {site}: 「{label}」で {lost:,} 件が落ちています（通過 {r:.1f}%）")
    else:
        print("\n■ 目立った落ち込みはありません"
              "（記録がまだ少ない段階がある場合は判定できません）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
