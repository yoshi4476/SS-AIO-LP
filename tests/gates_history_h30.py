# -*- coding: utf-8 -*-
"""まとめのページ（比較表・テーマ・エリア・今の時期の特集・多言語の要約・メニュー）が、
自社サイト（self-static）以外のどの方式でも作られて届くこと（2026-10-06）。

運用者の方針: どの納品方式でも、最初の接続が済んだ後は人の手なしで全機能が動く。
監査で、まとめのページは build.py が site/ に作るだけで、別リポジトリ・FTP・ZIP・Next.js・WordPress の社には
1ページも届いていなかった（data/capabilities.json の missing）。中身は aggregate_pages.collect（build.py と
同じモジュールの関数）が組み、方式ごとの書き手は置くだけにした。ここでは偽の配信先（一時フォルダ・偽の WordPress）で、
  - 方式ごとにページ・sitemap・llms.txt・記事の末尾からの案内ができる
  - お客様の社のページに運用会社の名前・著者が出ない（出るページは捨てる）
  - 母数未満（3表未満の比較表・3本未満のテーマ・5本未満のエリア・3本未満の季節）は作らない
  - 先方が自分で作った同じパスのページは上書きしない／作らなくなったページは消す
を確かめる。外部（GitHub・FTP・WordPress・Claude）には触れない。
"""
import io
import json
import shutil
import subprocess
import tempfile
from contextlib import contextmanager, redirect_stdout
from datetime import date
from pathlib import Path

from test_gates import check, ROOT

SITE = "h30-shop"
CATS = {"h30-gourmet": "グルメ"}
BASE_CFG = {"id": SITE, "name": "h30食堂", "domain": "h30.example", "categories": CATS, "url_prefix": "/blog",
            "languages": ["en"], "content_dir": "content/blog", "template": "blog/_template.html",
            "repo": "h30/none", "branch": "main", "theme": "食堂の記事", "images_dir": "images"}
TABLE = "| 種類 | 容量 | 価格 |\n|:--|:--|:--|\n| アルミ | 30L | 1万円 |\n| ステンレス | 30L | 3万円 |\n\n"
FIVE = [f"h30-a{i}" for i in range(5)]


def _with(mod, **kw):
    old = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    return old


def _article(slug, i, table):
    return (f'---\ntitle: "道頓堀の寸胴鍋の選び方{i}"\ndescription: "寸胴鍋の選び方の説明{i}"\ncategory: h30-gourmet\n'
            f'date: 2026-09-0{i + 1}\nkeyword: "寸胴鍋 道頓堀"\nscore: 95\n---\n'
            "寸胴鍋は店の規模で選びます。\n\n## 寸胴鍋の比較\n\n寸胴鍋の違いを表にまとめます。\n\n"
            + (TABLE if table else "") + "## 失敗しない選び方\n\n容量から決めます。\n")


@contextmanager
def fixture(n_tables=3, n_articles=5, season=True, translate=True, credit=True):
    """一時フォルダに記事・季節の山・訳を置き、モジュールの置き場をそこへ向ける"""
    import aggregate_pages as AP
    import compare_pages as CP
    import i18n as I
    import publish as P
    import season as SN
    import sites as S
    import wp_bridge as W
    import menu_page as MP
    holder = {"cfg": dict(BASE_CFG, type="external-html")}
    td = tempfile.TemporaryDirectory()
    root = Path(td.name)
    (root / "articles").mkdir()
    for i in range(n_articles):
        (root / "articles" / f"h30-a{i}.md").write_text(_article(f"h30-a{i}", i, i < n_tables), encoding="utf-8")
    (root / "season").mkdir()
    if season:
        (root / "season" / f"{SITE}.json").write_text(json.dumps(
            {"span": 12, "peaks": {"寸胴鍋": date.today().month}}, ensure_ascii=False), encoding="utf-8")
    (root / "i18n" / "en").mkdir(parents=True)
    if translate:
        (root / "i18n" / "en" / "h30-a0.json").write_text(json.dumps(
            {"title": "How to choose a stock pot 0", "description": "Guide", "lead": "Choose by size.",
             "sections": [{"h2": "Comparison", "answer": "Aluminium is light."}], "faq": [],
             "category": "h30-gourmet", "date": "2026-09-01"}), encoding="utf-8")
    real_all, real_client, real_credit = S.load_all, S.is_client, P.client_credit

    def load_all():
        return {**real_all(), SITE: holder["cfg"]}

    def client_credit(cfg, url=""):
        if cfg.get("id") != SITE:
            return real_credit(cfg, url)
        if not credit:
            return None
        org = {"@type": "Organization", "name": "h30食堂", "url": "https://h30.example/"}
        return {"publisher": org, "author": dict(org), "reviewer": None, "byline": "", "supervisor": None}
    olds = [(W, _with(W, ROOT=root)), (CP, _with(CP, ROOT=root)), (SN, _with(SN, STORE=root / "season")),
            (I, _with(I, OUT=root / "i18n")), (AP, _with(AP, STATE=root / "state")),
            (S, _with(S, load_all=load_all, is_client=lambda sid: sid == SITE or real_client(sid))),
            (P, _with(P, client_credit=client_credit)),
            (MP, _with(MP, DATA=root / "menus", OUT=root / "menuout"))]
    AP._CACHE.clear()
    try:
        yield root, holder
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


