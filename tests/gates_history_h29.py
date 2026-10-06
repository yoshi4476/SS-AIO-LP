# -*- coding: utf-8 -*-
"""WordPress の社を、最初の接続のあとは人の手なしで回せるかの門（2026-10-06）。

監査で見つかった抜け: 本文の画像を上げていない／公開の確認が repo を読んで KeyError／
sitemap 索引（/wp-sitemap.xml）を平らに読んで通知が0件／統合が下書きに戻すだけで404／
計測・記事内の入口・FAQPage・VideoObject・著者が出ない／llms.txt を出せない／一括の描き直しが無い／
業種ハブ・用語集が作られない／/%postname%/ の社が登録できない。
先方のプラグイン（ss-quality-gate.php）の橋渡しは、転送を同じサイトのパスに限り、署名とハッシュが
合わない更新を入れないこと。WordPress・外部には触れない（_wp_call を差し替えた偽の WordPress）。
"""
import base64
import hashlib
import inspect
import io
import json
import re
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from test_gates import check, ROOT


class FakeWP:
    """publish._wp_call の代わり。記事・メディア・固定ページ・橋渡し（ss/v1）を辞書で持つ"""

    def __init__(self, domain="wp.example"):
        self.base = f"https://{domain}"
        self.posts, self.pages, self.media, self.calls = {}, {}, {}, []
        self.redirects, self.settings, self.n = {}, {}, 100

    def _id(self):
        self.n += 1
        return self.n

    def __call__(self, cfg, path, data=None, method=None, headers=None, raw=None):
        self.calls.append((path, data))
        q = dict(x.split("=", 1) for x in path.split("?", 1)[1].split("&")) if "?" in path else {}
        head = path.split("?", 1)[0]
        if head == "/ss/v1/urls":
            rows = [{"url": p["link"], "slug": p["slug"], "type": "post", "modified": "2026-10-01T00:00:00+00:00",
                     "managed": False} for p in self.posts.values() if p["status"] == "publish"]
            rows += [{"url": p["link"], "slug": p["slug"], "type": "page", "modified": "2026-10-01T00:00:00+00:00",
                      "managed": p["meta"].get("_ss_managed") == "1"} for p in self.pages.values() if p["status"] == "publish"]
            return {"page": 1, "pages": 1, "urls": rows}
        if head == "/ss/v1/settings":
            self.settings.update(data)
            return {"saved": list(data)}
        if head == "/ss/v1/redirects":
            for r in data.get("add") or []:
                self.redirects[r["from"]] = r["to"]
            return {"count": len(self.redirects), "rejected": []}
        if head == "categories":
            return [{"id": 3, "link": f"{self.base}/category/{q.get('slug', 'x')}/"}]
        if head == "media" and data is None and raw is None:
            return [m for m in self.media.values() if m["slug"] == q.get("search")]
        if head == "media":
            name = re.search(r'filename="([^"]+)"', headers["Content-Disposition"]).group(1)
            mid = self._id()
            slug = re.sub(r"[^a-z0-9-]+", "-", Path(name).stem.lower())
            self.media[mid] = {"id": mid, "slug": slug, "source_url": f"{self.base}/wp-content/uploads/{name}"}
            return self.media[mid]
        if head.startswith("media/"):
            return {}
        if head == "posts" and data is None:
            st = q.get("status", "publish").split(",")
            return [p for p in self.posts.values() if p["slug"] == q.get("slug") and p["status"] in st]
        if head == "posts":
            pid = self._id()
            self.posts[pid] = {"id": pid, "slug": data["slug"], "status": data["status"],
                               "link": f"{self.base}/2026/10/06/{data['slug']}/", "meta": dict(data.get("meta") or {}),
                               "content": data.get("content", "")}
            return dict(self.posts[pid])
        m = re.fullmatch(r"posts/(\d+)", head)
        if m:
            p = self.posts[int(m.group(1))]
            if data:
                p["meta"].update(data.pop("meta", {}) or {})
                p.update({k: v for k, v in data.items() if k in ("status", "content", "slug")})
            return dict(p)
        if head == "pages" and data is None:
            st = q.get("status", "publish").split(",")
            par = q.get("parent")
            return [p for p in self.pages.values()
                    if (q.get("slug") is None or p["slug"] == q.get("slug"))
                    and (par is None or str(p["parent"]) == par) and p["status"] in st]
        if head == "pages":
            pid = self._id()
            par = self.pages.get(data.get("parent") or 0)
            link = (par["link"] if par else self.base + "/") + data["slug"] + "/"
            self.pages[pid] = {"id": pid, "slug": data["slug"], "status": data.get("status", "publish"),
                               "parent": data.get("parent") or 0, "link": link, "meta": dict(data.get("meta") or {}),
                               "content": data.get("content", "")}
            return dict(self.pages[pid])
        m = re.fullmatch(r"pages/(\d+)", head)
        if m:
            p = self.pages[int(m.group(1))]
            if data:
                p["meta"].update(data.pop("meta", {}) or {})
                p.update({k: v for k, v in data.items() if k in ("status", "content", "title")})
            return dict(p)
        return {}


