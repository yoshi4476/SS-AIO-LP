# -*- coding: utf-8 -*-
"""ご契約前のよくある質問（/faq/）。問い合わせをためらう理由（契約期間・解約・記事の品質・Google の罰則）に先に答える。

    python scripts/faq_page.py      # site/faq/index.html を作り直す（外枠は /tools/ のページを使う）

答えに書くのは、決まっている条件と登録済みの事実だけ。
  - 契約条件: 最低契約期間6か月・解約は1か月前までに連絡・解約後も記事とページは使い続けられる（2026-10-03 原口さん確認）
  - 実績の数字: data/first_party_facts.json に期間と件数つきで登録したものだけ
画面の答えと FAQPage の構造化データは、同じ一覧から作る（食い違うと検索エンジンに信頼されない）。
"""
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_URL = "https://ai.7senses.co.jp"
OUT = ROOT / "site" / "faq" / "index.html"
SPAM = "https://developers.google.com/search/docs/essentials/spam-policies"
AI_GUIDE = "https://developers.google.com/search/blog/2023/02/google-search-and-ai-content"

FAQ = [
    ("契約と料金", [
        ("最低契約期間はありますか？",
         "最低契約期間は6か月です。SEO・AI検索対策は、効果が出るまで6〜8か月が目安です。見通しは、現状分析の結果をもとに個別にお伝えします。"),
        ("解約はどうすればできますか？",
         "6か月を過ぎた後は、解約したい月の1か月前までにご連絡いただければ解約できます。メール（info.ai@7senses.co.jp）かお電話（06-4305-7547）でお知らせください。"),
        ("解約したら、書いた記事やページはどうなりますか？",
         "解約後も、そのまま使い続けられます。公開した記事や作ったページを、解約を理由に引き上げることはありません。"),
        ("契約の前に費用はかかりますか？",
         "かかりません。無料相談と現状分析レポートは無料で、ご契約前のキャンセルにも費用は発生しません。"),
        ("料金はいくらですか？",
         "業種・サイトの状態・記事の本数で変わるため、現状分析のあとに個別にお見積りします。必要な施策だけを組み合わせてご提案します。"),
        ("返金はありますか？",
         '提供済みの作業の返金はお受けしていません。<a href="/tokushoho/">特定商取引法に基づく表記</a>にも記載しています。'),
    ]),
    ("記事の品質", [
        ("AIが書いた記事で大丈夫ですか？",
         "記事は公開の前に、機械の検査（文字数・見出し・リンク切れ・表示の崩れなど）と、3つの観点の採点（そこにしか無い情報があるか・答えとして切り出せるか・読者が次の行動を決められるか）を通ります。"
         "各観点80点以上・総合90点以上に届かない記事は公開しません。"),
        ("事実と違うことを書かれませんか？",
         "公開した記事を書き直すときは、元の記事に無かった数字が増えたら機械が止めて元に戻します。当社や御社の実績の数字は、期間と件数をそろえて登録した事実だけを使います。"),
        ("1日に何本も記事を出して大丈夫ですか？",
         "1サイトにつき1日2本・月60本までと上限を決めています。検索エンジンへの登録の状況を毎週確かめ、量産と見られる兆候が出たら、自動で1日1本、さらに0本へと減らします。"),
    ]),
    ("Googleの罰則（ペナルティ）", [
        ("AIで作った記事は、Googleの罰則を受けませんか？",
         f'Googleは、AIを使ったかどうかではなく、内容が役に立つかで評価するとしています（<a href="{AI_GUIDE}" target="_blank" rel="noopener">Google の説明</a>）。'
         f'罰則の対象になるのは、検索順位を操作する目的で中身の薄いページを大量に作ることです（<a href="{SPAM}" target="_blank" rel="noopener">スパムに関するポリシー</a>の「大量生成されたコンテンツの不正使用」）。'
         "当社は、本数の上限と自動の減速でこの状態を避けています。"),
        ("口コミの代理投稿や購入はしますか？",
         "しません。規約違反になり、アカウントが削除されるおそれがあるためです。"),
    ]),
    ("成果と手間", [
        ("成果は保証されますか？",
         "検索の順位やアクセスはGoogleやAIの仕組みが決めるため、保証はしていません。代わりに毎月の数字で効き目を確かめ、レポートでお伝えします。"
         "なお、2026年5月から9月に契約したAIO運用15件のうち、3か月以内の解約は0件です。"),
        ("どのくらいで効果が出ますか？",
         "SEO・AI検索対策は6〜8か月が目安です。2026年5月にAIO運用を始めた10件では、10件すべてで3か月以内に主要な検索語の平均順位が開始時より上がりました（2026年5月〜8月の集計・わずかな上昇も含みます）。"),
        ("社内の手間はどれくらいかかりますか？",
         "最初に、料金の決まり方・対応エリア・実績など、御社にしか無い事実を教えていただきます。そのあとの記事の作成・公開・計測は当社で行い、毎月1日にレポート（PDF）をお送りします。"),
        ("今のホームページのままでも頼めますか？",
         "頼めます。WordPressのサイトにも記事を投稿できます。作り直しが必要かどうかは、現状分析でお伝えします。"),
        ("相談したら、しつこく営業されませんか？",
         "しつこい営業はしません。相談のあとにお送りするご案内メールは、「停止」とご返信いただければ止まります。"),
    ]),
]

