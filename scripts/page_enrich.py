# -*- coding: utf-8 -*-
"""無料ツール5種と資料ダウンロードのページを肉付けする（写真・使い方・結果でわかること・向いている方・よくある質問・次に読む記事）。

中身は各ページにすでに書いてある説明（ツールが実際にすること）から作る。新しい数字は足さない。
ビルドのたびに呼ばれ、<!-- enrich --> … <!-- /enrich --> を入れ替えるので何度呼んでも同じになる。
"""
import html as _h
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TOOLS = {
    "url-check": {
        "hero": "/images/home/tool-url.webp",
        "side": ("/images/home/svc-tech.webp", "画面でサイトの設定と表示速度を確かめる担当者"),
        "steps": [("URLを入れる", "確かめたいページのURLを入れて「チェック」を押します。登録は要りません。"),
                  ("14項目を自動で検査", "ページを実際に取得し、AIが入れるか・検索に出るか・内容を読み取れるかを機械的に調べます。"),
                  ("不合格を上から直す", "項目ごとの合否と点数が出ます。不合格の項目を上から順に直せば対応が進みます。")],
        "learn": [("AIが入れるか（26点）", "AIのクローラーを robots.txt で拒否していないか、CDN・WAF の入口で弾いていないか、常時SSLか。"),
                  ("検索に出るか（40点）", "検索に出さない設定（noindex）になっていないか、タイトル・説明文・正規URL・スマホ表示。"),
                  ("内容を読み取れるか（32点）", "見出しH1、会社情報（電話番号・所在地）、構造化データ、画像の代替テキスト、OGP、llms.txt。"),
                  ("直す順番", "配点の大きい項目から並ぶので、どこから手を付けるかがその場で決まります。")],
        "who": ["自社サイトがAIと検索に読まれる状態かを、まず確かめたい方",
                "制作会社に直してもらう前に、何が足りないかを把握したい方",
                "リニューアルや引っ越しの後に、設定の漏れが無いか確かめたい方"],
        "faq": [("料金や登録は必要ですか？", "どちらも不要です。URLを入れるだけで、その場で結果が出ます。"),
                ("他社のサイトも調べられますか？", "対象は、ご自身が管理するサイトか、公開されているページに限ります。"),
                ("検索順位やAIに引用されているかもわかりますか？", "わかりません。公開ページの機械検査で、順位やAI引用の実績そのものは測りません。"),
                ("点数が低かったときは？", "不合格の項目を上から直してください。技術的に難しい場合や記事の中身まで見たい場合は、無料の現状分析をご利用ください。")],
    },
    "ai-check": {
        "hero": "/images/home/tool-ai.webp",
        "dark": True,
        "side": ("/images/home/svc-llmo.webp", "ノートパソコンでAIに質問する人"),
        "steps": [("地域・業種・社名を入れる", "地域と業種、社名、公式サイトのURL、結果を受け取るメールアドレスを入れます。"),
                  ("AIに3つの質問を聞く", "Google検索を使って答えるAI（Gemini）に「おすすめ」「評判 いい」「人気」の3つを聞きます。"),
                  ("名前と出典を確かめる", "答えの文章に社名が出たか、出典に公式サイトが入ったかを質問ごとに表示します。")],
        "learn": [("文章に名前が出るか", "入力した表記と同じ書き方で回答に出たときに「あり」とします。言い換えは数えません。"),
                  ("出典に公式サイトが入るか", "入力いただいた公式サイトのドメインが、答えの出典に入っているかで判定します。"),
                  ("質問ごとの違い", "「おすすめ」「評判」「人気」で、出る・出ないが分かれることがあります。"),
                  ("次に何をするか", "出ていない場合に、どこから整えるかの目安につなげます。")],
        "who": ["地域で探されたとき、AIが自社を紹介しているかを知りたい方",
                "検索では出ているのに、AIの答えに名前が出ない理由を探している方",
                "業種の中で、AIにどう扱われているかの傾向をつかみたい方"],
        "faq": [("何回でも使えますか？", "チェックは1つのメールアドレスにつき3回まで、1回で聞く質問は3問です。"),
                ("ChatGPT や Claude でも確かめられますか？", "このツールは Gemini で確かめます。ChatGPT・Claude を含めた確認はお問い合わせください。"),
                ("結果が日によって違うのはなぜですか？", "AIの答えは日によって変わります。1回の結果で決めず、傾向を知る目安としてお使いください。"),
                ("社名の書き方が違うとどうなりますか？", "入力した表記と同じ書き方だけを数えます。「〇〇歯科」と「〇〇デンタル」のような言い換えは数えません。")],
    },
    "aio-check": {
        "hero": "/images/home/svc-aio.webp",
        "side": ("/images/shelf/aisearch-2.webp", "AIの答えを画面で確かめる人"),
        "steps": [("8つの質問に答える", "検索順位・記事の構造・技術設定・発信者の信頼性について、当てはまるものを選びます。"),
                  ("100点満点で判定", "答えを100点満点に換算し、AI検索に引用される準備がどこまで整っているかを出します。"),
                  ("最初の3手から始める", "結果画面の「最初の3手」から着手し、3か月後にもう一度チェックして変化を確かめます。")],
        "learn": [("検索順位という土台", "AIが引用する前提になる、検索での立ち位置。"),
                  ("抽出されやすい構造", "AIが答えとして切り出しやすい書き方になっているか。"),
                  ("AIが読める技術設定", "AIのクローラーが入れる設定になっているか。"),
                  ("発信者の信頼性", "誰が書いているか、根拠が示されているか。")],
        "who": ["AI検索の対策を、何から始めればよいか迷っている方",
                "社内でサイトを運用していて、抜けている観点を確かめたい方",
                "外注する前に、自社の現在地を短時間で把握したい方"],
        "faq": [("結果はどのくらい正確ですか？", "自己申告に基づく簡易判定です。実際の順位やAIへの引用状況は、無料の現状分析で確かめます。"),
                ("点数が低いと手遅れですか？", "いいえ。取り組んでいる企業はまだ少数派で、先に動けば差をつけられる伸びしろです。"),
                ("どのくらいの間隔でやり直せばよいですか？", "最初の3手に取り組んだあと、3か月後にもう一度チェックすると変化が数字で確かめられます。"),
                ("URL診断とは何が違いますか？", "URL診断はページを機械的に調べます。このチェックは運用の状態を、質問への答えから判定します。")],
    },
    "kuchikomi-henshin": {
        "hero": "/images/shelf/reviews-1.webp",
        "side": ("/images/shelf/reviews-2.webp", "スマートフォンで口コミを読む店主"),
        "steps": [("業種と口コミの種類を選ぶ", "高評価・待ち時間や対応への不満・料金や内容の主張など、口コミの種類を選びます。"),
                  ("口コミの本文を貼る", "本文はお使いのブラウザの中だけで扱い、当社にも外部にも送信しません。"),
                  ("返信案の【 】を書き換える", "型に沿った返信案が出ます。【 】の部分は、実際に行っている改善の内容に書き換えます。")],
        "learn": [("高評価への返信", "感謝 → 具体への言及 → 次回の一言、の型で返します。"),
                  ("不満への返信", "謝罪 → 改善の事実 → お礼、の型で返します。"),
                  ("料金や内容の主張", "反論せず、窓口へ案内する型で返します。"),
                  ("医療での注意", "病院・歯科医院・整骨院では、症状や施術の内容にふれず、効果の保証や比較の言い回しも使いません。")],
        "who": ["口コミへの返信を、毎回ゼロから考えている方",
                "医療・歯科・整骨院で、返信の言い回しが規制にふれないか不安な方",
                "低評価の口コミに、どう返せばよいか迷っている方"],
        "faq": [("口コミの本文は外に送られますか？", "送られません。本文はお使いのブラウザの中だけで扱います。"),
                ("暴言や誹謗中傷の口コミにも返信すべきですか？", "返信より先に、Google への報告を案内します。"),
                ("返信案はそのまま使えますか？", "【 】の部分を、実際に行っている改善の内容に書き換えてから使ってください。行っていない改善を書くと事実と違う返信になります。"),
                ("口コミそのものを増やすには？", "口コミを増やす方法の記事で、頼み方と注意点をまとめています。")],
    },
    "meo-check": {
        "hero": "/images/home/svc-meo.webp",
        "side": ("/images/shelf/map-2.webp", "地図アプリで店を探す人"),
        "steps": [("8つの質問に答える", "Googleビジネスプロフィールの情報・口コミ・更新の状態について、当てはまるものを選びます。"),
                  ("A〜Dの4段階で判定", "答えを100点満点に換算し、マップ集客の整備度をA〜Dで判定します。"),
                  ("最初にやる3つから着手", "判定ごとに「最初にやるべき3つ」が出ます。そこから整えます。")],
        "learn": [("情報の正確さ", "店名・住所・電話番号・営業時間などが正しく、揃っているか。"),
                  ("口コミ", "口コミが集まり、返信できているか。"),
                  ("継続した更新", "写真や投稿を続けて更新できているか。"),
                  ("最初の3つ", "判定に応じて、先に手を付けるべきことを3つに絞って出します。")],
        "who": ["Googleマップからの来店や予約を増やしたい店舗・医院",
                "ビジネスプロフィールを作ったまま、更新できていない方",
                "マップ対策を外注する前に、自社の状態を知りたい方"],
        "faq": [("設問はどこから作っていますか？", "当社のMEO運用「G-ran」の初回ヒアリングで実際に確認している項目から、影響の大きい8つを選んでいます。"),
                ("結果はどのくらい正確ですか？", "自己申告に基づく簡易判定です。実際の順位・表示回数は、無料の現状分析で確かめます。"),
                ("判定が低かったら？", "提示された3つから着手してください。正確な情報・口コミ・継続した更新の3つを整えることが出発点です。"),
                ("口コミへの返信も手伝ってもらえますか？", "口コミ返信文の作成ツールで、型に沿った返信案を作れます。")],
        "more": [("/tools/kuchikomi-henshin/", "口コミ返信文の作成ツール")],
    },
}

