# -*- coding: utf-8 -*-
"""2026-10-31: Ahrefs の Site Audit（AI集客ラボ）で出た指摘の棚卸し。

- 説明文が短すぎる（/faq/ 76字）・長すぎる（/about/ 161字）。記事の説明文は build.py の門が見ているが、
  固定ページ（faq_page.py の DESC・手で書く site/about/）は seo_audit の「警告」止まりで、--gate は警告では止めない
- 被リンクが1本だけの23ページは、全部が業種別の調査（/research/<業種>-ai-sources/ と /research/ai-answers/）。
  業種ハブの無い業種は一覧（/research/）からしか張られていなかった → 同じまとまりの業種の調査どうしで張る
- IndexNow は自社の枠のたびに sitemap の全URLを送っていた（変わっていないページも毎回）。
  中身（本文・題・説明文）が変わったページだけを送り、日付だけ動いたページは送らない
"""
import json
import re
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_fixed_page_descriptions_are_in_range():
    import faq_page
    import seo_audit as SA
    print("\n■ 固定ページの説明文も100〜160字（Ahrefs: /faq/ 76字・/about/ 161字）")
    check("faq_page.DESC", SA.DESC_MIN <= len(faq_page.DESC) <= SA.DESC_MAX, True)
    about = (ROOT / "site" / "about" / "index.html").read_text(encoding="utf-8")
    d = SA.page_facts(about)["desc"] or ""
    check("site/about の説明文", SA.DESC_MIN <= len(d) <= SA.DESC_MAX, True)
    og = re.search(r'<meta property="og:description" content="([^"]*)"', about)
    check("about の og:description も同じ長さの範囲", bool(og) and SA.DESC_MIN <= len(og.group(1)) <= SA.DESC_MAX, True)


def test_gate_stops_on_description_length():
    import seo_audit as SA
    src = (ROOT / "scripts" / "seo_audit.py").read_text(encoding="utf-8")
    gate = src.split("if a.gate:", 1)[1].split("if not a.live:", 1)[0]
    print("\n■ デプロイ直前の門は、説明文の長さの外れで止める（警告のままだと固定ページの外れが本番に出た）")
    check("門が説明文の長さを見る", "desc_stops(" in gate, True)
    page = '<html><head><meta name="description" content="{d}"></head><body><main>{ld}</main></body></html>'
    art = '<script type="application/ld+json">{"@type": "BlogPosting"}</script>'
    pages = {"/faq/": SA.page_facts(page.format(d="短い", ld="")),
             "/aio/x/": SA.page_facts(page.format(d="短い", ld=art))}
    rows = [("警告", "説明文が短すぎる", "/faq/", "2字"), ("警告", "説明文が短すぎる", "/aio/x/", "2字"),
            ("警告", "OGPが不完全", "/faq/", "")]
    check("固定・自動のページの外れだけ止める（記事は build.py の門が見る）",
          [r[2] for r in SA.desc_stops(rows, pages)], ["/faq/"])


def test_research_pages_link_each_other():
    import industry_ai_sources as IAS
    print("\n■ 業種別の調査は、同じまとまりの業種の調査へ張る（被リンク1本の23ページ）")
    live = IAS.live_inds()
    h = IAS.sibling_html("ec", live)
    check("同じまとまり（飲食・宿泊・買い物）へ張る", all(f"/research/{i}-ai-sources/" in h for i in ("hotel", "inshoku") if i in live), True)
    check("自分へは張らない", "/research/ec-ai-sources/" in h, False)
    check("集計の無い業種へは張らない", all(m in live for m in re.findall(r"/research/([a-z]+)-ai-sources/", h)), True)
    check("まとまりに無い業種でも空にしない", IAS.sibling_html("zz-none", live) != "" if live else True, True)
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    body = src.split("def build_research_pages", 1)[1].split("\ndef ", 1)[0]
    check("build.py が調査ページに入れる", "sibling_html(" in body, True)


def _page(main):
    return (f'<html><head><title>t</title><meta name="description" content="d"></head><body>'
            f'<header class="site-header">nav</header><main class="article">{main}</main><footer>f</footer></body></html>')


def test_indexnow_sends_only_changed_pages():
    import notify_indexnow as NI
    print("\n■ IndexNow は中身が変わったページだけを送る（日付だけ・CSS の版だけの変化は送らない）")
    a = NI.page_sig(_page('<p>本文A</p><time datetime="2026-10-30">2026年10月30日</time>'))
    check("日付だけの変化は同じ印", a, NI.page_sig(_page('<p>本文A</p><time datetime="2026-10-31">2026年10月31日</time>')))
    check("CSS の版の印だけの変化は同じ印", NI.page_sig(_page('<link href="/css/a.css?v=1"><p>本文A</p>')),
          NI.page_sig(_page('<link href="/css/a.css?v=2"><p>本文A</p>')))
    check("本文の変化は別の印", a != NI.page_sig(_page('<p>本文B</p><time>2026年10月30日</time>')), True)
    check("関連記事の並びの変化は送らない", NI.page_sig(_page('<p>本文A</p><section class="related"><a>X</a></section>')),
          NI.page_sig(_page('<p>本文A</p><section class="related"><a>Y</a></section>')))
    with tempfile.TemporaryDirectory() as td:
        site = Path(td)
        for p, body in (("", "トップ"), ("aio/x/", "記事X"), ("aio/y/", "記事Y")):
            (site / p).mkdir(parents=True, exist_ok=True)
            (site / p / "index.html").write_text(_page(body), encoding="utf-8")
        base = "https://ai.example"
        urls = [f"{base}/", f"{base}/aio/x/", f"{base}/aio/y/"]
        state = {}
        sigs = NI.local_sigs(site, base, urls)
        first = NI.fresh(sigs, state)
        check("初回は全部", first, urls)
        NI.remember(state, sigs, first)
        check("変わらなければ送らない", NI.fresh(NI.local_sigs(site, base, urls), state), [])
        (site / "aio/x/index.html").write_text(_page("記事X（書き直し）"), encoding="utf-8")
        check("書き直した1本だけ", NI.fresh(NI.local_sigs(site, base, urls), state), [f"{base}/aio/x/"])
        check("記録の鍵は URL をそのまま書かない（お客様のドメインを残さない）",
              any("example" in k for k in state), False)
    src = (ROOT / "scripts" / "notify_indexnow.py").read_text(encoding="utf-8")
    main = src.split("def main(", 1)[1]
    check("送れたときだけ記録する", main.find("remember(") > main.find("notify(urls"), True)
    check("記録は CI のキャッシュで持ち越し、公開側で追跡しない",
          "data/indexnow_sent.json" in (ROOT / ".gitignore").read_text(encoding="utf-8"), True)
    for wf in ("pipeline-multi.yml", "weekly-optimize.yml", "focus-mode.yml", "pipeline.yml"):
        y = (ROOT / ".github" / "workflows" / wf).read_text(encoding="utf-8")
        check(f"{wf} が送信の記録を持ち越す", "indexnow-sent-" in y and "data/indexnow_sent.json" in y, True)
