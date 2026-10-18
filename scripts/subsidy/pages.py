# -*- coding: utf-8 -*-
"""ブログ一覧・カテゴリ別一覧(4種)・sitemap.xml を記事ファイルから自動生成
   再実行可能: 記事が増えたらこのスクリプトを再実行するだけで全一覧が更新される
   あわせて、全ページのヘッダー（ナビ）・トップの最新記事・フッターの制作表記を揃える"""
import os, sys, io, re, html
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(1, str(Path(__file__).resolve().parents[1]))
import photo_match  # noqa: E402
import desc_fill as DF  # noqa: E402
import footer_credit  # noqa: E402
import social_footer as SF  # noqa: E402
import noindex as NI  # noqa: E402
import turnstile_block as TB  # noqa: E402  ロボットよけ（管制塔へ直接送るフォーム）

# 補助金サイトの作業コピー。管制塔の publish.py が SUBSIDY_ROOT で渡す
# （2026-10-03 まで補助金サイト側の tools/ で CI が動かしていた。管制塔に一本化）
ROOT = Path(os.environ.get("SUBSIDY_ROOT") or Path(__file__).resolve().parents[2] / ".publish-work" / "subsidy")
DOMAIN = "https://lp.7senses.co.jp"

# ---- 全ページ共通のヘッダー ----
# トップにだけナビがあり、記事・制度・サービスのヘッダーはロゴと「無料で相談する」だけで、スマホにはメニューも無かった。
# 比較・用語集・調査のページはどこからもたどれなかった（2026-10-07 の点検）。ナビはここの1か所に置き、
# 配信のたびに配信先の全ページ（手書きのトップ・固定ページ・記事と比較などの雛形・記事）へ揃える（sync_chrome）
NAV = [
    ("サービス", "/#services", [("補助金申請サポート", "/service/hojokin/"), ("システム開発・AI導入", "/service/dev/"),
                               ("AIOコンサルティング", "/service/aio/"), ("MEOコンサルティング", "/service/meo/")]),
    ("補助金要項", "/youkou/", []),
    ("記事・資料", "/blog/", [("AI導入補助金ブログ", "/blog/"), ("制度から探す", "/seido/"), ("業種から探す", "/industry/"),
                            ("テーマから探す", "/topics/"), ("比較表", "/compare/"), ("用語集", "/glossary/"),
                            ("AIへの聞き取り調査", "/research/ai-hojokin/")]),
    ("事例", "/#cases", []),
    ("無料診断", "/#diagnosis", []),
    ("会社概要", "/about/", []),
    ("FAQ", "/#faq", []),
]
NAV_EXT = [("コーポレートサイト", "https://corp.7senses.co.jp/"), ("AI集客ラボ", "https://ai.7senses.co.jp/")]
TEL_SVG = ('<svg width="17" height="17" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a13 13 0 005 5L15 13l5 2v4'
           'a2 2 0 01-2 2A16 16 0 013 6a2 2 0 012-2z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>')

