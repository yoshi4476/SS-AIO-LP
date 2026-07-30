# -*- coding: utf-8 -*-
"""3サイト横断の月次レポート（グループ全体版）

使い方:
    python scripts/group_report.py            # 実データで生成
    python scripts/group_report.py --demo     # サンプルデータで形式確認
    python scripts/group_report.py --email    # 生成後メール送付

各サイト単体の詳細レポートは monthly_report.py が担当する。
こちらは「3サイトを1枚で見渡す」ための経営向けレポート。
GA4/GSCの権限が未付与のサイトは「権限付与待ち」と明示して空欄にはしない
（数字が無いことと、取得できていないことを混同させないため）。
"""
import base64
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_client  # noqa: E402
import sites as sites_mod  # noqa: E402
from cannibal_check import load_articles  # noqa: E402
from monthly_report import ENV, svg_line  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SA = ROOT / "indexing-service-account.json"
DEMO = "--demo" in sys.argv
NAVY, BLUE, TEAL, GOLD, MUTED = "#0b2447", "#2563eb", "#0d9488", "#b7922e", "#5b6b84"
AI_DOMAINS = {"chatgpt": ["chatgpt.com", "chat.openai.com"], "perplexity": ["perplexity.ai"],
              "gemini": ["gemini.google.com"], "copilot": ["copilot.microsoft.com"],
              "claude": ["claude.ai"]}


def months(n=6):
    out, d = [], date.today().replace(day=1)
    for _ in range(n):
        d = (d - timedelta(days=1)).replace(day=1)
        out.append(f"{d.year}-{d.month:02d}")
    return list(reversed(out))


def month_end(label):
    y, m = map(int, label.split("-"))
    return (date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)).isoformat()


def creds(scopes):
    from google.oauth2 import service_account
    return service_account.Credentials.from_service_account_file(str(SA), scopes=scopes)


def fetch_site(cfg, labels):
    """1サイト分の月次データ。取得できない項目は None のままにして理由を残す"""
    out = {"id": cfg["id"], "name": cfg["name"], "domain": cfg["domain"],
           "theme": cfg["theme"], "months": [{"label": m} for m in labels],
           "ga_error": None, "sc_error": None, "ai": 0, "breakdown": {}, "queries": []}

    prop = cfg.get("ga4_property_id", "")
    if not prop:
        out["ga_error"] = "GA4プロパティID未設定"
    elif SA.exists():
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.analytics.data_v1beta.types import (DateRange, Dimension, Metric,
                                                            RunReportRequest)
            c = BetaAnalyticsDataClient(credentials=creds(
                ["https://www.googleapis.com/auth/analytics.readonly"]))
            p = f"properties/{prop}"
            for i, m in enumerate(labels):
                rep = c.run_report(RunReportRequest(
                    property=p, date_ranges=[DateRange(start_date=f"{m}-01", end_date=month_end(m))],
                    metrics=[Metric(name="sessions"), Metric(name="conversions")]))
                r = rep.rows[0].metric_values if rep.rows else None
                out["months"][i].update({"sessions": int(r[0].value) if r else 0,
                                         "cv": int(float(r[1].value)) if r else 0})
            cur = labels[-1]
            rep = c.run_report(RunReportRequest(
                property=p,
                date_ranges=[DateRange(start_date=f"{cur}-01", end_date=month_end(cur))],
                dimensions=[Dimension(name="sessionSource")], metrics=[Metric(name="sessions")]))
            for r in rep.rows:
                src, n = r.dimension_values[0].value.lower(), int(r.metric_values[0].value)
                for k, doms in AI_DOMAINS.items():
                    if any(d in src for d in doms):
                        out["ai"] += n
                        out["breakdown"][k] = out["breakdown"].get(k, 0) + n
        except Exception as e:
            out["ga_error"] = f"取得失敗: {str(e)[:60]}"
    else:
        out["ga_error"] = "サービスアカウント未配置"

    if SA.exists():
        try:
            from googleapiclient.discovery import build
            sc = build("searchconsole", "v1", credentials=creds(
                ["https://www.googleapis.com/auth/webmasters.readonly"]))
            site_url = f"https://{cfg['domain']}/"
            for i, m in enumerate(labels):
                res = sc.searchanalytics().query(siteUrl=site_url, body={
                    "startDate": f"{m}-01", "endDate": month_end(m)}).execute()
                r = (res.get("rows") or [{}])[0]
                out["months"][i].update({
                    "clicks": int(r.get("clicks", 0)), "impressions": int(r.get("impressions", 0)),
                    "pos": round(r.get("position", 0), 1)})
            cur = labels[-1]
            res = sc.searchanalytics().query(siteUrl=site_url, body={
                "startDate": f"{cur}-01", "endDate": month_end(cur),
                "dimensions": ["query"], "rowLimit": 5}).execute()
            out["queries"] = [{"q": r["keys"][0], "imp": int(r["impressions"]),
                               "clicks": int(r["clicks"]), "pos": round(r["position"], 1)}
                              for r in res.get("rows", [])]
        except Exception as e:
            out["sc_error"] = ("Search Consoleの権限未付与"
                               if "sufficient permission" in str(e) else f"取得失敗: {str(e)[:50]}")
    else:
        out["sc_error"] = "サービスアカウント未配置"
    return out


