# -*- coding: utf-8 -*-
"""WordPress の社を、先方に何も置かずに回せるかの門（2026-10-06・2026-10-24 に作り直し）。

2026-10-24 運用者「PHP では作らない一番セキュリティが高いもの」で、先方の PHP のプラグイン（ss-quality-gate.php）と
公開サイトでの配布（/wp/）を廃止した。WordPress のお客様の標準はサブドメインの静的なページで、WordPress へ直接
投稿するのは同じドメインがどうしても要る社だけ。そのときも投稿者（author）の権限の鍵だけを預かる。

固定すること（WordPress・外部には触れない。_wp_call と公開一覧の読み込みを差し替えた偽の WordPress）:
  - 投稿者の鍵なら記事を投稿する（本文の画像・内部リンク・入口・動画の URL）。本文に <script> も投稿メタも入れない
  - 管理者・編集者の鍵、公開の権限の無い鍵なら投稿せずに止める（wp_bridge.role_problems・週次の --check）
  - 公開URLは WordPress 本体の REST（鍵なし）、読めなければ sitemap 索引を子まで辿る
  - 統合は下書きに戻し、301 は先方に足してもらう（要対応で知らせる）
  - プラグインのファイル・配布・署名・設定の同期・固定ページづくりがコードから消えている
"""
import inspect
import io
import re
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from test_gates import check, ROOT

AUTHOR = {"roles": ["author"], "capabilities": {"author": True, "publish_posts": True, "upload_files": True,
                                                "edit_posts": True, "edit_published_posts": True}}
ADMIN = {"roles": ["administrator"], "capabilities": {"administrator": True, "manage_options": True,
                                                      "unfiltered_html": True, "publish_posts": True}}


class FakeWP:
    """publish._wp_call の代わり。記事・メディア・鍵のユーザーを辞書で持つ"""

    def __init__(self, me=None, domain="wp.example"):
        self.base = f"https://{domain}"
        self.posts, self.media, self.calls, self.n = {}, {}, [], 100
        self.me = AUTHOR if me is None else me

    def _id(self):
        self.n += 1
        return self.n

    def public(self, url, timeout=30):
        """鍵なしの /wp/v2/posts（wp_bridge._public の代わり）"""
        assert "/wp/v2/posts?" in url and "status=publish" in url, url
        return [{"link": p["link"], "slug": p["slug"], "modified": "2026-10-01T00:00:00"}
                for p in self.posts.values() if p["status"] == "publish"], 1

    def __call__(self, cfg, path, data=None, method=None, headers=None, raw=None):
        self.calls.append((path, data))
        q = dict(x.split("=", 1) for x in path.split("?", 1)[1].split("&")) if "?" in path else {}
        head = path.split("?", 1)[0]
        assert not head.startswith("/ss/"), f"廃止した橋渡しの窓口を呼んだ: {path}"
        if head == "users/me":
            return dict(self.me)
        if head == "categories":
            return [{"id": 3}]
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
            self.posts[pid] = {"id": pid, "status": data["status"], "link": f"{self.base}/2026/10/06/{data['slug']}/",
                               **{k: v for k, v in data.items() if k != "status"}}
            return dict(self.posts[pid])
        m = re.fullmatch(r"posts/(\d+)", head)
        if m:
            p = self.posts[int(m.group(1))]
            p.update(data or {})
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


def _post(fake):
    import publish as P
    import video_embed as VE
    import wp_bridge as W
    meta = {"slug": "h29-a", "title": "クリニックの集客の進め方", "category": "h29-seo", "score": 95,
            "date": "2026-10-06", "description": "説明", "keyword": "クリニック 集客",
            "eyecatch": "/images/h29-a/eyecatch.png", "faq": [{"q": "費用は？", "a": "かかりません。"}]}
    W._ROLE_CHECKED.clear()
    with tempfile.TemporaryDirectory() as td:
        img = Path(td) / "site" / "images" / "h29-a"
        img.mkdir(parents=True)
        from PIL import Image
        Image.new("RGB", (8, 8)).save(img / "eyecatch.png")
        Image.new("RGB", (8, 8)).save(img / "fig.png")
        old = _with(P, _wp_call=fake, ROOT=Path(td), client_credit=lambda c, url="": None)
        oldv = _with(VE, info=lambda s: {"youtube": "abcdEFGhijk", "date": "2026-10-01", "sec": 75} if s == "h29-a" else None)
        oldw = _with(W, _public=fake.public)
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                ok = P.write_wordpress(CFG, meta, BODY, Path(td) / "a.md", push=True)
        finally:
            _with(P, **old)
            _with(VE, **oldv)
            _with(W, **oldw)
            W._ROLE_CHECKED.clear()
    return ok, out.getvalue()