CHROME_CSS = """<style id="ss-common">
/* サイト共通の土台（色・文字・ヘッダー・足元・ボタン・差し込みの部品）。決まりは補助金サイトの DESIGN.md。
   管制塔の scripts/subsidy/pages.py が配信のたびに全ページへ揃える。ここを直接直さない。
   土台（ss-base の層）はページごとの CSS より弱く、ヘッダー・足元・差し込みの部品は層の外に置いてページより強くする */
@font-face{font-family:"YuGothicM";src:local("Yu Gothic Medium"),local("YuGothic-Medium");font-weight:400}
@font-face{font-family:"YuGothicM";src:local("Yu Gothic Bold"),local("YuGothic-Bold");font-weight:700}
:root{
--paper:#fff;--sheet:#f3f5f1;--ink:#1a2230;--ink-2:#4d5666;--ink-3:#616a79;
--ai:#233f7c;--ai-deep:#172c59;--ai-tint:#e9eef7;--rule:#d5dad2;--rule-strong:#9aa3a0;
--shu:#b3402a;--shu-tint:#fbefea;--marker:#ffeb99;
--font:"BIZ UDPGothic","Hiragino Kaku Gothic ProN","Hiragino Sans","YuGothicM","Yu Gothic","Noto Sans JP","Noto Sans CJK JP",Meiryo,sans-serif;
--fs-12:12px;--fs-14:14px;--fs-16:16px;--fs-18:18px;--fs-22:22px;--fs-28:clamp(24px,3vw,30px);--fs-display:clamp(30px,5vw,50px);
--s-4:4px;--s-8:8px;--s-12:12px;--s-16:16px;--s-24:24px;--s-32:32px;--s-48:48px;--s-64:64px;--s-96:96px;
--r-sm:4px;--r-md:8px;--shadow-float:0 12px 32px -12px rgb(26 34 48 / .28);
--ease-out:cubic-bezier(.23,1,.32,1);--maxw:1160px;--gutter:24px;
/* 旧来の名前（管制塔が差し込む部品が使う）。新しい色に向けておく。新しく書く CSS では使わない */
--bg:var(--paper);--bg2:var(--sheet);--panel:var(--paper);--panel2:var(--sheet);--line:var(--rule);--line2:var(--rule-strong);
--text:var(--ink);--muted:var(--ink-2);--dim:var(--ink-3);--navy:var(--ink);--navy2:var(--ai);--navy-deep:var(--ai-deep);
--gold:var(--ai);--gold-strong:var(--ai);--gold-em:var(--ink);--gold-soft:var(--ai);--gold-pale:var(--ai-tint);--gold-ink:var(--ink);
--serif:var(--font);--sans:var(--font);--num:var(--font);--radius:var(--r-md);--shadow:none}
@media(max-width:600px){:root{--gutter:16px}}
@layer ss-base{
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-top:80px}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--font);font-size:var(--fs-16);line-height:1.9;-webkit-font-smoothing:antialiased;overflow-wrap:anywhere}
h1,h2,h3,h4{font-family:var(--font);font-weight:700;color:var(--ink);letter-spacing:.01em;text-wrap:pretty;word-break:auto-phrase}
h1{font-size:var(--fs-display);line-height:1.3}
h2{font-size:var(--fs-28);line-height:1.45}
h3{font-size:var(--fs-22);line-height:1.5}
p,ul,ol,dl,figure{margin-top:0}
img{max-width:100%;height:auto}
a{color:var(--ai);text-underline-offset:3px;text-decoration-thickness:1px}
a:hover{text-decoration-thickness:2px}
b,strong{font-weight:700}
table{border-collapse:collapse}
.num,time,td,.tnum{font-variant-numeric:tabular-nums}
::selection{background:var(--marker);color:var(--ink)}
:focus-visible{outline:2px solid var(--ai);outline-offset:3px;border-radius:2px}
}
/* ---- ヘッダー ---- */
.gh{position:sticky;top:0;z-index:50;background:var(--paper);border-bottom:1px solid var(--rule)}
.gh-in{max-width:1360px;margin:0 auto;padding:0 var(--gutter);height:64px;display:flex;align-items:center;justify-content:space-between;gap:16px}
.gh-logo{flex:none;display:block;line-height:0}
.gh-logo img{display:block;height:36px;width:auto;max-width:none}
.gh-nav{min-width:0}
.gh .gh-list,.gh .gh-sub{list-style:none;margin:0;padding:0}
.gh .gh-list li{margin:0}
.gh-list{display:flex;align-items:center;gap:20px}
.gh-list>li{position:relative}
.gh-list a{display:inline-block;padding:10px 0;font-size:14px;line-height:1.5;font-weight:400;color:var(--ink-2);text-decoration:none;white-space:nowrap;transition:color .15s}
.gh-list a:hover,.gh-list a:focus-visible{color:var(--ink);text-decoration:underline;text-underline-offset:6px}
.gh-has>a::after{content:"";display:inline-block;width:5px;height:5px;margin:0 0 3px 7px;border:solid currentColor;border-width:0 1.5px 1.5px 0;transform:rotate(45deg)}
.gh-sub{position:absolute;top:100%;left:-16px;z-index:70;display:grid;gap:0;min-width:236px;padding:6px;background:var(--paper);border:1px solid var(--rule);border-radius:var(--r-md);box-shadow:var(--shadow-float);opacity:0;visibility:hidden;transform:translateY(4px);transition:opacity .16s var(--ease-out),transform .16s var(--ease-out),visibility 0s .16s}
.gh-has:hover>.gh-sub,.gh-has:focus-within>.gh-sub{opacity:1;visibility:visible;transform:none;transition:opacity .16s var(--ease-out),transform .16s var(--ease-out),visibility 0s}
.gh-sub a{display:block;padding:9px 12px;border-radius:var(--r-sm);color:var(--ink)}
.gh-sub a:hover,.gh-sub a:focus-visible{background:var(--sheet);color:var(--ink);text-decoration:none}
.gh-tel{flex:none;display:inline-flex;align-items:center;gap:7px;min-height:44px;padding:6px 4px;color:var(--ink);text-decoration:none;white-space:nowrap}
.gh-tel:hover b{text-decoration:underline;text-underline-offset:4px}
.gh-tel b{font-size:17px;font-weight:700;letter-spacing:.02em;font-variant-numeric:tabular-nums}
.gh-tel small{font-size:12px;color:var(--ink-3)}
.gh-cta{flex:none;display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:8px 20px;border-radius:var(--r-sm);background:var(--ai);color:#fff;font-size:14px;font-weight:700;line-height:1.4;text-decoration:none;white-space:nowrap;transition:background-color .15s,transform .12s var(--ease-out)}
.gh-cta:hover{background:var(--ai-deep);color:#fff}
.gh-cta:active{transform:scale(.97)}
.gh-menu{display:none}
@media(max-width:1479px){.gh-list .gh-ext{display:none}}
@media(max-width:1199px){.gh-list{gap:14px}.gh-list a{font-size:13.5px}.gh-tel small{display:none}}
@media(max-width:1079px){
 .gh-in{height:60px;gap:8px}
 .gh-logo{margin-right:auto}
 .gh-logo img{height:32px}
 .gh-nav{display:none;position:absolute;left:0;right:0;top:100%;max-height:calc(100vh - 60px);overflow-y:auto;padding:4px var(--gutter) 24px;background:var(--paper);border-bottom:1px solid var(--rule);box-shadow:var(--shadow-float)}
 .gh.gh-open .gh-nav{display:block}
 .gh-list{display:block}
 .gh-list>li{border-bottom:1px solid var(--rule)}
 .gh-list a{display:block;padding:13px 0;font-size:16px;color:var(--ink)}
 .gh-has>a::after{content:none}
 .gh-sub{position:static;opacity:1;visibility:visible;transform:none;transition:none;min-width:0;padding:0 0 10px 14px;background:none;border:0;border-radius:0;box-shadow:none}
 .gh-sub a{padding:9px 0;font-size:15px;color:var(--ink-2)}
 .gh-list .gh-ext{display:block}
 .gh-tel{width:44px;height:44px;padding:0;justify-content:center;border:1.5px solid var(--ai);border-radius:var(--r-sm);color:var(--ai)}
 .gh-tel b,.gh-tel small{display:none}
 .gh-cta{padding:8px 14px;font-size:13.5px}
 .gh-menu{flex:none;display:inline-flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;width:52px;height:44px;padding:0;border:0;border-radius:var(--r-sm);background:none;color:var(--ink);font:inherit;font-size:12px;font-weight:700;line-height:1;cursor:pointer}
 .gh-bars,.gh-bars::before,.gh-bars::after{content:"";display:block;width:22px;height:2px;border-radius:1px;background:currentColor;transition:transform .2s var(--ease-out)}
 .gh-bars{position:relative;margin:6px 0 5px}
 .gh-bars::before,.gh-bars::after{position:absolute;left:0}
 .gh-bars::before{top:-7px}
 .gh-bars::after{top:7px}
 .gh-open .gh-bars{background:transparent}
 .gh-open .gh-bars::before{top:0;transform:rotate(45deg)}
 .gh-open .gh-bars::after{top:0;transform:rotate(-45deg)}
 .gh-lock .sticky-cta,.gh-lock .blog-sticky,.gh-lock .float-cta{visibility:hidden}
}
@media(max-width:420px){.gh-in{padding:0 12px}.gh-cta{padding:8px 12px}}
@media(max-width:389px){.gh-long{display:none}}
/* ---- ボタン（藍の地・角丸4px。丸い金のボタンはやめた） ---- */
.btn,.btn-gold,.btn-line{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;padding:12px 24px;border-radius:var(--r-sm);border:1.5px solid transparent;font-family:var(--font);font-size:15px;font-weight:700;line-height:1.5;text-align:center;text-decoration:none;cursor:pointer;box-shadow:none;transition:background-color .15s,border-color .15s,color .15s,transform .12s var(--ease-out)}
.btn:active,.btn-gold:active,.btn-line:active{transform:scale(.97)}
.btn-primary,.btn-gold{background:var(--ai);color:#fff}
.btn-primary:hover,.btn-gold:hover{background:var(--ai-deep);color:#fff;transform:none;box-shadow:none}
.btn-primary::after{content:none}
.btn-ghost,.btn-line{background:var(--paper);border-color:var(--ai);color:var(--ai)}
.btn-ghost:hover,.btn-line:hover{background:var(--ai-tint);color:var(--ai-deep)}
.btn-block{display:flex;width:100%}
.btn[disabled],button[disabled]{opacity:.6;cursor:progress}
/* ---- 文字の部品 ---- */
.em-marker{background:linear-gradient(transparent 58%,var(--marker) 58%);color:var(--ink);font-weight:700;padding:0 1px}
.micro{display:block;margin-top:8px;font-size:var(--fs-14);line-height:1.7;color:var(--ink-3)}
.table-note,.cost-note,.case-note,.plan-note{font-size:var(--fs-14);line-height:1.7;color:var(--ink-3)}
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}
/* ---- 足元（どのページも同じ見た目） ---- */
body>footer{background:var(--sheet);border-top:1px solid var(--rule);color:var(--ink-2);font-size:var(--fs-14);line-height:1.8;padding:56px max(var(--gutter),calc((100% - var(--maxw)) / 2 + var(--gutter))) 40px;text-align:left}
body>footer .wrap{padding:0}
body>footer nav{display:flex;flex-wrap:wrap;align-content:flex-start;gap:0 18px;margin-bottom:14px}

body>footer nav a,body>footer a{color:var(--ink-2);text-decoration:none;margin:0}
body>footer a:hover{color:var(--ink);text-decoration:underline}
footer nav a[href]{display:inline-block;padding:.55rem 0}
body>footer p{margin:6px 0 0}
body>footer .foot-grid{display:flex;flex-wrap:wrap;justify-content:space-between;gap:28px}
body>footer .foot-grid nav{max-width:640px}
body>footer .copyright{margin-top:24px}
body>footer .social-links{justify-content:flex-start;margin-top:16px}
@media(max-width:860px){body>footer{padding-bottom:104px}}
/* ---- スマホの下の固定ボタン（入力欄・診断が見えている間と入力中は引っ込める） ---- */
.sticky-cta{position:fixed;left:0;right:0;bottom:0;z-index:60;display:none;gap:8px;padding:8px 12px calc(8px + env(safe-area-inset-bottom,0px));background:var(--paper);border-top:1px solid var(--rule);box-shadow:var(--shadow-float);transition:transform .25s var(--ease-out),opacity .25s var(--ease-out)}
.sticky-cta .btn{flex:1;min-width:0;min-height:48px;padding:6px 8px;font-size:13.5px;line-height:1.35}
@media(max-width:860px){.sticky-cta{display:flex}}
.sticky-cta.is-hidden{transform:translateY(110%);opacity:0;pointer-events:none}
.float-cta{position:fixed;right:24px;bottom:24px;z-index:65;display:none;align-items:center;gap:6px;opacity:0;transform:translateY(8px);pointer-events:none;transition:opacity .2s var(--ease-out),transform .2s var(--ease-out)}
.float-cta.show{opacity:1;transform:none;pointer-events:auto}
@media(min-width:861px){.float-cta{display:flex}}
.float-cta a{display:inline-flex;align-items:center;gap:8px;min-height:48px;padding:12px 20px;border-radius:var(--r-sm);background:var(--ai);color:#fff;font-size:14px;font-weight:700;text-decoration:none;box-shadow:var(--shadow-float)}
.float-cta a:hover{background:var(--ai-deep)}
.float-cta .fdot{display:none}
.float-cta button{width:32px;height:32px;border:1px solid var(--rule);border-radius:var(--r-sm);background:var(--paper);color:var(--ink-2);font-size:13px;line-height:1;cursor:pointer}
/* ---- 記事に差し込まれる案内（管制塔の publish.py・subsidy_cta.py が書く。style 属性の色をここで揃える） ---- */
.bcta-mid,.cta-mid{margin:40px 0!important;padding:20px 22px!important;background:var(--sheet)!important;border:0!important;border-top:2px solid var(--ai)!important;border-radius:0!important;text-align:left!important}
.bcta-mid .t,.cta-mid>p:first-child{margin:0 0 6px!important;font-size:var(--fs-18);font-weight:700;line-height:1.6;color:var(--ink)}
.bcta-mid .d,.cta-mid>p:last-child{margin:8px 0 0!important;font-size:var(--fs-14)!important;line-height:1.7;color:var(--ink-3)!important}
.bcta-mid a,.cta-mid a.cta-button,.cta-inline a.cta-button,.blog-sticky a{display:inline-flex!important;align-items:center;justify-content:center;min-height:48px;padding:11px 22px!important;border-radius:var(--r-sm)!important;background:var(--ai)!important;color:#fff!important;font-size:15px;font-weight:700;line-height:1.5;text-decoration:none;transition:background-color .15s,transform .12s var(--ease-out)}
.bcta-mid a:hover,.cta-mid a.cta-button:hover,.cta-inline a.cta-button:hover{background:var(--ai-deep)!important}
.bcta-mid a:active,.cta-mid a.cta-button:active,.cta-inline a.cta-button:active{transform:scale(.97)}
.cta-inline{margin:28px 0 32px!important;padding:18px 20px!important;background:var(--paper)!important;border:1px solid var(--rule)!important;border-left:3px solid var(--ai)!important;border-radius:0!important}
.cta-inline>p{color:var(--ink)!important}
.cta-inline>p+a+p,.cta-inline p:last-of-type{color:var(--ink-3)!important}
.blog-sticky{background:var(--paper)!important;border-top:1px solid var(--rule);box-shadow:var(--shadow-float)!important}
.blog-sticky a{display:flex!important;width:100%}
aside:has(>a[data-cta^="subsidy_aicheck"]),.author aside,.diag+aside{max-width:none!important;margin:24px 0 0!important;padding:16px 18px!important;border:1px solid var(--rule)!important;border-radius:0!important;background:var(--paper)!important;font-size:var(--fs-14)!important}
main>aside:has(>a[data-cta^="subsidy_aicheck"]){max-width:calc(880px - 2 * var(--gutter))!important;margin:32px auto 0!important}
@media(max-width:880px){main>aside:has(>a[data-cta^="subsidy_aicheck"]){margin:32px var(--gutter) 0!important}}

aside:has(>a[data-cta^="subsidy_aicheck"]) b,.author aside b{color:var(--ink)!important}
/* 写真の注記（※ 写真はイメージです） */
figure.ph-band figcaption{font-size:var(--fs-12);color:var(--ink-3)}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important;scroll-behavior:auto!important}}
</style>"""

