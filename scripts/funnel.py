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

# 1回の送信で複数のイベントが飛ぶ。site.js は form_submit と lead_capture の
# 両方を発火させるため、両方を足すと同じ送信を2回数える。
# 実測で「送信10件」と出ていたが、中身は form_submit 4 + lead_capture 6 で、
# 実際の送信は4件だった。数える対象は form_submit 系だけにする。
STEPS = [
    ("記事を見た", ("page_view",)),
    ("CTAを押した", ("cta_click", "diagnosis_click", "contact_intent")),
    ("フォームを開いた", ("form_start",)),
    ("送信した", ("form_submit",)),   # 実際の数は lead_reconcile.is_lead で数える（main）。これは取れないときの代わり。同時に飛ぶ lead_capture は足さない
]

# 送信の中身。問い合わせと購読を同じ箱に入れると、商談につながる数が分からない。
# lead_route は site.js が付けている（newsletter / dl / form / 診断の結果送付）。
# 診断の結果送付は quiz.js が diagnosis_<種別> を付ける（diagnosis_aio / diagnosis_meo）
LEAD_ROUTES = [
    ("問い合わせ・相談", ("form", "diagnosis", "diagnosis_aio", "diagnosis_meo", "site_audit")),
    ("資料ダウンロード", ("dl",)),
    ("ニュースレター購読", ("newsletter",)),
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


def lead_routes(prop, days):
    """送信を経路ごとに数える。

    site.js は送信のたびに lead_route（newsletter / dl / form / diagnosis）を
    付けている。これを見ないと、問い合わせと購読が同じ数に混ざる。
    lead_route は lead_form_submit にも付くため、lead_capture だけに絞る
    （絞らないと結果送付の1回が2件に数えられる）。
    """
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Filter,
                                                    FilterExpression, Metric,
                                                    RunReportRequest)
    cl = BetaAnalyticsDataClient(credentials=gcreds.load(
        ROOT / "indexing-service-account.json",
        ["https://www.googleapis.com/auth/analytics.readonly"]))
    r = cl.run_report(RunReportRequest(
        property="properties/" + str(prop),
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="yesterday")],
        dimensions=[Dimension(name="customEvent:lead_route")],
        dimension_filter=FilterExpression(filter=Filter(
            field_name="eventName",
            string_filter=Filter.StringFilter(value="lead_capture"))),
        metrics=[Metric(name="eventCount")], limit=50))
    out = {}
    for x in r.rows:
        k = x.dimension_values[0].value
        if k and k != "(not set)":
            out[k] = int(x.metric_values[0].value)
    return out


# 記事の最初の章の入力欄（build.inline_tool / publish.insert_inline_entry）の段。
# view/start/submit は記事ページで、result/consult はツールのページで飛ぶ（ツール側は記事から来たときだけ送る）
INLINE_STEPS = [
    ("入力欄が見えた", "inline_tool_view"),
    ("入力を始めた", "inline_tool_start"),
    ("送った", "inline_tool_submit"),
    ("ツールの結果を見た", "inline_tool_result"),
    ("相談へ進んだ", "inline_tool_consult"),
]
# 記事のパス。サイトごとの置き場所（AI集客ラボはカテゴリ直下、配信先の社は url_prefix の下）
INLINE_ARTICLE = {"ai-lab": r"^/(aio|seo|meo|ai-marketing)/[^/]+/$", "subsidy": r"^/blog/[^/]+/$"}


def _page_events(prop, start, end, names):
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Filter,
                                                    FilterExpression, Metric,
                                                    RunReportRequest)
    cl = BetaAnalyticsDataClient(credentials=gcreds.load(
        ROOT / "indexing-service-account.json",
        ["https://www.googleapis.com/auth/analytics.readonly"]))
    r = cl.run_report(RunReportRequest(
        property="properties/" + str(prop),
        date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="eventName"), Dimension(name="pagePath")],
        dimension_filter=FilterExpression(filter=Filter(
            field_name="eventName", in_list_filter=Filter.InListFilter(values=list(names)))),
        metrics=[Metric(name="eventCount")], limit=10000))
    return [(x.dimension_values[0].value, x.dimension_values[1].value, int(x.metric_values[0].value)) for x in r.rows]


