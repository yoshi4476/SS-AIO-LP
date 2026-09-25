# -*- coding: utf-8 -*-
"""ヒアリングシートを1枚埋めれば、クライアントの運用が立ち上がる

これまでは sites/*.json を手で書き、会社情報と一次情報を別の場所に足し、
KWの起点を考え、CTAを設定する、という作業が散らばっていた。順番も
決まっておらず、抜けたまま記事を作り始めて後から気づくことがあった。

ここでは聞くことを1枚にまとめ、埋まった時点で必要なものが全部そろう。
特に一次情報（その会社にしか出せない数値）は、AI検索に引用されるかを
決める材料なので、空のまま先へ進ませない。

    python scripts/client_intake.py --sheet              # 記入用シートを作る
    python scripts/client_intake.py <記入済み.xlsx>       # 内容を確認する
    python scripts/client_intake.py <記入済み.xlsx> --apply   # 登録まで行う
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "docs" / "client" / "ヒアリングシート.xlsx"
SITES = ROOT / "sites"
sys.path.insert(0, str(ROOT / "scripts"))
from client_add import TYPES  # noqa: E402  形式の定義は1か所に置く

# ── 聞くこと ────────────────────────────────────
# (キー, 見出し, 説明, 記入例, 必須)
# キーの先頭が "#" の行は見出しだけを置く区切り
FIELDS = [
    ("#basic", "1. 会社の基本情報", "記事の著者情報・構造化データ・レポートの宛名に使います。"
     "表記がぶれると別法人と混同されるため、登記どおりに書いてください。", "", False),
    ("company.name", "会社名（正式）", "登記上の表記。株式会社の位置も登記どおりに",
     "セブンセンシズ株式会社", True),
    ("company.name_en", "英語表記", "無ければ空欄で構いません", "SEVEN SENSES Inc.", False),
    ("company.corporate_number", "法人番号", "13桁。国税庁の法人番号公表サイトで確認できます",
     "3120001227825", False),
    ("company.postal", "郵便番号", "ハイフンあり", "537-0003", False),
    ("company.address", "住所", "建物名・部屋番号まで", "大阪府大阪市東成区神路1丁目7-4 ○○ビル901", True),
    ("company.tel", "電話番号", "記事とサイトに掲載する番号", "06-0000-0000", True),
    ("company.hours", "営業時間", "問い合わせを受けられる時間帯",
     "9:00〜20:00（土・日・祝日を除く）", False),
    ("company.founded", "創業年月日", "「○年の実績」と書けるかの判断に使います", "2020年3月10日", False),
    ("company.capital", "資本金", "補助金の要件判定にも使います", "500万円", False),
    ("company.ceo", "代表者名", "記事の著者情報に使います", "山田 太郎", False),
    ("company.email", "問い合わせメール", "レポートの送付先にもなります", "info@example.co.jp", True),

    ("#media", "2. メディアの設計", "どこに、どんな形で記事を出すか。"
     "配信先が別リポジトリの場合は、書き込み権限のあるトークンが別途必要です。", "", False),
    ("id", "サイトID", "英小文字とハイフンのみ。ファイル名に使います", "example-media", True),
    ("name", "メディア名", "記事一覧やレポートに出る名前", "○○の集客ラボ", True),
    ("domain", "公開ドメイン", "https:// は不要", "media.example.co.jp", True),
    ("repo", "配信先リポジトリ", "owner/repo の形式。自社ビルドなら空欄", "example/media-site", False),
    ("branch", "ブランチ", "通常は main", "main", False),
    ("type", "サイトの形式",
     "WordPressをお使いなら wordpress。当社で新規構築するなら self-static。"
     "既存の静的サイトへ配信する場合は external-html / external-md / nextjs-json",
     "wordpress", True),
    ("url_prefix", "記事URLの接頭辞",
     "記事が /blog/xxx/ に出るなら /blog。自社構築（self-static）以外は必ず記入", "/blog", False),
    ("content_dir", "記事の置き場所", "配信先リポジトリ内のパス", "src/content/blog", False),
    ("images_dir", "画像の置き場所", "同上", "public/images/blog", False),
    ("wp_api", "WordPressのAPIのURL",
     "形式が wordpress のときのみ。通常は空欄で構いません"
     "（https://ドメイン/wp-json/wp/v2 を自動で使います）", "", False),
    ("wp_note", "WordPressの管理情報",
     "形式が wordpress のときのみ。管理画面のURLと、"
     "アプリケーションパスワードを発行できる権限のユーザー名。"
     "パスワード自体はこのシートに書かず、別途お預かりします",
     "https://example.co.jp/wp-admin/ / ユーザー名: editor-bot", False),

    ("#offer", "3. 主力商材", "いちばん大切な項目です。ここが曖昧だと、"
     "表示回数は増えても問い合わせにつながらない記事が量産されます。", "", False),
    ("main_offer", "主力商材（1行）", "この記事群で最終的に売りたいもの",
     "経理BPO（記帳代行の受託）", True),
    ("main_category", "主力カテゴリ", "下のカテゴリ一覧のうち、主力商材に直結するもの",
     "keiri-bpo", True),
    ("categories", "カテゴリ一覧",
     "「slug: 表示名」を改行区切りで。slugは英小文字とハイフン",
     "keiri-bpo: 経理BPO\nkeiri-jitsumu: 経理実務\nbackoffice: バックオフィス", True),
    ("category_mix", "カテゴリの配分",
     "「slug: 割合」を改行区切り。合計100。主力を50%前後にすると相談につながりやすくなります",
     "keiri-bpo: 50\nkeiri-jitsumu: 40\nbackoffice: 10", False),

    ("#scope", "4. 対象読者と守備範囲", "「扱わない領域」を書いておくと、"
     "複数サイトを運用したときに記事同士が食い合うのを防げます。", "", False),
    ("theme", "何を扱うメディアか", "1行で", "中小企業の経理実務とバックオフィス効率化", True),
    ("audience", "誰に向けたものか", "1行で。役職や状況まで書けると精度が上がります",
     "経理担当が1〜2名の中小企業の経営者・管理部門責任者", True),
    ("owns", "自社が扱う語", "改行区切り。このメディアの守備範囲",
     "経理BPO\n記帳代行\n月次決算\n請求書処理", True),
    ("avoid", "扱わない領域", "改行区切り。理由も添えてください",
     "補助金の申請手続き（別サイトの担当領域のため）\n人材採用・労務", False),

    ("#kw", "5. キーワードの起点", "業種 × 意図の組み合わせで記事のテーマを作ります。"
     "200通り以上あると、半年ほど書き続けてもテーマが枯れません。", "", False),
    ("kw_seeds.industries", "業種・対象", "改行区切り。20件以上を目安に",
     "製造業\n建設業\n飲食店\nクリニック\n士業事務所", True),
    ("kw_seeds.intents", "検索の意図", "改行区切り。10件以上を目安に",
     "費用\nやり方\n選び方\n比較\n失敗事例\n対象条件", True),

    ("#facts", "6. 一次情報（最重要）",
     "その会社にしか出せない数値です。AI検索が最も引用したがる材料で、"
     "ここが空だと「どこにでもある記事」になり引用されません。"
     "確認できない数値は書かないでください（書いた時点で信頼を失います）。", "", False),
    ("facts.1.claim", "実績・数値 ①", "記事にそのまま書ける一文で",
     "経理BPOで通算120社の月次決算を受託してきました", True),
    ("facts.1.source", "① の出典", "自社実績 / 自社調査 / 顧客アンケート など", "自社実績", True),
    ("facts.1.as_of", "① の時点", "YYYY-MM。古い数値は使われません", "2026-09", True),
    # 割合（◯%・◯割）は母数と集計期間が無いと登録しない（景品表示法・根拠の明示。add_fact と同じ検査）
    ("facts.1.denominator", "① の母数",
     "割合（◯%・◯割）を書く場合のみ。「何社中何社か」の何社を数字で。一文の中にも同じ数を書いてください",
     "42", False),
    ("facts.1.period", "① の集計期間",
     "割合を書く場合のみ。一文の中にも期間を書いてください", "2025-04〜2026-03", False),
    ("facts.2.claim", "実績・数値 ②", "", "導入企業の月次決算が平均6営業日短縮しました", False),
    ("facts.2.source", "② の出典", "", "自社調査（受託42社・2025年実績）", False),
    ("facts.2.as_of", "② の時点", "", "2026-09", False),
    ("facts.2.denominator", "② の母数", "割合を書く場合のみ", "", False),
    ("facts.2.period", "② の集計期間", "割合を書く場合のみ", "", False),
    ("facts.3.claim", "実績・数値 ③", "", "", False),
    ("facts.3.source", "③ の出典", "", "", False),
    ("facts.3.as_of", "③ の時点", "", "", False),
    ("facts.3.denominator", "③ の母数", "割合を書く場合のみ", "", False),
    ("facts.3.period", "③ の集計期間", "割合を書く場合のみ", "", False),
    ("facts.note", "事例・体験",
     "数値でなくても、現場で見てきたことがあれば。記事の一人称パートに使います",
     "担当者が1人の会社ほど、退職時に業務が止まるリスクを挙げられます", False),

    ("#cta", "7. リード導線", "記事を読んだ人がどこへ進むか。"
     "全記事に必ず2箇所以上入れます。", "", False),
    ("cta.label", "ボタンの文言", "行動が分かる言葉で。「お問い合わせ」より具体的に",
     "経理の現状分析（無料）", True),
    ("cta.url", "遷移先URL", "問い合わせフォームやLPのURL",
     "https://example.co.jp/contact/", True),
    ("cta_title", "記事下の見出し", "", "経理の負担、どこから減らせるか見てみませんか", False),
    ("cta_desc", "記事下の説明文", "", "現状を伺ったうえで、外に出せる業務を整理してご提案します。", False),
    ("cta.note", "補足", "「ご契約を前提としたご案内ではありません」など安心材料",
     "ご契約を前提としたご案内ではありません", False),

    ("#measure", "8. 計測とレポート", "数字が取れないと改善の判断ができません。"
     "GA4とSearch Consoleへの権限付与をお願いします。", "", False),
    ("ga4_property_id", "GA4プロパティID", "数字のみ。管理画面 > 管理 > プロパティの詳細",
     "123456789", False),
    ("report_to", "レポートの送付先", "複数ある場合はカンマ区切り", "info@example.co.jp", False),
    ("gsc_ready", "Search Consoleの権限付与", "済 / 未 で記入。未の場合は導入時にご案内します",
     "未", False),

    ("#rule", "9. 運用のきまり", "業種による表現規制や、公開前の確認が必要かどうか。", "", False),
    ("monthly_cap", "月の公開本数", "既定は60本（1日2本）。減らす場合は数字を記入", "60", False),
    ("review_before_publish", "公開前の確認",
     "要 / 不要。医療・金融など表現規制のある業種では「要」を推奨します", "不要", False),
    ("ng_words", "使ってはいけない表現",
     "改行区切り。薬機法・景表法などで避ける語があれば",
     "完治\n必ず治る\n日本一", False),
    ("note", "その他の申し送り", "競合、過去の施策、社内の事情など何でも", "", False),
]


# ── 狙う語と読者 ──────────────────────────────
# 業種×意図の掛け合わせ（5番）だけだと、機械的な組み合わせしか出ない。
# 実際に取りたい語と、その周辺語をここで受け取り、主題を作る材料にする。
KEYWORD = [
    ("#target", "5-1. ターゲット（誰に読ませるか）",
     "「誰に」がぼやけると、読まれても相談につながりません。"
     "1人の顔が浮かぶくらい具体的に書いてください。", "", False),
    ("target.persona", "いちばん来てほしいお客様",
     "年齢・立場・状況を1〜2文で。社内で呼んでいる呼び方でも構いません",
     "従業員20〜50名の会社で、経理をひとりで担当している40代の管理部長。"
     "決算期に毎年残業が続いている", True),
    ("target.second", "その次に来てほしい層",
     "無ければ空欄。2つ目の読者像があれば記事の幅が広がります",
     "これから経理担当を採用しようとしている経営者", False),
    ("target.area", "商圏・エリア",
     "地域名を含む検索を狙うかの判断に使います。全国対応なら「全国」",
     "大阪市内を中心に、京阪神エリア", False),
    ("target.stage", "検討の段階",
     "まだ困りごとを調べている段階か、業者を比べている段階か。"
     "記事の書き方が変わります",
     "困りごとを調べ始めた段階の人が多い（比較検討はまだ先）", False),
    ("target.decide", "決め手になること",
     "改行区切り。最後に何で選ばれるか",
     "対応の速さ\n担当者が変わらないこと\n見積の分かりやすさ", False),

    ("#kw", "5-2. 狙うキーワード",
     "実際に取りたい語を教えてください。ここを起点に、"
     "掛け合わせて記事の主題を作ります。思いつく範囲で構いません。", "", False),
    ("kw.main", "メインキーワード",
     "改行区切りで3〜5個。事業の柱になる、いちばん取りたい語",
     "経理代行\n記帳代行\n経理アウトソーシング", True),
    ("kw.sub", "サブキーワード",
     "改行区切り。メインと一緒に検索される語、言い換え、略称、"
     "お客様が使う言い方",
     "経理 外注\n経理 丸投げ\n記帳 代行 料金\n月次決算 早期化\n経理 属人化", True),
    ("kw.area_word", "地域を付けて狙う語",
     "改行区切り。「大阪 経理代行」のように地域名を付けたい語があれば",
     "経理代行 大阪\n記帳代行 梅田", False),
    ("kw.exclude", "狙わない語",
     "改行区切り。対応できない業務や、来てほしくない層が使う語",
     "経理 求人\n経理 資格\n無料 テンプレート", False),
    ("kw.known", "すでに上位に出ている語",
     "改行区切り。分かる範囲で。既存サイトがある場合のみ",
     "", False),
    ("languages", "多言語の要約ページ",
     "改行区切りで en（英語）/ zh（中国語）/ ko（韓国語）。空なら作らない（既定）。"
     "記事の要点（題名・冒頭・各見出しの1文結論・FAQ）だけを訳したページを別URLに置き、日本語の記事と結びます",
     "", False),
]

# ── 記事を書くための材料 ────────────────────────
# ここから下は、埋まっているほど記事の中身が濃くなる。空でも記事は出るが、
# 「どこにでもある記事」になり、AI検索にも引用されず問い合わせにもつながらない。
WRITING = [
    ("#service", "10. 商品・サービスの中身",
     "記事の結論を「で、何を頼めばいいのか」まで書くための材料です。"
     "ここが空だと、一般論で終わる記事になります。", "", False),
    ("service.list", "提供しているもの",
     "改行区切り。メニュー・プラン・サービス名を具体的に",
     "記帳代行\n月次決算の代行\n給与計算\n請求書発行の代行", True),
    ("service.price", "価格帯", "記事に載せてよい範囲で。「応相談」でも構いません",
     "月額3万円〜（仕訳数と業務範囲による）", False),
    ("service.area", "提供エリア", "地域名を書くと、地域名を含む検索で拾えます",
     "大阪府全域・兵庫県南部（オンラインは全国）", False),
    ("service.strength", "他社と違う点",
     "改行区切りで3つ。「安い・早い・丁寧」ではなく、具体的な事実で",
     "税理士と連携し申告まで一貫して対応できる\n初月は並行稼働して引き継ぎ漏れを防ぐ\n"
     "業務フローの図を作って納品する", True),
    ("service.flow", "依頼から開始までの流れ", "記事の「次にやること」に使います",
     "問い合わせ → 現状のヒアリング（60分）→ 見積 → 契約 → 並行稼働1ヶ月 → 本稼働", False),

    ("#customer", "11. お客様のこと",
     "検索する人が何に困っているかが分かると、記事の入口が決まります。"
     "よくある質問はそのままFAQとして記事に載ります。", "", False),
    ("customer.problem", "お客様が困っていること",
     "改行区切りで3つ以上。相談時に実際に言われる言葉で",
     "経理担当が1人しかいなくて、休まれると業務が止まる\n"
     "月次決算が翌月20日を過ぎてしまい、判断が遅れる\n"
     "インボイスと電帳法の対応が追いつかない", True),
    ("customer.faq", "よく聞かれる質問",
     "改行区切りで5つ以上。そのままFAQとして記事に載ります",
     "どこまでの業務を任せられますか\n社内に何も残らなくなりませんか\n"
     "契約期間の縛りはありますか\n途中で範囲を変えられますか\n"
     "うちの会計ソフトのままで対応できますか", True),
    ("customer.trigger", "問い合わせのきっかけ",
     "どんなときに相談が来るか。記事を出す時期の判断に使います",
     "経理担当の退職が決まったとき / 決算期の前 / 税理士に指摘されたとき", False),
    ("customer.ng", "よくある誤解",
     "改行区切り。記事で先回りして解いておくと、相談の質が上がります",
     "丸投げすると社内が何も分からなくなる、と思われがちです\n"
     "大企業向けだと思われがちです", False),

    ("#author", "12. 記事の書き手",
     "誰が書いたか分からない記事は、検索エンジンにもAIにも信用されません。"
     "実在する方のお名前と肩書きをお願いします。", "", False),
    ("author.name", "著者名", "記事に表示するお名前", "山田 太郎", True),
    ("author.title", "肩書き", "", "セブンセンシズ株式会社 経理BPO事業責任者", True),
    ("author.credential", "保有資格・経歴",
     "改行区切り。専門性の裏づけになるもの",
     "日商簿記1級\n上場企業の経理部で10年\n中小企業の経理支援を通算120社", False),
    ("author.supervisor", "監修者", "別の方が監修する場合のみ。資格も添えてください",
     "佐藤 花子（税理士・登録番号00000）", False),

    ("#tone", "13. 書き方のきまり",
     "文体や言い回しを揃えるための指定です。既存サイトがある場合は、"
     "そちらに合わせます。", "", False),
    ("tone.person", "自社の呼び方", "記事中の一人称", "当社", False),
    ("tone.style", "文体", "ですます / だ・である", "ですます", False),
    ("tone.level", "専門用語の扱い",
     "初心者向け（都度説明）/ 実務者向け（説明は最小限）",
     "初心者向け（都度説明）", False),
    ("tone.avoid", "使いたくない表現",
     "改行区切り。社内で避けている言い回しがあれば",
     "丸投げ\nお任せください", False),

    ("#compete", "14. 競合",
     "競合が書いていないことを書くために聞きます。"
     "同じ内容を書いても、後から出した側は上位に出ません。", "", False),
    ("compete.sites", "競合のサイト",
     "改行区切りでURL。3つほど", "https://example-a.co.jp\nhttps://example-b.co.jp", False),
    ("compete.diff", "競合にはない自社の強み",
     "上の「他社と違う点」と重なっても構いません。競合を見たうえでの差",
     "地域密着で訪問できる点。競合は全国対応だが訪問はしない", False),

    ("#asset", "15. すでにあるもの",
     "作り直しになるか、活かせるかの判断に使います。", "", False),
    ("asset.site", "既存サイト", "URL。無ければ空欄", "https://example.co.jp", False),
    ("asset.articles", "既存の記事数", "おおよその本数", "15本", False),
    ("asset.sns", "運用中のSNS", "改行区切り", "X: @example\nInstagram: example", False),
    ("asset.gbp", "Googleビジネスプロフィール",
     "登録済み / 未登録。店舗がある場合は重要です", "登録済み", False),
]


BACKLINK = [
    ("#backlink", "20. 外部との接点（被リンクの起点）",
     "他サイトからリンクされている数は、検索順位にもAI検索での信頼にも効きます。"
     "ただし買うことはできません（ペナルティの対象です）。"
     "現実的なのは、すでにある関係を掘り起こすことです。"
     "ここは思い出せる範囲で構いません。", "", False),
    ("link.orgs", "加盟している団体・協会",
     "改行区切り。会員一覧ページからリンクされていることが多く、"
     "いちばん確実な起点です",
     "大阪商工会議所\n全国経理協会\n地元の商店会", False),
    ("link.portals", "掲載中のポータル・媒体",
     "改行区切り。業界ポータル、比較サイト、求人媒体など",
     "エキテン\n比較ビズ\nマイナビ転職", False),
    ("link.partners", "取引先・パートナー",
     "改行区切り。実績紹介や導入事例として載せてもらえる相手",
     "○○システム株式会社（販売代理）\n△△税理士事務所（提携）", False),
    ("link.awards", "受賞歴・認定・表彰",
     "改行区切り。認定機関のサイトに掲載されることがあります",
     "健康経営優良法人2025\n大阪府の○○認定事業者", False),
    ("link.press", "取材・メディア掲載の実績",
     "改行区切り。過去のものでも構いません",
     "日経新聞 2024年5月（地域面）\n業界誌○○ 2025年3月号", False),
    ("link.release", "プレスリリースの配信",
     "配信したことがあるか、使っている媒体",
     "PR TIMESで年2回ほど配信", False),
    ("link.gov", "自治体・公的機関との関わり",
     "支援制度の活用事例、講師派遣、委員など。"
     "公的機関からのリンクは評価が高くなります",
     "市の補助金の採択事例として掲載\n商工会のセミナー講師", False),
    ("link.person", "代表者・担当者の発信",
     "改行区切り。個人の登壇・寄稿・SNSも起点になります",
     "業界セミナーで年3回登壇\nnoteで月1回執筆", False),
    ("link.writable", "寄稿できそうな媒体",
     "書けそうな先の心当たり。無ければ空欄で構いません",
     "業界誌○○（編集部に知人あり）", False),
    ("link.known", "すでに把握している被リンク",
     "改行区切りでURL。分かる範囲で。分からなければ当社で調べます",
     "", False),
]

INDUSTRY_LINK_restaurant = [
    ("#food_link", "21. 飲食店の外部掲載【飲食店】",
     "グルメサイトと地図サービスは、来店にも検索評価にも直結します。"
     "登録済みかどうかだけでも教えてください。", "", False),
    ("flink.gourmet", "登録中のグルメサイト",
     "改行区切り。店舗ページのURLが分かれば添えてください",
     "食べログ\nぐるなび\nホットペッパーグルメ\nRetty", False),
    ("flink.map", "Googleビジネスプロフィールの状況",
     "オーナー確認済みか、口コミ数、返信しているか",
     "オーナー確認済み・口コミ82件・返信は未対応", False),
    ("flink.sns", "SNSアカウント",
     "改行区切り。フォロワー数も分かれば",
     "Instagram @example（1,200人）\nX @example（300人）", False),
    ("flink.local", "地域のポータル・観光協会",
     "改行区切り。市区町村の観光サイト、商店会のページなど",
     "○○市観光協会の飲食店一覧\n△△商店会のサイト", False),
    ("flink.media", "グルメ媒体の取材",
     "雑誌・テレビ・地域情報誌など。過去のものでも",
     "関西ウォーカー 2024年11月号", False),
]

# ── 業種別に追加で聞くこと ──────────────────────
# 業種が変われば、記事に必要な材料も変わる。飲食店に「仕訳数」を聞いても
# 意味がなく、経理代行に「席数」を聞いても意味がない
INDUSTRY_LINK = {"restaurant": INDUSTRY_LINK_restaurant}

INDUSTRY = {
    "restaurant": ("飲食店", [
        ("#shop", "16. 店舗の基本【飲食店】",
         "地域名を含む検索（「梅田 居酒屋 個室」など）で拾うための情報です。"
         "ここが具体的なほど、来店につながる記事が書けます。", "", False),
        ("shop.type", "業態", "居酒屋 / カフェ / レストラン / 焼肉 / ラーメン など",
         "居酒屋（海鮮中心）", True),
        ("shop.seats", "席数", "カウンター・テーブル・個室の内訳も書けると理想です",
         "42席（カウンター8・テーブル24・個室10）", True),
        ("shop.budget", "客単価", "昼と夜で分けて", "昼1,200円 / 夜4,500円", True),
        ("shop.hours", "営業時間・定休日", "",
         "11:30〜14:00 / 17:00〜23:00、日曜定休", True),
        ("shop.access", "最寄駅と徒歩分数", "複数路線あれば全部",
         "JR大阪駅 徒歩6分 / 地下鉄梅田駅 徒歩4分", True),
        ("shop.parking", "駐車場", "有無と台数、提携の有無", "なし（近隣コインパーキング）", False),
        ("shop.capacity", "貸切・団体の可否",
         "最大人数も。宴会需要の記事に使います", "最大30名まで貸切可", False),
        ("shop.smoking", "喫煙・禁煙", "", "全席禁煙（店外に喫煙所）", False),
        ("shop.kids", "お子様連れ対応",
         "ベビーカー・子ども椅子・おむつ替え", "子ども椅子あり、ベビーカー入店可", False),

        ("#menu", "17. メニューと食材【飲食店】",
         "「何がおいしいのか」を書けないと、どの店の記事か分からなくなります。"
         "AI検索も、固有の食材名や産地を手がかりに引用します。", "", False),
        ("menu.signature", "看板メニュー",
         "改行区切りで3つ。価格も添えてください",
         "本日の鮮魚5種盛り 1,880円\n炭焼き金目鯛の煮付け 2,200円\n自家製さつま揚げ 680円", True),
        ("menu.ingredient", "食材のこだわり・産地",
         "改行区切り。仕入れ先や産地は、そこにしかない情報になります",
         "鮮魚は明石浦漁港から毎朝直送\n米は兵庫県産コシヒカリ", True),
        ("menu.course", "コース・宴会プラン", "価格と品数、飲み放題の有無",
         "宴会コース 4,000円（8品・2時間飲み放題付）", False),
        ("menu.drink", "ドリンクの特徴", "日本酒の銘柄数、クラフトビールなど",
         "日本酒は常時20種類。月替わりの地酒あり", False),
        ("menu.allergy", "アレルギー・食事制限への対応",
         "対応可否。検索されやすい項目です",
         "アレルギー対応可（事前予約制）。ベジタリアン対応は要相談", False),
        ("menu.takeout", "テイクアウト・デリバリー",
         "有無と対応メニュー、利用サービス",
         "テイクアウトあり（弁当・オードブル）。デリバリーはUber Eats", False),

        ("#attract", "18. 集客と予約【飲食店】",
         "記事から予約までの導線を作るために聞きます。", "", False),
        ("attract.reserve", "予約の受付方法",
         "電話・ネット・アプリ。記事のCTAに直結します",
         "電話 / 食べログ / 公式LINE", True),
        ("attract.now", "いまの集客経路",
         "改行区切り。割合が分かれば添えてください",
         "食べログ 4割\n通りがかり 3割\nInstagram 2割\n紹介 1割", False),
        ("attract.target", "来てほしいお客様",
         "記事の読者像になります",
         "会社帰りの30〜50代。接待や歓送迎会の幹事", True),
        ("attract.want", "埋めたい時間帯・曜日",
         "記事のテーマの優先順位に使います", "平日の昼と、月〜水の夜", False),
        ("attract.season", "繁忙期・閑散期",
         "記事を出す時期の設計に使います",
         "繁忙: 12月・3月・歓送迎会シーズン / 閑散: 1月・2月・8月", False),
        ("attract.event", "季節の催し",
         "改行区切り。記事のネタとして毎年使えます",
         "1月 ふぐコース\n5月 初鰹フェア\n9月 秋刀魚まつり", False),

        ("#food_rule", "19. 表示のきまり【飲食店】",
         "飲食店の記事は景品表示法・食品表示法に触れやすい領域です。"
         "書ける表現と書けない表現をあらかじめ確認します。", "", False),
        ("food.claim", "使ってよい表現",
         "根拠のあるものだけ。改行区切り",
         "明石浦漁港から毎朝直送（仕入伝票あり）\n創業35年", False),
        ("food.ng", "使えない表現",
         "根拠のない最上級・健康効果の断定は景表法・薬機法に触れます",
         "日本一\n最高級\n血圧が下がる\n体に良い", False),
        ("food.cert", "資格・認証",
         "改行区切り。記事の信頼性の裏づけになります",
         "食品衛生責任者\nふぐ調理師免許\nHACCP対応済み", False),
    ]),
}

SAMPLE_ROW = 4          # 記入欄の開始行（1-2行目は説明、3行目は見出し）


# ============================================================
# シートを作る
# ============================================================
def fields_for(industry=""):
    """そのシートで聞く項目。共通＋書くための材料＋（あれば）業種別"""
    # ターゲットと狙う語は「5. キーワードの起点」の直後に差し込む。
    # 聞く順序がそのまま考える順序になる
    base = list(FIELDS)
    at = next((i for i, f in enumerate(base) if f[0] == "#facts"), len(base))
    out = base[:at] + list(KEYWORD) + base[at:] + list(WRITING) + list(BACKLINK)
    if industry:
        if industry not in INDUSTRY:
            raise SystemExit(f"未対応の業種です（{' / '.join(INDUSTRY)}）")
        out += INDUSTRY[industry][1]
        out += INDUSTRY_LINK.get(industry, [])
    return out


def make_sheet(path=SHEET, industry=""):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "ヒアリングシート"
    navy = "0B2447"
    thin = Side(style="thin", color="D8DEE7")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    label = INDUSTRY[industry][0] if industry else ""
    ws["A1"] = "オウンドメディア運用 ヒアリングシート" + (f"【{label}向け】" if label else "")
    ws["A1"].font = Font(name="游ゴシック", size=16, bold=True, color=navy)
    ws["A2"] = ("水色の欄にご記入ください。「必須」の行が埋まれば運用を開始できます。"
                "分からない項目は空欄のままで構いません（導入時に一緒に決めます）。")
    ws["A2"].font = Font(name="游ゴシック", size=10, color="5B6B84")
    ws.merge_cells("A1:D1")
    ws.merge_cells("A2:D2")

    head = ["項目", "ご記入欄", "必須", "説明・記入例"]
    for i, h in enumerate(head, 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = Font(name="游ゴシック", size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color=navy)
        c.alignment = Alignment(vertical="center")
        c.border = border
    ws.row_dimensions[3].height = 22

    r = SAMPLE_ROW
    for key, label, desc, ex, req in fields_for(industry):
        if key.startswith("#"):
            c = ws.cell(row=r, column=1, value=label)
            c.font = Font(name="游ゴシック", size=11, bold=True, color=navy)
            c.fill = PatternFill("solid", start_color="E9EFF7")
            for col in range(1, 5):
                ws.cell(row=r, column=col).fill = PatternFill("solid", start_color="E9EFF7")
                ws.cell(row=r, column=col).border = border
            d = ws.cell(row=r, column=4, value=desc)
            d.font = Font(name="游ゴシック", size=9, color="5B6B84")
            d.alignment = Alignment(wrap_text=True, vertical="center")
            ws.row_dimensions[r].height = 30
            r += 1
            continue
        ws.cell(row=r, column=1, value=label).font = Font(name="游ゴシック", size=10)
        inp = ws.cell(row=r, column=2)
        inp.fill = PatternFill("solid", start_color="EEF6FD")
        inp.alignment = Alignment(wrap_text=True, vertical="top")
        rq = ws.cell(row=r, column=3, value="必須" if req else "")
        rq.font = Font(name="游ゴシック", size=9, bold=True,
                       color="B42318" if req else "5B6B84")
        rq.alignment = Alignment(horizontal="center", vertical="center")
        note = desc + (f"\n例）{ex}" if ex else "")
        n = ws.cell(row=r, column=4, value=note)
        n.font = Font(name="游ゴシック", size=9, color="5B6B84")
        n.alignment = Alignment(wrap_text=True, vertical="top")
        for col in range(1, 5):
            ws.cell(row=r, column=col).border = border
        ws.row_dimensions[r].height = 34 if "\n" in note else 22
        # キーは右端の隠し列に置く。読み取り時に見出しの表記ゆれで壊れないため
        ws.cell(row=r, column=6, value=key)
        r += 1

    dv = DataValidation(type="list", formula1='"wordpress,self-static,external-md,external-html,nextjs-json"')
    ws.add_data_validation(dv)
    for row in range(SAMPLE_ROW, r):
        if ws.cell(row=row, column=6).value == "type":
            dv.add(ws.cell(row=row, column=2))
    yn = DataValidation(type="list", formula1='"要,不要"')
    ws.add_data_validation(yn)
    for row in range(SAMPLE_ROW, r):
        if ws.cell(row=row, column=6).value == "review_before_publish":
            yn.add(ws.cell(row=row, column=2))

    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 42
    ws.column_dimensions["C"].width = 6
    ws.column_dimensions["D"].width = 62
    ws.column_dimensions["F"].hidden = True
    ws.freeze_panes = "A4"
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ============================================================
# シートを読む
# ============================================================
def read_sheet(path):
    from openpyxl import load_workbook
    ws = load_workbook(path, data_only=True).active
    got = {}
    for row in range(SAMPLE_ROW, ws.max_row + 1):
        key = ws.cell(row=row, column=6).value
        if not key or str(key).startswith("#"):
            continue
        v = ws.cell(row=row, column=2).value
        if v is None or str(v).strip() == "":
            continue
        got[str(key)] = str(v).strip()
    return got


def lines(v):
    return [x.strip() for x in re.split(r"[\n\r]+", v or "") if x.strip()]


def pairs(v, num=False):
    """「slug: 表示名」の並びを辞書にする"""
    out = {}
    for ln in lines(v):
        if ":" not in ln and "：" not in ln:
            continue
        k, _, val = ln.replace("：", ":").partition(":")
        val = val.strip()
        out[k.strip()] = int(re.sub(r"[^0-9]", "", val) or 0) if num else val
    return out


def to_config(got):
    """シートの回答を sites/<id>.json の形に組み立てる"""
    cfg = {
        "id": got.get("id", ""),
        "name": got.get("name", ""),
        "domain": got.get("domain", "").replace("https://", "").rstrip("/"),
        "repo": got.get("repo", ""),
        "branch": got.get("branch", "main"),
        "type": got.get("type", "external-html"),
        "ga4_property_id": got.get("ga4_property_id", ""),
        "kw_plan": f"docs/kw-{got.get('id', 'client')}.md",
        "theme": got.get("theme", ""),
        "audience": got.get("audience", ""),
        "owns": lines(got.get("owns")),
        "avoid": lines(got.get("avoid")),
        # 多言語は指示のある社だけ（空なら作らない）
        "languages": languages(got.get("languages"))[0],
        "categories": pairs(got.get("categories")),
        "kw_seeds": {"industries": lines(got.get("kw_seeds.industries")),
                     "intents": lines(got.get("kw_seeds.intents"))},
        "main_offer": got.get("main_offer", ""),
        "main_category": got.get("main_category", ""),
        "cta": {"label": got.get("cta.label", ""), "url": got.get("cta.url", ""),
                "note": got.get("cta.note", "")},
    }
    # 接頭辞は既定を補わない。空のまま "/blog" を入れると、実際の記事URLと違う
    # URLが sitemap・内部リンク・通知に出る。自社構築は カテゴリ/slug で組むので持たせない
    prefix = (got.get("url_prefix") or "").strip().strip("/")
    if cfg["type"] != "self-static" and prefix:
        cfg["url_prefix"] = "/" + prefix
    # note（社内事情）と report_to（担当者のメール）は sites/ に書かない。
    # sites/*.json は public リポジトリにコミットされる。private.json に分ける（to_private）
    for k in ("content_dir", "images_dir", "cta_title", "cta_desc", "wp_api"):
        if got.get(k):
            cfg[k] = got[k]
    mix = pairs(got.get("category_mix"), num=True)
    if mix:
        cfg["category_mix"] = mix
    # 運用のきまり。既定と違うときだけ持たせる
    rule = {}
    if got.get("monthly_cap") and got["monthly_cap"] != "60":
        rule["monthly_cap"] = int(re.sub(r"[^0-9]", "", got["monthly_cap"]) or 60)
    if got.get("review_before_publish", "").startswith("要"):
        rule["review_before_publish"] = True
    if lines(got.get("ng_words")):
        rule["ng_words"] = lines(got["ng_words"])
    if rule:
        cfg["rules"] = rule
    return cfg


def to_private(got):
    """公開リポジトリに置けないもの（担当者のメール・社内の申し送り）。
    data/clients/<id>/private.json に書き、.gitignore で外す"""
    out = {}
    if got.get("report_to"):
        out["report_to"] = [x.strip() for x in got["report_to"].replace("、", ",").split(",")
                            if x.strip()]
    if got.get("note"):
        out["note"] = got["note"]
    return out


LANGS = ("en", "zh", "ko")


def languages(v):
    """多言語の指定を読む。(拾えた言語, 拾えなかった語) を返す。
    「en（英語）」「en, zh, ko」「EN」のように書かれても拾う。
    完全一致だけで見ていたため、こう書いた社の指定が黙って捨てられていた"""
    got, bad = [], []
    for w in re.split(r"[\s,，、/／・]+", v or ""):
        if not w:
            continue
        m = re.match(r"(en|zh|ko)(?![a-z])", w, re.I)
        if m:
            if m.group(1).lower() not in got:
                got.append(m.group(1).lower())
        elif not re.fullmatch(r"[（(].*[)）]", w):
            bad.append(w)
    return got, bad



def subjects(got, limit=60):
    """メイン × サブ × 意図 から、記事の主題になる語を組み立てる。

    メインだけでは本数が足りず、業種×意図の機械的な掛け合わせだけでは
    お客様が実際に使う言い方から離れる。両方を掛けると、
    「その事業で実際に検索される語」に近いものが出る。

    ここで出すのは候補。実際に書くかは kw_guard（食い合い）と
    kw_intent（開く理由）を通してから決める。
    """
    main = lines(got.get("kw.main"))
    sub = lines(got.get("kw.sub"))
    area = lines(got.get("kw.area_word"))
    intents = lines(got.get("kw_seeds.intents"))
    inds = lines(got.get("kw_seeds.industries"))
    exclude = [x for x in lines(got.get("kw.exclude")) if x]

    out, seen = [], set()

    def push(kw, why):
        kw = re.sub(r"[ 　]+", " ", kw).strip()
        if not kw or kw in seen:
            return
        # 狙わない語に含まれる言葉が入っていたら捨てる
        for ng in exclude:
            if any(w and w in kw for w in re.split(r"[ 　]+", ng)):
                return
        seen.add(kw)
        out.append({"keyword": kw, "from": why})

    # サブキーワードは、お客様が実際に使う言い方。そのまま主題になる
    for s in sub:
        push(s, "サブKW")
    # メイン × 意図。事業の柱を意図ごとに割る
    for m in main:
        for i in intents[:12]:
            # メインに既に入っている語を足すと「梅田 個室 居酒屋 個室」になる
            if i in m:
                continue
            push(f"{m} {i}", "メインKW×意図")
    # 地域を付けて狙う語
    for a in area:
        push(a, "地域KW")
    # メイン × 業種。誰向けかで割る
    for m in main[:3]:
        for ind in inds[:10]:
            if ind in m:
                continue
            push(f"{ind} {m}", "メインKW×業種")
    return out[:limit]


def to_brief(got, industry=""):
    """記事を書くときに読む材料。sites/*.json は配信の設定なので分けて持つ"""
    def pick(prefix):
        return {k.split(".", 1)[1]: v for k, v in got.items()
                if k.startswith(prefix + ".")}
    brief = {
        "_readme": "記事を書くときに読む材料。ここが埋まっているほど、"
                   "その会社にしか書けない記事になる。空の項目は無理に埋めず、"
                   "分かった時点で足すこと（憶測で書くと事実と違う記事になる）。",
        "industry": industry,
        "service": pick("service"),
        "customer": pick("customer"),
        "author": pick("author"),
        "tone": pick("tone"),
        "compete": pick("compete"),
        "asset": pick("asset"),
        "backlink": pick("link"),
        "target": pick("target"),
        "keyword": pick("kw"),
        "subjects": subjects(got),
    }
    for pre in set(k.split(".")[0] for k in got if "." in k):
        if pre in ("company", "facts", "cta", "kw_seeds", "service", "customer",
                   "author", "tone", "compete", "asset", "link", "target", "kw"):
            continue
        brief.setdefault("industry_detail", {})[pre] = pick(pre)
    # 改行区切りで書かれたものは配列にしておく。記事側で1つずつ使える
    multi = {"backlink": ["orgs", "portals", "partners", "awards", "press",
                         "gov", "person", "known"],
             "target": ["decide"],
             "keyword": ["main", "sub", "area_word", "exclude", "known"],
             "service": ["list", "strength"],
             "customer": ["problem", "faq", "ng"],
             "author": ["credential"], "tone": ["avoid"],
             "compete": ["sites"], "asset": ["sns"]}
    for sec, keys in multi.items():
        for k in keys:
            if brief.get(sec, {}).get(k):
                brief[sec][k] = lines(brief[sec][k])
    for sec in (brief.get("industry_detail") or {}).values():
        for k, v in list(sec.items()):
            if isinstance(v, str) and chr(10) in v:
                sec[k] = lines(v)
    return brief


def to_company(got):
    out = {k.split(".", 1)[1]: v for k, v in got.items() if k.startswith("company.")}
    if out:
        out["_readme"] = ("この会社の正規表記。記事の著者情報・構造化データ・"
                          "レポートの宛名はすべてここを参照する。表記がぶれると"
                          "検索エンジンが同名の別法人と混同する。")
    return out


def to_facts(got, site_id):
    out = []
    for i in ("1", "2", "3"):
        claim = got.get(f"facts.{i}.claim")
        if not claim:
            continue
        f = {"id": f"{site_id}-fact{i}", "sites": [site_id],
             "topic": [], "claim": claim,
             "source": got.get(f"facts.{i}.source", "自社実績"),
             "as_of": got.get(f"facts.{i}.as_of", ""),
             "verifiable": True}
        den = re.sub(r"[^0-9]", "", got.get(f"facts.{i}.denominator", ""))
        if den:
            f["denominator"] = int(den)
        if got.get(f"facts.{i}.period"):
            f["period"] = got[f"facts.{i}.period"]
        out.append(f)
    if got.get("facts.note"):
        out.append({"id": f"{site_id}-note", "sites": [site_id], "topic": [],
                    "claim": got["facts.note"], "source": "現場での観察",
                    "as_of": got.get("facts.1.as_of", ""), "verifiable": False})
    return out


# ============================================================
# 埋まっているかを見る
# ============================================================
def review(got, cfg):
    """記事を作り始める前に気づきたいことだけを見る。
    「あとで直せるもの」は警告、「直さないと回らないもの」は不備にする"""
    ng, warn = [], []

    missing = [label for key, label, _, _, req in FIELDS
               if req and not key.startswith("#") and not got.get(key)]
    for m in missing:
        ng.append(f"「{m}」が空です")

    if cfg.get("id") and not re.fullmatch(r"[a-z][a-z0-9-]*", cfg["id"]):
        ng.append("サイトIDは英小文字とハイフンのみで書いてください")
    if cfg.get("type") not in TYPES:
        ng.append(f"サイトの形式が不正です（{' / '.join(TYPES)}）")
    # wordpress は REST API で投稿するのでリポジトリは要らない（client_add と同じ条件）。
    # ここで止めると、repo 欄を空にした WordPress の社がいつまでも登録できない
    if cfg.get("type") not in ("self-static", "wordpress") and not cfg.get("repo"):
        ng.append("配信先リポジトリが空です（自社構築以外は書き込み先が要ります）")
    # 以前は空欄に "/blog" を補っていた。実際の記事URLが違えば、sitemap も通知も
    # 存在しないURLを指す。推測で埋めず、書いてもらう
    if cfg.get("type") in TYPES and cfg["type"] != "self-static" and not cfg.get("url_prefix"):
        ng.append("記事URLの接頭辞が空です（記事が /blog/xxx/ に出るなら /blog と書いてください）")
    _, bad = languages(got.get("languages"))
    if bad:
        warn.append(f"多言語の指定で読めない語があります: {' / '.join(bad)}"
                    "（en / zh / ko で書いてください。読めた分だけ作ります）")
    # 上限は intake_watch だけで見ていた。手で client_intake を打つと21社目が通っていた
    import intake_watch
    if intake_watch.site_count() >= intake_watch.MAX_SITES:
        ng.append(f"サイトが既に{intake_watch.site_count()}件あります。この仕組みは"
                  f"{intake_watch.MAX_SITES}社までです（別リポジトリに分けてください）")

    cats = cfg.get("categories") or {}
    if cfg.get("main_category") and cfg["main_category"] not in cats:
        ng.append(f"主力カテゴリ「{cfg['main_category']}」がカテゴリ一覧にありません")
    mix = cfg.get("category_mix") or {}
    if mix:
        unknown = set(mix) - set(cats)
        if unknown:
            ng.append(f"配分に無いカテゴリがあります: {sorted(unknown)}")
        total = sum(mix.values())
        if total and abs(total - 100) > 2:
            warn.append(f"カテゴリの配分の合計が{total}です（100になるよう調整してください）")
        main = mix.get(cfg.get("main_category"), 0)
        if main and main < 35:
            warn.append(f"主力カテゴリの配分が{main}%です。"
                        "40〜50%を下回ると、表示は増えても相談につながりにくくなります")

    # 既存サイトとの衝突。記事がどちらのものか決まらなくなる
    for p in SITES.glob("*.json"):
        other = json.loads(p.read_text(encoding="utf-8-sig"))
        if other.get("id") == cfg.get("id"):
            ng.append(f"サイトID「{cfg['id']}」は既にあります")
        if other.get("domain") and other["domain"] == cfg.get("domain"):
            ng.append(f"ドメインが {p.stem} と同じです")
        dup = set(cats) & set(other.get("categories", {}))
        if dup:
            ng.append(f"カテゴリ {sorted(dup)} が {p.stem} と重複しています")

    seeds = cfg.get("kw_seeds", {})
    n = len(seeds.get("industries", [])) * len(seeds.get("intents", []))
    if n < 200:
        warn.append(f"キーワードの起点が{n}通りです。"
                    "200通りを下回ると半年ほどでテーマが枯れます")
    if not cfg.get("avoid"):
        warn.append("扱わない領域が空です。他サイトとの食い合い検査が弱くなります")
    if not cfg.get("ga4_property_id"):
        warn.append("GA4プロパティIDが空です。レポートに流入データが出ません")
    if got.get("gsc_ready", "").startswith("未"):
        warn.append("Search Consoleの権限が未付与です。順位と検索語が取れません")

    facts = to_facts(got, cfg.get("id") or "client")
    hard = [f for f in facts if f.get("verifiable")]
    if not hard:
        ng.append("一次情報が1つも書かれていません。"
                  "その会社にしか出せない数値が無いと、AI検索に引用されません")
    elif len(hard) < 2:
        warn.append("一次情報が1つだけです。3つあると記事ごとに使い分けられます")
    for f in hard:
        if not re.fullmatch(r"\d{4}-\d{2}", f.get("as_of") or ""):
            warn.append(f"一次情報の時点が YYYY-MM の形式ではありません: {f['claim'][:24]}…")
    # 割合は母数と集計期間が無いと優良誤認になる。add_fact と同じ検査を当てる
    # （「当社の採択率は90%です」がそのまま記事に使われていた）
    import add_fact
    for f in facts:
        for p in add_fact.rate_problems(f):
            ng.append(f"一次情報「{f['claim'][:24]}…」: {p}")
    if not to_company(got).get("address"):
        warn.append("住所が空です。構造化データの会社情報が不完全になります")
    return ng, warn


def show(cfg, got, ng, warn):
    print(f"■ {cfg.get('name') or '（名称なし）'}（{cfg.get('id') or '?'}）")
    print(f"    形式    : {cfg.get('type')} … {TYPES.get(cfg.get('type'), '不明')}")
    print(f"    公開先  : {cfg.get('domain', '')}{cfg.get('url_prefix', '')}")
    print(f"    主力商材: {cfg.get('main_offer') or '（未記入）'}")
    cats = cfg.get("categories") or {}
    mix = cfg.get("category_mix") or {}
    if cats:
        s = " / ".join(f"{v}{('・' + str(mix[k]) + '%') if k in mix else ''}"
                       for k, v in cats.items())
        print(f"    カテゴリ: {s}")
    seeds = cfg.get("kw_seeds", {})
    print(f"    KWの起点: 業種{len(seeds.get('industries', []))} × "
          f"意図{len(seeds.get('intents', []))} = "
          f"{len(seeds.get('industries', [])) * len(seeds.get('intents', []))}通り")
    facts = to_facts(got, cfg.get("id") or "client")
    subs = subjects(got)
    print(f"    狙う語  : メイン{len(lines(got.get('kw.main')))} / サブ{len(lines(got.get('kw.sub')))} → 主題候補{len(subs)}件")
    for x in subs[:4]:
        print(f"        ・{x['keyword']}  〔{x['from']}〕")
    print(f"    一次情報: {len(facts)}件")
    for f in facts[:3]:
        print(f"        ・{f['claim'][:44]}  〔{f['source']} / {f['as_of']}〕")
    print()
    for m in ng:
        print(f"    × {m}")
    for m in warn:
        print(f"    ! {m}")
    if not ng and not warn:
        print("    すべて埋まっています")


# ============================================================
# 反映する
# ============================================================
def apply(got, cfg, industry=""):
    site_id = cfg["id"]
    made = []

    out = SITES / f"{site_id}.json"
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    made.append(out)

    # 会社情報と一次情報はクライアントごとに分ける。1つのファイルに混ぜると
    # 別のクライアントの実績を引いてしまう事故が起きる
    cdir = ROOT / "data" / "clients" / site_id
    cdir.mkdir(parents=True, exist_ok=True)
    comp = to_company(got)
    if comp:
        p = cdir / "company.json"
        p.write_text(json.dumps(comp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        made.append(p)
    priv = to_private(got)
    if priv:
        p = cdir / "private.json"          # .gitignore 済み（public リポジトリに出さない）
        p.write_text(json.dumps(priv, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        made.append(p)
    brief = to_brief(got, industry)
    bp = cdir / "brief.json"
    bp.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + chr(10),
                  encoding="utf-8")
    made.append(bp)

    facts = to_facts(got, site_id)
    if facts:
        p = cdir / "facts.json"
        p.write_text(json.dumps(
            {"_readme": "この会社にしか出せない一次情報。記事はここから最低1つ引く。"
                        "確認できない数値は載せない（載せた瞬間に信頼を失う）。",
             "facts": facts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        made.append(p)

    plan = ROOT / cfg["kw_plan"]
    if not plan.exists():
        plan.parent.mkdir(parents=True, exist_ok=True)
        seeds = cfg.get("kw_seeds", {})
        plan.write_text(
            f"# {cfg['name']} KW計画\n\n"
            f"- 主力商材: {cfg.get('main_offer', '')}\n"
            f"- 対象読者: {cfg.get('audience', '')}\n"
            f"- 守備範囲: {' / '.join(cfg.get('owns', []))}\n"
            f"- 扱わない: {' / '.join(cfg.get('avoid', [])) or '（未設定）'}\n\n"
            f"## 起点\n業種{len(seeds.get('industries', []))}件 × "
            f"意図{len(seeds.get('intents', []))}件\n\n"
            "（kw_discover.py が自動で補充します）\n", encoding="utf-8")
        made.append(plan)
    return made


def main():
    ind = ""
    for i, a in enumerate(sys.argv):
        if a == "--industry" and i + 1 < len(sys.argv):
            ind = sys.argv[i + 1]
    if "--sheet" in sys.argv:
        k = sys.argv.index("--sheet")
        if not ind and k + 1 < len(sys.argv) and not sys.argv[k + 1].startswith("-"):
            ind = sys.argv[k + 1]
        out = SHEET if not ind else SHEET.with_name(
            f"ヒアリングシート_{INDUSTRY[ind][0] if ind in INDUSTRY else ind}.xlsx")
        p = make_sheet(out, ind)
        print(f"ヒアリングシートを作成しました: {p.relative_to(ROOT).as_posix()}")
        print("  クライアントにお渡しし、水色の欄をご記入いただいてください。")
        print(f"  記入後: python scripts/client_intake.py {p.name} --apply")
        if not ind:
            print(f"  業種別: --sheet <{' / '.join(INDUSTRY)}> で専用の項目が付きます")
        return 0

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__.strip())
        return 1
    src = Path(args[0])
    if not src.is_file():
        src2 = SHEET.parent / src.name
        if src2.is_file():
            src = src2
        else:
            raise SystemExit(f"見つかりません: {src}")

    got = read_sheet(src)
    cfg = to_config(got)
    ng, warn = review(got, cfg)
    show(cfg, got, ng, warn)

    if ng:
        print(f"\n  {len(ng)}件の不備があるため反映しません。シートを直して再実行してください。")
        return 1
    if "--apply" not in sys.argv:
        print("\n  確認のみ（--apply を付けると登録します）")
        return 0

    # ファイル名から業種を拾う。シート名を変えられても動くよう、中身でも見る
    ind2 = ind or next((k for k, (lab, _) in INDUSTRY.items()
                        if lab in src.name), "")
    made = apply(got, cfg, ind2)
    print("\n  作成したファイル")
    for p in made:
        print(f"    {p.relative_to(ROOT).as_posix()}")
    print("\n  次にやること")
    print(f"    1. python scripts/kw_discover.py --site {cfg['id']} --append   … KWを補充する")
    print("    2. GA4とSearch Consoleにサービスアカウントを追加してもらう")
    if cfg.get("type") != "self-static":
        print("    3. python scripts/token_check.py   … 配信先に書き込めるか確認する")
    if (cfg.get("rules") or {}).get("review_before_publish"):
        print("    ※ このクライアントは公開前の確認が必要です。自動公開を切ってください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
