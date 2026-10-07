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


# ── フォームの項目ごとの離脱 ───────────────────────────────
# site.js（と配信先のフォーム）は form_start / form_abandon に form_type を、form_abandon に
# last_field（最後に触った項目）を付ける。form_type の無い form_start は GA4 の自動計測や
# 記事の入力欄のもので、どのフォームか分からないので数えない（実測 2026-10-06: 同じ /contact で
# form_type 付きと無しの form_start が1件ずつ出ていた）。登録前の出来事は「(not set)」になる。
#
# **直すかは人が決める。** ここは数えて候補を出すだけで、フォームを書き換えない（運用者の指示）
FORM_EVENTS = ("form_start", "form_abandon", "form_submit", "lead_capture", "generate_lead")
MIN_START = 30      # 入力開始がこれ未満の月は、項目の良し悪しを決めない（判定前）
MIN_RATE = 10       # 割合は母数がこれ以上のときだけ出す
NOT_SET = ("", "(not set)")
FIELD_LABEL = {
    "name": "お名前", "company": "会社名", "email": "メールアドレス", "tel": "電話番号",
    "topic": "相談の種類", "message": "相談内容", "contact_way": "連絡方法",
    "contact_when": "連絡の時間帯", "url": "サイトのURL", "industry": "業種", "checklist": "資料の選択",
}
# (項目名に含まれる語, 直し方の候補)。上から順に当てる。候補は人が選ぶ材料で、ここでは当てない
FIELD_IDEAS = [
    (("company", "organization", "shop", "store"),
     ("任意にする（個人事業主や検討初期の人は書きにくい）", "届いた後に聞く")),
    (("tel", "phone"), ("任意にする", "連絡方法でメールを選んだ人には聞かない")),
    # メールは住所（address）より先に見る。email_address / mail_address が住所の候補になっていた（2026-10-07 再現）
    (("email", "mail"), ("入力例を添える", "形式の誤りを入力中に示す")),
    (("contact_way", "contact_when", "time"), ("任意にする", "届いた後に聞く")),
    (("message", "body", "detail", "inquiry", "content", "comment"),
     ("入力例を添える", "相談の種類（選択式）だけを必須にし、自由記述は任意にする")),
    (("topic", "category", "kind", "type"), ("選択肢を絞り「まだ決めていない」を足す", "後で聞く")),
    (("url", "website", "site"), ("任意にする", "入力例（https://〜）を添える")),
    (("industry",), ("選択式にする", "「その他」を足す")),
    (("budget", "price", "cost"), ("金額の幅の選択式にする", "届いた後に聞く")),
    (("zip", "address", "pref", "city"), ("届いた後に聞く", "郵便番号から自動で入れる")),
    (("agree", "consent", "privacy"), ("同意の文を短くし、送信ボタンの直前に置く",)),
    (("name",), ("入力例を添える（姓だけでも可と書く）",)),
]
_FORM_CACHE = {}


def field_label(f):
    return FIELD_LABEL.get(f, f or "(不明)")


def field_ideas(f):
    low = (f or "").lower()
    for keys, ideas in FIELD_IDEAS:
        if any(k in low for k in keys):
            return list(ideas)
    return ["その項目が今要るかを見直す（任意にする・届いた後に聞く）"]


def _ga_client():
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    return BetaAnalyticsDataClient(credentials=gcreds.load(
        ROOT / "indexing-service-account.json",
        ["https://www.googleapis.com/auth/analytics.readonly"]))


def _event_filter():
    from google.analytics.data_v1beta.types import Filter, FilterExpression
    return FilterExpression(filter=Filter(field_name="eventName",
                                          in_list_filter=Filter.InListFilter(values=list(FORM_EVENTS))))


