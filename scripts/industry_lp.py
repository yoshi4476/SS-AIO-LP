# -*- coding: utf-8 -*-
"""業種別の LP（/lp/medical/ /lp/fudosan/ /lp/koumuten/）。build.py が毎回作り直す。

全業種向けの /lp/ だけでは、医療・不動産・工務店の読者が「自分の業種の話か」を確かめられない。
業種ならではの悩み → 当社が行うこと → 業種が選ばれた状態の30秒診断 → その業種の記事 → よくある質問、の順に並べる。
記事一覧とよくある質問は、その業種の公開済み記事から集める（新しい文は作らない。記事が増えるほど厚くなる）。
悩みと対策の文に数字は書かない。実績は公開済みの表現（G-ran 通算3,200店舗以上・2026年7月時点）だけを使う。
"""
import html
import json

LPS = {
    "medical": {
        "name": "クリニック・歯科医院・整骨院",
        "h1": "クリニック・歯科医院のSEO・AI検索対策",
        "desc": "クリニック・歯科医院・整骨院向けのSEO・AIO・LLMO対策。医療広告ガイドラインにふれない書き方で、検索とAIの答えに選ばれるサイトをつくります。30秒の無料サイト診断つき。",
        "slugs": ["clinic", "shika", "seikotsuin"],
        "scan_ind": "クリニック・歯科医院",
        "pains": [
            ("何を書けばよいか分からない", "医療広告ガイドラインで体験談・比較・効果の保証が使えず、ホームページに載せる内容に迷う。"),
            ("ポータルサイトが上に並ぶ", "症状や治療名で調べられても、予約サイトや大手の情報サイトが先に表示される。"),
            ("AIの答えに医院名が出ない", "ChatGPT や Google の AI による概要に聞かれても、自院の名前や情報が出てこない。"),
            ("効果が分からない", "ホームページを直しても、予約や問い合わせが増えたのかが分からない。"),
        ],
        "fixes": [
            ("ガイドラインにふれない記事づくり（SEO）", "症状・治療・費用の疑問に答える記事を、医療広告ガイドラインにふれない書き方で作ります。"),
            ("医院の事実をAIが読める形に（AIO・LLMO）", "診療内容・設備・費用・院長の経歴など、その医院にしか無い事実を、検索とAIが読み取れる形に整えます。"),
            ("サイトの技術面を整える", "AIのクローラーが入れるか、検索に出る設定か、構造化データが正しいかを点検して直します。"),
            ("毎月の数字で確かめる", "検索とAI経由の訪問、予約・問い合わせの数を毎月測り、次に直す点をお伝えします。"),
        ],
    },
    "fudosan": {
        "name": "不動産会社",
        "h1": "不動産会社のSEO・AI検索対策",
        "desc": "不動産会社向けのSEO・AIO・LLMO対策。ポータルサイトに埋もれず、地域の売却・購入・住み替えの検索とAIの答えに選ばれるサイトをつくります。30秒の無料サイト診断つき。",
        "slugs": ["fudosan"],
        "scan_ind": "不動産",
        "pains": [
            ("ポータルサイトに埋もれる", "物件や地域名で調べられても、大手の不動産ポータルが上位を占め、自社サイトが見つからない。"),
            ("物件以外で選ばれない", "売却・相続・住み替えなどの相談先を探す人に、自社が候補として届いていない。"),
            ("AIの答えに社名が出ない", "地域の不動産会社をAIに聞かれても、自社の名前が出てこない。"),
            ("反響につながらない", "アクセスはあっても、査定依頼や来店予約につながっているかが分からない。"),
        ],
        "fixes": [
            ("地域×相談テーマの記事（SEO）", "売却・相続・住み替えなど、地域の相談に答える記事を作り、物件以外の入口を増やします。"),
            ("会社の事実をAIが読める形に（AIO・LLMO）", "対応エリア・得意な取引・会社の実績など、自社にしか無い事実を検索とAIが読み取れる形に整えます。"),
            ("サイトの技術面を整える", "AIのクローラーが入れるか、検索に出る設定か、構造化データが正しいかを点検して直します。"),
            ("毎月の数字で確かめる", "検索とAI経由の訪問、査定依頼・問い合わせの数を毎月測り、次に直す点をお伝えします。"),
        ],
    },
    "koumuten": {
        "name": "工務店・リフォーム会社",
        "h1": "工務店・リフォーム会社のSEO・AI検索対策",
        "desc": "工務店・リフォーム会社向けのSEO・AIO・LLMO対策。施工事例と家づくりの考え方を、地域の検索とAIの答えに選ばれる形に整えます。30秒の無料サイト診断つき。",
        "slugs": ["koumuten", "reform"],
        "scan_ind": "工務店・リフォーム",
        "pains": [
            ("施工事例が検索に出ない", "事例をたくさん載せているのに、地域名や工事の種類で調べても表示されない。"),
            ("比較・資料請求サイトが上に並ぶ", "「地域名 注文住宅」などで調べると、一括資料請求のサイトが先に表示される。"),
            ("AIの候補に挙がらない", "家づくりやリフォームの相談先をAIに聞かれても、自社が候補に出てこない。"),
            ("問い合わせにつながらない", "見学会や資料請求につながっているページがどれか分からない。"),
        ],
        "fixes": [
            ("施工事例を読まれる形に（SEO）", "施工事例を、地域・工事の種類・費用の考え方が伝わる形に整え、検索の入口にします。"),
            ("会社の事実をAIが読める形に（AIO・LLMO）", "対応エリア・得意な工法・性能・保証など、自社にしか無い事実を検索とAIが読み取れる形に整えます。"),
            ("サイトの技術面を整える", "AIのクローラーが入れるか、検索に出る設定か、構造化データが正しいかを点検して直します。"),
            ("毎月の数字で確かめる", "検索とAI経由の訪問、資料請求・見学会予約の数を毎月測り、次に直す点をお伝えします。"),
        ],
    },
}

