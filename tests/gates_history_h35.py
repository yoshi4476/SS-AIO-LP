# -*- coding: utf-8 -*-
"""最初の接続の点検（onboard_check.py）の門（2026-10-06）。

運用者の方針: どの納品方式でも全部動く・人の手間がない。方式×機能の表の partial には「先方の作り次第」で、
配る側のコードを読んでも動くか分からないものがある（先方のビルドが pages_dir・alternates・robots・image を
HTML/head に出すか、CSP が YouTube を止めていないか、sitemap・llms.txt・robots.txt・計測タグがあるか）。
本番を読んで確かめ、出ていなければ先方に頼む1文まで出す。

固定すること（本物の HTTP は使わない。偽の応答で確かめる）:
  - 出ている本番では全項目が ok、出ていない本番では各項目が ng になり、先方に頼む文が付く（道具ごとの文を選ぶ）
  - 「無い」と言う前に逆を探す: sitemap に無い記事は本番で開けるものだけを抜けと数える。
    まとめのページの404は、配った形跡（llms.txt・sitemap・控え）が無ければ「未配信」で要対応にしない
  - 印: 要対応があれば ONBOARD_OK=no、無ければ yes、本番に届かなければ unknown・終了コード1
  - お客様の結果（data/clients/<id>/onboard.json）は public のリポジトリに置かない（.gitignore）
  - 表の partial のうち点検で確かめるセルの note に「onboard_check で確かめる（中身）」がある（--caps で書く）
  - 週次の findings と、ヒアリングの登録直後から呼ばれる
"""
import contextlib
import inspect
import io
import json
import subprocess
from datetime import date

from test_gates import check, ROOT

DOM = "h35.example"
O = f"https://{DOM}"
A1, A2 = f"{O}/blog/a1/", f"{O}/blog/a2/"
KEY = "0123456789abcdef0123"
CFG = {"id": "h35-a", "name": "H35社", "domain": DOM, "type": "external-md", "languages": ["en"],
       "ga4_measurement_id": "G-H35TEST1", "cta_inline": {"url": "/tools/"}, "bing_consent": True}
ARTS = [{"slug": "a1", "url": A1, "date": "2026-09-02", "title": "記事1", "faq": True},
        {"slug": "a2", "url": A2, "date": "2026-09-01", "title": "記事2", "faq": False}]
PAGES = [{"kind": "compare", "path": "/compare/", "title": "比較表から探す"},
         {"kind": "compare", "path": "/compare/x/", "title": "Xの比較表"}]


def _article(good, faq):
    if not good:
        return "<html><head><title>t</title></head><body><h1>t</h1><p>本文</p></body></html>"
    lds = [{"@context": "https://schema.org", "@type": "BlogPosting", "headline": "t"}]
    if faq:
        lds.append({"@type": "FAQPage", "mainEntity": []})
    ld = "".join(f'<script type="application/ld+json">{json.dumps(x)}</script>' for x in lds)
    return ('<html><head><meta name="generator" content="Hugo 0.140.0">'
            '<meta name="robots" content="max-snippet:-1, max-image-preview:large, max-video-preview:-1">'
            f'<meta property="og:image" content="{O}/images/a1.jpg">'
            f'<link rel="alternate" hreflang="en" href="{O}/en/a1/">{ld}'
            '<script async src="https://www.googletagmanager.com/gtag/js?id=G-H35TEST1"></script></head><body>'
            '<iframe src="https://www.youtube-nocookie.com/embed/VID123"></iframe>'
            '<aside class="cta-inline"><script>g("inline_tool_view")</script></aside></body></html>')


