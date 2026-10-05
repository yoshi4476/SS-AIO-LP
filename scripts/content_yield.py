# -*- coding: utf-8 -*-
"""記事を増やした分だけ伸びているかを見張る（記事の出しすぎの検知）

growth_guard は「落ちたか」を見る。ここは「増やした割に伸びていないか」を見る。
記事を毎日出し続けても、検索に出ない記事が積み上がるとサイト全体の評価が薄まり、
1本あたりの表示が下がっていく。その段階では合計はまだ伸びて見えるため、
合計だけを見ていると気づけない。

見るもの（サイトごと・GSC のページ次元・直近28日とその前の28日）
  1. 眠っている記事: 公開30日以上で、28日間の表示が0の記事の割合
  2. 同じ年齢の記事どうしの1本あたり: 直近に公開5〜8週目を終えた記事（今のコホート）と、
     その28日前に公開された記事（前のコホート）の、公開5〜8週目の1本あたり週表示
     （期間の単純比較で「前からある記事の表示が落ちた」を見ると読み違える。どの記事も
      公開1〜3週で表示が山になり、4〜6週で山の約1/4に落ちる（2026-10-05 実測・3サイト共通）。
      記事を早く足した時期ほど「前からある記事」が山から下りる途中にいるため、2026-09 に
      AI集客ラボの既存記事 -34% を食い合いと読んだが、食い合いで新記事に移った表示は
      減り1,413回のうち65回だけだった。公開からの週数をそろえれば、経過の落ち込みは両方に同じだけ入る）

要対応にする条件
  - 眠っている記事が40%を超える（公開30日以上の記事が20本以上あるとき）
  - 今のコホートの1本あたり週表示が、前のコホートより20%以上低い
    （各コホート10本以上・前のコホートの表示が100回以上のときだけ。足りなければ判定しない）
どちらも「新しく書くより、既存記事の統合・書き直しに回す」合図。
期間の単純比較（記事全体の1本あたり・前からある記事の増減）は参考に表示するだけで、判定には使わない。

  python scripts/content_yield.py
  python scripts/content_yield.py --any-flagged   # 統合を増やす週か（終了コード0=増やす）

要対応になったサイトは data/yield_state.json に記録し、週次の統合を2組→4組に増やす
（食い合い・同型記事とも）。新しい記事の本数は減らさない（1日2本のまま。2026-09-28 方針）。
次の週に条件を外れれば自動で戻る。14日より古い記録は使わない。
コホートを判定できなかったサイトは flagged にしない（判定前を「落ちた」と扱わない）。
出す印: YIELD_OK=yes|no|unknown（見つかったら no。どのサイトも判定できなければ unknown。
検査が動かなかったときだけ終了コード1）
"""
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

MATURE_DAYS = 30
ZERO_MAX = 0.40
MIN_MATURE = 20
OLD_DROP = 0.20
MIN_PREV_IMP = 100
AGE_FROM, AGE_TO = 28, 55       # 公開5〜8週目（公開日を0日目とする）
COHORT_DAYS = 28
MIN_COHORT = 10
DAILY_TOL = 0.10                # 日別の合計がページ次元の合計とこれ以上ずれたら判定しない（0.1節）
LIMIT = 25000
STATE = ROOT / "data" / "yield_state.json"
STATE_DAYS = 14


def _fm(p):
    t = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    if not m:
        return None

    def g(k):
        x = re.search(rf"^{k}:\s*(.+)$", m.group(1), re.M)
        return x.group(1).strip().strip('"') if x else ""
    try:
        score = int(g("score") or 0)
    except ValueError:
        score = 0
    return {"slug": p.stem, "category": g("category"), "date": g("date")[:10], "score": score}


def _path(u):
    return urlparse(u).path.rstrip("/") + "/"


def pages(cfg, start, end):
    """ページ次元の表示・クリック。末尾スラッシュ違いで2行に割れるので合算する（0.1節）"""
    import report_verify as RV
    rows = RV._gsc(f"https://{cfg['domain']}/", start.isoformat(), end.isoformat(), ["page"], LIMIT).get("rows", [])
    if len(rows) >= LIMIT:
        raise RuntimeError("ページが上限に達し、取りこぼしがあります")
    out = {}
    for r in rows:
        k = _path(r["keys"][0])
        imp, clk = out.get(k, (0, 0))
        out[k] = (imp + int(r.get("impressions", 0)), clk + int(r.get("clicks", 0)))
    return out


def daily(cfg, start, end):
    """日×ページの表示 {path: {日付: 表示}}。25,000行で切れたまま足すと少なく出るのでページ送りする"""
    import gsc_detail as G
    sc = G.client()
    out, at = {}, 0
    while True:
        body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": ["date", "page"],
                "rowLimit": LIMIT, "startRow": at}
        rows = sc.searchanalytics().query(siteUrl=f"https://{cfg['domain']}/", body=body).execute().get("rows", [])
        for r in rows:
            d = out.setdefault(_path(r["keys"][1]), {})
            d[r["keys"][0]] = d.get(r["keys"][0], 0) + int(r.get("impressions", 0))
        if len(rows) < LIMIT:
            return out
        at += LIMIT


