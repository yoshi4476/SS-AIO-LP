# -*- coding: utf-8 -*-
"""2026-10-08 運用者の決定「担当領域の外の記事は検索から外す（URL は消さない）」から。

調査（GSC 2026-09-08〜10-05・28日、page 次元）: コーポレートの表示の約4割（4,097回のうち 1,576回）が
銀行の通帳・ゆうちょの記帳の5本で、問い合わせは0（GA4 の入口ページ別の lead_capture/generate_lead・90日も0）。
AI集客ラボの整骨院の保険・クリニックの建築や M&A、補助金の補助金でない電子申請も同じ形で出ていた。

決めたこと: URL は残し（404 にしない）、noindex にして、自社の導線（sitemap・llms.txt・一覧・関連・
まとめのページ・内部リンク）から外す。4つの描き方（AI集客ラボ build.py・コーポレート nextjs-json・
補助金 external-html・お客様の社 external-md）で同じに効かせる。週次の自動の直しが外した記事に手を入れたり、
リンクを戻したりしない。リンクは記法だけ外して文は残す（auto_review.guard の検算を通る）。
AI集客ラボは周辺のテーマ（SNS・チラシ・看板・イベント）を kw_off で止める。
"""
import inspect
import re
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

# 運用者が検索から外すと決めた記事（調査の一覧。slug は articles/ と GSC の page で確かめた）
HIDE = {
    "corporate": ["yucho-kicho-yarikata", "tsucho-kicho-yarikata", "atm-kicho-yarikata", "tsucho-kicho-dekinai-genin",
                  "ginko-kicho-yarikata", "keiri-kanji-chigai", "freee-keihi-seisan-yarikata",
                  "rakurakuseisan-keihi-seisan-yarikata", "smbc-keiri-jidouka", "keiri-koritsuka-hon"],
    "ai-lab": ["seikotsuin-hiyou-hoken", "seikotsuin-hiyou-iryouhikojo", "clinic-cyber-jirei", "clinic-ma-shukyaku-jirei",
               "clinic-kenchiku-jirei", "clinic-shiko-jirei", "ai-kantan-shukyaku"],
    "subsidy": ["kojinjigyonushi-kaigyoutodoke-denshishinsei", "kensetsugyou-denshishinsei-etsuran",
                "kensetsugyou-denshishinsei-gyoseishoshi", "kensetsugyou-kyoka-denshishinsei",
                "kaigo-denshishinsei-todokede", "shakaihoken-denshishinsei-gimuka-chusho",
                "egov-denshishinsei-kojinjigyonushi", "kojinjigyonushi-kyufukin-shinsei", "nougyou-hojokin-sekai-hikaku"],
}
# 外さないと決めた記事（sweeep は 10-07 公開で28日後の判定に残す。院長が読む4本は導線を足して残す。
# 題が補助金の電子申請の2本は狙う語を補助金の文脈に直して残す）
KEEP = ["sweeep-seikyusho", "shika-heiin-hiyou", "shika-kaigyou-hiyou", "shika-reform-hiyou",
        "clinic-denwa-yoyaku-yarikata", "kensetsugyou-denshishinsei-system", "hojokin-denshishinsei-gimuka-itsukara"]
DIRECTOR = ["shika-heiin-hiyou", "shika-kaigyou-hiyou", "shika-reform-hiyou", "clinic-denwa-yoyaku-yarikata"]


