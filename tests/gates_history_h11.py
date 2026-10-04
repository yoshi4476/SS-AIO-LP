# -*- coding: utf-8 -*-
"""検索結果での見え方（robots の meta）と画像・動画のサイトマップの門（2026-10-05）。

Google が公式に説明している手段だけを使う:
  https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag
  https://developers.google.com/search/docs/crawling-indexing/sitemaps/image-sitemaps
  https://developers.google.com/search/docs/crawling-indexing/sitemaps/video-sitemaps
守ること: noindex のページの noindex は外さない／robots の meta は1ページ1つ／
サイトマップは XML として読める／<loc> を数える既存の検査（seo_audit 等）が画像の URL を拾わない。
"""
import json
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import search_preview as SP  # noqa: E402

FULL = "max-image-preview:large"
VID = "AbCdEf12345"


def _page(robots="", body="", ld=None):
    head = '<html><head><meta charset="utf-8"><title>t</title>' + robots + "</head>"
    script = ('<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>") if ld else ""
    return head + "<body>" + body + script + "</body></html>"


def _robots(page):
    return re.findall(r'<meta\s+name="robots"\s+content="([^"]*)"', page)


def test_robots_meta_is_merged_and_noindex_is_kept():
    added = SP.robots_tag(_page())
    check("robots: 無いページには1つ足す", [len(_robots(added)), FULL in added], [1, True])
    merged = SP.robots_tag(_page('<meta name="robots" content="index,follow">'))
    check("robots: 既存の index,follow とまとめて1つにする",
          _robots(merged), ["index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1"])
    two = SP.robots_tag(_page('<meta name="robots" content="index">\n<meta name="robots" content="max-snippet:50">'))
    check("robots: 2つあれば1つにまとめ、先方が決めた max-snippet は上書きしない",
          _robots(two), ["index, max-snippet:50, max-image-preview:large, max-video-preview:-1"])
    for v in ("noindex", "noindex, follow", "NOINDEX,nofollow", "none"):
        p = _page(f'<meta name="robots" content="{v}">')
        check(f"robots: noindex（{v}）のページは一切変えない", SP.robots_tag(p), p)
    check("robots: 何度当てても同じ（ビルドのたびに書き換えない）", SP.robots_tag(merged), merged)


def test_templates_carry_one_robots_meta():
    for rel in ("templates/article.html", "templates/external_article.html"):
        t = (ROOT / rel).read_text(encoding="utf-8")
        check(f"雛形: {rel} の robots は1つで max-image-preview:large を含む",
              [len(_robots(t)), FULL in t], [1, True])
    sub = (ROOT / "scripts" / "subsidy" / "pages.py").read_text(encoding="utf-8")
    check("補助金: 生成するページの robots に見え方の指定がある（index,follow だけのものが残っていない）",
          ['content="index,follow"' in sub, sub.count(FULL) >= 2], [False, True])
    php = (ROOT / "automation" / "wordpress" / "ss-quality-gate.php").read_text(encoding="utf-8")
    check("WordPress: wp_robots で足し、noindex のときは足さない",
          ["add_filter('wp_robots'" in php, "$robots['noindex']" in php], [True, True])


def test_corporate_layout_and_sitemap_template():
    sample = ('export const metadata = {\n  robots: {\n    index: true,\n    follow: true,\n  },\n};\n')
    with tempfile.TemporaryDirectory() as d:
        app = Path(d) / "src" / "app"
        app.mkdir(parents=True)
        (app / "layout.tsx").write_text(sample, encoding="utf-8")
        (app / "sitemap.ts").write_text("old", encoding="utf-8")
        first = SP.corporate(Path(d))
        lay = (app / "layout.tsx").read_text(encoding="utf-8")
        again = SP.corporate(Path(d))
    check("コーポレート: layout の robots に3つを足す（index/follow は残す）",
          ['"max-image-preview": "large"' in lay, '"max-snippet": -1' in lay, "index: true" in lay, len(first)],
          [True, True, True, 2])
    check("コーポレート: 2回目は何も変えない", again, [])
    ts = (ROOT / "templates" / "corporate_sitemap.ts").read_text(encoding="utf-8")
    check("コーポレート: サイトマップの値を XML 用に退避している（Next.js は退避しない）",
          ['replace(/&/g, "&amp;")' in ts, "x(name)" in ts, "x(desc" in ts], [True, True, True])


def test_sitemap_images_and_videos_are_valid_xml():
    origin = "https://ex.jp"
    real = {"/images/s1/eyecatch.png", "/images/s1/flow.png", "/images/blog/s1/thumbnail.webp"}
    body = ('<img src="/images/s1/eyecatch.png"><img src="/images/s1/flow.png?v=3"><img src="/images/s1/gone.png">'
            '<img src="/assets/img/logo.webp"><img src="https://cdn.other.jp/images/s1/x.png">'
            '<img src="/images/s1/eyecatch.png"><img src="/images/blog/s1/thumbnail.webp">'
            f'<iframe src="https://www.youtube-nocookie.com/embed/{VID}"></iframe>')
    ld = {"@context": "https://schema.org", "@type": "VideoObject", "name": "A & B <比較>",
          "description": "説明 & 要点", "thumbnailUrl": f"https://i.ytimg.com/vi/{VID}/hqdefault.jpg",
          "uploadDate": "2026-10-01", "duration": "PT4M45S", "embedUrl": f"https://www.youtube.com/embed/{VID}"}
    page = _page(body=body, ld=ld)
    imgs = SP.page_images(page, "s1", origin, lambda p: p in real)
    check("画像: 記事のスラッグを含み実在するものだけ・重複なし・他ドメインと共通画像は載せない", imgs,
          [f"{origin}/images/s1/eyecatch.png", f"{origin}/images/s1/flow.png", f"{origin}/images/blog/s1/thumbnail.webp"])
    vids = SP.page_videos(page)
    check("動画: 構造化データから題・説明・サムネイル・player_loc・秒数を取る",
          [(v["title"], v["player_loc"], v["duration"]) for v in vids],
          [("A & B <比較>", f"https://www.youtube.com/embed/{VID}", 285)])
    check("動画: 埋め込みが無ければ載せない", SP.page_videos(_page(ld=ld)), [])
    check("動画: サムネイルが欠ければ載せない（必須）", SP.page_videos(_page(body=body, ld={**ld, "thumbnailUrl": ""})), [])

    xml = "\n".join(['<?xml version="1.0" encoding="UTF-8"?>', SP.urlset_open(),
                     SP.url_xml(f"{origin}/a/", "2026-10-01"),
                     SP.url_xml(f"{origin}/blog/s1/", "2026-10-02", imgs, vids), "</urlset>"])
    check("サイトマップ: XMLとして読め、必須がそろっている", SP.check_sitemap(xml), [])
    root = ET.fromstring(xml.encode("utf-8"))
    title = root.find(f".//{{{SP.NS_VIDEO}}}title").text
    check("サイトマップ: 題の & < は退避され、読み戻すと元の文字", title, "A & B <比較>")
    check("サイトマップ: <loc> を数える既存の検査はページのURLだけを拾う（画像・動画のURLを拾わない）",
          re.findall(r"<loc>(.*?)</loc>", xml), [f"{origin}/a/", f"{origin}/blog/s1/"])
    no_ns = xml.replace(f' xmlns:image="{SP.NS_IMAGE}"', "")
    check("サイトマップ: 名前空間が無ければ壊れとして検出する", bool(SP.check_sitemap(no_ns)), True)
    broken = SP.url_xml(f"{origin}/b/", "", [], [{"thumbnail_loc": "t", "title": "x", "description": "",
                                                    "player_loc": "p"}])
    check("サイトマップ: 動画の説明が空なら必須の欠けとして検出する",
          bool(SP.check_sitemap(SP.urlset_open() + broken + "</urlset>")), True)
    big = SP.url_xml(f"{origin}/c/", "", [f"{origin}/i{n}.png" for n in range(SP.MAX_IMAGES + 1)])
    check("サイトマップ: 1URLの画像が1,000を超えれば検出する",
          bool(SP.check_sitemap(SP.urlset_open() + big + "</urlset>")), True)


def test_external_sitemap_append_keeps_xml_valid():
    import publish as P
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d)
        (dest / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                          "  <url>\n    <loc>https://ex.jp/blog/old/</loc>\n  </url>\n</urlset>\n",
                                          encoding="utf-8")
        page = dest / "blog" / "s1" / "index.html"
        page.parent.mkdir(parents=True)
        (dest / "images" / "s1").mkdir(parents=True)
        (dest / "images" / "s1" / "eyecatch.png").write_bytes(b"x")
        page.write_text(_page(body='<img src="/images/s1/eyecatch.png"><img src="/images/s1/none.png">'),
                        encoding="utf-8")
        cfg = {"domain": "ex.jp", "url_prefix": "/blog", "images_dir": "images"}
        P._update_external_index(dest, cfg, {"slug": "s1", "date": "2026-10-05", "title": "t", "description": "d"})
        sm = (dest / "sitemap.xml").read_text(encoding="utf-8")
    check("配信先: 追記したサイトマップが XML として読め、名前空間が足されている",
          [SP.check_sitemap(sm), f'xmlns:image="{SP.NS_IMAGE}"' in sm], [[], True])
    check("配信先: 実在する画像だけが載る", re.findall(r"<image:loc>(.*?)</image:loc>", sm),
          ["https://ex.jp/images/s1/eyecatch.png"])


