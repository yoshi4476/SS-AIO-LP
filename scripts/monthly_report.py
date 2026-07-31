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
        "startDate": f"{labels[-1]}-01", "endDate": date.today().isoformat(),
        "dimensions": ["query"], "rowLimit": 10}).execute()
    data["queries"] = [{"q": r["keys"][0], "imp": int(r["impressions"]), "clicks": int(r["clicks"]),
                        "ctr": round(r["ctr"] * 100, 1), "pos": round(r["position"], 1)}
                       for r in res.get("rows", [])]

    # ページ別実績（当月・上位12）
    try:
        res = sc.searchanalytics().query(siteUrl=site, body={
            "startDate": f"{labels[-1]}-01", "endDate": date.today().isoformat(),
            "dimensions": ["page"], "rowLimit": 12}).execute()
        data["pages"] = [{"path": r["keys"][0].replace(site.rstrip("/"), "") or "/",
                          "imp": int(r["impressions"]), "clicks": int(r["clicks"]),
                          "ctr": round(r["ctr"] * 100, 1), "pos": round(r["position"], 1)}
                         for r in res.get("rows", [])]
    except Exception:
        data["pages"] = []

    # 日別クリック推移（当月）
    try:
        res = sc.searchanalytics().query(siteUrl=site, body={
            "startDate": f"{labels[-1]}-01", "endDate": date.today().isoformat(),
            "dimensions": ["date"], "rowLimit": 31}).execute()
        rows = sorted(res.get("rows", []), key=lambda r: r["keys"][0])
        data["daily"] = {"labels": [r["keys"][0][8:] for r in rows],
                         "clicks": [int(r["clicks"]) for r in rows],
                         "imps": [int(r["impressions"]) for r in rows]}
    except Exception:
        data["daily"] = {"labels": [], "clicks": [], "imps": []}

    # チャネル別・デバイス別セッション（GA4・当月）
    def ga_dist(dim):
        try:
            rep = ga.run_report(RunReportRequest(
                property=prop,
                date_ranges=[DateRange(start_date=f"{labels[-1]}-01", end_date="today")],
                dimensions=[Dimension(name=dim)], metrics=[Metric(name="sessions")]))
            pairs = [(r.dimension_values[0].value, int(r.metric_values[0].value)) for r in rep.rows]
            return sorted(pairs, key=lambda x: -x[1])
        except Exception:
            return []
    data["channels"] = ga_dist("sessionDefaultChannelGroup")
    data["devices"] = ga_dist("deviceCategory")

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
        "pages": [
            {"path": "/aio/aio-taisaku-guide/", "imp": 8900, "clicks": 410, "ctr": 4.6, "pos": 5.8},
            {"path": "/aio/llmo-taisaku-hoho/", "imp": 7200, "clicks": 360, "ctr": 5.0, "pos": 4.9},
            {"path": "/meo/meo-taisaku-yarikata/", "imp": 6800, "clicks": 250, "ctr": 3.7, "pos": 7.8},
            {"path": "/meo/kuchikomi-fuyasu-hoho/", "imp": 5100, "clicks": 190, "ctr": 3.7, "pos": 7.2},
            {"path": "/", "imp": 4300, "clicks": 170, "ctr": 4.0, "pos": 8.5},
            {"path": "/ai-marketing/ai-shukyaku-guide/", "imp": 3900, "clicks": 140, "ctr": 3.6, "pos": 9.1},
            {"path": "/lp/", "imp": 2100, "clicks": 90, "ctr": 4.3, "pos": 10.4},
        ],
        "daily": {"labels": [f"{i:02d}" for i in range(1, 31)],
                  "clicks": [18, 22, 25, 21, 28, 33, 30, 27, 35, 38, 34, 41, 39, 44, 40,
                             46, 43, 49, 52, 47, 55, 51, 58, 54, 60, 57, 63, 59, 66, 62],
                  "imps": []},
        "channels": [("Organic Search", 980), ("Direct", 340), ("Referral", 210),
                     ("Organic Social", 120), ("Email", 70)],
        "devices": [("mobile", 1030), ("desktop", 620), ("tablet", 70)],
    }


