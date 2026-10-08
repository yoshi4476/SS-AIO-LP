# -*- coding: utf-8 -*-
"""まとめのページ（比較表・テーマ・エリア・今の時期の特集・多言語の要約）を、自社サイト（self-static）
以外の方式の社にも作るための共通の口。

**なぜ要るか**: AI集客ラボは build.py が site/ に作るが、別リポジトリ・FTP・ZIP・Next.js・WordPress の社には
1ページも届いていなかった（data/capabilities.json の missing）。方式ごとに描き方を持つと中身が食い違うので、
中身は build.py と同じモジュールの関数（compare_pages・topics・area_hub・season・industry_hub・glossary・i18n）が組み、ここは

    pages = collect(cfg, live=公開済みの slug, url_of=記事のURL)
      → [{"kind", "path", "title", "description", "html", "jsonld", "lang", "members", "alternates"}]

を返すだけにする。置き方は方式ごとの書き手が受け持つ:
    external-html・ftp・zip → publish.write_aggregate_html（その社の雛形で HTML を作る）
    nextjs-json            → publish.write_aggregate_nextjs（pages.json と、それを描くページの雛形）
    external-md            → publish.write_aggregate_md（permalink つきの Markdown）
    wordpress              → wp_bridge.sync_pages（固定ページ。業種ハブ・用語集と同じ upsert_page）

守ること（各モジュールの決まりのまま）: 比較表は3表未満のカテゴリを作らない・テーマは3本未満を作らない・
エリアは5本未満を作らない・季節は12か月分の検索データがそろうまで作らない・業種ハブは5本未満の業種を作らない
（業種が1つで記事の8割以上を占める社は、ブログの一覧と同じ中身になるので作らない）・用語集は10語未満なら作らない。
業種ハブの説明文は data/industries.json の lead（AI集客ラボの集客向けの文）を使わない。数字は記事と検索データにあるものだけ。
WordPress の業種ハブ・用語集は wp_bridge.sync_pages が作る（wp_bridge._aggregate はここの業種・用語集を頼まない）。
sites/<id>.json の aggregate_skip に書いた種類は作らない（補助金サイトの業種ハブは subsidy/pages.py が作る）。
お客様の社のページに運用会社の名前・著者が出たらそのページを捨てる（sites.operator_leaks）。
先方が自分で作った同じパスのページは上書きも削除もしない（管制塔が作ったものには MARK を付ける）。

  python scripts/aggregate_pages.py --site <id>      # その社で何ページできるかを見る（何も書かない）
"""
import argparse
import html as _h
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
KINDS = ("compare", "topics", "area", "season", "industry", "glossary", "i18n", "i18n_index")
TOPS = ("compare", "topics", "area", "season")
# 業種ハブ・用語集。WordPress は wp_bridge.sync_pages が別に作るので、WordPress の入口の一覧（TOPS）には入れない
HUBS = ("industry", "glossary")
LANGS = ("en", "zh", "ko")
LANG_ATTR = {"ja": "ja", "en": "en", "zh": "zh-Hans", "ko": "ko"}
I18N_NAMES = {"en": "Articles in English", "zh": "中文文章", "ko": "한국어 기사"}
MARK = "ss-aggregate"
STATE = ROOT / "data" / "aggregate"
LLMS_HEAD = "## まとめのページ"
_LINK = re.compile(r'<a href="(/(?:compare|topics|area|season|industry|glossary|en|zh|ko)/[^"#?]*)"([^>]*)>(.*?)</a>', re.S)
# 用語集の中の記事へのリンク（AI集客ラボの組み方 /<カテゴリ>/<slug>/）
_ART = re.compile(r'href="/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)/(#[^"]*)?"')


def site_articles(cfg):
    """その社の記事で、公開の基準を満たすもの [(meta, body, path)]"""
    import wp_bridge
    return wp_bridge._site_articles(cfg)


def page_url(cfg, path):
    """まとめのページの公開URL（末尾スラッシュは記事と同じ決まり）"""
    url = f"https://{cfg['domain']}{path}"
    return url if cfg.get("trailing_slash", True) or path == "/" else url.rstrip("/")