CHROME_JS = """<script id="ss-common-js">
/* サイト共通の枠（管制塔の scripts/subsidy/pages.py が揃える）: スマホのメニューの開閉と、下の固定ボタンを引っ込める */
(function(){
var h=document.getElementById("gh"),b=h&&h.querySelector(".gh-menu"),t=b&&b.querySelector(".gh-menu-t");
if(b){
 var set=function(o){h.classList.toggle("gh-open",o);document.documentElement.classList.toggle("gh-lock",o);b.setAttribute("aria-expanded",o?"true":"false");if(t)t.textContent=o?"閉じる":"メニュー";};
 b.addEventListener("click",function(){set(!h.classList.contains("gh-open"));});
 h.querySelector(".gh-nav").addEventListener("click",function(e){if(e.target.closest("a"))set(false);});
 document.addEventListener("keydown",function(e){if(e.key==="Escape"&&h.classList.contains("gh-open")){set(false);b.focus();}});
 addEventListener("pageshow",function(e){if(e.persisted)set(false);});
}
var bar=document.querySelector(".sticky-cta");
if(bar){
 var seen=[],typing=false,isField=function(el){return !!(el&&el.matches&&el.matches("input,textarea,select"));};
 var upd=function(){var hide=seen.length>0||typing;bar.classList.toggle("is-hidden",hide);bar.inert=hide;};
 if("IntersectionObserver" in window){
  var io=new IntersectionObserver(function(es){es.forEach(function(e){var i=seen.indexOf(e.target);if(e.isIntersecting&&i<0)seen.push(e.target);if(!e.isIntersecting&&i>=0)seen.splice(i,1);});upd();});
  document.querySelectorAll("main form, .diag").forEach(function(el){io.observe(el);});
 }
 document.addEventListener("focusin",function(e){if(isField(e.target)){typing=true;upd();}});
 document.addEventListener("focusout",function(){setTimeout(function(){typing=isField(document.activeElement);upd();},0);});
}
})();
/* 最初に来たときの流入元（参照元のドメイン・utm・広告のクリック）と最初に見たページを180日覚え、相談・診断の送信に添える
   （ssTs.send が足す。4サイト共通の形。管制塔の台帳の送信元ページに「流入: …｜入口: …｜送信: …」と入る）。
   覚えられないときはこのページを開いた時点の値を送る。どちらでも送信は止めない */
(function(){
var KEY="ss_first",cur=null;
try{cur=JSON.parse(localStorage.getItem(KEY)||"null");}catch(e){cur=null;}
if(!cur||!(Date.now()-cur.t<180*864e5)){
 var q=new URLSearchParams(location.search),ref="";
 try{ref=document.referrer?new URL(document.referrer).hostname:"";}catch(e){ref="";}
 var utm=["utm_source","utm_medium","utm_campaign"].map(function(k){return (q.get(k)||"").slice(0,60);});
 cur={r:ref,u:utm.join("")?utm.join("|"):"",a:q.get("gclid")?"gclid":"",l:location.pathname.slice(0,150),t:Date.now()};
 try{localStorage.setItem(KEY,JSON.stringify(cur));}catch(e){}
}
window.ssFirst=function(){
 var d=new Date(cur.t),p=function(n){return ("0"+n).slice(-2);};
 return {first_ref:cur.r||"",first_utm:cur.u||"",first_ad:cur.a||"",first_land:cur.l||"",
  first_at:d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate()),send_page:location.pathname.slice(0,150)};
};
})();
</script>"""


def _live(root, href):
    """ナビに出すページが配信先にあるか（無いページへ送らない。ページ内の場所・外のサイトはそのまま出す）"""
    if not href.startswith("/") or "#" in href:
        return True
    p = href.strip("/")
    return not p or (root / p / "index.html").is_file()


def nav_html(root, cta="/#contact"):
    """全ページ共通のヘッダー。cta は「無料で相談する」の行き先（ページ内に相談の入力欄があるページはそこへ）"""
    items = []
    for label, href, sub in NAV:
        sub = [(l, h) for l, h in sub if _live(root, h)]
        if sub:
            lis = "".join(f'<li><a href="{h}">{l}</a></li>' for l, h in sub)
            items.append(f'<li class="gh-has"><a href="{href}">{label}</a><ul class="gh-sub">{lis}</ul></li>')
        elif _live(root, href):
            items.append(f'<li><a href="{href}">{label}</a></li>')
    items += [f'<li class="gh-ext"><a href="{h}" target="_blank" rel="noopener">{l}</a></li>' for l, h in NAV_EXT]
    return ('<header class="gh" id="gh">\n'
            '  <div class="gh-in">\n'
            '    <a class="gh-logo" href="/"><img src="/assets/img/logo-h.webp" alt="SEVEN SENSES セブンセンシズ株式会社" width="372" height="148"></a>\n'
            '    <nav class="gh-nav" id="gh-nav" aria-label="サイト内のメニュー"><ul class="gh-list">' + "".join(items) + '</ul></nav>\n'
            '    <a class="gh-tel" href="tel:0643057547" data-cta="tel_header" aria-label="電話で相談する 06-4305-7547 受付は平日9時から20時">'
            + TEL_SVG + '<b>06-4305-7547</b><small>9〜20時</small></a>\n'
            f'    <a class="gh-cta" href="{cta}" data-cta="header">無料<span class="gh-long">で</span>相談<span class="gh-long">する</span></a>\n'
            '    <button class="gh-menu" type="button" aria-expanded="false" aria-controls="gh-nav"><span class="gh-bars" aria-hidden="true"></span>'
            '<span class="gh-menu-t">メニュー</span></button>\n'
            '  </div>\n'
            '</header>')


SKIP_DIRS = {".git", "node_modules", "dist", "blog-system", "automation", "reports"}
HEADER_RX = re.compile(r"<header\b[^>]*>.*?</header>", re.S)


def chrome(text, root):
    """1ページのヘッダー・共通の CSS・共通の動きを揃える。旧来のヘッダー（ロゴと相談ボタンだけ）も置き換える。
    ヘッダーの無いページ・知らない形のヘッダーは触らない。何度当てても同じ結果"""
    m = HEADER_RX.search(text)
    if not m or not ('class="nav"' in m.group(0) or 'id="gh"' in m.group(0)):
        return text
    nl = "\r\n" if "\r\n" in text else "\n"
    put = lambda s: s.replace("\n", nl)
    cta = "#svcform" if 'id="svcform"' in text else "/#contact"
    u = text[:m.start()] + put(nav_html(root, cta)) + text[m.end():]
    for rx, block, anchor in ((r'<style id="ss-common">.*?</style>', CHROME_CSS, "</head>"),
                              (r'<script id="ss-common-js">.*?</script>', CHROME_JS, "</body>")):
        if re.search(rx, u, re.S):
            u = re.sub(rx, lambda _: put(block), u, count=1, flags=re.S)
        elif anchor in u:
            u = u.replace(anchor, put(block) + nl + anchor, 1)
    # 足元のアイコンは明るい足元の色に（暗い面用の白い輪郭のままだと地の色と 1.1:1 で見えなかった。色は social_footer に1か所）
    return SF.fix_style(u, "subsidy", nl)