def windows(end):
    """(今のコホートの公開期間, 前のコホートの公開期間)。今のコホートは end の日に公開8週目を終えた記事まで"""
    hi = end - timedelta(days=AGE_TO)
    cur = (hi - timedelta(days=COHORT_DAYS - 1), hi)
    prev = (cur[0] - timedelta(days=COHORT_DAYS), cur[1] - timedelta(days=COHORT_DAYS))
    return cur, prev


def cohort(arts, paths, day, lo, hi):
    """lo〜hi に公開された記事の、公開5〜8週目の表示。(本数, 表示の合計, 1本あたり週表示)"""
    own = [a for a in arts if a["date"] and lo.isoformat() <= a["date"] <= hi.isoformat()]
    tot = 0
    for a in own:
        d0 = date.fromisoformat(a["date"])
        s, e = (d0 + timedelta(days=AGE_FROM)).isoformat(), (d0 + timedelta(days=AGE_TO)).isoformat()
        tot += sum(v for d, v in day.get(paths[a["slug"]], {}).items() if s <= d <= e)
    weeks = (AGE_TO - AGE_FROM + 1) / 7
    return len(own), tot, (tot / len(own) / weeks if own else 0.0)


def site_report(sid, cfg, arts, end):
    import sites as S
    cur = (end - timedelta(days=27), end)
    prev_end = end - timedelta(days=28)
    prev = (prev_end - timedelta(days=27), prev_end)
    pc, pp = pages(cfg, *cur), pages(cfg, *prev)
    paths = {a["slug"]: _path(S.article_url(cfg, a)) for a in arts}

    live_now = [a for a in arts if a["date"] and a["date"] <= end.isoformat()]
    live_prev = [a for a in arts if a["date"] and a["date"] <= prev_end.isoformat()]
    mature = [a for a in arts if a["date"] and a["date"] <= (end - timedelta(days=MATURE_DAYS)).isoformat()]
    zero = [a for a in mature if pc.get(paths[a["slug"]], (0, 0))[0] == 0]
    clicked = [a for a in mature if pc.get(paths[a["slug"]], (0, 0))[1] > 0]
    imp_now = sum(pc.get(paths[a["slug"]], (0, 0))[0] for a in live_now)
    imp_prev = sum(pp.get(paths[a["slug"]], (0, 0))[0] for a in live_prev)
    clk_now = sum(pc.get(paths[a["slug"]], (0, 0))[1] for a in live_now)
    site_imp = sum(v[0] for v in pc.values())
    old_prev = imp_prev
    old_now = sum(pc.get(paths[a["slug"]], (0, 0))[0] for a in live_prev)
    r = {"sid": sid, "name": cfg.get("name", sid), "n_now": len(live_now), "n_prev": len(live_prev),
         "mature": len(mature), "zero": len(zero), "clicked": len(clicked),
         "imp_now": imp_now, "imp_prev": imp_prev, "clk_now": clk_now, "site_imp": site_imp,
         "old_prev": old_prev, "old_now": old_now, "cohort": None, "cohort_why": ""}
    cw, pw = windows(end)
    day = daily(cfg, pw[0] + timedelta(days=AGE_FROM), end)
    # 日別とページ次元で、同じ28日の記事の表示が合うかを先に確かめる（1つの測り方を事実にしない）
    a_ = imp_now
    b_ = sum(sum(v for d, v in day.get(paths[a["slug"]], {}).items() if cur[0].isoformat() <= d <= cur[1].isoformat())
             for a in live_now)
    if max(a_, b_) and abs(a_ - b_) / max(a_, b_) > DAILY_TOL:
        r["cohort_why"] = f"日別の合計（{b_:,}）とページ次元の合計（{a_:,}）が合いません"
        return r
    r["cohort"] = {"cur": [cw[0].isoformat(), cw[1].isoformat(), *cohort(arts, paths, day, *cw)],
                   "prev": [pw[0].isoformat(), pw[1].isoformat(), *cohort(arts, paths, day, *pw)]}
    return r


def cohort_judge(c):
    """コホートの判定。(None=判定しない|True=落ちた|False=落ちていない, 理由)"""
    if not c:
        return None, "コホートを測れませんでした"
    (_, _, n_c, t_c, w_c), (_, _, n_p, t_p, w_p) = c["cur"], c["prev"]
    if n_c < MIN_COHORT or n_p < MIN_COHORT:
        return None, f"コホートの本数が足りません（今{n_c}本・前{n_p}本。各{MIN_COHORT}本以上で判定）"
    if t_p < MIN_PREV_IMP:
        return None, f"前のコホートの表示が{t_p}回で少なすぎます（{MIN_PREV_IMP}回以上で判定）"
    g = w_c / w_p - 1 if w_p else 0.0
    return g <= -OLD_DROP, f"{g:+.0%}"


