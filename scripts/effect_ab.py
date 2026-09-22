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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=21, help="前後の観測日数")
    a = ap.parse_args()

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
