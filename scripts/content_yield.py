# -*- coding: utf-8 -*-
"""記事を増やした分だけ伸びているかを見張る（記事の出しすぎの検知）

growth_guard は「落ちたか」を見る。ここは「増やした割に伸びていないか」を見る。
記事を毎日出し続けても、検索に出ない記事が積み上がるとサイト全体の評価が薄まり、
1本あたりの表示が下がっていく。その段階では合計はまだ伸びて見えるため、
合計だけを見ていると気づけない。

見るもの（サイトごと・GSC のページ次元・直近28日とその前の28日）
  1. 眠っている記事: 公開30日以上で、28日間の表示が0の記事の割合
  2. 1本あたりの表示: 記事数の伸びに対して、記事全体の表示が伸びているか
  3. 既存記事の表示: 前の期間からある記事の表示が、新しい記事を足した後に落ちていないか
     （合計が伸びていても、新しい記事が既存記事の表示を置き換えているだけのことがある。
      2026-09 の実測で AI集客ラボ・コーポレートとも既存記事が約3割落ち、新記事が穴を埋めていた）

要対応にする条件
  - 眠っている記事が40%を超える（公開30日以上の記事が20本以上あるとき）
  - 記事数が10%以上増えたのに、表示の伸びが記事数の伸びの半分に届かない
    （前の期間の記事の表示が100回以上あるときだけ。少ない数で騒がない）
  - 記事数が10%以上増えた期間に、既存記事の表示が20%以上落ちた
どちらも「新しく書くより、既存記事の統合・書き直しに回す」合図。

  python scripts/content_yield.py
  python scripts/content_yield.py --throttled <site>   # 本数を絞る週か（終了コード0=絞る）

要対応になったサイトは data/yield_state.json に記録し、日次の執筆が1日2本→1本に絞る
（pipeline-multi の2本目の枠を飛ばす）。次の週に条件を外れれば自動で戻る。14日より古い記録は使わない。
出す印: YIELD_OK=yes|no（見つかったら no。検査が動かなかったときだけ終了コード1）
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
GROW_MIN = 0.10
OLD_DROP = 0.20
MIN_PREV_IMP = 100
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
    return {"sid": sid, "name": cfg.get("name", sid), "n_now": len(live_now), "n_prev": len(live_prev),
            "mature": len(mature), "zero": len(zero), "clicked": len(clicked),
            "imp_now": imp_now, "imp_prev": imp_prev, "clk_now": clk_now, "site_imp": site_imp,
            "old_prev": old_prev, "old_now": old_now}


def judge(r):
    bad = []
    if r["mature"] >= MIN_MATURE and r["zero"] / r["mature"] > ZERO_MAX:
        bad.append(f"要対応: {r['name']} — 公開{MATURE_DAYS}日以上の{r['mature']}本のうち{r['zero']}本"
                   f"（{r['zero'] / r['mature']:.0%}）が28日間表示ゼロ。新規より統合・書き直しを先に")
    if r["n_prev"] and r["imp_prev"] >= MIN_PREV_IMP:
        g_n = r["n_now"] / r["n_prev"] - 1
        g_i = r["imp_now"] / r["imp_prev"] - 1
        if g_n >= GROW_MIN and g_i < g_n / 2:
            bad.append(f"要対応: {r['name']} — 記事は{g_n:+.0%}（{r['n_prev']}→{r['n_now']}本）なのに"
                       f"記事の表示は{g_i:+.0%}。1本あたり {r['imp_prev'] / r['n_prev']:.1f}→"
                       f"{r['imp_now'] / r['n_now']:.1f}回。増やした分が伸びていません")
    if r["n_prev"] and r["old_prev"] >= MIN_PREV_IMP and r["n_now"] / r["n_prev"] - 1 >= GROW_MIN:
        g_o = r["old_now"] / r["old_prev"] - 1
        if g_o <= -OLD_DROP:
            bad.append(f"要対応: {r['name']} — 前からある{r['n_prev']}本の表示が{g_o:+.0%}"
                       f"（{r['old_prev']:,}→{r['old_now']:,}回）。新しい記事が既存の表示を置き換えているか、"
                       f"評価が薄まっています。新規を減らし、食い合いの統合を先に")
    return bad


def throttled(sid):
    import json
    try:
        st = json.loads(STATE.read_text(encoding="utf-8")).get(sid) or {}
    except Exception:
        return False
    fresh = st.get("date", "") >= (date.today() - timedelta(days=STATE_DAYS)).isoformat()
    return bool(st.get("throttle")) and fresh


def main():
    import json
    import sites as S
    if len(sys.argv) == 3 and sys.argv[1] == "--throttled":
        on = throttled(sys.argv[2])
        print(f"THROTTLE={'yes' if on else 'no'}")
        return 0 if on else 1
    end = date.today() - timedelta(days=3)      # GSC の確定待ち
    arts = [a for a in (_fm(p) for p in (ROOT / "articles").glob("*.md")) if a and a["score"] >= 90]
    print(f"■ 記事を増やした分だけ伸びているか（{end - timedelta(days=27)}〜{end} と その前の28日）\n")
    alerts, ran, state = [], 0, {}
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
        print(f"     1本あたりの表示 {per_prev:.1f} → {per_now:.1f}回")
        print(f"     内訳: 前からある{r['n_prev']}本 {r['old_prev']:,} → {r['old_now']:,}回"
              f" / 新しい{r['n_now'] - r['n_prev']}本 {r['imp_now'] - r['old_now']:,}回")
        if r["mature"]:
            print(f"     公開{MATURE_DAYS}日以上 {r['mature']}本: 表示ゼロ {r['zero']}本（{r['zero'] / r['mature']:.0%}）"
                  f" / クリックあり {r['clicked']}本（{r['clicked'] / r['mature']:.0%}）")
        b = judge(r)
        alerts += b
        state[sid] = {"throttle": bool(b), "date": date.today().isoformat(), "reasons": [x[5:] for x in b]}
        for x in b:
            print("  " + x)
        print()
    if not ran:
        print("  どのサイトも GSC を読めませんでした")
        return 1
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for sid, st in state.items():
        if st["throttle"]:
            print(f"  → {sid}: 来週は新しい記事を1日1本に絞ります（統合・書き直しに回す）")
    print(f"YIELD_OK={'no' if alerts else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
