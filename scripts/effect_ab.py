# -*- coding: utf-8 -*-
"""打った手が効いたかを、触っていない記事と比べて判定する。

**なぜ要るか**: いまの効果測定は、直した記事の前後だけを見ている。
サイト全体が28日で+107%伸びている時期には、**何をしても「効いた」に見える**。
実際 effect.py は「表示が増えた記事 55/126本」と出すが、
触っていない記事でも同じ割合で増えているなら、その手は効いていない。

触った記事と、触っていない記事（対照群）の動きを比べる。
差が無ければ、その手はやめてよい。実際、内部リンクの下限12本は
自社データで裏づけが無かった（1〜10位の中央値5本 < 11〜30位の9〜10本）。
ああいう発見を、人が気づくのを待たずに毎週出す。

**言えないこと**: 本数が少ないので「統計的に有意」とは言わない。
中央値の差と本数をそのまま出し、判断材料にする。

    python scripts/effect_ab.py              # 施策ごとの効き
    python scripts/effect_ab.py --days 21    # 前後の観測日数
    python scripts/effect_ab.py --rewrites   # 書き直し・統合の効きを種類別に（前後28日）
                                             # → data/rewrite_effect.json / REWRITE_EFFECT_OK=yes|no|unknown
"""
import argparse
import json
import re
import statistics as st
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
MIN_N = 5             # これ未満は参考値としか言えない
MIN_IMP = 5           # 前期の表示がこれ未満の記事は動きが読めない


def interventions():
    """いつ・どの記事に・どの手を打ったか"""
    out = []
    if not LOG.is_file():
        return out
    for line in LOG.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        slug = str(d.get("slug") or "")
        if not slug or slug.startswith("("):      # まとめ記録は対象外
            continue
        when = str(d.get("at") or d.get("when") or "")[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
            continue
        kind = d.get("kind") or d.get("by") or "?"
        if d.get("ok") is False:
            continue                              # 差し戻した分は打っていない
        if "変更なし" in str(d.get("note") or ""):
            continue
        out.append({"slug": slug, "at": when, "kind": str(kind)})
    return out


def daily_by_slug():
    """記事ごと・日ごとの表示と順位。rank_rescue のキャッシュは日次を持たないので取り直す"""
    import gsc_detail as G
    import sites as S
    sc = G.client()
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=119)
    out = defaultdict(lambda: defaultdict(lambda: [0, 0, 0.0]))   # slug -> day -> [imp, clk, pos*imp]
    for cfg in S.load_all().values():
        try:
            rows = G.q(sc, cfg["domain"], str(start), str(end), ["date", "page"], 25000)
        except Exception as e:
            print(f"  {cfg['id']}: GSCから取れません（{str(e)[:40]}）")
            continue
        for r in rows:
            day, url = r["keys"][0], r["keys"][1]
            slug = url.rstrip("/").split("/")[-1]
            a = out[slug][day]
            a[0] += r["impressions"]
            a[1] += r["clicks"]
            a[2] += r["position"] * r["impressions"]
    return out, start, end


def window(daily, slug, a, b):
    """期間 a〜b の表示・クリック・加重平均順位"""
    imp = clk = ps = 0
    for day, v in daily.get(slug, {}).items():
        try:
            d = date.fromisoformat(day)
        except ValueError:
            continue
        if a <= d <= b:
            imp += v[0]; clk += v[1]; ps += v[2]
    return imp, clk, (ps / imp if imp else None)


def change(daily, slug, at, days):
    """直した日の前後を同じ長さで比べる。返すのは (表示の倍率, 順位の改善)"""
    before_b = at - timedelta(days=1)
    before_a = before_b - timedelta(days=days - 1)
    after_a = at + timedelta(days=1)
    after_b = after_a + timedelta(days=days - 1)
    if after_b > date.today() - timedelta(days=3):
        return None                                # まだ観測期間が足りない
    bi, _, bp = window(daily, slug, before_a, before_b)
    ai, _, ap = window(daily, slug, after_a, after_b)
    if bi < MIN_IMP:
        return None
    imp_ratio = ai / bi
    pos_gain = (bp - ap) if (bp is not None and ap is not None) else None
    return imp_ratio, pos_gain


# ---- 書き直しの効き（種類別・28日） -------------------------------------------
# rewrite_rollback はタイトルだけを28日後に判定して戻す。stuck・aio・question・fresh・desc・
# quality・統合は、当てたまま効いたかが誰にも分からなかった（効かない手を毎週回し続ける）。
# 判定の物差しは rewrite_rollback と同じ（前後28日・同じ日で切った対照群の中央値）にそろえる
REWRITE_BY = ("auto_rewrite", "auto_merge")
REWRITE_DONE = ("直しました", "統合しました")
REWRITE_DAYS = 28
REWRITE_OUT = ROOT / "data" / "rewrite_effect.json"
LAG = 3               # GSC は直近3日が欠けるので、観測の終わりはその手前