CFG = {"id": "h29-wp", "type": "wordpress", "name": "h29医院", "domain": "wp.example",
       "categories": {"h29-seo": "SEO対策"}, "cta": {"label": "相談", "url": "/contact/"},
       "cta_inline": {"url": "/contact/", "head": "確かめる", "label": "確かめる"},
       "ga4_measurement_id": "G-ABCD1234"}

BODY = """クリニックの集客は、予約までの道筋を短くすることです。

## 集客とは

予約の道筋を短くすることです。

![図](/images/h29-a/fig.png)

[前の記事](/h29-seo/h29-old/)を先に読んでください。

## 進め方

順に進めます。

## 失敗

急がないことです。

## 費用

かかりません。

## よくある質問

まとめています。
"""


def _with(mod, **kw):
    """モジュールの属性を一時的に差し替える（戻すための元の値を返す）"""
    old = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    return old


def test_wordpress_article_gets_images_entries_and_full_jsonld():
    import publish as P
    import video_embed as VE
    print("\n■ WordPress の記事: 本文の画像・入口・内部リンク・動画・構造化データ（BlogPosting+FAQPage+VideoObject）")
    fake = FakeWP()
    fake.posts[1] = {"id": 1, "slug": "h29-old", "status": "publish", "link": "https://wp.example/2026/09/01/h29-old/",
                     "meta": {}, "content": ""}
    meta = {"slug": "h29-a", "title": "クリニックの集客の進め方", "category": "h29-seo", "score": 95,
            "date": "2026-10-06", "description": "説明", "keyword": "クリニック 集客",
            "eyecatch": "/images/h29-a/eyecatch.png",
            "faq": [{"q": "費用は？", "a": "かかりません。"}]}
    with tempfile.TemporaryDirectory() as td:
        img = Path(td) / "site" / "images" / "h29-a"
        img.mkdir(parents=True)
        from PIL import Image
        Image.new("RGB", (8, 8)).save(img / "eyecatch.png")
        Image.new("RGB", (8, 8)).save(img / "fig.png")
        import wp_bridge as W
        old = _with(P, _wp_call=fake, ROOT=Path(td), client_credit=lambda c, url="": None)
        oldv = _with(VE, info=lambda s: {"youtube": "abcdEFGhijk", "date": "2026-10-01", "sec": 75} if s == "h29-a" else None)
        oldw = _with(W, _has_auth=lambda cfg: True)
        try:
            with redirect_stdout(io.StringIO()):
                ok = P.write_wordpress(CFG, meta, BODY, Path(td) / "a.md", push=True)
        finally:
            _with(P, **old)
            _with(VE, **oldv)
            _with(W, **oldw)
    post = next(p for p in fake.posts.values() if p["slug"] == "h29-a")
    c = post["content"]
    check("公開まで進む", (ok, post["status"]), (True, "publish"))
    check("本文の画像を WordPress のメディアへ上げ、src を置き換える（/images/ のままにしない）",
          ['src="https://wp.example/wp-content/uploads/h29-a-fig.png"' in c, 'src="/images/' in c], [True, False])
    check("本文の内部リンクを実際のパーマリンクへ直す", 'href="https://wp.example/2026/09/01/h29-old/"' in c, True)
    check("その場の入口と中ほどの導線を入れ、入口の計測スクリプトは本文に入れない（mu-plugin が送る）",
          ['class="cta-inline"' in c, 'class="cta-mid"' in c, "<script" in c], [True, True, False])
    check("動画は URL を1行で置く（iframe は投稿者の権限によっては消される）",
          ["https://www.youtube.com/watch?v=abcdEFGhijk" in c, "<iframe" in c], [True, False])
    ld = json.loads(post["meta"]["_ss_jsonld"])
    extra = json.loads(post["meta"]["_ss_jsonld_extra"])
    check("自社の WordPress でも BlogPosting を出す（以前は空）・URL はパーマリンク・動画は VideoObject",
          (ld["@type"], ld["mainEntityOfPage"], ld["video"]["@type"], ld["datePublished"]),
          ("BlogPosting", "https://wp.example/2026/10/06/h29-a/", "VideoObject", "2026-10-06"))
    check("FAQPage は別の実体として _ss_jsonld_extra に入れる", (extra[0]["@type"], extra[0]["mainEntity"][0]["name"]),
          ("FAQPage", "費用は？"))
    # アイキャッチ画像は写真の棚の1枚（h31 で他の方式と揃えた）。棚が空のときだけ文字のアイキャッチ
    shelf = [m["id"] for m in fake.media.values() if m["slug"].startswith("ss-shelf-")]
    sent = [d.get("featured_media") for p, d in fake.calls if p == "posts" and d]
    check("アイキャッチ画像（写真の棚から上げたもの）を featured_media にし、その URL を image に入れる",
          ["/ss-shelf-" in ld.get("image", ""), bool(shelf) and sent[:1] == shelf[:1]], [True, True])
    check("公開したら llms.txt・GA4 の測定IDを先方へ送る（静的サイトの llms.txt 追記に当たる）",
          ["llms" in fake.settings, fake.settings.get("ga4")], [True, "G-ABCD1234"])
    check("初回はパーマリンクが分かってから構造化データの URL を直す（2回目の保存）",
          sum(1 for p, d in fake.calls if p == f"posts/{post['id']}" and d is not None and "content" not in d) >= 1, True)


