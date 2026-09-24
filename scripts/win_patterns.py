# -*- coding: utf-8 -*-
"""AI検索に引用が取れた記事の「型」を、次の記事を書く指示へ自動で渡す。

**なぜ要るか**: 引用が取れた記事は勝ちパターンで、レポートに載せて人が読むだけだった。
書く側（multi_site_prompt）はそれを見ていない。ここで引用実績のある記事の構造
（冒頭の長さ・表・FAQ数・質問形H2の割合・出典つき数字）を数え、そのままの見出しと
冒頭を、書く前に読ませる。

材料（引用の実測）: data/ai_kw/<site>.json の ai.ours=true の語、
                  data/ai_citations/*.json の measured（cited=true）
引用実績が1本も無ければ、何も渡さない（無いものを型にしない）。

  python scripts/win_patterns.py --site ai-lab          # data/win_patterns/<site>.md を書く
  python scripts/win_patterns.py --brief ai-lab         # 書く前に読ませる分を出す
"""
import argparse
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "win_patterns"


def _norm(s):
    return re.sub(r"[\s　・･／/（）()｜|【】\[\]「」、。,.\-‐－—_]", "", str(s).lower())


def cited_words(site_id):
    words = set()
    p = ROOT / "data" / "ai_kw" / f"{site_id}.json"
    if p.is_file():
        for r in json.loads(p.read_text(encoding="utf-8")).get("items", []):
            if (r.get("ai") or {}).get("ours"):
                words.add(_norm(r["kw"]))
    for f in sorted(glob.glob(str(ROOT / "data" / "ai_citations" / "*.json")))[-3:]:
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for r in ((d.get("measured") or {}).get("sites") or {}).get(site_id, {}).get("items", []):
            if r.get("cited"):
                words.add(_norm(r["kw"]))
    return words


def features(body, fm=""):
    h2 = re.findall(r"^##\s+(.+)$", body, re.M)
    lead = re.split(r"\n##\s", body, maxsplit=1)[0]
    lead_txt = re.sub(r"<[^>]+>|\*\*", "", lead)
    return {"h2": h2, "q_ratio": round(sum(1 for h in h2 if re.search(r"[?？]", h)) / max(len(h2), 1), 2),
            "tables": len(re.findall(r"^\|:?-", body, re.M)), "faq": len(re.findall(r"^\s*-\s*q:", fm + "\n" + body, re.M)),
            "defbox": body.count('class="definition-box"'),
            "sourced_numbers": len(re.findall(r"\d[\d,.]*[%円件本社人]?[^\n]{0,60}https?://", body)),
            "lead": lead_txt.strip()[:220]}


def articles_for(site_id, words):
    import sites as S
    hits = []
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.group(1), m.group(2)
        kw = re.search(r"^keyword:\s*(.+)$", fm, re.M)
        cat = re.search(r"^category:\s*(\S+)", fm, re.M)
        if not kw or not cat or S.find_category_owner(cat.group(1)) != site_id:
            continue
        if _norm(kw.group(1)) in words:
            title = re.search(r"^title:\s*(.+)$", fm, re.M)
            hits.append({"slug": p.stem, "title": title.group(1).strip() if title else p.stem,
                         "keyword": kw.group(1).strip(), **features(body, fm)})
    return hits


def write(site_id):
    hits = articles_for(site_id, cited_words(site_id))
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{site_id}.md"
    if not hits:
        p.write_text("", encoding="utf-8")
        return p, 0
    n = len(hits)
    avg = lambda k: round(sum(h[k] for h in hits) / n, 1)
    lines = [f"# AI検索に引用された記事の型（{site_id}・{n}本）", "",
             "引用が取れた記事に共通する数え方（これに揃える）:",
             f"- H2のうち質問形の割合 {avg('q_ratio')} / 比較表 {avg('tables')}個 / FAQ {avg('faq')}問 / 定義ブロック {avg('defbox')}個 / 出典つき数字 {avg('sourced_numbers')}箇所", ""]
    for h in hits[:3]:
        lines += [f"## {h['title']}（狙う語: {h['keyword']}）", "冒頭:", "> " + h["lead"], "見出し:"]
        lines += [f"- {x}" for x in h["h2"][:8]] + [""]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p, n


def ranked_for(site_id, kw, n=3):
    """同じ業種で、検索1ページ目（10位以内）にいる公開記事の型。引用実績が無いときの型にする。
    業種が判定できない語なら、同じサイトの上位記事から取る"""
    import industry_hub as IH
    import sites as S
    inds, _ = IH.load()
    ind = IH.detect(kw, kw, inds)
    pos = {}
    p = ROOT / "data" / "ranks" / f"{site_id}.json"
    if p.is_file():
        try:
            hist = json.loads(p.read_text(encoding="utf-8"))
            for r in hist[sorted(hist)[-1]]:
                s = str(r.get("url", "")).rstrip("/").split("/")[-1]
                if s and r.get("pos") is not None:
                    pos[s] = min(pos.get(s, 99), float(r["pos"]))
        except Exception:
            pass
    rows = []
    for md in (ROOT / "articles").glob("*.md"):
        if pos.get(md.stem, 99) > 10:
            continue
        t = md.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.group(1), m.group(2)
        title = (re.search(r"^title:\s*(.+)$", fm, re.M) or [None, ""])[1].strip().strip('"')
        k = (re.search(r"^keyword:\s*(.+)$", fm, re.M) or [None, ""])[1].strip()
        cat = (re.search(r"^category:\s*(\S+)", fm, re.M) or [None, ""])[1]
        if S.find_category_owner(cat) != site_id:
            continue
        if ind and IH.detect(title, k, inds) != ind:
            continue
        rows.append({"slug": md.stem, "title": title, "keyword": k, "pos": pos[md.stem], **features(body, fm)})
    rows.sort(key=lambda r: r["pos"])
    return ind, rows[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--brief", default="", help="書く前に読ませる分を出す")
    ap.add_argument("--kw", default="", help="これから書く語。引用実績が無ければ、同じ業種の上位記事の型を出す")
    a = ap.parse_args()
    import sites as S
    if a.brief:
        p = OUT / f"{a.brief}.md"
        t = p.read_text(encoding="utf-8") if p.is_file() else ""
        if t.strip():
            print(t)
            return 0
        if a.kw:
            ind, rows = ranked_for(a.brief, a.kw)
            if rows:
                iname = next((i["name"] for i in __import__("industry_hub").load()[0] if i["slug"] == ind), ind)
                print(f"# 同じ{'業種（' + iname + '）' if ind else 'サイト'}で検索1ページ目にいる記事の型（引用実績はまだ無いので、順位で選んだ）")
                print("構成を考え直す手間を省くため、この見出しの並びを土台にして、今回の語に合わせて足し引きする。\n")
                for r in rows:
                    print(f"## {r['title']}（{r['pos']:.1f}位・狙う語: {r['keyword']}）")
                    print(f"質問形の見出し {r['q_ratio']:.0%} / 表 {r['tables']} / FAQ {r['faq']}問 / 定義 {r['defbox']}")
                    print("> " + r["lead"][:160])
                    print("\n".join(f"- {h}" for h in r["h2"][:8]) + "\n")
                return 0
        print("（AI検索での引用実績も、同じ業種の上位記事もまだありません。型は渡しません）")
        return 0
    for sid in ([a.site] if a.site else list(S.load_all())):
        p, n = write(sid)
        print(f"   {sid}: 引用実績のある記事 {n}本 → {p.relative_to(ROOT).as_posix()}")
    print("WIN_OK=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
