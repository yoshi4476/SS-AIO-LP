# -*- coding: utf-8 -*-
"""地図・動画は、原稿の1行の記号から機械が決まった形の埋め込みを作る（2026-10-12 運用者の決定）。

記事を書く AI は外の文章を読むので、html_safety（2026-10-11）が本文の iframe を止めている。そのため、お客様が
「記事に地図を入れたい」と言っても入れられなかった。AI には HTML を書かせず、`@[地図](住所)`・`@[動画](11文字の id)`
の1行だけを書かせ、行き先・属性は scripts/embeds.py が決める。
- 当社が HTML を作る形式（自社サイト・external-html・FTP・ZIP・nextjs-json）は iframe（loading=lazy）の figure。
  配信先の CSP が許さない行き先はリンク。WordPress は地図がリンク・動画は URL の段落。external-md は Markdown のリンク
- 検査は埋め込みを置いた後の HTML を見て、記号から作った iframe と1文字も違わず、記号の数までのものだけを通す。
  AI が書いた iframe・同じ形の写し・印の偽造・site.js の地図の data-map-src は止める。書き違い・上限超えも止める
架空の社（zz.example）で試す。お客様の社の名前・記事の題・slug は書かない。
"""
import contextlib
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

ADDR = "試験県試験市本町1丁目2-3 試験ビル3階"
VID = "zzTEST_ab-1"
GOOD = (f"## アクセス\n\n店までの道順です。\n@[地図]({ADDR})\n\n"
        f"## 動画で見る\n\n@[動画]({VID})\n\n本文の段落です。\n")
MAP_KEYS = {"src", "title", "loading", "referrerpolicy", "style"}
VIDEO_KEYS = MAP_KEYS | {"allow", "allowfullscreen"}


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.frames, self.figs = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "iframe":
            self.frames.append(dict(attrs))
        if tag == "figure":
            self.figs.append(dict(attrs).get("class"))


def _tags(html):
    p = _Tags()
    p.feed(html)
    p.close()
    return p.frames, p.figs


def _shape(html):
    """良い例の形（地図・動画の figure と、決めた属性だけの iframe 2つ）か"""
    frames, figs = _tags(html)
    if len(frames) != 2 or figs != ["ss-embed ss-map", "ss-embed ss-video"]:
        return False
    m, v = frames
    return (set(m) == MAP_KEYS and m["src"] == f"https://www.google.com/maps?q={quote(ADDR, safe='')}&output=embed"
            and m["title"] == f"「{ADDR}」の地図（Google マップ）" and m["loading"] == "lazy"
            and m["referrerpolicy"] == "strict-origin-when-cross-origin"
            and all(s in m["style"] for s in ("width:100%", "max-width:100%", "height:360px"))
            and set(v) == VIDEO_KEYS and v["src"] == f"https://www.youtube-nocookie.com/embed/{VID}"
            and v["loading"] == "lazy" and v["referrerpolicy"] == "strict-origin-when-cross-origin"
            and "<figcaption" in html and "@[" not in html)


def _kinds(body, meta=None, raw=False):
    import html_safety as HS
    return sorted({k for k, _ in HS.article_problems(meta or {}, body, raw=raw)})