def _page(kind, path, title, desc, html, lang="ja", members=(), **extra):
    import wp_bridge
    body, lds = wp_bridge._split_ld(html)
    return {"kind": kind, "path": path, "title": title, "description": desc, "html": body, "jsonld": lds,
            "lang": lang, "members": list(members), **extra}


def collect(cfg, live=None, url_of=None, kinds=KINDS, i18n_prefix=None, arts=None, today=None):
    """その社のまとめのページの一覧。live: 公開済みの記事の slug（None ならその社の公開基準を満たす全記事）。
    url_of(meta): 記事の公開URL（既定は sites.article_url。WordPress はパーマリンクを渡す）"""
    import sites as S
    arts = site_articles(cfg) if arts is None else arts
    # slug はフロントマターの値、無ければ原稿のファイル名（build.py と同じ）
    arts = [(dict(m, slug=m.get("slug") or (Path(rest[0]).stem if rest else "")), b) for m, b, *rest in arts]
    if live is not None:
        arts = [a for a in arts if a[0]["slug"] in live]
    # 検索から外した記事（noindex）は、どの配信方式でもまとめのページに入れない
    import noindex
    arts = [a for a in arts if not noindex.on(a[0]) and not noindex.is_hidden(a[0]["slug"])]
    metas = [{"title": str(m.get("title") or ""), "slug": m["slug"], "keyword": str(m.get("keyword") or ""),
              "category": m.get("category", ""), "date": str(m.get("date") or ""), "body": b,
              "faq": m.get("faq") if isinstance(m.get("faq"), list) else []} for m, b in arts]
    by_slug = {m["slug"]: m for m in metas}
    url_of = url_of or (lambda m: S.article_url(cfg, m))
    cats_cfg = cfg.get("categories") or {}
    skip = set(cfg.get("aggregate_skip") or ())
    kinds = [k for k in kinds if k not in skip]
    out = []
    if not metas:
        return out

    def art_links(html):
        """/<カテゴリ>/<slug>/ の記事へのリンクを、その社の記事のURLへ（知らない記事のリンクは文字に戻さず残す）"""
        def repl(m):
            a = by_slug.get(m.group(2))
            if not a or a["category"] != m.group(1):
                return m.group(0)
            return f'href="{_h.escape(url_of(a))}{m.group(3) or ""}"'
        return _ART.sub(repl, html)

    if "compare" in kinds:
        import compare_pages as CP
        made = []
        for cat, rows in CP.collect(cfg["id"], set(by_slug)).items():
            if len(rows) < 3 or cat not in cats_cfg:
                continue
            name = cats_cfg[cat]
            out.append(_page("compare", f"/compare/{cat}/", f"{name}の比較表",
                             f"{name}の記事にある比較表{len(rows)}表を1か所に集めました。表は記事のものと同じです。",
                             CP.page_html(name, rows, lambda r: url_of(by_slug[r["slug"]])),
                             members={r["slug"] for r in rows}))
            made.append((cat, name, len(rows)))
        if made:
            out.append(_page("compare", "/compare/", "比較表から探す",
                             "記事の比較表をカテゴリごとに集め、違いと費用を見比べられる入口です。",
                             CP.index_html(made, extras=False)))

    if "topics" in kinds:
        import topics as TP
        groups = TP.build(cfg["id"], metas)
        for g in groups:
            out.append(_page("topics", f"/topics/{g['slug']}/", f"{g['name']}の記事",
                             f"テーマ「{g['name']}」の記事{len(g['members'])}本。まず読む1本は「{g['pillar']['title']}」です。",
                             TP.page_html(g, url_of, extras=False), members=[m["slug"] for m in g["members"]], name=g["name"]))
        if groups:
            out.append(_page("topics", "/topics/", "テーマから探す",
                             "同じ主題の記事を束ね、まず読む1本と掘り下げる記事に分けたテーマの一覧です。", TP.index_html(groups)))

    if "area" in kinds:
        import area_hub as AH
        pairs, g = AH.live(metas)
        for a, ms in pairs:
            # data/areas.json の lead は AI集客ラボの記事向け（集客・補助金）。ほかのサイトでは事実と違うので使わない
            a2 = dict(a, lead=f"題名か狙う語に「{a['name']}」を含む記事をまとめています。")
            out.append(_page("area", f"/area/{a['slug']}/", f"{a['name']}の記事", f"{a['name']}に関する記事{len(ms)}本をまとめています。",
                             AH.page_html(a2, ms, url_of), members=[m["slug"] for m in ms], name=a["name"]))
        if pairs:
            out.append(_page("area", "/area/", "エリアから探す", "エリアごとに記事をまとめています。", AH.index_html(pairs, g)))

    if "season" in kinds:
        import season as SN
        groups = SN.feature(cfg["id"], metas, today)
        if groups:
            flat = [m["slug"] for gr in groups for m in gr["members"]]
            out.append(_page("season", "/season/", "今の時期の特集",
                             f"毎年この時期に検索が増えるテーマ{len(groups)}つの記事{len(flat)}本をまとめています。",
                             SN.page_html(groups, url_of), members=flat))

    if "industry" in kinds:
        import industry_hub as IH
        inds, mn = IH.load()
        g = IH.group(metas, inds)
        pairs = [(i, g[i["slug"]]) for i in inds if len(g.get(i["slug"], [])) >= mn]
        # 1業種の社（歯科医院の自社サイトなど）は、業種ハブがブログの一覧の写しになる（中身の薄い重複ページ）
        if len(pairs) == 1 and len(pairs[0][1]) >= 0.8 * len(metas):
            pairs = []
        cats = {c: (n, "") for c, n in cats_cfg.items()}
        made = []
        for ind, ms in pairs:
            # data/industries.json の lead は AI集客ラボの集客の記事向け。ほかのサイトでは事実と違うので使わない
            ind2 = dict(ind, lead=f"{ind['name']}に関する記事{len(ms)}本を、カテゴリごとにまとめています。")
            path = f"/industry/{ind['slug']}/"
            body = IH.hub_body(ind2, ms, cats, lambda m: f'<li><a href="{_h.escape(url_of(m))}">{_h.escape(m["title"])}</a></li>',
                               cat_url=lambda c: "", extras=False)
            ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": f"{ind['name']}の記事",
                  "url": page_url(cfg, path), "mainEntity": {"@type": "ItemList", "itemListElement": [
                      {"@type": "ListItem", "position": i, "url": url_of(m), "name": m["title"]}
                      for i, m in enumerate(ms, 1)]}}
            out.append(_page("industry", path, f"{ind['name']}の記事", ind2["lead"],
                             body + '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>",
                             members=[m["slug"] for m in ms], name=ind["name"]))
            fq = IH.faq_body(ind2, ms, url_of)
            if fq:
                fhtml, fld = fq
                out.append(_page("industry", path + "faq/", f"{ind['name']}のよくある質問",
                                 f"{ind['name']}の記事{len(ms)}本から、よくある質問{len(fld['mainEntity'])}問と答えをまとめています。",
                                 fhtml + '<script type="application/ld+json">' + json.dumps(fld, ensure_ascii=False) + "</script>"))
            made.append((ind, ms, bool(fq)))
        if made:
            lis = "".join(f'<li><a href="/industry/{i["slug"]}/"><strong>{_h.escape(i["name"])}</strong>'
                          f'<span class="cnt">{len(ms)}本</span></a>'
                          + (f' <a href="/industry/{i["slug"]}/faq/">よくある質問</a>' if fq else "") + "</li>"
                          for i, ms, fq in made)
            out.append(_page("industry", "/industry/", "業種から探す", "業種ごとに、カテゴリをまたいで記事をまとめています。",
                             f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>業種から探す</h2>'
                             f'<span class="cnt">{len(made)}業種</span></div><ul class="hub-list">{lis}</ul></div>'))

    if "glossary" in kinds:
        import glossary as GL
        terms = GL.collect(cfg["id"], set(by_slug))
        if len(terms) >= 10:
            # 構造化データの URL は canonical と同じ形に（末尾スラッシュ無しの社は /glossary）
            base = page_url(cfg, "/glossary/")[len(f"https://{cfg['domain']}"):]
            body = GL.index_html(terms, base=base, site_url=f"https://{cfg['domain']}", rel_all=GL.related_all(terms))
            out.append(_page("glossary", "/glossary/", "用語集",
                             f"記事で定義した用語{len(terms)}語の意味を、1ページにまとめた用語集です。",
                             art_links(body)))

    if {"i18n", "i18n_index"} & set(kinds):
        import i18n as I
        pre = ((cfg.get("url_prefix") or "/blog") if i18n_prefix is None else i18n_prefix).strip("/")
        langs = I.langs_for(cfg["id"])
        tr = I.translated() if langs else {}
        docs_by = {lg: {s: d for s, d in tr.get(lg, {}).items()
                        if s in by_slug and d.get("category") == by_slug[s]["category"]} for lg in langs}
        path_of = lambda lg, s: "/" + "/".join(x for x in (lg, pre, s) if x) + "/"
        for lg, docs in docs_by.items():
            if not docs:
                continue
            if "i18n" in kinds:
                for s, d in docs.items():
                    ja = url_of(by_slug[s])
                    alts = {"ja": ja, "x-default": ja,
                            **{LANG_ATTR[o]: page_url(cfg, path_of(o, s)) for o in docs_by if s in docs_by[o]}}
                    out.append(_page("i18n", path_of(lg, s), d["title"], d.get("description", ""),
                                     I.page_html(d, ja, lg), lang=lg, alternates=alts))
            if "i18n_index" in kinds:
                lis = "".join(f'<li><a href="{path_of(lg, s)}"><strong>{_h.escape(d["title"])}</strong>'
                              f'<span class="cnt">{str(d.get("date", ""))[:7]}</span></a></li>'
                              for s, d in sorted(docs.items(), key=lambda kv: str(kv[1].get("date", "")), reverse=True))
                out.append(_page("i18n_index", f"/{lg}/", I18N_NAMES[lg], I18N_NAMES[lg],
                                 f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>{I18N_NAMES[lg]}</h2>'
                                 f'<span class="cnt">{len(docs)}</span></div><ul class="hub-list">{lis}</ul></div>', lang=lg))

    # まとめのページどうしのリンクを、その社の公開URLへ。作らなかったページへのリンクは文字に戻す（404へ送らない）
    paths = {p["path"] for p in out}

    def fix(m):
        return (f'<a href="{page_url(cfg, m.group(1))}"{m.group(2)}>{m.group(3)}</a>' if m.group(1) in paths
                else m.group(3))
    kept = []
    client = S.is_client(cfg["id"])
    for p in out:
        p["html"] = drop_title_heading(_LINK.sub(fix, p["html"]), p["title"])
        p["url"] = page_url(cfg, p["path"])
        leak = S.operator_leaks(p["html"] + json.dumps(p["jsonld"], ensure_ascii=False), cfg) if client else []
        if leak:
            print(f"要対応: {cfg['id']} の {p['path']} に運用会社の名前があるため作りません（{' / '.join(leak[:3])}）")
            continue
        kept.append(p)
    return kept