def form_rows(prop, start, end):
    """[(YYYYMMDD, eventName, form_type, last_field, pagePath, 件数)]。
    form_type / last_field は GA4 のカスタム定義に登録が要る（ga4_dims.py）"""
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    r = _ga_client().run_report(RunReportRequest(
        property=f"properties/{prop}", date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name=n) for n in ("date", "eventName", "customEvent:form_type",
                                                 "customEvent:last_field", "pagePath")],
        metrics=[Metric(name="eventCount")], dimension_filter=_event_filter(), limit=100000))
    return [tuple(v.value for v in x.dimension_values) + (int(x.metric_values[0].value),) for x in r.rows]


def form_totals(prop, start, end):
    """検算用: 項目の次元を付けずに、日 × 出来事の件数だけを取る {(YYYYMMDD, eventName): 件数}"""
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    r = _ga_client().run_report(RunReportRequest(
        property=f"properties/{prop}", date_ranges=[DateRange(start_date=str(start), end_date=str(end))],
        dimensions=[Dimension(name="date"), Dimension(name="eventName")],
        metrics=[Metric(name="eventCount")], dimension_filter=_event_filter(), limit=1000))
    return {(x.dimension_values[0].value, x.dimension_values[1].value): int(x.metric_values[0].value)
            for x in r.rows}


def summarize_forms(rows):
    """月 → フォームの種類 → 入力開始・離脱・送信・離脱した項目。

    送信は問い合わせの数え方（lead_reconcile.is_lead）に合わせ、同じ日・同じ種類の
    form_submit / lead_capture / generate_lead は足さずに多い方を取る（同じ送信で両方飛ぶ）。
    種類の付かない送信は種類別には入れず、月の合計（sent_total = lead_reconcile.count_rows）にだけ入る"""
    import collections
    import lead_reconcile as LR
    out = {}
    sends = collections.defaultdict(collections.Counter)      # (月, 種類, 日) → {出来事: 件数}
    for d, ev, ft, lf, path, n in rows:
        m = out.setdefault(d[:6], {"types": {}, "untyped_start": 0, "sent_total": 0})
        typed = ft not in NOT_SET
        if ev in ("form_start", "form_abandon") and not typed:
            if ev == "form_start":
                m["untyped_start"] += n
            continue
        if typed:
            t = m["types"].setdefault(ft, {"start": 0, "abandon": 0, "sent": 0,
                                           "fields": collections.Counter()})
            if ev == "form_start":
                t["start"] += n
            elif ev == "form_abandon":
                t["abandon"] += n
                t["fields"][lf if lf not in NOT_SET else "(不明)"] += n
        if typed and LR.is_lead(ev, path):
            sends[(d[:6], ft, d)][ev] += n
    for (ym, ft, _d), c in sends.items():
        out[ym]["types"][ft]["sent"] += max(c.values())
    for d, n in LR.count_rows([(d, ev, path, n) for d, ev, ft, lf, path, n in rows]).items():
        ym = d[:4] + d[5:7]
        if ym in out:
            out[ym]["sent_total"] += n
    return out


def rate(n, base):
    return f"{n / base * 100:.0f}%" if base >= MIN_RATE else "—"


def judge_form(t):
    """入力開始が MIN_START 未満なら「判定前」（項目を挙げない）。
    挙げるのは離脱3件以上で、離脱の母数が10以上なら離脱の2割以上を占める項目（最大3つ）"""
    if t["start"] < MIN_START:
        return {"status": "判定前", "hot": []}
    hot = []
    for f, n in t["fields"].most_common():
        if n < 3:
            break
        share = n / t["abandon"] if t["abandon"] >= MIN_RATE else None
        if share is not None and share < 0.2:
            continue
        hot.append({"field": f, "label": field_label(f), "n": n, "share": share, "ideas": field_ideas(f)})
        if len(hot) >= 3:
            break
    return {"status": "判定済み", "hot": hot}


def month_range(ym, through=None):
    from datetime import date, timedelta
    y, mo = map(int, ym.split("-"))
    end = date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)
    end = min(end, through or end, date.today() - timedelta(days=1))
    return date(y, mo, 1), end


def last_month():
    from datetime import date
    t = date.today().replace(day=1)
    return f"{t.year - (t.month == 1)}-{(t.month - 2) % 12 + 1:02d}"


