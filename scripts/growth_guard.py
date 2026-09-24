# -*- coding: utf-8 -*-
"""表示とクリックが前の期間より落ちていないかを見張り、落ちた原因を分解する

「毎月必ず上がる」は保証できない。アルゴリズムの更新も季節変動もあり、
順位は自社の外側で決まる部分があるため、約束できるものではない。

できるのは、落ちたその日に気づき、原因を切り分けて戻すこと。
放置すると原因が重なって特定できなくなり、戻すのに何倍も時間がかかる。

落ちる原因は限られている。この道具は、実データからそれを分解する。
  1. 既存ページの順位が下がった      → リライト・食い合い・競合の動き
  2. ページが検索結果から消えた      → インデックス落ち・404・noindex
  3. 新しいページが出ていない        → 公開が止まっている
  4. 語の総数が減った                → 対象クエリごと失っている

使い方:
    python scripts/growth_guard.py             # 直近28日 vs その前の28日
    python scripts/growth_guard.py --days 14   # 期間を変える
    python scripts/growth_guard.py --month     # 前月と当月を比べる
"""
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# この割合を超えて落ちたら警告する。数件の増減で騒がないための下限
DROP = 0.05
MIN_IMP = 30


def spans(days, month):
    end = date.today() - timedelta(days=3)      # GSCの確定待ち
    if month:
        first = end.replace(day=1)
        prev_end = first - timedelta(days=1)
        return (first, end), (prev_end.replace(day=1), prev_end)
    start = end - timedelta(days=days - 1)
    return (start, end), (start - timedelta(days=days), start - timedelta(days=1))


def fetch(sc, dom, span, dims):
    import gsc_detail as G
    # 取れなかったのを [] にすると、前期の語が全部「消えた語」に並ぶ
    try:
        return G.q(sc, dom, str(span[0]), str(span[1]), dims, 5000, raise_errors=True)
    except Exception:
        return None


def totals(sc, dom, span):
    """表示・クリックの合計。**2通りで一致したものだけ**を返す（measure 経由）。

    次元を付けた合計は信用しない。measure.gsc_totals が
    「次元なし」と「日次の合算」を突き合わせ、食い違えば例外を投げる。
    「概ね合っている」で先に進めないようにするのが目的。
    """
    import measure
    try:
        return measure.gsc_totals(dom, span[0], span[1])
    except measure.Disagree as e:
        print(f"  {dom}: 計測が一致しないため、この数字は使いません → {e}")
        return None
    except Exception as e:
        # 0 を返すと前期との比較で -100% の下落として警告してしまう
        print(f"  {dom}: GSCから取得できないため、この数字は使いません → {str(e)[:60]}")
        return None


def main():
    import gsc_detail as G
    import sites as S

    days = 28
    if "--days" in sys.argv:
        days = int(sys.argv[sys.argv.index("--days") + 1])
    now, prev = spans(days, "--month" in sys.argv)
    sc = G.client()

    print(f"■ {now[0]}〜{now[1]}  と  {prev[0]}〜{prev[1]} の比較\n")
    alerts = []
    for sid, cfg in S.load_all().items():
        # 内訳（どの語が消えたか）には語が要るので query+page で取る。
        # ただし合計はこれで数えない — query次元は検索数の少ない語を返さないため、
        # 実測で補助金のクリックが 51回→2回 に見えていた（CLAUDE.md 0.1）
        a = fetch(sc, cfg["domain"], now, ["query", "page"])
        b = fetch(sc, cfg["domain"], prev, ["query", "page"])
        tn, tp = totals(sc, cfg["domain"], now), totals(sc, cfg["domain"], prev)
        if tn is None or tp is None:
            print(f"  {cfg['name']}: 合計が確かめられないため比較しません\n")
            continue
        (ai, ac), (bi, bc) = tn, tp
        if not ai and not bi:
            continue
        di = (ai - bi) / bi if bi else None
        dc = (ac - bc) / bc if bc else None

        def pct(v):
            return "—" if v is None else f"{v * 100:+.0f}%"

        mark = "×" if (di is not None and di < -DROP) else "○"
        print(f"{mark} {cfg['name']}")
        print(f"    表示    {bi:>6,} → {ai:>6,}  {pct(di)}")
        print(f"    クリック {bc:>6,} → {ac:>6,}  {pct(dc)}")

        if di is None or di >= -DROP or bi < MIN_IMP:
            print()
            continue

        if a is None or b is None:
            print("    内訳: 語の一覧が取得できず、分解できません\n")
            alerts.append((sid, di, 0, 0, []))
            continue
        # ここから原因の分解。合計だけ見ても何を直せばいいか分からない
        na = {(x["keys"][0], x["keys"][1]): x for x in a}
        nb = {(x["keys"][0], x["keys"][1]): x for x in b}
        lost, worse, gone_page = [], [], defaultdict(int)
        for k, x in nb.items():
            y = na.get(k)
            if y is None:
                lost.append(x)
                gone_page[x["keys"][1]] += x["impressions"]
            elif y["impressions"] < x["impressions"] and y["position"] > x["position"] + 3:
                worse.append((x, y))
        lost.sort(key=lambda x: -x["impressions"])
        worse.sort(key=lambda p: p[0]["impressions"] - p[1]["impressions"])

        lost_imp = sum(x["impressions"] for x in lost)
        worse_imp = sum(x["impressions"] - y["impressions"] for x, y in worse)
        print(f"    内訳: 消えた語 {len(lost)}語（表示{lost_imp:,}） / "
              f"順位が下がった語 {len(worse)}語（表示{worse_imp:,}）")
        for x in lost[:3]:
            print(f"      消えた  「{x['keys'][0][:26]}」表示{x['impressions']}"
                  f" {x['position']:.0f}位 {x['keys'][1].rstrip('/').split('/')[-1][:24]}")
        for x, y in worse[:3]:
            print(f"      下降    「{x['keys'][0][:26]}」"
                  f"{x['position']:.0f}→{y['position']:.0f}位 "
                  f"表示{x['impressions']}→{y['impressions']}")
        top = sorted(gone_page.items(), key=lambda kv: -kv[1])[:2]
        for url, imp in top:
            print(f"      要確認  {url}（消えた表示{imp:,}）")
        alerts.append((sid, di, len(lost), len(worse), [u for u, _ in top]))
        print()

    print("GROWTH_DROP=" + ("yes" if alerts else "no"))
    if alerts:
        print("\n  次に見るところ")
        print("   1. 消えたページが200を返すか（404・noindex・配信漏れ）")
        print("   2. 順位が下がった語で自社ページが競合していないか"
              " → python scripts/cannibal_check.py --serp")
        print("   3. 該当記事の更新日が古くないか（鮮度）")
    return alerts


if __name__ == "__main__":
    main()