def drop_title_heading(html, title):
    """本文の最初の見出しがページの題と同じなら外す。題は置く側（雛形の h1・WordPress の固定ページの題）が出す。
    外さないと「テーマから探す」の h1 の直後に同じ文の h2 が続いていた（補助金・コーポレートの全まとめのページ。2026-10-08）"""
    m = re.search(r"<h([1-6])[^>]*>(.*?)</h\1>", html, re.S)
    if m and m.group(1) == "2" and _h.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip() == title.strip():
        return html[:m.start()] + html[m.end():]
    return html


# まとめのページの一覧・見出し・手順の見た目（AI集客ラボの hub-list・cat-head・enrich-steps・gl-toc と同じ形）。
# 配信先の CSS はこの部品を持たず、黒丸と下線だけの箇条書きになり、件数や日付が題にくっついていた（「…対象外2026-10」）。
# ページに同梱する。文字色・リンク色は配信先のものを使い、線と地の色だけ持つ（どの配色の社でも浮かない）
CSS = (
    ".ss-aggregate .latest-block{margin:0 0 2.6rem}"
    ".ss-aggregate .cat-head{display:flex;align-items:baseline;gap:.9rem;flex-wrap:wrap;padding-bottom:.7rem;"
    "margin:0 0 1.4rem;border-bottom:2px solid rgba(127,127,127,.22)}"
    ".ss-aggregate .cat-head h2{margin:0;padding-left:.8rem;border-left:4px solid currentColor;font-size:1.3rem;line-height:1.4}"
    ".ss-aggregate .cnt{font-size:.8rem;font-weight:400;opacity:.7}"
    ".ss-aggregate .hub-lead{margin:.4rem 0 0;font-size:.92rem;line-height:1.85;opacity:.85}"
    ".ss-aggregate .hub-list{list-style:none;margin:1.2rem 0 0;padding:0;display:grid;"
    "grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr));gap:.9rem}"
    ".ss-aggregate .hub-list li{list-style:none;margin:0;padding:1rem 1.1rem;border:1px solid rgba(127,127,127,.25);"
    "border-radius:14px;background:#fff}"
    ".ss-aggregate .hub-list li>a{display:flex;align-items:baseline;gap:.6em;text-decoration:none;font-weight:700;line-height:1.6}"
    ".ss-aggregate .hub-list li>a strong{font-size:1.05rem}"
    ".ss-aggregate .hub-list li>a .cnt{margin-left:auto;white-space:nowrap}"
    ".ss-aggregate .hub-list li>.cnt,.ss-aggregate .hub-list .hub-lead{display:block;margin:.4rem 0 0;font-size:.84rem}"
    ".ss-aggregate .hub-note{margin:1rem 0 0;font-size:.84rem;opacity:.8}"
    ".ss-aggregate .enrich-steps{list-style:none;counter-reset:s;display:grid;"
    "grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:1rem;margin:1.2rem 0 0;padding:0}"
    ".ss-aggregate .enrich-steps li{counter-increment:s;list-style:none;margin:0;padding:1.2rem;"
    "border:1px solid rgba(127,127,127,.25);border-radius:16px;background:#fff}"
    ".ss-aggregate .enrich-steps li::before{content:\"STEP \" counter(s);display:block;margin-bottom:.4rem;"
    "font-size:.72rem;font-weight:800;letter-spacing:.14em;opacity:.7}"
    ".ss-aggregate .enrich-steps b{display:block;margin-bottom:.35rem}"
    ".ss-aggregate .enrich-steps span{font-size:.88rem;line-height:1.85;opacity:.85}"
    ".ss-aggregate .gl-toc{display:flex;flex-wrap:wrap;gap:.35rem .5rem;margin:1.2rem 0 1.6rem;padding:1rem;"
    "border-radius:14px;background:rgba(127,127,127,.07)}"
    ".ss-aggregate .gl-toc a{padding:.25em .7em;border:1px solid rgba(127,127,127,.25);border-radius:999px;"
    "background:#fff;font-size:.82rem;text-decoration:none}"
    ".ss-aggregate .gl-term{padding:1.4rem 0;border-top:1px solid rgba(127,127,127,.25);scroll-margin-top:96px}"
    ".ss-aggregate .gl-term h3{margin:0 0 .7rem}"
    ".ss-aggregate .gl-rel,.ss-aggregate .gl-more{margin:.4rem 0 0;font-size:.84rem;opacity:.85}"
    ".ss-aggregate .definition-box{margin:.6rem 0;padding:.8rem 1rem;border-left:4px solid rgba(127,127,127,.5);"
    "background:rgba(127,127,127,.08)}"
    ".ss-aggregate .definition-box .term{font-weight:700}"
    ".ss-aggregate .table-wrap{overflow-x:auto;margin:.8rem 0}"
    ".ss-aggregate table{border-collapse:collapse;width:100%;font-size:.92rem}"
    ".ss-aggregate th,.ss-aggregate td{border:1px solid rgba(127,127,127,.35);padding:.5rem .7rem;text-align:left;"
    "vertical-align:top}"
    ".ss-aggregate details{margin:.6rem 0;padding:.7rem 1rem;border:1px solid rgba(127,127,127,.35);border-radius:10px}"
    ".ss-aggregate summary{font-weight:700;cursor:pointer}"
)


