# -*- coding: utf-8 -*-
"""業種別の LP（/lp/medical/ /lp/fudosan/ /lp/koumuten/）。build.py が毎回作り直す。

全業種向けの /lp/ だけでは、医療・不動産・工務店の読者が「自分の業種の話か」を確かめられない。
業種ならではの悩み → 当社が行うこと → 業種が選ばれた状態の30秒診断 → その業種の記事 → よくある質問、の順に並べる。
記事一覧とよくある質問は、その業種の公開済み記事から集める（新しい文は作らない。記事が増えるほど厚くなる）。
悩みと対策の文に数字は書かない。実績は公開済みの表現（G-ran 通算3,200店舗以上・2026年7月時点）だけを使う。
"""
import html
import json
from pathlib import Path

LPS = {
    "medical": {
        "name": "クリニック・歯科医院・整骨院",
        "h1": "クリニック・歯科医院のSEO・AI検索対策",
        "desc": "クリニック・歯科医院・整骨院向けのSEO・AIO・LLMO対策。医療広告ガイドラインにふれない書き方で、検索とAIの答えに選ばれるサイトをつくります。30秒の無料サイト診断つき。",
        "slugs": ["clinic", "shika", "seikotsuin"],
        "research": [("dental", "歯科"), ("clinic", "クリニック")],
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
        "research": [("fudosan", "不動産")],
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
        "research": [("koumuten", "工務店・リフォーム")],
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
    "shigyou": {
        "name": "士業事務所",
        "h1": "士業事務所のSEO・AI検索対策",
        "desc": "税理士・社労士・行政書士・司法書士・弁護士などの士業事務所向けのSEO・AIO・LLMO対策。専門分野が伝わる解説と事務所の事実を、検索とAIの答えに選ばれる形に整えます。30秒の無料サイト診断つき。",
        "slugs": ["shigyou"],
        "research": [("shigyou", "士業")],
        "scan_ind": "士業・コンサル",
        "pains": [
            ("解説を書いても埋もれる", "相続・労務・許認可などの解説を載せても、大手の情報サイトや比較サイトの下に表示される。"),
            ("比較・紹介サイトが上に並ぶ", "「地域名 税理士」などで調べられても、紹介サイトや比較サイトが先に表示される。"),
            ("AIの答えに事務所名が出ない", "相談先をAIに聞かれても、事務所の名前や専門分野が出てこない。"),
            ("広告の決まりで書き方に迷う", "各士業会の広告に関する規程があり、実績や他の事務所との比べ方をどこまで書けるか迷う。"),
        ],
        "fixes": [
            ("相談テーマごとの解説記事（SEO）", "相続・会社設立・労務・許認可など、相談する人が調べる疑問に答える記事を、事務所の専門分野に沿って作ります。"),
            ("事務所の事実をAIが読める形に（AIO・LLMO）", "資格者・専門分野・対応エリア・料金の考え方など、その事務所にしか無い事実を、検索とAIが読み取れる形に整えます。"),
            ("サイトの技術面を整える", "AIのクローラーが入れるか、検索に出る設定か、構造化データが正しいかを点検して直します。"),
            ("毎月の数字で確かめる", "検索とAI経由の訪問、相談予約・問い合わせの数を毎月測り、次に直す点をお伝えします。"),
        ],
    },
}

# 記事・ハブの業種（industry_hub の slug）→ LP
BY_HUB = {s: k for k, v in LPS.items() for s in v["slugs"]}

STYLE = """<style>
.ilp{max-width:1120px;margin:0 auto;display:grid;gap:3.4rem}
.ilp-eb{display:block;font-family:var(--sans);font-size:.8125rem;letter-spacing:.1em;color:var(--blue);font-weight:700;margin-bottom:.35rem}
.ilp h2{font-size:clamp(1.3rem,2.5vw,1.75rem);margin:0 0 1.1rem;line-height:1.45;text-wrap:balance}
.ilp-cards{display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr))}
.ilp-card{border:1px solid var(--line);border-radius:18px;padding:1.25rem 1.3rem;background:#fff;box-shadow:var(--shadow-sm)}
.ilp-card h3{font-size:1.02rem;margin:0 0 .5rem;line-height:1.5}
.ilp-card p{margin:0;font-size:.93rem;line-height:1.85;color:var(--muted)}
.ilp-pain .ilp-card{border-top:4px solid #d9932b}
.ilp-fix .ilp-card{border-top:4px solid var(--blue);background:var(--bg-alt)}
.ilp-photo-card{overflow:hidden;padding-top:0}
.ilp-photo-card img{display:block;width:calc(100% + 2.6rem);max-width:none;margin:0 -1.3rem 1rem;aspect-ratio:16/9;object-fit:cover}
.ilp-data{background:linear-gradient(135deg,#0b2447,#123a72);border-radius:26px;padding:clamp(1.5rem,3.4vw,2.6rem);color:#fff}
.ilp-data .ilp-eb{color:#8fb7ff}
.ilp-data h2{color:#fff}
.ilp-data .ilp-proof{color:rgba(255,255,255,.78)}
.ilp-data .ilp-card{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.18);box-shadow:none}
.ilp-stat .ilp-k{font-size:.8rem;color:rgba(255,255,255,.72);font-weight:700;margin:0 0 .35rem}
.ilp-stat .ilp-n{font-size:clamp(2rem,3.8vw,2.7rem);font-weight:800;color:#fff;margin:0;line-height:1.15;font-variant-numeric:tabular-nums}
.ilp-stat p{color:rgba(255,255,255,.86)}
.ilp-stat .ilp-src{margin-top:.7rem;font-size:.82rem}
.ilp-stat .ilp-src a{color:#8fb7ff}
.ilp-proof{font-size:.9rem;color:var(--muted);margin:0}
.ilp-band{background:var(--navy-deep);color:#fff;border-radius:26px;padding:clamp(1.6rem,3.6vw,2.6rem);display:grid;gap:1rem;justify-items:center;text-align:center}
.ilp-band h2{color:#fff;margin:0}
.ilp-band p{margin:0;color:rgba(255,255,255,.8)}
.ilp-band .btns{display:flex;gap:.8rem;flex-wrap:wrap;justify-content:center}
.ilp-band .btn-ghost{border-color:rgba(255,255,255,.7);color:#fff}
.ilp-faq details{border-bottom:1px solid var(--line);padding:1rem 0}
.ilp-faq-grid{display:grid;gap:1.6rem}
@media(min-width:900px){.ilp-faq-grid{grid-template-columns:minmax(0,1.4fr) minmax(0,1fr);gap:2.4rem;align-items:start}.ilp-faq-ph{position:sticky;top:96px}}
.ilp-faq-ph{margin:0;border-radius:18px;overflow:hidden;box-shadow:var(--shadow-md)}
.ilp-faq-ph img{display:block;width:100%;aspect-ratio:4/3;object-fit:cover}
.ilp-faq summary{font-weight:700;cursor:pointer;list-style-position:outside}
.ilp-faq details p{margin:.6rem 0 0;color:var(--muted);line-height:1.85}
.ilp-more{margin-top:1rem}
.ilp-console .lx-stat{padding:.9rem 0;border-top:1px solid rgba(255,255,255,.14)}
.ilp-console .lx-stat:first-of-type{border-top:0;padding-top:.2rem}
.ilp-console .lx-stat b{display:block;font-size:2.3rem;line-height:1.1;font-variant-numeric:tabular-nums;color:#fff}
.ilp-console .lx-stat span{font-size:.86rem;color:rgba(255,255,255,.82);line-height:1.7}
.ilp-hero .lx-h1{font-size:clamp(1.9rem,4.4vw,3.1rem)}
@media (prefers-reduced-motion:reduce){.ilp *{transition:none!important}}
</style>"""


def hero(key, c):
    """最初の画面。トップと同じ lx-hero の作り（左: 見出しと30秒診断、右: 調査の要点の数字）"""
    import industry_ai_sources as IAS
    stats = ""
    for r, label in c.get("research") or []:
        hl = IAS.headline(r)
        if not hl:
            continue
        T = hl["T"]
        if hl["verdict"] == "portal":
            first = (f'{hl["lp"]}%', f'{T["owner"]}を探す質問で、AIの出典が{T["portal"]}だった割合（{T["owner_site"]}は{hl["lc"]}%）')
        elif hl["verdict"] == "owner":
            first = (f'{hl["lc"]}%', f'{T["owner"]}を探す質問で、AIの出典が{T["owner_site"]}だった割合')
        else:
            first = (f'{hl["lp"]}%／{hl["lc"]}%', f'{T["owner"]}を探す質問で、AIの出典になった{T["portal"]}と{T["owner_site"]}の割合（ほぼ同じ）')
        stats = (f'<div class="lx-console ilp-console" aria-label="調査の要点"><div class="lx-console-head"><b>AIは何を出典に答えるか</b>'
                 f'<small>{_e(label)}・{hl["questions"]}問×4つのAI</small></div>'
                 f'<div class="lx-stat"><b>{_e(first[0])}</b><span>{_e(first[1])}</span></div>'
                 f'<div class="lx-stat"><b>{hl["oa"]}%</b><span>{_e(T["other_short"])}を調べる質問で、回答が{_e(T["owner_site"])}を1つ以上出典にしていた割合</span></div>'
                 f'<p class="lx-console-foot"><a href="/research/{r}-ai-sources/" style="color:#8fb7ff" data-cta="lp_{key}_hero_research">調査の詳細を見る（{hl["date"]}）</a></p></div>')
        break
    if not stats:
        items = "".join(f'<li class="lx-item"><span class="mk" aria-hidden="true"></span><span>{_e(t)}</span></li>' for t, _ in c["fixes"])
        stats = (f'<div class="lx-console ilp-console"><div class="lx-console-head"><b>セブンセンシズが行うこと</b></div>'
                 f'<div class="lx-group"><ul>{items}</ul></div></div>')
    name = c["h1"].replace("のSEO・AI検索対策", "")
    return (f'<section class="lx-hero ilp-hero" data-area="メインビジュアル" data-area-id="mv">'
            f'<div class="lx-wrap lx-hero-grid"><div>'
            f'<ul class="lx-kicker"><li>SEO・AIO・LLMO対策</li><li>{_e(c["name"])}向け</li></ul>'
            f'<h1 class="lx-h1">{_e(name)}の<br><em>SEO・AI検索対策</em></h1>'
            f'<p class="lx-lead">{_e(c["desc"].split("。")[1] if c["desc"].count("。") > 1 else c["desc"])}。まず、御社のサイトがAIと検索に読まれているかを30秒で確かめてください。</p>'
            f'<form class="lx-form" id="scan-start" action="/lp/" method="get">'
            f'<input type="hidden" name="ind" value="{_e(c["scan_ind"])}"><input type="hidden" name="src" value="lp_{key}">'
            f'<label>ホームページのURL<input type="url" name="check" inputmode="url" placeholder="https://example.co.jp" autocomplete="url" required></label>'
            f'<button type="submit" class="lx-go" data-cta="lp_{key}_scan">30秒で無料診断する</button>'
            f'<p class="lx-micro"><span>入力はURLだけ</span><span>登録不要</span><span>営業電話なし</span></p></form>'
            f'<p class="lx-alt">話を聞いてから決めたい方は <a href="{_e(consult_url(key))}" data-cta="lp_{key}_hero_consult">無料相談</a>'
            f' ／ サービス内容と料金は <a href="/lp/#service">こちら</a></p>'
            f'</div>{stats}</div></section>')


def consult_url(key):
    """業種LPの「相談する」の行き先。相談のフォームは全業種向けの /lp/ にあるため、業種を ?ind= で渡す
    （診断の ?ind= と同じ値。/lp/ では site.js がフォームの隠し項目に入れ、受付が本文に添える）。
    以前は /lp/#form へ移るだけで、どの業種の人の相談か分からなかった（2026-10-08）"""
    from urllib.parse import quote
    return f'/lp/?ind={quote(LPS[key]["scan_ind"])}&src=lp_{key}#form'


def url_for(hub_slug):
    k = BY_HUB.get(hub_slug or "")
    return f"/lp/{k}/" if k else "/lp/"


def _e(s):
    return html.escape(str(s or ""), quote=True)


def data_section(key, c):
    """調査（industry_ai_sources）の要点の数字。数字は headline() からだけ取る（調査ページと同じ値）"""
    import industry_ai_sources as IAS
    cards = []
    for r, label in c.get("research") or []:
        hl = IAS.headline(r)
        if not hl:
            continue
        T = hl["T"]
        if hl["verdict"] == "portal":
            big, cap = f'{hl["lp"]}%', f'が{T["portal"]}（{T["owner_site"]}は{hl["lc"]}%）'
        elif hl["verdict"] == "owner":
            big, cap = f'{hl["lc"]}%', f'が{T["owner_site"]}（{T["portal"]}は{hl["lp"]}%）'
        else:
            big, cap = f'{hl["lp"]}%／{hl["lc"]}%', f'{T["portal"]}と{T["owner_site"]}がほぼ同じ'
        cards.append(
            f'<div class="ilp-card ilp-stat"><p class="ilp-k">{_e(label)}｜{_e(T["owner"])}を探す質問の出典</p>'
            f'<p class="ilp-n">{_e(big)}</p><p>{_e(cap)}</p></div>'
            f'<div class="ilp-card ilp-stat"><p class="ilp-k">{_e(label)}｜{_e(T["other_short"])}の質問</p>'
            f'<p class="ilp-n">{hl["oa"]}%</p><p>の回答が{_e(T["owner_site"])}を1つ以上出典にしていた</p>'
            f'<p class="ilp-src"><a href="/research/{r}-ai-sources/" data-cta="lp_{key}_research_{r}">調査の詳細（{hl["questions"]}問×4つのAI・{hl["date"]}）</a>'
            f'　<a href="{IAS.checklist_url(r)}" data-cta="lp_{key}_checklist_{r}">チェックリスト（PDF）</a></p></div>')
    if not cards:
        return ""
    return ('<section class="ilp-data"><span class="ilp-eb">当社の調査</span><h2>データで見る：AIは何を出典に答えているか</h2>'
            '<p class="ilp-proof" style="margin:0 0 1rem">当社が、実際に調べられそうな質問を ChatGPT・Gemini・Claude などのAIに聞き、'
            '回答の出典になったサイトを種類ごとに数えた結果です。</p>'
            f'<div class="ilp-cards">{"".join(cards)}</div></section>')


def body(key, metas, faq_pairs, post_tile, site_url):
    c = LPS[key]
    pains = "".join(f'<div class="ilp-card"><h3>{_e(t)}</h3><p>{_e(d)}</p></div>' for t, d in c["pains"])
    # 4枚は どの業種も SEO → AIO・LLMO → 技術面 → 毎月の数字 の順。その場面の写真（イメージ）を頭に置く
    photos = ["svc-seo", "svc-aio", "svc-tech", "svc-report"]
    fixes = "".join(
        (f'<div class="ilp-card ilp-photo-card"><img src="/images/home/{photos[i]}.webp" alt="{_e(t)}のイメージ" width="1600" height="900" loading="lazy">'
         if i < len(photos) else '<div class="ilp-card">')
        + f'<h3>{_e(t)}</h3><p>{_e(d)}</p></div>' for i, (t, d) in enumerate(c["fixes"]))
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
    out = [STYLE, '<div class="ilp">',
           f'<section class="ilp-pain"><span class="ilp-eb">課題</span><h2>{_e(c["name"])}によくあるお悩み</h2><div class="ilp-cards">{pains}</div></section>',
           data_section(key, c),
           f'<section class="ilp-fix"><span class="ilp-eb">支援内容</span><h2>セブンセンシズが行うこと</h2><div class="ilp-cards">{fixes}</div>'
           '<p class="ilp-proof" style="margin-top:1rem">集客支援の実務: 店舗集客「G-ran」で通算3,200店舗以上（2026年7月時点）の運用に携わってきました。'
           'ここに挙げた業種のほかにも対応しています。</p></section>',
           '<section class="ilp-band"><h2>まずは、今の状態を知るところから</h2>'
           '<p>現状分析は無料です。30秒の診断だけでも、直す順番が分かります。</p><div class="btns">'
           f'<a class="btn btn-primary" href="{_e(consult_url(key))}" data-cta="lp_{key}_consult">無料で相談する（現状分析つき）</a>'
           f'<a class="btn btn-ghost" href="#scan-start" data-cta="lp_{key}_band_scan">30秒で診断する</a>'
           f'<a class="btn btn-ghost" href="/tools/ai-check/" data-cta="lp_{key}_band_aicheck">AIにどう紹介されているか確かめる</a></div></section>']
    if tiles:
        out.append(f'<section><span class="ilp-eb">関連する記事</span><h2>{_e(c["name"])}の集客に役立つ記事</h2><ul class="post-list">\n{tiles}\n</ul>'
                   + (f'<p class="ilp-more">業種別のまとめ: {hubs}</p>' if hubs else "") + '</section>')
    if faq:
        # 質問の列だけだと右が空くので、相談に答える場面の写真（イメージ）を右に置く
        out.append(f'<section class="ilp-faq"><span class="ilp-eb">質問と答え</span><h2>よくある質問</h2>'
                   f'<div class="ilp-faq-grid"><div>{faq}</div><figure class="ilp-faq-ph">'
                   f'<img src="/images/scenes/faq.webp" alt="オンラインで相談に答える担当者のイメージ" width="1600" height="900" loading="lazy">'
                   f'</figure></div></section>')
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