def test_wordpress_publish_check_uses_rest_link():
    import verify_publish as V
    import sites as S
    import wp_bridge as W
    print("\n■ 公開の確認: WordPress は REST のリンクで確かめる（repo を読まない・ビルド待ちに進まない）")
    seen = []
    old_s = _with(S, load=lambda sid: dict(CFG))
    old_w = _with(W, post_link=lambda cfg, slug: f"https://wp.example/2026/10/06/{slug}/")
    old_v = _with(V, wait_live=lambda url, t, title=None: (seen.append(url) or True, f"公開を確認: {url}"),
                  wait_build=lambda *a, **k: (_ for _ in ()).throw(AssertionError("ビルド待ちに進んだ")))
    try:
        ok, msgs = V.verify("h29-wp", "h29-a")
    finally:
        _with(S, **old_s)
        _with(W, **old_w)
        _with(V, **old_v)
    check("repo の無い WordPress でも止まらず、パーマリンクで確かめる", (ok, seen), (True, ["https://wp.example/2026/10/06/h29-a/"]))
    src = inspect.getsource(V.verify)
    check("repo の無い方式はビルド待ちに進まない", 'cfg.get("repo")' in src, True)
    flow = (ROOT / "scripts" / "publish_flow.py").read_text(encoding="utf-8")
    check("台帳に残すURLも WordPress ではパーマリンク", "wp_bridge.article_url(cfg, meta)" in flow, True)
    for f in ("post_social.py", "daily_audit.py", "youtube_upload.py", "video_make.py"):
        check(f"{f}: 外へ出す・確かめる記事URLはパーマリンク（wp_bridge.article_url）",
              "wp_bridge.article_url(" in (ROOT / "scripts" / f).read_text(encoding="utf-8"), True)
    check("WordPress 以外は組み立てたURLのまま（同じ関数を通す）",
          W.article_url({"type": "external-html", "domain": "x.example", "url_prefix": "/blog"}, {"slug": "a", "category": "c"}),
          "https://x.example/blog/a/")


