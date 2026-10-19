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
    rows = res.get("rows") or []
    if not rows:
        # 確定の数字がまだ無い日（Search Console の遅れ）。速報（dataState=all）で同じ日と後の日を見て、同じ日が
        # あればそれを使い、後の日だけに数字があれば本当に0、どちらも無ければ「未取得」として表示・クリックを送らない
        # （2026-10-10・11 は空の応答を0として全サイト表示0で送り、管制塔に0の日が残った）
        res = svc.searchanalytics().query(siteUrl=site_url, body={
            "startDate": day, "endDate": date.today().isoformat(), "dimensions": ["date"], "dataState": "all"}).execute()
        by = {x["keys"][0]: x for x in res.get("rows") or [] if x.get("keys")}
        if day in by:
            rows = [by[day]]
        elif not any(k > day for k in by):
            return {"gsc_missing": True}
    r = rows[0] if rows else {}
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
        # queries は AI が答えた語の数（ai_cite_check.measure_site）。0なら全部落ちた回で、引用0ではなく不明
        if m and m.get("queries"):
            note += f"／実測: 引用{m.get('cited', 0)}/{m.get('queries', 0)}語（{'・'.join((d.get('measured') or {}).get('engines') or [])}）"
        elif m:
            note += "／実測: 不明（AIの答えが取れませんでした）"
        return {"aio_est": n, "aio_note": note}
    except Exception:
        return {}


