# -*- coding: utf-8 -*-
"""一次データの種類を増やす（data_auto の BUILDERS に加わる）。

**なぜ要るか**: AIが根拠に選ぶのは「そこにしか無い数字」。data_auto は4種類しか
作っていなかった。自社の計測は毎日あるので、切り口を増やすだけで種類は増える。
どれも母数と期間を添え、母数が足りなければ作らない（景品表示法）。

  業種別のクリック率      … 業種（industries.json）ごとの表示・クリック（3サイト合算）
  手法別のクリック率      … カテゴリ（AIO・SEO・MEO・補助金…）ごと
  質問形の見出しと順位    … H2に質問形がある記事と無い記事の順位の中央値
  自動修正の効き          … 打った手ごとの表示の倍率（対照群つき）
"""
import re
import statistics as st
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_N = 100


def _articles():
    """slug → {title, keyword, category, h2q, site}。運用会社のサイトの記事だけ"""
    import sites as S
    from data_auto import is_client
    out = {}
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.group(1), m.group(2)

        def g(k):
            x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
            return x.group(1).strip().strip('"') if x else ""
        if int(g("score") or 0) < 90:
            continue
        # クライアントの記事の実数は、その会社の数字。運用会社名義で公開しない
        owner = S.find_category_owner(g("category")) or ""
        if not owner or is_client(owner):
            continue
        h2 = re.findall(r"^##\s+(.+)$", body, re.M)
        out[p.stem] = {"title": g("title"), "keyword": g("keyword"), "category": g("category"),
                       "site": owner,
                       "h2q": round(sum(1 for h in h2 if re.search(r"[?？]", h)) / max(len(h2), 1), 2)}
    return out


def _pages(days):
    """3サイトのページ次元（表示・クリック・順位）。slug つき"""
    import gsc_detail as G
    from data_auto import _spans, own_sites
    sc = G.client()
    start, end = _spans(days)
    rows = []
    for cfg in own_sites():
        # 1サイトでも取れなければ例外のまま上げる（data_auto が「作れません」にする）。
        # 欠けたまま「3サイト合算」として公開すると、事実と違う数字になる
        for r in G.q(sc, cfg["domain"], str(start), str(end), ["page"], 25000, raise_errors=True):
            slug = r.get("page", r.get("keys", [""])[0] if isinstance(r.get("keys"), list) else "").rstrip("/").split("/")[-1]
            rows.append({"site": cfg["id"], "slug": slug, "imp": r["impressions"],
                         "clicks": r["clicks"], "pos": r["position"]})
    return rows, start, end


def _ds(slug, title, desc, n, n_unit, start, end, method, unit, rows, cats, den, num, neg=""):
    return {"slug": slug, "title": title, "description": desc, "n": n, "n_unit": n_unit,
            "period": f"{start}〜{end}", "start": str(start), "end": str(end), "method": method,
            "unit": unit, "categories": cats, "den_label": den, "num_label": num, "neg_label": neg,
            "rows": rows}


def ctr_by_industry(days=90):
    import industry_hub as IH
    arts = _articles()
    rows, start, end = _pages(days)
    inds, _ = IH.load()
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        a = arts.get(r["slug"])
        if not a:
            continue
        s = IH.detect(a["title"], a["keyword"], inds)
        if s:
            agg[s][0] += r["imp"]
            agg[s][1] += r["clicks"]
    name = {i["slug"]: i["name"] for i in inds}
    out, total = [], 0
    for s, (imp, clk) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
        total += imp
        if imp < 30:
            continue
        out.append({"label": name.get(s, s), "value": round(clk / imp * 100, 2), "num": clk, "den": imp,
                    "window": f"{start}〜{end}の{days}日間", "note": "3サイト合算",
                    "row_start": str(start)[:7], "row_end": str(end)[:7]})
    if total < MIN_N or len(out) < 3:
        return None
    return _ds("gyoushu-betsu-ctr", f"業種別の検索クリック率（表示{total:,}回の集計）",
               "セブンセンシズが運営する3サイトの記事を業種ごとに分け、Search Consoleの表示回数とクリック数を集計しました。",
               total, "回（表示）", start, end,
               f"Search Console の page 次元を{days}日分取得し、記事の題名と狙う語から業種を判定して合計。クリック率＝クリック÷表示。表示30回未満の業種は除外",
               "%", out, ["aio", "seo"], "表示回数", "クリック", "非クリック")