def test_wordpress_urls_come_from_bridge_or_sitemap_index():
    import wp_bridge as W
    import notify_indexing as NX
    import publish as P
    print("\n■ 公開URL: WordPress は橋渡しの一覧、無ければ sitemap 索引を子まで辿る")
    pages = {
        "https://wp.example/sitemap.xml": '<?xml version="1.0"?><sitemapindex><sitemap><loc>https://wp.example/wp-sitemap-posts-post-1.xml</loc></sitemap>'
                                          '<sitemap><loc>https://wp.example/wp-sitemap-posts-page-1.xml</loc></sitemap></sitemapindex>',
        "https://wp.example/wp-sitemap-posts-post-1.xml": "<urlset><url><loc>https://wp.example/a/</loc><lastmod>2026-10-01</lastmod></url></urlset>",
        "https://wp.example/wp-sitemap-posts-page-1.xml": "<urlset><url><loc>https://wp.example/about/</loc></url></urlset>",
    }
    old = _with(W, _get=lambda url, timeout=30: pages[url])
    try:
        got = W.sitemap_entries("wp.example")
    finally:
        _with(W, **old)
    check("sitemap 索引の子まで辿る（子の sitemap のURLを記事として扱わない）",
          got, [("https://wp.example/a/", "2026-10-01"), ("https://wp.example/about/", "")])
    flat = "<urlset><url><loc>https://x.example/a/</loc></url></urlset>"
    old = _with(W, _get=lambda url, timeout=30: flat)
    try:
        check("平らな sitemap はこれまでどおり", W.sitemap_entries("x.example"), [("https://x.example/a/", "")])
    finally:
        _with(W, **old)
    fake = FakeWP()
    fake.posts[1] = {"id": 1, "slug": "a", "status": "publish", "link": "https://wp.example/2026/10/01/a/", "meta": {}}
    old = _with(P, _wp_call=fake)
    oldw = _with(W, _has_auth=lambda cfg: True)
    try:
        check("通知（Indexing API）は橋渡しの公開URLを使う", NX.sitemap_of(dict(CFG)), ["https://wp.example/2026/10/01/a/"])
        check("記事の slug → パーマリンク", W.url_map(dict(CFG)), {"a": "https://wp.example/2026/10/01/a/"})
    finally:
        _with(P, **old)
        _with(W, **oldw)
    for f, needle in (("notify_indexnow.py", "wp_bridge.site_urls(cfg)"), ("notify_indexnow.py", "wp_bridge.push_settings(cfg)"),
                      ("bing_webmaster.py", "wp_bridge.sitemap_entries(domain)"), ("seo_audit.py", "wp_bridge.site_urls(cfg)"),
                      ("live_check.py", "wp_bridge.url_rows(cfg)"), ("notify_indexing.py", "wp_bridge.url_map(cfg)")):
        check(f"{f} が WordPress の公開URLを共通の関数で取る", needle in (ROOT / "scripts" / f).read_text(encoding="utf-8"), True)


def test_wordpress_merge_adds_301_and_rerender_exists():
    import retract as R
    import publish as P
    import sites as S
    import wp_bridge as W
    import sys
    print("\n■ 統合: 先方の転送表に301を足してから下書きに戻す（以前は下書きに戻すだけで旧URLが404）")
    fake = FakeWP()
    fake.posts[1] = {"id": 1, "slug": "lose", "status": "publish", "link": "https://wp.example/2026/09/01/lose/", "meta": {}}
    fake.posts[2] = {"id": 2, "slug": "keep", "status": "publish", "link": "https://wp.example/2026/09/02/keep/", "meta": {}}
    with tempfile.TemporaryDirectory() as td:
        led = Path(td) / "r.jsonl"
        led.write_text(json.dumps({"site": "h29-wp", "slug": "lose", "from": "/h29-seo/lose/", "to": "/h29-seo/keep/",
                                   "at": "2026-10-06"}) + "\n", encoding="utf-8")
        old = (_with(R, RETRACT=led), _with(P, _wp_call=fake), _with(S, load=lambda sid: dict(CFG)),
               _with(W, _has_auth=lambda cfg: True))
        argv = sys.argv
        sys.argv = ["retract.py", "--pending", "--push", "--site", "h29-wp"]
        try:
            with redirect_stdout(io.StringIO()):
                R.main()
        finally:
            sys.argv = argv
            for mod, o in zip((R, P, S, W), old):
                _with(mod, **o)
        row = json.loads(led.read_text(encoding="utf-8").splitlines()[0])
    check("実際のパーマリンク同士で301を足す", fake.redirects, {"/2026/09/01/lose/": "/2026/09/02/keep/"})
    check("負けた記事は下書きに戻り、台帳は処理済み", (fake.posts[1]["status"], bool(row.get("done_at"))), ("draft", True))
    check("llms.txt を送り直す（外した記事を消す）", "llms" in fake.settings and "lose" not in fake.settings["llms"], True)
    check("転送先が別ドメインなら足さない", W.to_path(dict(CFG), "https://evil.example/x/"), None)
    import publish_rerender as PR
    check("一括の描き直しが WordPress を扱う（公開済みの記事だけ・まとめのページも作り直す）",
          [hasattr(PR, "rerender_wordpress"), "sync_pages" in inspect.getsource(PR.rerender_wordpress),
           'cfg["type"] == "wordpress"' in inspect.getsource(PR.main)], [True, True, True])


