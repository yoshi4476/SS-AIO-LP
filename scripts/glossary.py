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


def _explains(keyword, term):
    """その用語を説明する記事（狙う語が「<用語>とは」）か。括弧の中の正式名は外して比べる"""
    short = re.sub(r"（[^）]*）|\([^)]*\)", "", term).strip().lower().replace(" ", "")
    return bool(short) and keyword.lower().replace(" ", "").replace("　", "") == short + "とは"


def collect(site_id, only=None):
    """公開記事の定義ブロックを集める。同じ用語は、その用語を説明する記事（狙う語が「<用語>とは」）のものを採り、
    無ければ新しい記事のものを採る。新しい記事を優先するだけだと、AIO のような中心の用語の定義が記事の増えるたびに
    入れ替わり、トップの図の説明と食い違った（2026-10-11 に「aio 文字数」の記事の定義が「AIOとは」の記事の定義を上書きした）。

    only: 実際に公開する記事の slug の集合（build.py が渡す）。score だけで絞ると、
    観点の足切りや監修待ちで止めた記事まで出典になり、用語集から404へリンクする
    """
    import sites as S
    out, pubs, owner = {}, [], {}
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
        if int(g("score") or 0) < 85 or S.find_category_owner(g("category")) != site_id:
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
            own = _explains(g("keyword"), term)
            cur = out.get(term)
            if cur is None or (own and not owner.get(term)) or (own == owner.get(term, False) and cur["date"] < rec["date"]):
                out[term] = rec
                owner[term] = own
    kw_of = {a["slug"]: a["keyword"] for a in pubs}
    for rec in out.values():
        t = target_of(rec, pubs)
        # same_topic: 「詳しくは」の行き先の記事の狙う語が「用語＋骨組みの語」だけ（旧URLを301で送ってよい）か。
        # 語順だけ違う語（「不動産のLLMO」と「LLMO 不動産」）は target_of が拾わず出典に落ちるので、出典の語でも見る
        rec.update({"target": t["slug"], "target_title": t["title"], "target_category": t["category"],
                    "same_topic": same_topic(rec["term"], kw_of.get(t["slug"], ""))})
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


# 記事の狙う語のうち、主題を狭めない語（どの記事にも付く骨組み）。cannibal_check._FRAME と同じ考え
# 「費用・相場・事例」は読者の目的を変えるので入れない（「AIO対策」の旧URLを相場の記事へ送らない）
FRAME = {"とは", "方法", "やり方", "選び方", "比較", "対策", "ツール", "書き方", "作り方", "増やす", "増やし方", "仕組み",
         "理由", "分析", "変動", "ポイント", "改善", "手順", "違い", "注意点", "おすすめ",
         "始め方", "進め方", "流れ", "効果", "メリット", "デメリット", "確認", "基準", "目安", "見直し", "載る方法"}


def same_topic(term, keyword):
    """記事の狙う語が、用語そのものか「用語＋骨組みの語」だけか。
    「SEO」と「aio seo meo」、「MEO対策」と「飲食店 meo対策」のように、記事のほうが業種や別の手法で主題を狭めて
    いれば False（一般の語の旧URLを業種の記事へ301で送ると、主題の違うページへの転送になる）"""
    names = {_nz(term), _nz(re.sub(r"[（(].*?[）)]", "", term))} - {""}
    toks = [_nz(x) for x in re.split(r"[\s　]+", str(keyword))]
    if not names or not any(toks):
        return False
    for t in filter(None, toks):
        if t in FRAME or any(t in n for n in names):
            continue
        rest = [t.replace(n, "") for n in names if n in t]
        if rest and min(rest, key=len) in FRAME | {""}:
            continue
        # 「計測方法」のように、用語の一部＋骨組みの語でできた語
        if any(t.endswith(f) and t[:-len(f)] and any(t[:-len(f)] in n for n in names) for f in FRAME):
            continue
        return False
    return True


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
    """旧URL（1語1ページ）から、その語を狙う記事（「詳しくは」の行き先）への転送。

    2026-10-03 に1ページへまとめ、旧URLはまとめたページの該当箇所（#id）へ送ったが、Google は旧URLを使い続け、
    まとめた後の7日（10-03〜10-09）で旧URLの表示847回・クリック1、まとめた1ページは表示2回だった。
    旧URLが記事より上に出る語が14語あった（cannibal_check --glossary）。141本の旧URLを1ページへ送ると、
    その評価がまとめたページに集まり、同じ語で記事と食い合う。語ごとに狙う記事へ送り、記事を勝たせる（8.1 の統合と同じ考え）。

    狙う記事が無い語（「AI Overview」の定義が歯科の記事にある、など）と、記事のほうが主題を狭めている語（same_topic）は、
    記事へ送ると主題の違うページへの転送になるので、これまでどおりまとめたページの該当箇所へ送る"""
    out = []
    for r in terms:
        src = "/%s/%s/" % (r["category"], r["slug"])
        to = target_url(r, src) if r.get("same_topic") else f"{base}#{r['id']}"
        out.append(f"{base}{r['id']}/  {to}  301")
    return out


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
