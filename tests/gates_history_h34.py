# -*- coding: utf-8 -*-
"""方式×機能の表の partial のうち「道具はあるが工程に組み込めていない」ものを、どの方式でも人の手なしで回すこと（2026-10-06）。

  - 一括の描き直し: publish_rerender.py はあったが、どの工程からも呼ばれていなかった。雛形・CTA・会社の表記を変えても
    既存の記事は古い描き方のまま残った → rerender_watch が描き方の材料の指紋で変わった社だけ描き直す（週次）
  - 統合の301: _redirects（Cloudflare Pages の書式）にしか書かず、Vercel・Netlify・Apache の配信先では転送が効かなかった
  - robots.txt・llms.txt・sitemap.xml: 先方に無ければ作らず、AI クローラーが塞がれていても知らせるだけだった。
    FTP の社では、無いページを 200 で返すサーバーの HTML を sitemap.xml として上げうる形だった
  - 表示速度: 直す道具は手で走らせる前提で、お客様の社は誰も走らせなかった
  - WordPress: 配信時の指紋が無く本文の更新が届いたかを見られない／画像・動画のサイトマップが無い（橋渡し 2.0.3）
偽の配信先（一時フォルダ）で確かめる。外部（GitHub・FTP・WordPress）には触れない。
"""
import io
import json
import re
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from test_gates import check, ROOT

CFG = {"id": "h34-shop", "name": "h34商会", "domain": "h34.example", "url_prefix": "/blog", "content_dir": "content",
       "type": "external-html", "categories": {"h34": "店"}}


def _quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()) as buf:
        out = fn(*a, **kw)
    return out, buf.getvalue()