def test_wordpress_posts_with_an_author_key_only():
    print("\n■ WordPress の記事: 投稿者の鍵で本体の REST に投稿する（本文に <script>・投稿メタを入れない）")
    fake = FakeWP()
    fake.posts[1] = {"id": 1, "slug": "h29-old", "status": "publish", "link": "https://wp.example/2026/09/01/h29-old/"}
    ok, _ = _post(fake)
    post = next(p for p in fake.posts.values() if p["slug"] == "h29-a")
    c = post["content"]
    check("公開まで進む", (ok, post["status"]), (True, "publish"))
    check("本文の画像を WordPress のメディアへ上げ、src を置き換える（/images/ のままにしない）",
          ['src="https://wp.example/wp-content/uploads/h29-a-fig.png"' in c, 'src="/images/' in c], [True, False])
    check("本文の内部リンクを実際のパーマリンクへ直す", 'href="https://wp.example/2026/09/01/h29-old/"' in c, True)
    check("その場の入口と中ほどの導線は入れ、<script>（計測・構造化データ）は本文に入れない（投稿者の権限では消える）",
          ['class="cta-inline"' in c, 'class="cta-mid"' in c, "<script" in c], [True, True, False])
    check("動画は URL を1行で置く（iframe は投稿者の権限では消される）",
          ["https://www.youtube.com/watch?v=abcdEFGhijk" in c, "<iframe" in c], [True, False])
    check("投稿メタ（廃止したプラグインが読んでいた _ss_*）を送らない",
          [d for p, d in fake.calls if p.startswith("posts") and isinstance(d, dict) and "meta" in d], [])
    shelf = [m["id"] for m in fake.media.values() if m["slug"].startswith("ss-shelf-")]
    check("アイキャッチ画像（写真の棚から上げたもの）を featured_media にする", post.get("featured_media") in shelf, True)


def test_wordpress_refuses_wide_keys():
    import wp_bridge as W
    print("\n■ 管理者・編集者の鍵、公開の権限の無い鍵なら投稿しない（漏れたときにサイト全体へ届くため）")
    fake = FakeWP(me=ADMIN)
    ok, out = _post(fake)
    check("管理者の鍵: 投稿せずに止め、要対応で知らせる",
          (ok, [p for p, d in fake.calls if p == "posts" and d], "投稿者（author）の専用ユーザー" in out), (False, [], True))
    fake = FakeWP(me={"roles": ["contributor"], "capabilities": {"contributor": True, "edit_posts": True}})
    ok, out = _post(fake)
    check("寄稿者の鍵（公開できない）: 投稿しない", (ok, "publish_posts" in out), (False, True))
    fake = FakeWP(me={"roles": ["author"], "capabilities": {"author": True, "publish_posts": True, "edit_others_posts": True}})
    ok, _ = _post(fake)
    check("投稿者でも、ほかの人の記事を直せる権限が付いていれば止める", ok, False)
    import publish as P
    for me, want in ((ADMIN, "no"), (AUTHOR, "yes")):
        W._ROLE_CHECKED.clear()
        old = _with(P, _wp_call=FakeWP(me=me))
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                W.check({"h29-wp": dict(CFG)})
        finally:
            _with(P, **old)
            W._ROLE_CHECKED.clear()
        check(f"週次の --check: {me['roles'][0]} の鍵は WPBRIDGE_OK={want}", f"WPBRIDGE_OK={want}" in buf.getvalue(), True)
    buf = io.StringIO()
    with redirect_stdout(buf):
        got = W.check({"x": {"id": "x", "type": "ftp"}})
    check("WordPress の社が無ければ unset", (got, "WPBRIDGE_OK=unset" in buf.getvalue()), ([], True))