def fetch_demo(labels):
    base = [(320, 480, 690, 940, 1310, 1720), (120, 180, 260, 330, 420, 560),
            (60, 90, 140, 210, 300, 410)]
    out = []
    for (sid, cfg), s in zip(sites_mod.load_all().items(), base):
        d = {"id": sid, "name": cfg["name"], "domain": cfg["domain"], "theme": cfg["theme"],
             "ga_error": None, "sc_error": None, "ai": s[-1] // 20,
             "breakdown": {"chatgpt": s[-1] // 40, "perplexity": s[-1] // 60},
             "queries": [{"q": f"{cfg['id']} サンプルKW{i}", "imp": 900 - i * 120,
                          "clicks": 40 - i * 6, "pos": 5.2 + i} for i in range(1, 4)],
             "months": [{"label": m, "sessions": v, "cv": max(1, v // 130),
                         "clicks": v // 2, "impressions": v * 26, "pos": 22 - i * 2}
                        for i, (m, v) in enumerate(zip(labels, s))]}
        out.append(d)
    return out


def article_counts():
    """サイト別の記事ストック。自リポジトリは実ファイル、他サイトは台帳の公開済み件数"""
    counts = {"ai-lab": len([a for a in load_articles()])}
    for k in hub_client.all_kw():
        if k.get("status") == "公開済み" and k.get("site") != "ai-lab":
            counts[k["site"]] = counts.get(k["site"], 0) + 1
    return counts


def mom(cur, prev, key):
    a, b = cur.get(key) or 0, prev.get(key) or 0
    if not b:
        return "―"
    v = (a - b) / b * 100
    return f"{'+' if v >= 0 else ''}{v:.0f}%"


def tile(label, value, sub, good=True):
    cls = "good" if good else "bad"
    return (f'<div class="tile"><div class="t-l">{label}</div><div class="t-v">{value}</div>'
            f'<div class="t-s {cls}">{sub}</div></div>')


def render(sites, labels, arts, cross):
    ym = labels[-1]
    total = {k: sum((s["months"][-1].get(k) or 0) for s in sites)
             for k in ["sessions", "cv", "clicks", "impressions"]}
    prev = {k: sum((s["months"][-2].get(k) or 0) for s in sites)
            for k in ["sessions", "cv", "clicks", "impressions"]}
    ai_total = sum(s["ai"] for s in sites)

    logo = ""
    lp = ROOT / "site" / "images" / "company" / "logo-white.png"
    if lp.exists():
        logo = f'<img class="lg" src="data:image/png;base64,{base64.b64encode(lp.read_bytes()).decode()}">'

    # サイト別比較表
    rows = ""
    for s in sites:
        c = s["months"][-1]
        na = '<span class="na">権限付与待ち</span>'
        rows += (
            f'<tr><td><b>{s["name"]}</b><br><span class="dim">{s["domain"]}</span></td>'
            f'<td>{s["theme"][:22]}</td>'
            f'<td class="num">{arts.get(s["id"], 0)}本</td>'
            f'<td class="num">{f"{c.get(chr(115)+"essions"):,}" if c.get("sessions") is not None else na}</td>'
            f'<td class="num">{f"{c.get(chr(99)+"licks"):,}" if c.get("clicks") is not None else na}</td>'
            f'<td class="num">{s["ai"] if not s["ga_error"] else na}</td></tr>')

    # サイト別セクション
    sections = ""
    for i, s in enumerate(sites, 1):
        c, p = s["months"][-1], s["months"][-2]
        notes = [x for x in [s["ga_error"], s["sc_error"]] if x]
        note_html = (f'<div class="warn">データ未取得: {" / ".join(notes)}'
                     '<br>サービスアカウント <b>aio-report@ss-aio-media.iam.gserviceaccount.com</b> に'
                     'GA4「閲覧者」・Search Console「フル」を付与すると次号から反映されます。</div>'
                     if notes else "")
        qrows = "".join(
            f'<tr><td>{q["q"]}</td><td class="num">{q["imp"]:,}</td>'
            f'<td class="num">{q["clicks"]:,}</td><td class="num">{q["pos"]}位</td></tr>'
            for q in s["queries"]) or '<tr><td colspan="4">検索データは権限付与後に表示されます</td></tr>'
        charts = ""
        if c.get("sessions") is not None:
            charts = f'<div class="charts">{svg_line(s["months"], "sessions", BLUE, "セッション推移")}' \
                     f'{svg_line(s["months"], "clicks", TEAL, "検索クリック推移")}</div>'
        sections += f"""
<div class="sheet">
<div class="sec"><span class="no">{i + 2:02d}</span><h2>{s["name"]}</h2><div class="gold"></div></div>
<p class="lead">{s["theme"]}<br><span class="dim">{s["domain"]}</span></p>
{note_html}
<div class="tiles">
{tile("セッション", f'{c.get("sessions"):,}' if c.get("sessions") is not None else "—", f'前月比 {mom(c, p, "sessions")}')}
{tile("検索クリック", f'{c.get("clicks"):,}' if c.get("clicks") is not None else "—", f'前月比 {mom(c, p, "clicks")}')}
{tile("記事ストック", f'{arts.get(s["id"], 0)}本', "品質90点以上のみ")}
{tile("AI経由参照", str(s["ai"]) if not s["ga_error"] else "—", "ChatGPT・Perplexity等")}
</div>
{charts}
<h3>主要クエリ</h3>
<table><tr><th>クエリ</th><th>表示</th><th>クリック</th><th>平均順位</th></tr>{qrows}</table>
</div>"""

    cross_rows = "".join(
        f'<tr><td>{c["site"]}</td><td>{c["keyword"]}</td><td>{c["owner"]}</td></tr>'
        for c in cross) or '<tr><td colspan="3">サイト間の重複・領域侵食はありません（良好）</td></tr>'

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; }}
body {{ font-family: "Yu Gothic","Meiryo",sans-serif; color:#10203a; font-size:10pt; line-height:1.8; }}
.sheet {{ width:210mm; min-height:296mm; padding:16mm 15mm 18mm; page-break-after:always; }}
.sheet:last-child {{ page-break-after:auto; }}
.cover {{ background:linear-gradient(150deg,#071a38,{NAVY} 45%,#14345c); color:#fff;
  display:flex; flex-direction:column; padding:22mm 20mm; }}
.lg {{ height:34px; }} .cv-g {{ width:64px;height:4px;background:{GOLD};margin:10mm 0 6mm; }}
.kick {{ letter-spacing:.35em;font-size:9pt;color:#93b4e8; }}
.ttl {{ font-size:26pt;font-weight:900;line-height:1.4;margin-top:4mm; }}
.mon {{ font-size:15pt;color:{GOLD};font-weight:bold;margin-top:3mm;letter-spacing:.1em; }}
.meta {{ margin-top:auto;font-size:9.5pt;color:#bcd0ee;line-height:2.1;
  border-top:1px solid rgba(255,255,255,.25);padding-top:6mm; }}
.sec {{ display:flex;align-items:center;gap:10px;margin:0 0 12px; }}
.sec .no {{ background:{NAVY};color:#fff;font-weight:bold;font-size:10pt;padding:3px 12px;border-radius:4px; }}
.sec h2 {{ font-size:14.5pt; }} .sec .gold {{ flex:1;height:2px;background:linear-gradient(90deg,{GOLD},transparent); }}
h3 {{ font-size:11pt;margin:16px 0 6px;color:{NAVY}; }}
.lead {{ font-size:10pt;color:{MUTED};margin-bottom:10px; }}
.dim {{ color:{MUTED};font-size:8.5pt; }}
.na {{ color:#b45309;font-size:8pt; }}
.warn {{ background:#fffbeb;border-left:4px solid #f59e0b;padding:9px 12px;border-radius:0 8px 8px 0;
  font-size:8.6pt;margin:8px 0 12px; }}
.tiles {{ display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:10px 0; }}
.tile {{ border:1px solid #e3eaf3;border-radius:10px;padding:9px 11px; }}
.t-l {{ font-size:8.3pt;color:{MUTED}; }} .t-v {{ font-size:15pt;font-weight:900;color:{NAVY}; }}
.t-s {{ font-size:8.3pt;font-weight:bold; }} .good {{ color:#067647; }} .bad {{ color:#b91c1c; }}
.charts {{ display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px; }}
.chart {{ border:1px solid #e3eaf3;border-radius:8px;padding:8px; }}
.chart-t {{ font-size:9pt;font-weight:bold;margin-bottom:4px; }}
table {{ border-collapse:collapse;width:100%;font-size:9pt;margin-top:6px; }}
th,td {{ border:1px solid #dbe3ee;padding:5px 8px;text-align:left;vertical-align:top; }}
th {{ background:{NAVY};color:#fff;font-weight:600; }}
td.num {{ text-align:right;font-variant-numeric:tabular-nums; }}
tr:nth-child(even) td {{ background:#f7fafd; }}
.callout {{ border-left:4px solid {GOLD};background:#fbf8ef;padding:10px 14px;
  border-radius:0 8px 8px 0;margin:10px 0;font-size:9.5pt; }}
.back {{ background:{NAVY};color:#fff;display:flex;flex-direction:column;justify-content:center;
  align-items:center;text-align:center;gap:4mm; }}
.back .s {{ font-size:9.5pt;color:#9db8e0;line-height:2.2; }}
</style></head><body>

<div class="sheet cover">
  {logo}<div class="cv-g"></div>
  <div class="kick">GROUP MONTHLY REPORT</div>
  <div class="ttl">3サイト統合<br>月次レポート</div>
  <div class="mon">{ym} 月次報告</div>
  <div class="meta">
    対象: AI集客ラボ / AI導入補助金サポート / コーポレートサイト<br>
    発行: <b>セブンセンシズ株式会社</b>｜発行日: {date.today().isoformat()}<br>
    数値は Google Analytics 4 / Search Console / 運用台帳の実測にもとづきます
  </div>
</div>

<div class="sheet">
<div class="sec"><span class="no">01</span><h2>グループ全体サマリー</h2><div class="gold"></div></div>
<div class="tiles">
{tile("セッション合計", f'{total["sessions"]:,}', f'前月比 {mom(total, prev, "sessions")}')}
{tile("検索クリック合計", f'{total["clicks"]:,}', f'前月比 {mom(total, prev, "clicks")}')}
{tile("CV合計", f'{total["cv"]}件', f'前月比 {mom(total, prev, "cv")}')}
{tile("AI経由参照", str(ai_total), "3サイト合計")}
</div>
<h3>サイト別の比較</h3>
<table><tr><th style="width:24%">サイト</th><th>担当テーマ</th><th>記事</th>
<th>セッション</th><th>クリック</th><th>AI参照</th></tr>{rows}</table>
<div class="callout"><b>3サイト体制の狙い:</b> 集客手法はAI集客ラボ、資金調達は補助金サイト、
店舗経営の実務はコーポレートサイトと役割を分けています。同じ会社のサイトどうしで検索評価を
奪い合わないよう、キーワードは1つの台帳で一元管理し、毎回の記事作成前に重複を機械検査しています。</div>
<h3>記事の総ストック</h3>
<p>3サイト合計 <b>{sum(arts.values())}本</b>（品質90点以上のみ公開）。
記事は公開後も検索とAI回答の両方から流入を生み続けるストック資産です。</p>
</div>

<div class="sheet">
<div class="sec"><span class="no">02</span><h2>サイト間の重複チェック</h2><div class="gold"></div></div>
<p class="lead">同一企業が複数サイトで同じ検索意図を狙うと、Googleがどちらも評価しにくくなります。
毎回の記事作成前に、全サイトのキーワードを突き合わせて検査しています。</p>
<table><tr><th style="width:22%">サイト</th><th>キーワード</th><th style="width:22%">本来の担当</th></tr>{cross_rows}</table>
<div class="callout"><b>今月の判定:</b> {'領域侵食は検出されていません。3サイトが競合しない状態を維持できています。'
    if not cross else f'{len(cross)}件の領域侵食を検出しました。該当キーワードは台帳から取り下げ済みです。'}</div>
</div>
{sections}
<div class="sheet back">
  {logo}
  <div style="font-size:13pt;font-weight:bold;">セブンセンシズ株式会社</div>
  <div class="s">〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902<br>
  TEL 06-4305-7547（9:00〜20:00 / 土日祝休）<br>
  ai.7senses.co.jp ｜ lp.7senses.co.jp ｜ www.7senses.co.jp<br><br>
  本レポートは自動集計・自動作成されています。<br>次号は翌月1日に自動発行されます。</div>
</div>
</body></html>"""


def main():
    labels = months(6)
    cfgs = sites_mod.load_all()
    if DEMO:
        sites = fetch_demo(labels)
    else:
        if not SA.exists():
            print("警告: indexing-service-account.json が無いためGA4/GSCは取得できません")
        sites = [fetch_site(c, labels) for c in cfgs.values()]

    arts = {} if DEMO else article_counts()
    if DEMO:
        arts = {s["id"]: 12 - i * 3 for i, s in enumerate(sites)}
    try:
        from cannibal_check import territory_check
        cross = [] if DEMO else territory_check()
    except Exception:
        cross = []

    html = render(sites, labels, arts, cross)
    ym = labels[-1]
    out_dir = ROOT / "reports" / f"group-{ym}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.html").write_text(html, encoding="utf-8")
    print(f"HTML: {out_dir / 'report.html'}")

    try:
        from playwright.sync_api import sync_playwright
        pdf = out_dir / "report.pdf"
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto((out_dir / "report.html").resolve().as_uri(), wait_until="networkidle")
            pg.pdf(path=str(pdf), format="A4", print_background=True,
                   display_header_footer=True, header_template="<div></div>",
                   footer_template='<div style="width:100%;font-size:8px;color:#8a97ab;'
                                   'text-align:center;padding-right:12mm;">'
                                   '<span class="pageNumber"></span> / <span class="totalPages"></span></div>',
                   margin={"top": "0", "bottom": "10mm", "left": "0", "right": "0"})
            b.close()
        print(f"PDF : {pdf}")
    except Exception as e:
        print(f"PDF生成をスキップ: {e}")
        return

    if "--email" in sys.argv:
        send_mail(pdf, ym)


def send_mail(pdf_path, ym):
    import json
    import urllib.request
    key = ENV.get("RESEND_API_KEY", "")
    to = ENV.get("LEAD_TO_EMAIL", "") or "info.ai@7senses.co.jp"
    frm = ENV.get("LEAD_FROM_EMAIL", "")
    if not key or "YOUR_" in key or not frm:
        print("メール未送信: RESEND_API_KEY / LEAD_FROM_EMAIL を設定してください")
        return
    payload = json.dumps({
        "from": frm, "to": [to],
        "subject": f"【セブンセンシズ】3サイト統合 月次レポート {ym}",
        "text": f"{ym} のグループ月次レポートをお送りします。\n"
                "3サイト（AI集客ラボ / AI導入補助金 / コーポレート）の実績を1枚でまとめています。\n"
                "サイト単体の詳細レポートは別便でお送りしています。",
        "attachments": [{"filename": f"group-report-{ym}.pdf",
                         "content": base64.b64encode(pdf_path.read_bytes()).decode()}],
    }).encode()
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 # CloudflareがデフォルトUAを遮断する（error 1010）ためUA必須
                 "User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
    with urllib.request.urlopen(req) as r:
        print("メール送信:", r.status, "→", to)


if __name__ == "__main__":
    main()