def ctr_by_method(days=90):
    from data_auto import own_sites
    arts = _articles()
    rows, start, end = _pages(days)
    names = {}
    for cfg in own_sites():
        for k, v in (cfg.get("categories") or {}).items():
            names[k] = v if isinstance(v, str) else (v[0] if isinstance(v, (list, tuple)) else k)
    agg = defaultdict(lambda: [0, 0])
    for r in rows:
        a = arts.get(r["slug"])
        if a:
            agg[a["category"]][0] += r["imp"]
            agg[a["category"]][1] += r["clicks"]
    out, total = [], 0
    for c, (imp, clk) in sorted(agg.items(), key=lambda kv: -kv[1][0]):
        total += imp
        if imp < 30:
            continue
        out.append({"label": names.get(c, c), "value": round(clk / imp * 100, 2), "num": clk, "den": imp,
                    "window": f"{start}〜{end}の{days}日間", "note": "3サイト合算",
                    "row_start": str(start)[:7], "row_end": str(end)[:7]})
    if total < MIN_N or len(out) < 3:
        return None
    return _ds("shuhou-betsu-ctr", f"手法別（AIO・SEO・MEO・補助金）の検索クリック率（表示{total:,}回の集計）",
               "記事のカテゴリ（手法）ごとに、Search Consoleの表示回数とクリック数を集計しました。同じ順位でも手法で差が出ます。",
               total, "回（表示）", start, end,
               f"Search Console の page 次元を{days}日分取得し、記事のカテゴリごとに合計。クリック率＝クリック÷表示。表示30回未満は除外",
               "%", out, ["aio", "seo"], "表示回数", "クリック", "非クリック")


def question_h2_rank(days=90):
    arts = _articles()
    rows, start, end = _pages(days)
    bands = [("質問形の見出しなし", lambda q: q == 0), ("質問形が1〜3割", lambda q: 0 < q <= 0.3),
             ("質問形が3割超", lambda q: q > 0.3)]
    pos = defaultdict(list)
    for r in rows:
        a = arts.get(r["slug"])
        if not a or r["imp"] < 5:
            continue
        for lab, f in bands:
            if f(a["h2q"]):
                pos[lab].append(r["pos"])
                break
    out, total = [], 0
    for lab, _ in bands:
        v = pos.get(lab, [])
        total += len(v)
        if len(v) < 10:
            continue
        out.append({"label": lab, "value": round(st.median(v), 1), "num": len(v), "den": len(v),
                    "window": f"{start}〜{end}の{days}日間", "note": "平均掲載順位の中央値",
                    "row_start": str(start)[:7], "row_end": str(end)[:7]})
    if total < 30 or len(out) < 2:
        return None
    return _ds("shitsumon-midashi-juni", f"質問形の見出しと検索順位（記事{total}本の集計）",
               "H2見出しに質問の形（〜とは？ など）を含む記事と含まない記事で、Search Consoleの平均掲載順位の中央値を比べました。",
               total, "本（記事）", start, end,
               f"Search Console の page 次元を{days}日分取得し、表示5回以上の記事について、H2のうち質問形の割合で3群に分け、平均掲載順位の中央値を算出。10本未満の群は除外",
               "位", out, ["aio", "seo"], "記事数", "記事", "")


def fix_effects(days=90):
    """打った手ごとの表示の倍率（触っていない記事＝対照群の中央値と並べる）"""
    import effect_ab as EA
    # 介入記録と日次はクライアントの記事も含む。運用会社の記事だけに絞る（対照群も同じ）
    own = set(_articles())
    acts = [x for x in EA.interventions() if x["slug"] in own]
    if not acts:
        return None
    daily, gsc_start, gsc_end = EA.daily_by_slug()
    daily = {s: v for s, v in daily.items() if s in own}
    touched = {x["slug"] for x in acts}
    by_kind = defaultdict(list)
    for x in acts:
        try:
            at = date.fromisoformat(x["at"])
        except ValueError:
            continue
        c = EA.change(daily, x["slug"], at, 21)
        if c:
            by_kind[x["kind"]].append((at, c[0]))
    out, total = [], 0
    for kind, rows in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        if len(rows) < 5:
            continue
        ctrl = [c[0] for at in {r[0] for r in rows} for s in daily if s not in touched
                for c in [EA.change(daily, s, at, 21)] if c]
        if len(ctrl) < 5:
            continue
        total += len(rows)
        out.append({"label": kind, "value": round(st.median([r[1] for r in rows]), 2), "num": len(rows), "den": len(rows),
                    "window": "直した日の前後21日", "note": f"対照群の中央値 ×{st.median(ctrl):.2f}",
                    "row_start": str(gsc_start)[:7], "row_end": str(gsc_end)[:7]})
    if total < 10 or len(out) < 2:
        return None
    return _ds("jidou-shusei-no-kouka", f"記事の自動修正の効き（{total}本の前後比較）",
               "内部リンクの補充・タイトルの書き換え・CTAの追加など、機械が当てた手ごとに、直した日の前後21日で表示回数の倍率を出し、同じ期間に触っていない記事（対照群）と並べました。",
               total, "本（記事）", gsc_start, gsc_end,
               "automation/logs/auto_fix.jsonl の介入記録と Search Console の日次データから、直した日の前21日と後21日の表示回数の比（中央値）。対照群は同じ日に触っていない記事。5本未満の手は除外",
               "倍", out, ["aio", "seo"], "記事数", "記事", "")


BUILDERS = [("業種別のクリック率", ctr_by_industry), ("手法別のクリック率", ctr_by_method),
            ("質問形の見出しと順位", question_h2_rank), ("自動修正の効き", fix_effects)]
