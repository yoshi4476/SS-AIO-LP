# -*- coding: utf-8 -*-
"""採点（3観点と総合）が公開後の成果を当てているかを、月1回照合する（月次CI の月初）。

**なぜ要るか**: 公開の可否は rubric.py の3観点で決めているが、点数が成果を当てているかを定期に確かめる仕組みが無かった。
自社のデータでは「品質の点数は順位と逆」という結果が過去に出ている（0.3節）。validate_rules（週次）は総合点を区分で
並べるだけで、観点ごと・サイトごと・2つの方法の突き合わせ・公開からの日数の絞り込みを持たない。

材料（新しい Search Console の呼び出しはしない）:
  data/ranks/<site>.pages.json  rank_track が毎日残すページ単位の28日（page 次元。query 次元の合計は使わない）
  data/ranks/<site>.json        同じ日の語×ページ。指名検索（brand_search.pattern_for）の分をページから引く
  GA4                           AI 経由の訪問（着地ページ別・1サイト1回）。鍵が無ければ飛ばす。判定には使わない（件数が少ない）

対象: 自社のサイトの公開済みの記事で、測る28日の初日より min_age 日以上前に公開したもの（お客様の社は見ない）。
点数は原稿の score・score_breakdown。3観点の内訳がある記事（今の基準）と、旧基準の内訳の記事（総合点だけ・参考）を分ける。

判定（観点 × 成果。成果はクリックと平均順位で判定し、表示と CTR は参考）:
  方法A  Spearman の順位相関。|ρ| が max(0.2, 1.96/√(n−1)) 以上なら向きあり
  方法B  点数の上位3分の1と下位3分の1で成果の中央値を比べる（境目が同じ点に重なれば、その点より上と下）
  両方が「良い向き」 → 当てている。両方が良い向きでない → 当てていない（両方逆なら「逆向き」）。食い違えば判断できない
  母数が min_n 本未満・クリックのある記事が少ない・2群に分けられない → 判断できない
  点数の幅が狭い（上下10%点の差が6点未満）ときの無相関は見かけの恐れがあるので判断できない（逆向きはそのまま出す）

出し方: 明細（記事ごとの点と成果）は非公開の置き場の reports/score_cal/<年-月>.json・.md。ログには件数と結論だけ。
今の基準の観点が「当てていない」ときだけ `要対応:` を出す。rubric.py の重みと基準は変えない（人が判断する）。
最後の行は SCORE_CAL_OK=yes/no（8.7）。動かなかったときだけ 1 で終わる。

  python scripts/score_calibrate.py
  python scripts/score_calibrate.py --min-n 30 --min-age 28 --no-ga4
"""
import argparse
import json
import math
import statistics as st
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import rubric as R  # noqa: E402

SA = ROOT / "indexing-service-account.json"
RANKS = ROOT / "data" / "ranks"
WINDOW = 28
MIN_N = 30
MIN_AGE = 28
MIN_GROUP = 8
MIN_NONZERO = 10
MIN_IMP = 5
NARROW = 6.0
RHO_MIN = 0.2
AXIS_KEYS = [a["key"] for a in R.AXES]
NAMES = {**{a["key"]: a["name"] for a in R.AXES}, "total": "総合"}
METRICS = {"clk": "クリック（指名検索を除く）", "pos": "平均順位", "imp": "表示", "ctr": "CTR"}
JUDGED = ("clk", "pos")
TOL = {"clk": 0.0, "imp": 0.0, "ctr": 0.0, "pos": 1.0}
KINDS = {"v3": "今の基準の3観点", "old": "旧基準の総合点（参考・判定に使わない）"}
UNKNOWN, HIT, MISS = "判断できない", "当てている", "当てていない"


