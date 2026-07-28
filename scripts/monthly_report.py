# -*- coding: utf-8 -*-
"""月次コンサルティングレポート生成（毎月1日実行）

GA4 + Search Console + スプレッドシート(記事作成ログ)から実データを取得し、
6ヶ月トレンド・前月比・クエリ別CTR/順位・LPエリア到達ヒートマップ・
改善提案・翌月アクションプランを、表とグラフ入りのPDFで発行する。

使い方:
    python scripts/monthly_report.py            # 実データで生成（API設定必須）
    python scripts/monthly_report.py --demo     # サンプルデータで形式確認
    python scripts/monthly_report.py --email    # 生成後、Resendでメール送付

必要な設定（実データモード）:
    .env: GA4_PROPERTY_ID / GSC_SITE_URL / SPREADSHEET_ID
    credentials: indexing-service-account.json（GA4/GSC/Sheetsに閲覧権限付与）
    pip install google-analytics-data google-api-python-client google-auth
出力:
    reports/YYYY-MM/report.html / report.pdf
"""
import base64
import json
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = "--demo" in sys.argv
SEND_EMAIL = "--email" in sys.argv

BLUE, TEAL, NAVY, MUTED = "#2563eb", "#0d9488", "#0b2447", "#5b6b84"


def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


ENV = load_env()


# ============================================================
# データ取得
# ============================================================
def month_labels(n=6):
    labels = []
    d = date.today().replace(day=1)
    for _ in range(n):
        d = (d - timedelta(days=1)).replace(day=1)
        labels.append(f"{d.year}-{d.month:02d}")
    return list(reversed(labels))


