# -*- coding: utf-8 -*-
"""用語集（/glossary/）を、記事の定義ブロックから機械で組む。

**なぜ要るか**: 「◯◯とは」は AI Overview の主戦場。定義文は既に各記事の
`<div class="definition-box">` に434個ある（2026-09 実測）のに、1か所に集まって
いなかった。集めて DefinedTerm の構造化データを付ければ、記事を書かずに
「とは」の面が増える。新しい文は作らない。定義は記事のものをそのまま使う。

build.py が呼ぶ:
  terms = glossary.collect(site_id)          # [{term, slug_id, definition, article}]
  glossary.link_terms(content, slug)         # 記事の定義ブロックの用語を用語集へリンク
出力は build.py が BLOG_PAGE で包む（デザインを揃えるため、ここでHTMLの外枠は作らない）。
"""
import hashlib
import html as _h
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOX = re.compile(r'<div class="definition-box">\s*<span class="term">(.*?)</span>(.*?)</div>', re.S)
MIN_DEF = 20


def _plain(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip("、。 ")


def term_id(term):
    return hashlib.md5(term.encode("utf-8")).hexdigest()[:10]


def collect(site_id):
    """公開記事の定義ブロックを集める。同じ用語は新しい記事のものを採る"""
    import sites as S
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
        if int(g("score") or 0) < 90 or S.find_category_owner(g("category")) != site_id:
            continue
        for raw_term, raw_def in BOX.findall(body):
            term = _plain(raw_term)
            term = re.sub(r"(とは|の定義)$", "", term).strip()
            definition = _plain(raw_def)
            if len(term) < 2 or len(term) > 40 or len(definition) < MIN_DEF:
                continue
            rec = {"term": term, "id": term_id(term), "definition": definition[:300],
                   "slug": p.stem, "category": g("category"), "title": g("title"), "date": g("date")}
            if term not in out or out[term]["date"] < rec["date"]:
                out[term] = rec
    return sorted(out.values(), key=lambda r: r["term"])


def term_html(rec, article_url, base="/glossary/"):
    """1用語のページの中身（外枠は build が包む）"""
    ld = {"@context": "https://schema.org", "@type": "DefinedTerm",
          "name": rec["term"], "description": rec["definition"],
          "url": f"{base}{rec['id']}/",
          "inDefinedTermSet": {"@type": "DefinedTermSet", "name": "用語集", "url": base}}
    return (f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>{_h.escape(rec["term"])}とは</h2></div>'
            f'<div class="definition-box"><span class="term">{_h.escape(rec["term"])}とは</span>、{_h.escape(rec["definition"])}</div>'
            f'<p class="hub-note">出典の記事: <a href="{article_url}">{_h.escape(rec["title"][:60])}</a>'
            f'（{rec["date"]}時点の記述）</p>'
            f'<p class="hub-note"><a href="{base}">← 用語集へ</a></p></div>'
            '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>")


def index_html(terms, base="/glossary/"):
    lis = "".join(f'<li><a href="{base}{r["id"]}/"><strong>{_h.escape(r["term"])}</strong></a>'
                  f'<span class="hub-lead">{_h.escape(r["definition"][:60])}…</span></li>' for r in terms)
    ld = {"@context": "https://schema.org", "@type": "DefinedTermSet", "name": "用語集", "url": base,
          "hasDefinedTerm": [{"@type": "DefinedTerm", "name": r["term"], "url": f"{base}{r['id']}/"} for r in terms[:200]]}
    return (f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>用語集</h2>'
            f'<span class="cnt">{len(terms)}語</span></div>'
            '<p class="hub-lead">記事の中で定義した用語を1か所に集めています。定義は各記事に書いたものと同じで、'
            '出典の記事から詳しい使い方へ進めます。</p>'
            f'<ul class="hub-list">{lis}</ul></div>'
            '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>")


def link_terms(content, terms_by_term, base="/glossary/", self_slug=""):
    """記事本文の定義ブロックの用語を用語集へリンクする（内部リンクが機械で増える）"""
    def repl(m):
        term = re.sub(r"(とは|の定義)$", "", _plain(m.group(1))).strip()
        rec = terms_by_term.get(term)
        if not rec or rec["slug"] == self_slug:
            return m.group(0)
        return (f'<div class="definition-box"><span class="term"><a href="{base}{rec["id"]}/">'
                f'{m.group(1)}</a></span>{m.group(2)}</div>')
    return BOX.sub(repl, content)