def _ranks(v):
    order = sorted(range(len(v)), key=v.__getitem__)
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x, y):
    if len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = st.fmean(rx), st.fmean(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else None


def method_a(pairs):
    rho = spearman([s for s, _ in pairs], [o for _, o in pairs])
    if rho is None:
        return None, None
    cut = max(RHO_MIN, 1.96 / math.sqrt(len(pairs) - 1))
    return ("+" if rho >= cut else "-" if rho <= -cut else "0"), rho


def method_b(pairs, tol):
    q1, q2 = st.quantiles([s for s, _ in pairs], n=3)
    if q1 < q2:
        lo, hi = [o for s, o in pairs if s <= q1], [o for s, o in pairs if s >= q2]
    else:
        # 3分の1の境目が同じ点に重なる（半数が95点など）。重なった点の記事を除き、それより下と上で比べる
        lo, hi = [o for s, o in pairs if s < q1], [o for s, o in pairs if s > q2]
    if len(lo) < MIN_GROUP or len(hi) < MIN_GROUP:
        return None, None, None
    mh, ml = st.median(hi), st.median(lo)
    return ("+" if mh - ml > tol else "-" if ml - mh > tol else "0"), mh, ml


def value(r, metric):
    """成果の値。大きいほど良いにそろえる（順位は符号を反転）"""
    if metric in ("clk", "imp"):
        return r[metric]
    if r["imp"] < MIN_IMP:
        return None
    if metric == "ctr":
        return r["clk"] / r["imp"]
    return -r["pos"] if r.get("pos") else None


def judge(rows, axis, metric):
    pairs = [(r["scores"][axis], value(r, metric)) for r in rows if axis in r["scores"]]
    pairs = [(s, o) for s, o in pairs if o is not None]
    n = len(pairs)
    out = {"n": n, "verdict": UNKNOWN, "a": None, "rho": None, "b": None, "med_hi": None, "med_lo": None,
           "spread": None, "reason": ""}
    if n < MIN_N:
        out["reason"] = f"母数{n}本（{MIN_N}本未満）"
        return out
    scores = [s for s, _ in pairs]
    dec = st.quantiles(scores, n=10)
    out["spread"] = round(dec[-1] - dec[0], 1)
    out["a"], rho = method_a(pairs)
    out["rho"] = None if rho is None else round(rho, 3)
    out["b"], out["med_hi"], out["med_lo"] = method_b(pairs, TOL[metric])
    if metric in ("clk", "ctr") and sum(1 for _, o in pairs if o > 0) < MIN_NONZERO:
        out["reason"] = f"クリックのあった記事が{sum(1 for _, o in pairs if o > 0)}本（{MIN_NONZERO}本未満）"
        return out
    a, b = out["a"], out["b"]
    if a is None or b is None:
        out["reason"] = "点数が重なり、上位と下位の2群に分けられない"
        return out
    if a == "+" and b == "+":
        out["verdict"], out["reason"] = HIT, "2つの方法がそろって良い向き"
    elif a != "+" and b != "+":
        if a == b == "-":
            out["verdict"], out["reason"] = MISS, "2つの方法がそろって逆向き"
        elif out["spread"] < NARROW:
            out["reason"] = f"点数の幅が狭い（上下10%点の差{out['spread']}点）。無相関は見かけの恐れ"
        else:
            out["verdict"], out["reason"] = MISS, "2つの方法がそろって良い向きでない"
    else:
        out["reason"] = f"2つの方法が食い違う（A {a}・B {b}）"
    return out


def combine(per_metric):
    """観点の結論。判定に使う成果（クリック・順位）で当てている／当てていないが混ざれば判断できない"""
    vs = {per_metric[m]["verdict"] for m in JUDGED if m in per_metric}
    if MISS in vs and HIT not in vs:
        return MISS
    if HIT in vs and MISS not in vs:
        return HIT
    return UNKNOWN


def _norm(u):
    p = urlsplit(u.split("#")[0].split("?")[0].strip())
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip('/')}"


def _merge(items):
    """{URL: [表示, クリック, 順位×表示]}。末尾のスラッシュ違いは1つにまとめる"""
    out = {}
    for u, imp, clk, pos in items:
        v = out.setdefault(_norm(u), [0, 0, 0.0])
        v[0] += imp
        v[1] += clk
        v[2] += pos * imp
    return out