def sync_chrome(root):
    """配信先の全ページへ共通のヘッダーを揃える。揃えたページ数を返す"""
    n = 0
    for p in sorted(Path(root).rglob("*.html")):
        if SKIP_DIRS & set(p.relative_to(root).parts):
            continue
        t = p.read_bytes().decode("utf-8", "surrogateescape")
        u = TB.apply(chrome(t, root))
        if u != t:
            p.write_bytes(u.encode("utf-8", "surrogateescape"))
            n += 1
    return n

CATS = {  # 表示名 → (slug, ハブページ, 説明) ※ブログは補助金カテゴリのみ
    "補助金": ("hojokin", "/service/hojokin/", "IT導入補助金(AI導入補助金)の申請実務・採択のコツ"),
}
SLUG_THUMB = {  # 手動で固定したい記事だけここに書く (それ以外は本文から自動選定)
    "ai-hojokin-guide-2026": "calculator", "it-hojokin-saitakuritsu": "documents",
    "gbizid-shutoku": "paperwork",
}
DEFAULT_PHOTO = "documents"  # キーワードに当たらなかった場合

# ---- 記事メタ収集 ----
SITE_SUFFIX = re.compile(r"\s*[|｜]\s*セブンセンシズ株式会社\s*$")   # 雛形が題の末尾に付ける社名（45字を超える題では付かない）
arts = []
for d in sorted((ROOT / "blog").iterdir()):
    f = d / "index.html"
    if not d.is_dir() or not f.is_file() or d.name == "category":
        continue
    c = f.read_text(encoding="utf-8")
    # 検索から外した記事（noindex）はページを残すが、一覧・制度別・業種別・sitemap・llms.txt には出さない
    if NI.page_hidden(c) or NI.is_hidden(d.name):
        continue
    # 題は <title> 全体から末尾の社名だけを外して読む。以前は最初の区切り（|・｜）までを題としていたため、
    # 題の中に「｜」がある記事は一覧の題が途中で切れ、社名を外した題（45字を超える記事・2026-10-09）は
    # 読めずに一覧・sitemap から12本が落ちかけた
    title = re.search(r"<title>(.*?)</title>", c, re.S)
    desc = re.search(r'name="description" content="(.*?)"', c)
    date = re.search(r'"datePublished":\s*"(\d{4}-\d{2}-\d{2})"', c)
    # sitemap の lastmod は更新日。公開日のままだと、書き直した記事の再クロールが促されない
    mod = re.search(r'"dateModified":\s*"(\d{4}-\d{2}-\d{2})"', c)
    cat = re.search(r'<span class="cat">(.*?)</span>', c)
    if not (title and desc and date and cat):
        print(f"WARN meta不足: {d.name}")
        continue
    heads = re.findall(r"<h2[^>]*>(.*?)</h2>", c, re.S)
    arts.append({"slug": d.name, "title": SITE_SUFFIX.sub("", title.group(1).strip()), "desc": desc.group(1)[:80],
                 "date": date.group(1), "mod": max(date.group(1), mod.group(1) if mod else ""),
                 "cat": cat.group(1).strip(),
                 "heads": [re.sub(r"<[^>]+>", "", h) for h in heads]})
arts.sort(key=lambda a: a["date"], reverse=True)
print(f"記事: {len(arts)}本")


def T(a):
    """説明文に入れる記事の題名（<title> から取った実体参照を戻す）"""
    return html.unescape(a["title"])

def thumb(a):
    """記事の内容に合う在庫写真を選ぶ (見出し・タイトルとの一致度で判定)"""
    name = SLUG_THUMB.get(a["slug"]) or photo_match.pick(
        title=a["title"], desc=a["desc"], heads=a["heads"]) or DEFAULT_PHOTO
    return photo_match.thumb_src(name)

def thumb_src(a):
    """記事固有の生成サムネがあればそれを、無ければ内容に合う在庫写真を返す"""
    gen = ROOT / "images" / "blog" / a["slug"] / "thumbnail.webp"
    if gen.is_file():
        return f"/images/blog/{a['slug']}/thumbnail.webp", 1200, 630
    return thumb(a)

def _alt(s):
    import html
    return html.escape(str(s), quote=True)


def latest_cards(n=3):
    """トップの「最新ノウハウ」に並べるカード（公開日の新しい順）。写真が無ければ在庫の写真にする（404 を出さない）"""
    out = []
    for a in arts[:n]:
        src, w, h = thumb_src(a)
        if not (ROOT / src.lstrip("/")).is_file():
            src, w, h = photo_match.thumb_src(DEFAULT_PHOTO)
        out.append(f'<a class="post" href="/blog/{a["slug"]}/"><div class="th"><img src="{src}" alt="{_alt(T(a))}のイメージ" '
                   f'width="{w}" height="{h}" loading="lazy"></div><div class="pb"><p class="cat">{a["cat"]}</p>'
                   f'<h3>{a["title"]}</h3><time datetime="{a["date"]}">{a["date"].replace("-", ".")}</time></div></a>')
    return out


def update_latest(root):
    """トップ（index.html）の <!--latest--> と <!--/latest--> の間を、新しい記事3本に差し替える。
    手で並べた3本のまま7月の記事が並び続け、3枚目は記事の統合で写真が 404 になっていた（2026-10-07 の点検）"""
    f = root / "index.html"
    if not f.is_file() or not arts:
        return False
    t = f.read_bytes().decode("utf-8", "surrogateescape")
    m = re.search(r"<!--latest-->(.*?)<!--/latest-->", t, re.S)
    if not m:
        print("WARN トップに最新記事の目印（<!--latest--> と <!--/latest-->）がありません。手で並べた記事のままです")
        return False
    nl = "\r\n" if "\r\n" in t else "\n"
    body = nl + "      " + (nl + "      ").join(latest_cards()) + nl + "    "
    if m.group(1) == body:
        return False
    f.write_bytes((t[:m.start(1)] + body + t[m.end(1):]).encode("utf-8", "surrogateescape"))
    return True


def card(a):
    src, w, h = thumb_src(a)
    dj = a["date"].replace("-", ".")
    return f'''    <a class="post" href="/blog/{a["slug"]}/">
      <div class="th"><img src="{src}" alt="{_alt(a["title"])}のアイキャッチ画像" width="{w}" height="{h}" loading="lazy"></div>
      <div class="pb"><p class="cat">{a["cat"]}</p><h2>{a["title"]}</h2>
      <p>{a["desc"][:52]}…</p>
      <time datetime="{a["date"]}">{dj}</time></div>
    </a>'''

