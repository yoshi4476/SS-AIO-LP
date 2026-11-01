# -*- coding: utf-8 -*-
"""補助金サイトの全ページで、入口（相談・診断・電話・メール・無料ツール）の押下と区画の到達を GA4 へ送る共通の計測。

なぜ: 2026-10 の日本からの訪問（ページの表示261・うち記事143）で記録された cta_click は7件だけだった。
- 記事の計測は cta_id に「ボタンの文字」を入れていたため、同じ文言が記事の途中にも末尾にもあると、どこで押されたか分からない
  （記録は「質問に答える」1件だけ）
- 会社概要・要項・制度別・業種別・一覧のページには、入口の押下を送る計測が無かった（会社概要は表示15）
- 記事には区画の到達の計測が無く、途中・末尾の案内が見られて押されなかったのか、見られていないのかが分からなかった
そこで、どのページにも同じ計測を置く（subsidy/pages.py の chrome() が配信のたびに当てる。何度当てても同じ）。

- cta_id は data-cta。無ければ「ページの種類_置き場所_行き先」（例: blog_mid_diag・about_body_tel）
- 区画の到達は section_view_<data-area-id か section の id>（トップと同じ名前の付け方）
- トップ・サービスのように自分で数えるページは、自分で数える要素のセレクタを window.ssCtaOwn に、区画の到達も
  自分で送るなら window.ssAreaOwn=true を置く（同じ押下を2回数えない）
- 著者欄の「AIにどう紹介されているか」の入口は、その場の小さな計測が送る（subsidy_cta.AICHECK_TRACK）ので数えない
"""
import re

JS = """<script id="ss-cta-js">
/* 入口の押下（cta_click）と区画の到達（section_view_*）を送る。補助金サイトの全ページ共通。
   管制塔の scripts/subsidy/cta_track.py が配信のたびに揃える。ここを直接直さない */
(function(){
var send=function(n,p){if(typeof gtag==="function")gtag("event",n,p||{});};
var kind=(location.pathname.split("/")[1]||"top").replace(/[^0-9A-Za-z]/g,"_").slice(0,12);
var to=function(h){
 if(/^tel:/.test(h))return "tel";
 if(/^mailto:/.test(h))return "mail";
 if(/#contact|#svcform|\\/contact/.test(h))return "contact";
 if(/#diagnosis|#shindan|[?&]diag=/.test(h))return "diag";
 if(/ai-check|url-check/.test(h))return "tool";
 return "";
};
var PLACE="[data-area-id],.cta-inline,.cta-mid,.bcta-mid,.cta-box,.author,.scta,.blog-sticky,.sticky-cta,.float-cta,.rel,header,footer,section[id]";
var NAMES=[["cta-inline","inline"],["cta-mid","mid"],["bcta-mid","mid"],["cta-box","box"],["author","author"],["scta","side"],
 ["blog-sticky","sticky"],["sticky-cta","sticky"],["float-cta","sticky"],["rel","related"]];
var place=function(a){
 var el=a.closest(PLACE);
 if(!el)return "body";
 if(el.hasAttribute("data-area-id"))return el.getAttribute("data-area-id");
 for(var i=0;i<NAMES.length;i++){if(el.classList.contains(NAMES[i][0]))return NAMES[i][1];}
 var t=el.tagName.toLowerCase();
 return t==="section"?el.id:t;
};
var SELF='a[data-cta^="subsidy_aicheck"]';
document.addEventListener("click",function(e){
 var a=e.target&&e.target.closest&&e.target.closest("a[href],button[data-cta]");
 if(!a||a.matches(SELF)||(window.ssCtaOwn&&a.matches(window.ssCtaOwn)))return;
 var h=a.getAttribute("href")||"",id=a.getAttribute("data-cta"),t=to(h);
 if(!id&&!t)return;
 send("cta_click",{cta_id:(id||(kind+"_"+place(a)+"_"+t)).replace(/[^0-9A-Za-z_]/g,"_").slice(0,60),
  link_url:h.slice(0,100),page_path:location.pathname});
},true);
var areas=function(){
 if(window.ssAreaOwn||!("IntersectionObserver" in window))return;
 var seen={},io=new IntersectionObserver(function(es){es.forEach(function(x){
  var id=(x.target.getAttribute("data-area-id")||x.target.id||"").replace(/[^0-9A-Za-z_]/g,"_");
  if(x.isIntersecting&&id&&!seen[id]){seen[id]=1;send("section_view_"+id,{page_path:location.pathname});io.unobserve(x.target);}
 });},{threshold:.25});
 document.querySelectorAll("[data-area-id],main section[id]").forEach(function(el){io.observe(el);});
};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",areas);else areas();
})();
</script>"""