_CACHE = {}


def cached(cfg, live, kinds=KINDS):
    """同じ社・同じ公開済みの並びなら1回だけ組む（描き直しで記事ごとに呼んでも全記事を読み直さない）"""
    key = (cfg["id"], frozenset(live), tuple(kinds), cfg.get("domain"))
    if key not in _CACHE:
        _CACHE[key] = collect(cfg, live=live, kinds=kinds)
    return _CACHE[key]


# ---------- 記事の末尾からの導線 ----------

def links(pages, slug, url_for=None):
    """その記事を含むまとめのページへの案内 [(文言, URL)]。url_for(path) が None のページは出さない"""
    out = []
    for p in pages:
        if slug not in p.get("members", ()):
            continue
        u = url_for(p["path"]) if url_for else p.get("url")
        if not u:
            continue
        label = {"compare": f"{p['title']}を見る", "topics": f"テーマ「{p.get('name', '')}」の記事をまとめて見る",
                 "area": f"{p.get('name', '')}の記事をまとめて見る", "season": "今の時期の特集を見る",
                 "industry": f"{p.get('name', '')}の記事をまとめて見る"}.get(p["kind"])
        if label:
            out.append((label, u))
    return out


def links_html(pages, slug, url_for=None):
    got = links(pages, slug, url_for)
    if not got:
        return ""
    return ('\n<p class="ss-aggregate-links">' + " ／ ".join(
        f'<a href="{_h.escape(u)}" data-cta="article_aggregate">{_h.escape(t)}</a>' for t, u in got) + "</p>\n")