STYLE = '''
/* 一覧・制度別・業種別・調査のページ（管制塔の scripts/subsidy/pages.py が作る）。色・文字・ヘッダー・足元は ss-common。決まりは DESIGN.md */
main{max-width:var(--maxw);margin:0 auto;padding:32px var(--gutter) 96px;display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:64px;align-items:start}
.main-col{min-width:0}
@media(max-width:1023px){main{grid-template-columns:minmax(0,1fr);gap:48px}}
.crumb{font-size:var(--fs-14);line-height:1.7;color:var(--ink-3);margin:0 0 28px}
.crumb a{color:var(--ink-3);text-decoration:none}
.crumb a:hover{color:var(--ink);text-decoration:underline}
.kicker{margin:0 0 10px;font-size:var(--fs-14);font-weight:700;color:var(--ai)}
h1{font-size:clamp(28px,4vw,40px);line-height:1.35;margin:0 0 16px}
.lead{max-width:40em;margin:0 0 6px;font-size:var(--fs-18);line-height:1.8;color:var(--ink-2)}
.fresh{margin:0 0 28px;font-size:var(--fs-14);color:var(--ink-3)}
.main-col>.ph-band img{aspect-ratio:3/1}
.hub{margin:0 0 20px;padding:14px 18px;background:var(--sheet);border-left:3px solid var(--ai);font-size:15px;line-height:1.85;color:var(--ink-2)}
.hub a{font-weight:700}
.hub b{color:var(--ink)}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 28px;padding:0;list-style:none}
.filters li{margin:0}
.filter{display:inline-flex;align-items:center;min-height:44px;padding:8px 16px;border:1px solid var(--rule);border-radius:var(--r-sm);background:var(--paper);color:var(--ink);font-size:var(--fs-14);font-weight:700;text-decoration:none;transition:border-color .15s,background-color .15s}
.filter:hover{border-color:var(--ai);color:var(--ai)}
.filter[aria-current="true"]{border-color:var(--ai);background:var(--ai-tint);color:var(--ai-deep)}
/* 記事の一覧: カードを並べず、罫線で区切った行にする（書類の一覧の形） */
.grid{display:block;border-top:1px solid var(--rule-strong)}
.post{display:grid;grid-template-columns:176px minmax(0,1fr);gap:22px;padding:20px 0;border-bottom:1px solid var(--rule);color:var(--ink);text-decoration:none}
.post .th{aspect-ratio:1200/630;overflow:hidden;border-radius:var(--r-sm);background:var(--sheet)}
.post .th img{display:block;width:100%;height:100%;object-fit:cover}
.post .pb{min-width:0;display:flex;flex-direction:column}
.post .cat{display:none}
.post h2{margin:0;font-size:17px;font-weight:700;line-height:1.6;color:var(--ink);transition:color .15s}
.post p{font-size:15px;margin:6px 0 0;line-height:1.75;color:var(--ink-2)}
.post time{display:block;margin-top:6px;font-size:13px;color:var(--ink-3)}
.post:hover h2{color:var(--ai);text-decoration:underline;text-underline-offset:4px}
@media(max-width:600px){.post{grid-template-columns:104px minmax(0,1fr);gap:14px;padding:16px 0}.post h2{font-size:15.5px}.post p{display:none}}
/* よくある質問（業種別） */
.qa{border-bottom:1px solid var(--rule)}
.qa summary{list-style:none;cursor:pointer;position:relative;padding:16px 40px 16px 0;font-weight:700;line-height:1.7}
.qa summary::-webkit-details-marker{display:none}
.qa summary::after{content:"";position:absolute;right:8px;top:50%;width:12px;height:12px;margin-top:-6px;background:linear-gradient(var(--ai),var(--ai)) center/12px 2px no-repeat,linear-gradient(var(--ai),var(--ai)) center/2px 12px no-repeat;transition:transform .2s var(--ease-out)}
.qa[open] summary::after{transform:rotate(45deg)}
.qa p{margin:0 0 10px;color:var(--ink-2)}
.qa p.src{font-size:var(--fs-14)}
.note{margin-top:18px;font-size:var(--fs-14);color:var(--ink-3)}
/* 監修者 */
.author{max-width:760px;margin:56px 0 0;padding:24px 0 0;border-top:1px solid var(--rule-strong);font-size:15px;color:var(--ink-2)}
.author .sv-label{display:block;margin:0 0 14px;font-size:var(--fs-14);font-weight:700;color:var(--ink-2)}
.author .sv-body{display:flex;gap:18px}
.author img.av{width:56px;height:56px;border-radius:50%;object-fit:cover;flex:none;border:1px solid var(--rule)}
.author b{color:var(--ink)}
/* 横の欄 */
.side{position:sticky;top:88px;display:grid;gap:28px}
@media(max-width:1023px){.side{position:static}}
.side .sbox p.t{margin:0 0 6px;font-size:var(--fs-14);font-weight:700;color:var(--ink-2)}
.side .sbox ul{list-style:none;margin:0;padding:0;border-top:1px solid var(--rule)}
.side .sbox li{margin:0;border-bottom:1px solid var(--rule)}
.side .sbox a{display:block;padding:10px 0;font-size:var(--fs-14);line-height:1.6;color:var(--ink);text-decoration:none}
.side .sbox a:hover{color:var(--ai);text-decoration:underline}
.side .scta{padding:20px;background:var(--sheet);border-top:3px solid var(--ai)}
.side .scta p{margin:0 0 14px;font-size:15px;font-weight:700;line-height:1.7;color:var(--ink)}
.side .scta a{display:flex;align-items:center;justify-content:center;min-height:44px;margin-top:8px;padding:10px 12px;border-radius:var(--r-sm);background:var(--ai);color:#fff;font-size:var(--fs-14);font-weight:700;text-decoration:none;border:1.5px solid var(--ai)}
.side .scta a:hover{background:var(--ai-deep)}
.side .scta a.g{background:var(--paper);color:var(--ai)}
.side .scta a.g:hover{background:var(--ai-tint)}
'''

AUTHOR = '''  <div class="author">
    <span class="sv-label">記事の監修者</span>
    <div class="sv-body">
    <img class="av" src="/assets/img/ceo.webp" alt="原口優" width="56" height="56" loading="lazy">
    <div><b>原口 優|セブンセンシズ株式会社 代表取締役</b><br>
    大阪・東成区のデジタルマーケティング&AI導入支援会社の代表。デジタル化・AI導入補助金(旧IT導入補助金)の申請を、GビズIDの取得から実績報告まで伴走支援。MEO事業「G-ran」・AI集客メディア<a href="https://ai.7senses.co.jp/" target="_blank" rel="noopener">「AI集客ラボ」</a>運営。<a href="https://corp.7senses.co.jp/" target="_blank" rel="noopener">コーポレートサイト</a>/<a href="/#contact">無料相談はこちら</a>。</div>
    </div>
  </div>'''

SIDEBAR = '''<aside class="side">
  <div class="sbox">
    <p class="t">記事を探す</p>
    <ul>
      <li><a href="/blog/category/hojokin/">補助金の記事一覧</a></li>
      <li><a href="/industry/">業種から探す</a></li>
      <li><a href="/seido/">制度から探す</a></li>
    </ul>
  </div>
  <div class="sbox">
    <p class="t">サービス</p>
    <ul>
      <li><a href="/service/hojokin/">補助金申請サポート</a></li>
      <li><a href="/service/dev/">システム開発・AI導入</a></li>
      <li><a href="/service/aio/">AIOコンサルティング</a></li>
      <li><a href="/service/meo/">MEOコンサルティング</a></li>
    </ul>
  </div>
  <div class="scta">
    <p>補助金を活用できるか、<br>まずは無料診断でチェック。</p>
    <a href="/#diagnosis">無料診断を試す</a>
    <a class="g" href="/#contact">無料で相談する</a>
  </div>
</aside>'''

FOOTER = '''<footer>
  <nav><a href="/">AI導入補助金LP</a><a href="/service/hojokin/">補助金サポート</a><a href="/service/aio/">AIOコンサル</a><a href="/service/meo/">MEOコンサル</a><a href="/service/dev/">システム開発</a><a href="/#diagnosis">無料診断</a><a href="https://corp.7senses.co.jp/" target="_blank" rel="noopener">コーポレートサイト</a><a href="/privacy/">プライバシーポリシー</a></nav>
  <p>© 2026 SEVEN SENSES Inc. セブンセンシズ株式会社|大阪市東成区神路1-7-4</p>
  ''' + footer_credit.CREDIT + '''
  ''' + SF.BLOCK + '''
</footer>'''

# 一覧の上の小見出し。どのページにも「Blog — 毎日更新」と出ていて、制度・業種のページの中身と合わなかった
KICKER = "記事一覧（毎日更新）"

def filters_html(current):
    out = [f'<a class="filter" href="/blog/" aria-current="{"true" if current=="all" else "false"}">すべて({len(arts)})</a>']
    for name, (slug, _, _) in CATS.items():
        n = sum(1 for a in arts if a["cat"] == name)
        cur = "true" if current == name else "false"
        out.append(f'<a class="filter" href="/blog/category/{slug}/" aria-current="{cur}">{name}({n})</a>')
    return "\n    ".join(out)