# 記事・ハブの業種（industry_hub の slug）→ LP
BY_HUB = {s: k for k, v in LPS.items() for s in v["slugs"]}

STYLE = """<style>
.ilp{max-width:1080px;margin:0 auto;display:grid;gap:2.6rem}
.ilp h2{font-size:clamp(1.25rem,2.4vw,1.6rem);margin:0 0 1rem}
.ilp-lead{font-size:1.02rem;line-height:1.95;margin:0}
.ilp-scan{background:linear-gradient(135deg,#0b2447,#123a72);color:#fff;border-radius:22px;padding:clamp(1.4rem,3vw,2.2rem)}
.ilp-scan p{color:rgba(255,255,255,.88);margin:.3rem 0 1rem}
.ilp-scan form{display:flex;gap:.6rem;flex-wrap:wrap}
.ilp-scan input[type=url]{flex:1 1 260px;font:inherit;padding:.85em 1em;border-radius:12px;border:0}
.ilp-cards{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr))}
.ilp-card{border:1px solid var(--line);border-radius:18px;padding:1.2rem 1.25rem;background:#fff}
.ilp-card h3{font-size:1.02rem;margin:0 0 .45rem}
.ilp-card p{margin:0;font-size:.93rem;line-height:1.85;color:var(--muted)}
.ilp-fix .ilp-card{background:var(--bg-alt)}
.ilp-proof{font-size:.92rem;color:var(--muted);margin:0}
.ilp-cta{text-align:center;display:grid;gap:.8rem;justify-items:center}
.ilp-faq details{border-bottom:1px solid var(--line);padding:.9rem 0}
.ilp-faq summary{font-weight:700;cursor:pointer}
.ilp-more{margin-top:1rem}
</style>"""


def url_for(hub_slug):
    k = BY_HUB.get(hub_slug or "")
    return f"/lp/{k}/" if k else "/lp/"


def _e(s):
    return html.escape(str(s or ""), quote=True)