def test_robots_llms_sitemap_are_placed_and_fixed():
    import ai_crawler_check as AC
    import site_files as SF
    print("\n■ 配信先の robots.txt・llms.txt・sitemap.xml を、無ければ作り、AI クローラーが塞がれていれば直す")

    star = "User-agent: Googlebot\nAllow: /\n\nUser-agent: *\nDisallow: /\nDisallow: /admin/\n"
    new, added, by_name, why = SF.fix_robots(star, ("/", "/blog/x/"))
    check("「*」で塞がれた AI クローラーに名前の組を足す（Googlebot は通っているサイト）",
          [all(AC.robots_allows(new, a, "/blog/x/") for a in SF.AI_AGENTS), "GPTBot" in added, why], [True, True, ""])
    check("足した組も * の組の他の制限（/admin/）は守る", AC.robots_allows(new, "GPTBot", "/admin/x"), False)
    named = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    new2, added2, by_name2, _ = SF.fix_robots(named)
    check("名指しで塞いだ AI クローラーは先方の判断として触らず、知らせる", [new2 == named, added2, by_name2], [True, [], ["GPTBot"]])
    shut = "User-agent: *\nDisallow: /\n"
    check("Googlebot まで塞いだサイト（公開前かもしれない）は触らない", SF.fix_robots(shut)[0], shut)

    check("取ってきた中身: 無いページの HTML は sitemap.xml・llms.txt・robots.txt として使わない",
          [SF.valid("sitemap.xml", b"<!doctype html><html>"), SF.valid("llms.txt", b"<html><body>404"),
           SF.valid("robots.txt", b"<!DOCTYPE html>"), SF.valid("sitemap.xml", b'<?xml version="1.0"?><urlset>'),
           SF.valid("llms.txt", b"# shop\n")], [False, False, False, True, True])

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "index.html").write_text("<html></html>", encoding="utf-8")
        (d / "blog" / "old-post").mkdir(parents=True)
        (d / "blog" / "old-post" / "index.html").write_text('"datePublished": "2026-09-01"', encoding="utf-8")
        got, _ = _quiet(SF.ensure, CFG, d, d / "blog")
        check("静的サイト（external-html）: 無い llms.txt・sitemap.xml・robots.txt を公開フォルダに作る",
              sorted(p.name for p in got), ["llms.txt", "robots.txt", "sitemap.xml"])
        sm = (d / "sitemap.xml").read_text(encoding="utf-8")
        check("作った sitemap.xml に配信済みの記事を載せる（作った回に既存の記事が漏れない）",
              ["https://h34.example/blog/old-post/" in sm, "<lastmod>2026-09-01</lastmod>" in sm], [True, True])
        check("作った robots.txt はサイトマップの場所を書く", "Sitemap: https://h34.example/sitemap.xml" in (d / "robots.txt").read_text(encoding="utf-8"), True)
        check("2回目は何も変えない", _quiet(SF.ensure, CFG, d, d / "blog")[0], [])
        (d / "robots.txt").write_text(star, encoding="utf-8")
        got, _ = _quiet(SF.ensure, CFG, d, d / "blog")
        check("既にある robots.txt が「*」で AI クローラーを塞いでいれば直す", [p.name for p in got], ["robots.txt"])

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "public").mkdir()
        (d / "public" / "favicon.ico").write_bytes(b"x")
        (d / "src" / "app").mkdir(parents=True)
        (d / "src" / "app" / "robots.ts").write_text("export default {}", encoding="utf-8")
        (d / "src" / "app" / "sitemap.ts").write_text("export default {}", encoding="utf-8")
        got, _ = _quiet(SF.ensure, dict(CFG, type="nextjs-json"), d)
        check("Next.js: コードで作る robots・サイトマップは置かず（二重になる）、llms.txt だけ public/ に作る",
              [p.relative_to(d).as_posix() for p in got], ["public/llms.txt"])

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "hugo.toml").write_text('baseURL = "https://h34.example/"', encoding="utf-8")
        (d / "static").mkdir()
        (d / "public").mkdir()
        got, _ = _quiet(SF.ensure, dict(CFG, type="external-md"), d)
        check("Hugo（external-md）: 公開の元の static/ に置く（public/ はビルドの出力で消える）・サイトマップは Hugo が作るので作らない",
              sorted(p.relative_to(d).as_posix() for p in got), ["static/llms.txt", "static/robots.txt"])

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "_robots_dynamic").write_text("1", encoding="utf-8")
        got, _ = _quiet(SF.ensure, dict(CFG, type="ftp"), d, d / "blog")
        check("FTP: サーバーにファイルが無いのに本番が返す robots.txt（CMS・CDN が作る）は作らない・直さない",
              "robots.txt" in [p.name for p in got], False)

    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    m = src.split("def main():", 1)[1]
    check("publish.py: Git の社も FTP の社も、書き出しより先に site_files.ensure を呼ぶ",
          [m.index("site_files.ensure(cfg, dest") < m.index("write_nextjs_json(cfg, dest, meta, body)"),
           m.index("site_files.ensure(cfg, base") < m.index("write_external_html(deliver_files.stage_cfg(cfg)")], [True, True])
    df = (ROOT / "scripts" / "deliver_files.py").read_text(encoding="utf-8")
    check("deliver_files.stage: 取ってきた索引は site_files.valid を通ったものだけ使う",
          df.count("site_files.valid(name, b)") >= 2, True)