def _fm(slug):
    t = (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    return m.group(1), m.group(2)


def _all_hidden():
    return [s for ss in HIDE.values() for s in ss]


def test_decided_articles_are_noindex_with_reason():
    import noindex
    import kw_fit
    print("\n■ 運用者が決めた記事に noindex（理由・日付つき）。外さない記事は外さない")
    noindex.reset()
    miss = [s for s in _all_hidden() if not noindex.is_hidden(s)]
    check("外すと決めた記事がすべて noindex", miss, [])
    bad = [s for s in _all_hidden() if (ROOT / "articles" / f"{s}.md").is_file()
           and not (re.search(r"^noindex_reason:\s*\S", _fm(s)[0], re.M) and re.search(r"^noindex_date:\s*\d{4}-\d{2}-\d{2}", _fm(s)[0], re.M))]
    check("外した理由と日付が残っている", bad, [])
    check("外さないと決めた記事は noindex にしない", [s for s in KEEP if noindex.is_hidden(s)], [])
    # 院長が読む記事は、集客（AIO・SEO）の記事と業種LPへの導線を足して残す
    no_way = [s for s in DIRECTOR if "/lp/medical/" not in _fm(s)[1]
              or not re.search(r"\]\(/(?:aio|seo)/[a-z0-9-]+/\)", _fm(s)[1].split("## よくある質問")[-1])]
    check("院長が読む4本に、集客の記事と業種LPへの導線がある（記事の末尾）", no_way, [])
    for s in ("kensetsugyou-denshishinsei-system", "hojokin-denshishinsei-gimuka-itsukara"):
        kw = re.search(r"^keyword:\s*(.+)$", _fm(s)[0], re.M).group(1).strip()
        check(f"{s}: 狙う語が補助金の文脈（kw_fit で判定0）", kw_fit.judge(kw, "subsidy")[0], 0)


def test_unlink_keeps_the_words_and_passes_review():
    import noindex
    import auto_review as AR
    print("\n■ 外した記事への内部リンクは記法だけ外し、文は残す（auto_review.guard を通る）")
    hid = {"yucho-kicho-yarikata"}
    src = ("経理の基本は[ゆうちょの記帳のやり方](/blog/yucho-kicho-yarikata/)で確かめます。"
           "絶対URLの[通帳の記帳](https://corp.7senses.co.jp/blog/yucho-kicho-yarikata)も外します。"
           '<a href="/blog/yucho-kicho-yarikata/">枠の中のリンク</a>も同じ。'
           "図は![図](/images/yucho-kicho-yarikata/a.png)のまま。外部の[国税庁](https://www.nta.go.jp/yucho-kicho-yarikata/)も残す。"
           "残すのは[記帳代行とは](/blog/kichodaiko-toha/)です。")
    got, n = noindex.unlink(src, hid)
    want = ("経理の基本はゆうちょの記帳のやり方で確かめます。絶対URLの通帳の記帳も外します。枠の中のリンクも同じ。"
            "図は![図](/images/yucho-kicho-yarikata/a.png)のまま。外部の[国税庁](https://www.nta.go.jp/yucho-kicho-yarikata/)も残す。"
            "残すのは[記帳代行とは](/blog/kichodaiko-toha/)です。")
    check("内部リンク3つ（相対・絶対・HTML）を外し、画像・外部・外さない記事へのリンクは残す", (got, n), (want, 3))
    # 実際の記事に外した記事へのリンクを足し、外したときに検算（本文の減り・タグ・導線・見出し）を通るか
    head, body = _fm("kichodaiko-toha")
    before = body + "\n\n関連して、[ゆうちょの記帳のやり方](/blog/yucho-kicho-yarikata/)もあわせてご確認ください。\n"
    after = noindex.unlink(before, hid)[0]
    check("外した後の本文が auto_review.guard を通る", AR.guard(head, before, after, len(before) - len(after)), "")
    check("リンクの文字は文として残る", "関連して、ゆうちょの記帳のやり方もあわせてご確認ください。" in after, True)
    noindex.reset()
    check("原稿に、外した記事への内部リンクが残っていない", noindex.links(), [])


def test_four_renderers_mark_noindex_and_drop_from_indexes():
    import noindex
    import publish as P
    import search_preview as SP
    import sites as S
    print("\n■ 4つの描き方: head は noindex,follow・sitemap と llms.txt と まとめのページから外す")
    page = ('<html><head><title>t</title>\n<meta name="robots" content="max-snippet:-1, max-image-preview:large">\n'
            '<meta name="robots" content="index,follow">\n</head><body></body></html>')
    out = noindex.set_robots(page)
    check("external-html・build: robots の meta は noindex,follow の1つだけ",
          re.findall(r'<meta name="robots" content="([^"]*)">', out), ["noindex,follow"])
    check("見え方の指定（search_preview）が noindex を書き換えない", SP.robots_tag(out), out)
    check("ページから noindex を読める（配信先の一覧づくりが使う）", (noindex.page_hidden(out), noindex.page_hidden(page)), (True, False))
    check("external-md: フロントマターの robots と noindex", {k: v for k, v in noindex.md_front({"title": "t"}).items()
                                                            if k in ("robots", "noindex")}, {"robots": "noindex, follow", "noindex": True})
    check("nextjs-json: 記事の JSON に noindex と robots", noindex.nextjs_fields({"slug": "x"}),
          {"slug": "x", "noindex": True, "robots": {"index": False, "follow": True}})
    # 配信先の sitemap.xml・llms.txt から外す（足すのではなく外す）
    cfg = S.load("corporate")
    hid = {"slug": "yucho-kicho-yarikata", "category": "keiri-jitsumu", "title": "記帳のやり方", "description": "d",
           "date": "2026-09-10", "noindex": True}
    url = S.article_url(cfg, hid)
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d)
        (dest / "public").mkdir()
        (dest / "public" / "sitemap.xml").write_text(
            f'<?xml version="1.0"?>\n<urlset>\n  <url>\n    <loc>{url}</loc>\n  </url>\n  <url>\n    <loc>https://corp.7senses.co.jp/blog/kichodaiko-toha</loc>\n  </url>\n</urlset>\n',
            encoding="utf-8")
        (dest / "public" / "llms.txt").write_text(f"# x\n- [記帳のやり方]({url}): d\n- [記帳代行](https://corp.7senses.co.jp/blog/kichodaiko-toha): d\n",
                                                  encoding="utf-8")
        P._update_external_index(dest, cfg, hid)
        sm, lt = ((dest / "public" / n).read_text(encoding="utf-8") for n in ("sitemap.xml", "llms.txt"))
        check("配信のとき、外した記事を sitemap.xml から外す（ほかの記事は残す）", (url in sm, "kichodaiko-toha" in sm), (False, True))
        check("配信のとき、外した記事を llms.txt から外す（ほかの記事は残す）", (url in lt, "kichodaiko-toha" in lt), (False, True))
        (dest / cfg["content_dir"]).mkdir(parents=True)
        for s in ("yucho-kicho-yarikata", "kichodaiko-toha"):
            (dest / cfg["content_dir"] / f"{s}.json").write_text("{}", encoding="utf-8")
        noindex.reset()
        check("まとめのページ（比較表・テーマ・用語集）の材料に外した記事を入れない",
              sorted(P._live_slugs(cfg, dest, {"tsucho-kicho-yarikata"})), ["kichodaiko-toha"])
    # コーポレート（Next.js）の記事の読み込みと記事ページ: 外した記事もページは作り、一覧・関連・サイトマップに出さない
    blog = ('export type BlogPost = {\n  slug: string;\n  readingMinutes: number;\n};\n\nfunction readAll(): BlogPost[] {\n  return [];\n}\n\n'
            'export const posts: BlogPost[] = readAll();\n\nexport function getPost(slug: string) {\n  return posts.find((p) => p.slug === slug);\n}\n\n'
            'export function relatedPosts(slug: string, limit = 3) {\n  const base = getPost(slug);\n  if (!base) return [];\n  return posts.slice(0, limit);\n}\n')
    pg = ('import {\n  posts,\n  getPost,\n  relatedPosts,\n} from "@/lib/blog";\n\nexport function generateStaticParams() {\n'
          '  return posts.map((p) => ({ slug: p.slug }));\n}\n\nexport async function generateMetadata({ params }: Props): Promise<Metadata> {\n'
          '  const { slug } = await params;\n  const post = getPost(slug);\n  if (!post) return {};\n  return {\n    title: post.title,\n  };\n}\n\n'
          'export default async function Page({ params }: Props) {\n  const { slug } = await params;\n  const post = getPost(slug);\n  return null;\n}\n')
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d)
        (dest / "src" / "lib").mkdir(parents=True)
        (dest / "src" / "app" / "blog" / "[slug]").mkdir(parents=True)
        (dest / "src" / "lib" / "blog.ts").write_text(blog, encoding="utf-8")
        (dest / "src" / "app" / "blog" / "[slug]" / "page.tsx").write_text(pg, encoding="utf-8")
        w, why = noindex.nextjs_app(dest)
        b = (dest / "src" / "lib" / "blog.ts").read_text(encoding="utf-8")
        p = (dest / "src" / "app" / "blog" / "[slug]" / "page.tsx").read_text(encoding="utf-8")
        check("nextjs: 一覧・関連・サイトマップの posts は外した記事を除く",
              ("export const posts: BlogPost[] = allPosts.filter((p) => !p.noindex);" in b, "noindex?: boolean;" in b, why), (True, True, ""))
        check("nextjs: 記事ページは外した記事も作り（404 にしない）、head を noindex にする",
              ("return allPosts.map((p) => ({ slug: p.slug }));" in p, "getPost(" in p,
               "...(post.noindex ? { robots: { index: false, follow: true } } : {})," in p), (True, False, True))
        check("nextjs: 2回目は何も書かない", noindex.nextjs_app(dest), ([], ""))
        (dest / "src" / "lib" / "blog.ts").write_text("export const items = [];\n", encoding="utf-8")
        (dest / "src" / "app" / "blog" / "[slug]" / "page.tsx").write_text(pg, encoding="utf-8")
        w, why = noindex.nextjs_app(dest)
        check("nextjs: 形の違う先方のアプリには書かず、理由を返す", (w, bool(why)), ([], True))
    # 描き方ごとの配線（どの方式もこの1か所を通る）
    with tempfile.TemporaryDirectory() as d:
        md = Path(d) / "x.md"
        md.write_text("---\ntitle: x\n---\n本文の[ゆうちょの記帳](/blog/yucho-kicho-yarikata/)と[記帳代行とは](/blog/kichodaiko-toha/)。\n",
                      encoding="utf-8")
        check("publish: 配信の入口（parse_article。配信・描き直し・WordPress が通る）で外した記事へのリンクを外す",
              P.parse_article(md)[1].strip(), "本文のゆうちょの記帳と[記帳代行とは](/blog/kichodaiko-toha/)。")
    check("publish nextjs-json: JSON と先方のアプリ", ("noindex.nextjs_fields" in inspect.getsource(P.write_nextjs_json),
                                                   "noindex.nextjs_app" in inspect.getsource(P.write_nextjs_json)), (True, True))
    check("publish external-html: head を noindex に", "noindex.set_robots" in inspect.getsource(P.write_external_html), True)
    check("publish external-md: フロントマターの robots", "noindex.md_front" in inspect.getsource(P.write_external_md), True)
    check("publish: 関連記事（新しい順）に外した記事を出さない", "page_hidden" in inspect.getsource(P._recent_articles), True)
    sub = (ROOT / "scripts" / "subsidy" / "pages.py").read_text(encoding="utf-8")
    check("補助金の一覧・業種・sitemap・llms.txt（subsidy/pages.py）が外した記事を数えない", "page_hidden(" in sub, True)