def _static_dest(root, name, slugs):
    """external-html・ftp・zip の配信先（雛形・公開済みの記事・sitemap・llms.txt）"""
    d = root / name
    (d / "blog").mkdir(parents=True)
    # 先方の雛形は head に大きな style を持つことがある（補助金サイトは約8KB）。印を先頭だけで探すと自分のページを見失った
    tpl = (ROOT / "templates" / "external_article.html").read_text(encoding="utf-8")
    (d / "blog" / "_template.html").write_text(tpl.replace("<head>", "<head>\n<style>/*" + "x" * 9000 + "*/</style>", 1),
                                               encoding="utf-8")
    for s in slugs:
        (d / "blog" / s).mkdir()
        (d / "blog" / s / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
    (d / "sitemap.xml").write_text('<?xml version="1.0"?>\n<urlset>\n</urlset>\n', encoding="utf-8")
    (d / "llms.txt").write_text("# h30食堂\n", encoding="utf-8")
    return d


def _leaks(text):
    import sites as S
    return [m for m in S.OPERATOR_MARKS if m in text]


def test_collect_builds_every_page_kind_and_keeps_thresholds():
    import aggregate_pages as AP
    print("\n■ まとめのページの共通の口: 種類ごとに作り、母数未満は作らない・運用会社の名前を出さない")
    with fixture() as (root, holder):
        cfg = _cfg(holder, "external-html")
        with redirect_stdout(io.StringIO()):
            pages = AP.collect(cfg)
        by = {p["path"]: p for p in pages}
        check("比較表（3表）・テーマ・エリア（5本）・今の時期の特集・多言語の要約と目次ができる",
              sorted({p["kind"] for p in pages}), ["area", "compare", "i18n", "i18n_index", "season", "topics"])
        check("入口と下のページのパス", [x in by for x in ("/compare/", "/compare/h30-gourmet/", "/topics/", "/area/",
                                                    "/area/dotonbori/", "/season/", "/en/", "/en/blog/h30-a0/")], [True] * 8)
        tp = next(p for p in pages if p["kind"] == "topics" and p["path"] != "/topics/")
        check("まとめのページどうしのリンクはその社の公開URL（相対の /topics/ を残さない）",
              [[p["path"] for p in pages if 'href="/topics/' in p["html"] or 'href="/area/' in p["html"]],
               'href="https://h30.example/topics/"' in tp["html"]], [[], True])
        check("記事へのリンクはその社の記事のURL", 'href="https://h30.example/blog/h30-a1/"' in by["/area/dotonbori/"]["html"], True)
        check("エリアの説明は data/areas.json の AI集客ラボ向けの文（集客・補助金）を使わない",
              "補助金" in by["/area/dotonbori/"]["html"], False)
        check("AI集客ラボにしか無いツール・写真への案内を出さない",
              [s for p in pages for s in ("/tools/", "/images/shelf/") if s in p["html"]], [])
        check("お客様の社のページに運用会社の名前・著者が出ない",
              [p["path"] for p in pages if _leaks(p["html"] + json.dumps(p["jsonld"], ensure_ascii=False))], [])
        check("訳のページの著者・発行元はお客様の社", by["/en/blog/h30-a0/"]["jsonld"][0]["publisher"]["name"], "h30食堂")
        check("訳のページは日本語の記事と hreflang で結ぶ（ja・x-default・en）",
              sorted(by["/en/blog/h30-a0/"]["alternates"]), ["en", "ja", "x-default"])
        check("構造化データは本文から外して持つ（方式ごとに head・メタへ出す）",
              ["<script" in p["html"] for p in pages] == [False] * len(pages) and bool(by["/compare/h30-gourmet/"]["jsonld"]), True)
        tp = next(p for p in pages if p["kind"] == "topics" and p["path"] != "/topics/")
        check("記事の末尾の案内: その記事を含むテーマ・比較表・エリア・季節",
              sorted(t for t, _ in AP.links(pages, "h30-a0")),
              sorted(["グルメの比較表を見る", f"テーマ「{tp['name']}」の記事をまとめて見る",
                      "道頓堀の記事をまとめて見る", "今の時期の特集を見る"]))
    with fixture(credit=False) as (root, holder):
        cfg = _cfg(holder, "external-html")
        out = io.StringIO()
        with redirect_stdout(out):
            pages = AP.collect(cfg)
        check("お客様の著者が分からず運用会社の名前になる訳のページは作らない（要対応で知らせる）",
              ([p["path"] for p in pages if p["kind"] == "i18n"], "要対応" in out.getvalue()), ([], True))
    with fixture(n_tables=2, season=False, translate=False) as (root, holder):
        cfg = _cfg(holder, "external-html")
        with redirect_stdout(io.StringIO()):
            kinds = sorted({p["kind"] for p in AP.collect(cfg)})
        check("2表しか無いカテゴリの比較表・検索データの無い季節は作らない（テーマ・エリアは作る）", kinds, ["area", "topics"])
    with fixture(n_tables=2, n_articles=4) as (root, holder):
        cfg = _cfg(holder, "external-html")
        with redirect_stdout(io.StringIO()):
            kinds = sorted({p["kind"] for p in AP.collect(cfg)})
        check("4本しか無いエリアは作らない（5本から）", "area" in kinds, False)
    with fixture(n_tables=2, n_articles=2, translate=False) as (root, holder):
        cfg = _cfg(holder, "external-html")
        with redirect_stdout(io.StringIO()):
            got = AP.collect(cfg)
        check("2本しか無い社は、テーマ・季節も作らない（3本から）", [p["path"] for p in got], [])


def test_static_methods_get_pages_sitemap_llms_and_cleanup():
    import aggregate_pages as AP
    import deliver_files as DF
    import publish as P
    print("\n■ external-html・ftp・zip: その社の雛形でページを書き、sitemap・llms.txt に載せ、作らなくなったページを消す")
    with fixture() as (root, holder):
        cfg = _cfg(holder, "external-html")
        dest = _static_dest(root, "html", FIVE)
        (dest / "season").mkdir()
        (dest / "season" / "index.html").write_text("<html>先方の季節のページ</html>", encoding="utf-8")
        with redirect_stdout(io.StringIO()) as out:
            written = P.aggregate_for_git(cfg, dest)
        page = (dest / "compare" / "h30-gourmet" / "index.html").read_text(encoding="utf-8")
        check("比較表・テーマ・エリア・多言語の目次と訳のページを書く",
              [(dest / p / "index.html").is_file() for p in ("compare", "compare/h30-gourmet", "topics", "area",
                                                             "area/dotonbori", "en", "en/blog/h30-a0")], [True] * 7)
        check("雛形の置き換えが残らず、canonical はそのページ・記事の構造化データ（BlogPosting）は外す",
              ["{{" in page, '<link rel="canonical" href="https://h30.example/compare/h30-gourmet/">' in page,
               "BlogPosting" in page, '"ItemList"' in page, f'content="{AP.MARK}"' in page], [False, True, False, True, True])
        check("先方が自分で作った同じパスのページ（/season/）は上書きしない",
              ((dest / "season" / "index.html").read_text(encoding="utf-8"), "要対応" in out.getvalue()),
              ("<html>先方の季節のページ</html>", True))
        sm, lt = (dest / "sitemap.xml").read_text(encoding="utf-8"), (dest / "llms.txt").read_text(encoding="utf-8")
        check("sitemap.xml と llms.txt に載せる（書いたものとして返す）",
              ["https://h30.example/topics/" in sm, AP.LLMS_HEAD in lt, dest / "sitemap.xml" in written], [True, True, True])
        check("お客様の社のページに運用会社の名前が出ない",
              [str(f.relative_to(dest)) for f in dest.rglob("*.html") if _leaks(f.read_text(encoding="utf-8"))], [])
        check("記事の末尾から、その記事を含むまとめのページへ案内する",
              'href="https://h30.example/area/dotonbori/"' in P.aggregate_links(cfg, dest, {"slug": "h30-a0"}), True)
        # 公開中の記事が4本に減ると、エリア（5本から）は作らない → 前に置いたページを消し、sitemap からも外す
        shutil.rmtree(dest / "blog" / "h30-a4")
        AP._CACHE.clear()
        with redirect_stdout(io.StringIO()) as out2:
            P.aggregate_for_git(cfg, dest)
        check("2回目の配信で、自分が置いたページを先方のページと取り違えない（head の大きな雛形でも）",
              "/compare/h30-gourmet/ は先方のページ" in out2.getvalue(), False)
        check("作らなくなったページ（管制塔の印のあるもの）を消し、sitemap からも外す",
              [(dest / "area").exists(), "https://h30.example/area/" in (dest / "sitemap.xml").read_text(encoding="utf-8"),
               (dest / "season" / "index.html").is_file()], [False, False, True])

    for kind in ("ftp", "zip"):
        with fixture() as (root, holder):
            cfg = _cfg(holder, kind)
            base = _static_dest(root, "base", FIVE)
            (base / "_template.html").write_text((base / "blog" / "_template.html").read_text(encoding="utf-8"), encoding="utf-8")
            removed = []

            class FakeRemote:
                def __init__(self, c):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    pass

                def rmtree(self, rel):
                    removed.append(rel)
                    return 1
            old = _with(DF, Remote=FakeRemote, credentials=lambda c: {})
            try:
                with redirect_stdout(io.StringIO()):
                    w, keep = P.aggregate_for_files(cfg, base, {"h30-a0"})
                    rels = {rel for _, rel in DF.files_of(w, base, "/blog")}
                    P.aggregate_files_done(cfg, keep)
                    again = P.aggregate_for_files(cfg, base, {"h30-a0"})
                    shutil.rmtree(base / "blog" / "h30-a4")
                    AP._CACHE.clear()
                    w2, keep2 = P.aggregate_for_files(cfg, base, force=True)
                    P.aggregate_files_done(cfg, keep2)
            finally:
                _with(DF, **old)
            check(f"{kind}: 届けるファイルにまとめのページと索引が入る",
                  [r in rels for r in ("compare/h30-gourmet/index.html", "topics/index.html", "area/dotonbori/index.html",
                                       "en/index.html", "sitemap.xml", "llms.txt")], [True] * 6)
            check(f"{kind}: 同じ日の2本目の記事では作り直さない（1日1回まで）", again, ([], None))
            check(f"{kind}: 置いたパスを控え、作らなくなったページは FTP なら消す（ZIP は先方が上げるので消せない）",
                  (sorted(AP.load_state(SITE)["paths"]) == sorted(keep2), sorted(removed)),
                  (True, ["area", "area/dotonbori"] if kind == "ftp" else []))


def test_nextjs_and_markdown_get_pages():
    import aggregate_pages as AP
    import publish as P
    print("\n■ nextjs-json: pages.json と描くページ（雛形）を置く／external-md: permalink つきの Markdown を置く")
    with fixture() as (root, holder):
        cfg = _cfg(holder, "nextjs-json", content_dir="src/content/blog", trailing_slash=False)
        dest = root / "next"
        (dest / "src" / "app" / "season").mkdir(parents=True)
        (dest / "src" / "app" / "season" / "page.tsx").write_text("export default function P(){return null}", encoding="utf-8")
        (dest / "src" / "content" / "blog").mkdir(parents=True)
        for s in FIVE:
            (dest / "src" / "content" / "blog" / f"{s}.json").write_text("{}", encoding="utf-8")
        (dest / "public").mkdir()
        (dest / "public" / "llms.txt").write_text("# h30\n", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            P.aggregate_for_git(cfg, dest)
        app = dest / "src" / "app"
        data = json.loads((dest / "src" / "content" / "aggregate" / "pages.json").read_text(encoding="utf-8"))["pages"]
        comp = (dest / "src" / "components" / "SsAggregatePage.tsx").read_text(encoding="utf-8")
        routes = [app / "compare" / "page.tsx", app / "compare" / "[...slug]" / "page.tsx", app / "topics" / "page.tsx",
                  app / "area" / "[...slug]" / "page.tsx", app / "en" / "page.tsx", app / "en" / "[...slug]" / "page.tsx"]
        check("入口ごとに描くページを置く（印つき・雛形の差し込みが残らない）",
              [f.is_file() and AP.MARK in f.read_text(encoding="utf-8") and "__" not in f.read_text(encoding="utf-8")
               for f in routes], [True] * len(routes))
        check("描くページは部品を相対パスで読み、部品は pages.json を相対パスで読む（@/ の別名に頼らない）",
              ['from "../../components/SsAggregatePage"' in (app / "compare" / "page.tsx").read_text(encoding="utf-8"),
               'from "../content/aggregate/pages.json"' in comp, "__" in comp.replace("__html", "")], [True, True, False])
        check("pages.json に中身（URL は末尾スラッシュ無しの社の決まり・訳は hreflang つき）",
              [data["compare/h30-gourmet"]["url"], "alternates" in data["en/blog/h30-a0"], "season" in data],
              ["https://h30.example/compare/h30-gourmet", True, False])
        check("先方の /season は触らない", (app / "season" / "page.tsx").read_text(encoding="utf-8"),
              "export default function P(){return null}")
        check("llms.txt（public/）に載せる", AP.LLMS_HEAD in (dest / "public" / "llms.txt").read_text(encoding="utf-8"), True)
        (dest / "src" / "content" / "blog" / "h30-a4.json").unlink()
        AP._CACHE.clear()
        with redirect_stdout(io.StringIO()):
            P.aggregate_for_git(cfg, dest)
        check("作らなくなった入口（エリア）の描くページを消す", (app / "area").exists(), False)
        check("Next.js の sitemap（管制塔の雛形）は pages.json を読む（無い回もビルドを落とさない）",
              ["aggregate" in (ROOT / "templates" / "corporate_sitemap.ts").read_text(encoding="utf-8"),
               "existsSync(f)" in (ROOT / "templates" / "corporate_sitemap.ts").read_text(encoding="utf-8")], [True, True])

    with fixture() as (root, holder):
        cfg = _cfg(holder, "external-md")
        dest = root / "md"
        (dest / "content" / "blog").mkdir(parents=True)
        for s in FIVE:
            (dest / "content" / "blog" / f"{s}.md").write_text("x", encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            P.aggregate_for_git(cfg, dest)
        f = dest / "content" / "pages" / "compare" / "h30-gourmet" / "index.md"
        t = f.read_text(encoding="utf-8") if f.is_file() else ""
        check("Markdown（permalink・管制塔の印つき）として置く", ["permalink: /compare/h30-gourmet/" in t, "ss_managed: true" in t,
                                                         "application/ld+json" in t], [True, True, True])


def test_wordpress_gets_fixed_pages_and_menu():
    import aggregate_pages as AP
    import menu_page as MP
    import publish as P
    import wp_bridge as W
    from gates_history_h29 import FakeWP
    print("\n■ wordpress: まとめのページとメニューを固定ページで作る（業種ハブ・用語集と同じ upsert_page）")
    with fixture() as (root, holder):
        cfg = _cfg(holder, "wordpress", domain="wp.example")
        fake = FakeWP()
        for i, s in enumerate(FIVE):
            fake.posts[i + 1] = {"id": i + 1, "slug": s, "status": "publish", "link": f"https://wp.example/2026/09/0{i + 1}/{s}/",
                                 "meta": {}, "content": ""}
        old = (_with(P, _wp_call=fake), _with(W, _has_auth=lambda c: True))
        try:
            with redirect_stdout(io.StringIO()):
                W.sync_aggregate(cfg, W.url_rows(cfg))
            pages = {p["link"].replace("https://wp.example", ""): p for p in fake.pages.values()}
            check("比較表・テーマ・エリア・季節・多言語を固定ページで作る（親子の階層・管制塔の印）",
                  [pages.get(x, {}).get("meta", {}).get("_ss_managed") for x in
                   ("/compare/", "/compare/h30-gourmet/", "/topics/", "/area/dotonbori/", "/season/", "/en/", "/en/h30-a0/")],
                  ["1"] * 7)
            pg = pages["/compare/h30-gourmet/"]
            check("本文に <script> を残さず、構造化データは _ss_jsonld へ（mu-plugin が head に出す）・記事はパーマリンク",
                  ["<script" in pg["content"], json.loads(pg["meta"]["_ss_jsonld"])["@type"],
                   "https://wp.example/2026/09/01/h30-a0/" in pg["content"]], [False, "ItemList", True])
            rows = W.url_rows(cfg)
            check("記事の末尾から、先方に既にあるまとめのページへ案内する",
                  'href="https://wp.example/area/dotonbori/"' in W.aggregate_links(cfg, rows, "h30-a0"), True)
            fake.posts[5]["status"] = "draft"
            AP._CACHE.clear()
            with redirect_stdout(io.StringIO()):
                W.sync_aggregate(cfg, W.url_rows(cfg))
            check("本数が下限を割ったページ（エリア）は下書きに戻す", (pages["/area/"]["status"], pages["/area/dotonbori/"]["status"]),
                  ("draft", "draft"))
            check("記事の公開のついでに作り直す（sync_pages から呼ぶ・1日1回の判定にまとめのページも入る）",
                  ["sync_aggregate(cfg, rows, arts, made)" in (ROOT / "scripts" / "wp_bridge.py").read_text(encoding="utf-8"),
                   "*AP.TOPS" in (ROOT / "scripts" / "wp_bridge.py").read_text(encoding="utf-8")], [True, True])
            # メニュー: 日本語と、訳済みの英語（元のハッシュが同じなので訳し直さない＝Claude を呼ばない）
            import hashlib
            menu = {"site": SITE, "shop": "h30食堂", "items": [{"cat": "麺", "name": "醤油ラーメン", "price": 950, "desc": "", "note": ""}]}
            h = hashlib.md5(json.dumps(menu["items"], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            MP.DATA.mkdir(parents=True)
            (MP.DATA / f"{SITE}.json").write_text(json.dumps(menu, ensure_ascii=False), encoding="utf-8")
            (MP.DATA / f"{SITE}.en.json").write_text(json.dumps(
                {"shop": "h30 Shokudo", "items": [{"cat": "Noodles", "name": "Shoyu Ramen", "price": 950, "desc": "", "note": ""}],
                 "src_hash": h}), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                MP.build(SITE, push=True)
            pages = {p["link"].replace("https://wp.example", ""): p for p in fake.pages.values()}
            en = pages.get("/menu/en/", {})
            check("メニューを /menu/ の下に言語ごとの固定ページで作る（Menu の構造化データはメタへ・価格はそのまま）",
                  [pages.get("/menu/", {}).get("meta", {}).get("_ss_managed"), json.loads(en.get("meta", {}).get("_ss_jsonld") or "{}").get("@type"),
                   "950" in en.get("content", ""), "/menu/ja/" in pages], ["1", "Menu", True, True])
        finally:
            for o, m in zip(old, (P, W)):
                _with(m, **o)


def test_nextjs_menu_goes_to_public():
    import menu_page as MP
    import publish as P
    print("\n■ nextjs-json のメニュー: public/menu/ に置く（静的書き出しでそのまま公開される）")
    with fixture() as (root, holder):
        _cfg(holder, "nextjs-json", content_dir="src/content/blog")
        dest = root / "next"
        dest.mkdir()
        MP.DATA.mkdir(parents=True)
        (MP.DATA / f"{SITE}.json").write_text(json.dumps({"site": SITE, "shop": "h30食堂", "items": [
            {"cat": "", "name": "餃子", "price": 400, "desc": "", "note": ""}]}, ensure_ascii=False), encoding="utf-8")
        holder["cfg"]["languages"] = []
        calls = []
        real_run = subprocess.run
        old = _with(P, ensure_clone=lambda c, t: dest, _push_token=lambda: "")
        old_sp = _with(MP.subprocess, run=lambda *a, **k: calls.append(a[0]) or subprocess.CompletedProcess(a[0], 0, "", ""))
        try:
            with redirect_stdout(io.StringIO()):
                MP.build(SITE, push=True)
        finally:
            _with(P, **old)
            _with(MP.subprocess, **old_sp)
        assert subprocess.run is real_run
        check("public/menu/ja/index.html に置いて push する", [(dest / "public" / "menu" / "ja" / "index.html").is_file(),
                                                             any(c[:2] == ["git", "push"] for c in calls)], [True, True])


def test_capability_cells_for_aggregate_pages():
    print("\n■ 方式×機能の表: まとめのページの6機能に missing が残っていない（作り方が全方式にある）")
    caps = json.loads((ROOT / "data" / "capabilities.json").read_text(encoding="utf-8"))
    feats = ("compare", "topics", "area", "season_feature", "i18n", "menu")
    miss = [f"{f} × {m}" for f in feats for m, c in caps["features"][f]["cells"].items() if c["status"] == "missing"]
    check("比較表・テーマ・エリア・季節・多言語・メニューの missing", miss, [])
    check("入口に共通の口（aggregate_pages.py）が載っている",
          all("scripts/aggregate_pages.py" in caps["features"][f]["entry"] for f in feats[:5]), True)