def test_markers_become_the_fixed_embed():
    print("\n■ 記号の1行から、決めた形の地図・動画の埋め込みを作る（AI の文字は title・文字にエスケープして入れるだけ）")
    import embeds as E
    import md2html
    rep = {}
    html = md2html.convert(GOOD, report=rep)[0]
    check("地図・動画が figure（ss-embed ss-map / ss-video）の iframe になり、属性は決めた値だけ", _shape(html), True)
    check("検査で通す iframe は、置いた2つの開始タグだけ（report）", [t.split('"')[1].split("/")[2] for t in rep["frames"]],
          ["www.google.com", "www.youtube-nocookie.com"])
    check("良い例は止めない（build.py・publish.py・score_check と同じ html_safety）", (_kinds(GOOD), _kinds(GOOD, raw=True)),
          ([], []))
    three = "\n\n".join([f"@[地図](試験市本町{i}丁目)" for i in range(1, 4)] + [f"@[動画](zzTEST_ab-{i})" for i in range(3)])
    check("地図・動画は各3つまで通す", (len(_tags(md2html.convert(three)[0])[0]), _kinds(three)), (6, []))
    odd = E.html_for("地図", 'a"<b>&\'c')
    check("値は title・文字にエスケープして入れる（引用符で属性から抜けない）",
          ('title="「a&quot;&lt;b&gt;&amp;&#x27;c」の地図（Google マップ）"' in odd, 'a"<b>' in odd), (True, False))
    link = md2html.convert(GOOD, embeds="link")[0]
    check("link: iframe を出さず、Google マップの検索と YouTube への普通のリンク",
          ("<iframe" in link, f'href="https://www.google.com/maps/search/?api=1&amp;query={quote(ADDR, safe="")}"' in link,
           f'href="https://www.youtube.com/watch?v={VID}"' in link, "@[" in link), (False, True, True, False))
    wp = md2html.convert(GOOD, embeds="wp")[0]
    check("wp: 地図はリンク、動画は URL だけの段落（WordPress が埋め込みに変える。iframe は権限で消される）",
          ("<iframe" in wp, "maps/search/?api=1" in wp, f"<p>https://www.youtube.com/watch?v={VID}</p>" in wp), (False, True, True))
    gone = md2html.convert(GOOD, embeds=None)[0]
    check("None: 何も出さない（記号の文字も残さない）", ("<iframe" in gone, "地図" in re.sub(r"<[^>]+>", "", gone), "@[" in gone),
          (False, False, False))
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)

        def modes(csp):
            (d / "_headers").write_text(f"/*\n  Content-Security-Policy: {csp}\n", encoding="utf-8") if csp else None
            h = md2html.convert(GOOD, embeds=d)[0]
            return ("ss-map" in h, "ss-video" in h)
        check("配信先の CSP: 無い・枠の項目が無い → 両方 iframe／YouTube だけ許す → 地図はリンク／default-src 'self' → 両方リンク",
              [modes(""), modes("frame-ancestors 'self'"), modes("default-src 'self'; frame-src https://www.youtube-nocookie.com"),
               modes("default-src 'self'; frame-src https://www.google.com https://www.youtube-nocookie.com"), modes("default-src 'self'")],
              [(True, True), (True, True), (False, True), (True, True), (False, False)])
    check("自社サイト（site/_headers の CSP は枠を縛らない）は iframe", _shape(md2html.convert(GOOD, embeds=ROOT / "site")[0]), True)
    md = E.markdown_links(GOOD)
    check("external-md: 記号の行を普通の Markdown のリンクの行にする（iframe を出さない）",
          (f"[Google マップで「{ADDR}」を開く](https://www.google.com/maps/search/?api=1&query={quote(ADDR, safe='')})" in md,
           f"[YouTube で動画を見る](https://www.youtube.com/watch?v={VID})" in md, "@[" in md, "<iframe" in md),
          (True, True, False, False))
    fenced = f"```\n@[地図]({ADDR})\n```\n"
    check("コードの囲みの中の記号は文字のまま（止めない・埋め込まない・リンクにしない）",
          (_kinds(fenced), "<iframe" in md2html.convert(fenced)[0], E.markdown_links(fenced)), ([], False, fenced))


