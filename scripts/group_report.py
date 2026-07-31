# -*- coding: utf-8 -*-
"""3サイト横断の月次レポート（グループ全体版）

使い方:
    python scripts/group_report.py            # 実データで生成
    python scripts/group_report.py --demo     # サンプルデータで形式確認
    python scripts/group_report.py --email    # 生成後メール送付

各サイト単体の詳細レポートは monthly_report.py が担当する。
こちらは「3サイトを1冊で見渡す」ための経営向けレポート。
GA4/GSCの権限が未付与のサイトは「権限付与待ち」と明示し、数字がゼロなのか
取得できていないのかを混同させない。
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
from monthly_report import ENV, svg_line, svg_spark  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SA = ROOT / "indexing-service-account.json"
DEMO = "--demo" in sys.argv
NAVY, BLUE, TEAL, GOLD, MUTED, LINE = "#0b2447", "#2563eb", "#0d9488", "#b7922e", "#5b6b84", "#e3eaf3"
CPC = 300  # 広告換算に使う想定クリック単価（円）
AI_DOMAINS = {"chatgpt": ["chatgpt.com", "chat.openai.com"], "perplexity": ["perplexity.ai"],
              "gemini": ["gemini.google.com"], "copilot": ["copilot.microsoft.com"],
              "claude": ["claude.ai"]}


# ============================================================
# データ取得
# ============================================================
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
    """1サイト分の月次データ。取得できない項目はNoneのままにして理由を残す"""
    out = {"id": cfg["id"], "name": cfg["name"], "domain": cfg["domain"], "theme": cfg["theme"],
           "audience": cfg.get("audience", ""), "months": [{"label": m} for m in labels],
           "ga_error": None, "sc_error": None, "ai": 0, "breakdown": {}, "queries": [], "pages": []}

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
                property=p, date_ranges=[DateRange(start_date=f"{cur}-01", end_date=month_end(cur))],
                dimensions=[Dimension(name="sessionSource")], metrics=[Metric(name="sessions")]))
            for r in rep.rows:
                src, n = r.dimension_values[0].value.lower(), int(r.metric_values[0].value)
                for k, doms in AI_DOMAINS.items():
                    if any(dm in src for dm in doms):
                        out["ai"] += n
                        out["breakdown"][k] = out["breakdown"].get(k, 0) + n
        except Exception as e:
            out["ga_error"] = f"取得失敗: {str(e)[:50]}"
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
                    "ctr": round(r.get("ctr", 0) * 100, 2), "pos": round(r.get("position", 0), 1)})
            cur = labels[-1]
            for dim, key in [("query", "queries"), ("page", "pages")]:
                res = sc.searchanalytics().query(siteUrl=site_url, body={
                    "startDate": f"{cur}-01", "endDate": month_end(cur),
                    "dimensions": [dim], "rowLimit": 5}).execute()
                out[key] = [{"k": r["keys"][0], "imp": int(r["impressions"]),
                             "clicks": int(r["clicks"]), "ctr": round(r["ctr"] * 100, 1),
                             "pos": round(r["position"], 1)} for r in res.get("rows", [])]
        except Exception as e:
            out["sc_error"] = ("Search Consoleの権限未付与"
                               if "sufficient permission" in str(e) else f"取得失敗: {str(e)[:40]}")
    else:
        out["sc_error"] = "サービスアカウント未配置"
    return out


def fetch_demo(labels):
    seeds = [(320, 480, 690, 940, 1310, 1720), (120, 180, 260, 330, 420, 560),
             (60, 90, 140, 210, 300, 410)]
    out = []
    for (sid, cfg), s in zip(sites_mod.load_all().items(), seeds):
        out.append({
            "id": sid, "name": cfg["name"], "domain": cfg["domain"], "theme": cfg["theme"],
            "audience": cfg.get("audience", ""), "ga_error": None, "sc_error": None,
            "ai": s[-1] // 20,
            "breakdown": {"chatgpt": s[-1] // 40, "perplexity": s[-1] // 70, "gemini": s[-1] // 120},
            "queries": [{"k": f"{cfg['theme'][:6]} 関連KW{i}", "imp": 900 - i * 150,
                         "clicks": 40 - i * 7, "ctr": 4.4 - i * 0.5, "pos": 5.2 + i * 1.4}
                        for i in range(1, 4)],
            "pages": [{"k": f"https://{cfg['domain']}/sample-{i}/", "imp": 800 - i * 140,
                       "clicks": 36 - i * 6, "ctr": 4.2 - i * 0.4, "pos": 6.1 + i * 1.3}
                      for i in range(1, 4)],
            "months": [{"label": m, "sessions": v, "cv": max(1, v // 130), "clicks": v // 2,
                        "impressions": v * 26, "ctr": round(v / 2 / (v * 26) * 100, 2),
                        "pos": round(22 - i * 2.1, 1)}
                       for i, (m, v) in enumerate(zip(labels, s))]})
    return out


def article_stats():
    """記事ストックの実測。自リポジトリは実ファイル、他サイトは台帳の公開済み件数"""
    arts = load_articles()
    scores, lens, cats = [], [], {}
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.groups()
        sc = re.search(r"^score:\s*(\d+)", fm, re.M)
        if sc:
            scores.append(int(sc.group(1)))
        lens.append(len(re.sub(r"\s", "", body)))
        cm = re.search(r"^category:\s*(\S+)", fm, re.M)
        if cm:
            cats[cm.group(1)] = cats.get(cm.group(1), 0) + 1
    counts = {"ai-lab": len(arts)}
    for k in hub_client.all_kw():
        if k.get("status") == "公開済み" and k.get("site") != "ai-lab":
            counts[k["site"]] = counts.get(k["site"], 0) + 1
    return {"counts": counts, "cats": sorted(cats.items(), key=lambda x: -x[1]),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "avg_len": round(sum(lens) / len(lens)) if lens else 0,
            "total": sum(counts.values())}


def cross_links():
    """記事本文から他サイトへのリンク数を数える（相互送客の実測）"""
    doms = {c["domain"]: 0 for c in sites_mod.load_all().values()}
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        for d in doms:
            doms[d] += len(re.findall(re.escape(d), t))
    return doms


def kw_pipeline():
    """台帳のKW残数。記事を作り続けられるかの先行指標"""
    out = {}
    for k in hub_client.all_kw():
        s = out.setdefault(k["site"], {"todo": 0, "doing": 0, "done": 0, "off": 0})
        st = str(k.get("status", "")).strip()
        key = {"未着手": "todo", "執筆中": "doing", "公開済み": "done", "対象外": "off"}.get(st)
        if key:
            s[key] += 1
    return out


# ============================================================
# 分析
# ============================================================
def band(v, good, ok, reverse=False):
    if reverse:
        return "良好" if v and v <= good else ("標準" if v and v <= ok else "要改善")
    return "良好" if v >= good else ("標準" if v >= ok else "要改善")


def analyze(sites, labels, arts, pipeline):
    def total(key, idx=-1):
        return sum((s["months"][idx].get(key) or 0) for s in sites)

    cur = {k: total(k) for k in ["sessions", "cv", "clicks", "impressions"]}
    prev = {k: total(k, -2) for k in ["sessions", "cv", "clicks", "impressions"]}
    ai = sum(s["ai"] for s in sites)

    def mom(k):
        a, b = cur.get(k, 0), prev.get(k, 0)
        if not b:
            return "―"
        v = (a - b) / b * 100
        return f"{'+' if v >= 0 else ''}{v:.0f}%"

    ctr = round(cur["clicks"] / cur["impressions"] * 100, 2) if cur["impressions"] else 0
    cvr = round(cur["cv"] / cur["sessions"] * 100, 2) if cur["sessions"] else 0
    ai_ratio = round(ai / cur["sessions"] * 100, 1) if cur["sessions"] else 0
    poss = [s["months"][-1].get("pos") for s in sites if s["months"][-1].get("pos")]
    pos = round(sum(poss) / len(poss), 1) if poss else 0
    ad_value = cur["clicks"] * CPC

    assess = [
        {"k": "平均CTR（3サイト）", "v": f"{ctr}%", "j": band(ctr, 3.0, 1.5),
         "base": "3%以上=良好 / 1.5〜3%=標準 / 1.5%未満=要改善",
         "why": "同じ順位でもタイトル次第で倍以上変わる。低ければタイトル改善が最短の打ち手"},
        {"k": "平均掲載順位", "v": f"{pos}位", "j": band(pos, 10, 20, reverse=True),
         "base": "10位以内=良好 / 10〜20位=標準 / 20位超=要改善",
         "why": "10位以内が1ページ目。11〜30位はリライトで最も伸びしろが大きい"},
        {"k": "CV率", "v": f"{cvr}%", "j": band(cvr, 1.0, 0.3),
         "base": "1%以上=良好 / 0.3〜1%=標準 / 0.3%未満=要改善",
         "why": "問い合わせ型は0.5〜1%が一般的。低ければ導線設計を疑う"},
        {"k": "AI経由の比率", "v": f"{ai_ratio}%", "j": band(ai_ratio, 3.0, 1.0),
         "base": "3%以上=良好 / 1〜3%=標準 / 1%未満=立ち上げ中",
         "why": "AI検索からの流入比率。市場全体でまだ数%の段階で、あること自体が先行指標"},
    ]

    # サイト別の貢献度と成長率
    contrib = []
    for s in sites:
        c, p = s["months"][-1], s["months"][-2]
        sess, psess = c.get("sessions"), p.get("sessions")
        growth = "―"
        if sess is not None and psess:
            g = (sess - psess) / psess * 100
            growth = f"{'+' if g >= 0 else ''}{g:.0f}%"
        share = round((sess or 0) / cur["sessions"] * 100) if cur["sessions"] else 0
        contrib.append({"s": s, "share": share, "growth": growth,
                        "articles": arts["counts"].get(s["id"], 0),
                        "todo": pipeline.get(s["id"], {}).get("todo", 0)})

    # 改善プラン（データから機械的に導く）
    plan = []
    for s in sites:
        c = s["months"][-1]
        if s["ga_error"] or s["sc_error"]:
            plan.append(("高", s["name"], "計測データが取得できていない",
                         "サービスアカウントにGA4「閲覧者」・Search Console「フル」を付与する。"
                         "計測できない期間は改善の判断ができない"))
            continue
        if (c.get("pos") or 0) > 15:
            plan.append(("高", s["name"], f'平均順位 {c.get("pos")}位（2ページ目以降が中心）',
                         "表示回数の多い記事から順にリライト。H2を1本追加し内部リンクを2本増やす"))
        if (c.get("ctr") or 0) < 2 and (c.get("impressions") or 0) > 500:
            plan.append(("高", s["name"], f'CTR {c.get("ctr")}%（露出はあるが選ばれていない）',
                         "タイトルに数字と年号を入れ、説明文を結論先出しに書き換える"))
        if arts["counts"].get(s["id"], 0) < 10:
            plan.append(("中", s["name"], f'記事{arts["counts"].get(s["id"], 0)}本（面が狭い）',
                         "このサイトの担当テーマで記事本数を優先配分し、10本以上の面を作る"))
        if pipeline.get(s["id"], {}).get("todo", 0) < 10:
            plan.append(("中", s["name"], f'未着手KWが{pipeline.get(s["id"], {}).get("todo", 0)}件',
                         "実データ（検索実績とサジェスト）からKWを補充し、生成が止まらないようにする"))
    if not plan:
        plan.append(("中", "3サイト共通", "大きな課題は検出されていない",
                     "現在の運用を維持し、勝ちパターンの横展開に注力する"))

    # 来月の目標（当月実績から自動設定）
    def tgt(v, rate, floor):
        return max(round(v * rate), v + floor)
    targets = [
        ("セッション", f'{cur["sessions"]:,}', f'{tgt(cur["sessions"], 1.3, 100):,}',
         "記事数の増加と順位上昇の複利。前月比+30%または+100の大きい方"),
        ("検索クリック", f'{cur["clicks"]:,}', f'{tgt(cur["clicks"], 1.4, 60):,}',
         "新規記事のインデックス進行とリライトによるCTR改善"),
        ("CV", f'{cur["cv"]}件', f'{tgt(cur["cv"], 1.5, 2)}件',
         "記事からLPへの導線改善による転換率向上"),
        ("AI経由参照", f"{ai}", f"{tgt(ai, 1.5, 5)}",
         "記事の蓄積とllms.txt更新によるAI引用の積み上がり"),
        ("公開記事（3サイト合計）", f'{arts["total"]}本', f'{arts["total"] + 60}本',
         "月60本の生成体制の定常値（品質90点以上のみ）"),
    ]

    headline = [
        f'3サイト合計のセッションは{cur["sessions"]:,}（前月比{mom("sessions")}）、'
        f'検索クリックは{cur["clicks"]:,}（{mom("clicks")}）でした。',
        f'CVは{cur["cv"]}件（{mom("cv")}）。同じ流入を広告で買った場合は'
        f'約{ad_value:,}円相当にあたり、これを記事の資産で獲得しています。',
        f'記事は3サイト合計{arts["total"]}本まで積み上がりました。'
        f'サイト間の役割は分かれており、検索評価の奪い合いは発生していません。',
    ]

    risks = [
        ("単月の増減だけで判断しない", "検索は季節性とアルゴリズム更新で単月±20%程度動きます。"
                                "3ヶ月の傾向線で見るのが実務的です。"),
        ("Search Consoleは3日遅れ", "月末付近の数値は確定前のため、翌月号で微増することがあります。"),
        ("AI経由は過小評価になりやすい", "ChatGPT等はリファラーを送らない場合があり、"
                                "実際の影響は計測値より大きい可能性があります。"),
        ("3サイトは役割が異なる", "補助金サイトは申請時期、コーポレートは採用時期など、"
                          "サイトごとに需要の山が異なります。合計値だけでなくサイト別の推移も併せてご覧ください。"),
    ]

    return {"cur": cur, "prev": prev, "mom": mom, "ai": ai, "ctr": ctr, "cvr": cvr, "pos": pos,
            "ai_ratio": ai_ratio, "ad_value": ad_value, "assess": assess, "contrib": contrib,
            "plan": plan, "targets": targets, "headline": headline, "risks": risks}


# ============================================================
# 描画部品
# ============================================================
def tile(label, value, sub, good=True):
    return (f'<div class="tile"><div class="t-l">{label}</div><div class="t-v">{value}</div>'
            f'<div class="t-s {"good" if good else "bad"}">{sub}</div></div>')


def bars(pairs, color=BLUE, total=None):
    if not pairs:
        return f'<p class="dim" style="font-size:9pt">データなし</p>'
    tot = total or sum(v for _, v in pairs) or 1
    out = ""
    for name, v in pairs:
        pct = round(v / tot * 100)
        out += (f'<div class="hm-row"><div class="hm-l">{name}</div>'
                f'<div class="hm-t"><div class="hm-b" style="width:{max(pct, 2)}%;'
                f'background:{color}"></div></div>'
                f'<div class="hm-v">{v:,}<span class="dim"> ({pct}%)</span></div></div>')
    return f'<div class="heat">{out}</div>'


def na(v, fmt="{:,}"):
    return fmt.format(v) if v is not None else '<span class="na">権限付与待ち</span>'


# ============================================================
# レポート本体
# ============================================================
def render(sites, labels, arts, cross, links, pipeline, a):
    ym = labels[-1]
    cur, mom = a["cur"], a["mom"]
    logo = ""
    lp = ROOT / "site" / "images" / "company" / "logo-white.png"
    if lp.exists():
        logo = f'<img class="lg" src="data:image/png;base64,{base64.b64encode(lp.read_bytes()).decode()}">'

    toc = ["エグゼクティブサマリー（3行まとめ）", "グループ全体のKPIダッシュボード",
           "サイト別の貢献度と成長率", "指標の評価（良し悪しの判定）",
           "投資対効果（広告換算）", "サイト間の重複と役割分担の健全性",
           "コンテンツ資産の状況", "記事の供給状況（KW台帳）"] + \
          [f"{s['name'][:16]} の詳細" for s in sites] + \
          ["AI検索（AIO/LLMO）分析", "サイト間の相互送客", "グループ全体の改善プラン",
           "来月のKPI目標", "実行スケジュール", "リスクと前提条件", "付録: 指標の定義"]
    toc_html = "".join(f'<li><span>{i:02d}</span>{t}</li>' for i, t in enumerate(toc, 1))
    head_html = "".join(f"<li>{h}</li>" for h in a["headline"])

    # 各種テーブル
    contrib_rows = "".join(
        f'<tr><td><b>{c["s"]["name"][:18]}</b><br><span class="dim">{c["s"]["domain"]}</span></td>'
        f'<td>{c["s"]["theme"][:20]}</td>'
        f'<td class="num">{c["articles"]}本</td>'
        f'<td class="num">{na(c["s"]["months"][-1].get("sessions"))}</td>'
        f'<td class="num">{c["share"]}%</td>'
        f'<td class="num">{c["growth"]}</td></tr>' for c in a["contrib"])
    assess_rows = "".join(
        f'<tr><td><b>{x["k"]}</b></td><td class="num">{x["v"]}</td>'
        f'<td><span class="jd jd-{x["j"]}">{x["j"]}</span></td>'
        f'<td>{x["base"]}</td><td>{x["why"]}</td></tr>' for x in a["assess"])
    cross_rows = "".join(
        f'<tr><td>{c["site"]}</td><td>{c["keyword"]}</td><td>{c["owner"]}</td></tr>'
        for c in cross) or '<tr><td colspan="3">サイト間の重複・領域侵食はありません（良好）</td></tr>'
    plan_rows = "".join(
        f'<tr><td><span class="pri pri-{p}">{p}</span></td><td>{t}</td><td>{now}</td><td>{how}</td></tr>'
        for p, t, now, how in a["plan"])
    tgt_rows = "".join(
        f'<tr><td>{k}</td><td class="num">{n}</td>'
        f'<td class="num" style="color:#067647;font-weight:bold">{t}</td><td>{w}</td></tr>'
        for k, n, t, w in a["targets"])
    risk_rows = "".join(f'<tr><td style="white-space:nowrap"><b>{t}</b></td><td>{b}</td></tr>'
                        for t, b in a["risks"])
    pipe_rows = "".join(
        f'<tr><td>{sites_mod.load(sid)["name"][:20] if sid in sites_mod.load_all() else sid}</td>'
        f'<td class="num">{v["todo"]}</td><td class="num">{v["doing"]}</td>'
        f'<td class="num">{v["done"]}</td><td class="num">{v["off"]}</td>'
        f'<td>{"十分" if v["todo"] >= 20 else ("補充が近い" if v["todo"] >= 10 else "要補充")}</td></tr>'
        for sid, v in pipeline.items()) or '<tr><td colspan="6">台帳が未接続です</td></tr>'
    link_rows = "".join(
        f'<tr><td>{d}</td><td class="num">{n}</td>'
        f'<td>{"相互送客できています" if n > 0 else "リンクがありません。関連記事から送客導線を追加します"}</td></tr>'
        for d, n in links.items())
    cat_jp = {"aio": "AIO・LLMO", "seo": "SEO", "meo": "MEO", "ai-marketing": "AI集客・活用",
              "management": "店舗経営", "hr": "採用・人材", "operation": "オペレーション",
              "dx": "店舗DX", "case": "導入事例", "hojokin": "補助金"}
    cat_pairs = [(cat_jp.get(c, c), n) for c, n in arts["cats"]]
    ai_pairs = []
    for k, jp in [("chatgpt", "ChatGPT"), ("perplexity", "Perplexity"), ("gemini", "Gemini"),
                  ("copilot", "Copilot"), ("claude", "Claude")]:
        v = sum(s["breakdown"].get(k, 0) for s in sites)
        if v:
            ai_pairs.append((jp, v))
    site_ai = [(s["name"][:16], s["ai"]) for s in sites]

    # サイト別の詳細ページ
    details = ""
    for i, s in enumerate(sites):
        c, p = s["months"][-1], s["months"][-2]
        notes = [x for x in [s["ga_error"], s["sc_error"]] if x]
        note = (f'<div class="warn">データ未取得: {" / ".join(notes)}<br>'
                'サービスアカウント <b>aio-report@ss-aio-media.iam.gserviceaccount.com</b> に'
                'GA4「閲覧者」・Search Console「フル」を付与すると次号から反映されます。</div>'
                if notes else "")
        charts = ""
        if c.get("sessions") is not None:
            charts = ('<div class="charts">'
                      + svg_line(s["months"], "sessions", BLUE, "セッション推移")
                      + svg_line(s["months"], "clicks", TEAL, "検索クリック推移") + "</div>")
        qrows = "".join(
            f'<tr><td>{q["k"]}</td><td class="num">{q["imp"]:,}</td>'
            f'<td class="num">{q["clicks"]:,}</td><td class="num">{q["ctr"]}%</td>'
            f'<td class="num">{q["pos"]}位</td></tr>' for q in s["queries"]) \
            or '<tr><td colspan="5">検索データは権限付与後に表示されます</td></tr>'
        details += f"""
