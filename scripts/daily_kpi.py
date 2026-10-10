# -*- coding: utf-8 -*-
"""3サイトのKPIを集計して管制塔のダッシュボードへ送る（毎日1回）

使い方:
    python scripts/daily_kpi.py                  # 集計結果を表示するだけ
    python scripts/daily_kpi.py --send           # 管制塔へ送信して台帳を更新
    python scripts/daily_kpi.py --send --once    # 送った日を記録し、同じ日は2回送らない（抜けた日は7日前まで埋める）
    python scripts/daily_kpi.py --send --once --day 2026-09-28   # その日の分だけ（送り済みなら送らない）

定時の実行は .github/workflows/daily-kpi.yml（毎日 10:13 JST・記事の枠とは別のワークフロー）。
以前は記事の枠0の中にあり、枠0が月の上限・量産の兆候・取りこぼしで飛ぶと集計も飛んだ（2026-09-28〜10-03 の6日）。

Search Console API は Apps Script の追加サービスに無いため、集計はここ（Python）で行い、
GASは受け取って書くだけにしている。認証は既存のサービスアカウントを流用する。

必要な設定:
    indexing-service-account.json（GA4は閲覧者、GSCはオーナー権限）
    sites/*.json の ga4_property_id … 未設定のサイトはGA4分をスキップする
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_client  # noqa: E402
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SA = ROOT / "indexing-service-account.json"
# 送った日（GA4 の日）。管制塔の kpi_log は行を足すだけなので、同じ日を2回送ると KPIレポート・AIO計測に
# 同じ行が2本並ぶ。CI は daily-kpi.yml がキャッシュで持ち越す（.gitignore）
SENT = ROOT / "data" / "kpi_sent.json"
CATCH_UP = 7          # 取りこぼした日を埋めるのは7日前まで
AI_DOMAINS = {
    # AI経由の流入は参照元ドメインでしか見分けられない。ここに無いサービスは
    # 「Referral」に埋もれてAI流入として数えられないため、主要どころを網羅する
    # ChatGPT の検索結果のリンクは utm_source=openai を付けるため、参照元が「openai」（ドメインなし）になる。
    # 「openai.com」だけを探していて、直近28日でコーポレート14件・補助金4件を数え漏らしていた（2026-10-04）
    "chatgpt": ["chatgpt.com", "chat.openai.com", "openai"],
    "perplexity": ["perplexity.ai"],
    "gemini": ["gemini.google.com", "bard.google.com"],
    "copilot": ["copilot.microsoft.com", "bing.com/chat", "edgeservices.bing.com"],
    "claude": ["claude.ai", "anthropic.com"],
    "grok": ["grok.com", "x.ai", "grok.x.com"],
    # chat-assistant.persol-group.co.jp はパーソルの社内向けAIチャット（2026-10-05 運用者の判断でAI経由に数える）
    "その他AI": ["you.com", "poe.com", "felo.ai", "genspark.ai", "chat-assistant.persol-group.co.jp",
                 "chat.mistral.ai", "phind.com", "kagi.com", "duckduckgo.com/aichat",
                 "meta.ai", "iask.ai", "andisearch.com", "deepseek.com", "chat.qwen.ai",
                 "notebooklm.google", "aistudio.google.com", "search.brave.com/summarizer"],
}
# **参照元の分類はこの1か所だけ**。monthly_report / group_report / data_auto はここを読む。
# 別々に持つと、新しいAIが出たときに1つだけ古くなり、レポートごとに数字が食い違う
AI_LABELS = {"chatgpt": "ChatGPT", "perplexity": "Perplexity", "gemini": "Gemini", "copilot": "Copilot",
             "claude": "Claude", "grok": "Grok", "その他AI": "その他AI"}


AI_SOURCES = AI_DOMAINS      # 別名（data_auto が AI_SOURCES の名で読む）


def ai_label(source):
    """GA4 の参照元（sessionSource）→ 表示名。AIでなければ None"""
    s = str(source or "").lower()
    for key, doms in AI_DOMAINS.items():
        if any(d in s for d in doms):
            return AI_LABELS.get(key, key)
    return None


def creds(scopes):
    import gcreds
    return gcreds.load(SA, scopes)


def ga4(prop, day):
    """GA4: セッション・PV・CV・AI参照元の内訳"""
    if not prop:
        return {}
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    c = BetaAnalyticsDataClient(credentials=creds(
        ["https://www.googleapis.com/auth/analytics.readonly"]))
    p = f"properties/{prop}"
    rng = [DateRange(start_date=day, end_date=day)]
    rep = c.run_report(RunReportRequest(property=p, date_ranges=rng, metrics=[
        Metric(name="sessions"), Metric(name="screenPageViews")]))
    row = rep.rows[0].metric_values if rep.rows else None
    # CVは conversions 指標でなく lead_capture を直接数える（GA4側の設定が無いと0になるため）。
    # form_submit は同時に飛ぶので足さない
    ev = c.run_report(RunReportRequest(property=p, date_ranges=rng,
                                       dimensions=[Dimension(name="eventName")],
                                       metrics=[Metric(name="eventCount")], limit=300))
    evs = {r.dimension_values[0].value: int(r.metric_values[0].value) for r in ev.rows}
    out = {"sessions": int(row[0].value) if row else 0,
           "pv": int(row[1].value) if row else 0,
           "cv": evs.get("lead_capture", 0), "ai": 0, "breakdown": {}}
    rep2 = c.run_report(RunReportRequest(property=p, date_ranges=rng,
                                         dimensions=[Dimension(name="sessionSource")],
                                         metrics=[Metric(name="sessions")]))
    for r in rep2.rows:
        src = r.dimension_values[0].value.lower()
        n = int(r.metric_values[0].value)
        for key, doms in AI_DOMAINS.items():
            if any(d in src for d in doms):
                out["ai"] += n
                out["breakdown"][key] = out["breakdown"].get(key, 0) + n
    # どのページに着地したか。AI検索は「引用されたページ」に来るので、0か非0かより
    # ページが分かるほうが次の手につながる
    out["ai_pages"] = []
    if out["ai"]:
        rep3 = c.run_report(RunReportRequest(
            property=p, date_ranges=rng,
            dimensions=[Dimension(name="sessionSource"), Dimension(name="landingPage")],
            metrics=[Metric(name="sessions")], limit=200))
        for r in rep3.rows:
            src = r.dimension_values[0].value.lower()
            if any(d in src for doms in AI_DOMAINS.values() for d in doms):
                out["ai_pages"].append({"source": src, "page": r.dimension_values[1].value,
                                        "sessions": int(r.metric_values[0].value)})
    return out


def gsc(site_url, day):
    """Search Console: 表示・クリック・CTR・平均順位（確定まで3日ほどかかる）"""
    from googleapiclient.discovery import build
    svc = build("searchconsole", "v1", credentials=creds(
        ["https://www.googleapis.com/auth/webmasters.readonly"]))
    res = svc.searchanalytics().query(siteUrl=site_url,
                                      body={"startDate": day, "endDate": day}).execute()
    r = (res.get("rows") or [{}])[0]
    return {"impressions": int(r.get("impressions", 0)), "clicks": int(r.get("clicks", 0)),
            "ctr": round(r.get("ctr", 0) * 100, 2), "position": round(r.get("position", 0), 1)}


def aio_estimate(site_id):
    """AI Overview に取られている表示の推定。GSCのCTRの歪みから ai_citation_check が
    月ごとに出す（data/ai_citations/YYYY-MM.json）。APIでは取れない値なので推定と明記する"""
    try:
        # 月の記録（YYYY-MM.json）だけを見る。*.json だと followup.json が「最新」に来て、推定が空になっていた。
        # お客様の社の分は data/clients/<id>/private/ にある（client_private が合わせる）
        import client_private as CP
        months = CP.citation_months()
        if not months:
            return {}
        d = CP.load_citations(months[-1])
        s = (d.get("sites") or {}).get(site_id) or {}
        n = int(s.get("suspect_taken") or 0)
        note = f"推定（{d.get('date', '')} CTR歪み・判定{s.get('judged', 0)}語中）"
        # 実測（ai_cite_check）があれば添える。推定と実測を同じ欄で区別できるように
        m = ((d.get("measured") or {}).get("sites") or {}).get(site_id)
        if m:
            note += f"／実測: 引用{m.get('cited', 0)}/{m.get('queries', 0)}語（{'・'.join((d.get('measured') or {}).get('engines') or [])}）"
        return {"aio_est": n, "aio_note": note}
    except Exception:
        return {}


def sent_days():
    try:
        return set(json.loads(SENT.read_text(encoding="utf-8")).get("days") or [])
    except (OSError, ValueError, AttributeError):
        return set()


def mark_sent(day):
    SENT.parent.mkdir(parents=True, exist_ok=True)
    SENT.write_text(json.dumps({"days": sorted(sent_days() | {day})[-60:]}, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")


def days_to_send(sent, today):
    """送る GA4 の日（古い順）。前日がまだなら前日。送った記録があれば、最後に送った日の翌日から前日までの
    抜けも埋める（CATCH_UP 日まで）。GitHub の定時は取りこぼすことがある。記録が無いときは前日だけ
    （記録より前の日は、記事の枠の中で送っていたかもしれないので二重に送らない）"""
    y = today - timedelta(days=1)
    if not sent:
        return [y.isoformat()]
    d = max(date.fromisoformat(max(sent)) + timedelta(days=1), y - timedelta(days=CATCH_UP - 1))
    out = []
    while d <= y:
        if d.isoformat() not in sent:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def collect(ga_day):
    """GA4 は ga_day、Search Console は確定を待って2日前（毎日送る回の「前日」と「3日前」の関係のまま）"""
    sc_day = (date.fromisoformat(ga_day) - timedelta(days=2)).isoformat()
    rows = []
    for sid, cfg in sites_mod.load_all().items():
        row = {"site": sid, "date": ga_day, "note": f"GSCは{sc_day}時点"}
        try:
            row.update(ga4(cfg.get("ga4_property_id", ""), ga_day))
        except Exception as e:
            print(f"  {sid}: GA4取得スキップ（{e}）")
        try:
            row.update(gsc(f"https://{cfg['domain']}/", sc_day))
        except Exception as e:
            # 403の正体は「権限が制限付き」。長い例外をそのまま出すと原因が埋もれる
            if "403" in str(e) or "sufficient permission" in str(e):
                print(f"  {sid}: GSC取得スキップ（権限不足。"
                      "python scripts/gsc_check.py で対処手順を確認してください）")
            else:
                print(f"  {sid}: GSC取得スキップ（{e}）")
        row.update(aio_estimate(sid))
        # CV は台帳の相談の数（売り込み・社内の試し送信を除く）。GA4 の lead_capture は照合用に cv_ga4 に残す。
        # 台帳に無い社・台帳の始まる前の日は GA4 のまま（lead_reconcile.leads。2026-10-10 運用者の指示）
        try:
            import lead_reconcile as LR
            day = date.fromisoformat(ga_day)
            lead = LR.leads(sid, day, day, ga4_n=row.get("cv"))
            row["cv_ga4"] = row.get("cv")
            if lead["n"] is not None:
                row["cv"] = lead["n"]
            if lead["source"] == "ledger":
                c = lead["counts"]
                row["note"] = row["note"] + f"／CVは台帳の相談（売り込み{c['sales']}・テスト{c['test']}を除く）"
        except Exception as e:
            print(f"  {sid}: 台帳の問い合わせを数えられず、CV は GA4 の送信のまま（{str(e)[:60]}）")
        rows.append(row)
        if sites_mod.is_client(sid):     # お客様の社の数字は CI のログに出さない（日次の記録とメールには入る）
            print(f"{ga_day} {sid:10s} 取得しました")
            continue
        print(f"{ga_day} {sid:10s} セッション{row.get('sessions', 0):5d}  表示{row.get('impressions', 0):6d}  "
              f"クリック{row.get('clicks', 0):4d}  AI参照{row.get('ai', 0):3d}")
    return rows


def main():
    a = sys.argv[1:]
    if not SA.exists():
        raise SystemExit("indexing-service-account.json がありません")
    once = "--once" in a
    if "--day" in a:
        days = [date.fromisoformat(a[a.index("--day") + 1]).isoformat()]
    elif once:
        days = days_to_send(sent_days(), date.today())
    else:
        days = [(date.today() - timedelta(days=1)).isoformat()]
    if once:
        done = sent_days()
        for d in days:
            if d in done:
                print(f"{d} は送り済みです（同じ日を2回送りません。管制塔の kpi_log は行を足すだけ）")
        days = [d for d in days if d not in done]
    if "--send" in a and not hub_client.enabled():
        raise SystemExit("HUB_URL が未設定です")
    sent = 0
    for ga_day in days:
        rows = collect(ga_day)
        if "--send" not in a:
            continue
        r = hub_client._post({"action": "kpi_log", "rows": rows})
        if r.get("ok") is False:
            raise SystemExit(f"管制塔が受け取りませんでした（{ga_day}）: {r.get('error')}")
        print(f"\n管制塔へ送信（{ga_day}）: {r.get('rows', 0)}件 / ダッシュボード更新済み")
        sent += 1
        if once:
            mark_sent(ga_day)
    if "--send" not in a:
        print("\n※ 確認モードです。管制塔へ送るには --send を付けてください。")
    print(f"KPI_SENT={sent}")


if __name__ == "__main__":
    main()
