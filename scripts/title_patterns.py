# -*- coding: utf-8 -*-
"""タイトルの型（年号・数字・限定・疑問・括弧）ごとの実測クリック率を出し、勝った型を書き換えの指示に渡す。

**なぜ要るか**: 同じ順位でもタイトルの型でCTRは倍以上変わる。どの型が効くかは
サイトと読者で違うので、通説ではなく自社のGSCで決める。結果は data/title_patterns.md に
書き、auto_rewrite --kind title が読む（勝った型に寄せる指示になる）。

  python scripts/title_patterns.py
出す印: TITLE_PAT_OK=yes。表示300回未満の型は出さない（差が誤差になる）
"""
import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "title_patterns.md"
MIN_IMP = 300
PATTERNS = [
    ("年号入り", re.compile(r"20\d\d")),
    ("数字入り（◯選・◯つ・◯ステップ）", re.compile(r"\d+(選|つ|ステップ|項目|社|本|例|パターン|手順|条件|原因|方法)")),
    ("疑問形（？）", re.compile(r"[?？]")),
    ("限定・警告（NG・落とし穴・失敗・注意）", re.compile(r"NG|落とし穴|失敗|注意|やってはいけない|禁止|対象外|リスク")),
    ("括弧【】", re.compile(r"【.+?】")),
    ("区切り｜", re.compile(r"｜")),
    ("費用・相場・いくら", re.compile(r"費用|相場|いくら|料金|価格")),
    ("比較・違い・どっち", re.compile(r"比較|違い|どっち|vs")),
]


def titles():
    out = {}
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.search(r"^title:\s*(.+)$", t[:800], re.M)
        if m:
            out[p.stem] = m.group(1).strip().strip('"')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    a = ap.parse_args()
    import gsc_detail as G
    import sites as S
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=a.days)
    tt = titles()
    agg = {name: [0, 0, 0] for name, _ in PATTERNS}     # imp, clicks, pages
    base = [0, 0, 0]
    try:
        sc = G.client()
    except Exception as e:
        print(f"GSC を読めません（{str(e)[:60]}）\nTITLE_PAT_OK=unknown")
        return 0
    for cfg in S.load_all().values():
        for r in G.q(sc, cfg["domain"], str(start), str(end), ["page"], 25000):
            slug = r["keys"][0].rstrip("/").split("/")[-1]
            title = tt.get(slug)
            if not title or r["position"] > 20:      # 1〜20位だけ（順位の差をタイトルの差と混ぜない）
                continue
            imp, clk = int(r["impressions"]), int(r["clicks"])
            base[0] += imp; base[1] += clk; base[2] += 1
            for name, pat in PATTERNS:
                if pat.search(title):
                    agg[name][0] += imp; agg[name][1] += clk; agg[name][2] += 1
    if base[0] < MIN_IMP:
        print("表示が少なく判定できません\nTITLE_PAT_OK=unknown")
        return 0
    all_ctr = base[1] / base[0] * 100
    rows = []
    for name, (imp, clk, n) in agg.items():
        if imp < MIN_IMP:
            continue
        rows.append((name, clk / imp * 100, imp, n))
    rows.sort(key=lambda x: -x[1])
    lines = [f"# タイトルの型ごとの実測クリック率（1〜20位・{start}〜{end}・3サイト合算）", "",
             f"全体: CTR {all_ctr:.2f}%（表示{base[0]:,}回・{base[2]}ページ）", "",
             "| 型 | CTR | 全体比 | 表示 | ページ数 |", "|:--|--:|--:|--:|--:|"]
    for name, ctr, imp, n in rows:
        lines.append(f"| {name} | {ctr:.2f}% | ×{ctr / all_ctr:.2f} | {imp:,} | {n} |")
    win = [name for name, ctr, _, _ in rows if ctr >= all_ctr * 1.15][:3]
    lose = [name for name, ctr, _, _ in rows if ctr <= all_ctr * 0.85][:3]
    lines += ["", "## 書き換えの指示に渡す型", "",
              ("寄せる型: " + "／".join(win)) if win else "寄せる型: （全体比1.15倍以上の型なし。型より語の性質を優先）",
              ("避ける型: " + "／".join(lose)) if lose else "避ける型: なし", ""]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:4] + lines[6:6 + len(rows)] + lines[-4:]))
    print("TITLE_PAT_OK=yes")
    return 0


def brief():
    """auto_rewrite が読む分（無ければ空）"""
    if not OUT.is_file():
        return ""
    t = OUT.read_text(encoding="utf-8")
    m = re.search(r"## 書き換えの指示に渡す型\n\n(.*?)\n\n", t + "\n\n", re.S)
    return m.group(1).strip() if m else ""


if __name__ == "__main__":
    sys.exit(main())
