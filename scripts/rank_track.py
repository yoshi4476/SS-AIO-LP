# -*- coding: utf-8 -*-
"""検索順位を毎日記録し、変動と伸びしろを出す（GSCの実データ）

使い方:
    python scripts/rank_track.py            # 記録して要約を表示
    python scripts/rank_track.py --report    # 記録せず、蓄積データから要約だけ

順位を測らないと「リライトすべき記事」が勘になる。GSCの平均掲載順位は
実際に表示された位置の平均なので、順位チェックツールを買わずに実測できる。
記録は data/ranks/<site>.json に日別で追記する（1日1回の実行を想定）。
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gcreds  # noqa: E402
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ranks"
SA = ROOT / "indexing-service-account.json"
# 11〜30位は「あと少しで1ページ目」。ここが最も費用対効果の高いリライト対象
STRIKING_LO, STRIKING_HI = 11, 30


def fetch(site_url, days=28):
    creds = gcreds.load(SA, ["https://www.googleapis.com/auth/webmasters.readonly"])
    from googleapiclient.discovery import build
    sc = build("searchconsole", "v1", credentials=creds)
    # GSCは直近2〜3日が未確定なので、少し前までを見る
    end = date.today() - timedelta(days=3)
    res = sc.searchanalytics().query(siteUrl=site_url, body={
        "startDate": (end - timedelta(days=days)).isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["query", "page"], "rowLimit": 1000}).execute()
    out = []
    for r in res.get("rows", []):
        q, p = r["keys"]
        out.append({"kw": q, "url": p, "pos": round(r["position"], 1),
                    "imp": int(r["impressions"]), "clicks": int(r["clicks"]),
                    "ctr": round(r["ctr"] * 100, 2)})
    return out


def load_hist(site_id):
    f = OUT / f"{site_id}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}


def main():
    report_only = "--report" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    for cfg in sites_mod.load_all().values():
        sid, url = cfg["id"], f"https://{cfg['domain']}/"
        hist = load_hist(sid)
        if not report_only:
            try:
                rows = fetch(url)
            except Exception as e:
                print(f"  {sid}: 取得できません（{str(e)[:70]}）")
                continue
            hist[today] = rows
            # 90日を超える分は捨てる（判断に使わないデータを溜めても意味がない）
            for d in sorted(hist)[:-90]:
                hist.pop(d)
            (OUT / f"{sid}.json").write_text(
                json.dumps(hist, ensure_ascii=False), encoding="utf-8")

        days = sorted(hist)
        if not days:
            print(f"  {sid}: 記録がありません")
            continue
        cur = {(r["kw"], r["url"]): r for r in hist[days[-1]]}
        # 7日前と比べる（前日比は誤差が大きく、判断材料にならない）
        base_day = next((d for d in reversed(days[:-1])
                         if (date.fromisoformat(days[-1]) - date.fromisoformat(d)).days >= 7), None)
        prev = {(r["kw"], r["url"]): r for r in hist[base_day]} if base_day else {}

        striking = sorted([r for r in cur.values() if STRIKING_LO <= r["pos"] <= STRIKING_HI],
                          key=lambda r: -r["imp"])
        top10 = [r for r in cur.values() if r["pos"] <= 10]
        # 上位なのにクリックが無いのは、AI回答に答えを取られている可能性がある
        zero_click = [r for r in top10 if r["clicks"] == 0 and r["imp"] >= 5]

        print(f"\n■ {cfg['name']}（計測KW {len(cur)}件）")
        print(f"   10位以内 {len(top10)}件 / 11〜30位 {len(striking)}件"
              + (f" / 前回比は{base_day}と比較" if base_day else " / 比較対象なし（初回）"))
        if striking:
            print("   ＜1ページ目まであと少し（表示回数順）＞")
            for r in striking[:5]:
                d = ""
                if (r["kw"], r["url"]) in prev:
                    diff = prev[(r["kw"], r["url"])]["pos"] - r["pos"]
                    d = f"（{diff:+.1f}）" if abs(diff) >= 0.5 else "（横ばい）"
                print(f"     {r['pos']:5.1f}位{d:9s} 表示{r['imp']:4d}  {r['kw'][:28]}")
        if zero_click:
            print("   ＜10位以内なのにクリック0（AI回答に取られている疑い）＞")
            for r in sorted(zero_click, key=lambda r: -r["imp"])[:5]:
                print(f"     {r['pos']:5.1f}位  表示{r['imp']:4d}  {r['kw'][:28]}")


if __name__ == "__main__":
    main()