def test_build_renders_hidden_pages_and_keeps_them_out():
    import build as B
    import noindex
    print("\n■ AI集客ラボ（build.py）: 外した記事もページは作り（200）、head は noindex、導線からは外す")
    noindex.reset()
    tpl = B.TEMPLATE.read_text(encoding="utf-8")
    saved = B.SITE
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as d:
        try:
            B.SITE = Path(d)
            # 仮の置き場には画像が無いので、画像の警告は捨てる（見たいのは head の robots だけ）
            with contextlib.redirect_stdout(io.StringIO()):
                meta, _url = B.build_article(ROOT / "articles" / "clinic-kenchiku-jirei.md", tpl, noindex_page=True)
            out = (Path(d) / meta["category"] / meta["slug"] / "index.html").read_text(encoding="utf-8")
        finally:
            B.SITE = saved
    check("外した記事のページの head が noindex,follow", re.findall(r'<meta name="robots" content="([^"]*)">', out), ["noindex,follow"])
    src = inspect.getsource(B.main)
    check("build: 一覧・sitemap・llms.txt・まとめのページは外した記事を除いた集合で作る", "noindex" in src and "hidden" in src, True)
    check("build: 本文の、外した記事へのリンクを描くときに外す", "noindex.unlink" in inspect.getsource(B.build_article), True)
    site = ROOT / "site"
    if not (site / "sitemap.xml").is_file():
        return
    sm = (site / "sitemap.xml").read_text(encoding="utf-8")
    llms = (site / "llms.txt").read_text(encoding="utf-8")
    lists = "".join((site / p).read_text(encoding="utf-8") for p in ("blog/index.html", "index.html", "aio/index.html",
                                                                      "seo/index.html", "ai-marketing/index.html", "meo/index.html")
                    if (site / p).is_file())
    leaks, nopage = [], []
    for s in HIDE["ai-lab"]:
        hit = list(site.glob(f"*/{s}/index.html"))
        if not hit or not noindex.page_hidden(hit[0].read_text(encoding="utf-8")):
            nopage.append(s)
        if f"/{s}/" in sm or f"/{s}/" in llms or f"/{s}/\"" in lists:
            leaks.append(s)
    check("出力: 外した記事のページはあり（URL を消さない）、head が noindex", nopage, [])
    check("出力: 外した記事が sitemap.xml・llms.txt・一覧に無い", leaks, [])
    hid = set(HIDE["ai-lab"])
    linked = set()
    for f in site.rglob("index.html"):
        if f.parent.name in hid:
            continue
        for h in re.findall(r'<a\b[^>]*href="(?:https://ai\.7senses\.co\.jp)?/[a-z-]+/([a-z0-9-]+)/"', f.read_text(encoding="utf-8", errors="replace")):
            if h in hid:
                linked.add(h)
    check("出力: どのページからも外した記事へリンクしない（業種・テーマ・用語集・関連を含む）", sorted(linked), [])