def test_wordpress_hub_and_glossary_pages():
    import wp_bridge as W
    import publish as P
    import industry_hub as IH
    print("\n■ 業種ハブ・用語集: 固定ページで作り、先方のページは上書きしない・構造化データはメタへ")
    fake = FakeWP()
    old = _with(P, _wp_call=fake)
    try:
        pid, st = W.upsert_page(dict(CFG), "glossary", "用語集",
                                '<p>本文</p><script type="application/ld+json">{"@type": "DefinedTermSet"}</script>')
        pg = fake.pages[pid]
        check("新しく作る・本文に <script> を残さず _ss_jsonld へ・管制塔の印つき",
              (st, "<script" in pg["content"], json.loads(pg["meta"]["_ss_jsonld"])["@type"], pg["meta"]["_ss_managed"]),
              ("created", False, "DefinedTermSet", "1"))
        check("2回目は同じページを直す", W.upsert_page(dict(CFG), "glossary", "用語集", "<p>新</p>")[1], "updated")
        fake.pages[999] = {"id": 999, "slug": "industry", "status": "publish", "parent": 0, "link": "https://wp.example/industry/",
                           "meta": {}, "content": "先方のページ"}
        check("先方の同名ページ（印なし）は触らない", (W.upsert_page(dict(CFG), "industry", "x", "<p>x</p>")[1],
                                                fake.pages[999]["content"]), ("taken", "先方のページ"))
    finally:
        _with(P, **old)
    ind = {"slug": "clinic", "name": "クリニック", "lead": "説明"}
    metas = [{"slug": f"s{i}", "title": f"題{i}", "category": "h29-seo", "date": "2026-10-01"} for i in range(5)]
    body = IH.hub_body(ind, metas, {"h29-seo": ("SEO", "")}, lambda m: f'<li><a href="https://wp.example/{m["slug"]}/">x</a></li>',
                       cat_url=lambda c: "https://wp.example/category/h29-seo/", extras=False)
    check("業種ハブの本文: AI集客ラボにしか無い LP・調査・ツールへの案内を出さず、カテゴリは WordPress のリンク",
          ["/lp/" in body, "/tools/" in body, "https://wp.example/category/h29-seo/" in body], [False, False, True])
    rows = [{"url": "https://wp.example/2026/10/01/s1/", "slug": "s1", "type": "post"}]
    check("用語集・業種ハブの記事リンクをパーマリンクへ（まとめのページ自身は触らない）",
          W.rewrite_links('<a href="/h29-seo/s1/">a</a><a href="/industry/s1/">b</a>', rows),
          '<a href="https://wp.example/2026/10/01/s1/">a</a><a href="/industry/s1/">b</a>')
    pub = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("記事の公開のついでに、まとめのページを1日1回まで作り直す", "wp_bridge.sync_if_stale(cfg, rows)" in pub, True)