def test_bad_markers_and_forged_embeds_are_stopped():
    print("\n■ 書き違い・上限超え・AI が書いた iframe・同じ形の写し・印の偽造・地図の data-map-src は止める（埋め込まない）")
    import html_safety as HS
    import md2html
    base = "## 見出し\n\n本文です。\n\n"
    bad = {
        "住所に < >": "@[地図](試験市<script>)",
        "住所に URL": "@[地図](https://evil.example/x)",
        "住所にドメイン": "@[地図](www.evil.example)",
        "住所に全角のドメイン": "@[地図](ｗｗｗ．ｅｖｉｌ．ｅｘａｍｐｌｅ)",
        "住所に \"": '@[地図](試験市"本町)',
        "住所に '": "@[地図](試験市'本町)",
        "住所に `": "@[地図](試験市`本町)",
        "住所に制御文字": "@[地図](試験市\x07本町)",
        "括弧の入れ子": "@[地図](試験市(本社))",
        "住所が81字": "@[地図](" + "あ" * 81 + ")",
        "住所が空": "@[地図]( )",
        "動画の id が10文字": "@[動画](zzTEST_ab-)",
        "動画の id が12文字": "@[動画](zzTEST_ab-12)",
        "動画の id に /": "@[動画](zzTEST/ab-1)",
        "文の途中の記号": f"地図は @[地図]({ADDR}) です",
        "行末に文字": f"@[地図]({ADDR}) です",
        "字下げした記号": f"  @[地図]({ADDR})",
        "知らない種類": f"@[マップ]({ADDR})",
        "HTML の塊の中の記号": f'<div class="x">\n@[地図]({ADDR})\n</div>',
        "地図が4つ": "\n\n".join(f"@[地図](試験市本町{i}丁目)" for i in range(1, 5)),
        "動画が4つ": "\n\n".join(f"@[動画](zzTEST_ab-{i})" for i in range(4)),
    }
    for name, snip in bad.items():
        body = base + snip + "\n"
        # 上限超えは上限まで埋め込む（どちらにしても門で止まる）。ほかは1つも埋め込まない
        check(f"止める: {name}", (_kinds(body), len(_tags(md2html.convert(body)[0])[0])),
              (["embed"], 3 if name.endswith("4つ") else 0))
    copy = md2html.convert(f"@[地図]({ADDR})\n")[0]
    forged = {
        "AI が書いた iframe（Google マップの形）": ('<iframe src="https://www.google.com/maps?q=x&output=embed"></iframe>', ["frame"]),
        "埋め込みの HTML の写し（記号なし）": (copy, ["frame"]),
        "埋め込みの HTML の写し＋記号1つ（記号の数を超える）": (f"@[地図]({ADDR})\n\n" + copy, ["frame"]),
        "site.js の地図の data-map-src（押すと任意の行き先の iframe）":
            ('<div class="map-facade" data-map-src="https://evil.example/"><button class="map-load">地図</button></div>', ["frame"]),
    }
    for name, (snip, want) in forged.items():
        check(f"止める: {name}", _kinds(base + snip + "\n"), want)
    fake = base + "ssembed0123456789abcdefn0\n\n<p>ssembed0123456789abcdefn0</p>\n"
    out = md2html.convert(fake)[0]
    check("印を真似た文字は埋め込みにならない（印は実行ごとの乱数）", ("<iframe" in out, "ssembed0123456789abcdefn0" in out, _kinds(fake)),
          (False, True, []))
    hits = HS.article_problems({}, base + f"@[地図](試験市<x>{ADDR})\n")
    check("止めた理由は行番号と理由だけ（住所はお客様の情報になりうる。CI のログは public）",
          (ADDR in HS.describe(hits), "行目" in HS.describe(hits), "地図・動画の記号" in HS.describe(hits, sample=False)),
          (False, True, True))


def _site_tree(td, bodies):
    import sites as S
    from gates_history_h95_publish_safety import _FM, _body
    root = Path(td)
    (root / "sites").mkdir()
    for p in S.SITES_DIR.glob("*.json"):
        shutil.copy(p, root / "sites" / p.name)
    (root / "sites" / "h101-zzftp.json").write_text(json.dumps(
        {"id": "h101-zzftp", "name": "試験の社", "domain": "zz.example", "type": "ftp", "url_prefix": "/column",
         "categories": {"h101-col": "コラム"}}, ensure_ascii=False), encoding="utf-8")
    (root / "articles").mkdir()
    for slug, (cat, extra) in bodies.items():
        (root / "articles" / f"{slug}.md").write_text(
            _FM.format(title="試験の社の予約を増やす5つの方法", slug=slug, cat=cat) + _body(extra), encoding="utf-8")
    return root