# ---------- 静的な配信先（HTML・Markdown）の共通の手当て ----------

def html_doc(tpl, cfg, page):
    """その社の記事の雛形から、まとめのページの HTML を作る。<main> の中身を差し替え、
    題・説明・canonical・OGP をそのページのものにし、記事用の構造化データ（BlogPosting など）は外す"""
    E = _h.escape
    url = page["url"]
    vals = {"TITLE": E(page["title"]), "TITLE_SHORT": E(page["title"][:28]), "DESCRIPTION": E(page["description"]),
            "SITE_NAME": E(cfg.get("name", cfg["domain"])), "ORIGIN": f"https://{cfg['domain']}",
            "PREFIX": (cfg.get("url_prefix") or "/blog").rstrip("/")}
    t = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: vals.get(m.group(1), ""), tpl)
    t = re.sub(r'<script type="application/ld\+json">.*?</script>\s*', "", t, flags=re.S)
    t = re.sub(r'(<link rel="canonical" href=")[^"]*(")', lambda m: m.group(1) + url + m.group(2), t)
    for prop, val in (("og:url", url), ("og:title", E(page["title"])), ("og:description", E(page["description"])),
                      ("og:type", "website")):
        t = re.sub(rf'(<meta property="{prop}" content=")[^"]*(")', lambda m, v=val: m.group(1) + v + m.group(2), t)
    t = re.sub(r'<html lang="[^"]*"', f'<html lang="{LANG_ATTR.get(page["lang"], "ja")}"', t, count=1)
    # 記事の雛形の <main> は本文と脇の段組み（grid）のことがある。まとめのページは脇を持たないので全幅に置く
    body = (f'<div class="{MARK}" style="grid-column:1/-1;min-width:0">\n<h1>{E(page["title"])}</h1>\n'
            f'{page["html"]}\n</div>')
    alts = "".join(f'<link rel="alternate" hreflang="{k}" href="{E(v)}">\n' for k, v in (page.get("alternates") or {}).items())
    head = (f'<meta name="generator" content="{MARK}">\n{alts}<style>{CSS}</style>\n'
            + "".join('<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
                      + "</script>\n" for ld in page["jsonld"]))
    if re.search(r"<main\b[^>]*>.*?</main>", t, re.S):
        t = re.sub(r"(<main\b[^>]*>).*?(</main>)", lambda m: m.group(1) + "\n" + body + "\n" + m.group(2), t, count=1, flags=re.S)
    elif "</header>" in t and "<footer" in t:
        a, b = t.index("</header>") + len("</header>"), t.index("<footer")
        t = t[:a] + f'\n<main>\n{body}\n</main>\n' + t[b:]
    else:
        t = (f'<!DOCTYPE html>\n<html lang="{LANG_ATTR.get(page["lang"], "ja")}">\n<head>\n<meta charset="UTF-8">\n'
             '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
             f'<title>{E(page["title"])}｜{vals["SITE_NAME"]}</title>\n<meta name="description" content="{E(page["description"])}">\n'
             f'<link rel="canonical" href="{url}">\n</head>\n<body><main>\n{body}\n</main></body>\n</html>\n')
    t = t.replace("</head>", head + "</head>", 1)
    try:
        import search_preview
        t = search_preview.robots_tag(t)
    except Exception:
        pass
    return t


