# -*- coding: utf-8 -*-
"""2026-10 の補助金サイト（日本からの表示261・うち記事143）で、記録された入口の押下（cta_click）は7件だった。
1. 記事の計測は cta_id に「ボタンの文字」を入れ、同じ文言が途中にも末尾にもあると置き場所が分からなかった
2. 会社概要・要項・制度別・業種別・一覧には押下の計測が無く、記事には区画の到達の計測が無かった
3. 手書きのトップ・記事・会社概要は、自動操作中のブラウザでも計測タグを読んでいた（ab738d5ac は雛形だけ）
4. 記事142本のうち79本は題が別の制度なのに、相談のボタンが「AI導入補助金の無料相談」だった。
   207か所のボタンが同じサイトの入力欄を新しいタブで開き、冒頭の案内のボタンは「質問に答える」だった
ページは架空の短い HTML で確かめる（補助金サイトの作業コピーは読まない）。
"""
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "subsidy"))

GA = ("<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());"
      "window.addEventListener('load',function(){setTimeout(function(){var s=document.createElement('script');s.async=true;"
      "s.src='https://www.googletagmanager.com/gtag/js?id=G-ZZ';document.head.appendChild(s);},1200);});</script>")
OLD = ("<script>\n/* 記事本文のCTAクリックをGA4へ送る。\n   これが無いと、記事から診断・相談へ何人動いたかが分からない。 */\n"
       "document.addEventListener('click', function (e) {\n  gtag('event', 'cta_click', {cta_id: (a.textContent || '').trim()});\n"
       "}, true);\n</script>\n")


def test_common_tracker_is_placed_once():
    import cta_track as CT
    page = f"<html><head>{GA}</head><body><main><p>本文</p></main>\n{OLD}</body></html>"
    out = CT.apply(page)
    check("古い記事の計測（cta_id がボタンの文字）を外し、共通の計測を1つだけ置く",
          ("記事本文のCTAクリック" in out, out.count('<script id="ss-cta-js">'), out.index("ss-cta-js") < out.index("</body>")),
          (False, 1, True))
    check("自動操作中のブラウザでは計測タグを読まない（1回だけ足す）",
          out.count("if(navigator.webdriver)return;"), 1)
    check("何度当てても同じ", CT.apply(out), out)
    crlf = CT.apply(page.replace("\n", "\r\n"))
    check("改行が CRLF のページは CRLF のまま", ("\r\n" in crlf, "\n" in crlf.replace("\r\n", "")), (True, False))
    check("</body> の無い断片は触らない", CT.apply("<p>x</p>"), "<p>x</p>")


def test_common_tracker_names_place_and_skips_own():
    import cta_track as CT
    js = CT.JS
    check("cta_id は data-cta、無ければ「ページの種類_置き場所_行き先」",
          ('id=a.getAttribute("data-cta")' in js, '(id||(kind+"_"+place(a)+"_"+t))' in js), (True, True))
    check("行き先は電話・メール・相談・診断・無料ツールで、それ以外のリンクは数えない（押下率を水増ししない）",
          all(w in js for w in ('"tel"', '"mail"', '"contact"', '"diag"', '"tool"', "if(!id&&!t)return;")), True)
    check("自分で数えるページ（window.ssCtaOwn）と、著者欄の小さな計測が送る入口は数えない（2回数えない）",
          ("window.ssCtaOwn&&a.matches(window.ssCtaOwn)" in js, 'a[data-cta^="subsidy_aicheck"]' in js), (True, True))
    check("区画の到達は data-area-id か section の id で送り、自分で送るページ（ssAreaOwn）では送らない",
          ('"section_view_"+id' in js, "window.ssAreaOwn" in js, "[data-area-id],main section[id]" in js), (True, True, True))
    import funnel as F
    got = {k: F.contact_bound(k) for k in ("blog_art_box_contact", "blog_art_end_diag", "about_body_tel",
                                           "seido_header_mail", "blog_side_tool")}
    check("名付けた cta_id は、ファネルの「問い合わせ方向」の判定でそのまま読める",
          got, {"blog_art_box_contact": True, "blog_art_end_diag": False, "about_body_tel": True,
                "seido_header_mail": True, "blog_side_tool": False})


def test_article_areas_are_marked():
    import cta_track as CT
    art = ('<article><aside class="cta-inline" data-tool="q"><a href="/#diagnosis">x</a></aside>'
           '<div class="cta-mid" style="a"><a>m</a></div><div class="cta-box"><p>a</p><a href="/#contact">c</a></div></article>'
           '<section class="faq-sec"><h2>Q</h2></section>\n<div class="cta-box">\n<a href="/#diagnosis">e</a></div>'
           '<div class="author"><div class="sv-links"></div></div>')
    out = CT.mark_areas(art)
    ids = re.findall(r'data-area-id="([^"]+)"', out)
    check("冒頭・途中・本文の中・FAQ・締め・監修者の欄に、上から順に区画の印が付く",
          ids, ["art_inline", "art_mid", "art_box", "art_faq", "art_end", "art_author"])
    check("開始タグに印を足すだけ（ほかの属性と中身は変えない）",
          re.sub(r' data-area="[^"]*" data-area-id="[^"]*"', "", out), art)
    check("何度当てても同じ", CT.mark_areas(out), out)


def test_pages_wire_the_tracker():
    src = (ROOT / "scripts" / "subsidy" / "pages.py").read_text(encoding="utf-8")
    check("毎回の配信（chrome）が共通の計測を全ページに当て、記事だけに区画の印を付ける",
          ("u = CT.apply(u)" in src, 'p.parent.parent.name == "blog"' in src and "CT.mark_areas(u)" in src), (True, True))
    check("ナビは入口（無料診断）だけに data-cta を付ける",
          ('data-cta="nav_diag"\' if href == "/#diagnosis"' in src), True)

def test_article_cta_fits_the_topic():
    import subsidy_cta as C
    btn = '<a class="cta-button" href="https://lp.7senses.co.jp/#contact">AI導入補助金の無料相談</a>'
    blank = ('<a href="https://lp.7senses.co.jp/#contact" class="cta-button" target="_blank" rel="noopener">'
             'AI導入補助金の無料相談はこちら</a>')
    ext = '<a href="https://example.com/" target="_blank" rel="noopener">外</a>'
    inline = '<a class="cta-button" href="https://lp.7senses.co.jp/#diagnosis" data-cta="article_inline_hojokin_quiz">質問に答える</a>'
    farm = f"<h1>農業の補助金は返済不要？</h1>{btn}{blank}{ext}{inline}"
    out = C.fit_cta(farm)
    check("題が別の制度の記事は、相談のボタンを「補助金の無料相談」にする",
          (out.count(">補助金の無料相談</a>"), "AI導入補助金の無料相談" in out), (2, False))
    check("同じサイトの入口は同じタブで開く（外のサイトは新しいタブのまま）",
          (out.count('target="_blank"'), ext in out), (1, True))
    check("冒頭の案内のボタンは押した後が分かる文言にする", ">無料の8問診断を始める</a>" in out, True)
    ai = C.fit_cta(f"<h1>AI導入補助金の不採択理由</h1>{btn}")
    check("AI導入補助金の記事の相談のボタンはそのまま", btn in ai, True)
    check("何度当てても同じ", (C.fit_cta(out), C.fit_cta(ai)), (out, ai))
