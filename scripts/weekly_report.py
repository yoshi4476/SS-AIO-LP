# -*- coding: utf-8 -*-
"""週次レポート。月1回では、直した結果が出たのか分からないまま次の月に入る。

月次レポートは月末にまとめて出るため、途中で手を打てない。
週単位で順位・表示・クリックの折れ線を見れば、直した翌週に効いたかが分かる。

出すもの:
  1. 主要キーワードの順位推移（週ごとの折れ線。上に行くほど上位）
  2. 表示・クリックの週次推移
  3. 今週どのキーワードで新しく順位が付いたか
  4. リード導線の通過率

  python scripts/weekly_report.py            # 直近8週
  python scripts/weekly_report.py --weeks 12
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "reports" / "weekly"
NAVY, MUTED, ACCENT = "#0b2447", "#6b7c93", "#1967d2"
GOOD, WARN = "#137333", "#b06000"


def weeks(n, until=None):
    """n週ぶんの区切り。GSCの確定は3日前まで。

    until を渡すと過去の週まで遡って作れる。後から振り返るとき、
    そのときの数字で出せないと比較にならない。
    """
    end = until or (date.today() - timedelta(days=3))
    end -= timedelta(days=(end.weekday() + 1) % 7)      # 直近の土曜で切る
    out = []
    for i in range(n - 1, -1, -1):
        e = end - timedelta(days=7 * i)
        out.append((e - timedelta(days=6), e))
    return out


def sc_client():
    import gcreds
    from googleapiclient.discovery import build
    return build("searchconsole", "v1", credentials=gcreds.load(
        ROOT / "indexing-service-account.json",
        ["https://www.googleapis.com/auth/webmasters.readonly"]))


def query(sc, domain, s, e, dims=None, limit=25000):
    body = {"startDate": s.isoformat(), "endDate": e.isoformat(), "rowLimit": limit}
    if dims:
        body["dimensions"] = dims
    try:
        return sc.searchanalytics().query(
            siteUrl=f"https://{domain}/", body=body).execute().get("rows", [])
    except Exception:
        return []


def svg_rank(labels, series, title):
    """順位の折れ線。順位は小さいほど良いので、上下を反転して描く。

    普通の折れ線と同じ向きで描くと、改善したときに線が下がる。
    読む人が毎回「これは良いのか悪いのか」と考えることになる。
    """
    alive = {k: v for k, v in series.items() if any(x for x in v)}
    if not alive:
        return '<p style="color:%s">この期間に順位のついたデータがありません</p>' % MUTED
    W, H, PL, PB, PT = 700, 300, 44, 34, 18
    vals = [x for v in alive.values() for x in v if x]
    lo, hi = max(1, min(vals) - 2), min(60, max(vals) + 2)
    rng = (hi - lo) or 1

    def xy(i, v):
        x = PL + i * (W - PL - 90) / max(1, len(labels) - 1)
        y = PT + (v - lo) / rng * (H - PB - PT)      # 上位ほど上に来る
        return x, y

    grid, ticks = "", ""
    for g in range(5):
        v = lo + rng * g / 4
        y = PT + (v - lo) / rng * (H - PB - PT)
        grid += f'<line x1="{PL}" y1="{y:.0f}" x2="{W-90}" y2="{y:.0f}" stroke="#e3eaf3"/>'
        ticks += (f'<text x="{PL-6}" y="{y+4:.0f}" font-size="10" fill="{MUTED}"'
                  f' text-anchor="end">{v:.0f}位</text>')
    colors = [ACCENT, "#c5221f", GOOD, WARN, "#7b1fa2", "#00838f"]
    body, legend = "", ""
    for n, (name, vs) in enumerate(sorted(alive.items())):
        c = colors[n % len(colors)]
        pts = [(xy(i, v)) for i, v in enumerate(vs) if v]
        if len(pts) >= 2:
            body += (f'<path d="M{" L".join(f"{x:.0f} {y:.0f}" for x, y in pts)}"'
                     f' fill="none" stroke="{c}" stroke-width="2.4" stroke-linejoin="round"/>')
        body += "".join(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="3.5" fill="{c}"/>'
                        for x, y in pts)
        if pts:
            body += (f'<text x="{W-84}" y="{pts[-1][1]+4:.0f}" font-size="10" fill="{c}">'
                     f'{name[:11]}</text>')
        legend += (f'<span style="color:{c}">■</span> {name[:18]}　')
    xlab = "".join(
        f'<text x="{xy(i,lo)[0]:.0f}" y="{H-10}" font-size="9.5" fill="{MUTED}"'
        f' text-anchor="middle">{l}</text>' for i, l in enumerate(labels))
    return (f'<div class="chart"><div class="chart-t">{title}</div>'
            f'<svg viewBox="0 0 {W} {H}">{grid}{ticks}{body}{xlab}</svg>'
            f'<p class="legend">{legend}</p>'
            f'<p class="note">上にあるほど上位です。順位は小さいほど良いため、'
            f'線が上がっていれば改善しています。</p></div>')


def svg_bars(labels, values, title, color=ACCENT, unit=""):
    if not any(values):
        return '<p style="color:%s">データなし</p>' % MUTED
    W, H, PL, PB, PT = 700, 250, 46, 34, 16
    mx = max(values) * 1.15 or 1
    bw = (W - PL - 16) / len(values) * 0.62
    bars, xlab = "", ""
    for i, v in enumerate(values):
        x = PL + i * (W - PL - 16) / len(values) + (W - PL - 16) / len(values) * 0.19
        h = (v / mx) * (H - PB - PT)
        bars += (f'<rect x="{x:.0f}" y="{H-PB-h:.0f}" width="{bw:.0f}" height="{h:.0f}"'
                 f' fill="{color}" rx="3"/>'
                 f'<text x="{x+bw/2:.0f}" y="{H-PB-h-5:.0f}" font-size="10"'
                 f' fill="{NAVY}" text-anchor="middle">{v:,}{unit}</text>')
        xlab += (f'<text x="{x+bw/2:.0f}" y="{H-10}" font-size="9.5" fill="{MUTED}"'
                 f' text-anchor="middle">{labels[i]}</text>')
    grid = "".join(f'<line x1="{PL}" y1="{H-PB-(H-PB-PT)*g/4:.0f}" x2="{W-16}"'
                   f' y2="{H-PB-(H-PB-PT)*g/4:.0f}" stroke="#e3eaf3"/>' for g in range(5))
    return (f'<div class="chart"><div class="chart-t">{title}</div>'
            f'<svg viewBox="0 0 {W} {H}">{grid}{bars}{xlab}</svg></div>')


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def collect(sc, conf, ws):
    """週ごとに、サイト別の合計と検索語別の順位を集める"""
    site_rows, kw_pos = {}, {}
    for site, c in sorted(conf.items()):
        d = c["domain"]
        tot = []
        for s, e in ws:
            r = query(sc, d, s, e)
            if r:
                x = r[0]
                tot.append({"imp": int(x["impressions"]), "clk": int(x["clicks"]),
                            "pos": x["position"]})
            else:
                tot.append({"imp": 0, "clk": 0, "pos": 0})
        site_rows[site] = tot
        for i, (s, e) in enumerate(ws):
            for x in query(sc, d, s, e, ["query"]):
                k = x["keys"][0]
                kw_pos.setdefault((site, k), [None] * len(ws))[i] = x["position"]
    return site_rows, kw_pos


def picked_keywords(conf, limit=8):
    """いま狙っている検索語と、なぜそれを選んだのか。

    結果の数字だけでは進捗にならない。次に何を書くかが決まっていて、
    その理由が説明できることまで含めて進捗である。
    """
    import kw_intent
    out = []
    try:
        import hub_client
        if not hub_client.enabled():
            return out
        rows = hub_client.all_kw() or []
    except Exception:
        return out
    todo = [k for k in rows if str(k.get("status", "")).strip() == "未着手"]
    try:
        import kw_plan
        metrics = {site: kw_plan.plan_metrics(site) for site in conf}
    except Exception:
        metrics = {}
    for site in sorted(conf):
        n = 0
        for k in todo:
            if k.get("site") != site:
                continue
            kw = str(k.get("keyword", "")).strip()
            if not kw:
                continue
            v, pt, why = kw_intent.verdict(kw)
            # 検索数・難易度は計画ファイルから（台帳のAPIは note を返さない）
            vol, kd, _ = metrics.get(site, {}).get(re.sub(r"[\s　]+", "", kw).lower(), (None, None, ""))
            out.append({"site": site, "kw": kw, "aim": str(k.get("aim", "")),
                        "priority": str(k.get("priority", "")),
                        "vol": vol, "kd": kd,
                        "verdict": v, "point": pt, "why": why})
            n += 1
            if n >= limit:
                break
    return out


CSS = """
@page { size: A4; margin: 0; }
* { box-sizing: border-box; margin: 0; }
:root { --navy:#0b2447; --blue:#1967d2; --teal:#00838f; --gold:#b7922e;
        --muted:#6b7c93; --line:#e3eaf3; }
body { font-family:"Yu Gothic","Meiryo",sans-serif; color:#10203a;
       font-size:10pt; line-height:1.8; }
.sheet { width:210mm; min-height:296mm; padding:16mm 15mm 18mm;
         page-break-after:always; position:relative; }
.sheet:last-child { page-break-after:auto; }
.cover-page { background:linear-gradient(150deg,#071a38 0%,#0b2447 45%,#14345c 100%);
  color:#fff; display:flex; flex-direction:column; padding:22mm 20mm; }
.cv-gold { width:64px; height:4px; background:var(--gold); margin:10mm 0 6mm; }
.cv-kicker { letter-spacing:.35em; font-size:9pt; color:#93b4e8; }
.cv-title { font-size:27pt; font-weight:bold; line-height:1.4; margin-top:4mm; }
.cv-month { font-size:15pt; color:var(--gold); font-weight:bold; margin-top:3mm;
            letter-spacing:.1em; }
.cv-meta { margin-top:auto; font-size:9.5pt; color:#bcd0ee; line-height:2.1;
           border-top:1px solid rgba(255,255,255,.25); padding-top:6mm; }
.cv-meta b { color:#fff; }
.cv-badges { display:flex; gap:8px; margin-top:8mm; flex-wrap:wrap; }
.cv-badge { border:1px solid rgba(255,255,255,.35); border-radius:999px;
            padding:3px 14px; font-size:8.5pt; color:#dbe7fa; }
.sec { display:flex; align-items:center; gap:10px; margin:0 0 12px;
       page-break-after:avoid; }
.sec .no { background:var(--navy); color:#fff; font-weight:bold; font-size:10pt;
           padding:3px 12px; border-radius:4px; letter-spacing:.08em; }
.sec h2 { font-size:14.5pt; }
.sec .gold { flex:1; height:2px;
             background:linear-gradient(90deg,var(--gold),transparent); }
h3 { font-size:11pt; margin:14px 0 6px; color:var(--navy); }
.note { font-size:8.5pt; color:var(--muted); }
table { border-collapse:collapse; width:100%; font-size:9pt; margin:8px 0; }
th,td { border:1px solid var(--line); padding:5px 8px; text-align:left; }
th { background:var(--navy); color:#fff; font-weight:600; font-size:8.5pt; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.hl-cards { display:flex; gap:10px; margin:10px 0 4px; }
.hl { flex:1; border:1px solid var(--line); border-top:3px solid var(--blue);
      border-radius:8px; padding:10px 12px; }
.hl .k { font-size:8.5pt; color:var(--muted); }
.hl .v { font-size:16pt; font-weight:bold; color:var(--navy); }
.hl .s { font-size:8.5pt; color:var(--teal); font-weight:bold; }
.chart { margin:10px 0 4px; page-break-inside:avoid; }
.chart-t { font-weight:700; font-size:10pt; color:var(--navy); margin-bottom:3px; }
svg { width:100%; height:auto; }
.legend { font-size:8pt; color:var(--muted); margin:3px 0 0; }
.tag { display:inline-block; padding:1px 7px; border-radius:10px;
       font-size:8pt; font-weight:700; }
.t-strong { background:#e6f4ea; color:#137333; }
.t-mid { background:#f1f3f4; color:#5f6368; }
.t-weak { background:#fce8e6; color:#c5221f; }
"""


def effect_rows(days=30):
    """直した記事が、その後どうなったか。

    「対策した」と「効果があった」は別物である。直した日を起点に
    前後で同じ日数を比べれば、効いたかどうかが数字で出る。
    """
    try:
        import effect
        rows = effect.collect(days)
    except Exception:
        return [], []
    done = [r for r in rows if "before" in r]
    done.sort(key=lambda r: -(r["after"][0] - r["before"][0]))
    waiting = [r for r in rows if "wait" in r]
    return done[:7], waiting


def cover(ws):
    """表紙。月次レポートと同じ体裁に揃える"""
    return f"""<div class="sheet cover-page">
<div class="cv-kicker">WEEKLY REPORT</div>
<div class="cv-gold"></div>
<div class="cv-title">週次レポート<br>検索順位と導線の推移</div>
<div class="cv-month">{ws[-1][1]} まで（直近{len(ws)}週）</div>
<div class="cv-badges"><span class="cv-badge">順位の推移</span>
<span class="cv-badge">表示・クリック</span>
<span class="cv-badge">次に狙う検索語</span>
<span class="cv-badge">リード導線</span></div>
<div class="cv-meta">対象: <b>AI集客ラボ / セブンセンシズ コーポレート / AI導入補助金サポート</b><br>
集計期間: <b>{ws[0][0]} 〜 {ws[-1][1]}</b>　｜　作成: {date.today()}<br>
出典: Search Console・GA4の実測値（推計値は使用していません）<br>
発行: セブンセンシズ株式会社</div></div>"""


def html(ws, site_rows, kw_pos, picks, conf, funnel_txt):
    labels = [f"{s.month}/{s.day}" for s, _ in ws]
    tot = [sum(site_rows[s][i]["imp"] for s in site_rows) for i in range(len(ws))]
    clk = [sum(site_rows[s][i]["clk"] for s in site_rows) for i in range(len(ws))]
    d_i = tot[-1] - tot[-2] if len(tot) > 1 else 0
    d_c = clk[-1] - clk[-2] if len(clk) > 1 else 0
    ctr = clk[-1] / tot[-1] * 100 if tot[-1] else 0

    h = ['<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">',
         f"<title>週次レポート {ws[-1][1]}</title><style>{CSS}</style></head><body>",
         cover(ws),
         f"""<div class="sheet">
<div class="sec"><span class="no">01</span><h2>今週の要点</h2><div class="gold"></div></div>
<div class="hl-cards">
<div class="hl"><div class="k">今週の表示回数</div><div class="v">{tot[-1]:,}</div>
<div class="s">前週比 {d_i:+,}</div></div>
<div class="hl"><div class="k">今週のクリック</div><div class="v">{clk[-1]:,}</div>
<div class="s">前週比 {d_c:+,}</div></div>
<div class="hl"><div class="k">クリック率</div><div class="v">{ctr:.2f}%</div>
<div class="s">3サイト合計</div></div></div>
<p class="note">月の合計では月中の動きが見えません。週単位なら、直した翌週に効いたかが分かります。</p>
<div class="sec" style="margin-top:14px"><span class="no">02</span>
<h2>表示とクリックの推移</h2><div class="gold"></div></div>
{svg_bars(labels, tot, "週ごとの表示回数（3サイト合計）")}
{svg_bars(labels, clk, "週ごとのクリック数（3サイト合計）", GOOD)}
</div>"""]

    n = 3
    for site, c in sorted(conf.items()):
        cand = [(k, v) for (s, k), v in kw_pos.items() if s == site]
        cand = [(k, v) for k, v in cand if sum(1 for x in v if x) >= max(2, len(ws) // 3)]
        cand.sort(key=lambda kv: min(x for x in kv[1] if x))
        r = site_rows[site]
        prev = r[-2] if len(r) > 1 else {"imp": 0, "clk": 0, "pos": 0}
        h.append(f"""<div class="sheet">
<div class="sec"><span class="no">{n:02d}</span>
<h2>{esc(c.get("name", site))} の順位推移</h2><div class="gold"></div></div>
{svg_rank(labels, dict(cand[:5]), "主要キーワードの順位（上ほど上位）")}
<h3>今週の実績</h3>
<table><tr><th style="width:30%">指標</th><th>今週</th><th>前週</th><th>差</th></tr>
<tr><td>表示回数</td><td class="num">{r[-1]["imp"]:,}</td>
<td class="num">{prev["imp"]:,}</td><td class="num">{r[-1]["imp"] - prev["imp"]:+,}</td></tr>
<tr><td>クリック</td><td class="num">{r[-1]["clk"]:,}</td>
<td class="num">{prev["clk"]:,}</td><td class="num">{r[-1]["clk"] - prev["clk"]:+,}</td></tr>
<tr><td>平均順位</td><td class="num">{r[-1]["pos"]:.1f}位</td>
<td class="num">{prev["pos"]:.1f}位</td>
<td class="num">{r[-1]["pos"] - prev["pos"]:+.1f}</td></tr></table>
</div>""")
        n += 1

    if picks:
        cls = {"強": "t-strong", "並": "t-mid", "弱": "t-weak"}
        rows = "".join(
            f'<tr><td>{esc(p["site"])}</td><td>{esc(p["kw"])[:30]}</td>'
            f'<td>{esc(p["aim"])[:14]}</td>'
            f'<td class="num">{p["vol"] if p.get("vol") is not None else "—"}'
            f' / {p["kd"] if p.get("kd") is not None else "—"}</td>'
            f'<td><span class="tag {cls[p["verdict"]]}">{p["verdict"]}</span>'
            f' {p["point"]:+d}</td>'
            f'<td>{esc(p["why"])[:28]}</td></tr>' for p in picks[:18])
        weak = len([p for p in picks if p["verdict"] == "弱"])
        note = ("" if not weak else
                f'<p class="note">「弱」が{weak}件あります。検索結果に答えが出た時点で'
                "用が済む語です。書くなら、検索結果には出せないもの"
                "（違反例・失敗例・自社の実測）をタイトルに置いてください。</p>")
        h.append(f"""<div class="sheet">
<div class="sec"><span class="no">{n:02d}</span>
<h2>次に狙う検索語と、選んだ理由</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">台帳で「未着手」の語です。同じ順位でもクリック率は5倍違うため、
<b>検索結果で用が済む語かどうか</b>を機械で判定しています。</p>
<table><tr><th style="width:12%">サイト</th><th>検索語</th>
<th style="width:14%">狙い</th><th style="width:12%">月間 / 難易度</th><th style="width:12%">開く理由</th>
<th style="width:22%">判定の根拠</th></tr>{rows}</table>{note}
</div>""")
        n += 1


    done, waiting = effect_rows()
    if done:
        rows = ""
        advice = []
        for r in done:
            bi, bc, bp = r["before"]
            ai, ac, ap_ = r["after"]
            dp = (bp - ap_) if (bp and ap_) else 0
            rows += (f'<tr><td>{esc(r["slug"])[:26]}</td><td>{r["when"]}</td>'
                     f'<td class="num">{bi}→{ai}</td><td class="num">{bc}→{ac}</td>'
                     f'<td class="num">{dp:+.1f}</td></tr>')
            for q, i, c, pos in r["queries"][:1]:
                rows += (f'<tr><td colspan="2" style="padding-left:18px;color:#6b7c93">'
                         f'↳ {esc(q)[:30]}</td><td class="num">{i}</td>'
                         f'<td class="num">{c}</td><td class="num">{pos:.1f}位</td></tr>')
            # 改善の指示は数字から導く。感想を書かない
            if ai >= 20 and ac == 0 and ap_ and ap_ <= 20.5:
                advice.append(f"{r['slug']}: 表示{ai}でクリック0。"
                              f"{ap_:.0f}位まで来ているので、タイトルに"
                              "「検索結果に出せないもの」を置く")
            elif ai >= 20 and ap_ and ap_ > 20.5:
                advice.append(f"{r['slug']}: 表示{ai}だが{ap_:.0f}位。"
                              "内部リンクを足して順位を上げる")
            elif ai < bi:
                advice.append(f"{r['slug']}: 表示が{bi}から{ai}へ減った。"
                              "直した内容が検索意図とずれていないか見直す")
        adv = ""
        if advice:
            adv = ("<h3>次にやること</h3><ul style='font-size:9pt'>"
                   + "".join(f"<li>{esc(x)}</li>" for x in advice[:6]) + "</ul>")
        h.append(f"""<div class="sheet">
<div class="sec"><span class="no">{n:02d}</span>
<h2>直した記事の効果</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">直した日を起点に、前後で同じ日数を比べています。
<b>「対策した」と「効果があった」は別</b>なので、数字で確かめます。
順位は改善を正の値で表示しています。</p>
<table><tr><th>記事 / キーワード</th><th style="width:15%">直した日</th>
<th style="width:15%">表示</th><th style="width:14%">クリック</th>
<th style="width:12%">順位改善</th></tr>{rows}</table>
{adv}
<p class="note">直した効果のほかに、季節や競合の動きも混ざります。
1本ごとの増減より全体の傾向で見てください。
判定待ち（直してから7日未満）が{len(waiting)}本あります。</p>
</div>""")
        n += 1
    if funnel_txt:
        h.append(f"""<div class="sheet">
<div class="sec"><span class="no">{n:02d}</span>
<h2>リード導線の通過率</h2><div class="gold"></div></div>
<p style="font-size:9.5pt">記事を読んだ人が、どこで離れているかです。
<b>前の段階に対する割合</b>で見ます。</p>
<pre style="font-size:8.5pt;background:#f6f9fd;border:1px solid var(--line);
padding:10px 14px;border-radius:8px;white-space:pre-wrap">{esc(funnel_txt)}</pre>
<p class="note">段階は入れ子ではないため、通過率が100%を超えることがあります。
診断結果のメール送信のように、フォームを開かずに送信まで至る経路があるためです。</p>
</div>""")

    h.append("</body></html>")
    return "\n".join(h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--until", default="", help="この日までで区切る（YYYY-MM-DD）")
    a = ap.parse_args()

    conf = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "sites").glob("*.json")}
    until = date.fromisoformat(a.until) if a.until else None
    ws = weeks(a.weeks, until)
    sc = sc_client()
    site_rows, kw_pos = collect(sc, conf, ws)
    picks = picked_keywords(conf)

    funnel_txt = ""
    try:
        import subprocess
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "funnel.py")],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=300)
        funnel_txt = r.stdout.strip()
    except Exception:
        pass

    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{ws[-1][1].isoformat()}.html"
    f.write_text(html(ws, site_rows, kw_pos, picks, conf, funnel_txt),
                 encoding="utf-8", newline="")
    print(f"週次レポート: {f.relative_to(ROOT).as_posix()}")

    # PDFにする。HTMLのまま渡すと、受け取った環境の文字コード判定によっては
    # 日本語が化ける。実際、メールで送った週次が文字化けした。
    pdf = f.with_suffix(".pdf")
    try:
        from playwright.sync_api import sync_playwright
        import pdf_util
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            pg = b.new_page()
            pg.goto(f.as_uri())
            pg.wait_for_timeout(400)
            pdf_util.check_overflow(pg, "週次レポート")
            pg.pdf(path=str(pdf), format="A4", print_background=True,
                   display_header_footer=True, header_template="<span></span>",
                   footer_template=(
                       '<div style="width:100%;font-size:7px;color:#8ba0bd;'
                       'padding:0 12mm;display:flex;justify-content:space-between;">'
                       '<span>週次レポート ｜ セブンセンシズ株式会社</span>'
                       '<span><span class="pageNumber"></span> / '
                       '<span class="totalPages"></span></span></div>'),
                   margin={"top": "0", "bottom": "10mm", "left": "0", "right": "0"})
            b.close()
        print(f"PDF: {pdf.relative_to(ROOT).as_posix()}")
    except Exception as e:
        print(f"PDFにできませんでした（HTMLは作成済み）: {str(e)[:90]}")
    print(f"  期間 {ws[0][0]} 〜 {ws[-1][1]} / 狙う語 {len(picks)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