def test_weekly_tools_leave_hidden_articles_alone():
    import noindex
    print("\n■ 週次の自動の直しが、外した記事に手を入れない・リンクを戻さない")
    noindex.reset()
    hid = set(_all_hidden())
    import link_boost
    import inbound_links
    import rank_up
    import rank_rescue
    import retire_stale
    for sid in ("corporate", "ai-lab", "subsidy"):
        check(f"link_boost: {sid} の送り元・送り先に外した記事を入れない", sorted(set(link_boost.load(sid)) & hid), [])
        check(f"inbound_links（link_new の材料）: {sid} に外した記事を入れない", sorted(set(inbound_links.load_articles(sid)) & hid), [])
    check("rank_up: 押し上げ・リンクの送り元に外した記事を入れない", sorted(set(rank_up.articles()) & hid), [])
    check("rank_rescue: 外した記事を押し上げない", sorted(set(rank_rescue.article_index()) & hid), [])
    check("retire_stale: 外した記事を統合の候補（どちらの側にも）にしない",
          retire_stale._fm(ROOT / "articles" / "yucho-kicho-yarikata.md"), None)
    import auto_rewrite as AW
    import auto_merge as AM
    ok, why = AW.run_one({"slug": "yucho-kicho-yarikata", "kind": "title"}, True)
    check("auto_rewrite: 外した記事は書き直さない", (ok, "noindex" in why), (False, True))
    ok, why = AM.run_one({"survivor": "kichodaiko-toha", "loser": "yucho-kicho-yarikata", "site": "corporate"}, True)
    check("auto_merge: 外した記事を含む組は統合しない", (ok, "noindex" in why), (False, True))
    check("auto_rewrite: 直す一覧から外した記事を除く", "noindex.drop" in inspect.getsource(AW.main), True)
    check("auto_merge: 外した記事を含む組を見送りにする", "noindex" in inspect.getsource(AM.main), True)
    import cta_fill
    import fact_cite
    import auto_improve
    import auto_review
    import i18n
    import article_videos
    import social_post
    import desc_fill
    import season_feature
    for name, src in (("cta_fill", inspect.getsource(cta_fill.main)), ("fact_cite", inspect.getsource(fact_cite.candidates)),
                      ("auto_improve", inspect.getsource(auto_improve.main)), ("auto_review", inspect.getsource(auto_review)),
                      ("i18n", inspect.getsource(i18n.candidates)), ("article_videos", inspect.getsource(article_videos.candidates)),
                      ("social_post", inspect.getsource(social_post)), ("desc_fill", inspect.getsource(desc_fill)),
                      ("season_feature", inspect.getsource(season_feature.related))):
        check(f"{name}: 外した記事を飛ばす", "noindex" in src, True)