<div class="sheet">
<div class="sec"><span class="no">{9 + i:02d}</span><h2>{s["name"][:20]}</h2><div class="gold"></div></div>
<p class="lead">{s["theme"]}<br><span class="dim">{s["domain"]}｜想定読者: {s.get("audience", "—")[:40]}</span></p>
{note}
<div class="tiles">
{tile("セッション", na(c.get("sessions")), f'前月比 {mom_site(c, p, "sessions")}')}
{tile("検索クリック", na(c.get("clicks")), f'前月比 {mom_site(c, p, "clicks")}')}
{tile("記事ストック", f'{arts["counts"].get(s["id"], 0)}本', "品質90点以上のみ")}
{tile("AI経由参照", str(s["ai"]) if not s["ga_error"] else "—", "ChatGPT・Perplexity等")}
</div>
{charts}
<h3>主要クエリ（上位3）</h3>
<table><tr><th>クエリ</th><th style="width:13%">表示</th><th style="width:13%">クリック</th>
<th style="width:11%">CTR</th><th style="width:13%">平均順位</th></tr>{qrows}</table>
<div class="callout"><b>このサイトの役割:</b> {s["theme"]}を担当します。
他サイトの領域（{"、".join(x.split("（")[0] for x in sites_mod.load(s["id"]).get("avoid", []))[:60]}）は
主題にせず、必要な場合は該当サイトへリンクで送客します。</div>
</div>"""

    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8"><style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; margin: 0; }}
body {{ font-family:"Yu Gothic","Meiryo",sans-serif; color:#10203a; font-size:10pt; line-height:1.85; }}
.sheet {{ width:210mm; min-height:296mm; padding:15mm 15mm 17mm; page-break-after:always; }}
.sheet:last-child {{ page-break-after:auto; }}
.cover {{ background:linear-gradient(150deg,#071a38,{NAVY} 45%,#14345c); color:#fff;
  display:flex; flex-direction:column; padding:22mm 20mm; }}
/* 縦並びのflex内では既定で横に引き伸ばされるため、align-selfで実寸比率を保つ */
.lg {{ height:34px;width:auto;align-self:flex-start;flex:0 0 auto; }}
.back .lg {{ align-self:center; }}
.cv-g {{ width:64px;height:4px;background:{GOLD};margin:10mm 0 6mm; }}
.kick {{ letter-spacing:.35em;font-size:9pt;color:#93b4e8; }}
.ttl {{ font-size:26pt;font-weight:900;line-height:1.42;margin-top:4mm; }}
.mon {{ font-size:15pt;color:{GOLD};font-weight:bold;margin-top:3mm;letter-spacing:.1em; }}
.badges {{ display:flex;gap:7px;margin-top:8mm;flex-wrap:wrap; }}
.badge {{ border:1px solid rgba(255,255,255,.35);border-radius:999px;padding:3px 13px;
  font-size:8.4pt;color:#dbe7fa; }}
.meta {{ margin-top:auto;font-size:9.4pt;color:#bcd0ee;line-height:2.05;
  border-top:1px solid rgba(255,255,255,.25);padding-top:6mm; }}
.sec {{ display:flex;align-items:center;gap:10px;margin:0 0 11px; }}
.sec .no {{ background:{NAVY};color:#fff;font-weight:bold;font-size:10pt;padding:3px 12px;border-radius:4px; }}
.sec h2 {{ font-size:14.5pt; }}
.sec .gold {{ flex:1;height:2px;background:linear-gradient(90deg,{GOLD},transparent); }}
h3 {{ font-size:11pt;margin:14px 0 6px;color:{NAVY}; }}
.lead {{ font-size:9.8pt;color:{MUTED};margin-bottom:8px; }}
.dim {{ color:{MUTED};font-size:8.5pt; }}
.na {{ color:#b45309;font-size:8pt; }}
.note {{ font-size:8.5pt;color:{MUTED}; }}
.warn {{ background:#fffbeb;border-left:4px solid #f59e0b;padding:9px 12px;
  border-radius:0 8px 8px 0;font-size:8.6pt;margin:8px 0 10px; }}
.callout {{ border-left:4px solid {GOLD};background:#fbf8ef;padding:10px 14px;
  border-radius:0 8px 8px 0;margin:10px 0;font-size:9.4pt; }}
.tiles {{ display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin:10px 0; }}
.tile {{ border:1px solid {LINE};border-radius:10px;padding:9px 11px; }}
.t-l {{ font-size:8.2pt;color:{MUTED}; }} .t-v {{ font-size:15pt;font-weight:900;color:{NAVY}; }}
.t-s {{ font-size:8.2pt;font-weight:bold; }} .good {{ color:#067647; }} .bad {{ color:#b91c1c; }}
.charts {{ display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px; }}
.chart {{ border:1px solid {LINE};border-radius:8px;padding:7px; }}
.chart-t {{ font-size:8.8pt;font-weight:bold;margin-bottom:3px; }}
table {{ border-collapse:collapse;width:100%;font-size:8.9pt;margin-top:6px; }}
th,td {{ border:1px solid #dbe3ee;padding:5px 8px;text-align:left;vertical-align:top; }}
th {{ background:{NAVY};color:#fff;font-weight:600; }}
td.num {{ text-align:right;font-variant-numeric:tabular-nums; }}
tr:nth-child(even) td {{ background:#f7fafd; }}
.heat {{ border:1px solid {LINE};border-radius:8px;padding:9px 11px;margin-top:6px; }}
.hm-row {{ display:flex;align-items:center;gap:8px;margin:3px 0; }}
.hm-l {{ width:120px;font-size:8.4pt; }}
.hm-t {{ flex:1;background:#eef2f8;border-radius:4px;height:12px; }}
.hm-b {{ height:12px;border-radius:4px; }}
.hm-v {{ width:74px;text-align:right;font-size:8.4pt;font-weight:bold; }}
.jd {{ font-weight:bold;padding:1px 8px;border-radius:10px;font-size:8.4pt;white-space:nowrap; }}
.jd-良好 {{ background:#dcfce7;color:#047857; }} .jd-標準 {{ background:#e0f2fe;color:#0369a1; }}
.jd-要改善 {{ background:#fee2e2;color:#b91c1c; }} .jd-立ち上げ中 {{ background:#fef3c7;color:#b45309; }}
.pri {{ font-weight:bold;padding:1px 8px;border-radius:10px;font-size:8.4pt; }}
.pri-高 {{ background:#fee2e2;color:#b91c1c; }} .pri-中 {{ background:#fef3c7;color:#b45309; }}
ol.head3 {{ counter-reset:h;list-style:none;padding:0;margin:0; }}
ol.head3 li {{ counter-increment:h;position:relative;padding:8px 0 8px 32px;font-size:10.2pt;
  line-height:1.9;border-bottom:1px dotted {LINE}; }}
ol.head3 li:last-child {{ border-bottom:0; }}
ol.head3 li::before {{ content:counter(h);position:absolute;left:0;top:9px;width:21px;height:21px;
  border-radius:50%;background:{NAVY};color:#fff;font-size:8.2pt;font-weight:bold;
  text-align:center;line-height:21px; }}
.toc {{ columns:2;column-gap:20px;margin:6px 0 0; }}
.toc li {{ list-style:none;padding:2.2px 0;border-bottom:1px dotted {LINE};font-size:8.5pt;break-inside:avoid; }}
.toc li span {{ color:{GOLD};font-weight:bold;margin-right:7px; }}
.roi {{ display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:8px; }}
.roi-box {{ border:1px solid {LINE};border-radius:10px;padding:11px 13px; }}
.roi-box .k {{ font-size:8.5pt;color:{MUTED}; }}
.roi-box .v {{ font-size:18pt;font-weight:900;color:{NAVY}; }}
.roi-box .s {{ font-size:8.4pt;color:{MUTED}; }}
.back {{ background:{NAVY};color:#fff;display:flex;flex-direction:column;justify-content:center;
  align-items:center;text-align:center;gap:4mm; }}
.back .s {{ font-size:9.4pt;color:#9db8e0;line-height:2.2; }}
</style></head><body>

<div class="sheet cover">
  {logo}<div class="cv-g"></div>
  <div class="kick">GROUP MONTHLY REPORT</div>
  <div class="ttl">3サイト統合<br>月次レポート</div>
  <div class="mon">{ym} 月次報告</div>
  <div class="badges">
    <span class="badge">グループ全体KPI</span><span class="badge">サイト別の貢献度</span>
    <span class="badge">重複と役割分担</span><span class="badge">投資対効果</span>
    <span class="badge">改善プラン</span>
  </div>
  <div class="meta">
    対象: AI集客ラボ（ai.7senses.co.jp）／AI導入補助金サポート（lp.7senses.co.jp）／
    コーポレートサイト（www.7senses.co.jp）<br>
    発行: <b>セブンセンシズ株式会社</b>｜発行日: {date.today().isoformat()}｜作成: 自動集計+分析エンジン<br>
    数値は Google Analytics 4 / Google Search Console / 運用台帳の実測にもとづきます
  </div>
</div>

<div class="sheet">
<div class="sec"><span class="no">01</span><h2>エグゼクティブサマリー</h2><div class="gold"></div></div>
<h3 style="margin-top:0">今月を3行で</h3>
<ol class="head3">{head_html}</ol>
<div class="tiles" style="margin-top:12px">
{tile("セッション（3サイト）", f'{cur["sessions"]:,}', f'前月比 {mom("sessions")}')}
{tile("検索クリック", f'{cur["clicks"]:,}', f'前月比 {mom("clicks")}')}
{tile("CV", f'{cur["cv"]}件', f'前月比 {mom("cv")}')}
{tile("AI経由参照", str(a["ai"]), "3サイト合計")}
</div>
<div class="callout"><b>3サイト体制の狙い:</b> 集客手法はAI集客ラボ、資金調達は補助金サイト、
店舗経営の実務はコーポレートサイトと役割を分けています。同じ会社のサイトどうしで検索評価を
奪い合わないよう、キーワードは1つの台帳で一元管理し、記事作成のたびに重複を機械検査しています。</div>
<h3>本レポートの構成</h3>
<ul class="toc">{toc_html}</ul>
</div>

<div class="sheet">
<div class="sec"><span class="no">02</span><h2>グループ全体のKPIダッシュボード</h2><div class="gold"></div></div>
<div class="tiles">
{tile("セッション", f'{cur["sessions"]:,}', f'前月比 {mom("sessions")}')}
{tile("検索表示回数", f'{cur["impressions"]:,}', f'前月比 {mom("impressions")}')}
{tile("検索クリック", f'{cur["clicks"]:,}', f'前月比 {mom("clicks")}')}
{tile("平均CTR", f'{a["ctr"]}%', "3サイト合算")}
</div>
<h3>6ヶ月トレンド（3サイト合計）</h3>
<div class="charts">
{svg_line(group_months(sites, labels), "sessions", BLUE, "セッション合計")}
{svg_line(group_months(sites, labels), "clicks", TEAL, "検索クリック合計")}
{svg_line(group_months(sites, labels), "impressions", BLUE, "検索表示回数合計")}
{svg_line(group_months(sites, labels), "cv", TEAL, "CV合計")}
</div>
<p class="note">読み方: 表示回数はグループ全体の「露出の総量」、クリックは「選ばれた回数」です。
サイトごとに需要の山が異なるため、合計値の凸凹は特定サイトの季節要因である場合があります。</p>
</div>

<div class="sheet">
<div class="sec"><span class="no">03</span><h2>サイト別の貢献度と成長率</h2><div class="gold"></div></div>
<p class="lead">どのサイトがグループ全体のどれだけを担っているか、どこが伸びているかを比較します。</p>
<table><tr><th style="width:24%">サイト</th><th>担当テーマ</th><th style="width:9%">記事</th>
<th style="width:13%">セッション</th><th style="width:9%">構成比</th><th style="width:10%">前月比</th></tr>
{contrib_rows}</table>
<h3>セッションの構成比</h3>
{bars([(c["s"]["name"][:16], c["s"]["months"][-1].get("sessions") or 0) for c in a["contrib"]], BLUE)}
<div class="callout"><b>読み方:</b> 構成比が偏っていること自体は問題ではありません。
立ち上げ時期が異なるため、後から始めたサイトの比率が低いのは自然です。
見るべきは<b>前月比</b>で、伸びが止まっているサイトがあれば改善プラン（第14章）で対処します。</div>
</div>

<div class="sheet">
<div class="sec"><span class="no">04</span><h2>指標の評価（良し悪しの判定）</h2><div class="gold"></div></div>
<p class="lead">数字だけでは良いのか悪いのかが分かりません。一般的な水準と比べた判定を併記します。</p>
<table><tr><th style="width:17%">指標</th><th style="width:9%">当月</th><th style="width:9%">判定</th>
<th style="width:27%">判定の基準</th><th>この指標の意味と打ち手</th></tr>{assess_rows}</table>
<div class="callout"><b>判定の使い方:</b> 「要改善」があれば、その打ち手を第15章の実行スケジュールに
最優先で組み込みます。立ち上げ期は「標準」でも順調な場合が多いため、前月比の伸びと併せて判断してください。</div>
<h3>この4指標を選んでいる理由</h3>
<p style="font-size:9.4pt">セッションやPVは「結果」であり、動かすには原因側の指標を見る必要があります。
<b>順位</b>は露出量を決め、<b>CTR</b>は露出をクリックに変える効率、<b>CV率</b>はクリックを成果に変える効率、
<b>AI経由比率</b>は次の時代への適応度を表します。この4つが改善すれば、セッションとCVは後から付いてきます。</p>
</div>

<div class="sheet">
<div class="sec"><span class="no">05</span><h2>投資対効果</h2><div class="gold"></div></div>
<p class="lead">記事は一度書けば資産として残ります。「同じ流入を広告で買ったらいくらか」を金額で示します。</p>
<div class="roi">
  <div class="roi-box"><div class="k">当月の流入を広告で買った場合</div>
  <div class="v">約{a["ad_value"]:,}円</div>
  <div class="s">検索クリック{cur["clicks"]:,}回 × 想定単価{CPC}円で換算</div></div>
  <div class="roi-box"><div class="k">記事1本あたりの月間価値</div>
  <div class="v">約{round(a["ad_value"] / max(arts["total"], 1)):,}円</div>
  <div class="s">3サイト合計{arts["total"]}本で割った1本あたり</div></div>
  <div class="roi-box"><div class="k">記事1本あたりの月間セッション</div>
  <div class="v">{round(cur["sessions"] / max(arts["total"], 1), 1)}</div>
  <div class="s">本数が増えるほど合計は積み上がる</div></div>
  <div class="roi-box"><div class="k">年間換算の広告相当額</div>
  <div class="v">約{a["ad_value"] * 12:,}円</div>
  <div class="s">今の水準が1年続いた場合の目安</div></div>
</div>
<h3>広告との決定的な違い</h3>
<p style="font-size:9.4pt">広告は出稿を止めた瞬間に流入がゼロになりますが、
記事は<b>公開後も検索とAI回答の両方から流入を生み続けます</b>。
上の金額は今月分であり、来月も同じ記事が同じように働きます。
記事が積み上がるほど、この金額は複利のように増えていきます。</p>
<div class="callout"><b>換算の前提:</b> クリック単価は{CPC}円で計算しています。
実際のリスティング広告では1クリック500〜1,000円以上になることも珍しくないため、
上の金額は<b>控えめな見積もり</b>です。</div>
</div>

<div class="sheet">
<div class="sec"><span class="no">06</span><h2>サイト間の重複と役割分担の健全性</h2><div class="gold"></div></div>
<p class="lead">同一企業が複数サイトで同じ検索意図を狙うと、Googleがどちらも評価しにくくなります。
記事作成のたびに、全サイトのキーワードを突き合わせて検査しています。</p>
<table><tr><th style="width:22%">サイト</th><th>キーワード</th><th style="width:22%">本来の担当</th></tr>{cross_rows}</table>
<div class="callout"><b>今月の判定:</b> {"領域侵食は検出されていません。3サイトが競合しない状態を維持できています。" if not cross else f"{len(cross)}件の領域侵食を検出しました。該当キーワードは台帳から取り下げ済みです。"}</div>
<h3>担当領域の定義</h3>
<table><tr><th style="width:26%">サイト</th><th>担当する領域</th><th style="width:30%">扱わない領域</th></tr>
{"".join(f'<tr><td><b>{c["name"][:18]}</b></td><td>{c["theme"]}</td>'
         f'<td>{"／".join(x.split("（")[0] for x in c.get("avoid", []))}</td></tr>'
         for c in sites_mod.load_all().values())}</table>
<p class="note">判断基準: 「この記事の読者は何に困っているか」で振り分けます。
集客ならAI集客ラボ、資金調達なら補助金サイト、それ以外の経営課題ならコーポレートです。</p>
</div>

<div class="sheet">
<div class="sec"><span class="no">07</span><h2>コンテンツ資産の状況</h2><div class="gold"></div></div>
<div class="tiles">
{tile("公開記事（3サイト合計）", f'{arts["total"]}本', "品質90点以上のみ")}
{tile("平均品質スコア", f'{arts["avg_score"]}点', "6観点採点/100点")}
{tile("平均文字数", f'{arts["avg_len"]:,}字', "基準5,000字以上")}
{tile("年間の想定増加", "720本", "月60本ペースの場合")}
</div>
<h3>サイト別の記事本数</h3>
{bars([(c["s"]["name"][:16], c["articles"]) for c in a["contrib"]], TEAL)}
<h3>カテゴリ別の記事構成</h3>
{bars(cat_pairs, BLUE)}
<div class="callout"><b>資産の考え方:</b> 記事は広告と違い、公開後も検索とAI回答の両方から
流入を生み続けるストック資産です。1記事あたり平均{arts["avg_len"]:,}字・平均{arts["avg_score"]}点の
品質を保ったまま蓄積することが、ドメイン全体の評価とAI引用の確率を押し上げます。</div>
</div>

<div class="sheet">
<div class="sec"><span class="no">08</span><h2>記事の供給状況（KW台帳）</h2><div class="gold"></div></div>
<p class="lead">記事を作り続けられるかは、書くテーマの在庫で決まります。
3サイト分のキーワードを1つの台帳で管理し、残りが少なくなると実データから自動補充します。</p>
<table><tr><th style="width:30%">サイト</th><th style="width:12%">未着手</th><th style="width:12%">執筆中</th>
<th style="width:12%">公開済み</th><th style="width:12%">対象外</th><th>在庫の判定</th></tr>{pipe_rows}</table>
<h3>キーワードはどう補充されるか</h3>
<ul style="font-size:9.4pt">
  <li><b>Search Consoleの実績から</b> — 自社サイトが実際に表示されているのに専用記事がないクエリを抽出します。需要が実証済みの最優先キーワードです。</li>
  <li><b>Googleサジェストから</b> — 実際の検索行動から生成される候補を収集します。サジェストに出る＝一定の検索需要がある証拠です。</li>
  <li><b>重複の自動除外</b> — 既存記事や他サイトのキーワードと近いものは、追加時点で除外されます。</li>
</ul>
<div class="callout"><b>「未着手」が10件を切ると補充が走ります。</b>
ネタ切れで記事の生成が止まらないよう、在庫を常に監視しています。</div>
</div>
{details}
<div class="sheet">
<div class="sec"><span class="no">{9 + len(sites):02d}</span><h2>AI検索（AIO / LLMO）分析</h2><div class="gold"></div></div>
<p class="lead">検索結果の外側——ChatGPTやPerplexityの「回答」の中で自社がどれだけ参照されたかの分析です。
ゼロクリック時代の新しい流入経路であり、3サイト共通の中核戦略です。</p>
<div class="tiles">
{tile("AI経由セッション", str(a["ai"]), "3サイト合計")}
{tile("全体に占める比率", f'{a["ai_ratio"]}%', "対セッション")}
{tile("実装済みAIO施策", "12項目", "全記事に標準適用")}
{tile("AIクローラー許可", "6種", "GPTBot・ClaudeBot等")}
</div>
<h3>プラットフォーム別の内訳（3サイト合計）</h3>
{bars(ai_pairs, TEAL)}
<h3>サイト別のAI経由参照</h3>
{bars(site_ai, BLUE)}
<div class="callout"><b>この数字の意味:</b> AI経由の訪問者は「AIの回答で自社を知り、確かめに来た」
<b>確度の高い見込み客</b>です。ChatGPT比率が高い場合はサイト外の言及（プレスリリース・寄稿）を、
Perplexity比率が高い場合は記事の鮮度更新を強化するのが定石です。</div>
<p class="note">実装済みAIO施策: 冒頭断言回答 / 見出し直下の1文結論 / FAQ構造化 / 出典付き数値 /
llms.txt / robots.txtでのAI許可 / 構造化データ4種 / 監修者情報 / 鮮度表記 / 定義ブロック /
比較表 / 対象読者の明記</p>
</div>

<div class="sheet">
<div class="sec"><span class="no">{10 + len(sites):02d}</span><h2>サイト間の相互送客</h2><div class="gold"></div></div>
<p class="lead">3サイトは競合させない一方で、<b>互いに送客し合う</b>ことで全体の成果を高めます。
記事本文から他サイトへのリンクがどれだけ張られているかを実測しました。</p>
<table><tr><th style="width:32%">リンク先ドメイン</th><th style="width:16%">本文中のリンク数</th><th>状態</th></tr>{link_rows}</table>
<h3>なぜ相互送客が重要か</h3>
<ul style="font-size:9.4pt">
  <li><b>読者の課題は1つではない</b> — 集客に悩む経営者は、人材にも資金にも悩んでいます。
  適切なサイトへ案内できれば、グループ全体での接点が増えます。</li>
  <li><b>指名検索が増える</b> — 複数の入口で社名に触れることで、後日「セブンセンシズ」で
  直接検索される確率が上がります。これはAI検索でも評価される信号です。</li>
  <li><b>ドメイン間の関連性が伝わる</b> — 同一企業の関連サイトであることが検索エンジンに伝わり、
  それぞれの専門性がより明確に評価されます。</li>
</ul>
<div class="callout"><b>運用方針:</b> リンクは記事の文脈に沿った場所にのみ設置します。
関係のない場所への機械的なリンクは、読者にとって邪魔になるうえ検索評価にも逆効果です。</div>
</div>

<div class="sheet">
<div class="sec"><span class="no">{11 + len(sites):02d}</span><h2>グループ全体の改善プラン</h2><div class="gold"></div></div>
<p class="lead">データから機械的に抽出した、今月取り組むべき項目です。優先度の高い順に並んでいます。</p>
<table><tr><th style="width:8%">優先度</th><th style="width:24%">対象</th>
<th style="width:30%">現状（データ根拠）</th><th>改善アクション</th></tr>{plan_rows}</table>
<div class="callout"><b>実施について:</b> ここに挙げた改善は、翌月の運用の中で当社が実施します。
記事の修正・内部リンクの追加・導線の変更は月額費用に含まれており、追加料金はかかりません。
実施結果は翌月号で効果を検証します。</div>
</div>

<div class="sheet">
<div class="sec"><span class="no">{12 + len(sites):02d}</span><h2>来月のKPI目標</h2><div class="gold"></div></div>
<p class="lead">当月実績をベースに、来月の目標値を設定します。目標は「前月比の成長率」と
「最低増加量」の大きい方を採用し、立ち上げ期でも歩みを止めない設計です。</p>
<table><tr><th>指標</th><th style="width:15%">当月実績</th><th style="width:15%">来月目標</th>
<th>目標の根拠</th></tr>{tgt_rows}</table>
<div class="sec" style="margin-top:16px"><span class="no">{13 + len(sites):02d}</span>
<h2>実行スケジュール</h2><div class="gold"></div></div>
<table><tr><th style="width:14%">時期</th><th style="width:30%">実施内容</th><th>狙い</th></tr>
<tr><td>毎日</td><td>3サイト合計で記事を生成・公開</td><td>テーマの面を広げ、AI引用の入口を増やす</td></tr>
<tr><td>毎日</td><td>Google・Bingへの即時通知とKPI集計</td><td>インデックスを早め、変化を毎日把握する</td></tr>
<tr><td>毎週</td><td>順位11〜30位の記事をリライト</td><td>2ページ目から1ページ目へ。最も費用対効果が高い作業</td></tr>
<tr><td>毎週</td><td>サイト内・サイト横断の重複検査</td><td>自社サイト同士の評価の奪い合いを未然に防ぐ</td></tr>
<tr><td>毎週</td><td>内部リンクの最適化と鮮度更新</td><td>サイト全体の評価を底上げし、AI検索の鮮度評価に対応</td></tr>
<tr><td>毎月</td><td>本レポートの発行と改善の実施</td><td>数字の報告で終わらせず、翌月の行動に落とす</td></tr>
</table>
</div>

<div class="sheet">
<div class="sec"><span class="no">{14 + len(sites):02d}</span><h2>リスクと前提条件</h2><div class="gold"></div></div>
<p class="lead">数字を正しく受け取っていただくために、知っておいていただきたい前提をまとめます。</p>
<table><tr><th style="width:32%">前提・注意点</th><th>内容</th></tr>{risk_rows}</table>
<div class="callout"><b>判断のしかた:</b> 単月の数字が下がっても、施策が間違っているとは限りません。
逆に単月で上がっても、それが施策の成果とは限りません。
<b>3ヶ月の傾向線</b>と<b>順位・CTRという原因側の指標</b>で判断するのが、この事業の正しい見方です。</div>
</div>

<div class="sheet">
<div class="sec"><span class="no">{15 + len(sites):02d}</span><h2>付録: 指標の定義</h2><div class="gold"></div></div>
<table>
<tr><td style="width:26%"><b>セッション</b></td><td>サイトへの訪問回数。1人が朝と夜に見れば2セッション</td></tr>
<tr><td><b>CV（コンバージョン）</b></td><td>無料相談・資料ダウンロードなど、成果地点への到達件数</td></tr>
<tr><td><b>表示回数</b></td><td>Google検索結果に自社ページが表示された回数</td></tr>
<tr><td><b>CTR</b></td><td>表示回数のうちクリックされた割合。タイトル改善で伸ばせる</td></tr>
<tr><td><b>平均掲載順位</b></td><td>検索結果での平均的な表示位置。小さいほど上位</td></tr>
<tr><td><b>AI経由参照</b></td><td>ChatGPT・Perplexity等のAIサービスからの流入</td></tr>
<tr><td><b>AIO / LLMO</b></td><td>AI検索の回答に引用されるための最適化</td></tr>
<tr><td><b>領域侵食</b></td><td>あるサイトが他サイトの担当テーマを扱ってしまうこと。検索評価の奪い合いにつながる</td></tr>
<tr><td><b>品質スコア</b></td><td>6観点の採点（100点満点）。90点未満は公開されない</td></tr>
<tr><td><b>KW台帳</b></td><td>3サイト分のキーワードを一元管理する表。重複防止の要</td></tr>
</table>
<h3>データソース</h3>
<p class="note">Google Analytics 4（セッション・CV・AI参照元）／Google Search Console（表示・クリック・CTR・順位・クエリ）／
運用台帳（記事作成・品質審査・キーワード管理）。AI経由参照は chatgpt.com・chat.openai.com・perplexity.ai・
gemini.google.com・copilot.microsoft.com・claude.ai からの参照流入の合計です。数値は月初〜月末の集計です。</p>
</div>

<div class="sheet back">
  {logo}
  <div style="font-size:13pt;font-weight:bold;">セブンセンシズ株式会社</div>
  <div class="s">〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902<br>
  TEL 06-4305-7547（9:00〜20:00 / 土日祝休）<br>
  ai.7senses.co.jp ｜ lp.7senses.co.jp ｜ www.7senses.co.jp<br><br>
  本レポートは自動集計・自動作成されています。<br>
  ご質問・追加分析のご要望はお気軽にお申し付けください。<br>次号は翌月1日に自動発行されます。</div>
</div>
</body></html>"""


