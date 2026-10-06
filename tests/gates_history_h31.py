# -*- coding: utf-8 -*-
"""記事1本ごとの届け物が、どの納品方式でも出力に入ること（2026-10-06）。

運用者の方針: どの納品方式でも、最初の接続が済んだ後は人の手なしで全機能が動く。
external-md は原稿を置くだけで、本文の図解・アイキャッチが404、構造化データ・動画・入口・写真が1つも
届いていなかった。FTP・ZIP の汎用の雛形には GA4 の計測が無く、nextjs-json には about/mentions と
動画が入っていなかった。WordPress のアイキャッチ画像は写真の棚を使っていなかった。
一時フォルダ・偽の配信先だけで書き出しを通し、出力の中身を見る（Git・FTP・WordPress の本物には触れない）。
"""
import inspect
import json
import re
import tempfile
from pathlib import Path

from test_gates import check, ROOT

SLUG = "h31-shiken"
LD_RX = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
BODY = (
    "IT導入補助金の申請は、準備の順番で結果が変わります。\n\n"
    + "".join(f"## 見出し{i}\n\n**結論{i}**は、ChatGPTを使う前に決めることです。\n\n本文{i}の段落です。\n\n"
              for i in range(1, 7))
    + f'<figure><img src="/images/{SLUG}/zu.png" alt="図" loading="lazy"><figcaption>図</figcaption></figure>\n\n'
    "## よくある質問\n\n### 質問1\n\n答え1です。\n")
META = {"title": "IT導入補助金の準備6つ", "description": "説明", "slug": SLUG, "keyword": "IT導入補助金 準備",
        "category": "c1", "date": "2026-10-01", "modified": "2026-10-05", "score": 95,
        "eyecatch": f"/images/{SLUG}/eyecatch.png",
        "faq": [{"q": "質問1", "a": "答え1です。"}, {"q": "質問2", "a": "答え2です。"}]}
CTA_INLINE = {"url": "https://example-client.test/diag/", "head": "当てはまるか確かめる", "label": "質問に答える"}


def _tree(td, client=True):
    r = Path(td)
    img = r / "site" / "images" / SLUG
    img.mkdir(parents=True)
    from PIL import Image
    for n in ("eyecatch.png", "zu.png"):
        Image.new("RGB", (8, 8), "white").save(img / n)
    (r / "data").mkdir()
    (r / "data" / "videos.json").write_text(json.dumps({SLUG: {"youtube": "abcdEFGhijk", "date": "2026-10-02",
                                                               "sec": 95}}), encoding="utf-8")
    if client:
        c = r / "data" / "clients" / "h31-client"
        c.mkdir(parents=True)
        (c / "company.json").write_text(json.dumps({"name": "株式会社 試験商会"}, ensure_ascii=False), encoding="utf-8")
        (c / "brief.json").write_text(json.dumps({"author": {"name": "試験 一郎", "title": "代表"}},
                                                 ensure_ascii=False), encoding="utf-8")
    return r


def _dest(td):
    d = Path(td) / "dest"
    d.mkdir()
    (d / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n</urlset>\n',
                                   encoding="utf-8")
    (d / "llms.txt").write_text("# 試験\n", encoding="utf-8")
    return d


class _Patched:
    """publish・sites・video_embed の ROOT と台帳を一時フォルダへ向ける"""

    def __init__(self, root):
        import publish as P
        import sites as S
        import video_embed as V
        self.mods, self.root = (P, S, V), root

    def __enter__(self):
        P, S, V = self.mods
        self.old = (P.ROOT, S.ROOT, V.LEDGER)
        P.ROOT = S.ROOT = self.root
        V.LEDGER = self.root / "data" / "videos.json"
        return P

    def __exit__(self, *a):
        P, S, V = self.mods
        P.ROOT, S.ROOT, V.LEDGER = self.old


def _lds(text):
    return [json.loads(b) for b in LD_RX.findall(text)]


def _leaks(text):
    import sites as S
    return [m for m in S.OPERATOR_MARKS if m in text]


