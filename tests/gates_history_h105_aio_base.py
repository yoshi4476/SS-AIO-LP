# -*- coding: utf-8 -*-
"""AIO基盤の検出器と図の折り返しの門（2026-10-12 の週次点検）。

1. aio_check: sitemap の先頭が記事の下の一覧ページ（例: /blog/theme）だと、FAQ も記事型も持たないのが正しい
   ページを「構造化データ 不足: FAQPage, 記事型」と出していた。一覧（テーマ・タグ・カテゴリ・ページ送り）を
   記事として選ばない。一覧に FAQPage を足すのは誤り（本文と一致しない構造化データになる）
2. aio_check: お客様の社の社名・ドメイン・記事の slug を出力（CI のログ。public）に出さない。
   見つかったことは印（AIO_OK=no）で表し、終了コード1にしない（CLAUDE.md 8.7）
3. 図の折り返し: 英数字の語を途中で割らない（「Google-Exten／ded」と描かれていた。行数の上限に収まるので
   検査を通っていた）。小さい文字なら割らずに収まるときは小さくし、行の幅を詰める段でも語より狭くしない
4. site/robots.txt: automation/ai-crawlers.txt の20種をすべて明示し、Googlebot を塞がない
架空の社（client-zz・zz.example）で試す。お客様の社の名前・記事の題・slug は書かない。
"""
import contextlib
import io
import re
import sys
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_aio_check_picks_an_article_not_a_listing():
    print("\n■ AIO基盤: 構造化データの検査に一覧ページ（テーマ・タグ・カテゴリ・ページ送り）を選ばない")
    import aio_check as A
    locs = ["https://zz.example/blog/theme", "https://zz.example/blog/theme/zz-kicho",
            "https://zz.example/blog/tag/zz", "https://zz.example/blog/page/2",
            "https://zz.example/blog/category/zz", "https://zz.example/blog",
            "https://zz.example/about", "https://zz.example/blog/zz-article",
            "https://zz.example/blog/theme-guide"]
    check("記事の下の一覧を飛ばし、記事だけを残す（語の一部に theme を含む記事は残す）",
          A.article_urls(locs, ["blog"]),
          ["https://zz.example/blog/zz-article", "https://zz.example/blog/theme-guide"])
    cats = ["https://zz.example/aio/", "https://zz.example/industry/zz-clinic/",
            "https://zz.example/aio/zz-x/", "https://zz.example/topics/aio/"]
    check("カテゴリで分けるサイトも、カテゴリの一覧・業種・テーマの束は選ばない",
          A.article_urls(cats, ["aio", "seo"]), ["https://zz.example/aio/zz-x/"])


def test_aio_check_hides_client_names_and_reports_by_mark():
    print("\n■ AIO基盤: お客様の社は公開の id で書き、社名・ドメイン・記事の slug を出さない。見つかっても終了コード0")
    import aio_check as A
    S = A.sites_mod
    cfgs = {"client-zz": {"name": "ZZ商事の記事", "domain": "zz.example", "url_prefix": "/blog"}}
    pages = {
        "https://zz.example/robots.txt": "User-agent: GPTBot\nAllow: /\n",
        "https://zz.example/llms.txt": "- [記事](https://zz.example/blog/zz-secret-slug)\n",
        "https://zz.example/sitemap.xml": "<loc>https://zz.example/blog/zz-secret-slug</loc>",
        "https://zz.example/blog/zz-secret-slug": '"@type": "BlogPosting" "@type": "BreadcrumbList"',
    }
    with contextlib.ExitStack() as st:
        st.enter_context(mock.patch.object(S, "load_all", lambda: cfgs))
        st.enter_context(mock.patch.object(S, "is_client", lambda s: s == "client-zz"))
        st.enter_context(mock.patch.object(S, "public_id", lambda s: "c00000zz" if s == "client-zz" else s))
        st.enter_context(mock.patch.object(A, "get", lambda u: pages.get(u, "")))
        out = st.enter_context(contextlib.redirect_stdout(io.StringIO()))
        try:
            A.main()
            code = 0
        except SystemExit as e:
            code = e.code
    text = out.getvalue()
    check("社名・ドメイン・記事の slug を出さず、公開の id で書く",
          [w for w in ("ZZ商事", "zz.example", "zz-secret-slug") if w in text] + ["c00000zz" in text], [True])
    check("足りないもの（robots の未記載・FAQPage の不足）は出す",
          ("未記載: " in text, "不足: FAQPage" in text), (True, True))
    check("見つかったことは印で表し、終了コードは0", ("AIO_OK=no" in text, code), (True, 0))


def test_diagram_wrap_keeps_latin_words_whole():
    print("\n■ 図の折り返し: 英数字の語を途中で割らない（小さい文字なら収まるときは小さくする）")
    import make_diagram as MD
    d = MD.Pen()
    width = (MD.W - 2 * MD.M) / 5 - 40       # 手順の図（5つ横並び）の箱の中の幅
    lines, f, ok = MD.fit_block(d, "Google-Extendedを確かめる", width, 3, 24, 16)
    check("手順の図の箱で「Google-Extended」が1行にそろう",
          (ok, any("Google-Extended" in ln for ln in lines)), (True, True))
    w = MD.wrap(d, "Google-Extendedの設定と、robots.txtの書き方を確かめる手順", MD.font(18), width)
    check("行の幅を詰める段でも、語が行をまたがない",
          (len(w) > 1, [x for x in ("Google-Extended", "robots.txt") if not any(x in ln for ln in w)]), (True, []))
    lines, f, ok = MD.fit_block(d, "A" * 80, width, 3, 24, 16)
    check("どの大きさでも入らない長い語は、従来どおり割って収まらないと知らせる", ok, False)


def test_site_robots_lists_every_ai_crawler():
    print("\n■ robots.txt: AI集客ラボは automation/ai-crawlers.txt の20種をすべて明示し、Googlebot を塞がない")
    import ai_crawler_check as C
    want = [ln.split("\t")[0] for ln in (ROOT / "automation" / "ai-crawlers.txt").read_text(encoding="utf-8").splitlines()
            if "\t" in ln]
    text = (ROOT / "site" / "robots.txt").read_text(encoding="utf-8")
    have = set(re.findall(r"User-agent:\s*(\S+)", text, re.I))
    check("一覧は20種", len(want), 20)
    check("20種をすべて明示している", [b for b in want if b not in have], [])
    check("Googlebot と20種のどれも塞いでいない",
          [b for b in ["Googlebot"] + want if not C.robots_allows(text, b)], [])
