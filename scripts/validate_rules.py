# -*- coding: utf-8 -*-
"""システムが使っている判断が、実際の成果を言い当てているかを確かめる。

**なぜ要るか**: この仕組みは、いくつもの判断で記事を選び、直し、公開している。
点数・語の性質・業種の優先度・内部リンクの下限。どれも「そう決めた」だけで、
**当たっているかを誰も確かめていなかった**。

実際に確かめると、当たっていないものがあった。

| 判断 | 決めていたこと | 実測 |
|:--|:--|:--|
| 内部リンクの下限12本 | 上位はこのくらい持っている | 1〜10位は中央値5本。逆だった |
| 品質スコア | 90点以上を公開条件 | 96点以上の順位が91〜93点より悪い |

当たっていない判断で記事を選び続けると、努力の向き先がずれる。
ここでは、判断ごとに成果の分布を並べ、**差が出ているかどうかだけ**を言う。

**言えないこと**: 本数が少ないので因果は言わない。「差が出ていない」は
「効果が無い」ではなく「この本数では区別できない」という意味。

    python scripts/validate_rules.py
    python scripts/validate_rules.py --min 8     # 1区分の最低本数
"""
import argparse
import re
import statistics as st
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

MIN_PER_BAND = 6          # これ未満の区分は比べない
MIN_IMP = 5               # この表示回数を割る記事は動きが読めない


def perf():
    """記事ごとの実績。表示・クリック・加重平均順位"""
    import rank_rescue as RR
    d = RR.load()
    out = defaultdict(lambda: [0, 0, 0.0])
    for rows in (d.get("sites") or {}).values():
        for r in rows:
            s = r["url"].rstrip("/").split("/")[-1]
            out[s][0] += r["imp"]; out[s][1] += r["clk"]; out[s][2] += r["pos"] * r["imp"]
    return out


def meta():
    """記事の属性。判断の材料になっているものを集める"""
    out = {}
    for p in (ROOT / "articles").glob("*.md"):
        if p.name.startswith("_"):
            continue
        t = p.read_text(encoding="utf-8-sig", errors="ignore")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)

        def g(k):
            x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
            return x.group(1).strip().strip('"') if x else ""

        sc = g("score")
        if not sc.isdigit() or int(sc) < 90:
            continue
        slug = g("slug") or p.stem
        dt = g("date")
        age = None
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", dt):
            age = (date.today() - date(*map(int, dt.split("-")))).days
        out[slug] = {"score": int(sc), "kw": g("keyword"), "depth": g("depth") or "standard",
                     "age": age, "body": t[m.end():]}
    return out


def kw_band(kw):
    try:
        import kw_intent
        return kw_intent.verdict(kw)[0]
    except Exception:
        return "?"


def inbound(arts):
    n = defaultdict(int)
    for a in arts.values():
        for u in set(re.findall(r"\]\((/[^)]+/)\)", a["body"])):
            n[u.rstrip("/").split("/")[-1]] += 1
    return n


def report(name, groups, p, note="", expect=None):
    """区分ごとに成果の中央値を並べる。

    expect には「この区分が一番良いはず」という期待を書く。
    **向きを見ないと、逆相関を「差が出ている」と読んでしまう。**
    実際、品質スコアは高いほど順位が悪かったのに、最初の版は
    「差が出ています」と報告した。逆に出る判断は、無い判断より悪い。
    """
    rows = []
    for label, slugs in groups:
        ss = [s for s in slugs if s in p and p[s][0] >= MIN_IMP]
        if len(ss) < MIN_PER_BAND:
            continue
        imp = [p[s][0] for s in ss]
        pos = [p[s][2] / p[s][0] for s in ss]
        rows.append((label, len(ss), st.median(imp), st.median(pos)))
    print(f"\n■ {name}" + (f"（{note}）" if note else ""))
    if len(rows) < 2:
        print(f"   本数が足りず比べられません（各区分{MIN_PER_BAND}本以上が必要）")
        return None
    print(f"   {'区分':<16}{'本数':>5}{'表示中央値':>11}{'順位中央値':>11}")
    for label, n, imp, pos in rows:
        print(f"   {label:<16}{n:>5}{imp:>11.0f}{pos:>10.1f}位")
    # 差が出ているか。順位は小さいほど良い
    best = min(rows, key=lambda r: r[3])
    worst = max(rows, key=lambda r: r[3])
    gap = worst[3] - best[3]
    ordered = [r[3] for r in rows]
    monotonic = ordered == sorted(ordered) or ordered == sorted(ordered, reverse=True)
    if gap < 2.0:
        print(f"   → 区分の間に差が出ていません（順位差{gap:.1f}）。"
              "この判断では成果を分けられていません")
        return False
    if not monotonic:
        print(f"   → 順序が入れ替わっています（best={best[0]} / worst={worst[0]}）。"
              "この判断は成果の順番を言い当てていません")
        return False
    if expect and expect not in [r[0] for r in rows]:
        print(f"   → 期待していた区分「{expect}」は本数が足りず比べられません。"
              "残った区分だけでは向きを判定できません")
        return None
    if expect and best[0] != expect:
        print(f"   → **逆になっています**。良いはずの「{expect}」ではなく"
              f"「{best[0]}」が{gap:.1f}位ぶん良い。"
              "逆に出る判断は、無い判断より悪い（選び方が成果を下げます）")
        return False
    print(f"   → 差が出ています（{best[0]} が {gap:.1f}位ぶん良い）"
          + ("" if expect else "。期待する向きを決めていないため参考値です"))
    return True