def test_wordpress_intake_and_findings():
    import client_intake as CI
    import findings as F
    import wp_bridge as W
    print("\n■ 取り込み: /%postname%/ の WordPress は接頭辞なしで登録できる・週次で版を見る")
    got = {"id": "h29-wp", "type": "wordpress", "domain": "wp.example"}
    ng_wp, _ = CI.review(got, {"id": "h29-wp", "type": "wordpress", "domain": "wp.example"})
    ng_html, _ = CI.review(got, {"id": "h29-x", "type": "external-html", "domain": "x.example", "repo": "a/b"})
    pre = "記事URLの接頭辞が空です"
    check("WordPress は接頭辞が空でも止めない（ほかの方式は止める）",
          (any(pre in n for n in ng_wp), any(pre in n for n in ng_html)), (False, True))
    ng_ga, _ = CI.review(got, {"id": "h29-wp", "type": "wordpress", "domain": "wp.example", "ga4_measurement_id": "UA-1"})
    check("GA4 の測定IDは G- の形だけ", any("GA4の測定ID" in n for n in ng_ga), True)
    check("週次の検査に橋渡しの版の確認がある", any(s == "wp_bridge.py --check" for _, s, _ in F.CHECKS), True)
    with redirect_stdout(io.StringIO()) as o:
        W.check({"x": {"id": "x", "type": "external-html"}})
    check("WordPress の社が無ければ印は unset（要対応にしない）", "WPBRIDGE_OK=unset" in o.getvalue(), True)


def _php():
    return (ROOT / "automation" / "wordpress" / "ss-quality-gate.php").read_text(encoding="utf-8")


def test_bridge_plugin_is_safe():
    print("\n■ 橋渡しのプラグイン: 同じサイトのパスにしか送らない・HTML を出さない・書き込みはアプリケーションパスワードだけ")
    php = _php()
    m = re.search(r"preg_match\('(#\^/.*?#)', \$p\)", php)
    check("転送先・転送元の形の検査がある", bool(m), True)
    # PHP の単一引用符の中の \\\\ は正規表現の \\（1文字のバックスラッシュ）。Python の正規表現に読み替えて同じ入力を当てる
    rx = m.group(1)[1:-1].replace("\\\\\\\\", "\\\\").replace("\\'", "'")
    ok = lambda p: bool(re.fullmatch(rx.lstrip("^").rstrip("$"), p))
    check("同じサイトのパスは通す", [ok("/a/b/"), ok("/2026/10/06/x/"), ok("/%E3%81%82/")], [True, True, True])
    check("別ドメインに読める形は通さない（//・/\\・https://・空白・改行）",
          [ok("//evil.example/"), ok("/\\evil.example"), ok("https://evil.example/"), ok("/a b"), ok("/a\n")],
          [False] * 5)
    check("転送は wp_safe_redirect（許可したホスト以外へ飛ばない）・301", "wp_safe_redirect(home_url($to), 301" in php, True)
    check("書き込みは編集者以上かつアプリケーションパスワードでの認証だけ",
          ["current_user_can('edit_posts')" in php, "rest_get_authenticated_app_password() !== null" in php,
           "'permission_callback' => 'ssb_can_write'" in php], [True] * 3)
    check("llms.txt と鍵ファイルは text/plain・nosniff で、保存した文字列だけを返す",
          ["Content-Type: text/plain; charset=utf-8" in php, "X-Content-Type-Options: nosniff" in php,
           "SSB_MAX_LLMS_BYTES" in php], [True] * 3)
    check("GA4 の測定IDは G- の形だけを保存・出力（wp_json_encode で埋める）",
          [php.count("'/^G-[A-Z0-9]{4,20}$/'") >= 2, "window.SSB_GA4=' . wp_json_encode($ga)" in php], [True, True])
    js = php.split("const SSB_MEASURE_JS = <<<'JS'", 1)[1].split("\nJS;", 1)[0]
    check("計測は site.js と同じ出来事の名前で送る",
          [f"'{e}'" in js for e in ("cta_click", "form_start", "form_abandon", "form_submit", "lead_capture",
                                     "inline_tool_view", "inline_tool_start", "inline_tool_submit", "ab_impression",
                                     "scroll_depth")], [True] * 10)
    check("計測のスクリプトに </script> を含めない", "</script" in js, False)
    check("固定ボタンの文言は esc_html・行き先は同じサイトのパスだけ",
          ["esc_html($st['label'])" in php, "ssb_safe_path($st['url'] ?? '')" in php], [True, True])
    check("REST の新規投稿で、リクエストのメタで判定する（保存前のメタを見て、採点つきの記事まで下書きに戻していた）",
          ["add_filter('rest_pre_insert_post'" in php, "function ssqg_meta(" in php,
           "(int) ssqg_meta($post_id, SSQG_META_SCORE)" in php], [True] * 3)


