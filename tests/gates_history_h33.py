# -*- coding: utf-8 -*-
"""業種ハブ・用語集・訳のページとの hreflang・WordPress の表示速度が、どの納品方式でも人の手なしで届くこと（2026-10-06）。

data/capabilities.json の最後の missing だった3つ:
  - 業種ハブ（/industry/）と用語集（/glossary/）は build.py が site/ に作るだけで、external-md・nextjs-json・ftp の社には
    1ページも届いていなかった（external-html も補助金サイトだけ）。まとめのページの共通の口 aggregate_pages.collect に足し、
    方式ごとの書き手（HTML・Next.js・Markdown・FTP）に乗せた。WordPress は wp_bridge.sync_pages が前から作る（二重に作らない）
  - 訳のページはあっても、日本語の記事の head から訳へ向ける hreflang の口が Next.js・Markdown・WordPress に無かった
  - WordPress はテーマの PHP を触らない方針で、表示速度を直す手段が無かった（mu-plugin のフィルターで出来る分を足した）
偽の配信先（一時フォルダ・偽の WordPress の行）で確かめる。外部（GitHub・FTP・WordPress・Claude）には触れない。
"""
import io
import json
import re
import tempfile
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

from test_gates import check, ROOT

SITE = "h33-shop"
CATS = {"h33-dental": "歯科", "h33-food": "飲食"}
BASE_CFG = {"id": SITE, "name": "h33商会", "domain": "h33.example", "categories": CATS, "url_prefix": "/blog",
            "languages": ["en"], "content_dir": "content/blog", "template": "blog/_template.html",
            "repo": "h33/none", "branch": "main", "theme": "店の記事", "images_dir": "images"}


def _with(mod, **kw):
    old = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    return old


def _article(slug, i, kind):
    """kind: d（歯科医院）/ f（飲食店）。記事ごとに FAQ 1問と用語の定義1つ"""
    title, cat, term = (("歯科医院の予約の取り方", "h33-dental", "予約枠") if kind == "d"
                        else ("飲食店の仕込みの段取り", "h33-food", "仕込み表"))
    return (f'---\ntitle: "{title}{i}"\nslug: {slug}\ndescription: "説明{i}"\ncategory: {cat}\ndate: 2026-09-0{i + 1}\n'
            f'keyword: "{title}{i}"\nscore: 95\nfaq:\n  - q: "{title}{i}の質問は？"\n    a: "{title}{i}の答えです。"\n---\n'
            f"{title}は順に進めます。\n\n## 進め方\n\n"
            f'<div class="definition-box"><span class="term">{term}{kind.upper()}{i}とは</span>、'
            f"{term}{kind.upper()}{i}は記事の中で決めた言葉で、二十文字を超える長さの説明をここに書きます。</div>\n\n"
            "## 失敗しない段取り\n\n急がないことです。\n")


@contextmanager
def fixture(n_dental=5, n_food=5, translate=True):
    import aggregate_pages as AP
    import compare_pages as CP
    import glossary as GL
    import i18n as I
    import publish as P
    import season as SN
    import sites as S
    import wp_bridge as W
    holder = {"cfg": dict(BASE_CFG, type="external-html")}
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    (root / "articles").mkdir()
    slugs = [f"h33-d{i}" for i in range(n_dental)] + [f"h33-f{i}" for i in range(n_food)]
    for s in slugs:
        (root / "articles" / f"{s}.md").write_text(_article(s, int(s[5:]), s[4]), encoding="utf-8")
    (root / "season").mkdir()
    (root / "i18n" / "en").mkdir(parents=True)
    if translate and n_dental:
        (root / "i18n" / "en" / "h33-d0.json").write_text(json.dumps(
            {"title": "How to book a dentist 0", "description": "Guide", "lead": "Book early.",
             "sections": [{"h2": "Steps", "answer": "Call first."}], "faq": [],
             "category": "h33-dental", "date": "2026-09-01"}), encoding="utf-8")
    real_all, real_client, real_credit = S.load_all, S.is_client, P.client_credit

    def load_all():
        return {**real_all(), SITE: holder["cfg"]}

    def client_credit(cfg, url=""):
        if cfg.get("id") != SITE:
            return real_credit(cfg, url)
        org = {"@type": "Organization", "name": "h33商会", "url": "https://h33.example/"}
        return {"publisher": org, "author": dict(org), "reviewer": None, "byline": "", "supervisor": None}
    olds = [(W, _with(W, ROOT=root)), (CP, _with(CP, ROOT=root)), (GL, _with(GL, ROOT=root)),
            (SN, _with(SN, STORE=root / "season")), (I, _with(I, OUT=root / "i18n")), (AP, _with(AP, STATE=root / "state")),
            (S, _with(S, load_all=load_all, is_client=lambda sid: sid == SITE or real_client(sid))),
            (P, _with(P, client_credit=client_credit))]
    AP._CACHE.clear()
    try:
        yield root, holder, slugs
    finally:
        for mod, old in reversed(olds):
            _with(mod, **old)
        AP._CACHE.clear()
        td.cleanup()