def test_gates_stop_bad_markers_before_delivery():
    print("\n■ 書き違いは publish.py --check（全方式の入口）と score_check（書く段）で止まり、良い例は通る")
    import deliver_files as DF
    import editorial_review as ER
    import publish as P
    import scaled_guard as SG
    import score_check as SC
    import sites as S
    arts = {"h101-ok": ("h101-col", f"@[地図]({ADDR})\n\n@[動画]({VID})"),
            "h101-ng": ("h101-col", "@[地図](https://evil.example/)"),
            "h101-sc-ok": ("aio", f"@[地図]({ADDR})"), "h101-sc-ng": ("aio", "@[動画](zz)")}
    old = (S.ROOT, S.SITES_DIR, P.ROOT, P.WORK, DF.WORK, SG.check, ER.reviewed, sys.argv, SC.ROOT)

    def run(slug):
        sys.argv = ["publish.py", "--site", "h101-zzftp", "--slug", slug, "--check"]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            try:
                P.main()
                res = ""
            except SystemExit as e:
                res = str(e.code)
        text = res + "\n" + out.getvalue()
        return "ok" if "PUBLISH_CHECK=ok" in text else ("BLOCKED" if "BLOCKED(公開不可)" in text else text[:80])
    try:
        with tempfile.TemporaryDirectory() as td:
            root = _site_tree(td, arts)
            S.ROOT, S.SITES_DIR = root, root / "sites"
            P.ROOT, P.WORK, DF.WORK, SC.ROOT = root, root / ".publish-work", root / ".publish-work", root
            SG.check = lambda *a, **k: []
            ER.reviewed = lambda *a, **k: True
            check("publish.py --check: 良い記号は通り、住所に URL の記号は BLOCKED",
                  (run("h101-ok"), run("h101-ng")), ("ok", "BLOCKED"))
            row = {s: [ok for name, ok, _d, _w in SC.run(s) if name.startswith("入れてはいけない HTML")]
                   for s in ("h101-sc-ok", "h101-sc-ng")}
            check("score_check: 良い記号は PASS、id の形違いは FAIL", row, {"h101-sc-ok": [True], "h101-sc-ng": [False]})
    finally:
        (S.ROOT, S.SITES_DIR, P.ROOT, P.WORK, DF.WORK, SG.check, ER.reviewed, sys.argv, SC.ROOT) = old
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("build.py: 記事ごとの門（html_safety）はそのまま・変換は site/ の CSP を見て埋め込む",
          ("html_safety.article_problems(meta, _body)" in src, "md2html.convert(body, embeds=SITE)" in src), (True, True))