def body(key, metas, faq_pairs, post_tile, site_url):
    c = LPS[key]
    pains = "".join(f'<div class="ilp-card"><h3>{_e(t)}</h3><p>{_e(d)}</p></div>' for t, d in c["pains"])
    fixes = "".join(f'<div class="ilp-card"><h3>{_e(t)}</h3><p>{_e(d)}</p></div>' for t, d in c["fixes"])
    hubs = "・".join(f'<a href="/industry/{s}/">{_e(n)}</a>' for s, n in c.get("hub_names", []))
    tiles = "\n".join(post_tile(m) for m in metas[:6])
    faq = "".join(f'<details><summary>{_e(q)}</summary><p>{_e(a)}</p>'
                  f'<p style="font-size:.85rem"><a href="{_e(u)}">この質問の記事を読む</a></p></details>'
                  for q, a, u in faq_pairs[:6])
    scan = (f'<section class="ilp-scan" id="scan-start"><h2 style="color:#fff">{_e(c["name"])}のサイトを、30秒で診断する</h2>'
            '<p>URLを入れるだけで、AIのクローラーが入れるか・検索に出る設定か・内容を読み取れるかを14項目で測り、その場で点数と直し方を出します。無料・登録不要。</p>'
            '<form action="/lp/" method="get">'
            f'<input type="hidden" name="ind" value="{_e(c["scan_ind"])}"><input type="hidden" name="src" value="lp_{key}">'
            '<input type="url" name="check" required inputmode="url" placeholder="https://example.co.jp" aria-label="ホームページのURL">'
            f'<button type="submit" class="btn btn-primary" data-cta="lp_{key}_scan">30秒で診断する</button></form></section>')
    out = [STYLE, '<div class="ilp">', scan,
           f'<section><h2>{_e(c["name"])}によくあるお悩み</h2><div class="ilp-cards">{pains}</div></section>',
           f'<section class="ilp-fix"><h2>セブンセンシズが行うこと</h2><div class="ilp-cards">{fixes}</div>'
           '<p class="ilp-proof" style="margin-top:1rem">集客支援の実務: 店舗集客「G-ran」で通算3,200店舗以上（2026年7月時点）の運用に携わってきました。'
           'ここに挙げた業種のほかにも対応しています。</p></section>',
           '<section class="ilp-cta"><a class="btn btn-primary" href="/lp/#form" '
           f'data-cta="lp_{key}_consult">無料で相談する（現状分析つき）</a>'
           '<p class="ilp-proof">サービス内容と料金は<a href="/lp/#service">サービス・料金</a>をご覧ください。</p></section>']
    if tiles:
        out.append(f'<section><h2>{_e(c["name"])}の集客に役立つ記事</h2><ul class="post-list">\n{tiles}\n</ul>'
                   + (f'<p class="ilp-more">業種別のまとめ: {hubs}</p>' if hubs else "") + '</section>')
    if faq:
        out.append(f'<section class="ilp-faq"><h2>よくある質問</h2>{faq}</section>')
    out.append('</div>')
    return "\n".join(out)


def json_ld(key, faq_pairs, site_url, org):
    c = LPS[key]
    url = f"{site_url}/lp/{key}/"
    graph = [{"@type": "Service", "name": c["h1"], "url": url, "description": c["desc"],
              "provider": org, "areaServed": "JP", "serviceType": "SEO・AIO・LLMO対策",
              "audience": {"@type": "BusinessAudience", "name": c["name"]}},
             {"@type": "BreadcrumbList", "itemListElement": [
                 {"@type": "ListItem", "position": 1, "name": "ホーム", "item": site_url + "/"},
                 {"@type": "ListItem", "position": 2, "name": "サービス", "item": site_url + "/lp/"},
                 {"@type": "ListItem", "position": 3, "name": c["h1"], "item": url}]}]
    if faq_pairs:
        graph.append({"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a, _ in faq_pairs[:6]]})
    return ('<script type="application/ld+json">'
            + json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)
            + "</script>")
