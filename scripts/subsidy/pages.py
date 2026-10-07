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
/* サイト共通の枠（ヘッダー・文字・足元）。管制塔の scripts/subsidy/pages.py が配信のたびに全ページへ揃える。ここを直接直さない */
@font-face{font-family:"YuGothicM";src:local("Yu Gothic Medium"),local("YuGothic-Medium");font-weight:400}
@font-face{font-family:"YuGothicM";src:local("Yu Gothic Bold"),local("YuGothic-Bold");font-weight:700}
:root{--sans:"Hiragino Kaku Gothic ProN","Hiragino Sans","YuGothicM","Yu Gothic","Noto Sans JP","Noto Sans CJK JP","BIZ UDPGothic",Meiryo,sans-serif;
--num:"Oswald","Hiragino Kaku Gothic ProN","Hiragino Sans","YuGothicM","Yu Gothic","Noto Sans JP","Noto Sans CJK JP","BIZ UDPGothic",Meiryo,sans-serif}
.gh-in{max-width:1360px;margin:0 auto;padding:0 22px;height:64px;display:flex;align-items:center;justify-content:space-between;gap:16px}
.gh-logo{flex:none;display:block;line-height:0}
.gh-logo img{display:block;height:38px;width:auto;max-width:none}
.gh-nav{min-width:0}
.gh .gh-list,.gh .gh-sub{list-style:none;margin:0;padding:0}
.gh .gh-list li{margin:0}
.gh-list{display:flex;align-items:center;gap:18px}
.gh-list>li{position:relative}
.gh-list a{display:inline-block;padding:10px 2px;font-size:14px;line-height:1.5;font-weight:500;color:#5b6472;text-decoration:none;white-space:nowrap}
.gh-list a:hover,.gh-list a:focus-visible{color:#1d3461}
.gh-has>a::after{content:"▾";font-size:10px;color:#b08b3e;margin-left:5px}
.gh-sub{position:absolute;top:100%;left:-14px;z-index:70;display:none;min-width:228px;padding:8px;background:#fff;border:1px solid #e7e2d4;border-radius:12px;box-shadow:0 18px 44px rgba(29,52,97,.16)}
.gh-has:hover>.gh-sub,.gh-has:focus-within>.gh-sub{display:grid;gap:2px}
.gh-sub a{display:block;padding:10px 14px;border-radius:8px;color:#212b3d}
.gh-sub a:hover,.gh-sub a:focus-visible{background:#f4ead3;color:#7a5b14}
.gh-tel{flex:none;display:inline-flex;align-items:center;gap:7px;min-height:44px;padding:6px 8px;border-radius:10px;color:#1d3461;text-decoration:none;white-space:nowrap}
.gh-tel:hover{background:rgba(42,74,138,.06)}
.gh-tel b{font-family:var(--num);font-size:17px;font-weight:600;letter-spacing:.03em}
.gh-tel small{font-size:12px;color:#5b6472}
.gh-cta{flex:none;display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:8px 22px;border-radius:999px;background:linear-gradient(135deg,#e8c988,#d9b36a 55%,#c39a4e);color:#171104;font-size:14px;font-weight:700;line-height:1.4;text-decoration:none;white-space:nowrap;box-shadow:0 6px 18px rgba(176,139,62,.32)}
.gh-menu{display:none}
@media(max-width:1479px){.gh-list .gh-ext{display:none}}
@media(max-width:1199px){.gh-list{gap:13px}.gh-list a{font-size:13.5px}.gh-tel small{display:none}}
@media(max-width:1079px){
 .gh-in{height:60px;gap:8px}
 .gh-logo{margin-right:auto}
 .gh-nav{display:none;position:absolute;left:0;right:0;top:100%;max-height:calc(100vh - 60px);overflow-y:auto;padding:4px 22px 24px;background:#fdfcf9;border-top:1px solid #e7e2d4;border-bottom:1px solid #e7e2d4;box-shadow:0 22px 40px -18px rgba(19,36,69,.3)}
 .gh.gh-open .gh-nav{display:block}
 .gh-list{display:block}
 .gh-list>li{border-bottom:1px solid #ece6d6}
 .gh-list a{display:block;padding:13px 2px;font-size:16px;color:#212b3d}
 .gh-has>a::after{content:none}
 .gh-sub{position:static;display:grid;gap:0;min-width:0;padding:0 0 10px 14px;background:none;border:0;border-radius:0;box-shadow:none}
 .gh-sub a{padding:10px 2px;font-size:15px;color:#5b6472}
 .gh-list .gh-ext{display:block}
 .gh-tel{width:44px;height:44px;padding:0;justify-content:center;border:1.5px solid #2a4a8a;border-radius:50%}
 .gh-tel b,.gh-tel small{display:none}
 .gh-cta{padding:8px 16px;font-size:13.5px;box-shadow:none}
 .gh-menu{flex:none;display:inline-flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;width:52px;height:44px;padding:0;border:0;border-radius:10px;background:none;color:#1d3461;font:inherit;font-size:12px;font-weight:700;line-height:1;cursor:pointer}
 .gh-bars,.gh-bars::before,.gh-bars::after{content:"";display:block;width:22px;height:2px;border-radius:2px;background:currentColor;transition:transform .2s}
 .gh-bars{position:relative;margin:6px 0 5px}
 .gh-bars::before,.gh-bars::after{position:absolute;left:0}
 .gh-bars::before{top:-7px}
 .gh-bars::after{top:7px}
 .gh-open .gh-bars{background:transparent}
 .gh-open .gh-bars::before{top:0;transform:rotate(45deg)}
 .gh-open .gh-bars::after{top:0;transform:rotate(-45deg)}
 .gh-lock .sticky-cta,.gh-lock .blog-sticky,.gh-lock .float-cta{visibility:hidden}
}
@media(max-width:420px){.gh-in{padding:0 14px}.gh-cta{padding:8px 14px}}
@media(max-width:389px){.gh-long{display:none}}
/* スマホの下の固定ボタン: 入力欄・診断が見えている間と、入力中は引っ込める（入力欄に重なっていた） */
.sticky-cta{transition:transform .25s ease,opacity .25s ease}
.sticky-cta.is-hidden{transform:translateY(110%);opacity:0;pointer-events:none}
/* 足元のリンクは指で押せる大きさに（スマホで高さ16px・間隔0〜9pxだった） */
footer nav a[href]{display:inline-block;padding:.6rem .4rem}
/* 「※ 写真はイメージです」が地の色と 3.16:1 で読みにくかった */
figure.ph-band figcaption{font-size:12px;color:#6b7280}
@media(prefers-reduced-motion:reduce){.sticky-cta,.gh-bars,.gh-bars::before,.gh-bars::after{transition:none}}
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
        u = chrome(t, root)
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
arts = []
for d in sorted((ROOT / "blog").iterdir()):
    f = d / "index.html"
    if not d.is_dir() or not f.is_file() or d.name == "category":
        continue
    c = f.read_text(encoding="utf-8")
    title = re.search(r"<title>(.*?)[||]", c)
    desc = re.search(r'name="description" content="(.*?)"', c)
    date = re.search(r'"datePublished":\s*"(\d{4}-\d{2}-\d{2})"', c)
    # sitemap の lastmod は更新日。公開日のままだと、書き直した記事の再クロールが促されない
    mod = re.search(r'"dateModified":\s*"(\d{4}-\d{2}-\d{2})"', c)
    cat = re.search(r'<span class="cat">(.*?)</span>', c)
    if not (title and desc and date and cat):
        print(f"WARN meta不足: {d.name}")
        continue
    heads = re.findall(r"<h2[^>]*>(.*?)</h2>", c, re.S)
    arts.append({"slug": d.name, "title": title.group(1).strip(), "desc": desc.group(1)[:80],
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
:root{--bg:#fdfcf9;--bg2:#f4f1e9;--panel:#ffffff;--line:#e7e2d4;--line2:rgba(176,139,62,.45);
--text:#212b3d;--muted:#5b6472;--dim:#5c6472;--gold:#775c1c;--gold-strong:#7a5b14;--gold-ink:#171104;
--serif:"Hiragino Mincho ProN", "Yu Mincho", "Noto Serif JP", "Noto Serif CJK JP", serif;--sans:"Hiragino Kaku Gothic ProN", "Hiragino Sans", "YuGothicM", "Yu Gothic", "Noto Sans JP", "Noto Sans CJK JP", "BIZ UDPGothic", Meiryo, sans-serif;--num:"Hiragino Kaku Gothic ProN", "Hiragino Sans", "YuGothicM", "Yu Gothic", "Noto Sans JP", "Noto Sans CJK JP", "BIZ UDPGothic", Meiryo, sans-serif}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:15.5px;line-height:1.9;-webkit-font-smoothing:antialiased}
a{color:inherit}
:focus-visible{outline:2px solid var(--gold);outline-offset:3px;border-radius:4px}
header{position:sticky;top:0;z-index:50;background:rgba(253,252,249,.9);backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
main{max-width:1240px;margin:0 auto;padding:56px 22px 90px;display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:44px;align-items:start}
.main-col{min-width:0}
.side{position:sticky;top:84px;display:grid;gap:16px}
@media(max-width:1023px){main{grid-template-columns:minmax(0,1fr)}.side{position:static}}
.side .sbox{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;box-shadow:0 6px 20px rgba(29,52,97,.05)}
.side .sbox p.t{font-family:var(--num);font-size:12px;letter-spacing:.3em;color:var(--gold);margin:0 0 12px}
.side .sbox ul{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.side .sbox li{margin:0}
.side .sbox a{display:block;font-size:14.5px;text-decoration:none;color:var(--text);padding:10px 12px;border:1px solid var(--line);border-radius:8px;line-height:1.5}
.side .sbox a:hover{border-color:var(--line2);color:var(--gold-strong)}
.side .scta{background:linear-gradient(150deg,#132445,#1d3461 60%,#24427c);border-radius:12px;padding:22px;color:#fff;text-align:center}
.side .scta p{font-family:var(--serif);font-weight:800;font-size:15px;line-height:1.8;margin:0 0 12px;color:#fff}
.side .scta a{display:block;background:linear-gradient(135deg,#e8c988,#d9b36a 55%,#c39a4e);color:#171104;border-radius:999px;padding:12px;font-weight:700;font-size:14px;text-decoration:none;margin-top:8px}
.side .scta a.g{background:none;border:1.5px solid rgba(255,255,255,.5);color:#fff}
.crumb{font-size:13px;color:var(--dim);margin-bottom:20px}
.crumb a{color:var(--dim);text-decoration:none}
.kicker{font-family:var(--num);font-size:13px;font-weight:700;letter-spacing:.18em;color:var(--gold);display:flex;align-items:center;gap:14px;margin-bottom:16px}
.kicker::before{content:"";width:34px;height:1px;background:var(--gold)}
h1{font-family:var(--serif);font-weight:800;font-size:clamp(26px,4.4vw,38px);line-height:1.5;margin-bottom:12px;color:#1d3461}
.lead{color:var(--muted);max-width:720px;margin-bottom:8px}
.fresh{font-size:13px;color:var(--dim);margin-bottom:30px}
.hub{background:#fff;border:1px solid var(--line2);border-radius:12px;padding:16px 20px;margin-bottom:30px;font-size:15px;color:var(--muted)}
.hub a{color:var(--gold-strong);font-weight:700}
.filters{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:34px}
.filter{display:inline-flex;align-items:center;min-height:44px;padding:8px 20px;border-radius:999px;border:1px solid var(--line);color:var(--muted);font-size:14px;font-weight:700;text-decoration:none;background:#fff}
.filter[aria-current="true"]{border-color:var(--line2);color:var(--gold-strong);background:rgba(217,179,106,.1)}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}
@media(max-width:600px){.grid{grid-template-columns:1fr}}
.post{background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;text-decoration:none;transition:border-color .15s,transform .15s;display:flex;flex-direction:column;box-shadow:0 10px 34px rgba(29,52,97,.06)}
.post:hover{border-color:var(--line2);transform:translateY(-3px)}
.post .th{height:104px;background:linear-gradient(135deg,#eef1f8,#e4e9f4);border-bottom:1px solid var(--line);overflow:hidden}
.post .th img{width:100%;height:100%;object-fit:cover;display:block}
.post .pb{padding:18px 18px 20px;display:flex;flex-direction:column;flex:1}
.post .cat{font-size:12px;letter-spacing:.22em;color:var(--gold);margin-bottom:8px}
.post h2{font-size:15.5px;font-weight:700;line-height:1.7;font-family:var(--sans)}
.post p{font-size:15px;color:var(--dim);margin-top:8px;line-height:1.8}
.post time{display:block;font-size:13px;color:var(--dim);margin-top:auto;padding-top:12px}
.author{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:24px;margin-top:48px;font-size:15px;color:var(--muted);max-width:760px}
.author .sv-label{display:block;font-size:12px;letter-spacing:.14em;font-weight:700;color:var(--dim);margin:0 0 14px}
.author .sv-body{display:flex;gap:16px}
.author img.av{width:56px;height:56px;border-radius:50%;object-fit:cover;border:1px solid var(--line2);flex:none}
.author b{color:var(--text)}
footer{border-top:1px solid var(--line);background:var(--bg2);padding:40px 22px;font-size:13.5px;color:var(--muted);text-align:center;line-height:1.9}
footer a{color:var(--muted);text-decoration:none;margin:0 10px}
'''

AUTHOR = '''  <div class="author">
    <span class="sv-label">SUPERVISED BY|記事の監修者</span>
    <div class="sv-body">
    <img class="av" src="/assets/img/ceo.webp" alt="原口優" width="56" height="56" loading="lazy">
    <div><b>原口 優|セブンセンシズ株式会社 代表取締役</b><br>
    大阪・東成区のデジタルマーケティング&AI導入支援会社の代表。デジタル化・AI導入補助金(旧IT導入補助金)の申請を、GビズIDの取得から実績報告まで伴走支援。MEO事業「G-ran」・AI集客メディア<a href="https://ai.7senses.co.jp/" target="_blank" rel="noopener" style="color:var(--gold-strong)">「AI集客ラボ」</a>運営。<a href="https://corp.7senses.co.jp/" target="_blank" rel="noopener" style="color:var(--gold-strong)">コーポレートサイト</a>/<a href="/#contact" style="color:var(--gold-strong)">無料相談はこちら</a>。</div>
    </div>
  </div>'''

SIDEBAR = '''<aside class="side">
  <div class="sbox">
    <p class="t">CATEGORY</p>
    <ul>
      <li><a href="/blog/category/hojokin/">補助金の記事一覧</a></li>
      <li><a href="/industry/">業種から探す</a></li>
      <li><a href="/seido/">制度から探す</a></li>
    </ul>
  </div>
  <div class="sbox">
    <p class="t">SERVICE</p>
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
  <p>© 2026 SEVEN SENSES INC. セブンセンシズ株式会社|大阪市東成区神路1-7-4</p>
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
        f"カテゴリ: <span style='color:#7a5b14'>{name}</span>の記事一覧",
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
            f"<span style='color:#7a5b14'>{ind['name']}</span>の補助金・AI導入",
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
                '<p style="font-size:13px;color:var(--dim);margin-top:18px">記事が' + str(_min)
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
        items = "".join(f'<details style="margin:10px 0;padding:12px 16px;background:#fff;border:1px solid var(--line);border-radius:10px">'
                        f'<summary style="cursor:pointer;font-weight:700">{q}</summary>'
                        f'<p style="margin:10px 0 6px">{a}</p><p style="font-size:12.5px"><a href="/blog/{m["slug"]}/">→ {m["title"][:48]}</a></p></details>'
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
            f"<span style='color:#7a5b14'>{ind['name']}</span>の補助金 よくある質問",
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
        f"<span style='color:#7a5b14'>{name}</span>",
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
table{{border-collapse:collapse;width:100%;font-size:.92rem}}th,td{{border:1px solid #e3e7ee;padding:8px;text-align:left;vertical-align:top}}
thead th{{background:#f6f8fb}}small{{color:#5b6474}}</style>
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
  <p class="kicker">調査 — 当社調べ</p>
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







