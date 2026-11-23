# -*- coding: utf-8 -*-
"""2026-11-23 AIO基盤の点検（aio_check）が、お客様の社の分野の一覧（/column/<分野>/）を記事と取り違え、FAQ も記事型も無いのが
正しい一覧のページを「構造化データ 不足」と出していた。一覧の区切りの名前は社ごとに違うので、名前ではなく「その URL の下に
別のページが sitemap にあるか」で一覧を見分ける。"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_aio_check_skips_listing_pages():
    import aio_check as A
    print("\n■ AIO基盤の点検: 下にページを持つ一覧の URL を記事として開かない")
    locs = ["https://x.example/column/", "https://x.example/column/bpo/", "https://x.example/column/bpo/invoice/",
            "https://x.example/column/it-komon-hiyou/", "https://x.example/about/"]
    check("分野の一覧（下に記事がある）は外し、記事だけを残す", A.article_urls(locs, ["column"]),
          ["https://x.example/column/bpo/invoice/", "https://x.example/column/it-komon-hiyou/"])
    check("今までの一覧の区切り（theme など）も外す",
          A.article_urls(["https://y.example/blog/theme/a/", "https://y.example/blog/kiji/"], ["blog"]),
          ["https://y.example/blog/kiji/"])
