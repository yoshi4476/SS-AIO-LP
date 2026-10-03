# -*- coding: utf-8 -*-
"""AI診断（/tools/ai-check/）の段階ごとの数（週次）。どこで落ちているかを数字で見る（F5・2026-10-04）。

  入口を押した → 診断ページを見た → 診断を始めた → 結果が出た → 次の一歩を押した
  → メールから戻った（結果・3日後・1か月後）→ あとで相談に来た（台帳のメールで突き合わせ）

GA4 は人をまたいで追えないので、最後の「相談に来た」は管制塔の台帳（ai_check_stats）で数える。
GA4 のパラメータは管理画面で登録しないと読めないため、出来事の名前（cta_<ID>・ai_check_*）と
標準の項目（pagePath・sessionCampaignName）だけで数える。

    python scripts/aicheck_funnel.py            # 直近28日
    python scripts/aicheck_funnel.py --days 7
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
PAGE = "/tools/ai-check/"
CAMPAIGNS = {"aicheck_result": "結果のメール", "aicheck_day3": "3日後のメール", "aicheck_recheck": "1か月後のメール"}


def ga4(prop, days, dims, metric="eventCount", flt=None):
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    cl = BetaAnalyticsDataClient(credentials=gcreds.load(
        ROOT / "indexing-service-account.json", ["https://www.googleapis.com/auth/analytics.readonly"]))
    req = RunReportRequest(property=f"properties/{prop}",
                           date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="yesterday")],
                           dimensions=[Dimension(name=d) for d in dims], metrics=[Metric(name=metric)], limit=1000)
    if flt is not None:
        req.dimension_filter = flt
    return [([v.value for v in r.dimension_values], int(r.metric_values[0].value)) for r in cl.run_report(req).rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args()
    prop = json.loads((ROOT / "sites" / "ai-lab.json").read_text(encoding="utf-8")).get("ga4_property_id")
    if not prop:
        print("AICHECK_FUNNEL_OK=unknown（GA4 のプロパティが設定されていません）")
        return 0
    try:
        ev = {k[0]: n for k, n in ga4(prop, a.days, ["eventName"])}
        views = sum(n for (path, name), n in ga4(prop, a.days, ["pagePath", "eventName"])
                    if name == "page_view" and path.rstrip("/") + "/" == PAGE)
        camp = {k[0]: n for k, n in ga4(prop, a.days, ["sessionCampaignName"], "sessions")}
    except Exception as e:
        print(f"AICHECK_FUNNEL_OK=unknown（GA4 を読めません: {str(e)[:80]}）")
        return 1
    # 入口: data-cta に ai_check を含むボタン・リンク（結果画面の次の一歩は除く）
    entry = {k[4:]: n for k, n in ev.items() if k.startswith("cta_") and "ai_check" in k and "ai_check_next" not in k}
    try:
        import hub_client
        st = hub_client._post({"action": "ai_check_stats", "days": a.days}) or {}
    except Exception:
        st = {}

    print(f"■ AI診断の段階ごとの数（直近{a.days}日）")
    rows = [("入口を押した（記事・ヘッダー・固定ボタン）", sum(entry.values())),
            ("診断ページを見た", views),
            ("診断を始めた", ev.get("ai_check_start", 0)),
            ("結果が出た", ev.get("ai_check_done", 0)),
            ("次の一歩を押した", ev.get("ai_check_next", 0))]
    prev = None
    for label, n in rows:
        rate = f"  前段階の {n / prev * 100:.0f}%" if prev else ""
        print(f"   {label:<24} {n:5,}{rate}")
        prev = n
    for k, label in CAMPAIGNS.items():
        print(f"   {label}から戻った（セッション） {camp.get(k, 0):5,}")
    if st.get("ok"):
        print(f"   台帳: 診断 {st['checks']}回・{st['people']}人（0問 {st['cited0']} / 1〜2問 {st['cited12']} / 3問 {st['cited3']}）"
              f"・案内の希望 {st['optin']}人・あとで相談 {st['consult']}人")
    else:
        print("   台帳: 読めませんでした")
    if entry:
        print("   入口の内訳: " + "・".join(f"{k} {n}" for k, n in sorted(entry.items(), key=lambda x: -x[1])[:6]))
    # 知らせる条件: 診断ページは見られているのに、始める人がいない（入力の手前で落ちている）
    weak = views >= 20 and ev.get("ai_check_start", 0) == 0
    print(f"AICHECK_FUNNEL_OK={'no' if weak else 'yes'}")
    if weak:
        print(f"   要対応: 診断ページが{views}回見られているのに、診断を始めた人が0人です（入力欄・ロボットよけの表示を確かめる）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