DOWNLOAD = {
    "side": ("/images/home/dl-check.webp", "チェックリストに印をつけながら自社の状態を確かめる経営者"),
    "steps": [("業種を選んで送信", "お名前・会社名・メールアドレスと、受け取る業種のチェックリストを選んで送信します。"),
              ("メールでリンクが届く", "選んだ業種のチェックリスト（PDF）のダウンロードリンクをメールでお送りします。"),
              ("印をつけて直す順番を決める", "約25項目に印をつけるだけで、何から直すかがわかります。")],
    "learn": [("5業種別", "歯科医院・クリニック・不動産会社・工務店リフォーム・士業事務所の5つから選べます。"),
              ("調査の数字つき", "AIに聞いた調査（100問×4つのAI）の数字をもとに、何から直すかを示します。"),
              ("印をつけるだけ", "約25項目のチェックリスト形式で、社内で回して使えます。"),
              ("営業電話なし", "しつこい営業の電話は行いません。")],
    "who": ["AI検索の対策を、社内で話し合う材料がほしい方",
            "自社の業種で、AIが何を出典に答えているかを知りたい方",
            "まずは手元で確かめてから、相談するか決めたい方"],
    "faq": [("費用はかかりますか？", "かかりません。フォームを送信すると、ダウンロードのリンクをメールでお送りします。"),
            ("自分の業種がありません", "いまは5業種です。ほかの業種は、無料のURL診断やAI診断で現在地を確かめられます。"),
            ("営業の電話はかかってきますか？", "しつこい営業の電話は行いません。"),
            ("チェックの根拠は何ですか？", "業種ごとに、AIに聞いた調査（100問×4つのAI）の結果をもとにしています。調査の詳細は各業種の調査ページで公開しています。")],
    "more": [("/research/dental-ai-sources/", "調査: 歯科医院"), ("/research/clinic-ai-sources/", "調査: クリニック"),
             ("/research/fudosan-ai-sources/", "調査: 不動産"), ("/research/koumuten-ai-sources/", "調査: 工務店・リフォーム"),
             ("/research/shigyou-ai-sources/", "調査: 士業")],
}