def form_plan(prop, ym, through=None, rows_fn=None):
    """その月のフォームの種類ごとの数と判定。[{type, start, abandon, sent, status, hot}]（入力開始の多い順）"""
    key = (str(prop), ym, str(through), rows_fn)
    if key not in _FORM_CACHE:
        s, e = month_range(ym, through)
        m = summarize_forms((rows_fn or form_rows)(prop, s, e)).get(ym.replace("-", ""), {"types": {}})
        plans = [{"type": ft, "start": t["start"], "abandon": t["abandon"], "sent": t["sent"], **judge_form(t)}
                 for ft, t in m["types"].items() if t["start"] or t["abandon"]]
        _FORM_CACHE[key] = sorted(plans, key=lambda p: -p["start"])
    return _FORM_CACHE[key]


def dims_missing(e):
    return "not a valid dimension" in str(e)


def form_report_html(prop, ym, through=None, rows_fn=None):
    """月次レポートの節の中身。数と候補を出すだけで、直すかは読み手が決める"""
    import html as H
    try:
        plans = form_plan(prop, ym, through, rows_fn)
    except Exception as e:
        if dims_missing(e):
            return ('<p class="note">GA4 に form_type / last_field のカスタム定義が無いため、'
                    'フォームの項目ごとの離脱を数えられません（管理 → カスタム定義 で登録します）。</p>')
        raise
    intro = ('<p style="font-size:9.5pt">フォームを開いた人が<span class="mark">どの項目で離れたか</span>を'
             '数えています。離脱の項目は「最後に触った項目」で、その項目か次の項目で止まったことを表します。'
             f'入力開始が{MIN_START}件に満たない月は、項目の良し悪しを決めず「判定前」とします。</p>')
    if not plans:
        return intro + '<p class="note">この月は、フォームの種類つきの記録がまだありません。</p>'
    rows = "".join(
        f'<tr><td>{H.escape(p["type"])}</td><td class="num">{p["start"]}</td><td class="num">{p["abandon"]}</td>'
        f'<td class="num">{p["sent"]}</td><td class="num">{rate(p["sent"], p["start"])}</td>'
        f'<td>{p["status"]}</td></tr>' for p in plans[:6])
    table = ('<table><tr><th>フォームの種類</th><th style="width:12%">入力開始</th><th style="width:10%">離脱</th>'
             '<th style="width:10%">送信</th><th style="width:12%">送信率</th><th style="width:14%">判定</th></tr>'
             + rows + '</table>')
    ideas = []
    for p in plans[:6]:
        for h in p["hot"]:
            share = f'（離脱の{h["share"] * 100:.0f}%）' if h["share"] is not None else ""
            ideas.append(f'<tr><td>{H.escape(p["type"])}</td><td><b>{H.escape(h["label"])}</b>'
                         f'　{h["n"]}件{share}</td><td>{H.escape(" / ".join(h["ideas"]))}</td></tr>')
    if ideas:
        sug = ('<h3 style="margin-top:14px">離脱の多い項目と直し方の候補</h3>'
               '<table><tr><th style="width:18%">フォーム</th><th style="width:30%">項目</th><th>候補</th></tr>'
               + "".join(ideas) + '</table>'
               '<p class="note">フォームは自動では変えていません。どの候補を採るか（または採らないか）はご判断ください。</p>')
    elif any(p["status"] == "判定済み" for p in plans):
        sug = '<p class="note">離脱が1つの項目に偏っていません（目立った詰まりは無し）。</p>'
    else:
        sug = (f'<p class="note">どのフォームも入力開始が{MIN_START}件未満のため、項目の判定はまだしません。'
               '割合は母数10件以上のときだけ出しています。</p>')
    return intro + table + sug