def test_each_delivery_format_gets_its_fixed_form():
    print("\n■ 方式ごとの形: nextjs-json・FTP は iframe（CSP が許す行き先）、external-md は Markdown のリンク、WordPress はリンクと URL")
    import deliver_files as DF
    import gates_history_h31 as H31
    body = H31.BODY + "\n" + GOOD
    base = {"type": "nextjs-json", "domain": "example-next.test", "name": "試験", "url_prefix": "/blog",
            "trailing_slash": False, "content_dir": "src/content/blog", "images_dir": "public/images/blog",
            "categories": {"c1": "カテゴリ"}, "cta": {"url": "/contact", "label": "相談"}}
    for csp, want in (("", (True, True)), ("default-src 'self'; frame-src https://www.google.com", (True, False))):
        with tempfile.TemporaryDirectory() as td:
            root = H31._tree(td, client=False)
            dest = H31._dest(td)
            if csp:
                (dest / "public").mkdir()
                (dest / "public" / "_headers").write_text(f"/*\n  Content-Security-Policy: {csp}\n", encoding="utf-8")
            with H31._Patched(root) as P, contextlib.redirect_stdout(io.StringIO()):
                P.write_nextjs_json(dict(base, id="h101-own"), dest, dict(H31.META), body)
                out = json.loads((dest / "src" / "content" / "blog" / f"{H31.SLUG}.json").read_text(encoding="utf-8"))
            h = out["html"]
            check(f"nextjs-json（CSP {'あり' if csp else 'なし'}）: 許す行き先は iframe・許さない行き先はリンク",
                  ("ss-embed ss-map" in h, "ss-embed ss-video" in h, "@[" in h,
                   (f"watch?v={VID}" in h) if not want[1] else True), (*want, False, True))
    cfg = {"id": "h101-md", "type": "external-md", "domain": "example-client.test", "name": "試験コラム",
           "url_prefix": "/column", "content_dir": "content/posts", "images_dir": "static/images", "categories": {"c1": "カテゴリ"}}
    with tempfile.TemporaryDirectory() as td:
        root = H31._tree(td, client=False)
        dest = H31._dest(td)
        with H31._Patched(root) as P, contextlib.redirect_stdout(io.StringIO()):
            P.write_external_md(cfg, dest, dict(H31.META), body, root / "x.md")
            md = (dest / "content" / "posts" / f"{H31.SLUG}.md").read_text(encoding="utf-8")
    check("external-md: 記号は Markdown のリンクの行（iframe を出さない。先方の変換が通すか分からない）",
          ("maps/search/?api=1&query=" in md, f"(https://www.youtube.com/watch?v={VID})" in md, "@[" in md, "ss-embed" in md),
          (True, True, False, False))
    import gates_history_h50 as H50
    import publish as P
    _fm, jbody, _html, bad = P.journal_prepare(H50.CFG, H50.META, H50.BODY + "\n" + GOOD)
    check("external-md（先方の方言の社）: 同じくリンクの行で、先方の変換の門も通る",
          ("maps/search/?api=1&query=" in jbody, "@[" in jbody, "<iframe" in jbody, bad), (True, False, False, []))
    ftp = {"id": "h101-ftp", "type": "ftp", "domain": "example-ftp.test", "name": "試験の店", "url_prefix": "/column",
           "categories": {"c1": "カテゴリ"}}
    with tempfile.TemporaryDirectory() as td:
        root = H31._tree(td, client=False)
        stage = Path(td) / "stage"
        stage.mkdir()
        tpl = (ROOT / "templates" / "external_article.html").read_text(encoding="utf-8")
        (stage / "_template.html").write_text(tpl.replace("{{SITE_NAME}}", ftp["name"]).replace(
            "{{ORIGIN}}", "https://example-ftp.test").replace("{{PREFIX}}", "/column"), encoding="utf-8")
        src = root / f"{H31.SLUG}.md"
        src.write_text("x", encoding="utf-8")
        with H31._Patched(root) as P, contextlib.redirect_stdout(io.StringIO()):
            P.write_external_html(DF.stage_cfg(ftp), stage, dict(H31.META), body, src)
            page = (stage / "blog" / H31.SLUG / "index.html").read_text(encoding="utf-8")
    frames, figs = _tags(page)
    check("FTP・ZIP（external-html と同じ書き出し）: 地図・動画の figure の iframe",
          (figs.count("ss-embed ss-map"), figs.count("ss-embed ss-video"), "@[" in page), (1, 1, False))
    import gates_history_h29 as H29
    import video_embed as VE
    import wp_bridge as W
    fake = H29.FakeWP()
    meta = {"slug": "h101-wp", "title": "クリニックの集客の進め方", "category": "h29-seo", "score": 95, "date": "2026-10-06",
            "description": "説明", "keyword": "クリニック 集客", "eyecatch": "/images/h101-wp/eyecatch.png", "faq": []}
    with tempfile.TemporaryDirectory() as td:
        img = Path(td) / "site" / "images" / "h101-wp"
        img.mkdir(parents=True)
        from PIL import Image
        Image.new("RGB", (8, 8)).save(img / "eyecatch.png")
        old = H29._with(P, _wp_call=fake, ROOT=Path(td), client_credit=lambda c, url="": None)
        oldv = H29._with(VE, info=lambda s: None)
        oldw = H29._with(W, _has_auth=lambda cfg: True)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                P.write_wordpress(H29.CFG, meta, H29.BODY + "\n" + GOOD, Path(td) / "a.md", push=False)
        finally:
            H29._with(P, **old)
            H29._with(VE, **oldv)
            H29._with(W, **oldw)
    c = next(p for p in fake.posts.values() if p["slug"] == "h101-wp")["content"]
    check("WordPress: 地図はリンク・動画は URL の段落（iframe は出さない）",
          ("maps/search/?api=1&amp;query=" in c, f"<p>https://www.youtube.com/watch?v={VID}</p>" in c, "<iframe" in c, "@[" in c),
          (True, True, False, False))