def page(url_path, title, desc, h1, lead, cards, current_cat, crumb_leaf, hub_html="", jsonld_extra="", more=(), kicker=KICKER):
    # 一覧・業種ページの説明が短く（35〜44字）、検索結果と共有で何のページか伝わらなかった
    # （サイト監査 2026-09-29）。運営者の一文を足しても69〜92字で、Bing が100字未満を「短すぎる」と
    # 指摘した（2026-10-05）。more はそのページの中身（本数・業種・制度・質問）から作った文で、
    # 100〜150字に収まるものだけを足す。運営者の一文は中身の文で届かないときの最後の手
    desc = DF.extend(html.unescape(desc), list(more) + ["セブンセンシズ株式会社が、補助金の申請支援の現場で確かめた内容をもとにまとめています。"])
    desc = html.escape(desc, quote=True)
    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!-- 自動生成: scratchpad/gen_blog_pages.py(記事追加時に再実行) -->
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{DOMAIN}{url_path}">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1">
<meta property="og:type" content="website">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{DOMAIN}{url_path}">
<meta property="og:image" content="{DOMAIN}/ogp.png">
<meta property="og:locale" content="ja_JP">
<link rel="icon" type="image/png" href="/favicon.png">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@graph": [
    {{ "@type": "CollectionPage", "url": "{DOMAIN}{url_path}", "name": "{title}",
      "publisher": {{ "@type": "Organization", "@id": "{DOMAIN}/#org", "name": "セブンセンシズ株式会社" }} }},
    {{ "@type": "BreadcrumbList", "itemListElement": [
      {{ "@type": "ListItem", "position": 1, "name": "ホーム", "item": "{DOMAIN}/" }},
      {{ "@type": "ListItem", "position": 2, "name": "ブログ", "item": "{DOMAIN}/blog/" }}{jsonld_extra} ] }}
  ]
}}
</script>
<style>{STYLE}</style>
{SF.style_tag("subsidy")}
<!-- GA4。日本語Webフォントと計測タグを先に読むと、スマホで一覧の表示に10秒以上かかっていた（ほかのページと同じく描画の後に読む） -->
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','G-MXQQM8DJTS');
window.addEventListener('load',function(){{setTimeout(function(){{var s=document.createElement('script');s.async=true;s.src='https://www.googletagmanager.com/gtag/js?id=G-MXQQM8DJTS';document.head.appendChild(s);}},1200);}});</script>
{CHROME_CSS}
</head>
<body>
{nav_html(ROOT)}
<main>
<div class="main-col">
  <nav class="crumb" aria-label="パンくず"><a href="/">ホーム</a> › {crumb_leaf}</nav>
  <p class="kicker">{kicker}</p>
  <h1>{h1}</h1>
  <p class="lead">{lead}</p>
  <p class="fresh">本ページは2026年7月時点の情報です</p>
{hub_html}
  <div class="filters" aria-label="カテゴリで絞り込み">
    {filters_html(current_cat)}
  </div>
  <div class="grid">
{cards}
  </div>
{AUTHOR}
</div>
{SIDEBAR}
</main>
{FOOTER}
{CHROME_JS}
</body>
</html>
'''

# ---- ブログ一覧 ----
all_cards = "\n".join(card(a) for a in arts)
(ROOT / "blog" / "index.html").write_text(page(
    "/blog/", "AI導入補助金ブログ|申請実務と採択のノウハウ|セブンセンシズ株式会社",
    f"AI導入補助金(IT導入補助金)の申請実務・採択のコツを支援現場の一次情報で毎日発信。全{len(arts)}記事。",
    "AI導入補助金の<br>実務ノウハウを毎日発信",
    "AI導入補助金(IT導入補助金)の申請実務・必要書類・採択のコツまで。支援の現場で得た一次情報だけを書いています。",
    all_cards, "all", "AI導入補助金ブログ",
    more=[f"最新の記事は「{T(arts[0])}」です。" if arts else ""]), encoding="utf-8")
print("生成: blog/index.html")

# ---- カテゴリ別 ----
for name, (slug, hub, catdesc) in CATS.items():
    cat_arts = [a for a in arts if a["cat"] == name]
    cards = "\n".join(card(a) for a in cat_arts)
    hub_html = (f'  <div class="hub">このカテゴリを体系的に知りたい方は、サービス紹介ページ'
                f'「<a href="{hub}">{name}のサービス詳細</a>」をご覧ください。個別のご相談は'
                f'<a href="/#contact">無料相談</a>へ。</div>')
    jsonld_extra = f',\n      {{ "@type": "ListItem", "position": 3, "name": "{name}" }}'
    out = ROOT / "blog" / "category" / slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page(
        f"/blog/category/{slug}/",
        f"{name}の記事一覧({len(cat_arts)}本)|セブンセンシズ株式会社ブログ",
        f"{catdesc}。全{len(cat_arts)}記事。",
        f"カテゴリ: {name}の記事一覧",
        catdesc + "。", cards, name, f'<a href="/blog/">AI導入補助金ブログ</a> › {name}',
        hub_html, jsonld_extra,
        more=[f"体系的に知りたい方は、サービス紹介ページ「{name}のサービス詳細」から読めます。",
              f"最新の記事は「{T(cat_arts[0])}」です。" if cat_arts else ""], kicker="カテゴリ別の記事"), encoding="utf-8")
    print(f"生成: blog/category/{slug}/index.html ({len(cat_arts)}本)")

# ---- 業種ハブ (/industry/<slug>/) ----
# 手法（補助金）ではなく業種から探す入口。定義は blog-system/data/industries.json
# （パイプライン側 data/industries.json の写し。配信のたびに同期される）。
# 記事が _min_articles 本たまった業種だけページを作る（薄い一覧はサイトの評価を下げる）
import json as _json
IND_FILE = Path(__file__).resolve().parents[2] / "data" / "industries.json"   # 管制塔の定義をそのまま使う（写しは持たない）
hub_pairs = []
if IND_FILE.is_file():
    _ind = _json.loads(IND_FILE.read_text(encoding="utf-8"))
    _min = int(_ind.get("_min_articles") or 5)

    def _detect(a):
        # 題名の中で最初に出てくる業種の語を、その記事の主題とする（無ければ説明文で同じように見る）。
        # 定義の順だけで見ると「飲食店の…｜動物病院…」が「病院」でクリニックに入っていた。
        # 同じ位置なら定義の順（具体的なものが先）
        for text in (a["title"], a["desc"]):
            key = text.lower()
            best = None
            for order, ind in enumerate(_ind.get("industries", [])):
                for w in ind.get("synonyms", []):
                    i = key.find(w.lower())
                    if i >= 0 and (best is None or (i, order) < best[:2]):
                        best = (i, order, ind["slug"])
            if best:
                return best[2]
        return None

    _g = {}
    for a in arts:
        s = _detect(a)
        if s:
            _g.setdefault(s, []).append(a)
    hub_pairs = [(i, _g[i["slug"]]) for i in _ind.get("industries", [])
                 if len(_g.get(i["slug"], [])) >= _min]
    def _faq(ia):
        """記事HTMLの FAQ（details/summary）を集める。答えは記事のまま、新しい文は作らない"""
        pairs = []
        for a in ia:
            f = ROOT / "blog" / a["slug"] / "index.html"
            if not f.is_file():
                continue
            c = f.read_text(encoding="utf-8")
            for q, ans in re.findall(r'<details[^>]*>\s*<summary>(.*?)</summary>\s*<div class="a">(.*?)</div>', c, re.S):
                q, ans = re.sub("<[^>]+>", "", q).strip(), re.sub("<[^>]+>", "", ans).strip()
                if q and ans:
                    pairs.append((q, ans, a))
        return pairs[:60]

    hub_faqs = {}
    for ind, ia in hub_pairs:
        out = ROOT / "industry" / ind["slug"]
        out.mkdir(parents=True, exist_ok=True)
        lead = (f'{ind["name"]}で使える補助金と申請の実務について書いた記事を、'
                f'{len(ia)}本まとめました。自社に近い記事から読めます。')
        fq = _faq(ia)
        if len(fq) >= 5:
            hub_faqs[ind["slug"]] = fq
        hub_html = ('  <div class="hub">補助金が使えるかは業種より「導入するツールと事業計画」で決まります。'
                    '自社の場合は<a href="/#diagnosis">3分の無料診断（8問・登録不要）</a>で確かめられます。'
                    + (f' <a href="/industry/{ind["slug"]}/faq/">{ind["name"]}のよくある質問（{len(fq)}問）</a>' if len(fq) >= 5 else "")
                    + '</div>')
        jsonld_extra = f',\n      {{ "@type": "ListItem", "position": 3, "name": "{ind["name"]}" }}'
        (out / "index.html").write_text(page(
            f"/industry/{ind['slug']}/",
            f"{ind['name']}の補助金・AI導入の記事({len(ia)}本)|セブンセンシズ株式会社",
            f"{ind['name']}向けの補助金活用・申請実務の記事一覧。全{len(ia)}記事。",
            f"{ind['name']}の補助金・AI導入",
            lead, "\n".join(card(a) for a in ia), "all",
            f'<a href="/industry/">業種から探す</a> › {ind["name"]}', hub_html, jsonld_extra,
            more=[f'{ind["name"]}で使える補助金と申請の実務について書いた記事です。',
                  DF.named("主な記事は", sorted((T(a) for a in ia), key=len), "です。", most=2)], kicker="業種から探す"),
            encoding="utf-8")
        print(f"生成: industry/{ind['slug']}/index.html ({len(ia)}本)")
    if hub_pairs:
        lis = "".join(f'<li><a class="filter" href="/industry/{i["slug"]}/">{i["name"]}（{len(v)}本）</a></li>'
                      for i, v in hub_pairs)
        coming = [i for i in _ind.get("industries", []) if 0 < len(_g.get(i["slug"], [])) < _min]
        note = ("" if not coming else
                '<p class="note">記事が' + str(_min)
                + '本たまった業種からページを作ります。準備中: '
                + "、".join(f'{i["name"]}（{len(_g[i["slug"]])}本）' for i in coming) + "</p>")
        idx_html = ('<div class="hub">業種ごとに、補助金の対象になりやすいツールと申請の注意点をまとめています。'
                    f'</div>\n  <ul class="filters" style="list-style:none">{lis}</ul>{note}')
        outi = ROOT / "industry"
        (outi / "index.html").write_text(page(
            "/industry/", f"業種から探す({len(hub_pairs)}業種)|AI導入補助金ブログ|セブンセンシズ株式会社",
            "補助金・AI導入の記事を業種別にまとめた入口。同じ業種の記事を横断して読めます。",
            "業種から探す", "手法ではなく、自分の業種から記事を探せる入口です。",
            "", "all", "業種から探す", idx_html,
            more=[("、".join(f'{i["name"]}' for i, _ in hub_pairs)
                   + f"の{len(hub_pairs)}業種、記事{sum(len(v) for _, v in hub_pairs)}本を載せています。",
                   f"{len(hub_pairs)}業種、記事{sum(len(v) for _, v in hub_pairs)}本を載せています。"),
                  "業種ごとに、補助金の対象になりやすいツールと申請の注意点をまとめています。"], kicker="業種から探す"), encoding="utf-8")
        print(f"生成: industry/index.html ({len(hub_pairs)}業種)")
    # 業種×よくある質問。質問形のクエリは AI Overview 表示率64.7%。答えは記事の FAQ そのまま
    for ind, ia in hub_pairs:
        fq = hub_faqs.get(ind["slug"])
        if not fq:
            continue
        outq = ROOT / "industry" / ind["slug"] / "faq"
        outq.mkdir(parents=True, exist_ok=True)
        items = "".join(f'<details class="qa">'
                        f'<summary>{q}</summary>'
                        f'<p>{a}</p><p class="src">根拠の記事: <a href="/blog/{m["slug"]}/">{m["title"][:48]}</a></p></details>'
                        for q, a, m in fq)
        ld = _json.dumps({"@context": "https://schema.org", "@type": "FAQPage",
                          "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                                         for q, a, _ in fq]}, ensure_ascii=False)
        faq_html = (f'<div class="hub">{ind["name"]}の記事{len(ia)}本から、よくある質問と答えを1か所に集めました。'
                    f'答えは各記事に書いたものと同じです。</div>{items}'
                    f'<script type="application/ld+json">{ld}</script>')
        (outq / "index.html").write_text(page(
            f"/industry/{ind['slug']}/faq/",
            f"{ind['name']}の補助金のよくある質問({len(fq)}問)|セブンセンシズ株式会社",
            f"{ind['name']}向けの補助金・AI導入について、記事{len(ia)}本のよくある質問{len(fq)}問と答え。",
            f"{ind['name']}の補助金 よくある質問",
            "記事に書いた質問と答えを、業種ごとに1か所へ集めています。", "", "all",
            f'<a href="/industry/">業種から探す</a> › <a href="/industry/{ind["slug"]}/">{ind["name"]}</a> › よくある質問',
            faq_html,
            more=["答えは各記事に書いたものと同じで、質問から根拠の記事へ進めます。",
                  DF.named("主な質問は", sorted((html.unescape(q) for q, _, _ in fq), key=len), "です。")],
            kicker="業種別のよくある質問"),
            encoding="utf-8")
        print(f"生成: industry/{ind['slug']}/faq/index.html ({len(fq)}問)")

# ---- 制度から探す (/seido/<slug>/) ----
# 143本が「補助金」1カテゴリに並ぶだけだったので、制度ごとに束ねる（記事のURLは変えない）。
# 「まず読む1本」を上に置き、残りを新しい順に並べる。事業再構築補助金は受付が終わった制度なので束ねない
SEIDO = [
    ("ai-hojokin", "AI導入補助金（IT導入補助金）",
     r"AI導入補助金|IT導入補助金|ベンダー|GビズID|みらデジ|セキュリティアクション|会計ソフト|受発注",
     r"申請のやり方|とは|ガイド|いくら",
     "AI・ITツールの導入費用を国が補助する制度です。対象ツール・申請の手順・必要書類・採択後の実績報告まで、申請の流れに沿って記事をまとめています。"),
    ("monozukuri", "新事業進出・ものづくり商業サービス補助金（旧ものづくり補助金）", r"ものづくり",
     r"中小企業の定義|1人|個人事業主",
     "ものづくり補助金は、2026年度から新事業進出補助金と統合され「新事業進出・ものづくり商業サービス補助金」になりました。"
     "ここに並ぶ記事は統合前の制度で書いたもので、業種ごとの使い方や要件の考え方の参考としてお読みください。最新の公募要領もあわせてご確認ください。"),
    ("jizokuka", "小規模事業者持続化補助金", r"持続化", r"中小企業|対象|個人事業主",
     "販路開拓や業務効率化の取り組みを支援する、小規模事業者向けの補助金です。業種ごとの書き方と採択の考え方をまとめています。"),
    ("sonota", "助成金・電子申請・そのほかの制度", r"助成金|省力化|成長加速化|給付金|電子申請|開業届|創業|インボイス",
     r"助成金とは|違い",
     "補助金と助成金の違い、省力化投資補助金などの制度、申請に使う電子申請の手続きをまとめています。"),
]
seido_pairs = []
for slug, name, rx, pillar_rx, lead_txt in SEIDO:
    sa = [a for a in arts if re.search(rx, a["title"])]
    if len(sa) < 3:
        continue
    pillar = next((a for a in sa if re.search(pillar_rx, a["title"])), sa[0])
    rest = [a for a in sa if a is not pillar]
    seido_pairs.append((slug, name, sa))
    out = ROOT / "seido" / slug
    out.mkdir(parents=True, exist_ok=True)
    hub_html = (f'  <div class="hub">{lead_txt}</div>\n'
                f'  <div class="hub"><b>まず読む1本:</b> <a href="/blog/{pillar["slug"]}/">{pillar["title"]}</a></div>')
    jsonld_extra = f',\n      {{ "@type": "ListItem", "position": 3, "name": "{name}" }}'
    (out / "index.html").write_text(page(
        f"/seido/{slug}/",
        f"{name.split('（')[0]}の記事({len(sa)}本)|セブンセンシズ株式会社",
        f"{name}について、申請の実務から採択後の手続きまで書いた記事{len(sa)}本の一覧。",
        f"{name}",
        f"{name}について書いた記事を{len(sa)}本まとめました。まず読む1本から、知りたい論点の記事へ進めます。",
        "\n".join(card(a) for a in [pillar] + rest), "all",
        f'<a href="/seido/">制度から探す</a> › {name}', hub_html, jsonld_extra,
        more=[f"まず読む1本は「{T(pillar)}」です。"], kicker="制度から探す"),
        encoding="utf-8")
    print(f"生成: seido/{slug}/index.html ({len(sa)}本)")
if seido_pairs:
    lis = "".join(f'<li><a class="filter" href="/seido/{s}/">{n}（{len(v)}本）</a></li>' for s, n, v in seido_pairs)
    (ROOT / "seido").mkdir(parents=True, exist_ok=True)
    (ROOT / "seido" / "index.html").write_text(page(
        "/seido/", f"制度から探す({len(seido_pairs)}制度)|AI導入補助金ブログ|セブンセンシズ株式会社",
        "補助金・助成金の記事を制度ごとにまとめた入口。同じ制度の記事を横断して読めます。",
        "制度から探す", "補助金・助成金の制度ごとに、記事をまとめています。",
        "", "all", "制度から探す",
        f'<div class="hub">事業再構築補助金は新規の受付が終わったため、ここには並べていません（採択後の手続きの記事はブログ一覧から読めます）。</div>\n'
        f'  <ul class="filters" style="list-style:none">{lis}</ul>',
        more=[("、".join(n for _, n, _ in seido_pairs) + f"の{len(seido_pairs)}制度の記事を載せています。",
               f"{len(seido_pairs)}制度の記事を載せています。"),
              "事業再構築補助金は新規の受付が終わったため、ここには並べていません。"], kicker="制度から探す"), encoding="utf-8")
    print(f"生成: seido/index.html ({len(seido_pairs)}制度)")

# ---- AIへの聞き取り調査（/research/ai-hojokin/）。一覧の枠ではなく、読み物の枠で出す ----
def research_shell(url_path, title, desc, h1, lead, body, crumb_leaf, jsonld_extra=""):
    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{DOMAIN}{url_path}">
<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1">
<meta property="og:type" content="article">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{DOMAIN}{url_path}">
<meta property="og:image" content="{DOMAIN}/ogp.png">
<meta property="og:locale" content="ja_JP">
<link rel="icon" type="image/png" href="/favicon.png">
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@graph": [
    {{ "@type": "WebPage", "url": "{DOMAIN}{url_path}", "name": "{title}",
      "publisher": {{ "@type": "Organization", "@id": "{DOMAIN}/#org", "name": "セブンセンシズ株式会社" }} }},
    {{ "@type": "BreadcrumbList", "itemListElement": [
      {{ "@type": "ListItem", "position": 1, "name": "ホーム", "item": "{DOMAIN}/" }},
      {{ "@type": "ListItem", "position": 2, "name": "{crumb_leaf}" }} ] }}{jsonld_extra}
  ]
}}
</script>
<style>{STYLE}
.main-col section h2{{font-size:var(--fs-28);margin:56px 0 14px;padding-top:20px;border-top:1px solid var(--rule-strong)}}
.main-col section ul{{padding-left:1.4em}}
.main-col section table{{min-width:640px}}

table{{width:100%;font-size:var(--fs-14);line-height:1.7;border-top:1px solid var(--rule-strong);border-bottom:1px solid var(--rule-strong)}}
th,td{{padding:10px 12px;text-align:left;vertical-align:top;border-bottom:1px solid var(--rule)}}
thead th{{background:var(--sheet);white-space:nowrap}}small{{color:var(--ink-3)}}
/* 引用の枠（research_cite.py は AI集客ラボと共通の部品で、本文の中に色を持つ。このサイトの色へ寄せる） */
.main-col .cite-box{{border:0;border-top:3px solid var(--ai);border-radius:0;background:var(--sheet)}}
.main-col .cite-text{{border-color:var(--rule);border-radius:var(--r-sm)}}
.main-col .cite-copy{{border-color:var(--ai);color:var(--ai);border-radius:var(--r-sm);min-height:40px}}
.main-col .cite-copy:hover{{background:var(--ai-tint)}}</style>
{SF.style_tag("subsidy")}
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','G-MXQQM8DJTS');
window.addEventListener('load',function(){{setTimeout(function(){{var s=document.createElement('script');s.async=true;s.src='https://www.googletagmanager.com/gtag/js?id=G-MXQQM8DJTS';document.head.appendChild(s);}},1200);}});</script>
{CHROME_CSS}
</head>
<body>
{nav_html(ROOT)}
<main>
<div class="main-col">
  <nav class="crumb" aria-label="パンくず"><a href="/">ホーム</a> › {crumb_leaf}</nav>
  <p class="kicker">当社の調査</p>
  <h1>{h1}</h1>
  <p class="lead">{lead}</p>
{body}
{AUTHOR}
</div>
{SIDEBAR}
</main>
{FOOTER}
{CHROME_JS}
</body>
</html>
'''