def test_wordpress_urls_come_from_core_rest_or_sitemap_index():
    import wp_bridge as W
    import notify_indexing as NX
    print("\n■ 公開URL: WordPress 本体の REST（鍵なし）、読めなければ sitemap 索引を子まで辿る")
    fake = FakeWP()
    fake.posts[1] = {"id": 1, "slug": "a", "status": "publish", "link": "https://wp.example/2026/10/01/a/"}
    old = _with(W, _public=fake.public)
    try:
        check("記事の slug → パーマリンク", W.url_map(dict(CFG)), {"a": "https://wp.example/2026/10/01/a/"})
        check("通知（Indexing API）も同じ一覧を使う", NX.sitemap_of(dict(CFG)), ["https://wp.example/2026/10/01/a/"])
    finally:
        _with(W, **old)
    pages = {
        "https://wp.example/sitemap.xml": '<?xml version="1.0"?><sitemapindex><sitemap><loc>https://wp.example/wp-sitemap-posts-post-1.xml</loc></sitemap></sitemapindex>',
        "https://wp.example/wp-sitemap-posts-post-1.xml": "<urlset><url><loc>https://wp.example/b/</loc><lastmod>2026-10-02</lastmod></url></urlset>",
    }

    def broken(url, timeout=30):
        raise OSError("止まっている")
    old = _with(W, _public=broken, _get=lambda url, timeout=30: pages[url])
    try:
        got = W.url_rows(dict(CFG))
        none = W.url_rows(dict(CFG), fallback=False)
    finally:
        _with(W, **old)
    check("REST が読めなければ sitemap 索引から拾う（fallback=False なら空）",
          ([(r["url"], r["slug"]) for r in got], none), ([("https://wp.example/b/", "b")], []))
    for f, needle in (("notify_indexnow.py", "wp_bridge.site_urls(cfg)"), ("bing_webmaster.py", "wp_bridge.sitemap_entries(domain)"),
                      ("seo_audit.py", "wp_bridge.site_urls(cfg)"), ("live_check.py", "wp_bridge.url_rows(cfg)"),
                      ("notify_indexing.py", "wp_bridge.url_map(cfg)")):
        check(f"{f} が WordPress の公開URLを共通の関数で取る", needle in (ROOT / "scripts" / f).read_text(encoding="utf-8"), True)


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
    flow = (ROOT / "scripts" / "publish_flow.py").read_text(encoding="utf-8")
    check("台帳に残すURLも WordPress ではパーマリンク", "wp_bridge.article_url(cfg, meta)" in flow, True)
    check("WordPress 以外は組み立てたURLのまま（同じ関数を通す）",
          W.article_url({"type": "external-html", "domain": "x.example", "url_prefix": "/blog"}, {"slug": "a", "category": "c"}),
          "https://x.example/blog/a/")


def test_wordpress_merge_drafts_and_asks_for_301():
    import retract as R
    print("\n■ 統合: 投稿者の鍵では転送を足せないので、下書きに戻して 301 を先方に頼む")
    src = inspect.getsource(R)
    check("下書きに戻し、転送元と転送先を要対応で知らせる（転送表を書く窓口を呼ばない）",
          ['{"status": "draft"}' in src, "301は先方の WordPress で足してください" in src, "add_redirects" in src], [True, True, False])


def test_wordpress_plugin_is_retired():
    import publish as P
    import site_change as SC
    import wp_bridge as W
    print("\n■ PHP のプラグインと配布をやめた（2026-10-24 運用者「PHP では作らない一番セキュリティが高いもの」）")
    check("プラグインと配布の案内のファイルが無い（公開サイトの /wp/ にも置かない）",
          [p for p in ("automation/wordpress/ss-quality-gate.php", "automation/wordpress/ss-bridge.json",
                       "site/wp/ss-quality-gate.php", "site/wp/ss-bridge.json") if (ROOT / p).exists()], [])
    check("署名・配布・設定の同期・固定ページづくりの関数が無い",
          [n for n in ("publish_release", "sign", "keygen", "push_settings", "add_redirects", "upsert_page", "sync_pages",
                       "sync_if_stale", "plugin_version", "call") if hasattr(W, n)], [])
    check("build.py が /wp/ を置かない", "publish_release" in (ROOT / "scripts" / "build.py").read_text(encoding="utf-8"), False)
    js = ROOT / "automation" / "measure" / "ss-measure.js"
    tag = P.measure_script({"ga4_measurement_id": "G-ABCD1234"})
    check("計測は取り出した JS を唯一の正として読む（PHP の記号が無い）",
          [js.is_file(), "window.SSB_GA4=\"G-ABCD1234\"" in tag, len(tag) > 1000, "<?php" in js.read_text(encoding="utf-8")],
          [True, True, True, False])
    check("サイトの改修は WordPress では FTP の社だけ（REST の固定ページ・デザインの窓口を持たない）",
          [hasattr(SC, n) for n in ("wp_pull", "wp_push", "wp_design_pull", "WP_RES")] + ["FTP の接続情報がありません" in inspect.getsource(SC.main)],
          [False, False, False, False, True])
    import client_intake as CI
    keys = {f[0] for f in CI.FIELDS}
    wp_user = next(f for f in CI.FIELDS if f[0] == "wp.user")
    check("ヒアリングシート: プラグインの設置・管理者の鍵の欄が無く、投稿用のユーザーは投稿者の権限",
          (sorted(keys & {"wp.plugin", "wp.admin_key"}), "投稿者" in wp_user[2]), ([], True))
    tracked = [l for l in __import__("subprocess").run(["git", "grep", "-l", "ss-quality-gate", "--", "scripts", ".github"],
                                                     cwd=ROOT, capture_output=True, text=True).stdout.split() if l]
    check("コードと CI でプラグインを呼ぶ所が無い（説明の中の名前だけ）", [t for t in tracked if t != "scripts/wp_bridge.py"], [])
