# -*- coding: utf-8 -*-
"""台帳の未着手を「開かないと済まない語」の順に並べ直し、弱い語の記事には強い派生語を出す。

**なぜ要るか**: 同じ順位でもクリック率は検索語の性質で5倍違う（実測: 6〜10位で
AI集客ラボ 1.04% / 補助金 2.80%）。弱い語（例文・とは・一覧）の記事はタイトルを
変えても上がりにくい。台帳の並びは登録順のままだったので、弱い語が先に書かれていた。

やること（毎週）:
  1. 未着手を kw_intent で採点し、優先度を A（強）/ B（並）/ C（弱）に付け直す
     直接接続（hub_sheets）が使えれば台帳の「優先度」列を書く。使えなければ
     docs/kw-priority-<site>.md に書き、next_kw が同じ採点で先に拾う
  2. 狙う語が「弱」の公開記事について、GSCで実際に流入している語のうち
     「強」のパターンを含むものを派生語の候補として docs/kw-strong-<site>.md に出す

  python scripts/kw_reorder.py            # 見るだけ
  python scripts/kw_reorder.py --write    # 優先度を書く（直接接続がある場合）
出す印: KW_REORDER_OK=yes / REORDERED=<件> / STRONG_CANDS=<件>
"""
import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DOCS = ROOT / "docs"


def grade(kw):
    import kw_intent
    v, pts, _ = kw_intent.verdict(kw)
    return {"強": "A", "並": "B", "弱": "C"}[v], pts


def reorder(site, write):
    import hub_client as HC
    rows = [r for r in HC.all_kw() if r.get("site") == site and str(r.get("status", "")).strip() == "未着手"]
    graded = sorted(((grade(r["keyword"]), r["keyword"], r) for r in rows), key=lambda x: (-x[0][1], x[1]))
    changed = 0
    direct = False
    try:
        import hub_sheets as HS
        direct = HS.available()
    except Exception:
        direct = False
    if write and direct:
        sheet = HS.rows("KW台帳", HS.KW_COLS)
        for (g, _), kw, r in graded:
            for i, s in enumerate(sheet):
                if str(s[0]) == site and str(s[1]) == kw and str(s[3] or "B") != g:
                    HS._set("KW台帳", i + 2, 4, g)
                    changed += 1
                    break
    DOCS.mkdir(exist_ok=True)
    lines = [f"# 未着手の並び（{site}・{date.today()}）", "", "| 優先 | 点 | 語 |", "|:--|--:|:--|"]
    lines += [f"| {g} | {pts} | {kw} |" for (g, pts), kw, _ in graded]
    (DOCS / f"kw-priority-{site}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return graded, changed, direct


def strong_variants(site, days=90):
    """狙う語が弱い公開記事について、実際に流入している「強」の語を候補に出す"""
    import gsc_detail as G
    import kw_intent
    import sites as S
    cfg = S.load(site)
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days)
    try:
        sc = G.client()
        # 取得失敗を [] で受けると「候補0本」として前回の一覧を空で上書きする
        rows = G.q(sc, cfg["domain"], str(start), str(end), ["query", "page"], 25000,
                   raise_errors=True)
    except Exception as e:
        print(f"   {site}: GSC を読めません（{str(e)[:50]}）")
        return []
    by_page = {}
    for r in rows:
        q, page = r["keys"][0], r["keys"][1].rstrip("/").split("/")[-1]
        by_page.setdefault(page, []).append((q, int(r["impressions"]), r["position"]))
    out = []
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        kw = re.search(r"^keyword:\s*(.+)$", fm, re.M)
        cat = re.search(r"^category:\s*(\S+)", fm, re.M)
        if not kw or not cat or S.find_category_owner(cat.group(1)) != site:
            continue
        if kw_intent.verdict(kw.group(1))[0] != "弱":
            continue
        cands = [(q, imp, pos) for q, imp, pos in by_page.get(p.stem, [])
                 if kw_intent.verdict(q)[0] == "強" and imp >= 5]
        cands.sort(key=lambda x: -x[1])
        if cands:
            out.append({"slug": p.stem, "keyword": kw.group(1), "cands": cands[:3]})
    lines = [f"# 弱い語の記事に、実際に流入している強い語（{site}・{date.today()}）", "",
             "狙う語を付け替える候補。付け替えは kw_guard を通してから（食い合いを作らない）。", "",
             "| 記事 | いまの狙う語（弱） | 強い語（表示・順位） |", "|:--|:--|:--|"]
    for o in out:
        lines.append(f"| {o['slug']} | {o['keyword']} | " + "／".join(f"{q}（{imp}回・{pos:.0f}位）" for q, imp, pos in o["cands"]) + " |")
    (DOCS / f"kw-strong-{site}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    total_changed = total_strong = 0
    for sid in ([a.site] if a.site else list(S.load_all())):
        graded, changed, direct = reorder(sid, a.write)
        n = {"A": 0, "B": 0, "C": 0}
        for (g, _), _, _ in graded:
            n[g] += 1
        print(f"■ {sid}: 未着手{len(graded)}本 → 強{n['A']} / 並{n['B']} / 弱{n['C']}"
              + (f" / 台帳の優先度を{changed}件書き換え" if a.write and direct else " / 台帳は docs/kw-priority へ（直接接続なし）"))
        sv = strong_variants(sid)
        print(f"   弱い語の記事 {len(sv)}本に強い派生語の候補 → docs/kw-strong-{sid}.md")
        total_changed += changed
        total_strong += len(sv)
    print(f"KW_REORDER_OK=yes\nREORDERED={total_changed}\nSTRONG_CANDS={total_strong}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