def inline_compare(site, prop, since, days=28, rows_fn=None):
    """入力欄を置いた日（data/inline_tool.json）の前後 days 日で、記事から先へ進んだ数を比べる。
    同じ記事群の前後比較なので公開からの週数はそろえない。後ろが days 日に満たないうちは、経過日数を添えて出す。
    返り値は [(段, 前, 後)] と後ろの日数"""
    import re
    from datetime import date, timedelta
    rows_fn = rows_fn or _page_events
    s = date.fromisoformat(since)
    y = date.today() - timedelta(days=1)
    after_end = min(s + timedelta(days=days - 1), y)
    if after_end < s:
        return [], 0
    art = re.compile(INLINE_ARTICLE.get(site, r"^/blog/[^/]+/$"))
    names = ["page_view", "cta_click"] + [n for _, n in INLINE_STEPS]
    out = {}
    for key, (a, b) in (("before", (s - timedelta(days=days), s - timedelta(days=1))), ("after", (s, after_end))):
        c = {}
        for ev, path, n in rows_fn(prop, a, b, names):
            # ツールのページで飛ぶ段は、記事から来たときしか送られないので、ページで絞らない
            if ev in ("inline_tool_result", "inline_tool_consult") or art.match(path):
                c[ev] = c.get(ev, 0) + n
        out[key] = c
    steps = [("記事の訪問", "page_view"), ("記事のボタン・リンクの押下", "cta_click")] + INLINE_STEPS
    return [(label, out["before"].get(ev, 0), out["after"].get(ev, 0)) for label, ev in steps], (after_end - s).days + 1


def print_inline(conf):
    p = ROOT / "data" / "inline_tool.json"
    if not p.is_file():
        return
    sites = json.loads(p.read_text(encoding="utf-8")).get("sites", {})
    for site, v in sites.items():
        prop = (conf.get(site) or {}).get("ga4_property_id")
        if not v.get("since") or not prop:
            continue
        try:
            res, n = inline_compare(site, prop, v["since"])
        except Exception as e:
            print(f"\n■ {conf[site].get('name', site)}: 記事の入力欄の前後比較を取得できません（{str(e)[:60]}）")
            continue
        if not res:
            continue
        print(f"\n■ {conf[site].get('name', site)}: 記事の入力欄の前後比較（置いた日 {v['since']}・前28日／後{n}日）")
        for label, b, a in res:
            print(f"   {label:<16} 前 {b:6,}  後 {a:6,}")
        if n < 28:
            print(f"   ※後ろはまだ{n}日分です。28日そろうまで、前と同じ尺度では比べられません")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args()

    conf = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "sites").glob("*.json")}
    worst = []
    need_setup = set()
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
        # 「送信した」は問い合わせの数え方を1つにそろえる（lead_reconcile.is_lead）。以前はサイト全体の form_submit を
        # 足しており、30秒診断のURL入力まで送信に数え、コーポレートは記録の無い名前を見て0と出していた（2026-10-04）
        import lead_reconcile as LR
        from datetime import date, timedelta
        try:
            sent = sum(LR.ga4_by_day(prop, date.today() - timedelta(days=a.days), date.today() - timedelta(days=1)).values())
        except Exception:
            sent = None
        for label, names in STEPS:
            n = sum(ev.get(x, 0) for x in names)
            if label == "送信した" and sent is not None:
                n = sent
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
        # 送信の中身を分ける。問い合わせと購読を同じ数で語ると、
        # 商談につながる数が分からなくなる。
        # lead_route はGA4の「カスタム定義」に登録しないとAPIから読めない
        try:
            routes = lead_routes(prop, a.days)
        except Exception as e:
            routes = {}
            if "not a valid dimension" in str(e):
                need_setup.add(str(prop))
        if routes:
            print("     ├ 内訳")
            for label2, keys in LEAD_ROUTES:
                v = sum(routes.get(k, 0) for k in keys)
                if v:
                    print(f"     │  {label2:<14} {v:>4}")
            other = sum(v for k, v in routes.items()
                        if not any(k in keys for _, keys in LEAD_ROUTES))
            if other:
                print(f"     │  {'その他・未分類':<14} {other:>4}")

    print_inline(conf)

    if need_setup:
        print("\n■ 設定が要ります（問い合わせと購読を分けて数えるため）")
        print("   GA4 の 管理 → カスタム定義 → カスタムディメンションを作成")
        print("     ディメンション名: lead_route / 範囲: イベント / "
              "イベントパラメータ: lead_route")
        print(f"   対象プロパティ: {', '.join(sorted(need_setup))}")
        print("   登録するまで、送信の内訳（問い合わせ/資料DL/購読）は出せません")

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
