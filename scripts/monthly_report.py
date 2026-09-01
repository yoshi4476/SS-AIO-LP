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
import re
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
        # BOM付きで保存された場合に1行目のキー名が壊れるため utf-8-sig で読む
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    return env


ENV = load_env()

# どのサイトのレポートかは引数で決める。既定は自前でビルドするサイト。
# ここにIDを直接書くと、別の会社では存在しないサイトのレポートを出そうとする。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as _sites_mod  # noqa: E402
SITE_ID = _sites_mod.primary()
if "--site" in sys.argv:
    SITE_ID = sys.argv[sys.argv.index("--site") + 1]


def site_cfg():
    import sites as _s
    return _s.load(SITE_ID)


def ga4_property():
    """GA4プロパティIDを数値だけに正規化する（GA4 APIは数値以外を受け付けない）"""
    raw = site_cfg().get("ga4_property_id") or ENV.get("GA4_PROPERTY_ID", "")
    # BOM・ゼロ幅文字・前後の空白を落とす（Secretsへの貼り付けで混入しやすい）
    v = "".join(c for c in raw if c.isdigit() or c.isalpha() or c in "-_/")
    v = v.removeprefix("properties/")
    if v.isdigit():
        return v
    # 値そのものはGitHub Actionsのログでマスクされるため、原因の切り分けに使える特徴だけを出す
    shape = ("空" if not v else
             "測定ID（G-で始まる）" if v.upper().startswith("G-") else
             "数字以外の文字を含む" if any(c.isalpha() for c in v) else
             "記号・空白を含む")
    raise SystemExit(
        f"GA4_PROPERTY_ID が数値ではありません（長さ{len(v)}文字・{shape}）\n"
        "  必要なのは9桁前後の数値のプロパティIDです（例: 547346579）。\n"
        "  GA4 → 左下の歯車（管理）→ プロパティ設定 → 右上の「プロパティ ID」で確認できます。\n"
        "  「G-」で始まる測定IDや「UA-」で始まる旧IDは使えません。\n"
        "  修正先: GitHub Secrets の GA4_PROPERTY_ID")


# ============================================================
# データ取得
# ============================================================
def month_labels(n=6):
    # 月初に前月分を発行する。当月は途中経過にしかならないため対象にしない。
    labels = []
    d = date.today().replace(day=1)
    for _ in range(n):
        d = (d - timedelta(days=1)).replace(day=1)
        labels.append(f"{d.year}-{d.month:02d}")
    return list(reversed(labels))


def renumber_sections(html):
    """セクション番号を振り直し、目次を本文から作り直す。

    ページを足したり分けたりするたびに手で番号を直すと、必ずどこかで
    重複する。実際に05・08・11が二重になり、目次は22件なのに本文は
    26件という状態だった。番号が飛び、目次と中身が食い違う資料は
    「作りが雑」に見え、中身まで疑われる。

    目次も手で並べていたため、ページを分けるたびにずれた。
    本文の見出しから作れば、二度とずれない。
    """
    n = [0]
    titles = []

    def bump(m):
        n[0] += 1
        return f'<span class="no">{n[0]:02d}</span>'

    # 番号と見出しを同時に拾う。「（続き 2/2）」は目次に出さない
    def collect(m):
        titles.append(re.sub(r"（続き[^）]*）", "", m.group(2)).strip())
        return m.group(0)

    html = re.sub(r'<span class="no">\d+</span>', bump, html)
    re.sub(r'<span class="no">(\d+)</span><h2>([^<]+)</h2>', collect, html)

    seen, items = set(), []
    for i, ti in enumerate(titles, 1):
        if ti in seen:
            continue        # 分割ページは1項目にまとめる
        seen.add(ti)
        items.append(f'<li><span>{i:02d}</span>{ti}</li>')
    return re.sub(r'<ul class="toc">.*?</ul>',
                  '<ul class="toc">' + "".join(items) + "</ul>",
                  html, count=1, flags=re.S)


def group_totals(sc_, cur_m):
    """3サイト全部の表示・クリックを取る。

    自サイトの数字だけ見ても、グループ全体で伸びているのか、
    他サイトから食い合って移っただけなのかが分からない。
    """
    try:
        import sites as _s
        out = []
        for sid, cfg in _s.load_all().items():
            try:
                r = sc_.searchanalytics().query(
                    siteUrl=f"https://{cfg['domain']}/",
                    body={"startDate": f"{cur_m}-01", "endDate": month_end(cur_m)}
                ).execute().get("rows", [])
            except Exception:
                out.append({"id": sid, "name": cfg["name"], "ok": False}); continue
            x = r[0] if r else {}
            out.append({"id": sid, "name": cfg["name"], "ok": True,
                        "imp": int(x.get("impressions", 0)),
                        "clicks": int(x.get("clicks", 0)),
                        "pos": round(x.get("position", 0), 1),
                        "ctr": round(x.get("ctr", 0) * 100, 2)})
        return out
    except Exception:
        return []


def group_table(rows, me):
    if not rows:
        return '<p class="note">3サイトの横断集計は取得できませんでした。</p>'
    ti = sum(r.get("imp", 0) for r in rows if r.get("ok"))
    tc = sum(r.get("clicks", 0) for r in rows if r.get("ok"))
    body = []
    for r in rows:
        mark = ' style="background:#f5f8ff"' if r["id"] == me else ""
        if not r.get("ok"):
            body.append(f'<tr{mark}><td>{r["name"]}</td>'
                        '<td colspan="4">権限付与待ち（取得できません）</td></tr>')
            continue
        share = r["imp"] / ti * 100 if ti else 0
        body.append(
            f'<tr{mark}><td>{r["name"]}{"（本レポート）" if r["id"] == me else ""}</td>'
            f'<td class="num">{r["imp"]:,}</td><td class="num">{r["clicks"]}</td>'
            f'<td class="num">{r["ctr"]}%</td><td class="num">{r["pos"]}位</td></tr>')
    body.append(f'<tr><td><b>合計</b></td><td class="num"><b>{ti:,}</b></td>'
                f'<td class="num"><b>{tc}</b></td><td class="num">—</td>'
                f'<td class="num">—</td></tr>')
    return ('<table><tr><th>サイト</th><th style="width:16%">表示回数</th>'
            '<th style="width:13%">クリック</th><th style="width:12%">クリック率</th>'
            '<th style="width:13%">平均順位</th></tr>' + "".join(body) + "</table>")


# 指標の言い換え。専門用語のままだと、読み手が巻末の用語集まで戻ることになり、
# 実際には戻らずに読み飛ばされる。その場で一言そえる。
PLAIN = {
    "セッション": "訪問した回数",
    "検索表示回数": "検索結果に出た回数",
    "検索クリック": "検索から来た回数",
    "平均CTR": "出たうち押された割合",
    "平均掲載順位": "検索での平均の順位",
    "CV（相談+資料DL）": "問い合わせ・資料請求の件数",
    "AI経由参照": "ChatGPTなどから来た回数",
    "当月公開記事": "今月出した記事",
    "公開記事ストック": "今までに出した記事の合計",
    "平均品質スコア": "記事の採点（100点満点）",
    "平均文字数": "記事1本あたりの長さ",
    "AI経由セッション（当月）": "ChatGPTなどから来た訪問",
    "AI経由の全体比": "全訪問のうちAI経由の割合",
    "実装済みAIO施策": "AI検索向けに入れている対策",
}


def plain(label):
    """指標名に、素人にも分かる一言を添える"""
    s = PLAIN.get(label)
    if not s:
        return label
    # ラベル自体に括弧があると「（相談+資料DL）（問い合わせ…）」と二重になる。
    # その場合は括弧の中身を説明で置き換える
    base = label.split("（")[0]
    return (f'{base}<span style="font-weight:normal;color:#8a94a6">'
            f'（{s}）</span>')


def section_heat(sections):
    """セクション到達のヒートマップ。先頭を100%として、どこで落ちたかを見る"""
    if not sections:
        return ('<p class="note">セクション到達は計測されていません。'
                '各セクションに <code>data-area</code> 属性を設置すると、'
                '翌月から離脱位置が特定できます。</p>')
    rows = []
    for s in sections[:16]:
        pct = s["pct"]
        col = "#0d9488" if pct >= 60 else ("#2563eb" if pct >= 30 else "#dc2626")
        flag = '<b style="color:#dc2626">離脱大</b>' if pct < 30 else ""
        rows.append(
            f'<tr><td>{s["name"]}</td><td class="num">{s["n"]}</td>'
            f'<td class="num">{pct}%</td>'
            f'<td><div style="background:{col};height:11px;width:{max(pct,2)}%;'
            f'border-radius:2px"></div></td><td>{flag}</td></tr>')
    return ('<table><tr><th style="width:22%">セクション</th><th style="width:12%">到達</th>'
            '<th style="width:10%">割合</th><th>到達率</th><th style="width:12%"></th></tr>'
            + "".join(rows) + "</table>")


def fix_list(d):
    """実測から改修点を出す。担当者の勘ではなく、数字が閾値を割った箇所だけ挙げる"""
    out = []
    b = d.get("behavior") or {}
    ss = b.get("sessions", 0)

    # 直帰が極端に高い入口。サイト平均から大きく外れたページだけ挙げる
    lands = [x for x in (d.get("landing") or []) if x["sessions"] >= 5]
    if lands:
        avg = sum(x["engagement"] for x in lands) / len(lands)
        for x in lands:
            if x["engagement"] < max(avg - 25, 15):
                out.append((
                    "最優先", f'入口 <code>{x["path"]}</code> の直帰が突出',
                    f'{x["sessions"]}セッション入って、エンゲージ率{x["engagement"]}%'
                    f'（サイト平均{avg:.0f}%）。ファーストビューで何のページか伝わっているか、'
                    f'流入元の話題とページの話題がつながっているかを確認します'))

    # CTAとフォームの落差。ただし「CTA」には診断・記事一覧など
    # フォームへ向かわないものが混ざる。全部を同じ扱いにすると、
    # 実際には起きていない詰まりを毎月報告することになる。
    cta, fs, fe = b.get("cta", 0), b.get("form_start", 0), b.get("form_submit", 0)
    to_form = b.get("cta_to_form", cta)   # フォームへ向かうCTAだけ
    if to_form >= 5 and fs <= max(to_form * 0.15, 1):
        out.append((
            "最優先", "問い合わせボタンは押されているが、入力が始まっていない",
            f'ボタン押下{to_form}回に対し入力開始{fs}件。押す意思はあるため、'
            f'ボタンの遷移先とフォームの位置を確認します'))
    elif cta >= 8 and to_form <= cta * 0.3:
        out.append((
            "高", "押されているボタンが、問い合わせにつながっていない",
            f'ボタン押下{cta}回のうち、問い合わせへ向かうものは{to_form}回。'
            f'診断や記事一覧など、途中で終わる導線に流れています。'
            f'問い合わせへの入口を増やします'))
    if fs >= 3 and fe == 0:
        out.append((
            "高", "フォームを開いた人が全員離脱している",
            f'開始{fs}件・送信{fe}件。項目数か必須指定を見直します'))

    # CTAが読まれる位置にあるか
    sec = d.get("sections") or []
    cta_sec = [s for s in sec if "cta" in s["name"] or "form" in s["name"]]
    if cta_sec:
        worst = min(cta_sec, key=lambda x: x["pct"])
        if worst["pct"] < 35:
            out.append((
                "高", "CTAがページの下すぎる位置にある",
                f'<code>{worst["name"]}</code> の到達率は{worst["pct"]}%。'
                f'到達率50%以上の位置にもCTAを置きます'))
    if len(sec) >= 12:
        thin = [s for s in sec if s["pct"] < 15]
        if len(thin) >= 4:
            out.append((
                "中", "セクションが多く、下部が読まれていない",
                f'{len(sec)}セクションのうち{len(thin)}個が到達率15%未満。'
                f'統合か削除を検討します'))
    if not sec:
        out.append((
            "高", "セクション到達が計測されていない",
            "各セクションに <code>data-area</code> 属性が未設置です。"
            "どこで離脱しているか分からないため、改修の根拠が作れません"))
    if not out:
        out.append(("—", "実測の閾値を割った箇所はありません",
                    "現状の導線に大きな詰まりは検出されていません"))
    return out