CSS = """
/* 無料ツール・資料ダウンロードの肉付け（page_enrich.py・2026-10-03） */
section.hero:has(> .tool-hero-ph) { position: relative; isolation: isolate; overflow: hidden; }
.tool-hero-ph { position: absolute; inset: 0; z-index: -1; pointer-events: none;
  -webkit-mask-image: linear-gradient(180deg, #000 0%, rgba(0,0,0,.6) 55%, transparent 100%);
  mask-image: linear-gradient(180deg, #000 0%, rgba(0,0,0,.6) 55%, transparent 100%); }
.tool-hero-ph img { width: 100%; height: 100%; object-fit: cover; opacity: .16; }
.enrich { max-width: 1180px; margin: 0 auto; padding: clamp(2.2rem, 5vw, 3.6rem) clamp(1rem, 3vw, 2rem) 0; }
.enrich h2 { font-size: clamp(1.3rem, 2.4vw, 1.7rem); margin: 0 0 .4rem; }
.enrich .en { font-size: .72rem; letter-spacing: .2em; color: var(--blue); font-weight: 700; text-transform: uppercase; }
.enrich-block { margin: 0 0 clamp(2.4rem, 5vw, 3.4rem); }
.enrich-steps { list-style: none; counter-reset: s; display: grid; grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap: 1rem; margin: 1.2rem 0 0; padding: 0; }
.enrich-steps li { counter-increment: s; background: #fff; border: 1px solid var(--line); border-radius: 16px; padding: 1.3rem 1.3rem 1.2rem; box-shadow: var(--shadow-sm); }
.enrich-steps li::before { content: "STEP " counter(s); display: block; font-size: .72rem; font-weight: 800; letter-spacing: .14em; color: var(--blue); margin-bottom: .4rem; }
.enrich-steps b { display: block; font-size: 1.02rem; margin-bottom: .35rem; }
.enrich-steps span { font-size: .88rem; color: var(--muted); line-height: 1.85; }
.enrich-learn { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1.6rem; align-items: center; margin-top: 1.2rem; }
@media (max-width: 860px) { .enrich-learn { grid-template-columns: minmax(0, 1fr); } }
.enrich-learn figure { margin: 0; border-radius: 18px; overflow: hidden; box-shadow: var(--shadow-md); }
.enrich-learn figure img { display: block; width: 100%; height: auto; aspect-ratio: 4 / 3; object-fit: cover; }
.enrich-learn dl { margin: 0; display: grid; gap: .8rem; }
.enrich-learn dl div { background: var(--bg-alt); border-radius: 14px; padding: 1rem 1.15rem; }
.enrich-learn dt { font-weight: 800; margin-bottom: .25rem; }
.enrich-learn dd { margin: 0; font-size: .88rem; color: var(--muted); line-height: 1.85; }
.enrich-who { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(260px, 100%), 1fr)); gap: .8rem; list-style: none; padding: 0; margin: 1.1rem 0 0; }
.enrich-who li { border-left: 4px solid var(--blue); background: #fff; border-radius: 0 12px 12px 0; padding: .9rem 1.1rem; font-size: .92rem; font-weight: 700; box-shadow: var(--shadow-sm); }
.enrich-faq details { border-bottom: 1px solid var(--line); padding: 1rem 0; }
.enrich-faq summary { font-weight: 700; cursor: pointer; }
.enrich-faq details p { margin: .6rem 0 0; color: var(--muted); line-height: 1.85; }
.enrich-more { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: 1rem; }
.enrich-more a { display: inline-flex; align-items: center; padding: .55em 1.1em; border: 1.5px solid var(--line); border-radius: 999px; font-weight: 700; font-size: .88rem; text-decoration: none; color: var(--blue-deep); background: #fff; }
.enrich-more a:hover { border-color: var(--blue); }
.enrich-note { font-size: .74rem; color: var(--muted); margin: .5rem 0 0; }
.dl-grid { display: grid; grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr); gap: 2.4rem; align-items: center; }
@media (max-width: 860px) { .dl-grid { grid-template-columns: minmax(0, 1fr); } }
.dl-grid > figure { margin: 0; border-radius: 18px; overflow: hidden; box-shadow: var(--shadow-md); }
.dl-grid > figure img { display: block; width: 100%; height: auto; aspect-ratio: 4 / 3; object-fit: cover; }
"""