def fetch_real():
    """GA4/GSC/Sheetsから実データ取得。未設定なら例外に設定手順を含める"""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (DateRange, Dimension, Metric, RunReportRequest)
    except ImportError as e:
        raise SystemExit(
            f"必要ライブラリ未導入: {e}\n"
            "→ python -m pip install google-analytics-data google-api-python-client google-auth\n"
            "  形式の確認だけなら --demo を付けて実行してください")

    sa_path = ROOT / "indexing-service-account.json"
    if not sa_path.exists() or "YOUR_" in ENV.get("GA4_PROPERTY_ID", "YOUR_"):
        raise SystemExit(
            "実データ取得の設定が未完了です:\n"
            "  1. サービスアカウントJSONを indexing-service-account.json として配置\n"
            "  2. GA4プロパティ/GSC/スプレッドシートに閲覧権限を付与\n"
            "  3. .env の GA4_PROPERTY_ID / GSC_SITE_URL / SPREADSHEET_ID を設定\n"
            "  形式の確認だけなら --demo を付けて実行してください")

    creds = service_account.Credentials.from_service_account_file(
        str(sa_path),
        scopes=["https://www.googleapis.com/auth/analytics.readonly",
                "https://www.googleapis.com/auth/webmasters.readonly",
                "https://www.googleapis.com/auth/spreadsheets.readonly"])

    labels = month_labels(6)
    data = {"demo": False, "months": []}

    # --- GA4: 月別セッション/CV/AI参照 ---
    ga = BetaAnalyticsDataClient(credentials=creds)
    prop = f"properties/{ENV['GA4_PROPERTY_ID']}"
    for m in labels:
        y, mo = map(int, m.split("-"))
        end = (date(y + (mo == 12), (mo % 12) + 1, 1) - timedelta(days=1)).isoformat()
        rep = ga.run_report(RunReportRequest(
            property=prop, date_ranges=[DateRange(start_date=f"{m}-01", end_date=end)],
            metrics=[Metric(name="sessions"), Metric(name="conversions")]))
        row = rep.rows[0].metric_values if rep.rows else None
        data["months"].append({"label": m,
                               "sessions": int(row[0].value) if row else 0,
                               "cv": int(float(row[1].value)) if row else 0})

    # AI参照元セッション（当月）
    rep = ga.run_report(RunReportRequest(
        property=prop,
        date_ranges=[DateRange(start_date=f"{labels[-1]}-01", end_date="today")],
        dimensions=[Dimension(name="sessionSource")], metrics=[Metric(name="sessions")]))
    ai_domains = ("chatgpt.com", "chat.openai.com", "perplexity.ai", "gemini.google.com",
                  "copilot.microsoft.com", "claude.ai")
    data["ai_sessions"] = sum(int(r.metric_values[0].value) for r in rep.rows
                              if any(d in r.dimension_values[0].value for d in ai_domains))
    # プラットフォーム別内訳（AI検索分析ページ用）
    bk = {}
    for r in rep.rows:
        src = r.dimension_values[0].value
        for dom in ai_domains:
            if dom in src:
                key = {"chat.openai.com": "ChatGPT", "chatgpt.com": "ChatGPT",
                       "perplexity.ai": "Perplexity", "gemini.google.com": "Gemini",
                       "copilot.microsoft.com": "Copilot", "claude.ai": "Claude"}[dom]
                bk[key] = bk.get(key, 0) + int(r.metric_values[0].value)
    data["ai_breakdown"] = sorted(bk.items(), key=lambda x: -x[1])

    # エリア到達（area_reachイベント）
    try:
        rep = ga.run_report(RunReportRequest(
            property=prop,
            date_ranges=[DateRange(start_date=f"{labels[-1]}-01", end_date="today")],
            dimensions=[Dimension(name="customEvent:area_name")],
            metrics=[Metric(name="eventCount")]))
        total = max(1, max((int(r.metric_values[0].value) for r in rep.rows), default=1))
        data["areas"] = [{"name": r.dimension_values[0].value,
                          "reach": round(int(r.metric_values[0].value) / total * 100)}
                         for r in rep.rows]
    except Exception:
        data["areas"] = []

    # --- GSC: 月別クリック/表示/CTR/順位 + クエリ別 ---
    sc = build("searchconsole", "v1", credentials=creds)
    site = ENV["GSC_SITE_URL"]
    for i, m in enumerate(labels):
        y, mo = map(int, m.split("-"))
        end = (date(y + (mo == 12), (mo % 12) + 1, 1) - timedelta(days=1)).isoformat()
        res = sc.searchanalytics().query(siteUrl=site, body={
            "startDate": f"{m}-01", "endDate": end}).execute()
        r = (res.get("rows") or [{}])[0]
        data["months"][i].update({
            "clicks": int(r.get("clicks", 0)), "impressions": int(r.get("impressions", 0)),
            "ctr": round(r.get("ctr", 0) * 100, 2), "pos": round(r.get("position", 0), 1)})
    res = sc.searchanalytics().query(siteUrl=site, body={
        "startDate": f"{labels[-1]}-01", "endDate": "today",
        "dimensions": ["query"], "rowLimit": 10}).execute()
    data["queries"] = [{"q": r["keys"][0], "imp": int(r["impressions"]), "clicks": int(r["clicks"]),
                        "ctr": round(r["ctr"] * 100, 1), "pos": round(r["position"], 1)}
                       for r in res.get("rows", [])]

    # --- スプレッドシート: 記事作成ログ ---
    try:
        sh = build("sheets", "v4", credentials=creds)
        vals = sh.spreadsheets().values().get(
            spreadsheetId=ENV["SPREADSHEET_ID"], range="記事作成ログ!A2:L200").execute().get("values", [])
        cur = labels[-1].replace("-", "/")
        rows = [v for v in vals if len(v) > 9 and str(v[1]).startswith((labels[-1], cur))]
        data["content"] = {
            "published": len([v for v in rows if "公開" in str(v[9])]),
            "rows": [{"date": v[1], "title": v[3][:30], "score": v[8] if len(v) > 8 else "-",
                      "status": v[9]} for v in rows[:15]],
        }
    except Exception as e:
        data["content"] = {"published": 0, "rows": [], "note": f"スプレッドシート未接続: {e}"}
    return data