def test_periphery_is_stopped_and_seeds_carry_context():
    import json
    import hub_client as HC
    import kw_fit
    print("\n■ AI集客ラボの周辺（SNS・チラシ・看板・イベント）は台帳に入らない。起点は売り物の文脈つき")
    for k in ("リフォーム sns集客", "tiktok 不動産 集客", "不動産 集客 チラシ", "集客できる看板 美容室", "工務店 集客イベント",
              "美容室 集客 インスタ", "税理士 集客 セミナー"):
        check(f"ai-lab: 「{k}」は判定2", kw_fit.judge(k, "ai-lab")[0], 2)
    for k in ("工務店 ai検索 集客", "llmo 店舗集客", "リフォーム 集客 方法", "aio sns 言及", "クリニック seo"):
        check(f"ai-lab: 主力の語「{k}」は止めない", kw_fit.judge(k, "ai-lab")[0], 0)
    saved = {k: getattr(HC, k) for k in ("enabled", "_post")}
    sent = []
    try:
        HC.enabled = lambda: True
        HC._post = lambda body: (sent.append(body), {"ok": True, "added": len(body["keywords"])})[1]
        r = HC.add_kw("ai-lab", ["飲食店 集客 sns", "工務店 aio対策 費用"])
        check("台帳の入口（add_kw）が周辺の語を送らない", [k for b in sent for k in b["keywords"]], ["工務店 aio対策 費用"])
        check("送らなかった語を返す", len((r or {}).get("skipped_unfit", [])), 1)
    finally:
        for k, v in saved.items():
            setattr(HC, k, v)
    corp = json.loads((ROOT / "sites" / "corporate.json").read_text(encoding="utf-8"))
    sub = json.loads((ROOT / "sites" / "subsidy.json").read_text(encoding="utf-8"))
    check("コーポレートの起点に「記帳」単独が無い（通帳の記帳を拾う）", "記帳" in corp["kw_seeds"]["industries"], False)
    check("コーポレートの起点は記帳代行の文脈", any(s.startswith("記帳") and s != "記帳" for s in corp["kw_seeds"]["industries"]), True)
    check("補助金の意図に「電子申請」単独が無い（建設業許可・社会保険の電子申請を拾う）", "電子申請" in sub["kw_seeds"]["intents"], False)
    check("補助金の意図は「補助金 電子申請」", "補助金 電子申請" in sub["kw_seeds"]["intents"], True)
    # 補助金の周辺（AI・IT以外の補助金）は続けるが、主力（AI導入・IT導入）より少ない配分にする
    mix = {k: v for k, v in sub["scheme_mix"].items() if not k.startswith("_")}
    main = mix.get("AI導入補助金", 0) + mix.get("IT導入補助金", 0)
    check("補助金: 周辺の配分（その他を含む）が主力より少ない", (sum(mix.values()), "その他" in mix, sum(mix.values()) - main < main),
          (100, True, True))
    import site_brief
    check("site_brief: 制度の数え方が空白の入った語を取りこぼさない（周辺を多く数えない）",
          [site_brief.scheme_of(k) for k in ("ai導入 補助金 個人事業主", "it 導入 補助金 飲食店", "農業 補助金 トラクター")],
          ["AI導入補助金", "IT導入補助金", "その他"])