# ============================================================
# サイト全体監査（記事別・ページ別の具体的な修正指示を自動生成）
# ============================================================
def audit_site(d):
    import re as _re
    today = date.today()
    arts = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = _re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, _re.S)
        if not m:
            continue
        fm, body = m.groups()

        def fv(key):
            mm = _re.search(rf"^{key}:\s*(.+?)\s*$", fm, _re.M)
            return mm.group(1).strip('"') if mm else ""

        arts.append({
            "slug": p.stem, "title": fv("title"), "cat": fv("category"),
            "date": fv("dateModified") or fv("date"),
            "links": len(_re.findall(r"\]\(/(?:aio|seo|meo|ai-marketing)/[a-z0-9-]+/\)", body)),
            "faq": len(_re.findall(r"<details><summary>", body)),
            "len": len(_re.sub(r"\s", "", body)),
        })

    by_cat = {}
    for x in arts:
        by_cat.setdefault(x["cat"], []).append(x)
    pages = {p["path"]: p for p in d.get("pages", [])}

    art_rows, keep = [], []
    for x in arts:
        path = f'/{x["cat"]}/{x["slug"]}/'
        g = pages.get(path)
        issues = []
        # 検索データにもとづく指示
        if g and g["pos"] > 10 and g["imp"] >= 50:
            issues.append(("本文構成",
                           f'順位{g["pos"]}位・表示{g["imp"]:,}（2ページ目に滞留）',
                           "検索上位3記事にあって自記事にないH2を1本追加し、冒頭の1文結論を検索意図に合わせて書き直す。同カテゴリ記事から内部リンク2本を追加"))
        elif g and g["pos"] <= 10 and g["ctr"] < 2.5 and g["imp"] >= 100:
            issues.append(("タイトル・メタ",
                           f'順位{g["pos"]}位なのにCTR {g["ctr"]}%（同順位帯の期待値4〜6%を下回る）',
                           f'タイトルを「数字+年号」型に変更（例:「{x["title"][:14]}…【2026年版・◯選】」）。メタディスクリプションの先頭60字を結論先出しに書き換え'))
        # 鮮度
        try:
            age = (today - date.fromisoformat(x["date"])).days
        except Exception:
            age = 0
        if age > 60:
            issues.append(("鮮度表記・冒頭",
                           f'最終更新から{age}日経過',
                           "冒頭の「◯年◯月時点」を当月に更新し、数値・事例・ツール情報を点検。dateModifiedを更新して再ビルド"))
        # 内部リンク
        if x["links"] < 3:
            cands = [y["title"][:18] for y in by_cat.get(x["cat"], []) if y["slug"] != x["slug"]][:2]
            hint = f'（候補: {" / ".join(cands)}）' if cands else "（新規記事の公開後に追加）"
            issues.append(("本文中の関連箇所",
                           f'内部リンクが{x["links"]}本（基準3本以上）',
                           f'同カテゴリ記事への文中リンクを{3 - x["links"]}本追加{hint}。アンカーは具体表現にする'))
        # FAQ
        if x["faq"] < 5:
            issues.append(("FAQセクション",
                           f'FAQが{x["faq"]}問（基準5問以上）',
                           "読者の検索意図から質問を追加し、回答は40〜60字で本文・Schemaと完全一致させる"))

        if issues:
            for where, now, change in issues[:2]:  # 1記事あたり最重要2件まで掲載
                art_rows.append({"art": x["title"][:24] or x["slug"], "where": where,
                                 "now": now, "change": change})
        else:
            keep.append(f'{x["title"][:26]}（{("順位" + str(g["pos"]) + "位・CTR" + str(g["ctr"]) + "%") if g else "構造基準を全て満たしています"}）')

    # --- サイト全体（構造・導線・カテゴリ） ---
    site_rows = []
    thin = [(c, len(v)) for c, v in by_cat.items() if len(v) <= 2]
    cat_jp = {"aio": "AIO・LLMO", "seo": "SEO", "meo": "MEO", "ai-marketing": "AI集客・活用"}
    for c, n in sorted(thin, key=lambda x: x[1]):
        site_rows.append({"target": f'カテゴリ「{cat_jp.get(c, c)}」', "where": "記事クラスター",
                          "now": f"記事{n}本のみ（クラスターが薄くトピック権威が立たない）",
                          "change": "このカテゴリのKWを次の記事作成で優先し、5本以上のクラスターにしてピラー記事から相互リンク"})
    areas = d.get("areas") or []
    if areas:
        drops = [(areas[i], areas[i + 1], areas[i]["reach"] - areas[i + 1]["reach"])
                 for i in range(len(areas) - 1)]
        drops.sort(key=lambda x: -x[2])
        for a1, a2, gap in drops[:2]:
            site_rows.append({"target": "LP（集客支援サービス）", "where": f'「{a1["name"]}」セクション末尾',
                              "now": f'「{a1["name"]}」→「{a2["name"]}」で到達率が{gap}pt低下（最大の離脱点）',
                              "change": f'「{a1["name"]}」の最後に次セクションへの橋渡し文+ミニCTAボタンを追加。「{a2["name"]}」の見出しを読者利益型に変更'})
    if d.get("devices"):
        mb = next((v for k, v in d["devices"] if k == "mobile"), 0)
        tot = sum(v for _, v in d["devices"]) or 1
        if mb / tot >= 0.55:
            site_rows.append({"target": "全記事テンプレート", "where": "冒頭ファーストビュー",
                              "now": f"スマートフォン比率{round(mb/tot*100)}%",
                              "change": "スマホ表示での冒頭を点検: 結論ボックス→この記事でわかること→目次が2スクロール以内に収まるか確認し、超える場合は冒頭画像を軽量化"})
    if d.get("ai_sessions", 0) < 10:
        site_rows.append({"target": "サイト外の露出", "where": "プレスリリース・外部寄稿",
                          "now": f'AI経由参照が{d.get("ai_sessions", 0)}セッション（立ち上がり前）',
                          "change": "記事15本到達を目安に準備済みのプレスリリース草稿（docs/press-release-draft.md）を配信。ChatGPT系はサイト外の言及量が引用を左右する"})
    ch = d.get("channels") or []
    if ch:
        org = next((v for k, v in ch if "Organic Search" in k), 0)
        tot = sum(v for _, v in ch) or 1
        if org / tot < 0.4:
            site_rows.append({"target": "流入構造", "where": "検索チャネル",
                              "now": f"自然検索比率{round(org/tot*100)}%（4割未満）",
                              "change": "新規記事の公開ペース維持とインデックス確認を最優先。直接流入が多い場合は指名検索の受け皿（サイト名での1位表示）を確認"})

    return {"articles": art_rows[:14], "site": site_rows[:6], "keep": keep[:6],
            "audited": len(arts)}


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

    # サイト資産サマリー（リポジトリの記事から実測 — デモ/実データ共通）
    import re as _re
    scores, lens, cats = [], [], {}
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = _re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, _re.S)
        if not m:
            continue
        fm, body = m.groups()
        sc = _re.search(r"^score:\s*(\d+)", fm, _re.M)
        if sc:
            scores.append(int(sc.group(1)))
        lens.append(len(_re.sub(r"\s", "", body)))
        cm = _re.search(r"^category:\s*(\S+)", fm, _re.M)
        if cm:
            cats[cm.group(1)] = cats.get(cm.group(1), 0) + 1
    assets = {
        "count": len(lens),
        "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
        "avg_len": round(sum(lens) / len(lens)) if lens else 0,
        "cats": sorted(cats.items(), key=lambda x: -x[1]),
    }

    # 来月のKPI目標（当月実績から自動設定。立ち上げ期は最低増加量でフロアを敷く）
    def tgt(v, rate, floor):
        return max(round(v * rate), v + floor)
    targets = [
        ("セッション", f'{cur.get("sessions", 0):,}', f'{tgt(cur.get("sessions", 0), 1.3, 100):,}',
         "記事数増加+順位上昇の複利。前月比+30%または+100の大きい方"),
        ("検索クリック", f'{cur.get("clicks", 0):,}', f'{tgt(cur.get("clicks", 0), 1.4, 60):,}',
         "新規記事のインデックス進行とリライトによるCTR改善"),
        ("検索表示回数", f'{cur.get("impressions", 0):,}', f'{tgt(cur.get("impressions", 0), 1.4, 2000):,}',
         "露出の総量。テーマの面を広げるほど伸びる先行指標"),
        ("CV（相談+資料DL）", str(cur.get("cv", 0)), str(tgt(cur.get("cv", 0), 1.5, 2)),
         "記事→LP導線の改善プラン実施による転換率向上"),
        ("AI経由参照", str(d.get("ai_sessions", 0)), str(tgt(d.get("ai_sessions", 0), 1.5, 5)),
         "記事蓄積とllms.txt更新によるAI引用の積み上がり"),
        ("新規公開記事", f'{d["content"]["published"]}本', "60本",
         "毎日2本の自動生成体制の定常値（品質90点以上のみ）"),
    ]

    # 機械が読める目標値（翌月号で達成率を突合するために保存する）
    target_nums = {
        "sessions": tgt(cur.get("sessions", 0), 1.3, 100),
        "clicks": tgt(cur.get("clicks", 0), 1.4, 60),
        "impressions": tgt(cur.get("impressions", 0), 1.4, 2000),
        "cv": tgt(cur.get("cv", 0), 1.5, 2),
        "ai": tgt(d.get("ai_sessions", 0), 1.5, 5),
    }

    # 前月号で設定した「当月の目標」との突合（初月は前月号が無いため空になる）
    import json as _json
    prev_targets, achievement = {}, []
    tf = ROOT / "reports" / "targets.json"
    if tf.exists():
        try:
            prev_targets = _json.loads(tf.read_text(encoding="utf-8")).get(cur["label"], {})
        except Exception:
            prev_targets = {}
    if prev_targets:
        actual = {"sessions": cur.get("sessions", 0), "clicks": cur.get("clicks", 0),
                  "impressions": cur.get("impressions", 0), "cv": cur.get("cv", 0),
                  "ai": d.get("ai_sessions", 0)}
        jp = {"sessions": "セッション", "clicks": "検索クリック", "impressions": "検索表示回数",
              "cv": "CV（相談+資料DL）", "ai": "AI経由参照"}
        for k, label in jp.items():
            t, a = prev_targets.get(k), actual.get(k, 0)
            if not t:
                continue
            rate = round(a / t * 100)
            achievement.append({"label": label, "target": t, "actual": a, "rate": rate,
                                "judge": "達成" if rate >= 100 else ("あと一歩" if rate >= 80 else "未達")})

    # 指標の良し悪しを基準つきで判定する（数字だけでは判断できないため）
    sess = cur.get("sessions", 0) or 0
    ctr = cur.get("ctr", 0) or 0
    pos = cur.get("pos", 0) or 0
    cvr = (cur.get("cv", 0) / sess * 100) if sess else 0
    ai_ratio = (d.get("ai_sessions", 0) / sess * 100) if sess else 0

    def band(v, good, ok, reverse=False):
        if reverse:
            return "良好" if v and v <= good else ("標準" if v and v <= ok else "要改善")
        return "良好" if v >= good else ("標準" if v >= ok else "要改善")

    assess = [
        {"k": "平均CTR", "v": f"{ctr}%", "j": band(ctr, 3.0, 1.5),
         "base": "3%以上=良好 / 1.5〜3%=標準 / 1.5%未満=要改善",
         "why": "同じ順位でもタイトルとメタ次第で倍以上変わる。低いならタイトル改善が最短の打ち手"},
        {"k": "平均掲載順位", "v": f"{pos}位", "j": band(pos, 10, 20, reverse=True),
         "base": "10位以内=良好 / 10〜20位=標準 / 20位超=要改善",
         "why": "10位以内が1ページ目。11〜30位はリライトで最も伸びしろが大きい層"},
        {"k": "CV率", "v": f"{cvr:.2f}%", "j": band(cvr, 1.0, 0.3),
         "base": "1%以上=良好 / 0.3〜1%=標準 / 0.3%未満=要改善",
         "why": "BtoBの問い合わせ型は0.5〜1%が一般的な水準。低いならLP導線を疑う"},
        {"k": "AI経由の比率", "v": f"{ai_ratio:.1f}%", "j": band(ai_ratio, 3.0, 1.0),
         "base": "3%以上=良好 / 1〜3%=標準 / 1%未満=立ち上げ中",
         "why": "AI検索からの流入比率。まだ市場全体で数%の段階なので、あること自体が先行指標"},
    ]

    # 広告で同じ流入を買った場合の金額（経営判断のための換算値）
    CPC = 300  # この領域（AIO/SEO/MEO関連KW）の控えめな想定単価（円）
    ad_value = (cur.get("clicks", 0) or 0) * CPC
    n_art = max(assets["count"], 1)
    efficiency = {
        "ad_value": ad_value, "cpc": CPC,
        "per_article_sessions": round(sess / n_art, 1),
        "per_article_clicks": round((cur.get("clicks", 0) or 0) / n_art, 1),
        "per_article_value": round(ad_value / n_art),
    }

    # 3行サマリー（詳細を読む前に結論だけ掴めるようにする）
    headline = [
        f'流入は{"増えました" if cur.get("sessions", 0) >= prev.get("sessions", 0) else "伸び悩みました"}。'
        f'セッション{cur.get("sessions", 0):,}（前月比{mom("sessions")}）、'
        f'検索クリック{cur.get("clicks", 0):,}（{mom("clicks")}）。',
        f'成果は{"前進しました" if cur.get("cv", 0) >= prev.get("cv", 0) else "横ばいでした"}。'
        f'CV{cur.get("cv", 0)}件（{mom("cv")}）、'
        f'広告で同じクリックを買うと約{ad_value:,}円相当の流入を、記事の資産で獲得しています。',
        f'来月は「{actions[0][0]}」を最優先に進めます。'
        f'記事は{d["content"]["published"]}本公開し、累計{assets["count"]}本（平均{assets["avg_score"]}点）まで積み上がりました。',
    ]

    # リスクと前提（数字を過信しないための注記）
    risks = [
        ("単月の増減だけで判断しない", "検索は季節性とGoogleのアルゴリズム更新で単月±20%程度動きます。"
                                "3ヶ月の傾向線で見るのが実務的です。"),
        ("Search Consoleのデータは3日遅れ", "月末付近の数値は確定前のため、翌月号で微増することがあります。"),
        ("AI経由の流入は過小評価になりがち", "ChatGPT等はリファラーを送らない場合があり、"
                                     "実際のAI経由の影響は計測値より大きい可能性があります。"),
        ("記事数が少ない段階は順位が不安定", f"現在{assets['count']}本。"
                                    "30本を超えたあたりからドメイン全体の評価が安定してきます。"),
    ]

    return {"grown": grown, "fixes": fixes, "actions": actions, "mom": mom,
            "winners": winners, "challengers": challengers, "summary": summary,
            "assets": assets, "targets": targets, "audit": audit_site(d),
            "target_nums": target_nums, "achievement": achievement, "assess": assess,
            "efficiency": efficiency, "headline": headline, "risks": risks}


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


