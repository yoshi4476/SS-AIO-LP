# -*- coding: utf-8 -*-
"""数字の増減に、必ず文脈を添える。

**なぜ要るか**: 「表示回数が885回減りました」とだけ書くと、読んだ人は
悪くなったと受け取る。実際は9月が24日までしかなく、しかも平均順位は
36.1位から20.5位へ15.6位上がっていた。**減った事実と、同時に起きた改善を
並べて初めて、正しく読める。**

決まりは3つ。

  1. 日数の違う期間は、**1日あたりに直してから**比べる
  2. 下がった数字には、**同じ期間に上がった数字を必ず添える**
  3. 途中の月は、途中だと分かる形でしか出さない

この3つを、書く人が覚えておく決まりにしない。ここを通せば必ずそうなる形にする。
"""
from datetime import date, timedelta

# 数字の性質。方向が逆のものがあるため、良し悪しを機械で決められるようにする
#   up_is_good … 増えるほど良い
#   lower_is_better … 小さいほど良い（順位）
METRICS = {
    "impressions": {"name": "表示回数", "up_is_good": True},
    "clicks": {"name": "検索クリック", "up_is_good": True},
    "sessions": {"name": "セッション", "up_is_good": True},
    "cv": {"name": "リード獲得", "up_is_good": True},
    "ctr": {"name": "クリック率", "up_is_good": True, "unit": "%", "rate": True},
    "pos": {"name": "平均順位", "up_is_good": False, "lower_is_better": True, "unit": "位"},
}


def days_in(label, through=None):
    """その月の日数。途中なら、経過した日数を返す"""
    y, m = map(int, label.split("-"))
    last = (date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)).day
    if through and through.year == y and through.month == m:
        return min(through.day, last)
    return last


def per_day(value, label, through=None):
    d = days_in(label, through) or 1
    return value / d


def compare(cur, prev, key, cur_label, prev_label, through=None):
    """1日あたりに直して比べる。**日数の違う月をそのまま比べない。**

    返すもの: {"dir": "up"/"down"/"flat", "good": bool, "pct": float, "text": str}
    """
    meta = METRICS.get(key, {"name": key, "up_is_good": True})
    a, b = cur.get(key, 0) or 0, prev.get(key, 0) or 0
    if not b:
        return {"dir": "flat", "good": True, "pct": 0.0,
                "text": "前月の数字が無いため、比べられません"}

    if meta.get("lower_is_better") or meta.get("rate"):
        # 順位・率は1日あたりに直さない（平均値・比率なので、日数で割ると意味が変わる）
        pa, pb = a, b
    else:
        pa = per_day(a, cur_label, through)
        pb = per_day(b, prev_label)

    pct = (pa - pb) / pb * 100 if pb else 0.0
    if abs(pct) < 3:
        d = "flat"
    elif pct > 0:
        d = "up"
    else:
        d = "down"
    good = (d == "flat") or ((d == "up") == bool(meta.get("up_is_good", True)))

    unit = meta.get("unit", "")
    if meta.get("lower_is_better"):
        body = f"{b}{unit} → {a}{unit}"
        if a < b:
            body += f"（{b - a:.1f}{unit}上がりました）"
        elif a > b:
            body += f"（{a - b:.1f}{unit}下がりました）"
    else:
        dn, dp = days_in(cur_label, through), days_in(prev_label)
        body = f"{b:,} → {a:,}"
        if dn != dp:
            body += f"（1日あたり {pb:.1f} → {pa:.1f}。{prev_label}は{dp}日、{cur_label}は{dn}日）"
        body += f" {'+' if pct >= 0 else ''}{pct:.0f}%"
    return {"dir": d, "good": good, "pct": pct, "text": body, "name": meta["name"]}


def with_context(results):
    """下がった数字に、同じ期間に上がった数字を添えた文を作る。

    results: {key: compare()の戻り} をまとめて渡す。
    **下がったものが1つでもあれば、必ず改善点を添える。**
    添える改善が1つも無ければ、そう書く（無いのに「ただし〜」とは書かない）。
    """
    down = [r for r in results.values() if r["dir"] == "down" and not r["good"]]
    up = [r for r in results.values() if r["dir"] == "up" and r["good"]]
    # 順位の改善は、数字としては「下がる」が中身は改善。ここで拾う
    up += [r for r in results.values()
           if r["dir"] == "down" and r["good"] and r not in up]

    if not down:
        return ""
    names = "・".join(f'<b>{r["name"]}</b>（{r["text"]}）' for r in down)
    if up:
        good = "・".join(f'<b>{r["name"]}</b>（{r["text"]}）' for r in up[:3])
        return (f'<p class="note">{names} が下がりました。'
                f'ただし同じ期間に {good} が改善しています。'
                f'<b>下がった数字だけを見て判断しないでください。</b></p>')
    return (f'<p class="note stop">{names} が下がりました。'
            f'同じ期間に改善した指標はありません。'
            f'原因の切り分けを次章の改善点に載せています。</p>')


def partial_warning(label, through):
    """途中の月であることの但し書き。**途中なら必ず出す。**"""
    if not through or f"{through.year}-{through.month:02d}" != label:
        return ""
    d, full = through.day, days_in(label)
    return (f'<p class="note stop"><b>{label} は {through.month}月{d}日までの'
            f'途中経過です（{d}日／{full}日・{d / full * 100:.0f}%が経過）。</b>'
            f'月の合計をそのまま前月と比べると、必ず少なく見えます。'
            f'このレポートの前月比は、<b>1日あたりに直してから</b>比べています。</p>')


def main():
    """使い方の確認。実データではなく、決まりが効いているかを見る"""
    cur = {"impressions": 2268, "clicks": 17, "pos": 20.5}
    prev = {"impressions": 3153, "clicks": 23, "pos": 36.1}
    through = date(2026, 9, 24)
    res = {k: compare(cur, prev, k, "2026-09", "2026-08", through)
           for k in ("impressions", "clicks", "pos")}
    for k, r in res.items():
        print(f"  {r['name']:<8} {r['dir']:<5} {'良' if r['good'] else '悪'}  {r['text']}")
    print()
    print(with_context(res))
    print()
    print(partial_warning("2026-09", through))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
