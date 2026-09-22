# -*- coding: utf-8 -*-
"""どの領域を押さえていて、どこが空いているかを盤面で出す。

**なぜ要るか**: 記事は1本ずつ選ばれており、全体としてどこが埋まっているかを
誰も見ていなかった。その結果、同じ業種の同じ手法に記事が重なり（実測で
クリニック21本・整骨院12本）、一方で1本も無いマスが残る。
検索エンジンとAIが「この分野を扱っているサイト」と判断するのは、
1本の出来ではなく面の広さと深さによる。空いたマスは、そのまま
「次に書くべき記事」になる。

盤面は3つの軸で作る。
  業種   … data/industries.json（歯科医院・整骨院・クリニック…）
  手法   … sites/<id>.json の kw_seeds.core（集客・MEO・AIO・SEO…）
  意図   … kw_intent の判定（開かないと済まない語かどうか）

    python scripts/coverage.py                # 盤面と空きマス
    python scripts/coverage.py --gaps 20      # 次に書くべき順に20件
    python scripts/coverage.py --site ai-lab
"""
import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

THIN = 2          # このマスの記事数がこれ以下なら「薄い」
DEEP = 5          # これ以上あれば「厚い」


def industries(site_id=""):
    """業種の軸。サイト固有の起点を優先する。

    data/industries.json は AI集客ラボ向けに作った一覧なので、
    経理BPOのコーポレートに当てると歯科医院や整骨院のマスが並び、
    埋まるはずのない空きが37マス出る。サイトが持つ起点を先に使う。
    """
    import sites as S
    ks = (S.load_all().get(site_id) or {}).get("kw_seeds") or {}
    own = ks.get("industries") or []
    d = json.loads((ROOT / "data" / "industries.json").read_text(encoding="utf-8"))
    defined = {x["name"]: x for x in (d.get("industries") or [])}
    syn = {}
    for x in (d.get("industries") or []):
        for s in [x["name"]] + (x.get("synonyms") or []):
            syn[s] = x
    if own:
        out, seen = [], set()
        for name in own:
            x = syn.get(name)
            if x and x["slug"] in seen:
                continue
            if x:
                seen.add(x["slug"])
                out.append(x)
            else:
                out.append({"slug": _norm(name), "name": name, "synonyms": [],
                            "priority": name in (ks.get("priority") or [])})
        return out
    return list(defined.values())


def cores(site_id):
    import sites as S
    cfg = S.load_all().get(site_id) or {}
    ks = cfg.get("kw_seeds") or {}
    return ks.get("core") or (cfg.get("owns") or [])[:4]


def _norm(s):
    return re.sub(r"[\s　・･／/（）()｜|【】\[\]「」、。,.\-‐－—ー_]", "", str(s).lower())


def articles(site_id=""):
    """公開済みの記事。slug -> {title, kw, cat, site}"""
    import sites as S
    out = {}
    for p in (ROOT / "articles").glob("*.md"):
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
        cat = g("category")
        owner = S.find_category_owner(cat) if cat else ""
        if site_id and owner != site_id:
            continue
        slug = g("slug") or p.stem
        out[slug] = {"title": g("title"), "kw": g("keyword"), "cat": cat,
                     "site": owner, "hay": _norm(g("title") + g("keyword"))}
    return out


def gsc_by_slug():
    """記事ごとの表示回数。キャッシュがあれば使う（無ければ0で続ける）"""
    try:
        import rank_rescue as RR
        d = RR.load()
    except Exception:
        return {}
    out = defaultdict(int)
    for rows in (d.get("sites") or {}).values():
        for r in rows:
            out[r["url"].rstrip("/").split("/")[-1]] += r["imp"]
    return out


def matrix(site_id):
    """業種 × 手法 のマス目。各マスに記事と表示回数を入れる"""
    arts = articles(site_id)
    imp = gsc_by_slug()
    inds = industries(site_id)
    cs = cores(site_id)
    cells = defaultdict(lambda: {"slugs": [], "imp": 0})
    for slug, a in arts.items():
        hit_i = [i for i in inds
                 if any(_norm(s) in a["hay"] for s in ([i["name"]] + (i.get("synonyms") or [])))]
        hit_c = [c for c in cs if _norm(c) in a["hay"]]
        for i in hit_i:
            for c in (hit_c or ["（手法なし）"]):
                k = (i["slug"], c)
                cells[k]["slugs"].append(slug)
                cells[k]["imp"] += imp.get(slug, 0)
    return cells, inds, cs, arts, imp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="ai-lab")
    ap.add_argument("--gaps", type=int, default=0, help="次に書くべき順に出す")
    a = ap.parse_args()

    cells, inds, cs, arts, imp = matrix(a.site)
    by_slug = {i["slug"]: i for i in inds}

    if not a.gaps:
        print(f"■ {a.site} の盤面（業種 × 手法）  記事{len(arts)}本\n")
        head = "".join(f"{c[:6]:>8}" for c in cs)
        print(f"{'業種':<14}{head}{'合計':>7}{'表示':>8}")
        for i in inds:
            row, tot, tim = "", 0, 0
            for c in cs:
                n = len(cells[(i["slug"], c)]["slugs"])
                tot += n
                tim += cells[(i["slug"], c)]["imp"]
                row += f"{(str(n) if n else '-'):>8}"
            mark = "★" if i.get("priority") else " "
            print(f"{mark}{i['name'][:12]:<13}{row}{tot:>7}{tim:>8,}")
        empty = [(i, c) for i in inds for c in cs if not cells[(i["slug"], c)]["slugs"]]
        thin = [(i, c) for i in inds for c in cs
                if 0 < len(cells[(i["slug"], c)]["slugs"]) <= THIN]
        print(f"\n  空いているマス {len(empty)} / 薄いマス {len(thin)} / "
              f"厚いマス {sum(1 for i in inds for c in cs if len(cells[(i['slug'], c)]['slugs']) >= DEEP)}")
        print("  次に書くべき順は --gaps で出ます")
        print("COVERAGE_OK=" + ("no" if empty else "yes"))
        if empty:
            pri = sum(1 for i, c in empty if i.get("priority"))
            print(f"   ::warning::盤面に空きが{len(empty)}マス（うち優先業種{pri}マス）。"
                  "面が欠けていると、その分野を扱うサイトとして評価されにくくなります")
        return 0

    # 次に書くべき順: 優先業種 > その業種の実績（表示）> 薄さ
    rows = []
    for i in inds:
        ind_imp = sum(cells[(i["slug"], c)]["imp"] for c in cs)
        for c in cs:
            n = len(cells[(i["slug"], c)]["slugs"])
            if n > THIN:
                continue
            score = (3 if i.get("priority") else 0) + (2 if n == 0 else 0)
            score += min(3.0, ind_imp / 200.0)
            rows.append((score, i, c, n, ind_imp))
    rows.sort(key=lambda x: -x[0])
    print(f"■ 次に書くべきマス（{a.site}）\n")
    print(f"{'点':>5}  {'業種':<14}{'手法':<8}{'いまの本数':>10}{'業種の表示':>11}")
    for score, i, c, n, ind_imp in rows[:a.gaps]:
        mark = "★" if i.get("priority") else " "
        print(f"{score:>5.1f}  {mark}{i['name'][:12]:<13}{c[:7]:<8}{n:>10}{ind_imp:>11,}")
    print("\n  ★は sites/<id>.json の kw_seeds.priority に入れた優先業種です")
    print("  この組み合わせで kw_guard と kw_intent を通してから着手してください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