def fake_site(good):
    """URL → (状態, ヘッダー, 本文)。good=False は先方の作りが配ったものを出していない本番"""
    sm = ('<?xml version="1.0"?><urlset xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">'
          f'<url><loc>{A1}</loc><image:image><image:loc>{O}/images/a1.jpg</image:loc></image:image></url>'
          f'<url><loc>{A2}</loc></url></urlset>')
    if not good:
        sm = f'<?xml version="1.0"?><urlset><url><loc>{A1}</loc></url></urlset>'
    csp = {} if good else {"content-security-policy": "default-src 'self'; frame-src https://www.google.com"}
    site = {
        "/": (200, {}, '<html><head><meta name="generator" content="Hugo 0.140.0"></head><body>top</body></html>'),
        "/robots.txt": (200, {}, "User-agent: *\nAllow: /\n" if good else "User-agent: GPTBot\nDisallow: /\n"),
        "/sitemap.xml": (200, {}, sm),
        "/llms.txt": (200, {}, f"# H35\n- [記事1]({A1})\n- [記事2]({A2})\n" if good
                      else f"# H35\n## まとめのページ\n- [比較表]({O}/compare/)\n"),
        "/blog/a1/": (200, csp, _article(good, True)),
        "/blog/a2/": (200, csp, _article(good, False)),
        "/images/a1.jpg": (200, {}, ""),
        "/compare/": (200, {}, "<html><body><h1>比較表から探す</h1></body></html>") if good else (404, {}, ""),
        f"/{KEY}.txt": (200, {}, KEY) if good else (404, {}, ""),
        "/BingSiteAuth.xml": (200, {}, "<users><user>ABC</user></users>") if good else (404, {}, ""),
        "/blog/old/": (301, {"location": "/blog/a1/"}, "") if good else (200, {}, "<html>old</html>"),
    }
    return site


def _fetcher(site, log=None):
    def fetch(url, follow=True, head=False):
        if log is not None:
            log.append(url)
        path = url[len(O):] if url.startswith(O) else None
        if site is None:
            return None, {}, "", url
        if path is None or path not in site:
            return (404, {}, "", url) if path is not None else (None, {}, "", url)
        st, hd, body = site[path]
        return st, hd, "" if head else body, url
    return fetch


@contextlib.contextmanager
def _swap(mod, **kw):
    old = {k: getattr(mod, k) for k in kw}
    for k, v in kw.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


def _run(good, cfg=CFG, site=None, **extra):
    import onboard_check as OC
    kw = dict(fetch=_fetcher(site or fake_site(good)), articles=lambda c, ctx: [dict(a) for a in ARTS],
              expected_pages=lambda c, live: PAGES, delivered_paths=lambda c: set(),
              videos=lambda c: {"a1": "VID123"}, translations=lambda c: {"a1": ["en"]},
              merges=lambda c: [("/blog/old/", "/blog/a1/")], indexnow_key=lambda: KEY)
    kw.update(extra)
    with _swap(OC, **kw):
        return OC.run_site(cfg, today=date(2026, 10, 6))


def _status(r):
    out = {}
    for c in r["checks"]:
        out.setdefault(c["id"], c["status"])
    return out