def ensure_public_dirs(dest: Path, names):
    """配信物を作る道具（tools/make_dist.py の PUBLIC_DIRS）が、置いたフォルダを配信対象に入れていなければ足す。
    入れないと置いたページが公開されない（補助金サイトの /seido/ が404だった）"""
    md = dest / "tools" / "make_dist.py"
    if not md.is_file():
        return False
    t = md.read_text(encoding="utf-8")
    m = re.search(r"PUBLIC_DIRS\s*=\s*\[([^\]]*)\]", t)
    if not m:
        return False
    add = [n for n in dict.fromkeys(names) if f'"{n}"' not in m.group(1)]
    if add:
        md.write_text(t[:m.end(1)] + "".join(f', "{n}"' for n in add) + t[m.end(1):], encoding="utf-8", newline="\n")
    return bool(add)


def _public_file(dest: Path, name):
    for rel in (name, f"public/{name}", f"static/{name}", f"site/{name}"):
        if (dest / rel).is_file():
            return dest / rel
    return None


def update_indexes(dest: Path, cfg, pages, gone=()):
    """配信先の sitemap.xml と llms.txt に、まとめのページを載せる（消したページは外す）。書き換えたファイルを返す"""
    touched = []
    urls = [p["url"] for p in pages]
    gone_urls = {page_url(cfg, g) for g in gone}
    sm = _public_file(dest, "sitemap.xml")
    if sm:
        t = sm.read_text(encoding="utf-8")
        new = t
        for u in gone_urls:
            new = re.sub(r"\s*<url>\s*<loc>" + re.escape(u) + r"</loc>.*?</url>", "", new, flags=re.S)
        add = "".join(f"  <url>\n    <loc>{u}</loc>\n    <lastmod>{date.today().isoformat()}</lastmod>\n  </url>\n"
                      for u in urls if f"<loc>{u}</loc>" not in new)
        if add and "</urlset>" in new:
            new = new.replace("</urlset>", add + "</urlset>", 1)
        if new != t:
            sm.write_text(new, encoding="utf-8", newline="\n")
            touched.append(sm)
    lt = _public_file(dest, "llms.txt")
    if lt:
        t = lt.read_text(encoding="utf-8")
        block = (LLMS_HEAD + "\n" + "".join(f"- [{p['title']}]({p['url']}): {p['description']}\n" for p in pages)) if pages else ""
        if LLMS_HEAD in t:
            new = re.sub(re.escape(LLMS_HEAD) + r"\n(?:- [^\n]*\n?)*", lambda m: block, t, count=1)
        else:
            new = t.rstrip("\n") + ("\n\n" + block if block else "\n")
        if new != t:
            lt.write_text(new, encoding="utf-8", newline="\n")
            touched.append(lt)
    return touched