def _e(s):
    return _h.escape(s, quote=True)


def _blocks(d, more):
    steps = "".join(f"<li><b>{_e(a)}</b><span>{_e(b)}</span></li>" for a, b in d["steps"])
    learn = "".join(f"<div><dt>{_e(a)}</dt><dd>{_e(b)}</dd></div>" for a, b in d["learn"])
    who = "".join(f"<li>{_e(x)}</li>" for x in d["who"])
    faq = "".join(f"<details><summary>{_e(q)}</summary><p>{_e(a)}</p></details>" for q, a in d["faq"])
    links = "".join(f'<a href="{u}">{_e(t)}</a>' for u, t in more)
    src, alt = d["side"]
    return (f'<div class="enrich">'
            f'<div class="enrich-block"><span class="en">How to use</span><h2>使い方は3ステップ</h2><ol class="enrich-steps">{steps}</ol></div>'
            f'<div class="enrich-block"><span class="en">Result</span><h2>結果でわかること</h2><div class="enrich-learn">'
            f'<figure><img src="{src}" alt="{_e(alt)}のイメージ" width="1600" height="900" loading="lazy" decoding="async"></figure>'
            f'<dl>{learn}</dl></div><p class="enrich-note">※ 写真はイメージです</p></div>'
            f'<div class="enrich-block"><span class="en">For you</span><h2>こんな方に向いています</h2><ul class="enrich-who">{who}</ul></div>'
            f'<div class="enrich-block enrich-faq"><span class="en">FAQ</span><h2>よくある質問</h2>{faq}</div>'
            + (f'<div class="enrich-block"><span class="en">Next</span><h2>あわせて読む・使う</h2><div class="enrich-more">{links}</div></div>' if links else "")
            + '</div>')