def test_merge_redirect_is_written_for_the_host():
    import retract as R
    import site_files as SF
    print("\n■ 統合の301を、配信先のホストが読む形で書く（Cloudflare Pages・Vercel・Netlify・Apache・転送の無いホスト）")
    row = {"slug": "old", "from": "/blog/old/", "to": "/blog/new/", "at": "2026-10-06", "reason": "統合"}

    def run(setup, cfg=CFG):
        td = tempfile.mkdtemp()
        d = Path(td)
        (d / "index.html").write_text("<html></html>", encoding="utf-8")
        (d / "blog" / "old").mkdir(parents=True)
        (d / "blog" / "old" / "index.html").write_text("x", encoding="utf-8")
        setup(d)
        touched, _ = _quiet(R.apply, row, cfg, d)
        return d, touched

    d, t = run(lambda d: (d / "vercel.json").write_text('{"cleanUrls": true}', encoding="utf-8"))
    v = json.loads((d / "vercel.json").read_text(encoding="utf-8"))
    check("Vercel: vercel.json の redirects に 301 で足す（先方の他の設定は残す）",
          [v.get("cleanUrls"), {"source": "/blog/old/", "destination": "/blog/new/", "statusCode": 301} in v["redirects"],
           (d / "_redirects").exists(), "vercel.json" in t], [True, True, False, True])
    check("Vercel: 2回目は足さない", SF.add_redirect(CFG, d, "/blog/old/", "/blog/new/", "x"), None)
    d, _ = run(lambda d: (d / "netlify.toml").write_text('[build]\n  publish = "dist"\n', encoding="utf-8"))
    nt = (d / "netlify.toml").read_text(encoding="utf-8")
    check("Netlify: netlify.toml に [[redirects]] を足す（公開フォルダが分からなくても効く）",
          ['publish = "dist"' in nt, 'from = "/blog/old/"' in nt and "status = 301" in nt], [True, True])
    d, _ = run(lambda d: (d / ".htaccess").write_text("RewriteEngine On\n", encoding="utf-8"))
    ht = (d / ".htaccess").read_text(encoding="utf-8")
    check("Apache: .htaccess に Redirect 301 を足す（先方の設定は残す）",
          [ht.splitlines()[0], "Redirect 301 /blog/old/ https://h34.example/blog/new/" in ht], ["RewriteEngine On", True])
    d, _ = run(lambda d: None)
    check("見分けがつかなければ従来どおり _redirects（Cloudflare Pages）", "/blog/old/ /blog/new/ 301" in (d / "_redirects").read_text(encoding="utf-8"), True)
    d, _ = run(lambda d: None, dict(CFG, redirect_host="meta"))
    stub = (d / "blog" / "old" / "index.html").read_text(encoding="utf-8")
    check("転送の仕組みの無いホスト（redirect_host=meta）: 旧URLに正規URLと即時の移動だけのページ",
          ['rel="canonical" href="https://h34.example/blog/new/"' in stub, 'content="noindex"' in stub], [True, True])
    d, t = run(lambda d: None, dict(CFG, type="ftp"))
    check("FTP の社は retract.apply では転送を書かない（deliver_files.retract が .htaccess に書く）",
          [(d / "_redirects").exists(), any("_redirects" in x for x in t)], [False, False])


def test_bulk_rerender_runs_when_inputs_change():
    import rerender_watch as RW
    print("\n■ 雛形・設定が変わった社だけ、公開済みの記事を全部描き直す（週次）")
    cfg = dict(CFG, cta={"label": "相談する", "url": "/contact/"}, kw_seeds={"core": ["a"]})
    parts = RW.inputs(cfg)
    check("初めて見る社は指紋を記録するだけ", RW.judge(None, parts)[0], False)
    prev = {"fp": RW.fingerprint(parts), "parts": parts}
    check("変わっていなければ描き直さない", RW.judge(prev, parts)[0], False)
    check("KW の種のように描き方に関係しない項目は、変えても描き直さない",
          RW.judge(prev, RW.inputs(dict(cfg, kw_seeds={"core": ["b"]})))[0], False)
    go, why = RW.judge(prev, RW.inputs(dict(cfg, cta={"label": "無料で相談する", "url": "/contact/"})))
    check("CTA の文言を変えたら描き直す（理由に変わった材料が出る）", [go, "sites" in why], [True, True])
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "tpl.html").write_text("<html>{{BODY}}</html>", encoding="utf-8")
        c2 = dict(CFG, template="tpl.html")
        a = RW.inputs(c2, d)
        (d / "tpl.html").write_text("<html><nav>新</nav>{{BODY}}</html>", encoding="utf-8")
        check("Git の社: 配信先の雛形（site_change で変えた回）が変われば描き直す",
              RW.judge({"fp": RW.fingerprint(a), "parts": a}, RW.inputs(c2, d))[0], True)
    check("対象は描き直しが要る方式だけ（self-static は build.py、external-md は先方のビルドが毎回描く）",
          sorted(RW.TYPES), ["external-html", "ftp", "nextjs-json", "wordpress"])
    pr = (ROOT / "scripts" / "publish_rerender.py").read_text(encoding="utf-8")
    check("publish_rerender は押せなかった回を失敗で返す（指紋を進めず翌週やり直す）",
          ["sys.exit(main())" in pr, "        return 1\n    return 0" in pr], [True, True])
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次が描き直し（rerender_watch --push）を回し、指紋を正本に残す",
          ["python scripts/rerender_watch.py --push" in wf, "git add data/rerender_state.json" in wf], [True, True])