def test_external_md_delivers_images_ld_video_entries_and_photo():
    print("\n■ external-md: 原稿だけでなく、画像・写真・構造化データ・動画・入口・サイトマップの画像を届ける")
    cfg = {"id": "h31-client", "type": "external-md", "domain": "example-client.test", "name": "試験コラム",
           "url_prefix": "/column", "content_dir": "content/posts", "images_dir": "static/images",
           "categories": {"c1": "カテゴリ"}, "cta": {"url": "https://example-client.test/contact/", "label": "相談"},
           "cta_inline": CTA_INLINE}
    with tempfile.TemporaryDirectory() as td:
        root = _tree(td)
        dest = _dest(td)
        with _Patched(root) as P:
            written, chars = P.write_external_md(cfg, dest, dict(META), BODY, root / "x.md")
            md = (dest / "content" / "posts" / f"{SLUG}.md").read_text(encoding="utf-8")
            fm = __import__("yaml").safe_load(md.split("---\n")[1])
            body = md.split("---\n", 2)[2]
            check("本文の図解とアイキャッチを配信先の公開フォルダへ複製する",
                  sorted(p.name for p in (dest / "static" / "images" / SLUG).iterdir()), ["eyecatch.png", "zu.png"])
            check("本文とフロントマターの画像の参照を配信先の公開パスへ書き換える",
                  (f'src="/images/{SLUG}/zu.png"' in body, fm["eyecatch"]),
                  (True, f"/images/{SLUG}/eyecatch.png"))
            check("写真の棚から1枚を選び、配信先へ複製して photo と OGP（image）に載せる",
                  [bool(fm.get("photo")), (dest / "static" / fm["photo"].lstrip("/")).is_file(),
                   str(fm.get("image", "")).startswith("https://example-client.test/images/shelf/")],
                  [True, True, True])
            check("robots の meta の値をフロントマターに載せる",
                  fm.get("robots"), "max-snippet:-1, max-image-preview:large, max-video-preview:-1")
            lds = _lds(body)
            bp = next((d for d in lds if d.get("@type") == "BlogPosting"), {})
            check("BlogPosting（日付・画像・about/mentions・お客様の著者と発行元）を本文に置く",
                  [bp.get("datePublished"), bp.get("dateModified"), bool(bp.get("image")),
                   [a["name"] for a in bp.get("about", [])], "ChatGPT" in json.dumps(bp.get("mentions", []), ensure_ascii=False),
                   bp.get("author", {}).get("name"), bp.get("publisher", {}).get("name")],
                  ["2026-10-01", "2026-10-05", True, ["IT導入補助金"], True, "試験 一郎", "株式会社 試験商会"])
            check("FAQPage をフロントマターの FAQ と同じ問いで置く",
                  [q["name"] for d in lds if d.get("@type") == "FAQPage" for q in d["mainEntity"]], ["質問1", "質問2"])
            check("動画を本文の頭に埋め込み、VideoObject を1つだけ出す（BlogPosting に重ねない）",
                  [body.lstrip().startswith('<figure class="article-video"'),
                   sum(d.get("@type") == "VideoObject" for d in lds), "video" in bp,
                   fm.get("video")], [True, 1, False, "https://www.youtube.com/watch?v=abcdEFGhijk"])
            check("最初の章の1文結論の後にその場の入口、中ほどに導線を1つずつ置く（前後は空行）",
                  [body.count('class="cta-inline"'), body.count('class="cta-mid"'),
                   "**結論1**は、ChatGPTを使う前に決めることです。\n\n<aside class=\"cta-inline\"" in body,
                   body.index('class="cta-mid"') < body.index("## 見出し4")], [1, 1, True, True])
            html = P.md2html.convert(body)[0]
            check("Markdown として変換しても入口・導線・構造化データが HTML の塊のまま残る",
                  ['<aside class="cta-inline"' in html, '<div class="cta-mid"' in html,
                   len(LD_RX.findall(html)) == len(lds)], [True, True, True])
            sm = (dest / "sitemap.xml").read_text(encoding="utf-8")
            check("サイトマップに記事の画像（図解・アイキャッチ）と動画の行を足す",
                  [f"https://example-client.test/images/{SLUG}/zu.png" in sm,
                   f"https://example-client.test/images/{SLUG}/eyecatch.png" in sm, "<video:video>" in sm],
                  [True, True, True])
            check("llms.txt に記事を足す", f"/column/{SLUG}/" in (dest / "llms.txt").read_text(encoding="utf-8"), True)
            check("本文の字数は届け物を足す前の本文で数える", chars < len(P.md2html.plain_text(html)), True)
            check("お客様の記事に運用会社の名前が出ない", _leaks(md), [])
        # CSP が YouTube を許さない配信先には埋め込まない（空の枠を出さない）
        (dest / "_headers").write_text("/*\n  Content-Security-Policy: default-src 'self'; frame-src https://www.google.com\n",
                                       encoding="utf-8")
        with _Patched(root) as P:
            P.write_external_md(cfg, dest, dict(META), BODY, root / "x.md")
            md = (dest / "content" / "posts" / f"{SLUG}.md").read_text(encoding="utf-8")
            check("CSP の frame-src が YouTube を許さなければ埋め込まず、BlogPosting の video で渡す",
                  ["<iframe" in md, any(d.get("video") for d in _lds(md))], [False, True])