def is_ours(f: Path):
    """管制塔が置いたまとめのページか（head の generator の印）。先方の雛形は head に大きな style を持つことがあるので全体を見る"""
    try:
        return f.is_file() and f'<meta name="generator" content="{MARK}">' in f.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def sweep_html(dest: Path, keep):
    """前に管制塔が置いたまとめのページ（印のあるもの）のうち、今回作らなかったものを消す。消したパスを返す。
    消すのはそのページの index.html だけ（同じフォルダの先方のファイル・下のページは残す）"""
    gone = []
    for top in TOPS + HUBS + LANGS:
        base = dest / top
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("index.html"), key=lambda p: -len(p.parts)):
            path = "/" + f.parent.relative_to(dest).as_posix() + "/"
            if path in keep or not is_ours(f):
                continue
            f.unlink()
            gone.append(path)
            d = f.parent
            while d != dest and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                d = d.parent
    return gone


def load_state(site_id):
    p = STATE / f"{site_id}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except ValueError:
        return {}


def save_state(site_id, paths):
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / f"{site_id}.json").write_text(json.dumps({"at": date.today().isoformat(), "paths": sorted(paths)},
                                                      ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    a = ap.parse_args()
    for sid, cfg in S.load_all().items():
        if (a.site and sid != a.site) or cfg.get("type") == "self-static":
            continue
        pages = collect(cfg) if cfg.get("type") != "wordpress" else []
        print(f"■ {sid}（{cfg['type']}）: {len(pages)}ページ")
        for p in pages:
            print(f"   {p['path']:<40} {p['title'][:30]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