def _cfg(holder, type_, **kw):
    import aggregate_pages as AP
    holder["cfg"] = dict(BASE_CFG, type=type_, **kw)
    AP._CACHE.clear()
    return holder["cfg"]


def _quiet(fn, *a, **kw):
    out = io.StringIO()
    with redirect_stdout(out):
        got = fn(*a, **kw)
    return got, out.getvalue()


def test_industry_hub_and_glossary_come_from_the_common_collector():
    import aggregate_pages as AP
    import sites as S
    print("\n■ 業種ハブ・用語集: まとめのページの共通の口が組む（母数の決まり・運用会社の名前を出さない・その社のURL）")
    with fixture() as (root, holder, slugs):
        cfg = _cfg(holder, "external-html")
        pages, _ = _quiet(AP.collect, cfg)
        by = {p["path"]: p for p in pages}
        check("業種ハブ（入口・業種・よくある質問）と用語集ができる",
              [x in by for x in ("/industry/", "/industry/shika/", "/industry/shika/faq/", "/industry/inshokuten/",
                                 "/industry/inshokuten/faq/", "/glossary/")], [True] * 6)
        hub = by["/industry/shika/"]
        check("業種ハブの説明は data/industries.json の AI集客ラボ向けの文（検索とAI検索で…）を使わない",
              ["検索とAI検索" in hub["html"], "歯科医院に関する記事5本" in hub["html"]], [False, True])
        check("業種ハブの記事へのリンクはその社の記事のURL・よくある質問へのリンクはその社の公開URL",
              ['href="https://h33.example/blog/h33-d0/"' in hub["html"],
               'href="https://h33.example/industry/shika/faq/"' in hub["html"]], [True, True])
        check("AI集客ラボにしか無い LP・調査・ツール・写真への案内を出さない",
              [s for p in pages for s in ("/lp/", "/research/", "/tools/", "/images/scenes/") if s in p["html"]], [])
        check("よくある質問は FAQPage・業種ハブは記事の一覧（構造化データは本文から外して持つ）",
              [by["/industry/shika/faq/"]["jsonld"][0]["@type"], hub["jsonld"][0]["@type"], "<script" in hub["html"]],
              ["FAQPage", "CollectionPage", False])
        gl = by["/glossary/"]
        check("用語集: 10語・記事へのリンクはその社のURL（/<カテゴリ>/<slug>/ を残さない）・DefinedTermSet",
              [len(gl["jsonld"][0]["hasDefinedTerm"]), bool(re.search(r'href="/h33-', gl["html"])),
               'href="https://h33.example/blog/h33-f1/"' in gl["html"], gl["jsonld"][0]["@type"]],
              [10, False, True, "DefinedTermSet"])
        check("お客様の社のページに運用会社の名前・著者が出ない",
              [p["path"] for p in pages if [m for m in S.OPERATOR_MARKS if m in p["html"] + json.dumps(p["jsonld"], ensure_ascii=False)]], [])
        check("記事の末尾の案内に、その記事の業種ハブが入る",
              "歯科医院の記事をまとめて見る" in [t for t, _ in AP.links(pages, "h33-d1")], True)
        cfg = _cfg(holder, "external-html", aggregate_skip=["industry"])
        pages, _ = _quiet(AP.collect, cfg)
        check("sites/<id>.json の aggregate_skip に書いた種類は作らない（補助金サイトの業種ハブは subsidy/pages.py）",
              sorted({p["kind"] for p in pages} & {"industry", "glossary"}), ["glossary"])
    with fixture(n_dental=4, n_food=5) as (root, holder, slugs):
        cfg = _cfg(holder, "external-html")
        pages, _ = _quiet(AP.collect, cfg)
        check("4本しか無い業種（歯科）は作らない・9語の用語集は作らない",
              ["/industry/shika/" in {p["path"] for p in pages}, "glossary" in {p["kind"] for p in pages}], [False, False])
    with fixture(n_dental=6, n_food=0) as (root, holder, slugs):
        cfg = _cfg(holder, "external-html")
        pages, _ = _quiet(AP.collect, cfg)
        check("1業種で記事のほとんどを占める社（歯科医院の自社サイト）は、ブログの一覧の写しになる業種ハブを作らない",
              "industry" in {p["kind"] for p in pages}, False)
    import publish as P
    import wp_bridge as W
    with fixture() as (root, holder, slugs):
        cfg = _cfg(holder, "wordpress")
        rows = [{"slug": s, "url": f"https://h33.example/2026/10/06/{s}/", "type": "post"} for s in slugs]
        got, _ = _quiet(W._aggregate, cfg, rows)
        check("WordPress は業種ハブ・用語集を sync_pages が親子の固定ページで作るので、まとめのページからは作らない（二重にしない）",
              sorted({p["kind"] for p in got} & set(AP.HUBS)), [])
        old = _with(P, _wp_call=lambda *a, **k: [])          # カテゴリのリンクを聞きに行かない（外へ出ない）
        try:
            hubs = W.hub_pages(cfg, W._site_articles(cfg), rows)[0]
        finally:
            _with(P, **old)
        check("WordPress の業種ハブ（sync_pages）も AI集客ラボ向けの説明文を使わない",
              [len(hubs), "検索とAI検索" in "".join(b for _, _, b, _, _ in hubs)], [2, False])