BLOCK = re.compile(r'<script id="ss-cta-js">.*?</script>', re.S)
# 記事の雛形（補助金サイトの blog/_template.html）から来た古い計測。cta_id にボタンの文字を入れていた。共通の計測に置き換える
GA_LOAD = "window.addEventListener('load',function(){"
GA_BARE = re.compile(re.escape(GA_LOAD) + r"(?=setTimeout\(function\(\)\{var s=document\.createElement\('script'\))")
OLD_ARTICLE = re.compile(r"<script>\s*/\* 記事本文のCTAクリックをGA4へ送る。.*?</script>\r?\n?", re.S)

# 記事の案内の区画（到達を数え、押下の置き場所の名前にもなる）。開始タグに data-area を足すだけ。何度当てても同じ
ARTICLE_AREAS = (
    ('<aside class="cta-inline"', "記事の冒頭の診断の案内", "art_inline"),
    ('<div class="cta-mid"', "記事の途中の案内", "art_mid"),
    ('<aside class="bcta-mid"', "記事の途中の案内（業種）", "art_mid2"),
    ('<section class="faq-sec"', "よくある質問", "art_faq"),
    ('<div class="author"', "監修者", "art_author"),
)


def mark_areas(html):
    """記事の案内・FAQ・監修者の欄に data-area を付ける。本文の中の cta-box は art_box、FAQ の後の締めの案内は art_end"""
    for tag, label, aid in ARTICLE_AREAS:
        if f'data-area-id="{aid}"' not in html:
            html = re.sub(re.escape(tag) + r"(?=[\s>])", lambda _: f'{tag} data-area="{label}" data-area-id="{aid}"', html)
    if 'class="cta-box">' in html:
        faq = html.find('<section class="faq-sec"')
        out, pos = [], 0
        for m in re.finditer(r'<div class="cta-box">', html):
            end = faq >= 0 and m.start() > faq
            out.append(html[pos:m.start()])
            out.append('<div class="cta-box" data-area="{}" data-area-id="{}">'.format(
                *(("記事の締めの案内", "art_end") if end else ("本文の中の案内", "art_box"))))
            pos = m.end()
        html = "".join(out) + html[pos:]
    return html


def apply(text):
    """1ページに共通の計測を置く（古い記事の計測は外す）。</body> の無いページは触らない。何度当てても同じ"""
    if "</body>" not in text:
        return text
    nl = "\r\n" if "\r\n" in text else "\n"
    js = JS.replace("\n", nl)
    # 自動操作中のブラウザでは計測タグを読まない（ab738d5ac で pages.py の雛形だけに入れ、手書きのトップ・記事・会社概要は
    # 読んだままだった。10月のトップは訪問227のうち176がアメリカの機械の訪問）
    t = GA_BARE.sub(lambda _: GA_LOAD + "if(navigator.webdriver)return;", OLD_ARTICLE.sub("", text))
    if BLOCK.search(t):
        return BLOCK.sub(lambda _: js, t, count=1)
    i = t.rfind("</body>")
    return t[:i] + js + nl + t[i:]