def _before(rel):
    """記号の埋め込みを足す前の版（足したコミットの1つ前。まだコミットしていなければ HEAD）。取れなければ None"""
    def g(*a):
        return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True)
    revs = g("log", "--format=%H", "-S", "import embeds as _embeds", "--", rel).stdout.decode().split()
    r = g("show", f"{revs[-1]}^:{rel}" if revs else f"HEAD:{rel}")
    text = r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
    return text if text and "import embeds" not in text else None


def test_old_code_could_not_render_markers():
    print("\n■ 直す前の変換（md2html）では、良い例が埋め込みにならない（記号が文字・壊れたリンクのまま出る）")
    src = _before("scripts/md2html.py")
    if src is None:
        print("  （直す前の版が手元にありません。浅い取得の CI では飛ばします）")
        return
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "md2html_before_h101.py"
        f.write_text(src, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("md2html_before_h101", f)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        html = mod.convert(GOOD)[0]
    import md2html
    check("直す前: 良い例の形にならない（iframe なし・記号が @<a href=\"住所\"> の壊れたリンクのまま）／直した後: なる",
          (_shape(html), "<iframe" in html, "@[地図]" in html or "@<a href=" in html, _shape(md2html.convert(GOOD)[0])),
          (False, False, True, True))


def test_writers_are_told_and_current_articles_do_not_collide():
    print("\n■ 記事を書く AI の指示書と CLAUDE.md に書き方がある・いまの原稿に記号とぶつかる行が無い")
    for f in ("multi_site_prompt.txt", "retry_prompt.txt", "pipeline_prompt.txt"):
        t = (ROOT / "automation" / f).read_text(encoding="utf-8")
        check(f"指示書 {f}: 地図・動画は記号の1行で書き、iframe は書かない", ("`@[地図](" in t and "`@[動画](" in t, "iframe は書かない" in t),
              (True, True))
    cl = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    row = next((ln for ln in cl.splitlines() if ln.startswith("| **入れてはいけない HTML")), "")
    check("CLAUDE.md の機械品質ゲートの表に記号の埋め込みがある", ("@[地図]" in row, "embeds.py" in row), (True, True))
    files = sorted((ROOT / "articles").glob("*.md")) + sorted((ROOT / "private" / "articles").glob("*.md"))
    hit = sum(any(ln.startswith("@[") for ln in p.read_text(encoding="utf-8-sig", errors="replace").splitlines()) for p in files)
    # お客様の記事も混ざるので、名前は出さず本数だけ見る
    check(f"いまの原稿（{len(files)}本）に、行頭が @[ の行を持つ記事は無い（記号の書き方とぶつからない）", hit, 0)
