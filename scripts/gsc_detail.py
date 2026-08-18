# -*- coding: utf-8 -*-
"""3サイトの表示回数・クリック数を、期間・記事・クエリの単位で出す

月次レポートは要約しか載せないため、生の内訳を見たいときはこれを使う。
GSCのデータは3日ほど遅れて確定するため、直近3日は少なめに出る。

使い方:
    python scripts/gsc_detail.py            # 直近28日
    python scripts/gsc_detail.py --days 90
    python scripts/gsc_detail.py --site ai-lab --top 30
"""
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sites as sites_mod  # noqa: E402

SA = ROOT / "indexing-service-account.json"
SCOPE = ["https://www.googleapis.com/auth/webmasters.readonly"]


def client():
    import gcreds
    from googleapiclient.discovery import build
    return build("searchconsole", "v1", credentials=gcreds.load(SA, SCOPE))


def q(sc, domain, start, end, dims=None, limit=1000):
    body = {"startDate": start, "endDate": end, "rowLimit": limit}
    if dims:
        body["dimensions"] = dims
    try:
        res = sc.searchanalytics().query(siteUrl=f"https://{domain}/", body=body).execute()
    except Exception as e:
        print(f"    取得失敗: {str(e)[:90]}")
        return []
    return res.get("rows", [])


def row(r):
    return {"k": r.get("keys", [""]), "imp": int(r["impressions"]), "clicks": int(r["clicks"]),
            "ctr": r["clicks"] / r["impressions"] * 100 if r["impressions"] else 0,
            "pos": r["position"]}


def bar(v, mx, w=22):
    return "█" * max(1, round(v / mx * w)) if v else ""