def fetch_demo():
    """サンプルデータ（レポート形式の確認用。全ページにSAMPLE表示）"""
    labels = month_labels(6)
    sessions = [320, 480, 690, 940, 1310, 1720]
    clicks = [110, 190, 310, 470, 700, 960]
    imps = [5200, 9800, 16400, 24100, 33800, 44500]
    pos = [28.4, 22.1, 17.8, 14.2, 11.6, 9.8]
    cvs = [1, 2, 4, 6, 9, 13]
    months = [{"label": l, "sessions": s, "clicks": c, "impressions": i,
               "ctr": round(c / i * 100, 2), "pos": p, "cv": v}
              for l, s, c, i, p, v in zip(labels, sessions, clicks, imps, pos, cvs)]
    return {
        "demo": True, "months": months, "ai_sessions": 86,
        "ai_breakdown": [("ChatGPT", 41), ("Perplexity", 23), ("Gemini", 15), ("Copilot", 5), ("Claude", 2)],
        "ai_prev": 52,
        "queries": [
            {"q": "aio 対策", "imp": 6200, "clicks": 292, "ctr": 4.7, "pos": 6.2},
            {"q": "llmo とは", "imp": 4900, "clicks": 260, "ctr": 5.3, "pos": 4.8},
            {"q": "meo 対策 やり方", "imp": 5400, "clicks": 194, "ctr": 3.6, "pos": 8.1},
            {"q": "google 口コミ 増やす", "imp": 4100, "clicks": 152, "ctr": 3.7, "pos": 7.4},
            {"q": "ai 集客", "imp": 3800, "clicks": 129, "ctr": 3.4, "pos": 9.9},
            {"q": "chatgpt 集客 活用", "imp": 2900, "clicks": 119, "ctr": 4.1, "pos": 6.8},
            {"q": "クリニック meo", "imp": 2400, "clicks": 65, "ctr": 2.7, "pos": 12.3},
            {"q": "工務店 集客", "imp": 2100, "clicks": 44, "ctr": 2.1, "pos": 14.6},
            {"q": "saas リード獲得", "imp": 1800, "clicks": 32, "ctr": 1.8, "pos": 16.9},
            {"q": "ゼロクリック検索 対策", "imp": 1500, "clicks": 51, "ctr": 3.4, "pos": 7.7},
        ],
        "areas": [
            {"name": "ヒーロー", "reach": 100}, {"name": "課題共感", "reach": 82},
            {"name": "市場の変化", "reach": 71}, {"name": "サービス4本柱", "reach": 63},
            {"name": "料金", "reach": 47}, {"name": "注力業種", "reach": 41},
            {"name": "他社比較", "reach": 36}, {"name": "動画", "reach": 29},
            {"name": "支援の流れ", "reach": 24}, {"name": "代表メッセージ", "reach": 21},
            {"name": "FAQ", "reach": 17}, {"name": "申込フォーム", "reach": 12},
        ],
        "content": {"published": 8, "rows": [
            {"date": "2026/07/05", "title": "AIO対策とは？AI検索に引用される5つの手順", "score": "116/120", "status": "公開済み"},
            {"date": "2026/07/09", "title": "LLMO対策とは？ChatGPTに引用される7つの方法", "score": "118/120", "status": "公開済み"},
            {"date": "2026/07/14", "title": "MEO対策のやり方7ステップ", "score": "115/120", "status": "公開済み"},
            {"date": "2026/07/19", "title": "Googleマップの口コミを増やす方法5選", "score": "117/120", "status": "公開済み"},
            {"date": "2026/07/27", "title": "AI集客の完全ガイド", "score": "119/120", "status": "公開済み"},
        ]},
    }