def test_onboard_check_reads_live_and_asks_client():
    import onboard_check as OC
    print("\n■ 最初の接続の点検: 偽の本番で、出ている／出ていないを見分け、先方に頼む文を出す")
    check("検出器: meta generator と Next.js の印から道具を読む",
          (OC.generator('<meta name="generator" content="Jekyll v4.3">'), OC.generator('<script src="/_next/a.js">'),
           OC.generator("<html></html>")), ("jekyll", "next", ""))
    check("検出器: CSP が YouTube を止めるか（frame-src → child-src → default-src の順・無ければ止めない）",
          (OC.csp_blocks_youtube("default-src 'self'; frame-src https://www.google.com"),
           OC.csp_blocks_youtube("frame-src https://www.youtube-nocookie.com"),
           OC.csp_blocks_youtube("default-src 'self'"), OC.csp_blocks_youtube("script-src 'self'"), OC.csp_blocks_youtube("")),
          (True, False, True, False, False))
    check("検出器: JSON-LD の @type を @graph・配列の中まで拾う",
          OC.ld_types('<script type="application/ld+json">{"@graph":[{"@type":["BlogPosting"]},{"@type":"FAQPage"}]}</script>'),
          {"BlogPosting", "FAQPage"})

    want = ["robots_txt", "sitemap", "llms_txt", "ld_blogposting", "ld_faqpage", "robots_meta", "og_image",
            "measure_tag", "measure_entry", "sitemap_images", "hreflang", "video_embed", "merge_301",
            "indexnow_key", "bing_auth", "agg_compare"]
    good = _run(True)
    st = _status(good)
    check("出ている本番: 全項目が ok", {k: st.get(k) for k in want}, {k: "ok" for k in want})
    check("まとめのページは種類ごとに入口の1ページだけ開く（/compare/x/ は開かない）",
          [c["detail"] for c in good["checks"] if c["id"] == "agg_compare"], ["/compare/"])

    bad = _run(False)
    st = _status(bad)
    check("出ていない本番: 各項目が ng", {k: st.get(k) for k in want}, {k: "ng" for k in want})
    ng = [c for c in bad["checks"] if c["status"] == "ng"]
    check("ng のすべてに先方に頼む文が付く", [c["id"] for c in ng if not c["ask"].strip()], [])
    asks = {c["id"]: c["ask"] for c in ng}
    check("頼む文は道具に合わせる（Hugo の社には Hugo の設定で書く）",
          (".Params.robots" in asks["robots_meta"], "content/pages" in asks["agg_compare"],
           "unsafe = true" in asks["measure_entry"]), (True, True, True))
    check("頼む文は方式に合わせる（Cloudflare Pages 以外のホストの転送・CSP の frame-src）",
          ("_redirects" in asks["merge_301"], "youtube-nocookie.com" in asks["video_embed"]), (True, True))
    det = {c["id"]: c["detail"] for c in ng}
    check("何が出ていないかを書く（sitemap の抜けは記事の slug・robots.txt は止めているクローラー）",
          ("a2" in det["sitemap"], "GPTBot" in det["robots_txt"], "noindex" not in det["robots_meta"]), (True, True, True))

    # 逆を探す: sitemap に無い記事が本番で開けない（未配信）なら抜けと数えない。まとめのページも配った形跡が無ければ未配信
    site = fake_site(False)
    site["/blog/a2/"] = (404, {}, "")
    site["/llms.txt"] = (200, {}, f"# H35\n- [記事1]({A1})\n")
    st = _status(_run(False, site=site))
    check("sitemap に無く本番でも開けない記事は抜けと数えない／配った形跡の無いまとめのページは未配信",
          (st["sitemap"], st["agg_compare"]), ("ok", "skip"))
    with_ctl = _status(_run(False, site=site, delivered_paths=lambda c: {"/compare/"}))
    check("配信の控えにあるまとめのページの404は要対応", with_ctl["agg_compare"], "ng")

    nolive = _status(_run(True, articles=lambda c, ctx: []))
    check("公開済みの記事が無い社は、記事の要る項目を確かめず（試験の記事を出さない）skip にする",
          (nolive["ld_blogposting"], nolive["sitemap"], nolive["llms_txt"], nolive["robots_txt"]),
          ("skip", "skip", "skip", "ok"))
    noi18n = _status(_run(True, cfg=dict(CFG, languages=[], cta_inline={}, bing_consent=False)))
    check("多言語・入口・Bing を指示していない社はその項目を見ない",
          ("hreflang" in noi18n, "measure_entry" in noi18n, "bing_auth" in noi18n), (False, False, False))

    # WordPress: 橋渡しの版と、ナビ
    import wp_bridge
    wp = dict(CFG, type="wordpress", languages=[])
    site = fake_site(True)
    site["/wp-json/ss/v1/urls"] = (200, {}, json.dumps({"urls": [{"slug": "a1", "url": A1, "type": "post"}]}))
    site["/"] = (200, {}, "<html><body><a href='/compare/'>比較</a></body></html>")
    pages = PAGES + [{"kind": "industry", "path": "/industry/", "title": "業種から探す"}]
    site["/industry/"] = (200, {}, "<h1>業種から探す</h1>")
    with _swap(wp_bridge, check=lambda cfgs: ["要対応: h35-a の WordPress のプラグインが古い版です（2.0.1 → 2.0.3）"]):
        r = _run(True, cfg=wp, site=site, expected_pages=lambda c, live: pages)
    st, asks = _status(r), {c["id"]: c["ask"] for c in r["checks"]}
    check("WordPress: 橋渡しが古ければ要対応・ナビから業種ハブへ辿れなければ要対応",
          (st.get("wp_bridge"), st.get("hub_nav"), "mu-plugins" in asks["wp_bridge"], "メニュー" in asks["hub_nav"]),
          ("ng", "ng", True, True))