def _state():
    try:
        d = json.loads(SENT.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(days, retry):
    SENT.parent.mkdir(parents=True, exist_ok=True)
    out = {"days": sorted(days)[-60:]}
    if retry:
        out["retry"] = {d: sorted(s) for d, s in sorted(retry.items()) if s}
    SENT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def sent_days():
    return set(_state().get("days") or [])


def retry_sites():
    """送り直す社 {GA4 の日: [社]}。GA4 や Search Console が落ちて数字の無かった社だけを、CATCH_UP 日まで取り直す"""
    r = _state().get("retry") or {}
    return {d: set(s or []) for d, s in r.items()} if isinstance(r, dict) else {}


def mark_sent(day, retry=None):
    """day を送り済みにする。retry（社の集まり）を渡すと、その社だけ次の回に取り直す。
    以前は GA4 が落ちた日も送り済みにして0で書き、二度と取り直さなかった（2026-10-20）"""
    pend = retry_sites()
    pend.pop(day, None)
    if retry:
        pend[day] = set(retry)
    _write_state(sent_days() | {day}, pend)


def clear_retry(day, done):
    pend = retry_sites()
    left = pend.get(day, set()) - set(done)
    if left:
        pend[day] = left
    else:
        pend.pop(day, None)
    _write_state(sent_days(), pend)


def last_chance(day, today):
    """CATCH_UP 日の窓から次の回に外れる日。この回で取れなければ空欄で送り、取り直しをやめる"""
    return date.fromisoformat(day) <= today - timedelta(days=CATCH_UP)


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


def _no_permission(e):
    s = str(e)
    return "403" in s or "sufficient permission" in s or "PERMISSION_DENIED" in s


def collect(ga_day, only=None):
    """GA4 は ga_day、Search Console は確定を待って2日前（毎日送る回の「前日」と「3日前」の関係のまま）。
    取れなかった社の行には _retry（何が落ちたか）を付ける。送る側が取り直すか空欄で送るかを決める"""
    sc_day = (date.fromisoformat(ga_day) - timedelta(days=2)).isoformat()
    rows = []
    for sid, cfg in sites_mod.load_all().items():
        if only is not None and sid not in only:
            continue
        row = {"site": sid, "date": ga_day, "note": f"GSCは{sc_day}時点"}
        failed = []
        try:
            row.update(ga4(cfg.get("ga4_property_id", ""), ga_day))
        except Exception as e:
            # 権限が無い（導入直後のお客様など）は取り直しても直らない。空欄で送り、理由を書き添える
            if _no_permission(e):
                row["note"] = row["note"] + "／GA4は権限が無く空欄（0ではありません）"
            else:
                failed.append("GA4")
            print(f"  {sid}: GA4取得スキップ（{e}）")
        try:
            got = gsc(f"https://{cfg['domain']}/", sc_day)
            if got.pop("gsc_missing", False):
                row["note"] = row["note"] + "／GSCの数字がまだ出ていません（未取得。0ではありません）"
            row.update(got)
        except Exception as e:
            if not _no_permission(e):
                failed.append("GSC")
            # 403の正体は「権限が制限付き」。長い例外をそのまま出すと原因が埋もれる
            if _no_permission(e):
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
        if failed:
            row["_retry"] = failed
        rows.append(row)
        if sites_mod.is_client(sid):     # お客様の社の数字は CI のログに出さない（日次の記録とメールには入る）
            print(f"{ga_day} {sid:10s} 取得しました")
            continue
        ses = f"{row['sessions']:5d}" if "sessions" in row else "未取得"
        if "impressions" not in row:
            print(f"{ga_day} {sid:10s} セッション{ses}  表示・クリック: 未取得（Search Console の遅れ）"
                  f"  AI参照{row.get('ai', 0):3d}")
            continue
        print(f"{ga_day} {sid:10s} セッション{ses}  表示{row.get('impressions', 0):6d}  "
              f"クリック{row.get('clicks', 0):4d}  AI参照{row.get('ai', 0):3d}")
    return rows


def split_rows(rows, final):
    """送る行と、取り直す社に分ける。取れなかった社は CATCH_UP 日の窓の中では送らずに取り直す
    （kpi_log は行を足すだけなので、空欄で送ってから送り直すと同じ日の行が2本並ぶ）。
    窓から外れる回（final）は空欄のまま送る。0 と書かない（管制塔は無い数字を空欄で書く）"""
    keep, wait = [], set()
    for r in rows:
        failed = r.pop("_retry", None)
        if failed and not final:
            wait.add(r["site"])
            continue
        if failed:
            r["note"] = (r.get("note") or "") + f"／{'・'.join(failed)}を取れず空欄（取り直しの期限切れ。0ではありません）"
        keep.append(r)
    return keep, wait


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
    today = date.today()
    # 前の回に取れなかった社（GA4・Search Console が落ちた社）を先に取り直す。--day の手動は触らない
    jobs = []
    if once and "--day" not in a:
        jobs = [(d, sids) for d, sids in sorted(retry_sites().items()) if sids]
    jobs += [(d, None) for d in days]
    sent = 0
    for ga_day, only in jobs:
        rows = collect(ga_day) if only is None else collect(ga_day, only=only)
        if "--send" not in a:
            continue
        keep, wait = split_rows(rows, final=not once or last_chance(ga_day, today))
        if wait:
            print(f"  {ga_day}: {len(wait)}社は数字を取れなかったため送らず、次の回に取り直します")
        if keep:
            body = {"action": "kpi_log", "rows": keep}
            if only is not None:
                body["partial"] = True       # 取り直した社だけの行。ダッシュボード（全社の合計）は書き換えない
            r = hub_client._post(body)
            if r.get("ok") is False:
                raise SystemExit(f"管制塔が受け取りませんでした（{ga_day}）: {r.get('error')}")
            print(f"\n管制塔へ送信（{ga_day}）: {r.get('rows', 0)}件"
                  + ("（取り直した社）" if only is not None else " / ダッシュボード更新済み"))
            sent += 1
        if once:
            if only is None:
                mark_sent(ga_day, wait)
            else:
                clear_retry(ga_day, set(only) - wait)      # 一覧から外れた社も待ち続けない
    if "--send" not in a:
        print("\n※ 確認モードです。管制塔へ送るには --send を付けてください。")
    print(f"KPI_SENT={sent}")


if __name__ == "__main__":
    main()