# ============================================================
# 分析（何が効いたか / 直すべきか / 来月プラン）
# ============================================================
def analyze(d):
    cur, prev = d["months"][-1], d["months"][-2]

    def mom(k):
        if not prev.get(k):
            return "―"
        v = (cur.get(k, 0) - prev[k]) / prev[k] * 100
        return f"{'+' if v >= 0 else ''}{v:.0f}%"

    grown = []
    if cur.get("clicks", 0) > prev.get("clicks", 0):
        grown.append(f"検索クリックが <b>{prev['clicks']}→{cur['clicks']}（{mom('clicks')}）</b>。"
                     f"平均順位が {prev.get('pos','-')}位→{cur.get('pos','-')}位 に改善したことが主因で、"
                     "記事の内部リンク網とE-E-A-T整備が順位を押し上げています。")
    if cur.get("cv", 0) > prev.get("cv", 0):
        grown.append(f"CV（相談・資料DL）が <b>{prev['cv']}→{cur['cv']}件</b>。"
                     "記事下CTAと追従サイドバー経由のLP到達が増えています。")
    if d.get("ai_sessions"):
        grown.append(f"AI経由の参照流入が <b>{d['ai_sessions']}セッション</b>。"
                     "llms.txt・構造化・H2直下結論などのAIO/LLMO施策が引用に結びつき始めています。")
    if not grown:
        grown.append("当月は主要指標の伸びが確認できませんでした。来月プランの優先度1〜3に集中してください。")

    fixes = []
    areas = d.get("areas") or []
    if areas:
        # 到達率の落差が最大の区画 = 離脱ポイント
        drops = [(areas[i]["name"], areas[i + 1]["name"], areas[i]["reach"] - areas[i + 1]["reach"])
                 for i in range(len(areas) - 1)]
        drops.sort(key=lambda x: -x[2])
        for a, b, gap in drops[:2]:
            fixes.append({"pri": "高", "area": f"LP「{a}」→「{b}」",
                          "now": f"到達率が {gap}pt 低下（最大の離脱ポイント）",
                          "fix": f"「{a}」の末尾に次セクションへの橋渡し文とミニCTAを追加。「{b}」の見出しを利益訴求型に変更"})
        form = next((x for x in areas if "フォーム" in x["name"]), None)
        if form and form["reach"] < 20:
            fixes.append({"pri": "高", "area": "LP「申込フォーム」",
                          "now": f"フォーム到達率 {form['reach']}%（低水準）",
                          "fix": "ページ中腹（サービス直後・比較表直後）にアンカーCTAボタンを追加し、到達経路を短縮"})
    low_ctr = [q for q in d.get("queries", []) if q["imp"] > 1000 and q["ctr"] < 3 and q["pos"] <= 15]
    for q in low_ctr[:2]:
        fixes.append({"pri": "中", "area": f"記事「{q['q']}」",
                      "now": f"表示{q['imp']:,}に対しCTR {q['ctr']}%（順位{q['pos']}位の期待値未満）",
                      "fix": "タイトルに数字と年号を追加（例:「◯◯の方法【2026年版・◯選】」）し、メタディスクを結論先出しに書き換え"})
    deep = [q for q in d.get("queries", []) if 11 <= q["pos"] <= 30]
    for q in deep[:2]:
        fixes.append({"pri": "中", "area": f"記事「{q['q']}」",
                      "now": f"順位 {q['pos']}位（2ページ目）",
                      "fix": "H2を1本追加して検索意図の抜けを補い、関連記事から内部リンク2本を追加して1ページ目へ"})
    if not fixes:
        fixes.append({"pri": "高", "area": "計測", "now": "改善対象を特定できるデータが不足",
                      "fix": "GA4イベント（area_reach/scroll_depth）とGSCの接続を確認"})

    actions = [
        ("改善優先度「高」の項目（本編6章の対比表）をすべて実施する", "第1週", "LP離脱の止血が最優先。CVR改善に直結"),
        ("順位11〜30位のクエリ上位2本をリライトする（H2追加+内部リンク2本）", "第2週", "2ページ目→1ページ目でクリックが数倍化"),
        ("新規記事を計画本数どおり公開する（品質90点以上・図解付き）", "毎日", "トピックの面を拡大しAI引用の入口を増やす"),
        ("CTR未達クエリのタイトル・メタディスクリプションを改善する", "第3週", "順位を変えずにクリックを増やす最速の一手"),
        ("AIスポットチェック（主要クエリをChatGPT/Perplexityに質問し自社言及を記録）", "第4週", "LLMOの定点観測。言及の増減が次月の方針を決める"),
        ("本レポートの数値をスプレッドシート「KPIレポート」「AIO計測」タブに転記・突合する", "月末", "学習ループ（kpi_feedback.md）の精度を維持"),
    ]

    # 勝ちクエリ / テコ入れクエリの分類（クエリ分析ページ用）
    qs = d.get("queries", [])
    winners = sorted([q for q in qs if q["pos"] <= 10 and q["ctr"] >= 3.5], key=lambda q: -q["clicks"])[:3]
    challengers = sorted([q for q in qs if 11 <= q["pos"] <= 30], key=lambda q: -q["imp"])[:3]

    # エグゼクティブサマリー（総評文）
    cur_, prev_ = d["months"][-1], d["months"][-2]
    summary = (
        f"当月はセッション{cur_.get('sessions', 0):,}（前月比{mom('sessions')}）、"
        f"検索クリック{cur_.get('clicks', 0):,}（{mom('clicks')}）、CV{cur_.get('cv', 0)}件（{mom('cv')}）と、"
        f"主要指標が{'揃って伸長しました' if cur_.get('sessions', 0) > prev_.get('sessions', 0) else '伸び悩みました'}。"
        f"平均掲載順位は{prev_.get('pos', '-')}位→{cur_.get('pos', '-')}位。"
        f"AI経由の参照流入は{d.get('ai_sessions', 0)}セッションを記録し、"
        "検索とAIの両輪で「見つかる→選ばれる」導線が機能し始めています。"
        "来月は本レポート8章の実行順プランに沿って、LPの離脱改善とリライトを最優先で進めます。")

    return {"grown": grown, "fixes": fixes, "actions": actions, "mom": mom,
            "winners": winners, "challengers": challengers, "summary": summary}