def dist_bars(pairs, color="#2563eb", jp=None):
    """チャネル別・デバイス別などの分布バー"""
    if not pairs:
        return f'<p style="color:{MUTED}">データなし（GA4接続後に表示されます）</p>'
    total = sum(v for _, v in pairs) or 1
    rows = ""
    for name, v in pairs:
        label = (jp or {}).get(name, name)
        pct = round(v / total * 100)
        rows += (f'<div class="hm-row"><div class="hm-label">{label}</div>'
                 f'<div class="hm-track"><div class="hm-bar" style="width:{max(pct,2)}%;background:{color}"></div></div>'
                 f'<div class="hm-val">{v:,}<span style="color:{MUTED};font-weight:normal"> ({pct}%)</span></div></div>')
    return f'<div class="heatmap">{rows}</div>'


def svg_series(vals, labels, color, title, height=170):
    """日別推移などの汎用折れ線（月次svg_lineの生値版）"""
    if not vals or not any(vals):
        return f'<p style="color:{MUTED}">データなし</p>'
    W, H, PL, PB = 560, height, 40, 26
    mx = max(vals) * 1.15
    n = max(len(vals) - 1, 1)
    pts = [(PL + i * (W - PL - 12) / n, H - PB - (v / mx) * (H - PB - 18))
           for i, v in enumerate(vals)]
    path = "M" + " L".join(f"{x:.0f} {y:.0f}" for x, y in pts)
    step = max(1, len(labels) // 10)
    ticks = "".join(f'<text x="{pts[i][0]:.0f}" y="{H-6}" font-size="9" fill="{MUTED}" text-anchor="middle">{labels[i]}</text>'
                    for i in range(0, len(labels), step))
    last = f'<text x="{pts[-1][0]:.0f}" y="{pts[-1][1]-9:.0f}" font-size="11" font-weight="bold" fill="{NAVY}" text-anchor="middle">{vals[-1]:,}</text>'
    grid = "".join(f'<line x1="{PL}" y1="{H-PB-(H-PB-18)*g/4:.0f}" x2="{W-12}" y2="{H-PB-(H-PB-18)*g/4:.0f}" stroke="#e3eaf3"/>' for g in range(5))
    area = f'<path d="{path} L{pts[-1][0]:.0f} {H-PB} L{PL} {H-PB} Z" fill="{color}" opacity="0.08"/>'
    return (f'<div class="chart"><div class="chart-t">{title}</div>'
            f'<svg viewBox="0 0 {W} {H}">{grid}{area}'
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
            f'{last}{ticks}</svg></div>')


def render(d, a):
    labels = d["months"]
    cur, prev = labels[-1], labels[-2]
    ym = cur["label"]
    demo_banner = ('<div class="demo-banner">SAMPLE ― 本レポートはサンプルデータです。'
                   'GA4/GSC接続後、実データで自動発行されます。</div>') if d["demo"] else ""

    # 表紙ロゴ（白版）をbase64で埋め込み
    logo_b64 = ""
    lp = ROOT / "site" / "images" / "company" / "logo-white.png"
    if lp.exists():
        logo_b64 = f'<img class="cv-logo" src="data:image/png;base64,{base64.b64encode(lp.read_bytes()).decode()}">'

    def tile(label, key, unit=""):
        v = cur.get(key, 0)
        series = [m.get(key, 0) or 0 for m in labels]
        mom = a["mom"](key)
        up = not mom.startswith("-")
        good = (not up) if key == "pos" else up  # 順位は下がる=良い
        return (f'<div class="tile"><div class="t-label">{label}</div>'
                f'<div class="t-val">{v:,}{unit}</div>'
                f'<div class="t-mom {"good" if good else "bad"}">前月比 {mom}</div>'
                f'<div class="t-spark">{svg_spark(series, BLUE if key != "pos" else TEAL)}</div></div>')

    qrows = "".join(f'<tr><td>{q["q"]}</td><td class="num">{q["imp"]:,}</td><td class="num">{q["clicks"]:,}</td>'
                    f'<td class="num">{q["ctr"]}%</td><td class="num">{q["pos"]}位</td></tr>'
                    for q in d.get("queries", []))
    prows = "".join(f'<tr><td style="word-break:break-all">{p["path"]}</td><td class="num">{p["imp"]:,}</td>'
                    f'<td class="num">{p["clicks"]:,}</td><td class="num">{p["ctr"]}%</td><td class="num">{p["pos"]}位</td></tr>'
                    for p in d.get("pages", [])) or '<tr><td colspan="5">当月のページ別データはまだありません</td></tr>'
    trows = "".join(f'<tr><td>{k}</td><td class="num">{now}</td><td class="num" style="color:#067647;font-weight:bold">{tv}</td><td>{why}</td></tr>'
                    for k, now, tv, why in a["targets"])
    audit = a["audit"]
    # 1ページに収まる件数に絞る（溢れると読みにくくなるため、優先度の高い順に上位のみ掲載）
    ART_MAX, SITE_MAX = 5, 3
    audit_art_rows = "".join(
        f'<tr><td>{r["art"]}</td><td style="white-space:nowrap">{r["where"]}</td><td>{r["now"]}</td><td>{r["change"]}</td></tr>'
        for r in audit["articles"][:ART_MAX]) or '<tr><td colspan="4">全記事が基準を満たしています（修正指示なし）</td></tr>'
    audit_site_rows = "".join(
        f'<tr><td>{r["target"]}</td><td style="white-space:nowrap">{r["where"]}</td><td>{r["now"]}</td><td>{r["change"]}</td></tr>'
        for r in audit["site"][:SITE_MAX]) or '<tr><td colspan="4">構造上の修正指示はありません</td></tr>'
    audit_more = ""
    rest = max(len(audit["articles"]) - ART_MAX, 0) + max(len(audit["site"]) - SITE_MAX, 0)
    if rest:
        audit_more = (f'<p class="note">※ 優先度の高い{ART_MAX + SITE_MAX}件を掲載しています。'
                      f'他{rest}件の指示も週次最適化で順次実施します。</p>')
    # ページ溢れを防ぐため件数を絞り、2カラムで表示する
    audit_keep = "".join(f'<li>{k}</li>' for k in audit["keep"][:4]) \
        or "<li>（来月の計測データで抽出します）</li>"

    head_html = "".join(f'<li>{h}</li>' for h in a["headline"])
    assess_rows = "".join(
        f'<tr><td><b>{x["k"]}</b></td><td class="num">{x["v"]}</td>'
        f'<td><span class="jd jd-{x["j"]}">{x["j"]}</span></td>'
        f'<td>{x["base"]}</td><td>{x["why"]}</td></tr>' for x in a["assess"])
    ach = a["achievement"]
    ach_rows = "".join(
        f'<tr><td>{x["label"]}</td><td class="num">{x["target"]:,}</td>'
        f'<td class="num">{x["actual"]:,}</td>'
        f'<td class="num"><b>{x["rate"]}%</b></td>'
        f'<td><span class="jd jd-{x["judge"]}">{x["judge"]}</span></td></tr>' for x in ach) \
        or '<tr><td colspan="5">前号がないため今回は突合できません。次号から達成率を表示します。</td></tr>'
    eff = a["efficiency"]
    risk_rows = "".join(f'<tr><td style="white-space:nowrap"><b>{t}</b></td><td>{b}</td></tr>'
                        for t, b in a["risks"])
    assets = a["assets"]
    cat_jp = {"aio": "AIO・LLMO", "seo": "SEO", "meo": "MEO", "ai-marketing": "AI集客・活用"}
    cat_pairs = [(cat_jp.get(c, c), n) for c, n in assets["cats"]]
    frows = "".join(f'<tr><td><span class="pri pri-{f["pri"]}">{f["pri"]}</span></td><td>{f["area"]}</td>'
                    f'<td>{f["now"]}</td><td>{f["fix"]}</td></tr>' for f in a["fixes"])
    crows = "".join(f'<tr><td>{r["date"]}</td><td>{r["title"]}</td><td class="num">{r["score"]}</td>'
                    f'<td>{r["status"]}</td></tr>' for r in d["content"]["rows"])
    grown = "".join(f"<li>{g}</li>" for g in a["grown"])
    action_rows = "".join(
        f'<tr><td class="num">{i}</td><td>{t}</td><td style="white-space:nowrap">{w}</td><td>{why}</td></tr>'
        for i, (t, w, why) in enumerate(a["actions"], 1))
    winner_rows = "".join(
        f'<li><b>「{q["q"]}」</b> — {q["pos"]}位・CTR {q["ctr"]}%・クリック{q["clicks"]:,}。この構造（結論先出し+FAQ）を新規記事に横展開</li>'
        for q in a["winners"]) or "<li>該当なし（来月の分析で抽出します）</li>"
    challenger_rows = "".join(
        f'<li><b>「{q["q"]}」</b> — 現在{q["pos"]}位（表示{q["imp"]:,}）。1ページ目に入ればクリック数倍のポテンシャル。H2追加+内部リンクでリライト</li>'
        for q in a["challengers"]) or "<li>該当なし</li>"

    glossary = [
        ("セッション", "サイトへの訪問回数。1人が朝と夜に見れば2セッション"),
        ("CV（コンバージョン）", "無料相談・資料DLなど、成果地点への到達件数"),
        ("表示回数（インプレッション）", "Google検索結果に自社ページが表示された回数"),
        ("CTR", "表示回数のうちクリックされた割合。タイトル改善で伸ばせる"),
        ("平均掲載順位", "検索結果での平均的な表示位置。小さいほど上位"),
        ("AI経由参照", "ChatGPT・Perplexity等のAIサービスからの流入。LLMO施策の成果指標"),
        ("エリア到達率", "LPの各セクションまで読者がスクロール到達した割合（独自計測）"),
        ("AIO", "Google検索のAI回答（AI Overview）に引用されるための最適化"),
        ("LLMO", "ChatGPT等のAIチャットの回答で言及されるための最適化"),
        ("E-E-A-T", "経験・専門性・権威性・信頼性。Googleの品質評価基準"),
        ("リライト", "既存記事の加筆・修正。順位11〜30位の記事が最も効果的"),
        ("品質スコア", "当社の6観点採点（100点満点）。90点未満は公開されない"),
    ]
    gloss_rows = "".join(f'<tr><td style="white-space:nowrap"><b>{k}</b></td><td>{v}</td></tr>'
                         for k, v in glossary)
    ai_total = d.get("ai_sessions", 0)
    ai_prev = d.get("ai_prev", 0)
    ai_mom = f"+{round((ai_total - ai_prev) / ai_prev * 100)}%" if ai_prev else "―"
    best = max(d["content"]["rows"], key=lambda r: str(r.get("score", "")), default=None)
    toc_items = [
        "エグゼクティブサマリー（3行まとめ）", "指標の評価（良し悪しの判定）",
        "KPIダッシュボード（前月比・6ヶ月推移）",
        "検索パフォーマンス詳細（クエリ分析）", "記事別パフォーマンス+サイト資産",
        "流入構造分析（チャネル・デバイス・日別）", "AI検索（AIO/LLMO）分析",
        "投資対効果（広告換算・記事あたり効率）",
        "LPコンバージョン分析（ファネル+ヒートマップ）", "成果の要因分析",
        "改善プラン（優先度つき対比表）", "サイト全体監査（記事別の修正指示）", "コンテンツ実績",
        "前月目標の達成率と来月のKPI目標", "来月の実行スケジュール",
        "リスクと前提条件", "付録: 指標の定義"]
    toc_html = "".join(f'<li><span>{i:02d}</span>{t}</li>' for i, t in enumerate(toc_items, 1))

    best_html = ""
    if best:
        best_html = (f'<div class="best-card"><div class="bc-k">🏆 今月のベスト記事</div>'
                     f'<div class="bc-t">{best["title"]}</div>'
                     f'<div class="bc-s">品質スコア {best["score"]}。この記事の構成（冒頭断言・FAQ・出典付きデータ）を来月の新規記事の手本とします。</div></div>')

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; }}
:root {{ --navy: {NAVY}; --blue: {BLUE}; --teal: {TEAL}; --gold: #b7922e; --muted: {MUTED}; --line: #e3eaf3; }}
body {{ font-family: "Yu Gothic", "Meiryo", sans-serif; color: #10203a; font-size: 10pt; line-height: 1.8; }}
.sheet {{ width: 210mm; min-height: 296mm; padding: 16mm 15mm 18mm; page-break-after: always; position: relative; }}
.sheet:last-child {{ page-break-after: auto; }}

/* ---- 表紙 ---- */
.cover-page {{ background: linear-gradient(150deg, #071a38 0%, #0b2447 45%, #14345c 100%); color: #fff;
  display: flex; flex-direction: column; padding: 22mm 20mm; }}
.cv-gold {{ width: 64px; height: 4px; background: var(--gold); margin: 10mm 0 6mm; }}
.cv-kicker {{ letter-spacing: .35em; font-size: 9pt; color: #93b4e8; }}
.cv-title {{ font-size: 27pt; font-weight: bold; line-height: 1.4; margin-top: 4mm; }}
.cv-month {{ font-size: 15pt; color: var(--gold); font-weight: bold; margin-top: 3mm; letter-spacing: .1em; }}
.cv-logo {{ height: 34px; width: auto; }}
.cv-meta {{ margin-top: auto; font-size: 9.5pt; color: #bcd0ee; line-height: 2.1; border-top: 1px solid rgba(255,255,255,.25); padding-top: 6mm; }}
.cv-meta b {{ color: #fff; }}
.cv-badges {{ display: flex; gap: 8px; margin-top: 8mm; flex-wrap: wrap; }}
.cv-badge {{ border: 1px solid rgba(255,255,255,.35); border-radius: 999px; padding: 3px 14px; font-size: 8.5pt; color: #dbe7fa; }}

/* ---- 共通 ---- */
.demo-banner {{ background: #fff3cd; border: 2px dashed #d97706; color: #92400e; font-weight: bold; text-align: center; padding: 5px; margin-bottom: 10px; border-radius: 6px; font-size: 9pt; }}
.sec {{ display: flex; align-items: center; gap: 10px; margin: 0 0 12px; page-break-after: avoid; }}
.sec .no {{ background: var(--navy); color: #fff; font-weight: bold; font-size: 10pt; padding: 3px 12px; border-radius: 4px; letter-spacing: .08em; }}
.sec h2 {{ font-size: 14.5pt; }}
.sec .gold {{ flex: 1; height: 2px; background: linear-gradient(90deg, var(--gold), transparent); }}
h3 {{ font-size: 11pt; margin: 14px 0 6px; color: var(--navy); }}
.note {{ font-size: 8.5pt; color: var(--muted); }}
.callout {{ border-left: 4px solid var(--gold); background: #fbf8ef; padding: 10px 14px; border-radius: 0 8px 8px 0; margin: 10px 0; font-size: 9.5pt; }}

/* ---- 目次・サマリー ---- */
.toc {{ columns: 2; column-gap: 22px; margin: 6px 0 0; }}
.toc li {{ list-style: none; padding: 2.5px 0; border-bottom: 1px dotted var(--line); font-size: 8.8pt; break-inside: avoid; }}
.toc li span {{ color: var(--gold); font-weight: bold; margin-right: 8px; }}
.exec {{ font-size: 10pt; line-height: 1.9; background: #f6f9fd; border: 1px solid var(--line); border-radius: 10px; padding: 11px 15px; }}
.hl-cards {{ display: flex; gap: 10px; margin-top: 12px; }}
.hl {{ flex: 1; border: 1px solid var(--line); border-top: 3px solid var(--blue); border-radius: 8px; padding: 10px 12px; }}
.hl .k {{ font-size: 8.5pt; color: var(--muted); }}
.hl .v {{ font-size: 16pt; font-weight: bold; color: var(--navy); }}
.hl .s {{ font-size: 8.5pt; color: var(--teal); font-weight: bold; }}

/* ---- KPI ---- */
.tiles {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
.tile {{ border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px 6px; }}
.t-label {{ font-size: 8.5pt; color: var(--muted); }}
.t-val {{ font-size: 17pt; font-weight: bold; color: var(--navy); }}
.t-mom {{ font-size: 8.5pt; font-weight: bold; }}
.t-mom.good {{ color: #067647; }} .t-mom.bad {{ color: #b91c1c; }}
.t-spark {{ margin-top: 2px; }}
.charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
.chart {{ border: 1px solid var(--line); border-radius: 8px; padding: 8px; }}
.chart-t {{ font-size: 9pt; font-weight: bold; margin-bottom: 4px; }}

/* ---- テーブル ---- */
table {{ border-collapse: collapse; width: 100%; font-size: 9pt; }}
th, td {{ border: 1px solid #dbe3ee; padding: 5px 8px; text-align: left; vertical-align: top; }}
th {{ background: var(--navy); color: #fff; font-weight: 600; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr:nth-child(even) td {{ background: #f7fafd; }}
.two-col {{ display: flex; gap: 12px; }}
.two-col > div {{ flex: 1; border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; }}
.two-col h3 {{ margin-top: 0; }}
.two-col ul {{ padding-left: 18px; font-size: 9pt; }}
.two-col li {{ margin: 6px 0; }}

/* ---- ヒートマップ・ファネル ---- */
.heatmap {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }}
.hm-row {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
.hm-label {{ width: 110px; font-size: 8.5pt; }}
.hm-track {{ flex: 1; background: #eef2f8; border-radius: 4px; height: 13px; }}
.hm-bar {{ height: 13px; border-radius: 4px; }}
.hm-val {{ width: 40px; text-align: right; font-size: 8.5pt; font-weight: bold; }}
.funnel {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; }}
.fn-row {{ margin: 2px 0; }}
.fn-bar {{ background: linear-gradient(90deg, var(--navy), var(--blue)); color: #fff; border-radius: 6px;
  padding: 7px 12px; display: flex; justify-content: space-between; font-size: 9.5pt; min-width: 130px; }}
.fn-drop {{ font-size: 8pt; color: #b91c1c; font-weight: bold; padding: 1px 0 1px 8px; }}

/* ---- その他 ---- */
.pri {{ font-weight: bold; padding: 1px 8px; border-radius: 10px; font-size: 8.5pt; white-space: nowrap; }}
.pri-高 {{ background: #fee2e2; color: #b91c1c; }}
.pri-中 {{ background: #fef3c7; color: #b45309; }}
.pri-低 {{ background: #e0f2fe; color: #0369a1; }}
ul.grown li {{ margin: 7px 0; font-size: 9.5pt; }}
.best-card {{ border: 2px solid var(--gold); border-radius: 10px; padding: 10px 14px; margin-top: 10px; background: #fdfaf1; }}
.bc-k {{ font-size: 8.5pt; color: var(--gold); font-weight: bold; letter-spacing: .1em; }}
.bc-t {{ font-weight: bold; font-size: 10.5pt; }}
.bc-s {{ font-size: 8.5pt; color: var(--muted); }}

/* ---- 判定バッジ・3行まとめ ---- */
.jd {{ font-weight: bold; padding: 1px 8px; border-radius: 10px; font-size: 8.5pt; white-space: nowrap; }}
.jd-良好, .jd-達成 {{ background: #dcfce7; color: #047857; }}
.jd-標準, .jd-あと一歩 {{ background: #e0f2fe; color: #0369a1; }}
.jd-要改善, .jd-未達 {{ background: #fee2e2; color: #b91c1c; }}
.jd-立ち上げ中 {{ background: #fef3c7; color: #b45309; }}
ol.head3 {{ counter-reset: h; list-style: none; padding: 0; margin: 0; }}
ol.head3 li {{ counter-increment: h; position: relative; padding: 9px 0 9px 34px; font-size: 10.5pt;
  line-height: 1.95; border-bottom: 1px dotted var(--line); }}
ol.head3 li:last-child {{ border-bottom: 0; }}
ol.head3 li::before {{ content: counter(h); position: absolute; left: 0; top: 10px;
  width: 22px; height: 22px; border-radius: 50%; background: var(--navy); color: #fff;
  font-size: 8.5pt; font-weight: bold; text-align: center; line-height: 22px; }}
.keep2 {{ columns: 2; column-gap: 18px; padding-left: 18px; font-size: 9pt; }}
.keep2 li {{ break-inside: avoid; margin: 4px 0; }}
.roi {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }}
.roi-box {{ border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; }}
.roi-box .k {{ font-size: 8.6pt; color: var(--muted); }}
.roi-box .v {{ font-size: 19pt; font-weight: 900; color: var(--navy); }}
.roi-box .s {{ font-size: 8.5pt; color: var(--muted); }}
.back-cover {{ background: #0b2447; color: #fff; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; gap: 4mm; }}
.back-cover .l {{ font-size: 13pt; font-weight: bold; }}
.back-cover .s {{ font-size: 9.5pt; color: #9db8e0; line-height: 2.2; }}
</style></head><body>

<!-- ページ1: 表紙 -->
<div class="sheet cover-page">
  {logo_b64}
  <div class="cv-gold"></div>
  <div class="cv-kicker">MONTHLY CONSULTING REPORT</div>
  <div class="cv-title">月次コンサルティング<br>レポート</div>
  <div class="cv-month">{ym} 月次報告</div>
  <div class="cv-badges">
    <span class="cv-badge">検索パフォーマンス</span><span class="cv-badge">AI検索（AIO/LLMO）</span>
    <span class="cv-badge">LPコンバージョン分析</span><span class="cv-badge">改善プラン</span>
  </div>
  <div class="cv-meta">
    対象メディア: <b>AI集客ラボ</b>（https://ai.7senses.co.jp）+ 集客支援LP<br>
    発行: <b>セブンセンシズ株式会社</b>｜発行日: {date.today().isoformat()}｜作成: 自動集計+分析エンジン<br>
    本レポートの数値は Google Analytics 4 / Google Search Console / 運用ログの実測にもとづきます
  </div>
</div>

<!-- ページ2: 目次+エグゼクティブサマリー -->
<div class="sheet">
{demo_banner}
<div class="sec"><span class="no">01</span><h2>エグゼクティブサマリー</h2><div class="gold"></div></div>
<h3 style="margin-top:0">今月を3行で</h3>
<ol class="head3">{head_html}</ol>
<h3>詳しい総評</h3>
<p class="exec">{a["summary"]}</p>
<div class="hl-cards">
  <div class="hl"><div class="k">セッション</div><div class="v">{cur.get("sessions",0):,}</div><div class="s">前月比 {a["mom"]("sessions")}</div></div>
  <div class="hl"><div class="k">CV（相談+資料DL）</div><div class="v">{cur.get("cv",0)}件</div><div class="s">前月比 {a["mom"]("cv")}</div></div>
  <div class="hl"><div class="k">AI経由参照</div><div class="v">{ai_total}</div><div class="s">前月比 {ai_mom}</div></div>
  <div class="hl"><div class="k">当月公開記事</div><div class="v">{d["content"]["published"]}本</div><div class="s">品質90点以上のみ</div></div>
</div>
<div class="callout"><b>今月の結論:</b> {a["grown"][0].replace("<b>","").replace("</b>","") if a["grown"] else "-"}</div>
<h3>本レポートの構成</h3>
<ul class="toc">{toc_html}</ul>
</div>

<!-- 指標の評価 -->
<div class="sheet">
<div class="sec"><span class="no">02</span><h2>指標の評価（良し悪しの判定）</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">数字だけでは「良いのか悪いのか」が分かりません。主要な4指標について、
一般的な水準と比べた判定と、その指標が何を意味するかを併記します。</p>
<table><tr><th style="width:16%">指標</th><th style="width:10%">当月</th><th style="width:9%">判定</th>
<th style="width:28%">判定の基準</th><th>この指標の意味と打ち手</th></tr>{assess_rows}</table>
<div class="callout"><b>判定の使い方:</b> 「要改善」があれば、その指標の打ち手を来月の実行スケジュール
（第13章）で最優先に組み込みます。「良好」は維持し、他の記事へ横展開します。
立ち上げ期は「標準」でも順調な場合が多いため、前月比の伸びと併せて判断してください。</div>
<h3>この4指標を選んでいる理由</h3>
<p style="font-size:9.5pt">セッションやPVは「結果」であり、動かすには原因側の指標を見る必要があります。
<b>順位</b>は露出量を決め、<b>CTR</b>は露出をクリックに変える効率、<b>CV率</b>はクリックを成果に変える効率、
<b>AI経由比率</b>は次の時代への適応度を表します。この4つが改善すれば、セッションとCVは後から付いてきます。</p>
</div>

<!-- KPIダッシュボード -->
<div class="sheet">
<div class="sec"><span class="no">03</span><h2>KPIダッシュボード</h2><div class="gold"></div></div>
<div class="tiles">
{tile("セッション", "sessions")}{tile("CV（相談+資料DL）", "cv", "件")}{tile("検索表示回数", "impressions")}
{tile("検索クリック", "clicks")}{tile("平均CTR", "ctr", "%")}{tile("平均掲載順位", "pos", "位")}
</div>
<h3>6ヶ月トレンド</h3>
<div class="charts">
{svg_line(labels, "sessions", BLUE, "セッション数（GA4）")}
{svg_line(labels, "clicks", TEAL, "検索クリック数（Search Console）")}
{svg_line(labels, "impressions", BLUE, "検索表示回数（Search Console）")}
{svg_line(labels, "pos", TEAL, "平均掲載順位（小さいほど良い）", "位")}
</div>
<p class="note" style="margin-top:8px">読み方: 表示回数はサイトの「露出の総量」、クリックは「選ばれた回数」、順位はその効率を表します。各タイル下の折れ線は6ヶ月の推移（スパークライン）です。</p>
</div>

<!-- ページ4: クエリ分析 -->
<div class="sheet">
<div class="sec"><span class="no">04</span><h2>検索パフォーマンス詳細</h2><div class="gold"></div></div>
<h3>クエリ別実績（上位10）</h3>
<table><tr><th>クエリ</th><th>表示回数</th><th>クリック</th><th>CTR</th><th>平均順位</th></tr>{qrows}</table>
<div class="two-col" style="margin-top:14px">
  <div><h3>🏅 勝ちクエリ（横展開する）</h3><ul>{winner_rows}</ul></div>
  <div><h3>🎯 テコ入れクエリ（リライト対象）</h3><ul>{challenger_rows}</ul></div>
</div>
</div>

<!-- ページ: 記事別パフォーマンス+サイト資産 -->
<div class="sheet">
<div class="sec"><span class="no">05</span><h2>記事別パフォーマンス</h2><div class="gold"></div></div>
<h3>ページ別実績（当月・表示回数順）</h3>
<table><tr><th>ページ</th><th>表示回数</th><th>クリック</th><th>CTR</th><th>平均順位</th></tr>{prows}</table>
<p class="note">読み方: 表示回数が多く順位が11位以下のページはリライトの最有力候補。CTRが同順位帯の平均より低いページはタイトル改善候補です。</p>
<h3 style="margin-top:14px">サイト資産サマリー（累計ストック）</h3>
<div class="hl-cards">
  <div class="hl"><div class="k">公開記事ストック</div><div class="v">{assets["count"]}本</div><div class="s">品質90点以上のみ</div></div>
  <div class="hl"><div class="k">平均品質スコア</div><div class="v">{assets["avg_score"]}点</div><div class="s">6観点採点/100点</div></div>
  <div class="hl"><div class="k">平均文字数</div><div class="v">{assets["avg_len"]:,}字</div><div class="s">基準5,000字以上</div></div>
</div>
<h3 style="margin-top:14px">カテゴリ別の記事構成</h3>
{dist_bars(cat_pairs, "#0d9488")}
<div class="callout"><b>資産の考え方:</b> 記事は広告と違い、公開後も検索とAI回答の両方から流入を生み続けるストック資産です。
1記事あたりの平均{assets["avg_len"]:,}字・平均{assets["avg_score"]}点の品質を保ったまま蓄積することが、ドメイン全体の評価とAI引用確率を押し上げます。</div>
</div>

<!-- ページ: 流入構造分析 -->
<div class="sheet">
<div class="sec"><span class="no">06</span><h2>流入構造分析</h2><div class="gold"></div></div>
<h3>チャネル別セッション（当月）</h3>
{dist_bars(d.get("channels", []), "#2563eb", {"Organic Search": "自然検索", "Direct": "直接流入", "Referral": "参照サイト", "Organic Social": "SNS", "Email": "メール", "Unassigned": "未分類", "Paid Search": "有料検索", "Cross-network": "クロスネットワーク"})}
<h3 style="margin-top:12px">デバイス別セッション（当月）</h3>
{dist_bars(d.get("devices", []), "#7b83eb", {"mobile": "スマートフォン", "desktop": "PC", "tablet": "タブレット"})}
<h3 style="margin-top:12px">日別クリック推移（当月・Search Console）</h3>
{svg_series(d.get("daily", {}).get("clicks", []), d.get("daily", {}).get("labels", []), "#0d9488", "検索クリック数の日次推移")}
<p class="note">読み方: 自然検索比率が高いほど広告費に依存しない集客構造。日別推移の右肩上がりは新規記事のインデックス進行を示します。
スマートフォン比率が高い場合、記事の冒頭結論・図解・表の見やすさがCVを左右します。</p>
</div>

<!-- ページ: AI検索分析 -->
<div class="sheet">
<div class="sec"><span class="no">07</span><h2>AI検索（AIO / LLMO）分析</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">検索結果の外側——ChatGPTやPerplexityの「回答」の中で自社がどれだけ参照されたかの分析です。ゼロクリック時代の新しい流入経路であり、当メディアの中核戦略です。</p>
<div class="hl-cards" style="margin:10px 0 14px">
  <div class="hl"><div class="k">AI経由セッション（当月）</div><div class="v">{ai_total}</div><div class="s">前月比 {ai_mom}</div></div>
  <div class="hl"><div class="k">AI経由の全体比</div><div class="v">{round(ai_total / max(cur.get("sessions",1),1) * 100, 1)}%</div><div class="s">対セッション</div></div>
  <div class="hl"><div class="k">実装済みAIO施策</div><div class="v">12項目</div><div class="s">全記事に標準適用</div></div>
</div>
<h3>プラットフォーム別内訳</h3>
{ai_bars(d.get("ai_breakdown", []), ai_total)}
<h3 style="margin-top:14px">この数字の意味と次の一手</h3>
<div class="callout">AI経由の訪問者は「AIの回答で自社を知り、確かめに来た」<b>非常に確度の高い見込み客</b>です。
ChatGPT比率が高い場合はサイト外の言及（プレスリリース・寄稿）を、Perplexity比率が高い場合は記事の鮮度更新を強化するのが定石です。
月末のAIスポットチェック（主要クエリをAIに質問し自社言及を記録）と併せて評価します。</div>
<p class="note">実装済みAIO施策: 冒頭断言回答 / H2直下1文結論 / FAQ構造化 / 出典付き数値 / llms.txt / robots.txt AI許可 / 構造化データ4種 / 監修者情報 / 鮮度表記 / 定義ブロック / 比較表 / 対象読者明記</p>
</div>

<!-- 投資対効果 -->
<div class="sheet">
<div class="sec"><span class="no">08</span><h2>投資対効果</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">記事は一度書けば資産として残り続けます。この章では
「同じ流入を広告で買ったらいくらか」と「記事1本がどれだけ働いているか」を金額と数字で示します。</p>
<div class="roi">
  <div class="roi-box">
    <div class="k">当月の流入を広告で買った場合の金額</div>
    <div class="v">約{eff["ad_value"]:,}円</div>
    <div class="s">検索クリック{cur.get("clicks", 0):,}回 × 想定クリック単価{eff["cpc"]}円で換算</div>
  </div>
  <div class="roi-box">
    <div class="k">記事1本あたりの月間価値</div>
    <div class="v">約{eff["per_article_value"]:,}円</div>
    <div class="s">累計{a["assets"]["count"]}本で割った1本あたりの広告換算値</div>
  </div>
  <div class="roi-box">
    <div class="k">記事1本あたりの月間セッション</div>
    <div class="v">{eff["per_article_sessions"]}</div>
    <div class="s">記事が増えるほど合計は積み上がる</div>
  </div>
  <div class="roi-box">
    <div class="k">記事1本あたりの月間クリック</div>
    <div class="v">{eff["per_article_clicks"]}</div>
    <div class="s">順位が上がると同じ本数でも増える</div>
  </div>
</div>
<h3>広告との決定的な違い</h3>
<p style="font-size:9.5pt">広告は出稿を止めた瞬間に流入がゼロになりますが、
記事は<b>公開後も検索とAI回答の両方から流入を生み続けます</b>。
上の金額は「今月分」であり、来月も同じ記事が同じように働きます。
記事が積み上がるほど、この金額は複利のように増えていきます。</p>
<div class="callout"><b>換算の前提:</b> クリック単価は{eff["cpc"]}円で計算しています。
AIO・SEO・MEO関連のキーワードは競合が多く、実際のリスティング広告では
1クリック500〜1,000円以上になることも珍しくありません。
そのため上の金額は<b>控えめな見積もり</b>です。</div>
</div>

<!-- ページ: LPコンバージョン分析 -->
<div class="sheet">
<div class="sec"><span class="no">09</span><h2>LPコンバージョン分析</h2><div class="gold"></div></div>
<h3>主要区画のファネル（どこまで読まれ、どこで離脱したか）</h3>
{funnel_html(d.get("areas", []))}
<h3 style="margin-top:14px">全12区画の到達ヒートマップ</h3>
{svg_heatbars(d.get("areas", []))}
<p class="note">■青=到達60%以上 ■水色=40-59% ■橙=20-39% ■赤=20%未満。GA4のarea_reachイベント（画面内40%表示で発火）による独自計測で、有料ヒートマップツールなしで取得しています。</p>
</div>

<!-- ページ7: 要因分析+改善プラン -->
<div class="sheet">
<div class="sec"><span class="no">10</span><h2>成果の要因分析</h2><div class="gold"></div></div>
<ul class="grown">{grown}</ul>
<div class="sec" style="margin-top:18px"><span class="no">11</span><h2>改善プラン（優先度つき対比表）</h2><div class="gold"></div></div>
<table><tr><th style="width:8%">優先度</th><th style="width:22%">エリア/対象</th><th style="width:30%">現状（データ根拠）</th><th>改善アクション（何をどう変えるか）</th></tr>{frows}</table>
</div>

<!-- ページ: サイト全体監査 -->
<div class="sheet">
<div class="sec"><span class="no">12</span><h2>サイト全体監査（どこを・どう変えるか）</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">全{audit["audited"]}記事とサイト構造を機械監査し、検索データ（順位・CTR）と品質基準（鮮度・内部リンク・FAQ）を突合した<b>具体的な修正指示</b>です。修正は週次最適化（毎週月曜）が自動で実施し、翌月号で効果を検証します。</p>
<h3>ブログ記事の修正指示（優先度順）</h3>
<table><tr><th style="width:22%">記事</th><th style="width:14%">修正箇所</th><th style="width:28%">現状（実測）</th><th>変更内容</th></tr>{audit_art_rows}</table>
<h3 style="margin-top:14px">サイト構造・導線の変更指示</h3>
<table><tr><th style="width:18%">対象</th><th style="width:16%">場所</th><th style="width:28%">現状（実測）</th><th>変更内容</th></tr>{audit_site_rows}</table>
{audit_more}
<h3 style="margin-top:14px">✅ 変更せず維持するもの（好調・基準充足）</h3>
<ul class="keep2">{audit_keep}</ul>
</div>

<!-- ページ8: コンテンツ実績+来月プラン -->
<div class="sheet">
<div class="sec"><span class="no">13</span><h2>コンテンツ実績</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">当月公開: <b>{d["content"]["published"]}本</b>（公開基準: 品質採点90点以上・機械検査18項目全PASSのみが公開されます）</p>
<table><tr><th>日付</th><th>タイトル</th><th>品質スコア</th><th>審査記録</th></tr>{crows}</table>
{best_html}
</div>

<!-- ページ: 目標対比+来月スケジュール -->
<div class="sheet">
<div class="sec"><span class="no">14</span><h2>前月目標の達成率と来月のKPI目標</h2><div class="gold"></div></div>
<h3 style="margin-top:0">前号で立てた「当月の目標」に対する結果</h3>
<table><tr><th>指標</th><th style="width:14%">前号の目標</th><th style="width:14%">当月の実績</th>
<th style="width:12%">達成率</th><th style="width:12%">判定</th></tr>{ach_rows}</table>
<h3>来月の目標</h3>
<p style="font-size:9.5pt">当月実績をベースに、来月の目標値を設定します。目標は「前月比の成長率」と「最低増加量」の大きい方を採用し、立ち上げ期でも歩みを止めない設計です。</p>
<table><tr><th>指標</th><th style="width:14%">当月実績</th><th style="width:14%">来月目標</th><th>目標の根拠</th></tr>{trows}</table>
<div class="callout"><b>目標の使い方:</b> 来月号のレポートで本表の目標と実績を突合します。2ヶ月連続で未達の指標は、施策の前提（KW選定・導線設計）から見直します。</div>
<div class="sec" style="margin-top:18px"><span class="no">15</span><h2>来月の実行スケジュール</h2><div class="gold"></div></div>
<table><tr><th style="width:6%">#</th><th>アクション</th><th style="width:12%">実施時期</th><th style="width:34%">狙い</th></tr>{action_rows}</table>
</div>

<!-- ページ9: 付録 -->
<div class="sheet">
<div class="sec"><span class="no">16</span><h2>リスクと前提条件</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">数字を正しく受け取っていただくために、
このレポートを読むうえで知っておいていただきたい前提をまとめます。</p>
<table><tr><th style="width:32%">前提・注意点</th><th>内容</th></tr>{risk_rows}</table>
<div class="callout"><b>判断のしかた:</b> 単月の数字が下がっても、施策が間違っているとは限りません。
逆に単月で上がっても、それが施策の成果とは限りません。
<b>3ヶ月の傾向線</b>と<b>順位・CTRという原因側の指標</b>で判断するのが、この事業の正しい見方です。
本レポートの第2章（指標の評価）と第3章の6ヶ月トレンドを、その判断材料としてご覧ください。</div>
</div>

<div class="sheet">
<div class="sec"><span class="no">17</span><h2>付録: 指標の定義と用語解説</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">本レポートで使用している指標・用語の定義です。社内共有の際にご活用ください。</p>
<table>{gloss_rows}</table>
<h3 style="margin-top:14px">データソースと計測方法</h3>
<p class="note">Google Analytics 4（セッション・CV・AI参照元・エリア到達）/ Google Search Console（表示・クリック・CTR・順位・クエリ）/ 運用ログ（記事作成・品質審査）。
AI経由参照は chatgpt.com・chat.openai.com・perplexity.ai・gemini.google.com・copilot.microsoft.com・claude.ai からの参照流入の合計。
エリア到達はLP各セクションが画面内に40%表示された時点で発火する独自イベントにもとづきます。数値は月初〜月末の集計です。</p>
</div>

<!-- ページ10: 裏表紙 -->
<div class="sheet back-cover">
  {logo_b64}
  <div class="l">AI集客ラボ｜セブンセンシズ株式会社</div>
  <div class="s">〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902<br>
  TEL 06-4305-7547（9:00〜20:00 / 土日祝休）<br>
  https://ai.7senses.co.jp ｜ https://www.7senses.co.jp<br><br>
  本レポートに関するご質問・追加分析のご要望はお気軽にお申し付けください。<br>
  次号は翌月1日に自動発行されます。</div>
</div>
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

    # 来月号で達成率を突合するため、設定した目標を翌月のキーで保存する
    if not DEMO:
        y, mo = map(int, ym.split("-"))
        next_ym = f"{y + (mo == 12)}-{(mo % 12) + 1:02d}"
        tf = ROOT / "reports" / "targets.json"
        store = {}
        if tf.exists():
            try:
                store = json.loads(tf.read_text(encoding="utf-8"))
            except Exception:
                store = {}
        store[next_ym] = a["target_nums"]
        tf.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"来月({next_ym})の目標を保存しました: {tf.name}")

    from playwright.sync_api import sync_playwright

    import pdf_util
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(html_path.as_uri())
        pg.wait_for_timeout(400)
        pdf_util.check_overflow(pg, "月次レポート")
        pg.pdf(path=str(pdf_path), format="A4", print_background=True,
               display_header_footer=True,
               header_template="<span></span>",
               footer_template=(
                   '<div style="width:100%;font-size:7px;color:#8ba0bd;'
                   'padding:0 12mm;display:flex;justify-content:space-between;">'
                   '<span>AI集客ラボ 月次コンサルティングレポート ｜ セブンセンシズ株式会社</span>'
                   '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'),
               margin={"top": "0", "bottom": "10mm", "left": "0", "right": "0"})
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
                                              "Content-Type": "application/json",
                                              # CloudflareがデフォルトUAを遮断する（error 1010）ためUA必須
                                              "User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"})
        with urllib.request.urlopen(req) as res:
            print("メール送信:", res.status)


if __name__ == "__main__":
    main()