research_done = None
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import research as _RS
    research_done = _RS.build(ROOT, DOMAIN, research_shell)
    print(f"生成: {research_done[0]}" if research_done else "AIへの聞き取り調査: 材料が足りないのでページを作らない")
    # トップの調査のグラフ（<!--research:top--> のあいだ）も同じデータから入れ直す。数字を手で書かない
    print(f"トップの調査の図: {_RS.put_top(ROOT, DOMAIN)}")
except Exception as e:
    print(f"AIへの聞き取り調査のページを作れませんでした: {e}")

# 配信物の生成（tools/make_dist.py）が research/ を配信対象に入れていなければ足す。
# 2026-10-04: sitemap に載せたのに PUBLIC_DIRS に無く、配信先のビルドが「404になる」で止まり続けた
if research_done:
    _md = ROOT / "tools" / "make_dist.py"
    if _md.is_file():
        _t = _md.read_text(encoding="utf-8")
        _m = re.search(r"PUBLIC_DIRS\s*=\s*\[([^\]]*)\]", _t)
        if _m and '"research"' not in _m.group(1):
            _md.write_text(_t[:_m.end(1)] + ', "research"' + _t[_m.end(1):], encoding="utf-8", newline="\n")

# ---- sitemap.xml ----
STATIC = [("/", "2026-07-21", "1.0"), ("/blog/", "2026-07-21", "0.8"),
          ("/service/hojokin/", "2026-07-21", "0.9"), ("/service/dev/", "2026-07-21", "0.8"),
          ("/service/aio/", "2026-07-21", "0.9"), ("/service/meo/", "2026-07-21", "0.8"),
          ("/about/", "2026-07-21", "0.5"), ("/youkou/", "2026-07-23", "0.7"),
          ("/privacy/", "2026-07-21", "0.3")]