def main():
    global MIN_PER_BAND
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=MIN_PER_BAND)
    a = ap.parse_args()
    MIN_PER_BAND = a.min

    p = perf()
    arts = meta()
    inb = inbound(arts)
    results = {}

    # 1) 品質スコア
    bands = [("91〜93点", [s for s, v in arts.items() if v["score"] <= 93]),
             ("94〜95点", [s for s, v in arts.items() if 94 <= v["score"] <= 95]),
             ("96点以上", [s for s, v in arts.items() if v["score"] >= 96])]
    results["品質スコア"] = report("品質スコア（公開条件に使っている）", bands, p,
                                "書いた本人が付けている", expect="96点以上")

    # 2) 検索語の性質
    g = defaultdict(list)
    for s, v in arts.items():
        g[kw_band(v["kw"])].append(s)
    results["語の性質"] = report(
        "検索語の性質（kw_intent の判定）",
        [(k, g[k]) for k in ("強", "並", "弱") if k in g], p,
        "開かないと済まない語かどうか", expect="強")

    # 3) 記事の長さ。depth の札は実質使われていない（372本中362本が standard）
    #    ので、実際の文字数で分ける
    g2 = defaultdict(list)
    for s, v in arts.items():
        g2[v["depth"]].append(s)
    n_std = len(g2.get("standard", []))
    n_all = sum(len(v) for v in g2.values())
    if n_all and n_std / n_all > 0.9:
        print(chr(10) + "■ 記事の長さ（depth の札）")
        print(f"   {n_std}/{n_all}本が standard。検索意図で長さを決める仕組みが"
              "使われていません（CLAUDE.md Phase 4）")
        print("   → 手順や定義だけの記事まで5,000字に伸ばしている可能性があります")
    lens = {}
    for s, v in arts.items():
        lens[s] = len(re.sub(r"\s|<[^>]+>", "", v["body"]))
    bands3 = [("5,500字未満", [s for s in lens if lens[s] < 5500]),
              ("5,500〜7,000字", [s for s in lens if 5500 <= lens[s] < 7000]),
              ("7,000字以上", [s for s in lens if lens[s] >= 7000])]
    results["記事の長さ"] = report("記事の長さ（実際の文字数）", bands3, p,
                               "5,000字以上を基準にしていた", expect="7,000字以上")

    # 4) 内部リンクの本数
    bands4 = [("0〜4本", [s for s in arts if inb.get(s, 0) <= 4]),
              ("5〜9本", [s for s in arts if 5 <= inb.get(s, 0) <= 9]),
              ("10本以上", [s for s in arts if inb.get(s, 0) >= 10])]
    results["内部リンク"] = report("内部リンクの本数", bands4, p,
                               "下限を決める根拠にしていた", expect="10本以上")

    # 5) 別工程の採点（新しい3軸）。当たり始めたら、直す判断に使ってよい
    try:
        import json as _json
        au = _json.loads((ROOT / "data" / "score_audit.json").read_text(encoding="utf-8"))
        import rubric as _R
        hi = [s for s, v in au.items()
              if (v.get("audit") or {}).get("total", 0) >= _R.PASS_TOTAL]
        lo = [s for s, v in au.items()
              if 0 < (v.get("audit") or {}).get("total", 99) < _R.PASS_TOTAL]
        results["別工程の採点"] = report(
            "別工程の採点（3軸・合格と不合格）",
            [("合格", hi), ("不合格", lo)], p,
            "合格のほうが成果が良いはず", expect="合格")
    except Exception:
        results["別工程の採点"] = None

    # 6) 公開からの日数（これは効いて当然。検査そのものが働いているかの確認用）
    bands5 = [("0〜20日", [s for s, v in arts.items() if (v["age"] or 99) <= 20]),
              ("21〜40日", [s for s, v in arts.items() if 21 <= (v["age"] or 0) <= 40]),
              ("41日以上", [s for s, v in arts.items() if (v["age"] or 0) >= 41])]
    results["公開からの日数"] = report("公開からの日数", bands5, p,
                                 "この検査自体が働いているかの確認用")

    ng = [k for k, v in results.items() if v is False]
    print(chr(10) + "   ※ 本数が少ないため、因果は言えません。難しい語を狙った記事ほど"
          "点数が高い、といった交絡もありえます。"
          "点数が高い、といった交絡もありえます。"
          "ここで分かるのは「その判断で選んでも成果は良くならない」ことだけです。")
    print("\n■ まとめ")
    for k, v in results.items():
        mark = {True: "成果を分けている", False: "成果を分けていない", None: "本数不足"}[v]
        print(f"   {k:<16}{mark}")
    if ng:
        print(f"\n   成果を分けていない判断: {', '.join(ng)}")
        print("   → その判断で記事を選び続けると、努力の向き先がずれます。"
              "基準の作り直しか、判断そのものをやめるかを検討してください")
    print("RULES_OK=" + ("no" if ng else "yes"))
    if ng:
        print(f"   ::warning::実測で成果を分けていない判断が{len(ng)}件あります: "
              f"{', '.join(ng)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