def test_nextjs_json_carries_entities_video_and_client_ld():
    print("\n■ nextjs-json: about/mentions・動画・お客様の構造化データと入口（コーポレートの見た目は変えない）")
    base = {"type": "nextjs-json", "domain": "example-next.test", "name": "試験", "url_prefix": "/blog",
            "trailing_slash": False, "content_dir": "src/content/blog", "images_dir": "public/images/blog",
            "categories": {"c1": "カテゴリ"}, "cta": {"url": "/contact", "label": "相談"}, "cta_inline": CTA_INLINE}
    with tempfile.TemporaryDirectory() as td:
        root = _tree(td)
        dest = _dest(td)
        with _Patched(root) as P:
            P.write_nextjs_json(dict(base, id="h31-client"), dest, dict(META), BODY)
            out = json.loads((dest / "src" / "content" / "blog" / f"{SLUG}.json").read_text(encoding="utf-8"))
            lds = _lds(out["html"])
            bp = next((d for d in lds if d.get("@type") == "BlogPosting"), {})
            check("JSON に about / mentions を載せる",
                  [[a["name"] for a in out["about"]], "ChatGPT" in json.dumps(out["mentions"], ensure_ascii=False)],
                  [["IT導入補助金"], True])
            check("JSON に動画の材料を載せ、本文の頭に埋め込む（VideoObject つき）",
                  [out.get("video", {}).get("youtube"), out["video"]["inHtml"], "youtube-nocookie.com/embed/" in out["html"],
                   sum(d.get("@type") == "VideoObject" for d in lds)], ["abcdEFGhijk", True, True, 1])
            check("お客様の社: BlogPosting に日付・画像・about・著者、FAQPage を本文に入れる",
                  [bp.get("datePublished"), bool(bp.get("image")), bool(bp.get("about")),
                   bp.get("author", {}).get("name"), any(d.get("@type") == "FAQPage" for d in lds)],
                  ["2026-10-01", True, True, "試験 一郎", True])
            check("お客様の社: その場の入口と中ほどの導線を本文に入れる",
                  ['class="cta-inline"' in out["html"], 'class="cta-mid"' in out["html"]], [True, True])
            check("サイトマップに記事の画像の行を足す（ページを書き出さない方式でも）",
                  f"/images/blog/{SLUG}/zu.png" in (dest / "sitemap.xml").read_text(encoding="utf-8"), True)
            check("お客様の記事に運用会社の名前が出ない", _leaks(json.dumps(out, ensure_ascii=False)), [])
    with tempfile.TemporaryDirectory() as td:
        root = _tree(td, client=False)
        dest = _dest(td)
        (dest / "public").mkdir()
        (dest / "public" / "_headers").write_text(
            "/*\n  Content-Security-Policy: default-src 'self'; frame-src https://www.google.com https://maps.google.com\n",
            encoding="utf-8")
        with _Patched(root) as P:
            P.write_nextjs_json(dict(base, id="h31-own", cta_inline=None), dest, dict(META), BODY)
            out = json.loads((dest / "src" / "content" / "blog" / f"{SLUG}.json").read_text(encoding="utf-8"))
            check("自社（コーポレートと同じ形）: 本文に構造化データ・入口・導線を足さない（アプリ側が出す）",
                  [LD_RX.search(out["html"]) is None, "cta-inline" in out["html"], "cta-mid" in out["html"]],
                  [True, False, False])
            check("CSP が YouTube を許さない配信先は埋め込まず、JSON に inHtml=false で渡す",
                  ["<iframe" in out["html"], out["video"]["inHtml"], bool(out["about"])], [False, False, True])