def main():
    a = sys.argv
    days = int(a[a.index("--days") + 1]) if "--days" in a else 28
    top = int(a[a.index("--top") + 1]) if "--top" in a else 15
    only = a[a.index("--site") + 1] if "--site" in a else None

    end = date.today() - timedelta(days=3)      # 確定分だけを見る
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    sc = client()

    print(f"集計期間: {start} 〜 {end}（{days}日間 / GSC確定分）")
    print(f"比較期間: {prev_start} 〜 {prev_end}\n")

    grand = defaultdict(int)
    for sid, cfg in sites_mod.load_all().items():
        if only and sid != only:
            continue
        d = cfg["domain"]
        print("=" * 78)
        print(f"■ {cfg['name']}  https://{d}/")
        print("=" * 78)

        cur = q(sc, d, str(start), str(end))
        pre = q(sc, d, str(prev_start), str(prev_end))
        if not cur:
            print("  データなし\n")
            continue
        c, p = row(cur[0]), (row(pre[0]) if pre else {"imp": 0, "clicks": 0, "ctr": 0, "pos": 0})
        grand["imp"] += c["imp"]; grand["clicks"] += c["clicks"]

        def diff(k, unit="", pct=False):
            dv = c[k] - p[k]
            s = f"{dv:+,.1f}" if pct else f"{dv:+,}"
            return f"{c[k]:,.1f}{unit}" if pct else f"{c[k]:,}{unit}", f"（前期比 {s}）"

        v, dd = diff("imp"); print(f"  表示回数     {v:>12}  {dd}")
        v, dd = diff("clicks"); print(f"  クリック数   {v:>12}  {dd}")
        v, dd = diff("ctr", "%", True); print(f"  CTR          {v:>12}  {dd}")
        print(f"  平均順位     {c['pos']:>11.1f}位  （前期比 {c['pos']-p['pos']:+.1f}）")
        print(f"  1日あたり    表示 {c['imp']/days:,.0f} / クリック {c['clicks']/days:.1f}")

        # 順位帯ごとの内訳（どこに表示が溜まっているか）
        qs = [row(r) for r in q(sc, d, str(start), str(end), ["query"], 5000)]
        band = [("1〜3位", 0, 3), ("4〜10位", 3, 10), ("11〜20位", 10, 20),
                ("21〜50位", 20, 50), ("51位以下", 50, 999)]
        print(f"\n  ▼ 順位帯別（全{len(qs):,}キーワード）")
        print(f"    {'順位帯':<10}{'KW数':>7}{'表示':>10}{'クリック':>9}{'CTR':>8}")
        for nm, lo, hi in band:
            g = [x for x in qs if lo < x["pos"] <= hi]
            if not g:
                continue
            i_ = sum(x["imp"] for x in g); k_ = sum(x["clicks"] for x in g)
            print(f"    {nm:<10}{len(g):>7,}{i_:>10,}{k_:>9,}"
                  f"{(k_/i_*100 if i_ else 0):>7.2f}%")

        # 上位に入っているキーワード。順位帯の数だけでは
        # 「何で取れているのか」が分からないため、実際の語を出す。
        for nm, lo, hi, note in (("1〜10位（1ページ目）", 0, 10, "クリックが発生する層"),
                                 ("11〜20位（2ページ目）", 10, 20, "リライトで1ページ目に届く層"),
                                 ("21〜30位", 20, 30, "内部リンクと加筆で狙える層")):
            g = sorted([x for x in qs if lo < x["pos"] <= hi], key=lambda x: x["pos"])
            print()
            print(f"  ▼ {nm} {len(g)}語 — {note}")
            if not g:
                print("    なし")
                continue
            print(f"    {'順位':>5} {'表示':>7} {'クリック':>8} {'CTR':>7}  キーワード")
            for x in g[:top]:
                print(f"    {x['pos']:>5.1f} {x['imp']:>7,} {x['clicks']:>8,} "
                      f"{x['ctr']:>6.1f}%  {x['k'][0][:40]}")
            if len(g) > top:
                print(f"    … 他{len(g)-top}語")

        # 上位に入っているページ（順位が近いページ単位でも見る）
        pg = sorted([row(r) for r in q(sc, d, str(start), str(end), ["page"], 1000)],
                    key=lambda x: x["pos"])
        up = [x for x in pg if x["pos"] <= 20]
        print()
        print(f"  ▼ 20位以内に入っているページ {len(up)}本")
        if up:
            print(f"    {'順位':>5} {'表示':>7} {'クリック':>8}  ページ")
            for x in up[:top]:
                print(f"    {x['pos']:>5.1f} {x['imp']:>7,} {x['clicks']:>8,}  "
                      f"{x['k'][0].replace(f'https://{d}', '')[:46]}")
        else:
            print("    なし")

        # クリックを生んでいるクエリ
        got = sorted([x for x in qs if x["clicks"]], key=lambda x: -x["clicks"])[:top]
        print(f"\n  ▼ クリックのあったキーワード（{len([x for x in qs if x['clicks']])}語）")
        if got:
            mx = got[0]["clicks"]
            print(f"    {'クリック':>8} {'表示':>7} {'CTR':>7} {'順位':>6}  キーワード")
            for x in got:
                print(f"    {x['clicks']:>8,} {x['imp']:>7,} {x['ctr']:>6.1f}% "
                      f"{x['pos']:>5.1f}  {bar(x['clicks'], mx, 10):<10} {x['k'][0][:34]}")
        else:
            print("    まだありません")

        # 表示は多いがクリックが取れていないクエリ（伸びしろ）
        loss = sorted([x for x in qs if x["imp"] >= 30 and x["ctr"] < 1.5],
                      key=lambda x: -x["imp"])[:top]
        print(f"\n  ▼ 表示は多いがクリックが少ないキーワード（{len(loss)}語 / 表示30以上・CTR1.5%未満）")
        if loss:
            print(f"    {'表示':>7} {'クリック':>8} {'CTR':>7} {'順位':>6}  キーワード")
            for x in loss:
                print(f"    {x['imp']:>7,} {x['clicks']:>8,} {x['ctr']:>6.1f}% "
                      f"{x['pos']:>5.1f}  {x['k'][0][:40]}")
        else:
            print("    該当なし")

        # ページ別
        ps = sorted([row(r) for r in q(sc, d, str(start), str(end), ["page"], 1000)],
                    key=lambda x: -x["imp"])[:top]
        print(f"\n  ▼ ページ別（表示回数順）")
        print(f"    {'表示':>7} {'クリック':>8} {'CTR':>7} {'順位':>6}  ページ")
        for x in ps:
            print(f"    {x['imp']:>7,} {x['clicks']:>8,} {x['ctr']:>6.1f}% "
                  f"{x['pos']:>5.1f}  {x['k'][0].replace(f'https://{d}', '')[:44]}")

        # デバイス・国
        for dim, label in (("device", "デバイス"), ("country", "国")):
            rs = sorted([row(r) for r in q(sc, d, str(start), str(end), [dim], 20)],
                        key=lambda x: -x["imp"])[:4]
            if rs:
                print(f"\n  ▼ {label}別")
                for x in rs:
                    print(f"    {x['k'][0]:<10} 表示 {x['imp']:>7,} / クリック {x['clicks']:>5,}"
                          f" / CTR {x['ctr']:>5.2f}% / 順位 {x['pos']:.1f}")
        print()

    # 日別の推移。計測開始からの立ち上がりを、平均ではなく生の数字で見る
    print("=" * 78)
    print("■ 日別の推移（表示 / クリック）")
    per = {}
    for sid, cfg in sites_mod.load_all().items():
        if only and sid != only:
            continue
        per[cfg["name"][:10]] = {
            r["keys"][0]: (int(r["impressions"]), int(r["clicks"]))
            for r in q(sc, cfg["domain"], str(start), str(end), ["date"], 400)}
    days_ = sorted({k for v in per.values() for k in v})
    if days_:
        print(f"  {'日付':<12}" + "".join(f"{n:>16}" for n in per) + f"{'合計':>12}")
        for k in days_:
            line, ti, tc = f"  {k:<12}", 0, 0
            for v in per.values():
                i_, c_ = v.get(k, (0, 0))
                ti += i_; tc += c_
                line += f"{i_:>10,}/{c_:<5}"
            line += f"{ti:>7,}/{tc:<4}"
            print(line)
        for n, v in per.items():
            if v:
                print(f"  {n}: 計測開始 {min(v)} / {len(v)}日分")
    print()
    print("=" * 78)
    print(f"3サイト合計: 表示 {grand['imp']:,} 回 / クリック {grand['clicks']:,} 回 "
          f"/ CTR {grand['clicks']/max(grand['imp'],1)*100:.2f}%")


if __name__ == "__main__":
    main()