def fix_table(d):
    rows = []
    for pr, title, body in fix_list(d):
        cls = {"最優先": "jd-未達", "高": "jd-注意", "中": "jd-良好"}.get(pr, "jd-良好")
        rows.append(f'<tr><td><span class="jd {cls}">{pr}</span></td>'
                    f'<td><b>{title}</b></td><td>{body}</td></tr>')
    return ('<table><tr><th style="width:10%">優先</th>'
            '<th style="width:30%">見つかったこと</th><th>対処</th></tr>'
            + "".join(rows) + "</table>")


def month_end(label):
    """その月の末日。対象月が8月なら 2026-08-31 を返す。

    終了日を「今日」にすると、月初に発行したとき当月の数日分が混ざる。
    前月の報告に翌月のデータが入ると、数字が合わない理由が誰にも分からなくなる。
    """
    y, m = map(int, label.split("-"))
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


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

    import gcreds
    creds = gcreds.load(sa_path, [
        "https://www.googleapis.com/auth/analytics.readonly",
        "https://www.googleapis.com/auth/webmasters.readonly",
        "https://www.googleapis.com/auth/spreadsheets.readonly"])

    labels = month_labels(6)
    data = {"demo": False, "months": []}

    # --- GA4: 月別セッション/CV/AI参照 ---
    ga = BetaAnalyticsDataClient(credentials=creds)
    prop = f"properties/{ga4_property()}"
    for m in labels:
        y, mo = map(int, m.split("-"))
        # 当月はまだ月末が来ていない。未来日を渡すと期間が空になるため今日で止める
        end = min(date(y + (mo == 12), (mo % 12) + 1, 1) - timedelta(days=1),
                  date.today()).isoformat()
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
    # 参照元ドメインでしか見分けられないため、主要なAIサービスを網羅する。
    # 抜けているサービスからの流入は「Referral」に埋もれてAI流入として数えられない
    import daily_kpi as _dk
    ai_domains = tuple(d for v in _dk.AI_DOMAINS.values() for d in v)
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
    site = f'https://{site_cfg()["domain"]}/'
    for i, m in enumerate(labels):
        y, mo = map(int, m.split("-"))
        # 当月はまだ月末が来ていない。未来日を渡すと期間が空になるため今日で止める
        end = min(date(y + (mo == 12), (mo % 12) + 1, 1) - timedelta(days=1),
                  date.today()).isoformat()
        res = sc.searchanalytics().query(siteUrl=site, body={
            "startDate": f"{m}-01", "endDate": end}).execute()
        r = (res.get("rows") or [{}])[0]
        data["months"][i].update({
            "clicks": int(r.get("clicks", 0)), "impressions": int(r.get("impressions", 0)),
            "ctr": round(r.get("ctr", 0) * 100, 2), "pos": round(r.get("position", 0), 1)})
    res = sc.searchanalytics().query(siteUrl=site, body={
        "startDate": f"{labels[-1]}-01", "endDate": month_end(labels[-1]),
        "dimensions": ["query"], "rowLimit": 10}).execute()
    data["queries"] = [{"q": r["keys"][0], "imp": int(r["impressions"]), "clicks": int(r["clicks"]),
                        "ctr": round(r["ctr"] * 100, 1), "pos": round(r["position"], 1)}
                       for r in res.get("rows", [])]

    # ページ別実績（当月・上位12）
    try:
        res = sc.searchanalytics().query(siteUrl=site, body={
            "startDate": f"{labels[-1]}-01", "endDate": month_end(labels[-1]),
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
            "startDate": f"{labels[-1]}-01", "endDate": month_end(labels[-1]),
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

    cur_m = labels[-1]
    cur_range = [DateRange(start_date=f"{cur_m}-01", end_date="today")]
    prev_m = labels[-2]
    prev_end = (date(int(prev_m[:4]) + (int(prev_m[5:]) == 12),
                     (int(prev_m[5:]) % 12) + 1, 1) - timedelta(days=1)).isoformat()

    # --- ユーザーの質（滞在・回遊・新規率）。記事改修の判断材料になる ---
    def quality(rng):
        try:
            rep = ga.run_report(RunReportRequest(property=prop, date_ranges=rng, metrics=[
                Metric(name="engagementRate"), Metric(name="averageSessionDuration"),
                Metric(name="screenPageViewsPerSession"), Metric(name="newUsers"),
                Metric(name="totalUsers"), Metric(name="bounceRate")]))
            r = rep.rows[0].metric_values if rep.rows else None
            if not r:
                return {}
            users = float(r[4].value) or 1
            return {"engagement": round(float(r[0].value) * 100, 1),
                    "duration": round(float(r[1].value)),
                    "pv_per_session": round(float(r[2].value), 2),
                    "new_ratio": round(float(r[3].value) / users * 100),
                    "bounce": round(float(r[5].value) * 100, 1)}
        except Exception:
            return {}
    data["quality"] = quality(cur_range)
    data["quality_prev"] = quality([DateRange(start_date=f"{prev_m}-01", end_date=prev_end)])

    # --- ランディングページ別（どの記事が入口になり、質はどうか）---
    try:
        rep = ga.run_report(RunReportRequest(
            property=prop, date_ranges=cur_range,
            dimensions=[Dimension(name="landingPage")],
            metrics=[Metric(name="sessions"), Metric(name="engagementRate"),
                     Metric(name="conversions"), Metric(name="averageSessionDuration")],
            limit=12))
        data["landing"] = [{
            "path": r.dimension_values[0].value or "/",
            "sessions": int(r.metric_values[0].value),
            "engagement": round(float(r.metric_values[1].value) * 100, 1),
            "cv": int(float(r.metric_values[2].value)),
            "duration": round(float(r.metric_values[3].value)),
        } for r in rep.rows]
        data["landing"].sort(key=lambda x: -x["sessions"])
    except Exception:
        data["landing"] = []

    # --- 地域別（商圏の把握。MEO施策の裏づけになる）---
    try:
        rep = ga.run_report(RunReportRequest(
            property=prop, date_ranges=cur_range, dimensions=[Dimension(name="city")],
            metrics=[Metric(name="sessions")], limit=8))
        data["cities"] = [(r.dimension_values[0].value or "(不明)",
                           int(r.metric_values[0].value)) for r in rep.rows]
    except Exception:
        data["cities"] = []

    # --- イベント別（CTAクリック等の行動量）---
    try:
        rep = ga.run_report(RunReportRequest(
            property=prop, date_ranges=cur_range, dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")], limit=10))
        skip = {"page_view", "session_start", "first_visit", "user_engagement", "scroll"}
        data["events"] = [(r.dimension_values[0].value, int(r.metric_values[0].value))
                          for r in rep.rows if r.dimension_values[0].value not in skip][:6]
    except Exception:
        data["events"] = []

    # --- 3サイト横断の表示・クリック ---
    try:
        data["group"] = group_totals(sc, cur_m)
    except Exception:
        data["group"] = []

    # --- GA4: セクション到達（ヒートマップ）と行動の内訳 ---
    # どこで読者が離脱したかは、合計の滞在時間では分からない。
    # section_view_<名前> の到達数を先頭比で見ると、落ちる位置が特定できる。
    try:
        rep = ga.run_report(RunReportRequest(
            property=prop, date_ranges=cur_range, dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")], limit=120))
        ev = {r.dimension_values[0].value: int(r.metric_values[0].value) for r in rep.rows}
        sec = {k.replace("section_view_", ""): v for k, v in ev.items()
               if k.startswith("section_view_")}
        base = max(sec.values()) if sec else 0
        data["sections"] = sorted(
            [{"name": k, "n": v, "pct": round(v / base * 100) if base else 0}
             for k, v in sec.items()], key=lambda x: -x["n"])
        # フォームへ向かうCTAだけを別に数える。診断・記事一覧・
        # ヘッダーのリンクを同じ「CTA」に混ぜると、詰まりを誤検知する
        FORM_CTA = ("form", "contact", "soudan", "consult", "lp", "mv")
        data["behavior"] = {
            "sessions": ev.get("session_start", 0),
            "cta": sum(v for k, v in ev.items() if k.startswith("cta")),
            "cta_to_form": sum(v for k, v in ev.items()
                               if k.startswith("cta")
                               and any(w in k for w in FORM_CTA)),
            "form_start": ev.get("form_start", 0),
            "form_submit": ev.get("form_submit", 0),
        }
    except Exception:
        data["sections"] = []
        data["behavior"] = {}

    # --- GSC: 順位帯の分布（リライト対象がどれだけ眠っているかの可視化）---
    try:
        res = sc.searchanalytics().query(siteUrl=site, body={
            "startDate": f"{cur_m}-01", "endDate": month_end(cur_m),
            "dimensions": ["query"], "rowLimit": 1000}).execute()
        buckets = {"1〜3位": 0, "4〜10位": 0, "11〜20位": 0, "21〜50位": 0, "51位以下": 0}
        bucket_imp = dict.fromkeys(buckets, 0)
        for r in res.get("rows", []):
            p, imp = r["position"], int(r["impressions"])
            k = ("1〜3位" if p <= 3 else "4〜10位" if p <= 10 else
                 "11〜20位" if p <= 20 else "21〜50位" if p <= 50 else "51位以下")
            buckets[k] += 1
            bucket_imp[k] += imp
        data["rank_buckets"] = [(k, v) for k, v in buckets.items()]
        data["rank_imp"] = bucket_imp
        # 11〜20位で表示回数の多いもの＝リライトの最優先候補
        data["rewrite_targets"] = sorted(
            [{"q": r["keys"][0], "imp": int(r["impressions"]), "clicks": int(r["clicks"]),
              "pos": round(r["position"], 1)}
             for r in res.get("rows", []) if 10 < r["position"] <= 20],
            key=lambda x: -x["imp"])[:8]
    except Exception:
        data["rank_buckets"], data["rank_imp"], data["rewrite_targets"] = [], {}, []

    # --- GSC: デバイス別（スマホとPCで順位・CTRが違うことがある）---
    try:
        res = sc.searchanalytics().query(siteUrl=site, body={
            "startDate": f"{cur_m}-01", "endDate": month_end(cur_m),
            "dimensions": ["device"]}).execute()
        jp = {"MOBILE": "スマートフォン", "DESKTOP": "PC", "TABLET": "タブレット"}
        data["gsc_devices"] = [{
            "d": jp.get(r["keys"][0], r["keys"][0]), "imp": int(r["impressions"]),
            "clicks": int(r["clicks"]), "ctr": round(r["ctr"] * 100, 2),
            "pos": round(r["position"], 1)} for r in res.get("rows", [])]
    except Exception:
        data["gsc_devices"] = []

    # --- スプレッドシート: 記事作成ログ ---
    try:
        sh = build("sheets", "v4", credentials=creds)
        vals = sh.spreadsheets().values().get(
            spreadsheetId=ENV["SPREADSHEET_ID"], range="記事作成ログ!A2:L200").execute().get("values", [])
        # 記事作成ログの列: 0=公開日時 1=サイト 2=タイトル 3=キーワード
        #                  4=カテゴリ 5=スコア 6=文字数 7=URL 8=備考
        # 日付は0列目。1列目（サイト名）を日付として見ていたため、
        # 常に0件になり「新規公開記事 0本」と報告していた。
        cur = labels[-1].replace("-", "/")
        # 台帳のサイト表記は「AI導入補助金 (lp.7senses.co.jp)」のような形で、
        # 設定側の name（AI導入補助金サポート）と一致しない。
        # 名前で照合すると常に0件になるため、ドメインで照合する。
        # 旧ドメインで記録された行もあるので、URL側も見る。
        dom = site_cfg().get("domain", "")
        rows = []
        for v in vals:
            v = list(v) + [""] * (9 - len(v))
            if not str(v[0]).startswith((labels[-1], cur)):
                continue
            if dom and dom not in str(v[1]) and dom not in str(v[7]):
                continue
            rows.append(v)
        data["content"] = {
            # URLが入っていれば公開済み。備考は「既存記事の同期」等が入り、
            # 「公開」の文字で判定すると取りこぼす
            "published": len([v for v in rows if str(v[7]).startswith("http")]),
            "rows": [{"date": v[0], "title": v[2][:30], "score": v[5] or "-",
                      "status": "公開済み" if str(v[7]).startswith("http") else "-"}
                     for v in rows[:15]],
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
        "quality": {"engagement": 58.4, "duration": 142, "pv_per_session": 1.86,
                    "new_ratio": 74, "bounce": 41.6},
        "quality_prev": {"engagement": 54.1, "duration": 128, "pv_per_session": 1.71,
                         "new_ratio": 78, "bounce": 45.9},
        "landing": [
            {"path": "/aio/aio-taisaku-guide/", "sessions": 410, "engagement": 64.2, "cv": 5, "duration": 188},
            {"path": "/aio/llmo-taisaku-hoho/", "sessions": 360, "engagement": 61.8, "cv": 4, "duration": 175},
            {"path": "/meo/meo-taisaku-yarikata/", "sessions": 250, "engagement": 48.3, "cv": 2, "duration": 121},
            {"path": "/meo/kuchikomi-fuyasu-hoho/", "sessions": 190, "engagement": 39.5, "cv": 1, "duration": 96},
            {"path": "/", "sessions": 170, "engagement": 71.4, "cv": 1, "duration": 204},
            {"path": "/ai-marketing/ai-shukyaku-guide/", "sessions": 140, "engagement": 35.1, "cv": 0, "duration": 84},
            {"path": "/lp/", "sessions": 90, "engagement": 66.7, "cv": 0, "duration": 158},
        ],
        "cities": [("Osaka", 620), ("Tokyo", 410), ("Nagoya", 150), ("Fukuoka", 120),
                   ("Sapporo", 90), ("(not set)", 330)],
        "events": [("cta_click", 214), ("form_start", 42), ("generate_lead", 13),
                   ("area_reach", 1860), ("file_download", 28)],
        "rank_buckets": [("1〜3位", 4), ("4〜10位", 18), ("11〜20位", 31),
                         ("21〜50位", 46), ("51位以下", 62)],
        "rank_imp": {"1〜3位": 3200, "4〜10位": 16800, "11〜20位": 14200,
                     "21〜50位": 8100, "51位以下": 2200},
        "rewrite_targets": [
            {"q": "クリニック meo", "imp": 2400, "clicks": 65, "pos": 12.3},
            {"q": "工務店 集客", "imp": 2100, "clicks": 44, "pos": 14.6},
            {"q": "meo 対策 費用", "imp": 1700, "clicks": 31, "pos": 13.1},
            {"q": "aio 対策 会社", "imp": 1500, "clicks": 26, "pos": 16.2},
            {"q": "llmo 事例", "imp": 1200, "clicks": 19, "pos": 18.4},
        ],
        "gsc_devices": [
            {"d": "スマートフォン", "imp": 27600, "clicks": 540, "ctr": 1.96, "pos": 10.8},
            {"d": "PC", "imp": 15100, "clicks": 385, "ctr": 2.55, "pos": 8.2},
            {"d": "タブレット", "imp": 1800, "clicks": 35, "ctr": 1.94, "pos": 11.4},
        ],
    }


# ============================================================
# サイト全体監査（記事別・ページ別の具体的な修正指示を自動生成）
# ============================================================
def audit_site(d):
    import sites as _sites
    _dom = _sites.load(SITE_ID)["domain"]
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

        # articles/ には3サイト分の原稿が入っている。絞らないと3サイトとも
        # 「全123記事を監査」と同じ数字になり、他サイトの記事に対する
        # 修正指示が並んでしまう。
        if _sites.find_category_owner(fv("category")) != SITE_ID:
            continue
        arts.append({
            "slug": p.stem, "title": fv("title"), "cat": fv("category"),
            "date": fv("dateModified") or fv("date"),
            "links": len(_re.findall(r"\]\(/[a-z-]+/[a-z0-9-]+/\)", body))
            + len(_re.findall(rf"\]\(https?://{_re.escape(_dom)}/[a-z-]+/[a-z0-9-]+/\)",
                              body)),
            "faq": len(_re.findall(r"<details><summary>", body)),
            "len": len(_re.sub(r"\s", "", body)),
        })

    by_cat = {}
    for x in arts:
        by_cat.setdefault(x["cat"], []).append(x)
    pages = {p["path"]: p for p in d.get("pages", [])}

    art_rows, keep = [], []
    for x in arts:
        path = _re.sub(r"^https?://[^/]+", "", _sites.article_url(
            _sites.load(SITE_ID), {"slug": x["slug"], "category": x["cat"],
                                   "date": x["date"]}))
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


def inbound_plan(d):
    """被リンクの追加指示（実装は inbound_links.py。グループレポートと共用する）"""
    import inbound_links
    pages = {p["path"]: p for p in d.get("pages", [])}
    return inbound_links.plan(pages, SITE_ID)


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
    # 本レポートはAI集客ラボ単体の報告。articles/ には3サイト分の原稿が入っているため、
    # 絞らないと他サイトの記事まで「当サイトの資産」として数えてしまう（38本と誤報していた）。
    import sites as _sites
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = _re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, _re.S)
        if not m:
            continue
        fm, body = m.groups()
        _cm = _re.search(r"^category:\s*(\S+)", fm, _re.M)
        if _cm and _sites.find_category_owner(_cm.group(1)) != SITE_ID:
            continue
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
    import sites as _sm
    tf = ROOT / "reports" / ("targets.json" if SITE_ID == _sm.primary()
                            else f"targets-{SITE_ID}.json")
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
        # クリックが0だと「約0円」が並び、集計が壊れているように見える。
        # 実際は公開初月でクリックがまだ発生していないだけなのでそう書く
        "yen": (lambda v: f"約{v:,}円") if ad_value > 0 else (lambda v: "算出前"),
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
        f'CV{cur.get("cv", 0)}件（{mom("cv")}）。'
        + (f'広告で同じクリックを買うと約{ad_value:,}円相当の流入を、記事の資産で獲得しています。'
           if ad_value > 0 else
           '広告換算は当月の検索クリックが0回のため算出前です。表示回数は出ているため、順位が上がり次第この欄に金額が入ります。'),
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

    # ── オウンドメディアの改修プラン（ランディングページの質から導く）──
    media_plan = []
    land = d.get("landing", [])
    for lp_ in [x for x in land if x["sessions"] >= 50 and x["engagement"] < 45][:4]:
        media_plan.append({
            "target": lp_["path"], "kind": "記事の冒頭と構成",
            "now": f'流入{lp_["sessions"]}・エンゲージメント{lp_["engagement"]}%'
                   f'・滞在{lp_["duration"]}秒（読まれずに離脱している）',
            "fix": "冒頭200字の結論を、検索意図により近い言い切りに書き換える。"
                   "『この記事でわかること』を最初の画面に収め、目次を上部へ移動する。"
                   "見出し直下の1文結論が抜けている箇所を補う",
        })
    for lp_ in [x for x in land if x["sessions"] >= 100 and x["cv"] == 0][:3]:
        media_plan.append({
            "target": lp_["path"], "kind": "記事内の導線",
            "now": f'流入{lp_["sessions"]}に対しCV 0件（読まれても次に進んでいない）',
            "fix": "本文中盤のCTAを、その記事の悩みに合わせた文言へ変更する。"
                   "関連記事のリンクを本文の文脈内へ移し、記事末尾のCTAをLPの該当セクションへ直接送る",
        })
    for t in d.get("rewrite_targets", [])[:4]:
        media_plan.append({
            "target": f'「{t["q"]}」の記事', "kind": "本文の加筆（リライト）",
            "now": f'{t["pos"]}位・表示{t["imp"]:,}回（1ページ目まであと少し）',
            "fix": "上位3記事にあって自記事にない見出しを1〜2本追加する。"
                   "出典付きの数値を1つ足し、同カテゴリの記事から内部リンクを2本追加する",
        })
    thin_cat = [c for c, n in assets["cats"] if n <= 2]
    if thin_cat:
        media_plan.append({
            "target": f'カテゴリ「{"、".join(thin_cat[:2])}」', "kind": "カテゴリ構成",
            "now": f'記事{2}本以下でクラスターが薄い（テーマの専門性が伝わらない）',
            "fix": "このカテゴリのキーワードを次月の記事配分で優先し、5本以上にする。"
                   "揃った時点でまとめ記事（ピラー）を作り、各記事から相互リンクする",
        })
    if not media_plan:
        media_plan.append({"target": "サイト全体", "kind": "—",
                           "now": "改修が必要な水準の指標は検出されていません",
                           "fix": "現在の構成を維持し、上位記事の型を新規記事へ横展開する"})

    # ── LPの改修プラン（到達率・デバイス・流入元から導く）──
    lp_plan = []
    areas = d.get("areas") or []
    if areas:
        drops = sorted([(areas[i], areas[i + 1], areas[i]["reach"] - areas[i + 1]["reach"])
                        for i in range(len(areas) - 1)], key=lambda x: -x[2])
        for a1, a2, gap in drops[:3]:
            lp_plan.append({
                "target": f'「{a1["name"]}」→「{a2["name"]}」', "kind": "離脱の止血",
                "now": f'到達率が{a1["reach"]}%→{a2["reach"]}%（{gap}pt低下）',
                "fix": f'「{a1["name"]}」の末尾に次を読ませる橋渡し文を追加し、'
                       f'「{a2["name"]}」の見出しを「何が得られるか」を書いた利益訴求型に変更する',
            })
        form = next((x for x in areas if "フォーム" in x["name"]), None)
        if form and form["reach"] < 25:
            lp_plan.append({
                "target": "申込フォーム", "kind": "到達経路の短縮",
                "now": f'フォーム到達率{form["reach"]}%（最後まで読まれていない）',
                "fix": "ページ中腹（サービス紹介の直後と比較表の直後）にフォームへ飛ぶボタンを追加する。"
                       "入力項目を必須3つに絞り、送信ボタンの文言を『無料で相談する』へ変更する",
            })
    dv = d.get("devices", [])
    if dv:
        tot = sum(v for _, v in dv) or 1
        mob = next((v for k, v in dv if k == "mobile"), 0)
        if mob / tot >= 0.55:
            lp_plan.append({
                "target": "スマートフォン表示", "kind": "ファーストビュー",
                "now": f"スマホ比率{round(mob / tot * 100)}%（主戦場はスマホ）",
                "fix": "スマホでの最初の画面に『何の会社か・誰向けか・次に何をするか』を収める。"
                       "見出しの文字数を1行に収まる長さへ調整し、CTAボタンを親指が届く位置に固定する",
            })
    gd = d.get("gsc_devices", [])
    if len(gd) >= 2:
        m = next((x for x in gd if "スマート" in x["d"]), None)
        p_ = next((x for x in gd if x["d"] == "PC"), None)
        if m and p_ and m["ctr"] < p_["ctr"] * 0.85:
            lp_plan.append({
                "target": "検索結果での見え方（スマホ）", "kind": "タイトル・説明文",
                "now": f'スマホCTR {m["ctr"]}% に対しPC {p_["ctr"]}%（スマホで選ばれにくい）',
                "fix": "タイトルを前半28文字で意味が通るよう組み直す。"
                       "スマホの検索結果は表示幅が狭く、後半が切れて訴求が届いていない",
            })
    ch = d.get("channels", [])
    if ch:
        tot = sum(v for _, v in ch) or 1
        org = next((v for k, v in ch if "Organic Search" in k), 0)
        if org / tot < 0.5:
            lp_plan.append({
                "target": "流入構造", "kind": "チャネル",
                "now": f"自然検索が{round(org / tot * 100)}%（検索以外への依存が大きい）",
                "fix": "記事の公開ペースを維持しつつ、インデックス登録状況を確認する。"
                       "直接流入が多い場合は、社名検索の受け皿ページを整備する",
            })
    if not lp_plan:
        lp_plan.append({"target": "LP全体", "kind": "—",
                        "now": "計測データが不足しているか、改修が必要な水準の指標がありません",
                        "fix": "GA4のセクション到達イベントの接続を確認する"})

    return {"grown": grown, "fixes": fixes, "actions": actions, "mom": mom,
            "winners": winners, "challengers": challengers, "summary": summary,
            "assets": assets, "targets": targets, "audit": audit_site(d),
            "target_nums": target_nums, "achievement": achievement, "assess": assess,
            "efficiency": efficiency, "headline": headline, "risks": risks,
            "media_plan": media_plan, "lp_plan": lp_plan, "inbound": inbound_plan(d)}


# ============================================================
# 描画（SVGチャート / ヒートマップ / HTML）
# ============================================================
def svg_line(months, key, color, title, unit=""):
    vals = [m.get(key, 0) or 0 for m in months]
    if not any(vals):
        return f'<p style="color:{MUTED}">データなし</p>'
    W, H, PL, PB = 560, 270, 46, 32
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
    cur = labels[-1]
    ym = cur["label"]
    demo_banner = ('<div class="demo-banner">SAMPLE ― 本レポートはサンプルデータです。'
                   'GA4/GSC接続後、実データで自動発行されます。</div>') if d["demo"] else ""

    # 表紙ロゴ（白版）をbase64で埋め込み
    logo_b64 = ""
    lp = ROOT / "site" / "images" / "company" / "logo-white.png"
    if lp.exists():
        logo_b64 = f'<img class="cv-logo" src="data:image/png;base64,{base64.b64encode(lp.read_bytes()).decode()}">'

    def tile_q(label, value, sub):
        """値を直接渡すタイル（前月差つきの文字列をそのまま表示する）"""
        return (f'<div class="tile"><div class="t-label">{plain(label)}</div>'
                f'<div class="t-val" style="font-size:14pt">{value}</div>'
                f'<div class="t-mom" style="color:{MUTED};font-weight:normal">{sub}</div></div>')

    def tile(label, key, unit=""):
        v = cur.get(key, 0)
        series = [m.get(key, 0) or 0 for m in labels]
        mom = a["mom"](key)
        up = not mom.startswith("-")
        good = (not up) if key == "pos" else up  # 順位は下がる=良い
        return (f'<div class="tile"><div class="t-label">{plain(label)}</div>'
                f'<div class="t-val">{v:,}{unit}</div>'
                f'<div class="t-mom {"good" if good else "bad"}">前月比 {mom}</div>'
                f'<div class="t-spark">{svg_spark(series, BLUE if key != "pos" else TEAL)}</div></div>')

    qrows = "".join(f'<tr><td>{q["q"]}</td><td class="num">{q["imp"]:,}</td><td class="num">{q["clicks"]:,}</td>'
                    f'<td class="num">{q["ctr"]}%</td><td class="num">{q["pos"]}位</td></tr>'
                    for q in d.get("queries", [])[:8])
    # ページ別実績は件数が読めない。1ページに詰めると溢れるため、
    # 件数を削らずに続きページへ流す（削ると「上位だけの報告」になり判断を誤らせる）
    PAGE_PER_SHEET = 6

    def _prow(p):
        return (f'<tr><td style="word-break:break-all">{p["path"]}</td><td class="num">{p["imp"]:,}</td>'
                f'<td class="num">{p["clicks"]:,}</td><td class="num">{p["ctr"]}%</td>'
                f'<td class="num">{p["pos"]}位</td></tr>')

    _pages = d.get("pages", [])
    _chunks = [_pages[i:i + PAGE_PER_SHEET] for i in range(0, len(_pages), PAGE_PER_SHEET)] or [[]]
    prows = "".join(_prow(x) for x in _chunks[0])         or '<tr><td colspan="5">当月のページ別データはまだありません</td></tr>'
    pages_extra = ""
    for _n, _chunk in enumerate(_chunks[1:], 2):
        pages_extra += f"""
<div class="sheet">
<div class="sec"><span class="no">05</span><h2>記事別パフォーマンス（続き {_n}/{len(_chunks)}）</h2><div class="gold"></div></div>
<h3 style="margin-top:0">ページ別実績（続き・表示回数順）</h3>
<table><tr><th>ページ</th><th>表示回数</th><th>クリック</th><th>クリック率</th><th>平均順位</th></tr>
{"".join(_prow(x) for x in _chunk)}</table>
</div>"""
    trows = "".join(f'<tr><td>{k}</td><td class="num">{now}</td><td class="num" style="color:#067647;font-weight:bold">{tv}</td><td>{why}</td></tr>'
                    for k, now, tv, why in a["targets"])
    audit = a["audit"]
    # 監査結果は情報量が命なので、削らずにページを分けて全件掲載する
    ART_PER_PAGE = 4   # 1行が2〜3行に折り返すため、5行でも溢れた

    def _art_row(r):
        return (f'<tr><td>{r["art"]}</td><td style="white-space:nowrap">{r["where"]}</td>'
                f'<td>{r["now"]}</td><td>{r["change"]}</td></tr>')

    art_pages = [audit["articles"][i:i + ART_PER_PAGE]
                 for i in range(0, len(audit["articles"]), ART_PER_PAGE)] or [[]]
    audit_art_rows = "".join(_art_row(r) for r in art_pages[0]) \
        or '<tr><td colspan="4">全記事が基準を満たしています（修正指示なし）</td></tr>'
    # 2ページ目以降（記事が多い月だけ増える）
    audit_art_extra = ""
    for n, chunk in enumerate(art_pages[1:], 2):
        audit_art_extra += f"""
<div class="sheet">
<div class="sec"><span class="no">16</span><h2>サイト全体監査（続き {n}/{len(art_pages)}）</h2><div class="gold"></div></div>
<h3 style="margin-top:0">ブログ記事の修正指示（続き）</h3>
<table><tr><th style="width:22%">記事</th><th style="width:14%">修正箇所</th>
<th style="width:28%">現状（実測）</th><th>変更内容</th></tr>
{"".join(_art_row(r) for r in chunk)}</table>
</div>"""
    audit_site_rows = "".join(
        f'<tr><td>{r["target"]}</td><td style="white-space:nowrap">{r["where"]}</td><td>{r["now"]}</td><td>{r["change"]}</td></tr>'
        for r in audit["site"]) or '<tr><td colspan="4">構造上の修正指示はありません</td></tr>'
    # ページ溢れを防ぐため件数を絞り、2カラムで表示する
    audit_keep = "".join(f'<li>{k}</li>' for k in audit["keep"][:8]) \
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

    # ── 追加分析の描画データ ──
    q, qp = d.get("quality", {}), d.get("quality_prev", {})

    def qd(key, unit="", better_high=True):
        """当月値と前月差を「58.4%（+4.3pt）」の形にする"""
        v, p = q.get(key), qp.get(key)
        if v is None:
            return "—"
        if p is None:
            return f"{v}{unit}"
        diff = round(v - p, 1)
        sign = "+" if diff >= 0 else ""
        good = (diff >= 0) if better_high else (diff <= 0)
        cls = "good" if good else "bad"
        return f'{v}{unit} <span class="{cls}" style="font-size:8.4pt">（{sign}{diff}）</span>'

    land_rows = "".join(
        f'<tr><td style="word-break:break-all">{x["path"]}</td>'
        f'<td class="num">{x["sessions"]:,}</td>'
        f'<td class="num">{x["engagement"]}%</td>'
        f'<td class="num">{x["duration"]}秒</td>'
        f'<td class="num">{x["cv"]}</td>'
        f'<td><span class="jd jd-{"良好" if x["engagement"] >= 55 else ("標準" if x["engagement"] >= 45 else "要改善")}">'
        f'{"良好" if x["engagement"] >= 55 else ("標準" if x["engagement"] >= 45 else "要改善")}</span></td></tr>'
        for x in d.get("landing", [])[:10]) or '<tr><td colspan="6">GA4接続後に表示されます</td></tr>'

    rank_rows = ""
    rimp = d.get("rank_imp", {})
    for k, n in d.get("rank_buckets", []):
        imp = rimp.get(k, 0)
        note = {"1〜3位": "維持する。この型を新規記事へ横展開",
                "4〜10位": "1ページ目。CTR改善で伸ばす",
                "11〜20位": "最優先のリライト対象。伸びしろが最大",
                "21〜50位": "内容の追加が必要。中期の改善対象",
                "51位以下": "検索意図とのズレを疑う。統合も検討"}.get(k, "")
        rank_rows += (f'<tr><td><b>{k}</b></td><td class="num">{n}</td>'
                      f'<td class="num">{imp:,}</td><td>{note}</td></tr>')
    rank_rows = rank_rows or '<tr><td colspan="4">Search Console接続後に表示されます</td></tr>'

    rewrite_rows = "".join(
        f'<tr><td>{t["q"]}</td><td class="num">{t["pos"]}位</td>'
        f'<td class="num">{t["imp"]:,}</td><td class="num">{t["clicks"]}</td>'
        f'<td class="num">{round(t["imp"] * 0.04 - t["clicks"])}</td></tr>'
        for t in d.get("rewrite_targets", [])[:6]) \
        or '<tr><td colspan="5">該当なし</td></tr>'

    gdev_rows = "".join(
        f'<tr><td>{x["d"]}</td><td class="num">{x["imp"]:,}</td><td class="num">{x["clicks"]:,}</td>'
        f'<td class="num">{x["ctr"]}%</td><td class="num">{x["pos"]}位</td></tr>'
        for x in d.get("gsc_devices", [])) or '<tr><td colspan="5">Search Console接続後に表示されます</td></tr>'

    ev_rows = "".join(f'<tr><td>{n}</td><td class="num">{v:,}</td></tr>'
                      for n, v in d.get("events", [])) \
        or '<tr><td colspan="2">GA4接続後に表示されます</td></tr>'

    def _media_row(x):
        return (f'<tr><td style="word-break:break-all">{x["target"]}</td>'
                f'<td style="white-space:nowrap">{x["kind"]}</td>'
                f'<td>{x["now"]}</td><td>{x["fix"]}</td></tr>')

    # 1ページ7件まで。あふれが3件以下なら次章の冒頭へ回し、薄いページを作らない
    MEDIA_PER_PAGE = 7
    mp = a["media_plan"]
    media_rows = "".join(_media_row(x) for x in mp[:MEDIA_PER_PAGE])
    rest_mp = mp[MEDIA_PER_PAGE:]
    media_extra, media_carry = "", ""
    if 0 < len(rest_mp) <= 2:
        media_carry = f"""<h3 style="margin-top:0">オウンドメディア改修プラン（続き）</h3>
<table><tr><th style="width:20%">対象</th><th style="width:14%">改修の種類</th>
<th style="width:28%">現状（実測）</th><th>変更内容</th></tr>
{"".join(_media_row(x) for x in rest_mp)}</table>
<h3>LPの改修プラン</h3>"""
    elif rest_mp:
        for n_, i in enumerate(range(MEDIA_PER_PAGE, len(mp), MEDIA_PER_PAGE), 2):
            media_extra += f"""
<div class="sheet">
<div class="sec"><span class="no">11</span><h2>オウンドメディアの改修プラン（続き {n_}）</h2><div class="gold"></div></div>
<table><tr><th style="width:20%">対象</th><th style="width:14%">改修の種類</th>
<th style="width:28%">現状（実測）</th><th>変更内容</th></tr>
{"".join(_media_row(x) for x in mp[i:i + MEDIA_PER_PAGE])}</table>
</div>"""
    # 被リンクの追加指示（月初のサイト改修でそのまま作業できる粒度で出す）
    ib = a["inbound"]

    def _ib_row(r):
        return (f'<tr><td><b>{r["to"][:26]}</b><br><span class="mono">{r["to_url"]}</span></td>'
                f'<td class="num">{r["inbound"]}本</td><td>{r["why"]}</td>'
                f'<td>{"／".join(t[:20] for t, _ in r["froms"])}</td></tr>')

    IB_PER_PAGE = 7
    inbound_rows = "".join(_ib_row(r) for r in ib["rows"][:IB_PER_PAGE])
    if not inbound_rows:
        inbound_rows = ('<tr><td colspan="4">追加すべき被リンクはありません'
                        '（全記事が基準を満たしています）</td></tr>')
    inbound_extra = ""
    for n_, i in enumerate(range(IB_PER_PAGE, len(ib["rows"]), IB_PER_PAGE), 2):
        inbound_extra += f"""
<div class="sheet">
<div class="sec"><span class="no">11</span><h2>被リンクを送るべき記事（続き {n_}）</h2><div class="gold"></div></div>
<table><tr><th style="width:26%">リンク先（この記事へ送る）</th><th style="width:9%">現在</th>
<th style="width:26%">優先する理由</th><th>リンク元にする記事</th></tr>
{"".join(_ib_row(r) for r in ib["rows"][i:i + IB_PER_PAGE])}</table>
</div>"""
    lpplan_rows = "".join(
        f'<tr><td>{x["target"]}</td><td style="white-space:nowrap">{x["kind"]}</td>'
        f'<td>{x["now"]}</td><td>{x["fix"]}</td></tr>' for x in a["lp_plan"])
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
        ("エンゲージメント率", "10秒以上の滞在・2ページ以上の閲覧・CVのいずれかが起きた訪問の割合"),
        ("1訪問あたりPV", "1回の訪問で何ページ見たか。関連記事への導線が効いているかを表す"),
        ("新規ユーザー比率", "初めて訪れた人の割合。下がるほどリピーターが育っている"),
        ("順位帯", "検索順位を1〜3位・4〜10位・11〜20位などに区切った分類。11〜20位が最も改善効果が大きい"),
        ("入口ページ", "訪問者が最初に開いたページ。どの記事が集客の入口になっているかが分かる"),
        ("到達率", "LPの各セクションが画面に表示された訪問の割合。どこで離脱したかが分かる"),
        ("広告換算額", "同じ流入を広告で購入した場合の金額。記事の資産価値を示す目安"),
        ("インデックス", "検索エンジンがページを認識し、検索結果に出せる状態にすること"),
        ("カニバリゼーション", "自社の記事同士が同じキーワードで競合し、互いの順位を下げ合う状態"),
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
        "流入構造分析（チャネル・デバイス・日別）", "チャネル別の打ち手",
        "AI検索（AIO/LLMO）分析",
        "読まれ方の質（エンゲージメント・滞在・回遊）",
        "入口ページ別の成績（改修の根拠）",
        "検索順位の分布（伸びしろの在り処）",
        "オウンドメディアの改修プラン",
        "LPの改修プラン",
        "LPコンバージョン分析（ファネル+ヒートマップ）", "成果の要因分析",
        "改善プラン（優先度つき対比表）",
        "サイト全体監査（記事別の修正指示）", "サイト全体監査（サイト構造・導線）",
        "コンテンツ実績", "1記事に含まれるもの",
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
/* 縦並びのflex内では既定で横に引き伸ばされるため、align-selfで実寸比率を保つ */
.cv-logo {{ height: 34px; width: auto; align-self: flex-start; flex: 0 0 auto; }}
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
.toc {{ columns: 3; column-gap: 16px; margin: 6px 0 0; }}
.toc li {{ list-style: none; padding: 0.9px 0; border-bottom: 1px dotted var(--line); font-size: 7.4pt; break-inside: avoid; }}
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
.mono {{ font-family: Consolas, "Courier New", monospace; font-size: 7.6pt; color: var(--muted); }}
tr:nth-child(even) td {{ background: #f7fafd; }}
.two-col {{ display: flex; gap: 12px; }}
.two-col > div {{ flex: 1; border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; }}
.two-col h3 {{ margin-top: 0; }}
.two-col ul {{ padding-left: 18px; font-size: 9pt; }}
.two-col li {{ margin: 6px 0; }}

/* ---- ヒートマップ・ファネル ---- */
.heatmap {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }}
.hm-row {{ display: flex; align-items: center; gap: 8px; margin: 2px 0; }}
.hm-label {{ width: 110px; font-size: 8.5pt; }}
.hm-track {{ flex: 1; background: #eef2f8; border-radius: 4px; height: 13px; }}
.hm-bar {{ height: 13px; border-radius: 4px; }}
.hm-val {{ width: 40px; text-align: right; font-size: 8.5pt; font-weight: bold; }}
.funnel {{ border: 1px solid var(--line); border-radius: 8px; padding: 9px 16px; }}
.fn-row {{ margin: 2px 0; }}
.fn-bar {{ background: linear-gradient(90deg, var(--navy), var(--blue)); color: #fff; border-radius: 6px;
  padding: 5px 12px; display: flex; justify-content: space-between; font-size: 9.5pt; min-width: 130px; }}
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
.mark {{ background: linear-gradient(transparent 58%, #ffe873 58%); font-weight: bold; }}
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
    対象メディア: <b>{site_cfg()["name"]}</b>（https://{site_cfg()["domain"]}）<br>
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
  <div class="hl"><div class="k">{plain("セッション")}</div><div class="v">{cur.get("sessions",0):,}</div><div class="s">前月比 {a["mom"]("sessions")}</div></div>
  <div class="hl"><div class="k">{plain("CV（相談+資料DL）")}</div><div class="v">{cur.get("cv",0)}件</div><div class="s">前月比 {a["mom"]("cv")}</div></div>
  <div class="hl"><div class="k">{plain("AI経由参照")}</div><div class="v">{ai_total}</div><div class="s">前月比 {ai_mom}</div></div>
  <div class="hl"><div class="k">{plain("当月公開記事")}</div><div class="v">{d["content"]["published"]}本</div><div class="s">品質90点以上のみ</div></div>
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
<h3>指標どうしの関係</h3>
<table>
<tr><th style="width:26%">上げたい結果</th><th style="width:26%">直接効く指標</th><th>動かす方法</th></tr>
<tr><td><b>クリック数を増やす</b></td><td>順位 と CTR</td>
<td>順位は本文の加筆と内部リンク、CTRはタイトルと説明文。CTRのほうが早く効きます</td></tr>
<tr><td><b>CVを増やす</b></td><td>CV率 と クリック数</td>
<td>CV率は記事内CTAとLPの導線。CV率が倍になれば成果も倍になります</td></tr>
<tr><td><b>AI検索で引用される</b></td><td>順位 と 構造</td>
<td>Googleで上位に入るのが前提。そのうえで結論の書き方とFAQ整備が効きます</td></tr>
</table>
<div class="callout"><b>「結果」ではなく「原因」を見る:</b> セッション数が下がったとき、
セッション数そのものを見ても打ち手は出てきません。順位が下がったのか、CTRが落ちたのか、
それとも季節要因かを切り分けて初めて、次の行動が決まります。
本レポートが原因側の指標を先に置いているのはそのためです。</div>
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
<table><tr><th>クエリ</th><th>表示回数</th><th>クリック</th><th>クリック率</th><th>平均順位</th></tr>{qrows}</table>
<div class="two-col" style="margin-top:14px">
  <div><h3>🏅 勝ちクエリ（横展開する）</h3><ul>{winner_rows}</ul></div>
  <div><h3>🎯 テコ入れクエリ（リライト対象）</h3><ul>{challenger_rows}</ul></div>
</div>
<h3 style="margin-top:14px">クエリの読み解き方</h3>
<table>
<tr><th style="width:24%">状態</th><th style="width:26%">見分け方</th><th>打ち手</th></tr>
<tr><td><b>勝っている</b></td><td>10位以内かつCTR3.5%以上</td>
<td>この記事の構成（冒頭の結論・FAQ・出典付きデータ）を新規記事の型として横展開します</td></tr>
<tr><td><b>惜しい</b></td><td>11〜20位で表示回数が多い</td>
<td>最も伸びしろが大きい層。見出しを追加し内部リンクを増やして1ページ目を狙います</td></tr>
<tr><td><b>選ばれていない</b></td><td>順位は良いがCTRが低い</td>
<td>順位を上げる必要はありません。タイトルと説明文だけを直せばクリックが増えます</td></tr>
<tr><td><b>意図がズレている</b></td><td>表示は多いがクリックがほぼ無い</td>
<td>検索している人が求めるものと記事の中身が違います。記事の主題を見直すか、別記事に分けます</td></tr>
</table>
<p class="note">優先順位: 同じ工数なら「選ばれていない」→「惜しい」→「意図がズレている」の順で着手します。
タイトル修正は効果が早く、順位を動かすリライトは数週間かかるためです。</p>
</div>

<!-- ページ: 記事別パフォーマンス+サイト資産 -->
<div class="sheet">
<div class="sec"><span class="no">05</span><h2>記事別パフォーマンス</h2><div class="gold"></div></div>
<h3>ページ別実績（当月・表示回数順）</h3>
<table><tr><th>ページ</th><th>表示回数</th><th>クリック</th><th>クリック率</th><th>平均順位</th></tr>{prows}</table>
<p class="note">読み方: 表示回数が多く順位が11位以下のページはリライトの最有力候補。CTRが同順位帯の平均より低いページはタイトル改善候補です。</p>
<h3 style="margin-top:14px">サイト資産サマリー（累計ストック）</h3>
<div class="hl-cards">
  <div class="hl"><div class="k">{plain("公開記事ストック")}</div><div class="v">{assets["count"]}本</div><div class="s">品質90点以上のみ</div></div>
  <div class="hl"><div class="k">{plain("平均品質スコア")}</div><div class="v">{assets["avg_score"]}点</div><div class="s">6観点採点/100点</div></div>
  <div class="hl"><div class="k">{plain("平均文字数")}</div><div class="v">{assets["avg_len"]:,}字</div><div class="s">基準5,000字以上</div></div>
</div>
<h3 style="margin-top:14px">カテゴリ別の記事構成</h3>
{dist_bars(cat_pairs, "#0d9488")}
<div class="callout"><b>資産の考え方:</b> 記事は広告と違い、公開後も検索とAI回答の両方から流入を生み続けるストック資産です。
1記事あたりの平均{assets["avg_len"]:,}字・平均{assets["avg_score"]}点の品質を保ったまま蓄積することが、ドメイン全体の評価とAI引用確率を押し上げます。</div>
</div>
{pages_extra}

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

<!-- ページ: チャネル別の打ち手（流入構造分析から分割）
     1ページに詰めると次ページへ流れ、表が途中で切れる -->
<div class="sheet">
<div class="sec"><span class="no">07</span><h2>チャネル別の打ち手</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">流入経路は「どこから来たか」ではなく<span class="mark">「何をすれば増えるか」</span>で見ます。
チャネルごとに効く施策がまったく違うため、内訳の変化はそのまま来月の施策の優先順位になります。</p>
<table>
<tr><th style="width:20%">チャネル</th><th style="width:34%">この数字が意味すること</th><th>増やすための打ち手</th></tr>
<tr><td><b>自然検索</b></td><td>検索結果から直接来た数。記事の順位とタイトルの魅力で決まります</td>
<td>順位11〜20位の記事のリライト。CTRが低い記事のタイトル・説明文の書き直し</td></tr>
<tr><td><b>直接流入</b></td><td>URL直接入力・ブックマーク・アプリ経由。<b>指名検索の受け皿</b>でもあります</td>
<td>社名・サービス名を記事内で数値とセットで書き、AI回答に社名ごと引用されることを狙います</td></tr>
<tr><td><b>参照サイト</b></td><td>他サイトのリンクから来た数。被リンクの獲得状況を映します</td>
<td>グループ3サイトの相互リンク、プレスリリース配信、業界メディアへの寄稿</td></tr>
<tr><td><b>AI検索</b></td><td>ChatGPT・Perplexity等の回答経由。まだ小さくても<b>伸び率</b>が重要です</td>
<td>冒頭断言・見出し直下の1文結論・FAQの整備（全記事に標準実装済み）</td></tr>
<tr><td><b>SNS</b></td><td>現在は施策対象外のため小さい数字が正常です</td>
<td>SNS運用を併用される場合は計測項目を追加します（本サービスの範囲外）</td></tr>
</table>
<div class="callout"><b>今の段階で見るべきなのは自然検索の「表示回数」です:</b>
立ち上げ期はセッションよりも先に表示回数が動きます。
表示回数が伸びていれば記事が検索結果に載り始めた証拠で、クリックとセッションは<b>その2〜3ヶ月後</b>に付いてきます。
現時点でセッションが小さくても、表示回数と順位が上向いていれば計画どおりです。</div>
</div>

<!-- ページ: 3サイト横断の実績 -->
<div class="sheet">
<div class="sec"><span class="no">00</span><h2>3サイト横断の検索実績</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">自サイトの数字だけでは、<span class="mark">グループ全体で伸びたのか、
他サイトから移っただけなのか</span>が分かりません。3サイトを並べて確認します。</p>
{group_table(d.get("group", []), SITE_ID)}
<p class="note">網掛けが本レポートの対象サイトです。合計はグループ全体の露出量を示します。
同じテーマを複数サイトで扱うと検索評価を奪い合うため、
1サイトだけ伸びて他が落ちている場合は、担当領域の重なりを確認します。</p>
<div class="callout"><b>この表の見方:</b>
表示回数は「検索結果に出た回数」、クリックは「選ばれた回数」です。
立ち上げ期は表示が先に伸び、クリックはその2〜3ヶ月後に付いてきます。
<b>合計の表示が増え続けているか</b>が、この段階で最も重要な指標です。</div>
</div>

<!-- ページ: 読まれ方のヒートマップと改修点（GA4実測） -->
<div class="sheet">
<div class="sec"><span class="no">00</span><h2>ページのどこで離脱しているか</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">滞在時間の合計では、<span class="mark">どこで読むのをやめたか</span>が分かりません。
セクションごとの到達数を先頭比で見ると、落ちる位置が特定できます。</p>
<h3>セクション到達（ヒートマップ）</h3>
{section_heat(d.get("sections", []))}
<h3 style="margin-top:14px">行動の内訳</h3>
<table><tr><th style="width:28%">指標</th><th style="width:16%">件数</th><th>読み方</th></tr>
<tr><td>セッション</td><td class="num">{(d.get("behavior") or {}).get("sessions", 0)}</td><td>訪問の総数</td></tr>
<tr><td>ボタン押下（全体）</td><td class="num">{(d.get("behavior") or {}).get("cta", 0)}</td><td>サイト内のボタンが押された回数。診断・記事一覧なども含みます</td></tr>
<tr><td>うち問い合わせ方向</td><td class="num">{(d.get("behavior") or {}).get("cta_to_form", 0)}</td><td>問い合わせフォームへ向かうボタン。ここが少ないと入口が足りていません</td></tr>
<tr><td>入力開始</td><td class="num">{(d.get("behavior") or {}).get("form_start", 0)}</td><td>入力を始めた数。CTA押下より極端に少ない場合、遷移先で落ちている</td></tr>
<tr><td>送信完了</td><td class="num">{(d.get("behavior") or {}).get("form_submit", 0)}</td><td>完了した数。開始との差が項目数の問題</td></tr>
</table>
</div>

<!-- ページ: 実測から出た改修点 -->
<div class="sheet">
<div class="sec"><span class="no">00</span><h2>今月の改修点（実測から）</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">担当者の印象ではなく、<span class="mark">数字が基準を割った箇所だけ</span>を挙げています。
該当が無ければ「詰まりなし」と表示され、無理に指摘は作りません。</p>
{fix_table(d)}
<div class="callout"><b>優先順位の意味:</b>
<b>最優先</b>は問い合わせ導線が塞がっている状態で、記事を増やしても成果になりません。
<b>高</b>は今月中に手を入れれば翌月の数字に出ます。
<b>中</b>は翌々月以降に効いてきます。</div>
</div>

<!-- ページ: AI検索分析 -->
<div class="sheet">
<div class="sec"><span class="no">07</span><h2>AI検索（AIO / LLMO）分析</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">検索結果の外側——ChatGPTやPerplexityの「回答」の中で自社がどれだけ参照されたかの分析です。ゼロクリック時代の新しい流入経路であり、当メディアの中核戦略です。</p>
<div class="hl-cards" style="margin:10px 0 14px">
  <div class="hl"><div class="k">{plain("AI経由セッション（当月）")}</div><div class="v">{ai_total}</div><div class="s">前月比 {ai_mom}</div></div>
  <div class="hl"><div class="k">{plain("AI経由の全体比")}</div><div class="v">{round(ai_total / max(cur.get("sessions",1),1) * 100, 1)}%</div><div class="s">対セッション</div></div>
  <div class="hl"><div class="k">{plain("実装済みAIO施策")}</div><div class="v">12項目</div><div class="s">全記事に標準適用</div></div>
</div>
<h3>プラットフォーム別内訳</h3>
{ai_bars(d.get("ai_breakdown", []), ai_total)}
<h3 style="margin-top:14px">AI検索対応の実装状況（全記事に適用）</h3>
<table>
<tr><th style="width:30%">実装項目</th><th style="width:10%">状態</th><th>内容と狙い</th></tr>
<tr><td>冒頭200字の断言型回答</td><td><span class="jd jd-良好">実装済</span></td>
<td>「◯◯は◯◯です」で書き始める。AIが最も抜き出しやすい形で結論を置く</td></tr>
<tr><td>見出し直下の1文結論</td><td><span class="jd jd-良好">実装済</span></td>
<td>40〜60字。その1文だけ切り出しても意味が通るため、AIの回答にそのまま採用されやすい</td></tr>
<tr><td>FAQ構造化（5問以上）</td><td><span class="jd jd-良好">実装済</span></td>
<td>本文と構造化データを完全一致させる。不一致はスパム判定のリスクがある</td></tr>
<tr><td>出典付きの数値ファクト</td><td><span class="jd jd-良好">実装済</span></td>
<td>1記事3箇所以上。AIは数値付きの断定文を優先的に引用する</td></tr>
<tr><td>llms.txt / AIクローラー許可</td><td><span class="jd jd-良好">6種</span></td>
<td>GPTBot・OAI-SearchBot・ClaudeBot・PerplexityBot・Google-Extended・Bingbot を明示的に許可。
ここをブロックしていると順位が高くてもAIに引用されない</td></tr>
<tr><td>構造化データ / 鮮度表記</td><td><span class="jd jd-良好">4種</span></td>
<td>記事情報・FAQ・パンくず・手順。あわせて「◯年◯月時点」を明記し、AI検索の鮮度評価に対応</td></tr>
</table>
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
    <div class="k">{plain("当月の流入を広告で買った場合の金額")}</div>
    <div class="v">{eff["yen"](eff["ad_value"])}</div>
    <div class="s">検索クリック{cur.get("clicks", 0):,}回 × 想定クリック単価{eff["cpc"]}円で換算</div>
  </div>
  <div class="roi-box">
    <div class="k">{plain("記事1本あたりの月間価値")}</div>
    <div class="v">{eff["yen"](eff["per_article_value"])}</div>
    <div class="s">累計{a["assets"]["count"]}本で割った1本あたりの広告換算値</div>
  </div>
  <div class="roi-box">
    <div class="k">{plain("記事1本あたりの月間セッション")}</div>
    <div class="v">{eff["per_article_sessions"]}</div>
    <div class="s">記事が増えるほど合計は積み上がる</div>
  </div>
  <div class="roi-box">
    <div class="k">{plain("記事1本あたりの月間クリック")}</div>
    <div class="v">{eff["per_article_clicks"]}</div>
    <div class="s">順位が上がると同じ本数でも増える</div>
  </div>
</div>
<h3>広告との決定的な違い</h3>
<p style="font-size:9.5pt">広告は出稿を止めた瞬間に流入がゼロになりますが、
記事は<b>公開後も検索とAI回答の両方から流入を生み続けます</b>。
上の金額は「今月分」であり、来月も同じ記事が同じように働きます。
記事が積み上がるほど、この金額は複利のように増えていきます。</p>
<h3>記事が積み上がるとどうなるか</h3>
<table>
<tr><th style="width:16%">時点</th><th style="width:18%">累計記事数</th>
<th style="width:22%">月間の広告換算額</th><th>状態</th></tr>
<tr><td>現在</td><td class="num">{a["assets"]["count"]}本</td>
<td class="num">{eff["yen"](eff["ad_value"])}</td><td>立ち上げ期。順位が安定し始める段階</td></tr>
<tr><td>6ヶ月後</td><td class="num">約{a["assets"]["count"] + 360}本</td>
<td class="num">{eff["yen"](eff["per_article_value"] * (a["assets"]["count"] + 360))}</td>
<td>面が広がり、複数キーワードで上位が取れ始める</td></tr>
<tr><td>12ヶ月後</td><td class="num">約{a["assets"]["count"] + 720}本</td>
<td class="num">{eff["yen"](eff["per_article_value"] * (a["assets"]["count"] + 720))}</td>
<td>ドメイン全体の評価が上がり、新記事の立ち上がりも速くなる</td></tr>
</table>
<p class="note">※ 月60本のペースで、1記事あたりの価値が現在の水準を保った場合の試算です。
実際には記事が増えるほど内部リンクが増え、ドメイン評価が上がるため、1本あたりの価値も上昇する傾向があります。
一方で、古い記事の情報が古くなると価値が落ちるため、週次のリライトで維持します。</p>
<div class="callout"><b>換算の前提:</b> クリック単価は{eff["cpc"]}円で計算しています。
AIO・SEO・MEO関連のキーワードは競合が多く、実際のリスティング広告では
1クリック500〜1,000円以上になることも珍しくありません。
そのため上の金額は<b>控えめな見積もり</b>です。</div>
</div>

<!-- ユーザーの質 -->
<div class="sheet">
<div class="sec"><span class="no">08</span><h2>読まれ方の質（GA4）</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">アクセス数が増えても、読まれずに離脱されていては成果につながりません。
「来た人がどれだけ中身を読んだか」を示す指標です。括弧内は前月からの変化です。</p>
<div class="tiles">
{tile_q("エンゲージメント率", qd("engagement", "%"), "10秒以上滞在・2PV以上・CVのいずれか")}
{tile_q("平均滞在時間", qd("duration", "秒"), "1セッションあたり")}
{tile_q("1訪問あたりPV", qd("pv_per_session"), "回遊のしやすさ")}
{tile_q("新規ユーザー比率", qd("new_ratio", "%", better_high=False), "低いほどリピートが多い")}
</div>
<h3>この指標の読み方</h3>
<table>
<tr><th style="width:22%">指標</th><th style="width:26%">目安</th><th>意味と打ち手</th></tr>
<tr><td><b>エンゲージメント率</b></td><td>55%以上=良好 / 45〜55%=標準 / 45%未満=要改善</td>
<td>低い記事は冒頭で期待とズレています。検索意図に合わせて冒頭200字を書き換えるのが最短の打ち手です</td></tr>
<tr><td><b>平均滞在時間</b></td><td>5,000字の記事なら120秒以上が目安</td>
<td>短い場合は読みにくさが原因のことが多く、図解の追加と段落の分割が効きます</td></tr>
<tr><td><b>1訪問あたりPV</b></td><td>1.5以上=回遊できている</td>
<td>1.0付近なら関連記事への導線が機能していません。本文中の内部リンクを増やします</td></tr>
<tr><td><b>新規ユーザー比率</b></td><td>立ち上げ期は70〜90%が普通</td>
<td>下がってくるのは良い兆候で、リピーターが育っている証拠です</td></tr>
</table>
<h3>行動イベントの発生数</h3>
<table><tr><th style="width:60%">イベント</th><th>回数</th></tr>{ev_rows}</table>
<p class="note">cta_click はCTAボタンの押下、form_start はフォーム入力の開始、
generate_lead は送信完了を表します。押されているのに送信まで至っていない場合、
フォームの項目数が多すぎる可能性があります。</p>
</div>

<!-- ランディングページ分析 -->
<div class="sheet">
<div class="sec"><span class="no">09</span><h2>入口ページ別の成績（オウンドメディア改修の根拠）</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">どの記事から入ってきて、どれだけ読まれ、成果につながったかの一覧です。
<b>流入は多いのにエンゲージメントが低いページ</b>が、改修すると最も効果が出る場所になります。</p>
<table><tr><th>入口ページ</th><th style="width:11%">流入</th><th style="width:13%">エンゲージ率</th>
<th style="width:11%">滞在</th><th style="width:8%">CV</th><th style="width:11%">判定</th></tr>{land_rows}</table>
<div class="callout"><b>ここから改修対象を決めています:</b> 流入50以上でエンゲージメント率45%未満のページは、
「検索では選ばれているが、開いた瞬間に期待と違うと判断されている」状態です。
記事を増やすより、このページを直すほうが費用対効果が高くなります。
具体的な指示は第11章に記載しています。</div>
<h3>地域別のアクセス</h3>
{dist_bars(d.get("cities", []), "#0d9488")}
<p class="note">商圏の実態を確認できます。想定している地域と違う場合は、
記事内の地域名の使い方やGoogleビジネスプロフィールの設定を見直す材料になります。</p>
</div>

<!-- 順位帯の分布 -->
<div class="sheet">
<div class="sec"><span class="no">10</span><h2>検索順位の分布（伸びしろの在り処）</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">検索されているキーワードを順位帯ごとに数えたものです。
<b>11〜20位にどれだけ眠っているか</b>が、来月伸ばせる量を決めます。</p>
<table><tr><th style="width:16%">順位帯</th><th style="width:14%">キーワード数</th>
<th style="width:16%">表示回数</th><th>この層への打ち手</th></tr>{rank_rows}</table>
<h3>リライトの最優先候補（11〜20位・表示回数順）</h3>
<table><tr><th>キーワード</th><th style="width:12%">現在順位</th><th style="width:14%">表示回数</th>
<th style="width:12%">現クリック</th><th style="width:16%">1ページ目到達時の増加見込み</th></tr>{rewrite_rows}</table>
<p class="note">増加見込みは「1ページ目のCTRを4%と仮定した場合の追加クリック数」です。
順位を10位以内に上げるだけで、記事を新しく書かずにクリックが増えることを示しています。</p>
<h3>デバイス別の検索実績</h3>
<table><tr><th style="width:22%">デバイス</th><th>表示回数</th><th>クリック</th><th>クリック率</th><th>平均順位</th></tr>{gdev_rows}</table>
<p class="note">スマホとPCでCTRが大きく違う場合、タイトルの後半が切れて訴求が届いていない可能性があります。
スマホの検索結果では前半28文字程度しか表示されません。</p>
</div>

<!-- オウンドメディア改修プラン -->
<div class="sheet">
<div class="sec"><span class="no">11</span><h2>オウンドメディアの改修プラン</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">ここまでの分析から導いた、<b>サイトのどこを・どう変えるか</b>の具体的な指示です。
すべて当社が翌月の運用の中で実施します。</p>
<table><tr><th style="width:20%">対象</th><th style="width:14%">改修の種類</th>
<th style="width:28%">現状（実測）</th><th>変更内容</th></tr>{media_rows}</table>
<p class="note">改修の優先順位: ①順位11〜20位のリライト → ②エンゲージメントが低い記事の冒頭改善
→ ③CVが出ていない記事の導線改善 → ④薄いカテゴリの補強。
新しい記事を書くより、既にある記事を直すほうが早く成果が出るためです。</p>
</div>
{media_extra}

<!-- 被リンクの追加指示 -->
<div class="sheet">
<div class="sec"><span class="no">11</span><h2>被リンクを送るべき記事（内部リンクの追加指示）</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">サイト内のどの記事へ、どの記事からリンクを足すかの指示です。
本文中のリンクを数えると、公開{ib["articles"]}記事で<b>最小{ib["min"]}本・中央{ib["mid"]}本・最大{ib["max"]}本</b>と開いています
（一覧・関連記事欄の自動リンクは除く）。人気のある記事にリンクが集まり、
順位が1ページ目の手前で止まっている記事ほど不足しています。
記事を新しく書かずに順位を動かせる、最も費用のかからない打ち手です。</p>
<table><tr><th style="width:26%">リンク先（この記事へ送る）</th><th style="width:9%">現在</th>
<th style="width:26%">優先する理由</th><th>リンク元にする記事</th></tr>{inbound_rows}</table>
<p class="note">作業手順: リンク元の記事本文で、リンク先の話題に触れている段落を探し、
その直後に1文を足してリンクを置きます。まとめ・FAQの中ではなく<b>本文H2の1文結論の直後</b>に置くこと。
読者が次に知りたくなる位置と一致し、AI検索にも文脈ごと読まれます。
アンカーテキストは<b>リンク先の記事タイトルをそのまま</b>使い、「こちら」は使いません。
リンク先が何かを検索エンジンにもAIにも伝えないためです。</p>
</div>
{inbound_extra}

<!-- LP改修プラン -->
<div class="sheet">
<div class="sec"><span class="no">12</span><h2>LPの改修プラン</h2><div class="gold"></div></div>
{media_carry}
<p class="note">記事で集めた読者を問い合わせまで運ぶのがLPの役割です。どこで離脱しているかを実測し、直す場所を特定します。</p>
<table><tr><th style="width:22%">対象</th><th style="width:14%">改修の種類</th>
<th style="width:26%">現状（実測）</th><th>変更内容</th></tr>{lpplan_rows}</table>
<p class="note">LP改修の考え方: LPは上から順に読まれるものではなく、
各セクションで読者が「読み進めるか離脱するか」を判断しています。
到達率が大きく落ちる場所が「読む価値なし」と判断された箇所です。
そこを直すほうが、デザイン全体を作り替えるより確実で安価です。</p>
</div>

<!-- ページ: LPコンバージョン分析 -->
<div class="sheet">
<div class="sec"><span class="no">13</span><h2>LPコンバージョン分析</h2><div class="gold"></div></div>
<h3>主要区画のファネル（どこまで読まれ、どこで離脱したか）</h3>
{funnel_html(d.get("areas", []))}
<h3 style="margin-top:14px">全12区画の到達ヒートマップ</h3>
{svg_heatbars(d.get("areas", []))}
<p class="note">■青=60%以上 ■水色=40-59% ■橙=20-39% ■赤=20%未満。
GA4の独自イベント（画面内40%表示で発火）による計測で、有料ツールなしで取得しています。</p>
<h3>この数字をどう読むか</h3>
<table>
<tr><th style="width:18%">到達率</th><th style="width:20%">意味</th><th>取るべき対応</th></tr>
<tr><td><b>60%以上</b></td><td>読まれている</td><td>機能しています。文言も順序も変えません</td></tr>
<tr><td><b>40〜59%</b></td><td>半数が離脱</td><td>見出しを利益訴求型に変え、冒頭1文で結論を出します</td></tr>
<tr><td><b>39%以下</b></td><td>大半が未到達</td><td>順序を見直すか削ります。ここにCTAを置いても効果はありません</td></tr>
</table>
<h3>CVまでの導線</h3>
<p style="font-size:9.4pt">読者がCVに至るまでには
<b>記事を読む → LPへ移動 → LPを読み進める → フォーム到達 → 送信</b>の5段階があります。
記事からLPへの移動が少なければ記事内のCTA文言、LP内の離脱が大きければセクション構成、
フォーム到達後の離脱が大きければ入力項目の数が原因です。第9章で記事側、この章でLP側を分けて計測しています。</p>
</div>

<!-- ページ7: 要因分析+改善プラン -->
<div class="sheet">
<div class="sec"><span class="no">14</span><h2>成果の要因分析</h2><div class="gold"></div></div>
<ul class="grown">{grown}</ul>
<div class="sec" style="margin-top:18px"><span class="no">15</span><h2>改善プラン（優先度つき対比表）</h2><div class="gold"></div></div>
<table><tr><th style="width:8%">優先度</th><th style="width:22%">エリア/対象</th><th style="width:30%">現状（データ根拠）</th><th>改善アクション（何をどう変えるか）</th></tr>{frows}</table>
</div>

<!-- ページ: サイト全体監査 -->
<div class="sheet">
<div class="sec"><span class="no">16</span><h2>サイト全体監査（記事別の修正指示）</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">全{audit["audited"]}記事とサイト構造を機械監査し、検索データ（順位・CTR）と品質基準（鮮度・内部リンク・FAQ）を突合した<b>具体的な修正指示</b>です。修正は週次最適化（毎週月曜）が自動で実施し、翌月号で効果を検証します。</p>
<h3>ブログ記事の修正指示（優先度順）</h3>
<table><tr><th style="width:22%">記事</th><th style="width:14%">修正箇所</th><th style="width:28%">現状（実測）</th><th>変更内容</th></tr>{audit_art_rows}</table>
<p class="note">読み方: 「修正箇所」はその記事のどこを触るかを示します。
順位が11位以下のものは本文構成、CTRが低いものはタイトルとメタ情報、
更新から日が経ったものは鮮度表記が対象になります。</p>
<h3 style="margin-top:16px">この監査はどう行っているか</h3>
<ul style="font-size:9.4pt">
  <li><b>検索データとの突合</b> — Search Consoleの順位・CTR・表示回数と、記事の構造を照らし合わせます。
  「露出はあるのに選ばれていない」「順位は惜しいが2ページ目」といった状態を機械的に検出します。</li>
  <li><b>品質基準との突合</b> — 内部リンクの本数、FAQの数、最終更新からの日数、
  出典付き数値の有無を全記事について数えます。基準を割ったものが修正指示に上がります。</li>
  <li><b>重複の検出</b> — 記事どうしの文章の近さを測定し、同じ検索意図を狙っている組を洗い出します。
  複数サイトを運用している場合は、サイトをまたいだ重複も同時に検査します。</li>
  <li><b>実施は翌月の運用の中で</b> — ここに挙げた修正は当社が実施します。追加料金はかかりません。
  実施した結果は翌月号で効果を検証します。</li>
</ul>
</div>
{audit_art_extra}
<!-- ページ: 監査（サイト構造編） -->
<div class="sheet">
<div class="sec"><span class="no">17</span><h2>サイト全体監査（サイト構造・導線）</h2><div class="gold"></div></div>
<h3 style="margin-top:0">サイト構造・導線の変更指示</h3>
<table><tr><th style="width:18%">対象</th><th style="width:16%">場所</th><th style="width:28%">現状（実測）</th><th>変更内容</th></tr>{audit_site_rows}</table>
<h3 style="margin-top:14px">✅ 変更せず維持するもの（好調・基準充足）</h3>
<p class="note">以下の記事は検索データと品質基準の両方を満たしています。
無理に手を入れると順位が下がることがあるため、今月は触りません。</p>
<ul class="keep2">{audit_keep}</ul>
<div class="callout"><b>優先順位の考え方:</b> 同じ工数をかけるなら、
<span class="mark">順位11〜30位の記事のリライト</span>が最も成果につながります。
1ページ目に入るとクリック数が数倍になるためです。
新規記事の追加より先に、この層の改善に取り組みます。</div>
</div>

<!-- ページ8: コンテンツ実績+来月プラン -->
<div class="sheet">
<div class="sec"><span class="no">18</span><h2>コンテンツ実績</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">当月公開: <b>{d["content"]["published"]}本</b>（公開基準: 品質採点90点以上・機械検査18項目全PASSのみが公開されます）</p>
<table><tr><th>日付</th><th>タイトル</th><th>品質スコア</th><th>審査記録</th></tr>{crows}</table>
{best_html}
<h3>公開までに通過する検査</h3>
<table>
<tr><th style="width:24%">検査</th><th style="width:14%">項目数</th><th>内容</th></tr>
<tr><td><b>構成の事前審査</b></td><td>14項目</td>
<td>書き始める前に構成を審査。見出し設計・結論の草案・出典候補・内部リンク先まで確認し、
全項目を満たすまで執筆に入りません</td></tr>
<tr><td><b>機械採点</b></td><td>18項目</td>
<td>文字数・強調の数・FAQ数・リンク数・見出し構造・AI感のNGワードなど、
数えられるものを機械が判定します</td></tr>
<tr><td><b>6観点の採点</b></td><td>120点満点</td>
<td>デザイン／SEO／編集／技術正確性／読者目線／AI検索対応。各20点で、
1観点でも16点未満なら合計に関わらず不合格です</td></tr>
<tr><td><b>公開時の物理ガード</b></td><td>90点未満は公開不可</td>
<td>基準に届かない記事は、システム上サイトに載せられません。
「本数が足りないから品質を落として出す」が構造的に起きない設計です</td></tr>
</table>
</div>

<!-- ページ: 記事の中身（コンテンツ実績から分割）
     検査の表と併記すると1ページに収まらず、表が途中で切れる -->
<div class="sheet">
<div class="sec"><span class="no">19</span><h2>1記事に含まれるもの</h2><div class="gold"></div></div>
<table>
<tr><td style="width:20%"><b>本文</b></td><td>5,000字以上</td>
<td style="width:20%"><b>画像</b></td><td>アイキャッチ1枚＋図解3〜5枚</td></tr>
<tr><td><b>FAQ</b></td><td>5問以上・構造化データと完全一致</td>
<td><b>リンク</b></td><td>内部3本以上＋出典の外部リンク</td></tr>
<tr><td><b>根拠</b></td><td>出典付きの数値ファクト3箇所以上</td>
<td><b>導線</b></td><td>目次・CTA2箇所以上・関連記事</td></tr>
</table>
<div class="callout"><b>品質を数値で管理する理由:</b> 記事を大量に作るとき、最大のリスクは品質のばらつきです。
採点を人の感覚ではなく<span class="mark">数値と項目で定義</span>しているため、
何本作っても基準が下がりません。当月の平均は{a["assets"]["avg_score"]}点でした。</div>
</div>

<!-- ページ: 目標対比+来月スケジュール -->
<div class="sheet">
<div class="sec"><span class="no">19</span><h2>前月目標の達成率と来月のKPI目標</h2><div class="gold"></div></div>
<h3 style="margin-top:0">前号で立てた「当月の目標」に対する結果</h3>
<table><tr><th>指標</th><th style="width:14%">前号の目標</th><th style="width:14%">当月の実績</th>
<th style="width:12%">達成率</th><th style="width:12%">判定</th></tr>{ach_rows}</table>
<h3>来月の目標</h3>
<p style="font-size:9.5pt">当月実績をベースに、来月の目標値を設定します。目標は「前月比の成長率」と「最低増加量」の大きい方を採用し、立ち上げ期でも歩みを止めない設計です。</p>
<table><tr><th>指標</th><th style="width:14%">当月実績</th><th style="width:14%">来月目標</th><th>目標の根拠</th></tr>{trows}</table>
<div class="callout"><b>目標の使い方:</b> 来月号のレポートで本表の目標と実績を突合します。2ヶ月連続で未達の指標は、施策の前提（KW選定・導線設計）から見直します。</div>
</div>

<!-- ページ: 来月の実行スケジュール -->
<div class="sheet">
<div class="sec"><span class="no">20</span><h2>来月の実行スケジュール</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">前章の目標を達成するために、来月に実施する施策を優先度順に並べたものです。
<span class="mark">上から順に着手</span>し、実施状況は来月号の本レポートで報告します。</p>
<table><tr><th style="width:6%">#</th><th>アクション</th><th style="width:12%">実施時期</th><th style="width:34%">狙い</th></tr>{action_rows}</table>
<h3>月内の進め方</h3>
<p style="font-size:9.5pt">記事の公開は毎日自動で進みます。人の判断が要る工程だけを、月内で以下のように配置しています。</p>
<table>
<tr><th style="width:14%">時期</th><th style="width:34%">実施すること</th><th>御社にお願いすること</th></tr>
<tr><td><b>第1週</b></td><td>本レポートの共有と、改修プランの着手判断</td>
<td>LPの文言・掲載事例など、御社にしか出せない情報のご提供</td></tr>
<tr><td><b>第2〜3週</b></td><td>既存記事のリライトと内部リンク強化、新規記事の継続公開</td>
<td>特にありません（進捗はいつでもご確認いただけます）</td></tr>
<tr><td><b>第4週</b></td><td>順位・AI検索の反応を確認し、翌月のキーワードを確定</td>
<td>問い合わせの中身に変化があればご共有ください</td></tr>
</table>
<div class="callout"><b>優先順位の決め方:</b> 施策は「効果が出るまでの速さ」ד影響する記事の本数”で並べています。
既存記事のリライトは<b>1〜2週間で順位に反映される</b>ため常に上位に置き、
新規記事の追加は効果まで3ヶ月かかる前提で、本数を落とさず継続することを重視します。</div>
</div>

<!-- ページ9: 付録 -->
<div class="sheet">
<div class="sec"><span class="no">21</span><h2>リスクと前提条件</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">数字を正しく受け取っていただくために、
このレポートを読むうえで知っておいていただきたい前提をまとめます。</p>
<table><tr><th style="width:32%">前提・注意点</th><th>内容</th></tr>{risk_rows}</table>
<h3>成果が出るまでの一般的な流れ</h3>
<table>
<tr><th style="width:16%">時期</th><th style="width:30%">この時期に起きること</th><th>見るべき指標</th></tr>
<tr><td><b>1〜2ヶ月目</b></td><td>記事のインデックス登録が進み、表示回数が増え始める</td>
<td>表示回数とインデックス済み記事数。クリックはまだ少なくて正常です</td></tr>
<tr><td><b>3〜4ヶ月目</b></td><td>順位が動き始め、一部のキーワードで1ページ目に入る</td>
<td>順位帯の分布。11〜20位の本数が増えていれば順調です</td></tr>
<tr><td><b>5〜6ヶ月目</b></td><td>クリックとセッションが伸び始める。CVが出始める</td>
<td>クリック数とCV。ここで初めて成果が数字に表れます</td></tr>
<tr><td><b>7ヶ月目以降</b></td><td>記事数の増加と順位上昇が重なり、伸びが加速する</td>
<td>全指標。ドメイン評価が上がり新記事の立ち上がりも速くなります</td></tr>
</table>
<h3>このレポートで扱っていないこと</h3>
<ul style="font-size:9.4pt">
  <li><b>競合サイトの数値</b> — 他社のアクセス数や順位は正確に取得できないため、
  推測値は載せていません。競合との比較が必要な場合は個別調査でご対応します。</li>
  <li><b>SNSからの流入の詳細</b> — 現在の施策は検索とAI検索が中心です。
  SNS運用を併用される場合は、計測項目を追加できます。</li>
  <li><b>問い合わせの中身と受注率</b> — CVの件数までは計測していますが、
  その後の商談化・受注は御社の管理範囲です。共有いただければ、
  「どのキーワードから受注につながったか」まで分析できます。</li>
</ul>
<div class="callout"><b>判断のしかた:</b> 単月の数字が下がっても、施策が間違っているとは限りません。
逆に単月で上がっても、それが施策の成果とは限りません。
<b>3ヶ月の傾向線</b>と<b>順位・CTRという原因側の指標</b>で判断するのが、この事業の正しい見方です。
本レポートの第2章（指標の評価）と第3章の6ヶ月トレンドを、その判断材料としてご覧ください。</div>
</div>

<div class="sheet">
<div class="sec"><span class="no">22</span><h2>付録: 指標の定義と用語解説</h2><div class="gold"></div></div>
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
  <div class="l">{site_cfg()["name"]}｜セブンセンシズ株式会社</div>
  <div class="s">〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902<br>
  TEL 06-4305-7547（9:00〜20:00 / 土日祝休）<br>
  https://ai.7senses.co.jp ｜ https://corp.7senses.co.jp<br><br>
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
    # サイトごとに分ける。同じ場所へ書くと最後に走ったサイトだけが残る。
    import sites as _sm2
    out_dir = ROOT / "reports" / (ym if SITE_ID == _sm2.primary()
                                  else f"{ym}-{SITE_ID}")
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / "report.html"
    pdf_path = out_dir / "report.pdf"
    html = renumber_sections(html)
    html_path.write_text(html, encoding="utf-8")

    # 来月号で達成率を突合するため、設定した目標を翌月のキーで保存する
    if not DEMO:
        y, mo = map(int, ym.split("-"))
        next_ym = f"{y + (mo == 12)}-{(mo % 12) + 1:02d}"
        import sites as _sm3
        tf = ROOT / "reports" / ("targets.json" if SITE_ID == _sm3.primary()
                                else f"targets-{SITE_ID}.json")
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
        pdf_util.compact_pages(pg)
        pdf_util.check_overflow(pg, "月次レポート")
        pg.pdf(path=str(pdf_path), format="A4", print_background=True,
               display_header_footer=True,
               header_template="<span></span>",
               footer_template=(
                   '<div style="width:100%;font-size:7px;color:#8ba0bd;'
                   'padding:0 12mm;display:flex;justify-content:space-between;">'
                   f'<span>{site_cfg()["name"]} 月次コンサルティングレポート ｜ セブンセンシズ株式会社</span>'
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
            "subject": f"【{site_cfg()['name']}】月次コンサルティングレポート {ym}",
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