def test_every_static_method_gets_industry_and_glossary_pages():
    import aggregate_pages as AP
    import publish as P
    print("\n■ 業種ハブ・用語集を、external-html・ftp（同じ書き手）・nextjs-json・external-md に置く")
    tpl = (ROOT / "templates" / "external_article.html").read_text(encoding="utf-8")
    with fixture() as (root, holder, slugs):
        cfg = _cfg(holder, "external-html")
        dest = root / "html"
        (dest / "blog").mkdir(parents=True)
        (dest / "blog" / "_template.html").write_text(tpl, encoding="utf-8")
        for s in slugs:
            (dest / "blog" / s).mkdir()
            (dest / "blog" / s / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
        (dest / "sitemap.xml").write_text('<?xml version="1.0"?>\n<urlset>\n</urlset>\n', encoding="utf-8")
        (dest / "industry" / "inshokuten").mkdir(parents=True)
        (dest / "industry" / "inshokuten" / "index.html").write_text("<html>先方の飲食店のページ</html>", encoding="utf-8")
        _, out = _quiet(P.aggregate_for_git, cfg, dest)
        f = dest / "industry" / "shika" / "faq" / "index.html"
        check("業種ハブ・よくある質問・用語集を雛形で置き（印つき）、sitemap に載せる",
              [AP.is_ours(f), AP.is_ours(dest / "industry" / "index.html"), AP.is_ours(dest / "glossary" / "index.html"),
               "https://h33.example/glossary/" in (dest / "sitemap.xml").read_text(encoding="utf-8")], [True] * 4)
        check("先方の同じパスのページ（/industry/inshokuten/）は上書きせず、要対応で知らせる",
              [(dest / "industry" / "inshokuten" / "index.html").read_text(encoding="utf-8"), "要対応" in out],
              ["<html>先方の飲食店のページ</html>", True])
        for s in slugs[1:]:
            (dest / "blog" / s / "index.html").unlink()
        AP._CACHE.clear()
        _quiet(P.aggregate_for_git, cfg, dest)
        check("母数を割ったら、管制塔が置いた業種ハブ・用語集を消す（先方のページは残す）",
              [(dest / "industry" / "shika").exists(), (dest / "glossary").exists(),
               (dest / "industry" / "inshokuten" / "index.html").is_file()], [False, False, True])

    with fixture() as (root, holder, slugs):
        cfg = _cfg(holder, "nextjs-json", content_dir="src/content/blog", trailing_slash=False)
        dest = root / "next"
        (dest / "src" / "app").mkdir(parents=True)
        (dest / "src" / "content" / "blog").mkdir(parents=True)
        for s in slugs:
            (dest / "src" / "content" / "blog" / f"{s}.json").write_text("{}", encoding="utf-8")
        _quiet(P.aggregate_for_git, cfg, dest)
        app = dest / "src" / "app"
        data = json.loads((dest / "src" / "content" / "aggregate" / "pages.json").read_text(encoding="utf-8"))["pages"]
        check("Next.js: pages.json に業種ハブ（下の階層の faq も）・用語集、描くページは入口と [...slug]",
              [k in data for k in ("industry", "industry/shika", "industry/shika/faq", "glossary")]
              + [(app / "industry" / "page.tsx").is_file(), (app / "industry" / "[...slug]" / "page.tsx").is_file(),
                 (app / "glossary" / "page.tsx").is_file(), (app / "glossary" / "[...slug]").exists()],
              [True] * 7 + [False])
        check("Next.js: 用語集の構造化データの URL は canonical と同じ形（末尾スラッシュ無しの社は /glossary）",
              [data["glossary"]["url"], data["glossary"]["jsonld"][0]["url"]],
              ["https://h33.example/glossary", "https://h33.example/glossary"])
        comp = (ROOT / "templates" / "nextjs_aggregate_page.tsx").read_text(encoding="utf-8")
        check("Next.js の描く部品が用語の枠・目次の見た目を持つ（サイトの CSS はリセットされている）",
              [".definition-box" in comp, ".gl-toc" in comp], [True, True])

    with fixture() as (root, holder, slugs):
        cfg = _cfg(holder, "external-md")
        dest = root / "md"
        (dest / "content" / "blog").mkdir(parents=True)
        for s in slugs:
            (dest / "content" / "blog" / f"{s}.md").write_text("x", encoding="utf-8")
        _quiet(P.aggregate_for_git, cfg, dest)
        t = (dest / "content" / "pages" / "industry" / "shika" / "faq" / "index.md").read_text(encoding="utf-8")
        check("Markdown: 業種のよくある質問・用語集を permalink つき（管制塔の印）で置く",
              ["permalink: /industry/shika/faq/" in t, "ss_managed: true" in t,
               (dest / "content" / "pages" / "glossary" / "index.md").is_file()], [True, True, True])


def test_japanese_articles_point_to_translations_by_hreflang():
    import publish as P
    print("\n■ 多言語: 日本語の記事から訳のページへの hreflang（Next.js は JSON と部品・Markdown はフロントマター・WordPress は投稿メタ）")
    body = "歯科医院の予約は早めに取ります。\n\n## 進め方\n\n電話で取ります。\n"
    meta = {"slug": "h33-d0", "title": "歯科医院の予約の取り方0", "description": "説明0", "category": "h33-dental",
            "date": "2026-09-01", "keyword": "歯科医院の予約の取り方0", "score": 95}
    with fixture() as (root, holder, slugs):
        cfg = _cfg(holder, "nextjs-json", content_dir="src/content/blog", url_prefix="/blog")
        dest = root / "next"
        (dest / "src" / "app" / "blog" / "[slug]").mkdir(parents=True)
        page = dest / "src" / "app" / "blog" / "[slug]" / "page.tsx"
        page.write_text("export default function P(){return null}", encoding="utf-8")
        (dest / "src" / "content" / "blog").mkdir(parents=True)
        for s in slugs:
            (dest / "src" / "content" / "blog" / f"{s}.json").write_text("{}", encoding="utf-8")
        (dest / "public").mkdir()
        _, out = _quiet(P.write_nextjs_json, cfg, dest, meta, body)
        j = json.loads((dest / "src" / "content" / "blog" / "h33-d0.json").read_text(encoding="utf-8"))
        part = dest / "src" / "lib" / "ssAlternates.ts"
        check("Next.js: 記事の JSON に alternates（ja・x-default・en）を載せ、部品 lib/ssAlternates.ts を置く",
              [sorted(j.get("alternates") or {}), (j.get("alternates") or {}).get("en"), part.is_file()],
              [["en", "ja", "x-default"], "https://h33.example/en/blog/h33-d0/", True])
        check("Next.js: 記事ページが部品を使っていなければ要対応で知らせる", "ssAlternates(post, canonical)" in out, True)
        page.write_text("import { ssAlternates } from '@/lib/ssAlternates';\n"
                        "export async function generateMetadata(){ return { alternates: ssAlternates(post, url) }; }",
                        encoding="utf-8")
        _, out = _quiet(P.write_nextjs_json, cfg, dest, dict(meta), body)
        check("Next.js: 使っていれば知らせない", "ssAlternates(post, canonical)" in out, False)
        meta2 = dict(meta, slug="h33-d1", title="歯科医院の予約の取り方1")
        _quiet(P.write_nextjs_json, cfg, dest, meta2, body)
        check("Next.js: 訳の無い記事には alternates を載せない",
              "alternates" in json.loads((dest / "src" / "content" / "blog" / "h33-d1.json").read_text(encoding="utf-8")), False)
        ts = (ROOT / "templates" / "nextjs_alternates.ts").read_text(encoding="utf-8")
        check("部品: 管制塔の印・訳が無ければ languages を付けない（自分だけを指す hreflang を出さない）",
              ["ss-aggregate" in ts.splitlines()[0], 'k !== "ja" && k !== "x-default"' in ts], [True, True])

    with fixture() as (root, holder, slugs):
        cfg = _cfg(holder, "external-md")
        dest = root / "md"
        (dest / "content" / "blog").mkdir(parents=True)
        for s in slugs:
            (dest / "content" / "blog" / f"{s}.md").write_text("x", encoding="utf-8")
        src = root / "articles" / "h33-d0.md"
        _quiet(P.write_external_md, cfg, dest, dict(meta), body, src)
        t = (dest / "content" / "blog" / "h33-d0.md").read_text(encoding="utf-8")
        check("Markdown: 日本語の記事のフロントマターに alternates（訳のページと同じ形）",
              ["alternates:" in t, "en: https://h33.example/en/blog/h33-d0/" in t], [True, True])

    with fixture() as (root, holder, slugs):
        cfg = _cfg(holder, "wordpress")
        rows = [{"slug": s, "url": f"https://h33.example/2026/10/06/{s}/", "type": "post"} for s in slugs]
        got, _ = _quiet(P.wp_alternates, cfg, rows, meta, rows[0]["url"])
        check("WordPress: 投稿メタ _ss_alternates に入れる組（訳のページは固定ページ /en/<slug>/）",
              got, {"ja": rows[0]["url"], "x-default": rows[0]["url"], "en": "https://h33.example/en/h33-d0/"})
        got, _ = _quiet(P.wp_alternates, dict(cfg, languages=[]), rows, meta, rows[0]["url"])
        check("WordPress: 多言語の指示が無い社は空", got, {})
        import wp_bridge as W
        from gates_history_h29 import FakeWP
        fake = FakeWP(domain="h33.example")
        old = _with(P, _wp_call=fake)
        try:
            _quiet(W.sync_aggregate, cfg, rows)
        finally:
            _with(P, **old)
        en = next((p for p in fake.pages.values() if p["slug"] == "h33-d0"), {})
        alts = json.loads((en.get("meta") or {}).get("_ss_alternates") or "{}")
        check("WordPress: 訳のページ（固定ページ）にも同じ組を入れる（mu-plugin が双方の head に出す）・他のページには入れない",
              [alts.get("ja"), alts.get("en"),
               [p["slug"] for p in fake.pages.values() if p["slug"] != "h33-d0" and "_ss_alternates" in p["meta"]]],
              [rows[0]["url"], "https://h33.example/en/h33-d0/", []])
        src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
        check("write_wordpress が _ss_alternates を送る", '"_ss_alternates": json.dumps(alts' in src, True)


def test_wordpress_plugin_prints_hreflang_and_speeds_up():
    import wp_bridge as W
    print("\n■ WordPress の mu-plugin（2.0.2）: 訳のページへの hreflang と、テーマに触れずに出来る表示速度の直し")
    php = (ROOT / "automation" / "wordpress" / "ss-quality-gate.php").read_text(encoding="utf-8")
    # 版は上がっていく（2.0.3 で画像・動画のサイトマップと配信の指紋を足した）。2.0.2 以降で、見出しと定数がそろうこと
    ver = W.plugin_version(php)
    head_ver = (re.search(r"^ \* Version: (\d+\.\d+\.\d+)$", php, re.M) or [None, None])[1]
    check("版は 2.0.2 以降（見出しの Version と SSB_VERSION がそろう）",
          [tuple(map(int, ver.split("."))) >= (2, 0, 2), head_ver == ver], [True, True])
    alt = php.split("function ssb_alternates($id)", 1)[1].split("\n}\n", 1)[0]
    check("hreflang: 投稿メタ _ss_alternates を REST で書けるように登録する",
          "SSB_META_ALTERNATES => 'string'" in php, True)
    check("hreflang: 同じサイト（home_url のホスト）の http(s) の URL・言語の名前の形の鍵だけ・訳のページが公開済みのものだけ",
          ["wp_parse_url(home_url('/'), PHP_URL_HOST)" in alt, "['http', 'https']" in alt,
           "preg_match('/^(x-default|[a-z]{2,3}(-[A-Za-z0-9]{2,8})*)$/', $lang)" in alt,
           "url_to_postid($url)" in alt and "get_post_status($pid) !== 'publish'" in alt], [True] * 4)
    check("hreflang: 記事は自分（ja・x-default）をパーマリンクから・訳が無ければ出さない／訳のページは2言語そろうときだけ",
          ["get_permalink($id)" in alt, "return $out ? array_merge(['ja' => $self, 'x-default' => $self], $out) : [];" in alt,
           "count(array_diff(array_keys($out), ['x-default'])) >= 2" in alt], [True, True, True])
    head = php.split("add_action('wp_head', function () {", 1)[1].split("\n});\n", 1)[0]
    check("hreflang: 記事と訳のページ（固定ページ）の両方の head に、esc_attr・esc_url で出す（片側だけだと Google は使わない）",
          ["printf('<link rel=\"alternate\" hreflang=\"%s\" href=\"%s\">' . \"\\n\", esc_attr($lang), esc_url($url));" in head,
           head.index("foreach (ssb_alternates($id)") > head.rindex("if (is_singular('post')) {"),
           "'page' => [SSQG_META_JSONLD => 'string', SSB_META_MANAGED => 'string', SSB_META_ALTERNATES => 'string']" in php],
          [True, True, True])
    sp = php.split("function ssb_speed_on()", 1)[1]
    check("速度: 本文の画像に loading=lazy（既にあれば触らない）・アイキャッチに fetchpriority=high（1枚だけ）",
          ["add_filter('the_content'" in sp, "(?![^>]*\\sloading=)" in sp,
           "$attr['fetchpriority'] = 'high';" in sp, "static $done = false;" in sp], [True] * 4)
    check("速度: gtag.js は load の1.2秒後に読む（前後のインラインの設定は残す）・日本語の Web フォントの CSS を読まない",
          ["add_filter('script_loader_tag'" in sp, "},1200);});</script>" in sp, "preg_replace_callback(" in sp,
           "add_filter('style_loader_tag'" in sp, "Noto\\+Sans\\+JP" in sp], [True] * 5)
    check("速度: 管理画面・REST・フィードでは動かさず、wp-config で止められる（SSB_SPEED・SSB_KEEP_WEBFONTS）",
          ["!is_admin()" in sp, "REST_REQUEST" in sp, "define('SSB_SPEED', true);" in php,
           "defined('SSB_KEEP_WEBFONTS')" in sp], [True] * 4)


def test_capability_cells_for_hubs_hreflang_and_wp_speed():
    print("\n■ 方式×機能の表: 業種ハブ・用語集・多言語・WordPress の表示速度に missing が無い")
    caps = json.loads((ROOT / "data" / "capabilities.json").read_text(encoding="utf-8"))
    F = caps["features"]
    check("業種ハブ・用語集・多言語の missing", [f"{f} × {m}" for f in ("industry_hub", "glossary", "i18n", "speed_fix")
                                     for m, c in F[f]["cells"].items() if c["status"] == "missing"], [])
    check("業種ハブ・用語集の入口に共通の口（aggregate_pages.py）",
          ["scripts/aggregate_pages.py" in F[f]["entry"] for f in ("industry_hub", "glossary")], [True, True])
    check("多言語の hreflang: Next.js と WordPress は ok（口がある）", [F["i18n"]["cells"][m]["status"] for m in ("nextjs-json", "wordpress")],
          ["ok", "ok"])
