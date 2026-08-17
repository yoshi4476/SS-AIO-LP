# -*- coding: utf-8 -*-
"""被リンクを送るべき記事と、その送り元を出す（月初のサイト改修用）

内部リンクは自動生成のぶんが人気ページに集中しやすく、実測で
最小0本・中央3本・最大36本まで開いていた（本文中のリンクのみ）。
順位が1ページ目の手前で止まっている記事ほどリンクが足りない。
どの記事へ、どこから送るかを、そのまま作業できる形で出す。

月次レポート（monthly_report.py）とグループレポート（group_report.py）の
両方から呼ぶため、独立したモジュールにしている。

単体で確認する場合:
    python scripts/inbound_links.py [site_id]
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cannibal_check as cc  # noqa: E402
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

MIN_IMP = 20        # これ未満の表示回数では順位が偶然に振れる
POS_FROM, POS_TO = 10, 30   # 1ページ目の手前で止まっている層
THIN = 3            # 本文リンクがこれ以下なら、サイト内で孤立ぎみとみなす


def load_articles(site_id):
    """当該サイトの公開済み記事だけを読む（他サイトの記事は指示に出さない）"""
    arts = {}
    for p in sorted((ROOT / "articles").glob("*.md")):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", p.read_text(encoding="utf-8-sig"), re.S)
        if not m:
            continue
        fm, body = m.groups()

        def fv(key, _fm=fm):
            mm = re.search(rf"^{key}:\s*(.+?)\s*$", _fm, re.M)
            return mm.group(1).strip('"') if mm else ""

        cat = fv("category")
        if sites_mod.find_category_owner(cat) != site_id:
            continue
        try:
            score = int(fv("score") or 0)
        except ValueError:
            score = 0
        if score < 90:      # 未公開の記事はリンク元にもリンク先にもしない
            continue
        arts[p.stem] = {
            "slug": p.stem, "title": fv("title"), "cat": cat, "kw": fv("keyword"),
            "out": set(re.findall(r"\]\(/[a-z-]+/([a-z0-9-]+)/\)", body)),
        }
    return arts


def plan(pages, site_id="ai-lab", limit=12):
    """pages: {"/cat/slug/": {"pos": float, "imp": int}} 形式の検索実績"""
    arts = load_articles(site_id)
    inbound = {s: 0 for s in arts}
    for x in arts.values():
        for tgt in x["out"]:
            if tgt in inbound:
                inbound[tgt] += 1

    rows = []
    for x in arts.values():
        g = pages.get(f'/{x["cat"]}/{x["slug"]}/') or {}
        pos, imp = g.get("pos"), g.get("imp", 0)
        if pos and POS_FROM < pos <= POS_TO and imp >= MIN_IMP:
            pri, why = 0, f"{pos}位・表示{imp:,}回（1ページ目の手前で停滞）"
        elif inbound[x["slug"]] <= THIN:
            pri, why = 1, f'被リンク{inbound[x["slug"]]}本（サイト内で孤立ぎみ）'
        else:
            continue

        # 送り元は、話題が近くまだリンクしていない記事。被リンクの多いページを優先する。
        # 読まれているページから送るほうが、読者の到達と評価の両方が動くため。
        cands = []
        for y in arts.values():
            if y["slug"] == x["slug"] or x["slug"] in y["out"]:
                continue
            sim = cc.dice(y["title"], x["title"]) + cc.dice(y["kw"], x["kw"])
            if y["cat"] == x["cat"]:
                sim += 0.3
            if sim >= 0.25:
                cands.append((sim + inbound[y["slug"]] / 200, y))
        cands.sort(key=lambda t: -t[0])
        if not cands:
            continue
        rows.append({
            "to": x["title"], "to_url": f'/{x["cat"]}/{x["slug"]}/',
            "inbound": inbound[x["slug"]], "pri": pri, "why": why,
            "froms": [(y["title"], f'/{y["cat"]}/{y["slug"]}/') for _, y in cands[:3]],
        })

    rows.sort(key=lambda r: (r["pri"], r["inbound"]))
    dist = sorted(inbound.values()) or [0]
    return {"rows": rows[:limit], "total": len(rows), "articles": len(arts),
            "min": dist[0], "mid": dist[len(dist) // 2], "max": dist[-1]}


def main():
    site_id = sys.argv[1] if len(sys.argv) > 1 else "ai-lab"
    r = plan({}, site_id)
    print(f"{site_id}: 公開{r['articles']}記事 / 本文リンク 最小{r['min']} 中央{r['mid']} 最大{r['max']}")
    print(f"  被リンクを足すべき記事: {r['total']}本")
    for x in r["rows"]:
        print(f"\n  [{x['inbound']}本] {x['to'][:34]}  {x['to_url']}")
        for t, u in x["froms"]:
            print(f"      ← {t[:30]}  {u}")


if __name__ == "__main__":
    main()