def test_ftp_zip_template_carries_the_same_measurement_as_wordpress():
    import deliver_files as DF
    print("\n■ FTP・ZIP: 汎用の雛形に GA4 の計測（WordPress の橋渡しと同じ出来事・同じ名前）")
    php = (ROOT / "automation" / "wordpress" / "ss-quality-gate.php").read_text(encoding="utf-8")
    events = sorted(set(re.findall(r"ga\('([a-z_]+)'", php)))
    for typ in ("ftp", "zip"):
        for gid in ("G-H31TEST9", ""):
            cfg = {"id": "h31-client", "type": typ, "domain": "example-ftp.test", "name": "試験の店",
                   "url_prefix": "/column", "categories": {"c1": "カテゴリ"}, "cta_inline": CTA_INLINE,
                   **({"ga4_measurement_id": gid} if gid else {})}
            with tempfile.TemporaryDirectory() as td:
                root = _tree(td)
                base = Path(td) / "stage"
                base.mkdir()
                tpl = (ROOT / "templates" / "external_article.html").read_text(encoding="utf-8")
                (base / "_template.html").write_text(
                    tpl.replace("{{SITE_NAME}}", cfg["name"]).replace("{{ORIGIN}}", "https://example-ftp.test")
                       .replace("{{PREFIX}}", "/column"), encoding="utf-8")
                src = root / f"{SLUG}.md"
                src.write_text("x", encoding="utf-8")
                with _Patched(root) as P:
                    P.write_external_html(DF.stage_cfg(cfg), base, dict(META), BODY, src)
                    page = (base / "blog" / SLUG / "index.html").read_text(encoding="utf-8")
                if gid:
                    check(f"{typ}: 測定IDのある社は計測を1つ置く（WordPress と同じ本体・同じ出来事）",
                          [page.count('id="ss-measure"'), f'window.SSB_GA4="{gid}"' in page,
                           [e for e in events if f"ga('{e}'" not in page],
                           page.index('id="ss-measure"') < page.index("</body>")], [1, True, [], True])
                    check(f"{typ}: 入口の塊が自分で送る計測は外す（二重に数えない）",
                          ["document.currentScript" in page, 'class="cta-inline"' in page], [False, True])
                else:
                    check(f"{typ}: 測定IDの無い社には計測を出さない", ["ss-measure" in page, "googletagmanager" in page],
                          [False, False])
                check(f"{typ}: 運用会社の名前が出ない", _leaks(page), [])
    check("計測の出来事は WordPress と同じ（cta_click・form_submit・lead_capture・inline_tool_view など）",
          {"cta_click", "form_submit", "lead_capture", "inline_tool_view", "form_abandon", "scroll_depth"} <= set(events), True)


def test_wordpress_featured_image_comes_from_the_photo_shelf():
    import publish as P
    print("\n■ WordPress: アイキャッチ画像を写真の棚から選ぶ（他の方式と同じ選び方）")
    got = []
    old = P._wp_media_info
    try:
        P._wp_media_info = lambda cfg, path, alt="", slug="": got.append((Path(path), slug)) or {"id": 7, "url": "u"}
        info = P._wp_photo({"id": "h31-wp"}, dict(META))
    finally:
        P._wp_media_info = old
    check("棚の写真（JPEG）を ss-shelf- の名前で上げ、その ID を返す",
          [info.get("id"), got and got[0][0].parent.name, got and got[0][0].suffix, got and got[0][1]],
          [7, "shelf", ".jpg", "ss-shelf"])
    src = inspect.getsource(P.write_wordpress)
    check("write_wordpress は棚の写真を先に使い、無いときだけ文字のアイキャッチを上げる",
          src.index("_wp_photo(cfg, meta)") < src.index('ROOT / "site" / eye.lstrip("/")'), True)