def print_forms(conf, months, rows_fn=None, totals_fn=None):
    """サイト × 月 × フォームの種類 × 項目。最後に、項目の次元を付けない取り方と件数を突き合わせる"""
    from datetime import date
    # 手元の Windows で出力をファイル・パイプに流すと cp932 になり、割合の「—」（U+2014）で落ちていた（2026-10-07 再現）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    t = date.today()
    yms = [f"{t.year + (t.month - i - 1) // 12}-{(t.month - i - 1) % 12 + 1:02d}" for i in range(months - 1, -1, -1)]
    s, e = month_range(yms[0])[0], month_range(yms[-1])[1]
    for site, c in sorted(conf.items()):
        prop = c.get("ga4_property_id")
        if not prop:
            continue
        print(f"\n■ {c.get('name', site)}: フォームの項目ごとの離脱（{s}〜{e}）")
        try:
            rows = (rows_fn or form_rows)(prop, s, e)
            tot = (totals_fn or form_totals)(prop, s, e)
        except Exception as ex:
            print("   GA4 に form_type / last_field が未登録です（scripts/ga4_dims.py）" if dims_missing(ex)
                  else f"   取得できません（{str(ex)[:60]}）")
            continue
        summ = summarize_forms(rows)
        for ym in yms:
            m = summ.get(ym.replace("-", ""), {"types": {}, "untyped_start": 0, "sent_total": 0})
            print(f"   {ym}: 問い合わせの送信 {m['sent_total']}件（lead_reconcile の数え方）"
                  f"・種類の無い入力開始 {m['untyped_start']}件は除外")
            if not m["types"]:
                print("     フォームの種類つきの記録はまだありません")
            for ft, tt in sorted(m["types"].items(), key=lambda x: -x[1]["start"]):
                j = judge_form(tt)
                print(f"     [{ft}] 入力開始 {tt['start']}・離脱 {tt['abandon']}・送信 {tt['sent']}"
                      f"（送信率 {rate(tt['sent'], tt['start'])}）… {j['status']}")
                for f, n in tt["fields"].most_common(5):
                    print(f"        最後に触った項目 {field_label(f)}（{f}）: {n}件"
                          f"（離脱の {rate(n, tt['abandon'])}）")
                for h in j["hot"]:
                    print(f"        → 候補（{h['label']}）: {' / '.join(h['ideas'])}")
        bad, old = verify_forms(rows, tot, retention_start())
        print("   検算（出来事の合計 vs 項目別の合計・日ごと）: " + ("一致" if not bad else "不一致 " + ", ".join(bad)))
        if old:
            print(f"   ※{retention_start()} より前は GA4 のデータ保持期間（2か月）の外で、項目の次元を付けると"
                  f"出来事が落ちる（{len(old)}組・日×出来事）。この期間は項目別に数えられない")


def retention_start():
    """GA4 のイベントデータの保持期間（既定2か月）の始まり。カスタムディメンションを付けた問い合わせは
    これより前の出来事を返さない（実測 2026-10-07: コーポレートの 8/1〜8/4 の form_start 6件が、
    date×eventName では出て form_type を付けると消えた）"""
    from datetime import date, timedelta
    t = date.today()
    y, m = (t.year, t.month - 2) if t.month > 2 else (t.year - 1, t.month + 10)
    for d in (t.day, 28):
        try:
            return date(y, m, d)
        except ValueError:
            continue
    return t - timedelta(days=61)


def verify_forms(rows, totals, since):
    """項目別の行を日 × 出来事に足し戻し、次元を付けずに取った件数と比べる。
    返り値: (保持期間内の食い違い, 保持期間外の食い違い)"""
    got = {}
    for d, ev, *_rest, n in rows:
        got[(d, ev)] = got.get((d, ev), 0) + n
    s = since.strftime("%Y%m%d")
    bad, old = [], []
    for k in sorted(set(totals) | set(got)):
        a, b = totals.get(k, 0), got.get(k, 0)
        if a != b:
            (old if k[0] < s else bad).append(f"{k[0]} {k[1]} 合計{a}・項目別{b}")
    return bad, old


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--forms", action="store_true", help="フォームの項目ごとの離脱を月ごとに出す")
    ap.add_argument("--months", type=int, default=3)
    a = ap.parse_args()
    if a.forms:
        conf = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "sites").glob("*.json")}
        print_forms(conf, a.months)
        return 0

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
