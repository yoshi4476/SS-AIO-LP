# -*- coding: utf-8 -*-
"""3サイトのKPIを集計して管制塔のダッシュボードへ送る（毎日1回）

使い方:
    python scripts/daily_kpi.py           # 集計結果を表示するだけ
    python scripts/daily_kpi.py --send    # 管制塔へ送信して台帳を更新

Search Console API は Apps Script の追加サービスに無いため、集計はここ（Python）で行い、
GASは受け取って書くだけにしている。認証は既存のサービスアカウントを流用する。

必要な設定:
    indexing-service-account.json（GA4は閲覧者、GSCはオーナー権限）
    sites/*.json の ga4_property_id … 未設定のサイトはGA4分をスキップする
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_client  # noqa: E402
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SA = ROOT / "indexing-service-account.json"
AI_DOMAINS = {"chatgpt": ["chatgpt.com", "chat.openai.com"], "perplexity": ["perplexity.ai"],
              "gemini": ["gemini.google.com"], "copilot": ["copilot.microsoft.com"],
              "claude": ["claude.ai"]}


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
        Metric(name="sessions"), Metric(name="screenPageViews"), Metric(name="conversions")]))
    row = rep.rows[0].metric_values if rep.rows else None
    out = {"sessions": int(row[0].value) if row else 0,
           "pv": int(row[1].value) if row else 0,
           "cv": int(float(row[2].value)) if row else 0, "ai": 0, "breakdown": {}}
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


def main():
    if not SA.exists():
        raise SystemExit("indexing-service-account.json がありません")
    ga_day = (date.today() - timedelta(days=1)).isoformat()
    sc_day = (date.today() - timedelta(days=3)).isoformat()

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
            print(f"  {sid}: GSC取得スキップ（{e}）")
        rows.append(row)
        print(f"{sid:10s} セッション{row.get('sessions', 0):5d}  表示{row.get('impressions', 0):6d}  "
              f"クリック{row.get('clicks', 0):4d}  AI参照{row.get('ai', 0):3d}")

    if "--send" not in sys.argv:
        print("\n※ 確認モードです。管制塔へ送るには --send を付けてください。")
        return
    if not hub_client.enabled():
        raise SystemExit("HUB_URL が未設定です")
    r = hub_client._post({"action": "kpi_log", "rows": rows})
    print(f"\n管制塔へ送信: {r.get('rows', 0)}件 / ダッシュボード更新済み")


if __name__ == "__main__":
    main()