TITLE = "ご契約前のよくある質問｜契約期間・解約・記事の品質・Googleの罰則"
DESC = ("最低契約期間（6か月）・解約の方法・解約後の記事の扱い・AIが書く記事の品質・Googleの罰則は大丈夫か、など、"
        "ご契約前によくいただく質問に答えます。")
E = html.escape


def plain(a):
    return re.sub(r"<[^>]+>", "", a)


def body():
    toc = "".join(f'<a href="#f{i}">{E(g)}</a>' for i, (g, _) in enumerate(FAQ, 1))
    secs = []
    for i, (g, qs) in enumerate(FAQ, 1):
        items = "".join(f'<details class="faq-item"><summary>{E(q)}</summary><p>{a}</p></details>' for q, a in qs)
        secs.append(f'<section class="faq-sec" id="f{i}"><h2>{E(g)}</h2>{items}</section>')
    return ('<section class="tools-head"><span class="kicker">FAQ</span><h1>ご契約前のよくある質問</h1>'
            '<p class="lead">契約期間・解約・記事の品質・Googleの罰則など、ご契約の前によくいただく質問に答えます。'
            'ここに無いことは、<a href="/lp/#form" data-cta="faq_head_consult">無料相談</a>でお気軽にお尋ねください。</p>'
            f'<nav class="qa-toc faq-toc" aria-label="質問の種類">{toc}</nav></section>'
            '<div class="faq-wrap">' + "".join(secs) + '</div>'
            '<section class="qa-cta faq-cta"><h2>まずは、今の状態を知るところから</h2>'
            '<p>現状分析は無料です。ご契約前に費用はかかりません。</p><p class="qa-btns">'
            '<a class="btn btn-primary" href="/lp/#form" data-cta="faq_consult">無料で相談する（現状分析つき）</a>'
            '<a class="btn btn-ghost" href="/tools/" data-cta="faq_tools">無料ツールで確かめる</a></p></section>')


def ld():
    faq = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": plain(a)}}
        for _, qs in FAQ for q, a in qs]}
    crumb = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "ホーム", "item": SITE_URL + "/"},
        {"@type": "ListItem", "position": 2, "name": "ご契約前のよくある質問", "item": SITE_URL + "/faq/"}]}
    return "".join('<script type="application/ld+json">\n' + json.dumps(x, ensure_ascii=False, indent=1) + "\n</script>\n"
                   for x in (crumb, faq))


def build():
    shell = (ROOT / "site" / "tools" / "index.html").read_text(encoding="utf-8")
    s = re.sub(r"<title>.*?</title>", f"<title>{E(TITLE)}</title>", shell, count=1, flags=re.S)
    s = re.sub(r'(<meta name="description" content=")[^"]*', lambda m: m.group(1) + E(DESC), s, count=1)
    s = re.sub(r'(<meta property="og:title" content=")[^"]*', lambda m: m.group(1) + E(TITLE), s, count=1)
    s = re.sub(r'(<meta property="og:description" content=")[^"]*', lambda m: m.group(1) + E(DESC), s, count=1)
    s = s.replace(f"{SITE_URL}/tools/\">", f"{SITE_URL}/faq/\">")
    s = re.sub(r'<script type="application/ld\+json".*?</script>\n?', "", s, flags=re.S)
    s = s.replace("</head>", ld() + "</head>", 1)
    s = re.sub(r'<nav class="breadcrumb".*?</nav>', '<nav class="breadcrumb" aria-label="パンくずリスト">\n  <ol>\n'
               '    <li><a href="/">ホーム</a></li>\n    <li aria-current="page">ご契約前のよくある質問</li>\n  </ol>\n</nav>',
               s, count=1, flags=re.S)
    a = s.index("</nav>", s.index('<nav class="breadcrumb"')) + len("</nav>")
    b = s.index('<footer class="site-footer">')
    s = s[:a] + "\n\n" + body() + "\n\n" + s[b:]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(s, encoding="utf-8", newline="\n")
    return OUT


if __name__ == "__main__":
    print(build())