def test_built_site_pages_and_sitemap():
    site = ROOT / "site"
    sm = site / "sitemap.xml"
    if not sm.is_file():
        return
    text = sm.read_text(encoding="utf-8")
    check("AI集客ラボ: site/sitemap.xml が XML として読め、必須がそろっている", SP.check_sitemap(text), [])
    check("AI集客ラボ: <loc> の数と <url> の数が同じ（画像・動画のURLが混ざらない）",
          len(re.findall(r"<loc>", text)), text.count("<url>"))
    if FULL not in (site / "index.html").read_text(encoding="utf-8"):
        return  # 新しい build.py で描き直す前の site/ は見ない
    dup, missing, lost = [], [], []
    for f in site.rglob("*.html"):
        h = f.read_text(encoding="utf-8", errors="replace")
        if "</head>" not in h:
            continue
        r = _robots(h)
        if len(r) > 1:
            dup.append(str(f.relative_to(site)))
        if any("noindex" in v for v in r):
            if any("max-" in v for v in r):
                lost.append(str(f.relative_to(site)))
            continue
        if not any(FULL in v for v in r):
            missing.append(str(f.relative_to(site)))
    check("AI集客ラボ: robots の meta が2つあるページは無い", dup, [])
    check("AI集客ラボ: noindex 以外の全ページに max-image-preview:large", missing[:5], [])
    check("AI集客ラボ: noindex のページに見え方の指定を混ぜていない", lost, [])
    for p in ("privacy/index.html", "tokushoho/index.html", "thanks/index.html"):
        f = site / p
        if f.is_file():
            check(f"AI集客ラボ: {p} の noindex が残っている",
                  any("noindex" in v for v in _robots(f.read_text(encoding="utf-8"))), True)