def _put(s, block, before_rx):
    s = re.sub(r"\n?<!-- enrich -->.*?<!-- /enrich -->\n?", "\n", s, flags=re.S)
    m = re.search(before_rx, s, re.S)
    if not m:
        return s
    return s[:m.start()] + f"<!-- enrich -->{block}<!-- /enrich -->\n" + s[m.start():]


def _about_links(s):
    m = re.search(r'<h2>(?:このチェックでわかること|このチェックについて|このツールについて|この診断について)</h2>(.*?)</section>', s, re.S)
    if not m:
        return []
    out = []
    for u, t in re.findall(r'href="(/[^"#]+)"[^>]*>([^<]+)<', m.group(1)):
        if u.startswith(("/author/",)) or (u, t) in out:
            continue
        out.append((u, t))
    return out


def apply(site: Path):
    n = 0
    for key, d in TOOLS.items():
        p = site / "tools" / key / "index.html"
        if not p.is_file():
            continue
        s = p.read_text(encoding="utf-8")
        s0 = s
        # ヒーローの写真（明るいヒーローは薄く敷く。暗いヒーローは動画の場所に写真を置く）
        s = re.sub(r'<div class="tool-hero-ph" aria-hidden="true">.*?</div>', "", s, flags=re.S)
        s = re.sub(r'<img class="lx-hero-video lx-hero-still"[^>]*>', "", s)
        if d.get("dark"):
            s = re.sub(r'(<section class="lx-hero[^"]*"[^>]*>)',
                       lambda m: m.group(1) + f'<img class="lx-hero-video lx-hero-still" src="{d["hero"]}" alt="{d.get('hero_alt', '利用場面')}のイメージ" aria-hidden="true">', s, count=1)
        else:
            s = re.sub(r'(<section class="hero"[^>]*>)',
                       lambda m: m.group(1) + f'<div class="tool-hero-ph" aria-hidden="true"><img src="{d["hero"]}" alt="{d.get('hero_alt', '利用場面')}のイメージ" decoding="async"></div>', s, count=1)
        more = _about_links(s) + d.get("more", [])
        block = _blocks(d, more)
        # 説明の区画（このチェックについて 等）の直前に入れる
        s = _put(s, block, r'<section class="section"[^>]*>\s*<div class="section-head">\s*<span class="en">About</span>|<section class="section"[^>]*>\s*(?:<div[^>]*>\s*)?<h2>(?:このチェックについて|このツールについて|この診断について|このチェックでわかること)</h2>')
        if s != s0:
            p.write_text(s, encoding="utf-8", newline="")
            n += 1
    p = site / "download" / "index.html"
    if p.is_file():
        s = p.read_text(encoding="utf-8")
        s0 = s
        # フォームの左に写真（中央の細いフォームの両脇が空いていた）
        if 'class="section dl-grid"' not in s:
            s = s.replace('<section class="section">\n  <!-- TODO: フォーム送信先の設定', '<section class="section dl-grid">\n  <figure><img src="' + DOWNLOAD["side"][0]
                          + '" alt="' + DOWNLOAD["side"][1] + 'のイメージ" width="1600" height="900" loading="lazy" decoding="async"></figure>\n  <!-- TODO: フォーム送信先の設定', 1)
        block = _blocks({**DOWNLOAD, "side": ("/images/shelf/subsidy-docs-1.webp", "資料を見ながら次の手を決める経営者")}, DOWNLOAD["more"])
        s = _put(s, block, r"<footer")
        if s != s0:
            p.write_text(s, encoding="utf-8", newline="")
            n += 1
    css = site / "css" / "style.css"
    c = css.read_text(encoding="utf-8")
    if "/* 無料ツール・資料ダウンロードの肉付け" not in c:
        css.write_text(c + CSS, encoding="utf-8")
    return n
