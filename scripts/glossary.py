# -*- coding: utf-8 -*-
"""用語集（/glossary/）を、記事の定義ブロックから機械で組む。

**なぜ要るか**: 「◯◯とは」は AI Overview の主戦場。定義文は既に各記事の
`<div class="definition-box">` に434個ある（2026-09 実測）のに、1か所に集まって
いなかった。集めて DefinedTerm の構造化データを付ければ、記事を書かずに
「とは」の面が増える。新しい文は作らない。定義は記事のものをそのまま使う。

build.py が呼ぶ:
  terms = glossary.collect(site_id, only)    # [{term, slug_id, definition, article}]（only=公開する slug）
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
    # マーカー記法（==…== / **…**）を残すと、説明文や meta description にそのまま出る
    s = re.sub(r"==(.+?)==|\*\*(.+?)\*\*", lambda m: m.group(1) or m.group(2), s)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip("、。 ")


def term_id(term):
    return hashlib.md5(term.encode("utf-8")).hexdigest()[:10]


def collect(site_id, only=None):
    """公開記事の定義ブロックを集める。同じ用語は新しい記事のものを採る。

    only: 実際に公開する記事の slug の集合（build.py が渡す）。score だけで絞ると、
    観点の足切りや監修待ちで止めた記事まで出典になり、用語集から404へリンクする
    """
    import sites as S
    out, pubs = {}, []
    for p in sorted((ROOT / "articles").glob("*.md")):   # 名前順（ランナーごとにファイルの並びが違い、同じ日付の並びが毎回変わった）
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
        import noindex
        if noindex.hidden_fm(fm):           # 検索から外した記事（noindex）を用語集の出典にしない
            continue
        pubs.append({"slug": p.stem, "keyword": g("keyword"), "title": g("title"),
                     "category": g("category"), "date": g("date")})
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
    for rec in out.values():
        t = target_of(rec, pubs)
        rec.update({"target": t["slug"], "target_title": t["title"], "target_category": t["category"]})
    return sorted(out.values(), key=lambda r: r["term"])


def _nz(s):
    return re.sub(r"[\s　・･/／（）()「」【】|｜:：、。の]", "", str(s).lower())


def target_of(rec, pubs):
    """その用語を狙う記事（狙う語が用語と一致・包含する公開記事）。無ければ定義の出典の記事。

    用語集のページが記事より上に出る語が13語あった（週次の要対応・2026-10-05）。用語集から
    詳しい記事へ送るリンクは、定義を書いた記事ではなく、その語を狙っている記事に向ける"""
    names = {_nz(rec["term"]), _nz(re.sub(r"[（(].*?[）)]", "", rec["term"]))} - {""}
    best, rank = None, 0
    for a in pubs:
        k = _nz(a["keyword"])
        if not k:
            continue
        r = 3 if k in names else (2 if any(len(n) >= 3 and (n in k or k in n) for n in names) else 0)
        # 同じ点なら、定義を書いた記事 → 狙う語が短い（用語に近い）記事の順
        if r and (r > rank or (r == rank and (a["slug"] == rec["slug"] or
                                               (best["slug"] != rec["slug"] and len(k) < len(_nz(best["keyword"])))))):
            best, rank = a, r
    return best or rec


def target_url(rec, article_url):
    """その語を狙う記事のURL。定義の出典と同じ記事なら article_url（サイトごとの組み方をそのまま使う）"""
    if not rec.get("target") or rec["target"] == rec["slug"]:
        return article_url
    return f'/{rec.get("target_category") or rec["category"]}/{rec["target"]}/'


def more_html(rec, article_url, t_url):
    """定義の直下に置く「詳しくは」の行。用語集に着いた読者（旧URL /glossary/<id>/ から転送された人も）を記事へ送る"""
    t_title = rec.get("target_title") or rec["title"]
    line = (f'<p class="gl-more">詳しくは <a href="{t_url}">「{_h.escape(t_title[:60])}」</a>'
            f'で解説しています。</p>')
    if t_url == article_url:
        return line + f'<p class="hub-note">定義の出典はこの記事です（{rec["date"]}時点の記述）。</p>'
    return line + (f'<p class="hub-note">定義の出典の記事: <a href="{article_url}">{_h.escape(rec["title"][:60])}</a>'
                   f'（{rec["date"]}時点の記述）</p>')


def related(rec, terms, k=4):
    """同じカテゴリの用語から、語の重なりが大きい順に k 個。重なりが無ければ並びの近いものを足す。

    用語集の各ページは一覧からしかリンクされず、被リンク1本のページが149あった（Ahrefs 2026-09-29）"""
    grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)} or {s}
    g0 = grams(rec["term"].lower())
    same = [r for r in terms if r["category"] == rec["category"] and r["id"] != rec["id"]]
    scored = sorted(same, key=lambda r: -len(g0 & grams(r["term"].lower())))
    out = [r for r in scored if g0 & grams(r["term"].lower())][:k]
    if len(out) < k:
        # 同じカテゴリに語が少ないと、互いに指し合うだけで被リンクが増えない。他のカテゴリからも語の近いものを足す
        other = sorted((r for r in terms if r["id"] != rec["id"] and r not in out and r["category"] != rec["category"]),
                       key=lambda r: -len(g0 & grams(r["term"].lower())))
        out += [r for r in other if g0 & grams(r["term"].lower())][:k - len(out)]
    if len(out) < k:
        order = [r["id"] for r in terms]
        i = order.index(rec["id"]) if rec["id"] in order else 0
        near = sorted(same, key=lambda r: abs(order.index(r["id"]) - i))
        out += [r for r in near if r not in out][:k - len(out)]
    return out


def related_all(terms, k=4):
    """全用語の関連を一度に決め、どの語もほかの語の関連に最低1回は入るようにする。
    語が重ならない用語は誰の関連にも選ばれず、一覧からの1本だけが残った（19語）"""
    rel = {r["id"]: related(r, terms, k) for r in terms}
    pointed = {x["id"] for lst in rel.values() for x in lst}
    by_id = {r["id"]: r for r in terms}
    order = [r["id"] for r in terms]
    for tid in order:
        if tid in pointed:
            continue
        # 並びで隣の語（同じカテゴリを優先）の関連に足す
        i = order.index(tid)
        near = sorted((o for o in order if o != tid),
                      key=lambda o: (by_id[o]["category"] != by_id[tid]["category"], abs(order.index(o) - i)))
        if near:
            rel[near[0]] = rel[near[0]] + [by_id[tid]]
            pointed.add(tid)
    return rel


def term_html(rec, article_url, base="/glossary/", rel=()):
    """1用語のページの中身（外枠は build が包む）"""
    rel_html = ("<h3>関連する用語</h3><ul class=\"hub-list\">" + "".join(
        f'<li><a href="{base}{r["id"]}/"><strong>{_h.escape(r["term"])}</strong></a>'
        f'<span class="hub-lead">{_h.escape(r["definition"][:50])}…</span></li>' for r in rel) + "</ul>") if rel else ""
    ld = {"@context": "https://schema.org", "@type": "DefinedTerm",
          "name": rec["term"], "description": rec["definition"],
          "url": f"{base}{rec['id']}/",
          "inDefinedTermSet": {"@type": "DefinedTermSet", "name": "用語集", "url": base}}
    return (f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>{_h.escape(rec["term"])}とは</h2></div>'
            f'<div class="definition-box"><span class="term">{_h.escape(rec["term"])}とは</span>、{_h.escape(rec["definition"])}</div>'
            + more_html(rec, article_url, target_url(rec, article_url)) + rel_html +
            f'<p class="hub-note"><a href="{base}">← 用語集へ</a></p></div>'
            '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>")


def index_html(terms, base="/glossary/", site_url="", rel_all=None):
    """用語集の1ページ（全語の定義を見出しつきで並べる）。
    1語1ページだと定義の数行だけのページが142本になり、90日でクリック0・1ページあたりの表示は記事の約12分の1だった。
    各語は見出しに目印（id）を付け、旧URL（/glossary/<id>/）は _redirects でここの該当箇所へ送る"""
    rel_all = rel_all or {}
    toc = "".join(f'<a href="#{r["id"]}">{_h.escape(r["term"])}</a>' for r in terms)
    secs = []
    for r in terms:
        rel = rel_all.get(r["id"], ())
        rel_html = ('<p class="gl-rel">関連する用語: ' + "、".join(
            f'<a href="#{x["id"]}">{_h.escape(x["term"])}</a>' for x in rel) + '</p>') if rel else ""
        secs.append(f'<section class="gl-term" id="{r["id"]}"><h3>{_h.escape(r["term"])}とは</h3>'
                    f'<div class="definition-box"><span class="term">{_h.escape(r["term"])}とは</span>、{_h.escape(r["definition"])}</div>'
                    + more_html(r, f'/{r["category"]}/{r["slug"]}/', target_url(r, f'/{r["category"]}/{r["slug"]}/'))
                    + f'{rel_html}</section>')
    ld = {"@context": "https://schema.org", "@type": "DefinedTermSet", "name": "用語集", "url": f"{site_url}{base}",
          "hasDefinedTerm": [{"@type": "DefinedTerm", "name": r["term"], "description": r["definition"],
                              "url": f"{site_url}{base}#{r['id']}"} for r in terms]}
    return (f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>用語集</h2>'
            f'<span class="cnt">{len(terms)}語</span></div>'
            '<p class="hub-lead">記事の中で定義した用語を1か所に集めています。定義は各記事に書いたものと同じで、'
            '各語の「詳しくは」から、その語を詳しく扱う記事へ進めます。</p>'
            f'<nav class="gl-toc" aria-label="用語の目次">{toc}</nav>{"".join(secs)}</div>'
            '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>")


def redirects(terms, base="/glossary/"):
    """旧URL（1語1ページ）から、まとめたページの該当箇所への転送"""
    return [f"{base}{r['id']}/  {base}#{r['id']}  301" for r in terms]


def link_terms(content, terms_by_term, base="/glossary/", self_slug=""):
    """記事本文の定義ブロックの用語を用語集の該当箇所へリンクする（内部リンクが機械で増える）"""
    def repl(m):
        term = re.sub(r"(とは|の定義)$", "", _plain(m.group(1))).strip()
        rec = terms_by_term.get(term)
        if not rec or rec["slug"] == self_slug:
            return m.group(0)
        return (f'<div class="definition-box"><span class="term"><a href="{base}#{rec["id"]}">'
                f'{m.group(1)}</a></span>{m.group(2)}</div>')
    return BOX.sub(repl, content)