def pages(site):
    """(ページの28日の成果, 期間の初日, 終わりの日, 指名検索の分, 指名に使った語×ページの日)。控えが無ければ None"""
    import brand_search as B
    try:
        pg = json.loads((RANKS / f"{site}.pages.json").read_text(encoding="utf-8"))
        end = date.fromisoformat(pg["end"])
    except (OSError, ValueError, KeyError):
        return None
    cur = _merge((u, int(v[0]), int(v[1]), float(v[2] or 0)) for u, v in (pg.get("cur") or {}).items())
    brand, day = {}, ""
    pat = B.pattern_for(site)
    try:
        hist = json.loads((RANKS / f"{site}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hist = {}
    if hist and pat:
        want = (end + timedelta(days=3)).isoformat()
        day = want if want in hist else sorted(hist)[-1]
        brand = _merge((r["url"], int(r["imp"]), int(r["clicks"]), float(r["pos"]))
                       for r in hist[day] if pat.search(r.get("kw") or ""))
    return cur, end - timedelta(days=WINDOW - 1), end, brand, day


def ai_sessions(cfg, start, end):
    """GA4 の AI 経由のセッション {着地パス: 回数}。鍵か設定が無ければ None"""
    prop = "".join(c for c in str(cfg.get("ga4_property_id") or "") if c.isdigit())
    if not prop or not SA.is_file():
        return None
    import daily_kpi as K
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
    c = BetaAnalyticsDataClient(credentials=gcreds.load(SA, ["https://www.googleapis.com/auth/analytics.readonly"]))
    rep = c.run_report(RunReportRequest(
        property=f"properties/{prop}", date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        dimensions=[Dimension(name="sessionSource"), Dimension(name="landingPage")],
        metrics=[Metric(name="sessions")], limit=100000))
    out = Counter()
    for r in rep.rows:
        if K.ai_label(r.dimension_values[0].value):
            out[r.dimension_values[1].value.split("?")[0].rstrip("/")] += int(r.metric_values[0].value)
    return out


def collect(site, min_age, ga4=True):
    """自社の1サイトの記事ごとの点と成果。({rows, start, end, skip, ...}) か、順位の控えが無ければ None"""
    import daily_audit as D
    import quality_loop as Q
    import sites as S
    got = pages(site)
    if got is None:
        return None
    cur, start, end, brand, bday = got
    cfg = S.load(site)
    cut = start - timedelta(days=min_age)
    rows, skip = [], Counter()
    for a in D.articles_by_site().get(site, []):
        if not D._is_published(a, need_review=False):
            skip["公開していない"] += 1
            continue
        try:
            pub = date.fromisoformat(str(a.get("date"))[:10])
        except ValueError:
            skip["公開日が読めない"] += 1
            continue
        if pub > cut:
            skip["公開から日が浅い"] += 1
            continue
        meta = Q.meta_of(Q.read(a["slug"]))
        b = meta.get("score_breakdown")
        try:
            total = float(meta.get("score"))
            if isinstance(b, dict) and all(k in b for k in AXIS_KEYS):
                kind, scores = "v3", {**{k: float(b[k]) for k in AXIS_KEYS}, "total": total}
            elif isinstance(b, dict) and b:
                kind, scores = "old", {"total": total}
            else:
                skip["点の内訳が無い"] += 1
                continue
        except (TypeError, ValueError):
            skip["点が読めない"] += 1
            continue
        url = _norm(S.article_url(cfg, {**meta, "slug": a["slug"], "category": a["category"]}))
        imp, clk, posw = cur.get(url, [0, 0, 0.0])
        bi, bc, bp = brand.get(url, [0, 0, 0.0])
        imp, clk, posw = max(0, imp - bi), max(0, clk - bc), max(0.0, posw - bp)
        mod = str(meta.get("modified") or "")[:10]
        rows.append({"slug": a["slug"], "kind": kind, "scores": scores, "date": pub.isoformat(), "url": url,
                     "imp": imp, "clk": clk, "pos": round(posw / imp, 1) if imp else None,
                     "brand_clk": bc, "touched": bool(mod and mod >= start.isoformat()), "ai": None})
    ai_note = "取らない（--no-ga4）"
    if ga4:
        try:
            ai = ai_sessions(cfg, start, end)
            ai_note = "鍵か GA4 の設定が無い" if ai is None else "取れた"
            for r in rows if ai is not None else []:
                r["ai"] = ai.get(urlsplit(r["url"]).path.rstrip("/"), 0)
        except Exception as e:  # noqa: BLE001  AI 経由は参考。取れなくても照合は続ける
            ai_note = f"取れない（{type(e).__name__}）"
    return {"rows": rows, "start": start.isoformat(), "end": end.isoformat(), "skip": dict(skip),
            "brand_day": bday, "ai_note": ai_note}


def analyse(rows):
    out = {}
    for kind in KINDS:
        rs = [r for r in rows if r["kind"] == kind]
        axes = AXIS_KEYS + ["total"] if kind == "v3" else ["total"]
        res = {}
        for ax in axes:
            pm = {m: judge(rs, ax, m) for m in METRICS}
            res[ax] = {"verdict": combine(pm), "metrics": pm}
        out[kind] = {"n": len(rs), "touched": sum(1 for r in rs if r["touched"]), "axes": res}
    return out


def _line(ax, res):
    parts = []
    for m in JUDGED:
        j = res["metrics"][m]
        parts.append(f"{METRICS[m]} {j['verdict']}" + (f"（{j['reason']}）" if j["verdict"] == UNKNOWN else
                                                       f"（ρ={j['rho']}・上位{j['med_hi']}／下位{j['med_lo']}）"))
    return f"    {NAMES[ax]}: {res['verdict']} — " + "／".join(parts)


def markdown(result):
    nl = chr(10)
    out = [f"# 採点と成果の照合 {result['at']}", "",
           f"条件: 公開済み・自社のサイトだけ・測る28日の初日より{result['min_age']}日以上前に公開・母数{result['min_n']}本未満は判断しない。",
           "方法A＝Spearman の順位相関、方法B＝点数の上位3分の1と下位3分の1の中央値。両方が同じ向きのときだけ結論を出す。",
           "クリックと順位は指名検索の分を除いた値。順位と CTR は表示5回以上の記事だけ。", ""]
    for site, s in result["sites"].items():
        if "error" in s:
            out += [f"## {site}", "", s["error"], ""]
            continue
        out += [f"## {site}（{s['start']}〜{s['end']}）", "",
                "除いた記事: " + ("・".join(f"{k} {v}本" for k, v in s["skip"].items()) or "なし") +
                f"　AI 経由（GA4）: {s['ai_note']}", ""]
        for kind, k in s["analysis"].items():
            out += [f"### {KINDS[kind]}（{k['n']}本・期間中に手が入った記事 {k['touched']}本）", "",
                    "| 観点 | 結論 | 成果 | n | 方法A ρ | A | 方法B 上位 | 下位 | B | 点の幅 | 判定 | 理由 |",
                    "|:--|:--|:--|--:|--:|:-:|--:|--:|:-:|--:|:--|:--|"]
            for ax, res in k["axes"].items():
                for m, j in res["metrics"].items():
                    out.append(f"| {NAMES[ax]} | {res['verdict']} | {METRICS[m]} | {j['n']} | {j['rho']} | {j['a']} | "
                               f"{j['med_hi']} | {j['med_lo']} | {j['b']} | {j['spread']} | {j['verdict']} | {j['reason']} |")
            out.append("")
    return nl.join(out) + nl


def main(argv=None):
    global MIN_N
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=MIN_N)
    ap.add_argument("--min-age", type=int, default=MIN_AGE)
    ap.add_argument("--no-ga4", action="store_true")
    a = ap.parse_args(argv)
    MIN_N = a.min_n
    import private_store as PS
    import sites as S
    result = {"at": date.today().isoformat(), "min_n": MIN_N, "min_age": a.min_age, "sites": {}}
    flagged, ran = [], 0
    print(f"■ 採点と成果の照合（母数{MIN_N}本未満は判断しない・公開から{a.min_age}日以上たってからの28日）")
    for site in S.own_ids():
        got = collect(site, a.min_age, ga4=not a.no_ga4)
        if got is None:
            result["sites"][site] = {"error": "順位の控え（data/ranks/<site>.pages.json）が無い"}
            print(f"  {site}: 順位の控えが無いため照合しません")
            continue
        ran += 1
        an = analyse(got["rows"])
        result["sites"][site] = {**{k: v for k, v in got.items() if k != "rows"}, "analysis": an, "rows": got["rows"]}
        print(f"  {site}（{got['start']}〜{got['end']}）: " +
              "・".join(f"{KINDS[k]} {an[k]['n']}本" for k in KINDS) +
              (f"　除いた記事 {sum(got['skip'].values())}本" if got["skip"] else ""))
        for kind in KINDS:
            if not an[kind]["n"]:
                continue
            print(f"   {KINDS[kind]}")
            for ax, res in an[kind]["axes"].items():
                print(_line(ax, res))
                if kind == "v3" and res["verdict"] == MISS:
                    flagged.append(f"{site}: {NAMES[ax]}")
        ai = [r["ai"] for r in got["rows"] if r["ai"] is not None]
        print(f"   AI 経由の訪問（GA4・判定に使わない）: " +
              (f"{sum(1 for x in ai if x)}本に計{sum(ai)}回" if ai else got["ai_note"]))
    if not ran:
        print("  照合できたサイトがありません（順位の控えが無い）")
        return 1
    d = PS.reports_dir() / "score_cal"
    d.mkdir(parents=True, exist_ok=True)
    ym = result["at"][:7]
    (d / f"{ym}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    (d / f"{ym}.md").write_text(markdown(result), encoding="utf-8", newline="\n")
    print(f"  明細は非公開の置き場 reports/score_cal/{ym}.md")
    if flagged:
        print(f"要対応: 採点の観点が公開後の成果を当てていません（{'・'.join(flagged)}）。"
              f"rubric.py の重みと基準は自動では変えません。見直すかを人が判断してください（明細 reports/score_cal/{ym}.md）")
    print("SCORE_CAL_OK=" + ("no" if flagged else "yes"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