def rewrites(log=None):
    """実際に本文を書き換えた記録だけ（変更なし・検算で戻した分は打っていない）"""
    out = []
    f = Path(log) if log else LOG
    if not f.is_file():
        return out
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        when = str(d.get("at") or "")[:10]
        if d.get("by") not in REWRITE_BY or not d.get("ok") or not d.get("slug") \
                or not str(d.get("note") or "").startswith(REWRITE_DONE) \
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", when):
            continue
        out.append({"slug": d["slug"], "at": when, "kind": str(d.get("kind") or "?")})
    return out


def measure(daily, slug, at, days, today):
    """直した日の前後 days 日。返すのは (状態, 値)。状態は ok / 観測中 / 表示が少ない"""
    before_b = at - timedelta(days=1)
    before_a = before_b - timedelta(days=days - 1)
    after_a = at + timedelta(days=1)
    after_b = after_a + timedelta(days=days - 1)
    if after_b > today - timedelta(days=LAG):
        return "観測中", None
    bi, bc, bp = window(daily, slug, before_a, before_b)
    ai, ac, ap = window(daily, slug, after_a, after_b)
    if bi < MIN_IMP:
        return "表示が少ない", None
    return "ok", {"imp_ratio": ai / bi, "pos_gain": (bp - ap) if (bp is not None and ap is not None) else None,
                  "clk_diff": ac - bc, "imp": [bi, ai], "clk": [bc, ac]}


def rewrite_effects(acts, daily, today, days=REWRITE_DAYS, min_n=MIN_N):
    """書き直し1件ずつを、同じ日で切った対照群（その前後に書き直していない記事）の中央値で割り引く。

    対照群から外すのは書き直し・統合だけ。内部リンク・CTA はほぼ全記事に入っており、
    それも外すと対照群が残らない（両群に同じように入るので差し引きで消える）"""
    by_slug = defaultdict(list)
    for x in acts:
        by_slug[x["slug"]].append(date.fromisoformat(x["at"]))
    items = []
    for x in acts:
        at = date.fromisoformat(x["at"])
        st_, me = measure(daily, x["slug"], at, days, today)
        it = {"slug": x["slug"], "at": x["at"], "kind": x["kind"], "status": st_}
        if me is None:
            items.append(it)
            continue
        busy = {s for s, ds in by_slug.items() if any(abs((d - at).days) <= days for d in ds)}
        ctrl = [c for s in daily if s not in busy
                for ok_, c in [measure(daily, s, at, days, today)] if ok_ == "ok"]
        if len(ctrl) < min_n:
            it["status"] = "対照群が足りない"
            items.append(it)
            continue
        ci = st.median(c["imp_ratio"] for c in ctrl)
        cps = [c["pos_gain"] for c in ctrl if c["pos_gain"] is not None]
        it.update(me, ctrl_n=len(ctrl), ctrl_imp=round(ci, 3),
                  net_imp=round(me["imp_ratio"] / ci, 3) if ci else None,
                  net_pos=(round(me["pos_gain"] - st.median(cps), 2)
                           if me["pos_gain"] is not None and cps else None),
                  net_clk=me["clk_diff"] - st.median(c["clk_diff"] for c in ctrl))
        it["imp_ratio"] = round(it["imp_ratio"], 3)
        it["pos_gain"] = None if it["pos_gain"] is None else round(it["pos_gain"], 2)
        items.append(it)

    kinds = {}
    for kind in sorted({x["kind"] for x in items}):
        rows = [x for x in items if x["kind"] == kind]
        judged = [x for x in rows if x["status"] == "ok" and x.get("net_imp") is not None]
        k = {"total": len(rows), "judged": len(judged),
             "pending": sum(x["status"] == "観測中" for x in rows),
             "low_imp": sum(x["status"] == "表示が少ない" for x in rows)}
        if len(judged) < min_n:
            k["verdict"] = "判定前"
        else:
            ni = st.median(x["net_imp"] for x in judged)
            nps = [x["net_pos"] for x in judged if x["net_pos"] is not None]
            npos = st.median(nps) if nps else 0.0
            nclk = st.median(x["net_clk"] for x in judged)
            # 表示か順位のどちらかで対照群を上回り、クリックを減らしていないこと（effect_ab と同じ幅）
            good = (ni >= 1.05 or npos >= 0.5) and nclk >= 0
            k.update(net_imp=round(ni, 3), net_pos=round(npos, 2), net_clk=nclk,
                     clicks=[sum(x["clk"][0] for x in judged), sum(x["clk"][1] for x in judged)],
                     verdict="効いた" if good else "効かない")
        kinds[kind] = k
    return {"days": days, "kinds": kinds, "items": items}