def test_bridge_self_update_is_signed():
    import wp_bridge as W
    from nacl.signing import SigningKey, VerifyKey
    print("\n■ 自己更新: Ed25519 の署名とハッシュ・版が合うときだけ、同じホストの https から置き換える")
    php = _php()
    check("署名・ハッシュ・版・https・同じホスト・転送なしを確かめる",
          ["sodium_crypto_sign_verify_detached($sig, $body, $pub)" in php, "hash_equals(strtolower((string) $m['sha256'])" in php,
           "version_compare($m['version'], SSB_VERSION, '>')" in php,
           "\"const SSB_VERSION = '\" . $m['version'] . \"';\"" in php,
           "($u['scheme'] ?? '') === 'https'" in php, "strtolower($u['host']) !== strtolower($base['host'] ?? '')" in php,
           php.count("'redirection' => 0") >= 2], [True] * 7)
    check("公開鍵が無ければ自動更新しない・書き換えられないサーバーは blocked を管制塔へ返す",
          ["'nokey'" in php, "'blocked'" in php, "is_writable($file)" in php], [True] * 3)
    check("一時ファイルに書いてから置き換える（途中で壊れたファイルを残さない）", "rename($tmp, $file)" in php, True)
    check("版の行が1つだけある", len(re.findall(r"^const SSB_VERSION = '\d+\.\d+\.\d+';", php, re.M)), 1)
    sk = SigningKey.generate()
    seed = base64.b64encode(bytes(sk)).decode()
    pub = base64.b64encode(bytes(sk.verify_key)).decode()
    with tempfile.TemporaryDirectory() as td:
        plug, man = Path(td) / "p.php", Path(td) / "m.json"
        # 本物の公開鍵が入った後でも試験の鍵に差し替える（空のときだけ差し替えると、鍵を作った後に門が落ちる）
        src = re.sub(r"define\('SSB_PUBKEY', '[^']*'\)", f"define('SSB_PUBKEY', '{pub}')", php).replace("\n", "\r\n")
        plug.write_bytes(src.encode("utf-8"))
        old = _with(W, PLUGIN=plug, MANIFEST=man)
        try:
            m = W.sign(seed, man)
            body = W.plugin_bytes()
            VerifyKey(bytes(sk.verify_key)).verify(body, base64.b64decode(m["sig"]))
            check("署名は改行を LF に揃えた中身に対して作る（Windows の作業コピーでも同じ）",
                  (b"\r\n" in body, m["sha256"] == hashlib.sha256(body).hexdigest(), m["version"] == W.plugin_version()),
                  (False, True, True))
            check("案内がいまのプラグインと合えば /wp/ に置く", (W.manifest_ok(), W.publish_release(Path(td) / "site")),
                  (True, True))
            check("置いた本体は署名したものと同じ", (Path(td) / "site" / "wp" / "ss-quality-gate.php").read_bytes() == body, True)
            plug.write_bytes(plug.read_bytes() + b"// changed\n")
            with redirect_stdout(io.StringIO()) as o:
                placed = W.publish_release(Path(td) / "site2")
            check("直したのに署名し直していなければ置かず、知らせる", (W.manifest_ok(), placed, "署名し直していません" in o.getvalue()),
                  (False, False, True))
            other = base64.b64encode(bytes(SigningKey.generate())).decode()
            try:
                W.sign(other, man)
                wrong = False
            except SystemExit:
                wrong = True
            check("プラグインの公開鍵と違う鍵では署名しない", wrong, True)
        finally:
            _with(W, **old)
    real = W.manifest_ok()
    check("リポジトリの案内があれば、いまのプラグインと合っている（直したら --sign し直す）", real in (None, True), True)
