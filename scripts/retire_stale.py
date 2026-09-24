# -*- coding: utf-8 -*-
"""公開から90日たっても検索に一度も出ない記事を、近い記事へ統合して面を薄めない。

**なぜ要るか**: auto_merge は「同じ語で2本が出ている組」しか見ない。
一度も表示されない記事は誰の競合にもならず、そのまま残る。薄い記事が増えると
サイト全体の評価が下がる（8.2.5節と同じ理由）。

やること（判断は機械だけ）:
  1. 90日以上前に公開し、GSC のページ次元で90日間の表示が0の記事を出す
  2. 同じサイトの公開記事から、題名と狙う語が最も近いもの（Dice ≥ 0.35）を吸収先にする
  3. auto_merge.run_one で統合する（検算・301・内部リンクの付け替えは auto_merge と同じ）
  近い記事が無いものは統合しない（無理に吸わせると主題がぼやける）。一覧に出すだけ

  python scripts/retire_stale.py                    # 候補を見る
  python scripts/retire_stale.py --write --limit 2  # 統合する（週次）
出す印: STALE_OK=yes / STALE=<本> / MERGED=<本>
"""
import argparse
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
AGE_DAYS = 90
MIN_SIM = 0.35


def _fm(p):
    t = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    if not m:
        return None
    fm = m.group(1)

    def g(k):
        x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
        return x.group(1).strip().strip('"') if x else ""
    return {"slug": p.stem, "title": g("title"), "keyword": g("keyword"), "category": g("category"),
            "date": g("date"), "score": int(g("score") or 0)}


def shown_urls(cfg):
    """90日間に一度でも表示されたURL（末尾スラッシュを揃える）"""
    import report_verify as RV
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=AGE_DAYS)
    rows = RV._gsc(f"https://{cfg['domain']}/", start.isoformat(), end.isoformat(), ["page"], 25000).get("rows", [])
    return {r["keys"][0].rstrip("/") + "/" for r in rows if int(r.get("impressions", 0)) > 0}


def stale(site_id=""):
    import sites as S
    from cannibal_check import dice
    out = []
    for sid, cfg in S.load_all().items():
        if site_id and sid != site_id:
            continue
        arts = [a for a in (_fm(p) for p in (ROOT / "articles").glob("*.md")) if a
                and a["score"] >= 90 and S.find_category_owner(a["category"]) == sid]
        try:
            shown = shown_urls(cfg)
        except Exception as e:
            print(f"   {sid}: GSC を読めません（{str(e)[:50]}）")
            continue
        old = (date.today() - timedelta(days=AGE_DAYS)).isoformat()
        for a in arts:
            if a["date"] > old:
                continue
            url = S.article_url(cfg, a).rstrip("/") + "/"
            if url in shown:
                continue
            best, sim = None, 0.0
            for b in arts:
                if b["slug"] == a["slug"] or (S.article_url(cfg, b).rstrip("/") + "/") not in shown:
                    continue
                s = dice(a["title"] + " " + a["keyword"], b["title"] + " " + b["keyword"])
                if s > sim:
                    best, sim = b, s
            out.append({"site": sid, "loser": a["slug"], "title": a["title"], "date": a["date"],
                        "survivor": best["slug"] if best and sim >= MIN_SIM else "", "sim": round(sim, 2),
                        "kws": [{"kw": a["keyword"], "imp": 0, "win_pos": 0, "lose_pos": 0}],
                        "imp": 0, "loser_stat": {"pos": 0, "clicks": 0}, "survivor_stat": {"pos": 0}})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--site", default="")
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--budget-min", type=int, default=0)
    a = ap.parse_args()
    rows = stale(a.site)
    can = [r for r in rows if r["survivor"]]
    print(f"■ 公開{AGE_DAYS}日以上で表示ゼロ: {len(rows)}本（吸収先あり {len(can)}本）")
    for r in rows[:20]:
        print(f"   [{r['site']:<9}] {r['loser'][:34]:<34} {r['date']} → "
              + (f"{r['survivor'][:28]}（{r['sim']}）" if r["survivor"] else "近い記事なし（残す）"))
    merged = 0
    if a.write and can:
        import auto_merge as AM
        t0 = time.time()
        for pair in can[:a.limit]:
            if a.budget_min and (time.time() - t0) / 60 >= a.budget_min:
                break
            ok, why = AM.run_one(pair, True)
            AM.note(pair, ok, "（表示ゼロの整理）" + why)
            print(f"   {'○' if ok else '×'} {pair['loser'][:30]} → {pair['survivor'][:30]}: {why[:60]}")
            merged += ok
    print(f"STALE_OK=yes\nSTALE={len(rows)}\nMERGED={merged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