def judge(r):
    bad = []
    if r["mature"] >= MIN_MATURE and r["zero"] / r["mature"] > ZERO_MAX:
        bad.append(f"要対応: {r['name']} — 公開{MATURE_DAYS}日以上の{r['mature']}本のうち{r['zero']}本"
                   f"（{r['zero'] / r['mature']:.0%}）が28日間表示ゼロ。統合・書き直しを優先（週次の統合を4組に増やします）")
    hit, why = cohort_judge(r.get("cohort"))
    if hit:
        (lc, hc, n_c, _, w_c), (lp, hp, n_p, _, w_p) = r["cohort"]["cur"], r["cohort"]["prev"]
        bad.append(f"要対応: {r['name']} — 公開5〜8週目の1本あたり週表示が {w_p:.1f}→{w_c:.1f}回（{why}。"
                   f"{lp}〜{hp}公開の{n_p}本 → {lc}〜{hc}公開の{n_c}本）。同じ年齢の記事で比べても"
                   f"落ちています。新しい記事が既存の表示を置き換えているか、評価が薄まっています（週次の統合を4組に増やします）")
    return bad


def judged(r):
    """何か1つでも判定できたか（できなければ YIELD_OK=unknown の材料）"""
    return r["mature"] >= MIN_MATURE or cohort_judge(r.get("cohort"))[0] is not None


def flagged(sid=""):
    """sid を渡せばそのサイト、空なら「どれか1つでも」"""
    import json
    try:
        allst = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return False
    since = (date.today() - timedelta(days=STATE_DAYS)).isoformat()
    sts = [allst.get(sid) or {}] if sid else [v for v in allst.values() if isinstance(v, dict)]
    return any((st.get("flagged") or st.get("throttle")) and st.get("date", "") >= since for st in sts)


def main():
    import json
    import sites as S
    if len(sys.argv) >= 2 and sys.argv[1] == "--any-flagged":
        on = flagged(sys.argv[2] if len(sys.argv) == 3 else "")
        print(f"FLAGGED={'yes' if on else 'no'}")
        return 0 if on else 1
    end = date.today() - timedelta(days=3)      # GSC の確定待ち
    arts = [a for a in (_fm(p) for p in (ROOT / "articles").glob("*.md")) if a and a["score"] >= 90]
    print(f"■ 記事を増やした分だけ伸びているか（{end - timedelta(days=27)}〜{end} と その前の28日）\n")
    alerts, ran, any_judged, state = [], 0, False, {}
    for sid, cfg in S.load_all().items():
        own = [a for a in arts if S.find_category_owner(a["category"]) == sid]
        if not own:
            continue
        try:
            r = site_report(sid, cfg, own, end)
        except Exception as e:
            print(f"  {cfg.get('name', sid)}: GSC を読めません（{str(e)[:60]}）")
            continue
        ran += 1
        per_prev = r["imp_prev"] / r["n_prev"] if r["n_prev"] else 0
        per_now = r["imp_now"] / r["n_now"] if r["n_now"] else 0
        share = r["imp_now"] / r["site_imp"] if r["site_imp"] else 0
        print(f"  {r['name']}")
        print(f"     記事数 {r['n_prev']} → {r['n_now']}本 / 記事の表示 {r['imp_prev']:,} → {r['imp_now']:,}回"
              f"（サイト全体の{share:.0%}）/ 記事のクリック {r['clk_now']}回")
        print(f"     参考（経過の差を含む）: 1本あたりの表示 {per_prev:.1f} → {per_now:.1f}回 /"
              f" 前からある{r['n_prev']}本 {r['old_prev']:,} → {r['old_now']:,}回"
              f" / 新しい{r['n_now'] - r['n_prev']}本 {r['imp_now'] - r['old_now']:,}回")
        if r["mature"]:
            print(f"     公開{MATURE_DAYS}日以上 {r['mature']}本: 表示ゼロ {r['zero']}本（{r['zero'] / r['mature']:.0%}）"
                  f" / クリックあり {r['clicked']}本（{r['clicked'] / r['mature']:.0%}）")
        hit, why = cohort_judge(r.get("cohort"))
        if r.get("cohort"):
            (lc, hc, n_c, t_c, w_c), (lp, hp, n_p, t_p, w_p) = r["cohort"]["cur"], r["cohort"]["prev"]
            print(f"     公開5〜8週目の1本あたり週表示: {lp}〜{hp}公開 {n_p}本 {w_p:.1f}回（計{t_p:,}）"
                  f" → {lc}〜{hc}公開 {n_c}本 {w_c:.1f}回（計{t_c:,}）")
        if hit is None:
            print(f"     コホートの判定: 判定しません（{r.get('cohort_why') or why}）")
        b = judge(r)
        alerts += b
        any_judged = any_judged or judged(r)
        state[sid] = {"flagged": bool(b), "date": date.today().isoformat(), "reasons": [x[5:] for x in b],
                      "cohort": "unknown" if hit is None else ("drop" if hit else "ok")}
        for x in b:
            print("  " + x)
        print()
    if not ran:
        print("  どのサイトも GSC を読めませんでした")
        return 1
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for sid, st in state.items():
        if st["flagged"]:
            print(f"  → {sid}: 来週は統合を週4組に増やします（新しい記事は1日2本のまま）")
    print(f"YIELD_OK={'no' if alerts else ('yes' if any_judged else 'unknown')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
