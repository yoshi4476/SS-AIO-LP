# -*- coding: utf-8 -*-
"""直した記事が、その後どうなったかを測る。

「対策した」と「効果があった」は別物である。直した日をgitから取り、
その前後で同じ長さの期間を比べれば、効いたかどうかが数字で出る。

比べるのは表示回数・クリック・平均順位の3つ。順位は小さいほど良いため、
差は符号を反転して「改善」と書く。読む人に毎回考えさせないため。

  python scripts/effect.py            # 直近30日に直した記事
  python scripts/effect.py --days 60
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
MIN_BEFORE = 7        # これ未満の観測日数では判定しない


# 内部リンクの一括補充など、全記事に触るコミットがある。これを「直した日」と
# 見なすと、全記事が同じ日に直されたことになり、効果を測れない。
# 1回で何本も触るコミットは、記事ごとの施策ではないので除く
BULK = 40


def edited(days, until=None):
    """記事ごとの、最後に手を入れた日。

    until を渡すと、その日より前の更新だけを見る。今日の一括修正に
    埋もれて過去の施策が測れなくなるのを避けるため。
    """
    r = subprocess.run(
        ["git", "log", f"--since={days} days ago", "--name-only",
         "--pretty=format:@%cI", "--", "articles/"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    commits, cur = [], None
    for line in r.stdout.splitlines():
        if line.startswith("@"):
            cur = (line[1:11], [])
            commits.append(cur)
        elif line.endswith(".md") and cur:
            cur[1].append(Path(line).stem)
    out = {}
    for when, files in commits:
        if len(files) >= BULK:
            continue                       # 一括修正は個別の施策ではない
        if until and when >= until:
            continue
        for f in files:
            out.setdefault(f, when)        # 新しいコミットが先に来る
    return out


def sc_client():
    import gcreds
    from googleapiclient.discovery import build
    return build("searchconsole", "v1", credentials=gcreds.load(
        ROOT / "indexing-service-account.json",
        ["https://www.googleapis.com/auth/webmasters.readonly"]))


def page_stats(sc, domain, slug, start, end):
    """そのページの、期間内の表示・クリック・平均順位"""
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": ["page"], "rowLimit": 5000}
    try:
        rows = sc.searchanalytics().query(
            siteUrl=f"https://{domain}/", body=body).execute().get("rows", [])
    except Exception:
        return None
    for r in rows:
        if r["keys"][0].rstrip("/").rsplit("/", 1)[-1] == slug:
            return (int(r["impressions"]), int(r["clicks"]), r["position"])
    return (0, 0, 0)


def top_queries(sc, domain, slug, start, end, n=3):
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": ["query"], "rowLimit": 200,
            "dimensionFilterGroups": [{"filters": [
                {"dimension": "page", "operator": "contains", "expression": "/" + slug}]}]}
    try:
        rows = sc.searchanalytics().query(
            siteUrl=f"https://{domain}/", body=body).execute().get("rows", [])
    except Exception:
        return []
    rows.sort(key=lambda r: -int(r["impressions"]))
    return [(r["keys"][0], int(r["impressions"]), int(r["clicks"]), r["position"])
            for r in rows[:n]]


def collect(days=30, until=None):
    conf = {p.stem: json.loads(p.read_text(encoding="utf-8"))
            for p in (ROOT / "sites").glob("*.json")}
    cs = {k: s for s, c in conf.items() for k in (c.get("categories") or {})}
    sc = sc_client()
    today = date.today() - timedelta(days=3)       # GSCの確定分
    out = []
    for slug, when in edited(days, until).items():
        p = ROOT / "articles" / f"{slug}.md"
        if not p.is_file():
            continue
        head = p.read_text(encoding="utf-8", errors="replace")[:1200]
        m = re.search(r"^category:\s*(.+)$", head, re.M)
        site = cs.get(m.group(1).strip()) if m else None
        if not site:
            continue
        d = datetime.fromisoformat(when).date()
        after_days = (today - d).days
        if after_days < MIN_BEFORE:
            out.append({"slug": slug, "site": site, "when": when,
                        "wait": MIN_BEFORE - after_days})
            continue
        span = min(after_days, 28)
        before = page_stats(sc, conf[site]["domain"], slug,
                            d - timedelta(days=span), d - timedelta(days=1))
        after = page_stats(sc, conf[site]["domain"], slug, d, d + timedelta(days=span - 1))
        if before is None or after is None:
            continue
        out.append({"slug": slug, "site": site, "when": when, "span": span,
                    "before": before, "after": after,
                    "queries": top_queries(sc, conf[site]["domain"], slug,
                                           d, d + timedelta(days=span - 1))})
    return out



def actions(rows):
    """効果の数字から、次にやることを決める。

    感想ではなく条件で決める。人が毎回判断すると、判断の基準が
    その日の気分で変わり、何が効いたのか後から検証できなくなる。
    """
    out = []
    for r in rows:
        if "before" not in r:
            continue
        bi, bc, bp = r["before"]
        ai, ac, ap_ = r["after"]
        if ai >= 20 and ac == 0 and ap_ and ap_ <= 20.5:
            # 1ページ目に近いのにクリックが出ない。snippetの問題
            out.append({"slug": r["slug"], "site": r["site"], "do": "title",
                        "why": f"表示{ai}・クリック0・{ap_:.0f}位",
                        "how": "タイトルに、検索結果には出せないもの"
                               "（違反例・失敗例・自社の実測）を置く"})
        elif ai >= 20 and ap_ and ap_ > 20.5:
            # 見られているが順位が足りない。機械で足せる
            out.append({"slug": r["slug"], "site": r["site"], "do": "links",
                        "why": f"表示{ai}・{ap_:.0f}位",
                        "how": "関連記事から内部リンクを送って順位を押し上げる"})
        elif bi > 0 and ai < bi * 0.7:
            out.append({"slug": r["slug"], "site": r["site"], "do": "review",
                        "why": f"表示が{bi}から{ai}へ減少",
                        "how": "直した内容が検索意図とずれていないか見直す"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", default="", help="やることを機械が読む形で書き出す")
    ap.add_argument("--until", default="",
                    help="この日より前の更新だけを見る（YYYY-MM-DD）")
    a = ap.parse_args()
    rows = collect(a.days, a.until or None)
    done = [r for r in rows if "before" in r]
    waiting = [r for r in rows if "wait" in r]
    done.sort(key=lambda r: -(r["after"][0] - r["before"][0]))

    print("■ 直した記事の効果（前後で同じ日数を比較）\n")
    if not done:
        print("   判定できる記事がまだありません")
    print("  %-34s %-10s %11s %11s %9s" %
          ("記事", "直した日", "表示", "クリック", "順位"))
    for r in done:
        bi, bc, bp = r["before"]
        ai, ac, ap_ = r["after"]
        # 順位は小さいほど良い。改善を正の値で見せる
        dp = (bp - ap_) if (bp and ap_) else 0
        print("  %-34s %-10s %5d→%-5d %5d→%-5d %+8.1f" %
              (r["slug"][:34], r["when"], bi, ai, bc, ac, dp))
        for q, i, c, pos in r["queries"][:2]:
            print("       ↳ %-30s 表示%4d ｸﾘｯｸ%2d %5.1f位" % (q[:30], i, c, pos))
    if waiting:
        print("\n  判定待ち（直してから日が浅い）: %d本" % len(waiting))
        for r in waiting[:6]:
            print("     %-34s あと%d日" % (r["slug"][:34], r["wait"]))

    if done:
        up = [r for r in done if r["after"][0] > r["before"][0]]
        print("\n  表示が増えた記事 %d / %d本" % (len(up), len(done)))
        print("  ※ 直した効果のほかに、季節や競合の動きも混ざります。"
              "1本ごとの増減より、全体の傾向で見てください。")
    if a.json:
        acts = actions(rows)
        Path(a.json).write_text(json.dumps(acts, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print()
        print("  やること %d件を書き出しました: %s" % (len(acts), a.json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