def rewrite_main(days):
    acts = rewrites()
    print(f"■ 書き直しの効き（種類別・前後{days}日・対照群の中央値で割り引く）\n")
    if not acts:
        print("  書き直した記録がありません（automation/logs/auto_fix.jsonl）")
        print("REWRITE_EFFECT_OK=yes")
        return 0
    try:
        daily, _, _ = daily_by_slug()
    except Exception as e:
        # 取れなかった回を「効いた・効かない無し」に数えない
        print(f"  GSC の日次が取れません（{str(e)[:60]}）")
        print("REWRITE_EFFECT_OK=unknown")
        return 0
    if not daily:
        print("  GSC の日次が1行も取れませんでした")
        print("REWRITE_EFFECT_OK=unknown")
        return 0
    res = rewrite_effects(acts, daily, date.today(), days)
    print(f"{'種類':<14}{'書き直し':>6}{'判定':>5}{'観測中':>6}{'表示×(対照比)':>14}{'順位(対照差)':>12}{'クリック差':>10}  判定")
    for kind, k in sorted(res["kinds"].items(), key=lambda kv: -kv[1]["total"]):
        vals = (f"{k['net_imp']:>13.2f}倍{k['net_pos']:>+11.1f}位{k['net_clk']:>+10.1f}"
                if "net_imp" in k else f"{'-':>14}{'-':>12}{'-':>10}")
        print(f"{kind[:12]:<14}{k['total']:>6}{k['judged']:>5}{k['pending']:>6}{vals}  {k['verdict']}")
    weak = [kd for kd, k in res["kinds"].items() if k["verdict"] == "効かない"]
    res["generated"] = date.today().isoformat()
    REWRITE_OUT.parent.mkdir(exist_ok=True)
    REWRITE_OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"\n  判定は{MIN_N}件以上がそろった種類だけ（足りない種類は判定前）。結果: data/rewrite_effect.json")
    if weak:
        print(f"  効かない種類: {', '.join(weak)} → 続ける前に、対象の選び方と指示を見直してください")
        print(f"   ::warning::書き直しのうち対照群と差が出ていない種類が{len(weak)}件あります: {', '.join(weak)}")
    print("REWRITE_EFFECT_OK=" + ("no" if weak else "yes"))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=21, help="前後の観測日数")
    ap.add_argument("--rewrites", action="store_true", help="書き直し・統合の効きを種類別に判定する（28日）")
    a = ap.parse_args()
    if a.rewrites:
        return rewrite_main(REWRITE_DAYS if a.days == 21 else a.days)

    acts = interventions()
    if not acts:
        print("  介入の記録がありません（automation/logs/auto_fix.jsonl）")
        print("EFFECT_AB_OK=yes")
        return 0

    daily, gsc_start, gsc_end = daily_by_slug()
    touched_days = defaultdict(set)
    for x in acts:
        touched_days[x["slug"]].add(x["at"])

    by_kind = defaultdict(list)
    for x in acts:
        try:
            at = date.fromisoformat(x["at"])
        except ValueError:
            continue
        c = change(daily, x["slug"], at, a.days)
        if c:
            by_kind[x["kind"]].append((x["slug"], at, c))

    # 対照群: その日に触っていない記事。同じ日で切って同じ長さを比べる
    print(f"■ 打った手の効き（前後{a.days}日・触っていない記事と比較）\n")
    print(f"{'施策':<14}{'本数':>5}{'表示の倍率':>12}{'対照群':>10}{'順位の改善':>12}{'対照群':>10}")
    rows_out = []
    for kind, rows in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        if not rows:
            continue
        dates = {r[1] for r in rows}
        ctrl_imp, ctrl_pos = [], []
        for at in dates:
            for slug in daily:
                if slug in touched_days:
                    continue
                c = change(daily, slug, at, a.days)
                if c:
                    ctrl_imp.append(c[0])
                    if c[1] is not None:
                        ctrl_pos.append(c[1])
        t_imp = [r[2][0] for r in rows]
        t_pos = [r[2][1] for r in rows if r[2][1] is not None]
        mi = st.median(t_imp) if t_imp else 0
        ci = st.median(ctrl_imp) if ctrl_imp else 0
        mp = st.median(t_pos) if t_pos else 0
        cp = st.median(ctrl_pos) if ctrl_pos else 0
        print(f"{kind[:12]:<14}{len(rows):>5}{mi:>11.2f}倍{ci:>9.2f}倍"
              f"{mp:>+11.1f}位{cp:>+9.1f}位")
        rows_out.append((kind, len(rows), mi, ci, mp, cp))

    if not rows_out:
        print("  まだ判定できる記録がありません"
              f"（直してから{a.days * 2}日たった記事が必要です）")
        print("EFFECT_AB_OK=yes")
        return 0

    print("\n■ 判定")
    weak = []
    for kind, n, mi, ci, mp, cp in rows_out:
        better = (mi > ci * 1.05) or (mp > cp + 0.5)
        note = "参考値（本数が少ない）" if n < MIN_N else ""
        mark = "効いている" if better else "対照群と差が無い"
        print(f"  {kind}: {mark}  {note}")
        if not better and n >= MIN_N:
            weak.append(kind)
    if weak:
        print(f"\n  差が無い施策: {', '.join(weak)}")
        print("  → 続ける前に、基準や当て方を見直してください。"
              "効かない手を毎週続けると、効く手に使う時間が減ります")
    print("EFFECT_AB_OK=" + ("no" if weak else "yes"))
    if weak:
        print(f"   ::warning::対照群と差が出ていない施策が{len(weak)}件あります: "
              f"{', '.join(weak)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