urls = [f"  <url>\n    <loc>{DOMAIN}{p}</loc>\n    <lastmod>{d}</lastmod>\n    <priority>{pr}</priority>\n  </url>"
        for p, d, pr in STATIC]
for name, (slug, _, _) in CATS.items():
    cat_arts = [a for a in arts if a["cat"] == name]
    last = max((a["mod"] for a in cat_arts), default="2026-07-21")
    urls.append(f"  <url>\n    <loc>{DOMAIN}/blog/category/{slug}/</loc>\n    <lastmod>{last}</lastmod>\n    <priority>0.6</priority>\n  </url>")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import search_preview  # noqa: E402

# 記事の画像（アイキャッチ・図解）と埋め込んだ動画も載せる。描いたページから拾い、実在する画像だけ
n_img = n_vid = 0
for a in arts:
    pr = "0.9" if a["slug"] == "ai-hojokin-guide-2026" else "0.7"
    _page = (ROOT / "blog" / a["slug"] / "index.html").read_text(encoding="utf-8")
    _media = search_preview.media_lines(_page, a["slug"], DOMAIN, lambda p: (ROOT / p.lstrip("/")).is_file())
    n_img += _media.count("<image:image>")
    n_vid += _media.count("<video:video>")
    urls.append(f"  <url>\n    <loc>{DOMAIN}/blog/{a['slug']}/</loc>\n    <lastmod>{a['mod']}</lastmod>\n    <priority>{pr}</priority>\n{_media}  </url>")
if hub_pairs:
    urls.append(f"  <url>\n    <loc>{DOMAIN}/industry/</loc>\n    <lastmod>{arts[0]['date']}</lastmod>\n    <priority>0.6</priority>\n  </url>")
    for i, v in hub_pairs:
        urls.append(f"  <url>\n    <loc>{DOMAIN}/industry/{i['slug']}/</loc>\n    <lastmod>{v[0]['date']}</lastmod>\n    <priority>0.6</priority>\n  </url>")
        if i["slug"] in hub_faqs:
            urls.append(f"  <url>\n    <loc>{DOMAIN}/industry/{i['slug']}/faq/</loc>\n    <lastmod>{v[0]['date']}</lastmod>\n    <priority>0.6</priority>\n  </url>")
if research_done:
    urls.append(f"  <url>\n    <loc>{DOMAIN}{research_done[0]}</loc>\n    <lastmod>{research_done[1]}</lastmod>\n    <priority>0.7</priority>\n  </url>")
if seido_pairs:
    urls.append(f"  <url>\n    <loc>{DOMAIN}/seido/</loc>\n    <lastmod>{arts[0]['date']}</lastmod>\n    <priority>0.6</priority>\n  </url>")
    for s, _, v in seido_pairs:
        urls.append(f"  <url>\n    <loc>{DOMAIN}/seido/{s}/</loc>\n    <lastmod>{v[0]['date']}</lastmod>\n    <priority>0.6</priority>\n  </url>")
# ---- llms.txt の記事セクション自動更新 (AIO: AIクローラーに全記事を提示) ----
llms_path = ROOT / "llms.txt"
if llms_path.is_file():
    llms = llms_path.read_text(encoding="utf-8")
    cut = llms.find("\n## ブログ記事")
    if cut != -1:
        llms = llms[:cut]
    lines = ["", "## ブログ記事(全記事・新しい順)", ""]
    for a in arts:
        lines.append(f"- [{a['title']}]({DOMAIN}/blog/{a['slug']}/): {a['desc'][:70]}")
    if research_done:
        lines += ["", "## 当社の調査", "", research_done[2]]
    lines += ["",
              "## 記事カテゴリ",
              "",
              f"- [補助金の記事一覧]({DOMAIN}/blog/category/hojokin/)", ""]
    if hub_pairs:
        lines += ["## 業種から探す", ""] + [
            f"- [{i['name']}の補助金・AI導入]({DOMAIN}/industry/{i['slug']}/): {len(v)}本" for i, v in hub_pairs] + [
            f"- [{i['name']}のよくある質問]({DOMAIN}/industry/{i['slug']}/faq/): {len(hub_faqs[i['slug']])}問"
            for i, v in hub_pairs if i["slug"] in hub_faqs] + [""]
    llms_path.write_text(llms.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")
    print(f"生成: llms.txt (記事{len(arts)}本を反映)")

(ROOT / "sitemap.xml").write_text(
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<!-- 自動生成: gen_blog_pages.py。lastmodは記事の公開/更新日のみ変更 -->\n"
    + search_preview.urlset_open() + "\n"
    + "\n".join(urls) + "\n</urlset>\n", encoding="utf-8")
print(f"生成: sitemap.xml ({len(urls)} URLs・画像{n_img}・動画{n_vid})")
# 手書きの固定ページも含めて、検索結果での見え方の指定をそろえる（noindex のページは触らない）
print(f"robots の見え方の指定: {search_preview.apply_dir(ROOT)}ページ")
print(f"トップの最新記事: {'新しい3本に差し替えました' if update_latest(ROOT) else '変わりません'}")
# ヘッダー（ナビ）は、手書きのトップ・固定ページ・記事の雛形・記事を含む全ページで同じものにする
print(f"ヘッダー（ナビ）: {sync_chrome(ROOT)}ページを揃えました")
# LP の制作表記も、手書きの LP・固定ページ・記事の雛形を含む全ページのフッターに揃える
print(f"フッターの制作表記: {footer_credit.apply(ROOT)}ページを揃えました")
print("done")