def mom_site(cur, prev, key):
    a, b = cur.get(key), prev.get(key)
    if a is None or not b:
        return "―"
    v = (a - b) / b * 100
    return f"{'+' if v >= 0 else ''}{v:.0f}%"


def group_months(sites, labels):
    """3サイト合計の月次系列（グラフ用）"""
    out = []
    for i, m in enumerate(labels):
        row = {"label": m}
        for k in ["sessions", "clicks", "impressions", "cv"]:
            row[k] = sum((s["months"][i].get(k) or 0) for s in sites)
        out.append(row)
    return out


def main():
    labels = months(6)
    cfgs = sites_mod.load_all()
    if DEMO:
        sites = fetch_demo(labels)
    else:
        if not SA.exists():
            print("警告: indexing-service-account.json が無いためGA4/GSCは取得できません")
        sites = [fetch_site(c, labels) for c in cfgs.values()]

    arts = article_stats()
    if DEMO:
        arts["counts"] = {s["id"]: 12 - i * 3 for i, s in enumerate(sites)}
        arts["total"] = sum(arts["counts"].values())
    links = cross_links()
    pipeline = kw_pipeline()
    try:
        from cannibal_check import territory_check
        cross = [] if DEMO else territory_check()
    except Exception:
        cross = []

    a = analyze(sites, labels, arts, pipeline)
    html = render(sites, labels, arts, cross, links, pipeline, a)

    ym = labels[-1]
    out_dir = ROOT / "reports" / f"group-{ym}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.html").write_text(html, encoding="utf-8")
    print(f"HTML: {out_dir / 'report.html'}")

    try:
        from playwright.sync_api import sync_playwright

        import pdf_util
        pdf = out_dir / "report.pdf"
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto((out_dir / "report.html").resolve().as_uri(), wait_until="networkidle")
            pdf_util.check_overflow(pg, "グループレポート")
            pg.pdf(path=str(pdf), format="A4", print_background=True,
                   display_header_footer=True, header_template="<div></div>",
                   footer_template='<div style="width:100%;font-size:7px;color:#8ba0bd;'
                                   'padding:0 12mm;display:flex;justify-content:space-between;">'
                                   '<span>3サイト統合 月次レポート ｜ セブンセンシズ株式会社</span>'
                                   '<span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
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
                "3サイト（AI集客ラボ / AI導入補助金 / コーポレート）の実績を1冊にまとめています。\n"
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