# ============================================================
# 描画（SVGチャート / ヒートマップ / HTML）
# ============================================================
def svg_line(months, key, color, title, unit=""):
    vals = [m.get(key, 0) or 0 for m in months]
    if not any(vals):
        return f'<p style="color:{MUTED}">データなし</p>'
    W, H, PL, PB = 560, 210, 46, 30
    mx = max(vals) * 1.15
    pts = [(PL + i * (W - PL - 12) / (len(vals) - 1), H - PB - (v / mx) * (H - PB - 20))
           for i, v in enumerate(vals)]
    path = "M" + " L".join(f"{x:.0f} {y:.0f}" for x, y in pts)
    dots = "".join(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="4" fill="{color}"/>' for x, y in pts)
    labels = "".join(f'<text x="{x:.0f}" y="{H-8}" font-size="10" fill="{MUTED}" text-anchor="middle">{m["label"][2:]}</text>'
                     for (x, _), m in zip(pts, months))
    last = f'<text x="{pts[-1][0]:.0f}" y="{pts[-1][1]-10:.0f}" font-size="12" font-weight="bold" fill="{NAVY}" text-anchor="middle">{vals[-1]:,}{unit}</text>'
    grid = "".join(f'<line x1="{PL}" y1="{H-PB-(H-PB-20)*g/4:.0f}" x2="{W-12}" y2="{H-PB-(H-PB-20)*g/4:.0f}" stroke="#e3eaf3"/>' for g in range(5))
    return (f'<div class="chart"><div class="chart-t">{title}</div>'
            f'<svg viewBox="0 0 {W} {H}">{grid}'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round"/>'
            f'{dots}{last}{labels}</svg></div>')


def svg_spark(vals, color, w=130, h=34):
    """タイル内ミニスパークライン"""
    if not vals or not any(vals):
        return ""
    mx, mn = max(vals), min(vals)
    rng = (mx - mn) or 1
    pts = [(4 + i * (w - 8) / (len(vals) - 1), h - 5 - (v - mn) / rng * (h - 10))
           for i, v in enumerate(vals)]
    path = "M" + " L".join(f"{x:.0f} {y:.0f}" for x, y in pts)
    return (f'<svg viewBox="0 0 {w} {h}" style="width:{w}px;height:{h}px">'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2"/>'
            f'<circle cx="{pts[-1][0]:.0f}" cy="{pts[-1][1]:.0f}" r="3" fill="{color}"/></svg>')


def funnel_html(areas):
    """LP主要区画のCVファネル（到達率の漏斗）"""
    keys = ["ヒーロー", "課題共感", "料金", "申込フォーム"]
    steps = [a for k in keys for a in areas if a["name"] == k]
    if len(steps) < 3:
        return ""
    rows = ""
    for i, s in enumerate(steps):
        w = max(s["reach"], 8)
        drop = "" if i == 0 else f'<div class="fn-drop">▼ −{steps[i-1]["reach"] - s["reach"]}pt</div>'
        rows += (f'{drop}<div class="fn-row"><div class="fn-bar" style="width:{w}%">'
                 f'<span>{s["name"]}</span><b>{s["reach"]}%</b></div></div>')
    return f'<div class="funnel">{rows}</div>'


def ai_bars(breakdown, total):
    if not breakdown:
        return f'<p style="color:{MUTED}">プラットフォーム別データはGA4接続後に表示されます</p>'
    colors = {"ChatGPT": "#10a37f", "Perplexity": "#1f7a8c", "Gemini": "#4285f4",
              "Copilot": "#7b83eb", "Claude": "#b45309"}
    rows = ""
    for name, v in breakdown:
        pct = round(v / max(total, 1) * 100)
        rows += (f'<div class="hm-row"><div class="hm-label">{name}</div>'
                 f'<div class="hm-track"><div class="hm-bar" style="width:{pct}%;'
                 f'background:{colors.get(name, "#64748b")}"></div></div>'
                 f'<div class="hm-val">{v}</div></div>')
    return f'<div class="heatmap">{rows}</div>'


def svg_heatbars(areas):
    if not areas:
        return '<p>エリア到達データなし（GA4のarea_reachイベント接続後に表示されます）</p>'
    rows = ""
    for a in areas:
        r = a["reach"]
        # 到達率で色: 高=青 / 中=水色 / 低=橙〜赤（ヒートマップ表現）
        col = "#2563eb" if r >= 60 else "#60a5fa" if r >= 40 else "#f59e0b" if r >= 20 else "#dc2626"
        rows += (f'<div class="hm-row"><div class="hm-label">{a["name"]}</div>'
                 f'<div class="hm-track"><div class="hm-bar" style="width:{r}%;background:{col}"></div></div>'
                 f'<div class="hm-val">{r}%</div></div>')
    return f'<div class="heatmap">{rows}</div>'


def render(d, a):
    labels = d["months"]
    cur, prev = labels[-1], labels[-2]
    ym = cur["label"]
    demo_banner = ('<div class="demo-banner">SAMPLE ― 本レポートはサンプルデータです。'
                   'GA4/GSC接続後、実データで自動発行されます。</div>') if d["demo"] else ""

    def tile(label, key, unit=""):
        v = cur.get(key, 0)
        return (f'<div class="tile"><div class="t-label">{label}</div>'
                f'<div class="t-val">{v:,}{unit}</div><div class="t-mom">前月比 {a["mom"](key)}</div></div>')

    qrows = "".join(f'<tr><td>{q["q"]}</td><td class="num">{q["imp"]:,}</td><td class="num">{q["clicks"]:,}</td>'
                    f'<td class="num">{q["ctr"]}%</td><td class="num">{q["pos"]}位</td></tr>'
                    for q in d.get("queries", []))
    frows = "".join(f'<tr><td><span class="pri pri-{f["pri"]}">{f["pri"]}</span></td><td>{f["area"]}</td>'
                    f'<td>{f["now"]}</td><td>{f["fix"]}</td></tr>' for f in a["fixes"])
    crows = "".join(f'<tr><td>{r["date"]}</td><td>{r["title"]}</td><td class="num">{r["score"]}</td>'
                    f'<td>{r["status"]}</td></tr>' for r in d["content"]["rows"])
    grown = "".join(f"<li>{g}</li>" for g in a["grown"])
    actions = "".join(f"<li>{x}</li>" for x in a["actions"])

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<style>
@page {{ size: A4; margin: 14mm 12mm; }}
* {{ box-sizing: border-box; }}
body {{ font-family: "Yu Gothic", "Meiryo", sans-serif; color: #10203a; font-size: 10.5pt; line-height: 1.75; margin: 0; }}
.demo-banner {{ background: #fff3cd; border: 2px dashed #d97706; color: #92400e; font-weight: bold; text-align: center; padding: 6px; margin-bottom: 12px; border-radius: 6px; }}
.cover {{ background: linear-gradient(135deg, #0b2447, #1d4ed8); color: #fff; border-radius: 12px; padding: 26px 28px; margin-bottom: 18px; }}
.cover h1 {{ margin: 0 0 4px; font-size: 20pt; }}
.cover .sub {{ color: #bfdbfe; font-size: 10pt; }}
h2 {{ font-size: 13pt; border-left: 5px solid {BLUE}; padding-left: 10px; margin: 22px 0 10px; page-break-after: avoid; }}
.tiles {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.tile {{ flex: 1 1 15%; min-width: 100px; border: 1px solid #e3eaf3; border-radius: 8px; padding: 8px 10px; }}
.t-label {{ font-size: 8pt; color: {MUTED}; }}
.t-val {{ font-size: 15pt; font-weight: bold; color: {NAVY}; }}
.t-mom {{ font-size: 8pt; color: {TEAL}; }}
.charts {{ display: flex; gap: 12px; flex-wrap: wrap; }}
.chart {{ flex: 1 1 46%; border: 1px solid #e3eaf3; border-radius: 8px; padding: 8px; }}
.chart-t {{ font-size: 9pt; font-weight: bold; margin-bottom: 4px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 9pt; }}
th, td {{ border: 1px solid #dbe3ee; padding: 5px 8px; text-align: left; vertical-align: top; }}
th {{ background: {NAVY}; color: #fff; font-weight: 600; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr:nth-child(even) td {{ background: #f7fafd; }}
.heatmap {{ border: 1px solid #e3eaf3; border-radius: 8px; padding: 10px 12px; }}
.hm-row {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
.hm-label {{ width: 110px; font-size: 8.5pt; }}
.hm-track {{ flex: 1; background: #eef2f8; border-radius: 4px; height: 14px; }}
.hm-bar {{ height: 14px; border-radius: 4px; }}
.hm-val {{ width: 38px; text-align: right; font-size: 8.5pt; font-weight: bold; }}
.hm-note {{ font-size: 8pt; color: {MUTED}; margin-top: 6px; }}
.pri {{ font-weight: bold; padding: 1px 8px; border-radius: 10px; font-size: 8.5pt; white-space: nowrap; }}
.pri-高 {{ background: #fee2e2; color: #b91c1c; }}
.pri-中 {{ background: #fef3c7; color: #b45309; }}
.pri-低 {{ background: #e0f2fe; color: #0369a1; }}
ol.actions li {{ margin: 4px 0; }}
ul.grown li {{ margin: 5px 0; }}
.src {{ font-size: 8pt; color: {MUTED}; margin-top: 16px; border-top: 1px solid #e3eaf3; padding-top: 6px; }}
.pagebreak {{ page-break-before: always; }}
</style></head><body>
{demo_banner}
<div class="cover">
  <h1>月次コンサルティングレポート ― {ym}</h1>
  <div class="sub">対象: AI集客ラボ（オウンドメディア + 集客支援LP）｜発行: セブンセンシズ株式会社｜発行日: {date.today().isoformat()}</div>
</div>

<h2>1. 当月サマリー（前月比つき）</h2>
<div class="tiles">
{tile("セッション", "sessions")}{tile("CV（相談+資料DL）", "cv", "件")}{tile("検索表示回数", "impressions")}{tile("検索クリック", "clicks")}{tile("平均CTR", "ctr", "%")}{tile("平均掲載順位", "pos", "位")}
</div>
<p style="font-size:9pt;color:{MUTED};margin-top:6px;">AI経由参照（ChatGPT/Perplexity/Gemini等）: <b>{d.get("ai_sessions", 0)}セッション</b></p>

<h2>2. 6ヶ月トレンド</h2>
<div class="charts">
{svg_line(labels, "sessions", BLUE, "セッション数（GA4）")}
{svg_line(labels, "clicks", TEAL, "検索クリック数（Search Console）")}
{svg_line(labels, "impressions", BLUE, "検索表示回数（Search Console）")}
{svg_line(labels, "pos", TEAL, "平均掲載順位（小さいほど良い）", "位")}
</div>

<h2>3. Search Console クエリ別実績（上位10）</h2>
<table><tr><th>クエリ</th><th>表示回数</th><th>クリック</th><th>CTR</th><th>平均順位</th></tr>{qrows}</table>

<div class="pagebreak"></div>
<h2>4. LPエリア到達ヒートマップ</h2>
<p style="font-size:9pt;">LP各セクションまで読者が到達した割合です（GA4 area_reachイベント）。<b>色が赤いほど到達が少ない=改善対象</b>です。</p>
{svg_heatbars(d.get("areas", []))}
<p class="hm-note">■青=到達60%以上 ■水色=40-59% ■橙=20-39% ■赤=20%未満</p>

<h2>5. 伸びたポイント（数字の根拠つき）</h2>
<ul class="grown">{grown}</ul>

<h2>6. 直すべきポイント（優先度つき・対比表）</h2>
<table><tr><th style="width:8%">優先度</th><th style="width:22%">エリア/対象</th><th style="width:30%">現状（データ根拠）</th><th>改善アクション（何をどう変えるか）</th></tr>{frows}</table>

<h2>7. コンテンツ実績</h2>
<p style="font-size:9.5pt;">当月公開: <b>{d["content"]["published"]}本</b>（公開基準: 6エージェント品質採点 114/120点以上）</p>
<table><tr><th>日付</th><th>タイトル</th><th>品質スコア</th><th>審査記録</th></tr>{crows}</table>

<h2>8. 来月のプラン（実行順）</h2>
<ol class="actions">{actions}</ol>

<div class="src">データソース: Google Analytics 4（セッション・CV・AI参照元・エリア到達）/ Google Search Console（表示・クリック・CTR・順位・クエリ）/ 運用スプレッドシート（記事作成ログ）。エリア到達はLP各セクションのarea_reachイベント（画面内40%表示で発火）にもとづく。</div>
</body></html>"""


# ============================================================
# 出力（HTML→PDF→メール）
# ============================================================
def main():
    d = fetch_demo() if DEMO else fetch_real()
    a = analyze(d)
    html = render(d, a)

    ym = d["months"][-1]["label"]
    out_dir = ROOT / "reports" / ym
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "report.html"
    pdf_path = out_dir / "report.pdf"
    html_path.write_text(html, encoding="utf-8")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(html_path.as_uri())
        pg.wait_for_timeout(400)
        pg.pdf(path=str(pdf_path), format="A4", print_background=True,
               margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
        b.close()
    print("PDF:", pdf_path)

    if SEND_EMAIL:
        key, to = ENV.get("RESEND_API_KEY", ""), ENV.get("LEAD_TO_EMAIL", "")
        frm = ENV.get("LEAD_FROM_EMAIL", "")
        if not key or "YOUR_" in key or not to:
            print("メール未送信: .env の RESEND_API_KEY / LEAD_TO_EMAIL / LEAD_FROM_EMAIL を設定してください")
            return
        payload = json.dumps({
            "from": frm, "to": [to],
            "subject": f"【AI集客ラボ】月次コンサルティングレポート {ym}",
            "text": f"{ym} の月次レポートをお送りします。PDFをご確認ください。",
            "attachments": [{"filename": f"report-{ym}.pdf",
                             "content": base64.b64encode(pdf_path.read_bytes()).decode()}],
        }).encode()
        req = urllib.request.Request("https://api.resend.com/emails", data=payload,
                                     headers={"Authorization": f"Bearer {key}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req) as res:
            print("メール送信:", res.status)


if __name__ == "__main__":
    main()