def test_onboard_check_output_and_privacy():
    import onboard_check as OC
    import sites as S
    print("\n■ 最初の接続の点検: 印と終了コード・お客様の結果を public に置かない・表と通知につながる")
    cfgs = {"h35-a": CFG}

    def main_with(good, site=None):
        buf = io.StringIO()
        kw = dict(fetch=_fetcher(None if site == "dead" else (site or fake_site(good))),
                  articles=lambda c, ctx: [dict(a) for a in ARTS], expected_pages=lambda c, live: PAGES,
                  delivered_paths=lambda c: set(), videos=lambda c: {"a1": "VID123"},
                  translations=lambda c: {"a1": ["en"]}, merges=lambda c: [("/blog/old/", "/blog/a1/")],
                  indexnow_key=lambda: KEY)
        with _swap(OC, **kw), contextlib.redirect_stdout(buf):
            rc = OC.main(["--all", "--no-save"], cfgs=cfgs)
        return rc, buf.getvalue()

    rc, out = main_with(True)
    check("出ている本番: ONBOARD_OK=yes・終了コード0・要対応なし", (rc, "ONBOARD_OK=yes" in out, "要対応:" in out), (0, True, False))
    rc, out = main_with(False)
    lines = [l for l in out.splitlines() if l.startswith("要対応:")]
    check("出ていない本番: ONBOARD_OK=no・終了コード0（見つかったは0）", (rc, "ONBOARD_OK=no" in out), (0, True))
    check("要対応の形: 「要対応: <社> <機能>: <何が出ていない>・<先方に頼むこと>」（機能は表の名前）",
          any(l.startswith("要対応: H35社 sitemap.xml: ") and "・" in l for l in lines), True)
    rc, out = main_with(False, site="dead")
    check("本番に1回も届かない: ONBOARD_OK=unknown・終了コード1", (rc, "ONBOARD_OK=unknown" in out), (1, True))

    with _swap(S, is_client=lambda sid: sid == "h35-a"):
        cp, op = OC.out_path("h35-a"), OC.out_path("ai-lab")
    check("お客様の結果は data/clients/<id>/onboard.json・自社は data/onboard/<id>.json",
          (cp.relative_to(ROOT).as_posix(), op.relative_to(ROOT).as_posix()),
          ("data/clients/h35-a/onboard.json", "data/onboard/ai-lab.json"))
    ign = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "data/clients/h35-a/onboard.json"]).returncode
    own = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "data/onboard/ai-lab.json"]).returncode
    check("お客様の結果は .gitignore で public に置かない（自社の分はコミットできる）", (ign, own), (0, 1))

    caps = json.loads((ROOT / "data" / "capabilities.json").read_text(encoding="utf-8"))
    hints = OC.load_hints()
    check("点検の項目の機能・方式はすべて表にある",
          sorted({f"{cid}:{f}" for cid, (fs, ms, _) in OC.CHECKS.items() for f in fs if f not in caps["features"]}
                 | {f"{cid}:{m}" for cid, (_, ms, _) in OC.CHECKS.items() for m in ms if m not in caps["methods"]}), [])
    check("点検の項目すべてに先方に頼む文がある（data/onboard_hints.json）",
          sorted(cid for cid in OC.CHECKS if not hints.get(cid)), [])
    check("頼む文の方式は表の方式か既定（_）だけ",
          sorted({m for k, v in hints.items() if isinstance(v, dict) for m in v} - set(caps["methods"]) - {"_"}), [])
    want = OC.caps_notes(caps)
    check("表: 点検で確かめる partial のセルが1つ以上ある（空振りで「揃っている」と言わない）", len(want) >= 20, True)
    stale = sorted(f"{f} × {m}" for (f, m), n in want.items() if not str(caps["features"][f]["cells"][m].get("note", "")).endswith(n))
    check("表: 点検で確かめるセルの note に「onboard_check で確かめる（中身）」がある"
          "（python scripts/onboard_check.py --caps で書く）", stale, [])
    extra = sorted(f"{fid} × {m}" for fid, f in caps["features"].items() for m, c in f["cells"].items()
                   if OC.NOTE_HEAD in str(c.get("note", "")) and (fid, m) not in want)
    check("表: 点検の対象でないセルに「onboard_check で確かめる」が残っていない", extra, [])

    import findings as F
    import intake_watch as IW
    check("週次の findings が全社を点検する", any(s == "onboard_check.py --all" for _, s, _ in F.CHECKS), True)
    check("ヒアリングの登録直後に点検し、要対応を通知（findings.txt）へ足す",
          ("onboard(cfg.get(\"id\"))" in inspect.getsource(IW.one), "FINDINGS" in inspect.getsource(IW.onboard)), (True, True))
