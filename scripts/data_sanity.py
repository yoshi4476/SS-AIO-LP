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
  5. AI流入の分類が漏れていないか（GA4 の「AI Assistant」と自前の分類を2通りで比べる・
     AIらしいのに数えていない参照元・自然検索に入った openai）
  6. 問い合わせが台帳にあるのに GA4 に送信が無い日（逆向きは lead_reconcile）・サイト不明の台帳の行

  python scripts/data_sanity.py            # 3サイトぶん確かめる
  python scripts/data_sanity.py --site ai-lab
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 同時に飛ぶイベント。足すと同じ行動を2回数える
# （コーポレートは 2026-10-08 から、相談の入口で cta_click と contact_intent も同時に送る）
CO_FIRED = [
    ("form_submit", "lead_capture"),
    ("form_submit", "lead_newsletter"),
    ("cta_click", "diagnosis_click"),
    ("cta_click", "contact_intent"),
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


def organic_split(rows):
    """sessionSourceMedium の (値, セッション) → Google の自然検索 / ほかの検索エンジン / 自然検索に入ったAI。

    GSC が数えるのは Google だけ。「/ organic」を全部足すと bing・yahoo と、ChatGPT の検索結果
    （utm_source=openai で「openai / organic」になる）まで混ざる。実測（28日・2026-10-04）で
    コーポレートは organic 161 のうち Google は 79、openai が16だった"""
    import daily_kpi as K
    g = other = ai = 0
    for sm, n in rows:
        src, _, med = sm.partition(" / ")
        if med.strip() != "organic":
            continue
        if K.ai_label(src):
            ai += n
        elif src.strip() == "google":
            g += n
        else:
            other += n
    return g, other, ai


def check_ga_vs_gsc(sid, cfg, prop, days, out):
    """GA4の自然検索（Google）のセッションと、GSCのクリック数が近いか。

    片方だけが壊れていれば、ここで食い違いが出る。
    完全一致はしない（GA4はセッション・GSCはクリック）が、桁が違えば異常。
    """
    import gsc_detail as G
    rows = ga(prop, ["sessionSourceMedium"], ["sessions"], days)
    g, other, ai = organic_split([(x.dimension_values[0].value, int(x.metric_values[0].value)) for x in rows])
    if ai:
        out.append(("注意", f"GA4の自然検索（organic）に AI 経由が{ai}セッション入っています"
                            f"（openai / organic など）。GA4 のチャネル「Organic Search」にも入るので、"
                            f"チャネルで数えた自然検索（月次レポートなど）にはAI経由が混ざっています"))
    sc = G.client()
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    clicks = total_clicks(sc, cfg["domain"], start, end)
    if clicks is None or (g == 0 and clicks == 0):
        return g + other + ai, clicks
    big, small = max(g, clicks), min(g, clicks)
    if small == 0 or big / max(1, small) >= 3:
        out.append(("注意", f"GA4の自然検索（Google）{g}セッション と "
                            f"GSCのクリック {clicks}回 が食い違っています"
                            f"（どちらかの計測が壊れている可能性）"))
    return g + other + ai, clicks


# AIらしい参照元の手がかり。daily_kpi.AI_DOMAINS に無いものがここに当たれば、分類が漏れている。
# 1語で広く当てない（「chat」は chatwork、「kimi」は日本語のドメインにも出る）
AI_HINT = re.compile(
    r"chat-?gpt|openai|perplexity|gemini|bard\.|copilot|claude|anthropic|grok|deepseek|qwen|tongyi|"
    r"doubao|kimi\.(?:ai|com|moonshot)|moonshot\.cn|mistral|phind|felo\.ai|genspark|metaso|yiyan\.|"
    r"chatglm|zhipu|monica\.im|character\.ai|lmarena|notebooklm|aistudio|"
    r"chat-?assistant|ai-?assistant|aichat|ai-chat|chatbot|(?:^|\.)chat\.[a-z]", re.I)


def ai_unclassified(sources):
    """(sessionSource, セッション) のうち、AIらしいのに daily_kpi.ai_label が拾わないもの"""
    import daily_kpi as K
    return [(s, n) for s, n in sources if AI_HINT.search(s or "") and not K.ai_label(s)]


# GA4 の既定のチャネル名は「AI Assistant」（単数）。複数形で探して0件と誤報した（2026-10-04）。
# 名前の揺れで0になるのを避けるため、どちらでも拾う
AI_CHANNEL = re.compile(r"^ai assistants?$", re.I)


def ai_channel_gap(channels, sources):
    """GA4 が「AI Assistant」に分けたセッションと、自前の分類（daily_kpi.ai_label）の合計。
    GA4 の方が多ければ、自前の分類が漏れている（2通りで数えて食い違いを見る）"""
    import daily_kpi as K
    ga_ai = sum(n for c, n in channels if AI_CHANNEL.match((c or "").strip()))
    ours = sum(n for s, n in sources if K.ai_label(s))
    return ga_ai, ours


def check_ai_referrals(prop, days, out):
    ch = [(x.dimension_values[0].value, int(x.metric_values[0].value))
          for x in ga(prop, ["sessionDefaultChannelGroup"], ["sessions"], days)]
    src = [(x.dimension_values[0].value, int(x.metric_values[0].value))
           for x in ga(prop, ["sessionSource"], ["sessions"], days)]
    ga_ai, ours = ai_channel_gap(ch, src)
    if ga_ai > ours:
        out.append(("注意", f"GA4 は AI Assistant に{ga_ai}セッション、自前の分類（daily_kpi.AI_DOMAINS）は"
                            f"{ours}セッション。分類から漏れている参照元があります"))
    miss = ai_unclassified(src)
    if miss:
        out.append(("注意", "AIらしい参照元が AI 流入に数えられていません: "
                            + "、".join(f"{s}（{n}）" for s, n in miss[:5])
                            + "。AIなら daily_kpi.AI_DOMAINS に足してください"))
    return ga_ai, ours


def lead_mismatch(ga_by_day, led_by_day, ack=()):
    """GA4 の問い合わせ（lead_reconcile.is_lead で数えた日ごと）と台帳の行の食い違いのうち、
    lead_reconcile が見ない向き＝**台帳にあるのに GA4 に送信が無い日**を返す。

    GA4 の方が多い日（台帳への取りこぼし）は lead_reconcile が知らせる。台帳は同じ人の
    24時間以内の再送信を1行にまとめるので、GA4 が多いこと自体は食い違いではない。
    逆向きは、送信の計測が飛んでいない（タグの外れ・別の入口）か、手で足した行"""
    return [d for d, n in sorted(led_by_day.items())
            if n > 0 and not ga_by_day.get(d) and d not in set(ack)]


def check_leads(sid, cfg, prop, days, ledger, out):
    import lead_reconcile as L
    if cfg.get("lead_hub") is False:
        return None
    if ledger is None:
        out.append(("注意", "問い合わせの台帳を読めず、GA4 との照合をしていません"))
        return None
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    gad = L.ga4_by_day(str(prop), start, end)
    led = {d: n for d, n in ledger.get(sid, {}).items() if d >= start.isoformat()}
    for d in lead_mismatch(gad, led, L.ACKED.get(sid, {})):
        out.append(("注意", f"{d} の問い合わせは台帳に{led[d]}行あるのに、GA4 に送信の記録がありません"
                            "（送信の計測が飛んでいないか。手で足した行なら問題なし）"))
    # 問い合わせとして数えるのは台帳の相談だけ（売り込み・社内の試し送信を除く）。GA4 と比べるのは台帳の全行
    try:
        txt = L.consult_text(L.ledger_counts(L.ledger_rows(start), sid=sid))
    except Exception:
        txt = ""
    return sum(gad.values()), sum(led.values()), txt


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
    ledger = None
    try:
        import lead_reconcile as L
        ledger = L.ledger_by_site(date.today() - timedelta(days=a.days))
    except Exception as e:
        print(f"  問い合わせの台帳を読めません（{str(e)[:60]}）\n")
    if ledger and ledger.get("?"):
        print(f"  注意 問い合わせの台帳にサイトを判定できない行が{sum(ledger['?'].values())}件あります"
              "（サイト別の問い合わせ数から漏れます。台帳のサイト名を直してください）\n")
        total_warn += 1
    for sid, cfg in S.load_all().items():
        if a.site and sid != a.site:
            continue
        prop = cfg.get("ga4_property_id")
        print(f"  {cfg['name'][:22]}")
        out = []
        if not prop:
            # 未設定は「確かめられなかった」ではない。注意に数えると毎週 SANITY_OK=no が消えない
            print("     GA4未設定のため確かめません\n")
            continue
        try:
            check_double_count(prop, a.days, out)
            tot, bad = check_invalid(prop, a.days, out)
            org, clicks = check_ga_vs_gsc(sid, cfg, prop, a.days, out)
            tc, bc = check_brand_share(cfg, a.days, out)
            ga_ai, ours = check_ai_referrals(prop, a.days, out)
            leads = check_leads(sid, cfg, prop, a.days, ledger, out)
            gsc = (f"GSCクリック{clicks}（うち指名{bc}）" if clicks is not None and bc is not None
                   else "GSCは取得できず確かめられません")
            print(f"     セッション{tot}（うち国不明{bad}）/ 自然検索{org} / {gsc}")
            print(f"     AI流入: GA4のAI Assistant {ga_ai} / 自前の分類 {ours}"
                  + (f" ／ 問い合わせ: GA4 {leads[0]}件・台帳 {leads[1]}行" + (f"（{leads[2]}）" if leads[2] else "")
                     if leads else ""))
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
