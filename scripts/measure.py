# -*- coding: utf-8 -*-
"""数字は、2通りで測って一致したものだけを返す。

CLAUDE.md 0.1 は「1つの測り方の結果を、そのまま事実として報告してはならない」と
決めている。それでも同じ誤りが繰り返された。**守るかどうかが人とAIの側にあるから**。
ここで、守らないと値が取れない形にする。

実際に起きた誤り（この仕組みが無かったときの実績）:

| 何を | どう間違えたか | 正しくは |
|:--|:--|:--|
| 表示・クリックの合計 | GSCの query 次元で数えた | 次元なし。補助金のクリックは2回でなく51回 |
| 伸び率 | 同上 | +38% ではなく +107% |
| 指名検索の割合 | 分母を query 次元にした | 88% ではなく 35%以下 |
| 検索に出ていない記事 | query 次元で数えた | 152本ではなく101本 |
| FAQ の有無 | 正規表現が実物と違った | 「0件」は誤り。全記事にあった |
| 内部リンクの下限 | よそで言われる12本を使った | 自社データに裏づけなし |

使い方:

    from measure import verified, Disagree
    n = verified("GSCの表示合計",
                 lambda: total_no_dimension(...),      # 方法A
                 lambda: sum_of_daily_rows(...),       # 方法B
                 tol=0.0)                              # 許容差（割合）

一致しなければ Disagree を投げる。**呼び出し側は値を得られない。**
「概ね合っている」で先に進めないようにするのが目的。

    python scripts/measure.py --selftest    # 一致しないときに本当に止まるか
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

LOG = ROOT / "automation" / "logs" / "measure.jsonl"


class Disagree(Exception):
    """2通りの測り方が一致しなかった。値は返さない"""


def _rel(a, b):
    if a == b:
        return 0.0
    m = max(abs(a), abs(b))
    return abs(a - b) / m if m else 0.0


def verified(name, method_a, method_b, tol=0.0, note=""):
    """2通りで測り、一致したときだけ値を返す。

    tol は許容する相対差（0.0 なら完全一致を求める）。
    GA4のように取得のたびに揺れるものだけ、理由を note に書いて緩める。
    """
    a = method_a()
    b = method_b()
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        d = _rel(float(a), float(b))
        ok = d <= tol
    else:
        d = 0.0 if a == b else 1.0
        ok = a == b
    _record(name, a, b, ok, note)
    if not ok:
        raise Disagree(
            f"{name}: 2通りの測り方が一致しません（A={a} / B={b} / 差{d:.1%} / 許容{tol:.1%}）"
            + (f"｜{note}" if note else "")
            + "。一致するまで、この数字は使えません")
    return a


def _record(name, a, b, ok, note):
    import json
    import time
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8", newline="") as f:
            f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "name": name,
                                "a": a, "b": b, "ok": bool(ok), "note": note},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


# ---- よく使う数字は、2通りをここに固定しておく -------------------------

def gsc_totals(domain, start, end):
    """表示とクリックの合計。次元なしと、日次の合算で突き合わせる。

    query 次元は検索数の少ない語を返さないため、合計には使えない。
    この関数を通せば、うっかり次元つきで数えることが起きない。
    """
    import gsc_detail as G
    sc = G.client()

    def none_dim():
        r = G.q(sc, domain, str(start), str(end), None, 1)
        return (r[0]["impressions"], r[0]["clicks"]) if r else (0, 0)

    def by_date():
        rows = G.q(sc, domain, str(start), str(end), ["date"], 5000)
        return (sum(x["impressions"] for x in rows), sum(x["clicks"] for x in rows))

    imp = verified(f"{domain} の表示合計", lambda: none_dim()[0], lambda: by_date()[0])
    clk = verified(f"{domain} のクリック合計", lambda: none_dim()[1], lambda: by_date()[1])
    return imp, clk


def published_articles():
    """公開記事の本数。原稿から数える方法と、生成HTMLから数える方法で突き合わせる"""
    import re

    def from_md():
        n = 0
        for p in (ROOT / "articles").glob("*.md"):
            if p.name.startswith("_"):
                continue
            t = p.read_text(encoding="utf-8-sig", errors="ignore")[:2000]
            if re.search(r"^score:\s*(9[0-9]|100)\s*$", t, re.M):
                n += 1
        return n

    def from_html():
        import json
        led = ROOT / "data" / "published.json"
        if led.is_file():
            try:
                return len(json.loads(led.read_text(encoding="utf-8")))
            except Exception:
                pass
        return len(list((ROOT / "site").glob("*/*/index.html")))

    # 原稿には他サイト配信分も含まれるため、完全一致は求めない。
    # 桁が違えばどちらかの数え方が壊れている
    return verified("公開記事の本数", from_md, from_html, tol=0.75,
                    note="原稿には他サイトへ配信した分も含まれる")


def selftest():
    """一致しないときに、本当に値を返さずに止まるか"""
    print("■ 計測の自己診断（食い違ったときに止まるか）\n")
    cases = [
        ("完全に一致", lambda: 100, lambda: 100, 0.0, True),
        ("1件ずれ（許容0%）", lambda: 100, lambda: 101, 0.0, False),
        ("1件ずれ（許容2%）", lambda: 100, lambda: 101, 0.02, True),
        ("桁が違う", lambda: 51, lambda: 2, 0.0, False),
        ("query次元の取りこぼし相当", lambda: 7762, lambda: 4157, 0.05, False),
        ("文字列の不一致", lambda: "ok", lambda: "ng", 0.0, False),
    ]
    ok = 0
    for name, a, b, tol, should_pass in cases:
        try:
            verified(f"診断: {name}", a, b, tol)
            got = True
        except Disagree:
            got = False
        good = got == should_pass
        ok += good
        print(f"  {'OK' if good else 'NG'}  {name}: "
              + ("値を返した" if got else "止めた")
              + f"（期待: {'返す' if should_pass else '止める'}）")
    print(f"\n  {ok}/{len(cases)} が期待どおり")
    return 0 if ok == len(cases) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--log", action="store_true", help="これまでの照合結果")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.log:
        import json
        if not LOG.is_file():
            print("  記録がありません")
            return 0
        rows = [json.loads(x) for x in LOG.read_text(encoding="utf-8").splitlines() if x.strip()]
        # 自己診断とゲートの確認は、わざと食い違わせて止まるかを見るもの。
        # 本番の計測と混ぜると、毎週「食い違いあり」と誤報する
        bad = [r for r in rows if not r["ok"]
               and not r["name"].startswith(("診断:", "ゲートの確認"))]
        print(f"■ 照合の記録 {len(rows)}件 / 食い違い {len(bad)}件")
        for r in bad[-10:]:
            print(f"  {r['at']}  {r['name']}: A={r['a']} / B={r['b']}")
        print("MEASURE_OK=" + ("no" if bad else "yes"))
        if bad:
            print(f"   ::warning::2通りで一致しなかった計測が{len(bad)}件あります。"
                  "原因を確かめるまで、その数字は使えません")
        return 0
    print(__doc__.split("使い方:")[0].strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