def test_speed_fix_runs_by_itself():
    import speed_fix as SP
    print("\n■ 表示速度の直しを週次で全社に当てる（Git の社・FTP の社・FTP の鍵がある WordPress のテーマ）")
    font = '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP&display=swap" rel="stylesheet">\n'
    php = ("<?php echo '<link href=\"https://fonts.googleapis.com/css2?family=Noto+Sans+JP\" rel=\"stylesheet\">'; ?>\n"
           "<head>\n" + font + "</head>\n")
    out = SP.fix_php(php, "x")
    check("PHP のテンプレート: PHP の外（HTML）のフォントだけ外し、PHP の文字列の中は触らない（引用符をずらさない）",
          [font in out, "<?php echo '<link href=\"https://fonts.googleapis.com" in out], [False, True])
    cfg = dict(CFG, type="wordpress")
    n, why = SP.auto(cfg, False) if not SP.has_ftp(cfg) else (None, "FTP")
    check("WordPress で FTP の鍵が無い社は見送る（mu-plugin が直す範囲だけ）", [n, "FTP" in why], [None, True])
    check("週次の対象の方式", sorted(SP.AUTO_TYPES), ["external-html", "external-md", "ftp", "nextjs-json", "wordpress"])
    src = (ROOT / "scripts" / "speed_fix.py").read_text(encoding="utf-8")
    body = src.split("def auto(cfg, write):", 1)[1].split("\ndef ", 1)[0]
    check("Git の社の週次は画像の遅延読み込みを足さない（配信し直すたびに戻り、毎週同じ差分を押すため）",
          "apply_plan(cfg, base, kind, [], write)" in body, True)
    check("FTP: 直した後にトップが返らなければ元の中身へ戻す", "if olds and not _alive(cfg):" in src, True)
    df = (ROOT / "scripts" / "deliver_files.py").read_text(encoding="utf-8")
    check("FTP の社は配信のたびに雛形のフォント・計測タグを外してから書き出す", "tpl = speed_fix.fix_html(tpl, cfg[\"id\"])" in df, True)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次が speed_fix --auto --apply を回す", "python scripts/speed_fix.py --auto --apply" in wf, True)
    sc = (ROOT / "scripts" / "site_change.py").read_text(encoding="utf-8")
    check("site_change: WordPress で FTP の鍵がある社はテーマを theme/ に取り、FTP で戻す（先方で変わったものは上書きしない）",
          ["got.update(wp_theme_pull(cfg, m))" in sc, "done = wp_theme_push(cfg, theme) if theme else 0" in sc,
           "取った後に変わったテーマのファイル" in sc], [True, True, True])


def test_wordpress_fingerprint_and_media_sitemap():
    import publish
    import publish_gap as PG
    print("\n■ WordPress: 配信の指紋で本文の更新が届いたかを照合し、画像・動画のサイトマップを出す（橋渡し 2.0.3）")
    rows = [{"slug": "a", "type": "post", "hash": "abc"}, {"slug": "b", "type": "post", "hash": ""},
            {"slug": "p", "type": "page", "hash": ""}]
    check("指紋を返す橋渡し: 投稿の slug → 指紋（未記録は載せず、配信し直しの対象になる）",
          PG.live_manifest_wp(CFG, rows), {"a": "abc"})
    check("指紋を返さない古い橋渡しは None（タイトルと本文の照合に切り替える）",
          PG.live_manifest_wp(CFG, [{"slug": "a", "type": "post"}]), None)
    src = (ROOT / "scripts" / "publish_gap.py").read_text(encoding="utf-8")
    check("publish_gap は WordPress でも指紋を読む", 'man = live_manifest_wp(c) if c.get("type") == "wordpress"' in src, True)
    ld = {"video": {"@type": "VideoObject", "name": "動画", "description": "説明", "thumbnailUrl": ["https://i.ytimg.com/vi/x/hq.jpg"],
                    "embedUrl": "https://www.youtube-nocookie.com/embed/x", "duration": "PT1M30S"}}
    m = publish.wp_media('<p><img src="https://h34.example/wp-content/uploads/a.png"></p>', "https://h34.example/wp-content/uploads/eye.jpg", ld)
    check("画像・動画のサイトマップの材料（上げた後の画像の URL・VideoObject）",
          [m["images"], m["videos"][0]["player_loc"], m["videos"][0]["duration"]],
          [["https://h34.example/wp-content/uploads/eye.jpg", "https://h34.example/wp-content/uploads/a.png"],
           "https://www.youtube-nocookie.com/embed/x", 90])
    pub = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("write_wordpress が指紋と材料を投稿メタで送る",
          ['"_ss_source_hash": source_hash(src)' in pub, '"_ss_media": json.dumps(wp_media(html, thumb_url, ld)' in pub], [True, True])
    php = (ROOT / "automation" / "wordpress" / "ss-quality-gate.php").read_text(encoding="utf-8")
    check("橋渡し: 2つの投稿メタを REST で書けるように登録し、/ss/v1/urls が指紋を返す",
          ["SSB_META_HASH => 'string', SSB_META_MEDIA => 'string'" in php,
           "'hash' => (string) get_post_meta($id, SSB_META_HASH, true)" in php], [True, True])
    sm = php.split("function ssb_media_sitemap()", 1)[1].split("\n}\n", 1)[0]
    check("橋渡し: /ss-media-sitemap.xml は JSON として読めた http(s) の URL と文字だけを esc_xml で出す（任意の XML を出させない）",
          ["json_decode(" in sm, "esc_xml(" in sm, "if (!is_array($m))" in sm,
           "preg_match($https_only ? '#^https://#' : '#^https?://#', $u)" in php], [True] * 4)
    check("橋渡し: 動画は必須（サムネイル・題・説明・再生の場所）がそろうものだけ", "if ($thumb === '' || $player === '' || $title === '' || $desc === '')" in sm, True)
    check("橋渡し: 公開している robots.txt にだけ、画像・動画のサイトマップの Sitemap 行を足す",
          "ssb_media_posts(1)" in php.split("add_filter('robots_txt'", 1)[1].split("}, 99, 2);", 1)[0], True)
    check("橋渡しの版は 2.0.3", re.search(r"^const SSB_VERSION = '(\d+\.\d+\.\d+)';", php, re.M).group(1), "2.0.3")


