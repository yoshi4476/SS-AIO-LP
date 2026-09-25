# -*- coding: utf-8 -*-
"""比較表のページ（/compare/<カテゴリ>/）を、記事の表から機械で組む。

**なぜ要るか**: AIが最も引用しやすい構造は比較表。記事には表が7万行あるのに、
横断して見られる場所が無かった。「比較・違い・料金・費用・相場・選び方」を扱う表だけを
カテゴリごとに集め、出典の記事へリンクする。新しい表は作らない。

build.py が呼ぶ:
  pages = compare_pages.collect(site_id, only)  # {category: [{title, h2, table_md, slug}]}（only=公開する slug）
  html  = compare_pages.page_html(cat_name, rows, url_of)
"""
import html as _h
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY = re.compile(r"比較|違い|vs|VS|料金|費用|相場|選び方|向き|メリット|デメリット")
MAX_PER_CAT = 20


def _tables(body):
    """(直前のH2, 表のMarkdown) を順に返す"""
    out, h2, buf = [], "", []
    for ln in body.splitlines() + [""]:
        if ln.startswith("## "):
            h2 = ln[3:].strip()
        if ln.startswith("|"):
            buf.append(ln)
            continue
        if buf:
            if len(buf) >= 4:                       # ヘッダ＋区切り＋2行以上
                out.append((h2, "\n".join(buf)))
            buf = []
    return out


def collect(site_id, only=None):
    """only: 実際に公開する記事の slug の集合（build.py が渡す）。止めた記事の表を出典にしない"""
    import sites as S
    cats = {}
    for p in (ROOT / "articles").glob("*.md"):
        if only is not None and p.stem not in only:
            continue
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.group(1), m.group(2)

        def g(k):
            x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
            return x.group(1).strip().strip('"') if x else ""
        if int(g("score") or 0) < 90 or S.find_category_owner(g("category")) != site_id:
            continue
        for h2, tbl in _tables(body):
            head = tbl.splitlines()[0]
            cols = [c.strip() for c in head.strip("|").split("|")]
            if len(cols) < 3 or not (KEY.search(h2) or KEY.search(head) or KEY.search(g("title"))):
                continue
            cats.setdefault(g("category"), []).append(
                {"title": g("title"), "h2": h2, "table": tbl, "slug": p.stem, "date": g("date"), "cols": len(cols)})
    for k, rows in cats.items():
        rows.sort(key=lambda r: (-r["cols"], r["date"]), reverse=False)
        cats[k] = sorted(rows, key=lambda r: r["date"], reverse=True)[:MAX_PER_CAT]
    return cats


def page_html(cat_name, rows, url_of, base="/compare/"):
    import md2html
    blocks = []
    for r in rows:
        tbl_html, _ = md2html.convert(r["table"])
        blocks.append(f'<div class="latest-block"><div class="cat-head"><h2>{_h.escape(r["h2"] or r["title"][:40])}</h2></div>'
                      f'<div class="table-wrap">{tbl_html}</div>'
                      f'<p class="hub-note">出典: <a href="{url_of(r)}">{_h.escape(r["title"][:60])}</a>（{r["date"]}時点）</p></div>')
    ld = {"@context": "https://schema.org", "@type": "ItemList",
          "name": f"{cat_name}の比較表", "numberOfItems": len(rows),
          "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": r["h2"] or r["title"],
                               "url": url_of(r)} for i, r in enumerate(rows)]}
    return (f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>{_h.escape(cat_name)}の比較表</h2>'
            f'<span class="cnt">{len(rows)}表</span></div>'
            f'<p class="hub-lead">{_h.escape(cat_name)}の記事にある比較表を1か所に集めました。表は各記事のものと同じで、'
            '数字の根拠と前提は出典の記事に書いています。</p></div>' + "\n".join(blocks)
            + '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>")


def index_html(cat_pages, base="/compare/"):
    lis = "".join(f'<li><a href="{base}{slug}/"><strong>{_h.escape(name)}の比較表</strong><span class="cnt">{n}表</span></a></li>'
                  for slug, name, n in cat_pages)
    return ('<div class="latest-block" data-cat="new"><div class="cat-head"><h2>比較表から探す</h2></div>'
            '<p class="hub-lead">「何と何がどう違うか」「いくらかかるか」を、記事の表だけを集めて見比べられる入口です。</p>'
            f'<ul class="hub-list">{lis}</ul></div>')
