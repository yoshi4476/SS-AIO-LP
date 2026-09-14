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
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "reports" / "weekly"
NAVY, MUTED, ACCENT = "#0b2447", "#6b7c93", "#1967d2"
GOOD, WARN = "#137333", "#b06000"


def weeks(n):
    """直近n週の区切り。GSCの確定は3日前まで"""
    end = date.today() - timedelta(days=3)
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
    for site in sorted(conf):
        n = 0
        for k in todo:
            if k.get("site") != site:
                continue
            kw = str(k.get("keyword", "")).strip()
            if not kw:
                continue
            v, pt, why = kw_intent.verdict(kw)
            out.append({"site": site, "kw": kw, "aim": str(k.get("aim", "")),
                        "priority": str(k.get("priority", "")),
                        "verdict": v, "point": pt, "why": why})
            n += 1
            if n >= limit:
                break
    return out


CSS = """body{font-family:'Hiragino Kaku Gothic ProN','Yu Gothic',sans-serif;
color:#0b2447;background:#f4f7fb;margin:0;padding:28px}
.wrap{max-width:780px;margin:0 auto;background:#fff;padding:34px 38px;border-radius:14px;
box-shadow:0 2px 16px rgba(11,36,71,.07)}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.1rem;margin:34px 0 10px;
padding-left:10px;border-left:4px solid #1967d2}
.sub{color:#6b7c93;font-size:.82rem;margin:0 0 6px}
table{border-collapse:collapse;width:100%;font-size:.84rem;margin:10px 0}
th,td{border:1px solid #e3eaf3;padding:7px 9px;text-align:left}
th{background:#0b2447;color:#fff;font-weight:600}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.chart{margin:14px 0 6px}.chart-t{font-weight:700;font-size:.9rem;margin-bottom:4px}
svg{width:100%;height:auto}
.legend{font-size:.78rem;color:#6b7c93;margin:4px 0 0}
.note{font-size:.76rem;color:#6b7c93;margin:2px 0 0}
.tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:.72rem;font-weight:700}
.t-strong{background:#e6f4ea;color:#137333}.t-mid{background:#f1f3f4;color:#5f6368}
.t-weak{background:#fce8e6;color:#c5221f}
.kpi{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
.kpi div{flex:1;min-width:130px;background:#f4f7fb;border-radius:10px;padding:12px 14px}
.kpi b{display:block;font-size:1.35rem}
.kpi span{font-size:.76rem;color:#6b7c93}"""


def html(ws, site_rows, kw_pos, picks, conf, funnel_txt):
    labels = [f"{s.month}/{s.day}" for s, _ in ws]
    h = [f'<!doctype html><meta charset="utf-8"><title>週次レポート {ws[-1][1]}</title>',
         f"<style>{CSS}</style><div class='wrap'>",
         f"<h1>週次レポート</h1>",
         f"<p class='sub'>集計: {ws[0][0]} 〜 {ws[-1][1]}（{len(ws)}週）／"
         f"作成: {date.today()}／出典: Search Console・GA4の実測</p>"]

    tot = [sum(site_rows[s][i]["imp"] for s in site_rows) for i in range(len(ws))]
    clk = [sum(site_rows[s][i]["clk"] for s in site_rows) for i in range(len(ws))]
    d_i = tot[-1] - tot[-2] if len(tot) > 1 else 0
    d_c = clk[-1] - clk[-2] if len(clk) > 1 else 0
    h.append(f"""<div class='kpi'>
<div><b>{tot[-1]:,}</b><span>今週の表示（前週比 {d_i:+,}）</span></div>
<div><b>{clk[-1]:,}</b><span>今週のクリック（前週比 {d_c:+,}）</span></div>
<div><b>{tot[-1] and clk[-1]/tot[-1]*100:.2f}%</b><span>クリック率</span></div></div>""")

    h.append("<h2>1. 表示とクリックの推移</h2>")
    h.append(svg_bars(labels, tot, "週ごとの表示回数（3サイト合計）"))
    h.append(svg_bars(labels, clk, "週ごとのクリック数（3サイト合計）", GOOD))

    h.append("<h2>2. 主要キーワードの順位推移</h2>")
    for site, c in sorted(conf.items()):
        # 直近週の表示が多い語を選ぶ。少ない語は線が飛んで読めない
        cand = [(k, v) for (s, k), v in kw_pos.items() if s == site]
        cand = [(k, v) for k, v in cand if sum(1 for x in v if x) >= max(2, len(ws) // 3)]
        cand.sort(key=lambda kv: min(x for x in kv[1] if x))
        top = dict(cand[:5])
        h.append(f"<h3 style='font-size:.95rem;margin:18px 0 2px'>{esc(c.get('name', site))}</h3>")
        h.append(svg_rank(labels, top, "順位の推移（上ほど上位）"))

    if picks:
        h.append("<h2>3. 次に狙う検索語と、選んだ理由</h2>")
        h.append("<p class='note'>管制塔の台帳で「未着手」の語です。"
                 "同じ順位でもクリック率は5倍違うため、"
                 "検索結果で用が済む語かどうかを機械で判定しています。</p>")
        h.append("<table><thead><tr><th>サイト</th><th>検索語</th><th>狙い</th>"
                 "<th>開く理由</th><th>判定の根拠</th></tr></thead><tbody>")
        cls = {"強": "t-strong", "並": "t-mid", "弱": "t-weak"}
        for p in picks:
            h.append(f"<tr><td>{esc(p['site'])}</td><td>{esc(p['kw'])[:34]}</td>"
                     f"<td>{esc(p['aim'])[:16]}</td>"
                     f"<td><span class='tag {cls[p['verdict']]}'>{p['verdict']}</span>"
                     f" {p['point']:+d}</td><td>{esc(p['why'])[:34]}</td></tr>")
        h.append("</tbody></table>")
        weak = [p for p in picks if p["verdict"] == "弱"]
        if weak:
            h.append(f"<p class='note'>「弱」が{len(weak)}件あります。"
                     "検索結果に答えが出た時点で用が済む語です。"
                     "書くなら、検索結果には出せないもの（違反例・失敗例・自社の実測）を"
                     "タイトルに置いてください。</p>")

    if funnel_txt:
        h.append("<h2>4. リード導線の通過率</h2><pre style='font-size:.8rem;"
                 "background:#f4f7fb;padding:12px;border-radius:8px;overflow-x:auto'>"
                 + esc(funnel_txt) + "</pre>")

    h.append("<h2>サイト別の内訳</h2><table><thead><tr><th>サイト</th>"
             "<th>今週の表示</th><th>クリック</th><th>平均順位</th><th>前週比（表示）</th>"
             "</tr></thead><tbody>")
    for site, c in sorted(conf.items()):
        r = site_rows[site]
        d = r[-1]["imp"] - r[-2]["imp"] if len(r) > 1 else 0
        h.append(f"<tr><td>{esc(c.get('name', site))}</td>"
                 f"<td class='num'>{r[-1]['imp']:,}</td><td class='num'>{r[-1]['clk']:,}</td>"
                 f"<td class='num'>{r[-1]['pos']:.1f}位</td><td class='num'>{d:+,}</td></tr>")
    h.append("</tbody></table></div>")
    return "\n".join(h)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=8)
    a = ap.parse_args()

    conf = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "sites").glob("*.json")}
    ws = weeks(a.weeks)
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
    print(f"  期間 {ws[0][0]} 〜 {ws[-1][1]} / 狙う語 {len(picks)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