def test_capability_cells_follow_the_work():
    print("\n■ 方式×機能の表: 工程に組み込んだものを ok に、意味の無いものを n/a に")
    caps = json.loads((ROOT / "data" / "capabilities.json").read_text(encoding="utf-8"))
    f = caps["features"]

    def st(fid, ms):
        return [f[fid]["cells"][m]["status"] for m in ms]
    clients = ["external-md", "external-html", "nextjs-json", "wordpress", "ftp"]
    check("一括の描き直し: external-html・nextjs-json・ftp は ok", st("bulk_rerender", ["external-html", "nextjs-json", "ftp"]), ["ok"] * 3)
    check("統合の301: Git の3方式は ok", st("merge_redirect", ["external-md", "external-html", "nextjs-json"]), ["ok"] * 3)
    check("内部リンク: お客様の5方式は ok", st("internal_links", clients), ["ok"] * 5)
    check("問い合わせの自動回答: お客様の5方式は n/a（運用会社の無料ツールと名前の文面）", st("auto_reply", clients), ["n/a"] * 5)
    check("表示速度: WordPress 以外のお客様の4方式は ok", st("speed_fix", ["external-md", "external-html", "nextjs-json", "ftp"]), ["ok"] * 4)
    check("本番の検査・検索での見え方: WordPress は ok", [f["live_check"]["cells"]["wordpress"]["status"],
                                                f["search_preview"]["cells"]["wordpress"]["status"]], ["ok", "ok"])
    check("llms.txt: Git の3方式と ftp は ok", st("llms_txt", ["external-md", "external-html", "nextjs-json", "ftp"]), ["ok"] * 4)
    # n/a の根拠: 追いかけは ai-lab の行だけ、転送は silent（お客様の読者へ運用会社の名前で送らない）
    gs = (ROOT / "automation" / "gas" / "contact.hub.gs").read_text(encoding="utf-8")
    fw = (ROOT / "automation" / "gas" / "forward-to-hub.gs").read_text(encoding="utf-8")
    check("自動回答を n/a にした根拠がコードにある（追いかけは AI集客ラボの行だけ・転送は silent）",
          ["const aiLab = { 'ai-lab': true };" in gs, "silent: true," in fw], [True, True])
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    loop = wf.split('python scripts/link_boost.py "$s" --write || true', 1)[0].rsplit("\n", 2)[-2]
    check("内部リンクを ok にした根拠: 週次の補充は全社で回り、直した原稿は全社へ配信する",
          ["$(python scripts/sites.py --ids)" in loop, "python scripts/publish_changed.py --all --since" in wf], [True, True])
