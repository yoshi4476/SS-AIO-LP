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
    python scripts/client_intake.py <記入済み.xlsx> --apply   # 登録まで行う（最後に機能ごとの準備状況）
    python scripts/client_intake.py --creds <id>          # 別経路で受け取った鍵を登録する形（パスワード欄は空）

シートは 1.会社・担当 / 2.サイトと納品方式 / 3.計測と検索エンジン / 4.商材・強み・読者 / 5.記事の材料 /
6.発信 / 7.サイトの改修 / 8.レポートと運用のきまり / 9.外部との接点（＋業種別）。どの欄がどこへ流れ、
どの機能が何を要るかは docs/intake-requirements.md（intake_readiness.py --doc が作る）。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "docs" / "client" / "ヒアリングシート.xlsx"
SITES = ROOT / "sites"
sys.path.insert(0, str(ROOT / "scripts"))
from client_add import TYPES, NEW_TYPES, RETIRED  # noqa: E402  形式の定義は1か所に置く

# ── 聞くこと ────────────────────────────────────
# (キー, 見出し, 説明, 記入例, 必須)
# キーの先頭が "#" の行は見出しだけを置く区切り。
# 必須は True（どの方式でも）か、方式の印（"wordpress" / "git" / "ftp" / "new"。カンマで複数）。
# 印の付いた欄は、2章で選んだ形式がその方式のときだけ必須になる（review が見る・シートのC列に出る）。
# どの欄も、どこかの設定（sites/<id>.json・data/clients/<id>/ の各ファイル）か準備状況（intake_readiness）へ流れる。
# 流れ先の一覧は docs/intake-requirements.md。流れ先の無い欄は作らない
FIELDS = [
    ("#basic", "1. 会社・担当・連絡先", "記事の著者情報・構造化データ・レポートの宛名に使います。"
     "表記がぶれると別法人と混同されるため、登記どおりに書いてください。", "", False),
    ("company.name", "会社名（正式）", "登記上の表記。株式会社の位置も登記どおりに",
     "株式会社サンプル商事", True),
    ("company.name_en", "英語表記", "無ければ空欄で構いません", "Sample Shoji Co., Ltd.", False),
    ("company.corporate_number", "法人番号", "13桁。国税庁の法人番号公表サイトで確認できます",
     "1234567890123", False),
    ("company.postal", "郵便番号", "ハイフンあり", "530-0001", False),
    ("company.address", "住所", "建物名・部屋番号まで", "大阪府大阪市北区梅田1丁目1-1 ○○ビル5階", True),
    ("company.tel", "電話番号", "記事とサイトに掲載する番号", "06-0000-0000", True),
    ("company.hours", "営業時間", "問い合わせを受けられる時間帯",
     "9:00〜20:00（土・日・祝日を除く）", False),
    ("company.founded", "創業年月日", "「○年の実績」と書けるかの判断に使います", "2020年3月10日", False),
    ("company.capital", "資本金", "補助金の要件判定にも使います", "500万円", False),
    ("company.ceo", "代表者名", "記事の著者情報に使います", "山田 太郎", False),
    ("company.email", "問い合わせメール", "サイトに出している会社の窓口", "info@example.co.jp", True),
    # 担当者の連絡先は public の sites/・company.json に置かない（private.json。to_private）
    ("contact.name", "ご担当者のお名前", "導入の手続き（権限の追加・接続情報の受け渡し）でご連絡する方。公開しません",
     "山田 花子", True),
    ("contact.email", "ご担当者のメール", "公開しません（当社の控えにだけ残します）", "hanako@example.co.jp", True),
    ("contact.tel", "ご担当者の電話", "公開しません", "06-0000-0001", False),

    ("#media", "2. サイトと納品方式",
     "どこに、どの形で記事を出すか。「サイトの形式」で選んだ方式の欄（2-1〜2-4）だけご記入ください"
     "（ほかの方式の欄は空欄で構いません）。パスワード類はこのシートに書かないでください。", "", False),
    ("id", "サイトID", "英小文字とハイフンのみ。ファイル名に使います（分からなければ当社で決めます）",
     "example-media", True),
    ("name", "メディア名", "記事一覧やレポートに出る名前", "○○の集客ラボ", True),
    ("domain", "公開ドメイン", "https:// は不要。新しく作る場合は使いたいドメイン", "media.example.co.jp", True),
    ("type", "サイトの形式",
     "WordPressをお使いなら wordpress（あわせて FTP の接続情報もいただくと、テーマ由来の表示速度とサイト構成の変更まで当社が自動で行います）。"
     "当社で新規構築するなら self-static。"
     "既存の静的サイトへ配信する場合は external-html / external-md / nextjs-json（GitHub のリポジトリ）。"
     "Git を使わないレンタルサーバー（FTP で上げているサイト）なら ftp（FTP の接続情報を1回いただきます）。"
     "どの形式でも、最初の接続の後は御社の作業はありません（ZIP で受け取る形式は受け付けていません）",
     "wordpress", True),
    ("url_prefix", "記事URLの接頭辞",
     "記事が /blog/xxx/ に出るなら /blog。Git・FTP の方式は必ず記入"
     "（wordpress は空欄で可。記事のURLは先方のパーマリンク設定から取ります）", "/blog", "git,ftp"),
    ("keys.sent", "別経路でお送りする鍵",
     "アプリケーションパスワード・FTP のパスワード・DNS のログイン情報など、このシートに書かないものの状況",
     "これから送る", False),

    ("#media_wp", "2-1. WordPress の場合",
     "当社用のユーザーを1人作り、そのアプリケーションパスワード（ユーザー > プロフィール）を別経路でお送りください。", "", False),
    ("wp.admin_url", "管理画面のURL", "ログイン画面のURL", "https://example.co.jp/wp-admin/", "wordpress"),
    ("wp.user", "投稿用のユーザー名", "当社用に作ったユーザー（権限は「編集者」）", "ss-editor", "wordpress"),
    ("wp.plugin", "品質の検査のプラグイン",
     "90点に届かない記事を公開させない小さなプラグイン（mu-plugin）を wp-content/mu-plugins/ に置きます。"
     "当社が置く場合は FTP の接続情報が要ります", "当社が置く", "wordpress"),
    ("wp.admin_key", "改修用の管理者の鍵",
     "追加CSS・head への追記・メニューの変更には、管理者のアプリケーションパスワードが要ります", "出せる", False),
    ("wp.ftp", "FTP の接続情報",
     "テーマ（PHP）の直し・表示速度の直し・プラグインの設置に使います（ホストなどは 2-3 に）", "出せる", False),
    ("wp_api", "WordPressのAPIのURL",
     "通常は空欄で構いません（https://ドメイン/wp-json/wp/v2 を自動で使います）", "", False),

    ("#media_git", "2-2. Git（GitHub）の場合",
     "配信先のリポジトリに、当社の GitHub アカウントを Write 権限で招待してください（手順は設定ガイド）。", "", False),
    ("repo", "配信先リポジトリ", "owner/repo の形式", "example/media-site", "git"),
    ("branch", "ブランチ", "通常は main", "main", False),
    ("content_dir", "記事の置き場所", "リポジトリ内のパス", "src/content/blog", False),
    ("images_dir", "画像の置き場所", "同上", "public/images/blog", False),
    ("pages_dir", "まとめのページの置き場所",
     "業種別・用語集・比較表のページを置くフォルダ。空欄なら記事の置き場所の隣の pages/", "src/content/pages", False),
    ("git.invited", "当社アカウントの招待（Write）", "済 / 未", "済", "git"),

    ("#media_ftp", "2-3. FTP（レンタルサーバー）の場合",
     "パスワードは別経路でお送りください。WordPress の社で FTP を出せる場合もここに書いてください。", "", False),
    ("ftp.host", "FTP のホスト名", "サーバー会社の管理画面に出ている名前", "sv1234.xserver.jp", "ftp"),
    ("ftp.protocol", "接続の方式", "分からなければ FTPS（暗号化あり）", "FTPS", False),
    ("ftp.user", "FTP のユーザー名", "パスワードは書かないでください", "example_ftp", "ftp"),
    ("ftp.root", "公開フォルダ", "ドメインのトップにあたるフォルダ", "/example.co.jp/public_html", "ftp"),

    ("#media_new", "2-4. 当社で新しく作る場合（self-static）",
     "公開ドメインを向けるために、DNS の設定が1回だけ要ります。", "", False),
    ("dns.provider", "DNS の管理会社", "ドメインを買った会社・DNS を設定している会社", "お名前.com", "new"),
    ("dns.access", "DNS の設定", "当社が行う場合はログイン情報を別経路で", "当社が行う", "new"),

    ("#measure", "3. 計測と検索エンジン",
     "数字が取れないと改善の判断ができません。権限の追加の手順は設定ガイドにあります。"
     "IndexNow（Bing などへの即時の通知）は当社が自動で行うため、ご記入は不要です。", "", False),
    ("ga4_property_id", "GA4プロパティID", "数字のみ。管理画面 > 管理 > プロパティの詳細",
     "123456789", False),
    ("ga4.viewer", "GA4 に当社を閲覧者で追加", "済 / 未。導入時にメールでお知らせするアカウントを「閲覧者」で", "済", False),
    ("ga4.installed", "サイトに GA4 が入っているか", "入っている / 入っていない", "入っていない", False),
    ("ga4_measurement_id", "GA4の測定ID（G-で始まる）",
     "形式が wordpress / ftp のときのみ。記事の計測（ボタン・フォーム・読了）を当社が入れます"
     "（wordpress は当社のプラグイン、ftp は当社が書き出す記事のページ）。"
     "GA4 を既にサイトへ入れている場合は空欄で構いません（二重には入れません）", "G-XXXXXXXXXX", False),
    ("gsc.property", "Search Console のプロパティの種類",
     "当社の仕組みは https://ドメイン/ の形（URLプレフィックス）のプロパティを読みます。"
     "ドメインのプロパティだけの場合は、URLプレフィックスのプロパティも追加してください", "URLプレフィックス", False),
    ("gsc_owner", "Search Consoleのオーナー権限",
     "当社のサービスアカウント（導入時にメールでお知らせします）を Search Console に「オーナー」で追加。済 / 未。"
     "オーナーでないと、新しい記事を Google へすぐ知らせる仕組み（Indexing API）が使えません", "済", False),
    ("bing_consent", "Bing・検索エンジンへの登録の同意",
     "Bing・検索エンジンへの登録を当社のアカウントで行うことに同意いただけるか。可 / 不可。"
     "可の場合、当社の Bing Webmaster に御社のサイトを登録し、確認用のファイル（BingSiteAuth.xml）を"
     "サイトの直下に置いて、新しい記事を Bing（ChatGPT の検索も使う索引）へすぐ知らせます"
     "（御社が既に Bing をお使いでも、確認用のファイルは両方の分を残します）", "可", False),

    ("#offer", "4. 商材・強み・読者", "いちばん大切な章です。ここが曖昧だと、"
     "表示回数は増えても問い合わせにつながらない記事が量産されます。", "", False),
    ("main_offer", "主力商材（1行）", "この記事群で最終的に売りたいもの",
     "経理BPO（記帳代行の受託）", True),
    ("service.priority", "利益の大きい順の商材", "改行区切りで上から。記事の結論はこの順で案内します",
     "経理BPO（月次決算まで）\n給与計算\n記帳代行のみ", False),
    ("main_category", "主力カテゴリ", "下のカテゴリ一覧のうち、主力商材に直結するもの",
     "keiri-bpo", True),
    ("categories", "カテゴリ一覧",
     "「slug: 表示名」を改行区切りで。slugは英小文字とハイフン",
     "keiri-bpo: 経理BPO\nkeiri-jitsumu: 経理実務\nbackoffice: バックオフィス", True),
    ("category_mix", "カテゴリの配分",
     "「slug: 割合」を改行区切り。合計100。主力を50%前後にすると相談につながりやすくなります",
     "keiri-bpo: 50\nkeiri-jitsumu: 40\nbackoffice: 10", False),
    ("service.list", "提供しているもの",
     "改行区切り。メニュー・プラン・サービス名を具体的に",
     "記帳代行\n月次決算の代行\n給与計算\n請求書発行の代行", True),
    ("service.price", "価格帯", "記事に載せてよい範囲で。「応相談」でも構いません",
     "月額3万円〜（仕訳数と業務範囲による）", False),
    ("service.price_policy", "価格の載せ方", "載せてよい / 目安だけ / 載せない", "目安だけ", False),
    ("service.area", "提供エリア", "地域名を書くと、地域名を含む検索で拾えます",
     "大阪府全域・兵庫県南部（オンラインは全国）", False),
    ("service.strength", "他社と違う点",
     "改行区切りで3つ。「安い・早い・丁寧」ではなく、具体的な事実で",
     "税理士と連携し申告まで一貫して対応できる\n初月は並行稼働して引き継ぎ漏れを防ぐ\n"
     "業務フローの図を作って納品する", True),
    ("service.why_chosen", "選ばれる理由",
     "改行区切り。お客様から実際に言われた決め手", "担当者が最後まで変わらない\n見積の内訳が細かい", False),
    ("customer.lost", "よく失注する理由",
     "改行区切り。記事で先回りして答えると、相談の質が上がります", "料金が月額固定でないと不安\n社内に担当が残らないと思われる", False),
    ("service.flow", "問い合わせから成約・開始までの流れ", "記事の「次にやること」に使います。期間も分かれば",
     "問い合わせ → 現状のヒアリング（60分）→ 見積 → 契約 → 並行稼働1ヶ月 → 本稼働（約6週間）", False),
    ("theme", "何を扱うメディアか", "1行で", "中小企業の経理実務とバックオフィス効率化", True),
    ("audience", "誰に向けたものか", "1行で。役職や状況まで書けると精度が上がります",
     "経理担当が1〜2名の中小企業の経営者・管理部門責任者", True),
    ("owns", "自社が扱う語", "改行区切り。このメディアの守備範囲",
     "経理BPO\n記帳代行\n月次決算\n請求書処理", True),
    ("avoid", "扱わない領域", "改行区切り。理由も添えてください",
     "補助金の申請手続き（別サイトの担当領域のため）\n人材採用・労務", False),

    ("#target", "4-1. 読者（誰に読ませるか）",
     "「誰に」がぼやけると、読まれても相談につながりません。1人の顔が浮かぶくらい具体的に。", "", False),
    ("target.persona", "いちばん来てほしいお客様",
     "年齢・立場・状況を1〜2文で。社内で呼んでいる呼び方でも構いません",
     "従業員20〜50名の会社で、経理をひとりで担当している40代の管理部長。"
     "決算期に毎年残業が続いている", True),
    ("target.second", "その次に来てほしい層", "無ければ空欄",
     "これから経理担当を採用しようとしている経営者", False),
    ("target.area", "商圏・エリア", "全国対応なら「全国」", "大阪市内を中心に、京阪神エリア", False),
    ("target.stage", "検討の段階",
     "まだ困りごとを調べている段階か、業者を比べている段階か", "困りごとを調べ始めた段階の人が多い", False),
    ("target.decide", "決め手になること", "改行区切り。最後に何で選ばれるか",
     "対応の速さ\n担当者が変わらないこと\n見積の分かりやすさ", False),
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
    ("customer.trigger", "問い合わせのきっかけ", "どんなときに相談が来るか",
     "経理担当の退職が決まったとき / 決算期の前 / 税理士に指摘されたとき", False),
    ("customer.ng", "よくある誤解", "改行区切り。記事で先回りして解いておきます",
     "丸投げすると社内が何も分からなくなる、と思われがちです\n大企業向けだと思われがちです", False),

    ("#compete", "4-2. 競合",
     "競合が書いていないことを書くために聞きます。挙げたサイトは毎月の競合比較にも必ず入れます。", "", False),
    ("compete.sites", "競合のサイト（3社）", "改行区切りでURL", "https://example-a.co.jp\nhttps://example-b.co.jp\nhttps://example-c.co.jp", False),
    ("compete.diff", "競合にはない自社の強み", "競合を見たうえでの差",
     "地域密着で訪問できる点。競合は全国対応だが訪問はしない", False),

    ("#cta", "4-3. 記事から問い合わせへの導線", "記事を読んだ人がどこへ進むか。"
     "全記事に必ず2箇所以上入れます。", "", False),
    ("cta.label", "ボタンの文言", "行動が分かる言葉で。「お問い合わせ」より具体的に",
     "経理の現状分析（無料）", True),
    ("cta.url", "遷移先URL", "問い合わせフォームやLPのURL", "https://example.co.jp/contact/", True),
    ("cta_title", "記事下の見出し", "", "経理の負担、どこから減らせるか見てみませんか", False),
    ("cta_desc", "記事下の説明文", "", "現状を伺ったうえで、外に出せる業務を整理してご提案します。", False),
    ("cta.note", "補足", "「ご契約を前提としたご案内ではありません」など安心材料",
     "ご契約を前提としたご案内ではありません", False),
    ("cta_mid.label", "記事の中ほどの軽い入口",
     "相談より手前の入口（無料診断・資料・LINE など）。無ければ空欄（上のボタンと同じ先へ）", "3分でできる経理の負担チェック", False),
    ("cta_mid.url", "軽い入口のURL", "", "https://example.co.jp/check/", False),

    ("#kw", "5. 記事の材料：狙う語",
     "実際に取りたい語を教えてください。ここを起点に、業種 × 意図と掛け合わせて記事の主題を作ります。", "", False),
    ("kw.main", "メインキーワード", "改行区切りで3〜5個。事業の柱になる、いちばん取りたい語",
     "経理代行\n記帳代行\n経理アウトソーシング", True),
    ("kw.sub", "サブキーワード",
     "改行区切り。メインと一緒に検索される語、言い換え、お客様が使う言い方",
     "経理 外注\n経理 丸投げ\n記帳 代行 料金\n月次決算 早期化\n経理 属人化", True),
    ("kw.regions", "狙いたい地域", "都道府県・市区の名前を改行区切り（全国なら空欄）",
     "大阪府\n兵庫県", False),
    ("kw.area_word", "地域を付けて狙う語", "改行区切り。「大阪 経理代行」のように",
     "経理代行 大阪\n記帳代行 梅田", False),
    ("kw.exclude", "狙わない語", "改行区切り。対応できない業務や、来てほしくない層が使う語",
     "経理 求人\n経理 資格\n無料 テンプレート", False),
    ("kw.known", "すでに上位に出ている語", "改行区切り。分かる範囲で。既存サイトがある場合のみ", "", False),
    ("kw_seeds.industries", "業種・対象", "改行区切り。20件以上を目安に",
     "製造業\n建設業\n飲食店\nクリニック\n士業事務所", True),
    ("kw_seeds.priority", "優先して狙う業種", "上の業種のうち、1件の成約が大きいものを改行区切り",
     "クリニック\n建設業", False),
    ("kw_seeds.intents", "検索の意図", "改行区切り。10件以上を目安に",
     "費用\nやり方\n選び方\n比較\n失敗事例\n対象条件", True),
    ("season.peaks", "繁忙期と、その時期に増える相談",
     "「月: 語」を改行区切り。その語の記事を山の6〜10週前に優先して書きます",
     "12月: 年末調整\n3月: 決算", False),

    ("#facts", "5-1. 一次情報（最重要）",
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

    # 事例とお客様の声は、掲載が「可」で本人の確認が済んだものだけを記事の材料へ渡す（to_brief）。
    # 事業者が作った感想を「お客様の声」として出すのはステルスマーケティング規制の違反
    ("#cases", "5-2. 事例とお客様の声",
     "記事に載せてよいものだけを使います。掲載が「可」で、ご本人の確認が済んだものだけが記事に出ます。", "", False),
    ("case.1.summary", "事例 ①（どんな会社の、何を）", "", "従業員30名の製造業。月次決算の代行", False),
    ("case.1.result", "事例 ① の結果", "数字は実際の値だけ", "月次決算が翌月25日 → 翌月10日に", False),
    ("case.1.publish", "事例 ① の掲載", "可（社名を出す）/ 可（社名を出さない）/ 不可", "可（社名を出さない）", False),
    ("case.1.confirmed", "事例 ① のご本人の確認", "済 / 未", "済", False),
    ("case.2.summary", "事例 ②（どんな会社の、何を）", "", "", False),
    ("case.2.result", "事例 ② の結果", "", "", False),
    ("case.2.publish", "事例 ② の掲載", "", "", False),
    ("case.2.confirmed", "事例 ② のご本人の確認", "", "", False),
    ("voice.1.text", "お客様の声 ①", "ご本人の言葉のまま", "引き継ぎの資料まで作ってもらえて、退職の不安が無くなりました", False),
    ("voice.1.name", "お客様の声 ① の表示名", "会社名を出さない場合は「大阪市の製造業」など", "大阪市の製造業", False),
    ("voice.1.publish", "お客様の声 ① の掲載", "可 / 不可", "可", False),
    ("voice.1.by", "お客様の声 ① の書き手", "本人が書いた / 本人が内容を確認した / 未確認", "本人が書いた", False),
    ("voice.2.text", "お客様の声 ②", "", "", False),
    ("voice.2.name", "お客様の声 ② の表示名", "", "", False),
    ("voice.2.publish", "お客様の声 ② の掲載", "", "", False),
    ("voice.2.by", "お客様の声 ② の書き手", "", "", False),

    ("#author", "5-3. 記事の書き手",
     "誰が書いたか分からない記事は、検索エンジンにもAIにも信用されません。"
     "実在する方のお名前と肩書きをお願いします。", "", False),
    ("author.name", "著者名", "記事に表示するお名前", "山田 太郎", True),
    ("author.title", "肩書き", "", "株式会社サンプル商事 経理BPO事業責任者", True),
    ("author.credential", "保有資格・経歴", "改行区切り。専門性の裏づけになるもの",
     "日商簿記1級\n上場企業の経理部で10年\n中小企業の経理支援を通算120社", False),

    # 記事の監修者はお客様ご本人（2026-10-05 運用者の決定）。当社の名前を監修者として出さない。
    # 名前・資格・同意が無いまま「監修」と表示すると事実と違う表示になるため、ここが埋まるまで登録を止める
    ("#supervisor", "5-4. 記事の監修者",
     "公開する記事には「監修」として、内容を確かめる方のお名前と資格を表示します"
     "（医療・法律・お金の分野では特に、誰が確かめたかが信頼の根拠になります）。"
     "実在の方で、掲載の同意をいただける方をお書きください。", "", False),
    ("supervisor.name", "監修者のお名前", "記事に表示するお名前（フルネーム）", "佐藤 花子", True),
    ("supervisor.title", "役職", "所属と役職", "さとう歯科クリニック 院長", True),
    ("supervisor.qualification", "資格", "正式な名称で。複数あれば改行区切り",
     "歯科医師\n日本口腔インプラント学会 専門医", True),
    ("supervisor.registration", "登録番号", "医師・歯科医師・士業などの登録番号（公開してよい場合のみ）",
     "歯科医籍登録 第000000号", False),
    ("supervisor.career", "経歴", "改行区切り。専門性の裏づけになるもの",
     "○○大学歯学部 卒業\n○○病院 口腔外科 勤務（10年）\n2018年 開院", False),
    ("supervisor.scope", "監修する範囲", "どこまでを確かめるか（表示に使います）",
     "診療内容・治療法・費用の説明", True),
    ("supervisor.profile_url", "プロフィールページ", "自社サイトの院長紹介・スタッフ紹介のページ",
     "https://example.jp/about/doctor/", False),
    ("supervisor.same_as", "外部のプロフィール", "学会の名簿・SNS・取材記事など。改行区切り",
     "https://www.example-gakkai.jp/member/000\nhttps://www.instagram.com/xxxx", False),
    ("supervisor.photo", "顔写真", "「あり」なら別途お送りください（無くても掲載できます）", "あり", False),
    ("supervisor.consent", "掲載の同意", "「可」と書いた場合だけ、お名前・資格を記事に表示します",
     "可", True),
    ("supervisor.review", "記事の確かめ方", "公開前に確かめる / 公開後に確かめる（修正があればご連絡）",
     "公開後に確かめる", True),
    ("supervisor.contact", "確認のご連絡先", "記事の確認依頼を送るメールアドレス",
     "sato@example.jp", True),

    ("#tone", "5-5. 書き方と表現のきまり",
     "文体や言い回しを揃え、業種の表現規制に触れないための指定です。", "", False),
    ("tone.person", "自社の呼び方", "記事中の一人称", "当社", False),
    ("tone.style", "文体", "ですます / だ・である", "ですます", False),
    ("tone.level", "専門用語の扱い", "初心者向け（都度説明）/ 実務者向け（説明は最小限）",
     "初心者向け（都度説明）", False),
    ("tone.avoid", "使いたくない言い回し", "改行区切り。社内で避けている言い回しがあれば",
     "丸投げ\nお任せください", False),
    ("ng_words", "使ってはいけない表現",
     "改行区切り。ここに書いた語を含む記事は公開を止めます（薬機法・景表法などで避ける語）",
     "完治\n必ず治る\n日本一", False),
    ("tone.regulation", "業種の表現の決まり",
     "医療広告ガイドライン / 薬機法 / 景品表示法 / 宅建業法 / 弁護士の広告規程 など。改行区切り",
     "景品表示法", False),

    ("#asset", "5-6. すでにあるもの", "作り直しになるか、活かせるかの判断に使います。", "", False),
    ("asset.site", "既存サイト", "URL。無ければ空欄", "https://example.co.jp", False),
    ("asset.articles", "既存の記事数", "おおよその本数", "15本", False),
    ("asset.top_pages", "よく読まれている既存のページ", "URLを改行区切り。記事からの内部リンクの送り先に使います",
     "https://example.co.jp/service/\nhttps://example.co.jp/price/", False),
    ("asset.failed", "過去にうまくいかなかった施策", "改行区切り。同じ打ち手を記事で勧めないために使います",
     "リスティング広告（月10万円で問い合わせ0件）", False),
    ("asset.photos", "写真素材", "あり（別途お送りください）/ なし（当社で用意した写真を使います）", "あり", False),

    # 動画・SNS は先方のアカウントにだけ上げる（当社のアカウントには上げない）。
    # 鍵やパスワードはシートに書かない。先方に当社を「管理者」に追加してもらい、許可の手続きは当社が行う
    ("#channels", "6. 発信（動画・SNS・Googleビジネスプロフィール）",
     "記事を動画・SNS・地図でも届けます。先方のアカウントに、当社を管理者として追加していただきます"
     "（パスワードはこのシートに書かないでください）。", "", False),
    ("channels.youtube", "YouTubeチャンネル", "チャンネルのURL。無ければ空欄（当社で作成をご相談）",
     "https://www.youtube.com/@example", False),
    ("channels.video", "動画を上げるか", "要 / 不要", "要", False),
    ("channels.facebook", "Facebookページ", "URL。無ければ空欄", "https://www.facebook.com/example", False),
    ("channels.instagram", "Instagram", "URLか@アカウント名", "@example", False),
    ("channels.threads", "Threads", "@アカウント名（Instagramでのログインの許可が1回必要です）", "@example", False),
    ("channels.linkedin", "LinkedIn会社ページ", "URL", "https://www.linkedin.com/company/example", False),
    ("channels.x", "X（旧Twitter）", "@アカウント名（投稿文は当社が作り、投稿は御社が行います）", "@example", False),
    ("channels.tags", "SNS に付けるタグ", "改行区切り（# は不要）", "経理代行\n大阪", False),
    ("channels.contact", "許可の手続きの担当者", "氏名とメールアドレス（管理者の追加をお願いする方）",
     "山田 太郎 / taro@example.co.jp", False),
    ("channels.admin_added", "当社を管理者に追加済みか", "済 / 未（記入時点）", "未", False),
    ("gbp.status", "Googleビジネスプロフィール", "登録済み / 未登録 / 店舗が無い", "登録済み", False),
    ("gbp.invite", "当社をプロフィールの管理者に追加",
     "可 / 不可。可なら導入時に当社のアカウントの追加と、許可の手続き（1回）をお願いします", "可", False),
    ("gbp.description", "地図に出す説明文",
     "750字まで。日本語で（訪日客には Google が自動で翻訳します）。当社が地図の説明文をこの文に揃えます", "", False),

    ("#renovate", "7. サイトの改修",
     "指示の一文で、当社がサイト（見た目・固定ページ・メニュー）を直します。反映の前に画面の写真で確かめ、"
     "反映後に表示やリンクが崩れたら自動で元に戻します。", "", False),
    ("renovate.want", "改修のご希望", "あり / なし", "あり", False),
    ("renovate_auto", "確認なしで反映してよい範囲",
     "CSSのみ / 文言のみ / CSSと文言 / なし（すべて確認してから）。範囲の外の直しは、写真を見て確かめてから反映します",
     "なし（すべて確認してから）", False),
    ("renovate.protect", "触ってはいけないページ", "パスを改行区切り（例: /recruit/）。改修の検査で止めます",
     "/recruit/\n/privacy/", False),
    ("renovate.wish", "直したいところ", "思いつく範囲で。導入後に当社から1つずつご提案します",
     "トップのお知らせ欄が古いままなので消したい", False),

    ("#rule", "8. レポートと運用のきまり", "月次レポートの送り方と、公開の決まりです。", "", False),
    ("report_to", "レポートの送付先", "複数ある場合はカンマ区切り", "info@example.co.jp", False),
    ("report_issuer", "月次レポートの発行者の表示",
     "当社名を出す / お客様名だけ。「お客様名だけ」は表紙・巻末・フッターに当社名とURLを出さず、"
     "御社の社名・住所・サイトだけを載せます（社内・取引先へそのまま回す場合）", "当社名を出す", False),
    ("review_before_publish", "公開前の確認",
     "要 / 不要。医療・金融など表現規制のある業種では「要」を推奨します", "不要", False),
    ("monthly_cap", "月の公開本数", "既定は60本（1日2本）。減らす場合は数字を記入", "60", False),
    ("languages", "多言語の要約ページ",
     "改行区切りで en（英語）/ zh（中国語）/ ko（韓国語）。空なら作らない（既定）。"
     "記事の要点（題名・冒頭・各見出しの1文結論・FAQ）だけを訳したページを別URLに置き、日本語の記事と結びます",
     "", False),
    ("note", "その他の申し送り", "社内の事情など何でも（公開しません）", "", False),
]

# プルダウンにする欄（データの入力規則）。type は別（client_add.NEW_TYPES から作る）。
# 値の判定は先頭の語で見る（「済（10/7）」のような書き足しは通す）
CHOICES = {
    "keys.sent": ["送付済み", "これから送る", "不要"],
    "wp.plugin": ["当社が置く", "御社で置く", "置けない"],
    "wp.admin_key": ["出せる", "出せない"],
    "wp.ftp": ["出せる", "出せない"],
    "git.invited": ["済", "未"],
    "ftp.protocol": ["FTPS", "SFTP", "FTP"],
    "dns.access": ["当社が行う", "御社が行う"],
    "ga4.viewer": ["済", "未"],
    "ga4.installed": ["入っている", "入っていない"],
    "gsc.property": ["URLプレフィックス", "ドメインだけ", "まだ無い"],
    "gsc_owner": ["済", "未"],
    "bing_consent": ["可", "不可"],
    "service.price_policy": ["載せてよい", "目安だけ", "載せない"],
    "case.1.publish": ["可（社名を出す）", "可（社名を出さない）", "不可"],
    "case.2.publish": ["可（社名を出す）", "可（社名を出さない）", "不可"],
    "case.1.confirmed": ["済", "未"],
    "case.2.confirmed": ["済", "未"],
    "voice.1.publish": ["可", "不可"],
    "voice.2.publish": ["可", "不可"],
    "voice.1.by": ["本人が書いた", "本人が内容を確認した", "未確認"],
    "voice.2.by": ["本人が書いた", "本人が内容を確認した", "未確認"],
    "supervisor.consent": ["可", "不可"],
    "supervisor.review": ["公開前に確かめる", "公開後に確かめる"],
    "tone.style": ["ですます", "だ・である"],
    "asset.photos": ["あり", "なし"],
    "channels.video": ["要", "不要"],
    "channels.admin_added": ["済", "未"],
    "gbp.status": ["登録済み", "未登録", "店舗が無い"],
    "gbp.invite": ["可", "不可"],
    "renovate.want": ["あり", "なし"],
    "renovate_auto": ["CSSのみ", "文言のみ", "CSSと文言", "なし（すべて確認してから）"],
    "report_issuer": ["当社名を出す", "お客様名だけ"],
    "review_before_publish": ["要", "不要"],
}

# 方式の印 → その印で必須になる形式（sites/<id>.json の type）
REQ_TYPES = {"wordpress": ("wordpress",), "git": ("external-md", "external-html", "nextjs-json"),
             "ftp": ("ftp",), "new": ("self-static",)}
REQ_LABEL = {"wordpress": "WordPress", "git": "Git", "ftp": "FTP", "new": "新規構築"}

# シートの先頭に置く「記入のしかた」の枠
HOWTO = [
    "■ 記入のしかた",
    "・水色の欄（B列）にご記入ください。E列は記入例（見本）です。▼のある欄は選択肢から選んでください。",
    "・C列が「必須」の欄は必ず、「WordPressなら必須」などは、2章で選んだサイトの形式のときだけ必ずご記入ください。"
    "分からない欄は空欄のままで構いません（導入時に一緒に決めます）。",
    "・パスワード・アプリケーションパスワード・FTP や DNS のログイン情報・APIの鍵は、このシートに書かないでください。"
    "当社からご案内する別の方法でお預かりします（2章の「別経路でお送りする鍵」に状況だけご記入ください）。",
    "・Search Console・GA4・GitHub・Googleビジネスプロフィールへの当社の追加は、設定ガイドに手順があります。済んだ欄は「済」にしてください。",
    "・所要時間の目安: 必須の欄だけで約30分、すべてで約90分です。",
]


BACKLINK = [
    ("#backlink", "9. 外部との接点（被リンクの起点）",
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
    ("#food_link", "14. 飲食店の外部掲載【飲食店】",
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
        ("#shop", "10. 店舗の基本【飲食店】",
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

        ("#menu", "11. メニューと食材【飲食店】",
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

        ("#attract", "12. 集客と予約【飲食店】",
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

        ("#food_rule", "13. 表示のきまり【飲食店】",
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

# 欄ごとの流れ先（docs/intake-requirements.md に出す）。キーそのもの、または「接頭辞.」で引く（長い方が先）。
# 欄を足したらここにも足す（門 gates_history_h38 が、流れ先の無い欄と、抜いても出力が変わらない欄を止める）
_BRIEF = "data/clients/<id>/brief.json → 執筆の案内（site_brief）"
_OB = "sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）"
FLOW = {
    "company.": "data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check）",
    "contact.": "private.json（公開しない）→ 導入の手続きの連絡先",
    "id": "sites/<id>.json のファイル名 → 全工程のサイトID",
    "name": "sites/<id>.json → 記事一覧・レポート・通知の表示名",
    "domain": "sites/<id>.json → 記事URL・sitemap・通知（IndexNow・Indexing API・Bing）・Search Console の https://ドメイン/",
    "type": "sites/<id>.json → 配信の方式（publish.py）・準備状況の判定",
    "url_prefix": "sites/<id>.json → 記事URL（sites.article_url）",
    "keys.sent": _OB + "（受領待ちか要対応か）",
    "wp.admin_url": "private.json → 準備状況・導入の手続き",
    "wp.user": "private.json → 鍵の登録の雛形（--creds の WP_CREDENTIALS_JSON）・準備状況（配信）",
    "wp.plugin": _OB + "（品質ゲート）",
    "wp.admin_key": _OB + "（サイト改修）",
    "wp.ftp": _OB + "（品質ゲート・表示速度の直し）",
    "wp_api": "sites/<id>.json → WordPress の REST の入口（publish.py）",
    "repo": "sites/<id>.json → 配信先（publish.py・site_change.py）",
    "branch": "sites/<id>.json → 配信先のブランチ（publish.py）",
    "content_dir": "sites/<id>.json → 記事の置き場所（publish.py）",
    "images_dir": "sites/<id>.json → 画像の置き場所（publish.py）",
    "pages_dir": "sites/<id>.json → まとめのページの置き場所（publish.py・aggregate_pages）",
    "git.invited": _OB + "（配信・改修）",
    "ftp.": "private.json → 鍵の登録の雛形（--creds の FTP_CREDENTIALS_JSON）・準備状況",
    "dns.provider": "private.json → 準備状況（新規構築）",
    "dns.access": _OB + "（新規構築）",
    "ga4_property_id": "sites/<id>.json → GA4 の数字（daily_kpi・月次レポート・lead_reconcile ほか）",
    "ga4.": _OB + "（計測）",
    "ga4_measurement_id": "sites/<id>.json → WordPress のプラグイン・FTP の記事の雛形が計測タグを置く",
    "gsc.property": _OB + "（Search Console のプロパティの形）",
    "gsc_owner": "sites/<id>.json → Indexing API で送るか（notify_indexing）・接続の点検（search_connect）",
    "bing_consent": "sites/<id>.json → 当社の Bing への登録と確認ファイル（bing_webmaster・search_connect）",
    "main_offer": "sites/<id>.json → 執筆の案内（記事の着地点）・月次レポート",
    "main_category": "sites/<id>.json → カテゴリの配分の主力（site_brief）",
    "categories": "sites/<id>.json → 記事のカテゴリ（publish.py が定義外を止める）",
    "category_mix": "sites/<id>.json → カテゴリの配分（site_brief が不足を出す）",
    "service.": _BRIEF + "（売っているもの・記事の結論）",
    "customer.": _BRIEF + "（読者の困りごと・FAQ・失注の理由）",
    "theme": "sites/<id>.json → 執筆の案内・KWの選定（kw_plan）",
    "audience": "sites/<id>.json → 執筆の案内（読者像）",
    "owns": "sites/<id>.json → 守備範囲（kw_guard・kw_discover・kw_plan）",
    "avoid": "sites/<id>.json → 書いてはいけない領域（site_brief・kw_guard）",
    "target.": _BRIEF + "（ターゲット）",
    "compete.sites": "sites/<id>.json の compete.rivals（毎月の競合比較に必ず入れる: compete.py）・" + _BRIEF,
    "compete.diff": _BRIEF + "（競合との差）",
    "cta.": "sites/<id>.json の cta → 記事のボタン（publish.py）",
    "cta_title": "sites/<id>.json → 記事下の導線の見出し（publish.py）",
    "cta_desc": "sites/<id>.json → 記事下の導線の説明（publish.py）",
    "cta_mid.": "sites/<id>.json の cta_mid → 記事の中ほどの軽い入口（publish.mid_cta_block）",
    "kw.": _BRIEF + "・主題の候補（subjects）",
    "kw.regions": "sites/<id>.json の kw_seeds.regions（同じ語を持つ他社との地域の判断: sites.region_of）・" + _BRIEF,
    "kw_seeds.industries": "sites/<id>.json の kw_seeds → KWの計画（kw_plan・kw_discover・ai_kw_research）",
    "kw_seeds.intents": "sites/<id>.json の kw_seeds → KWの計画（kw_plan・kw_discover）",
    "kw_seeds.priority": "sites/<id>.json の kw_seeds.priority → KWの計画の枠と加点（kw_plan）",
    "season.peaks": "sites/<id>.json の season.peaks → 季節の前出し（season.py。1年分の検索データがそろうまで）",
    "facts.": "data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない）",
    "case.": "brief.json の cases（掲載が「可」で本人の確認が「済」だけ）→ 執筆の案内",
    "voice.": "brief.json の voices（掲載が「可」で本人が書いた・確認したものだけ）→ 執筆の案内",
    "author.": "brief.json の author → 記事の著者（publish.client_credit の Person）・執筆の案内",
    "supervisor.": "company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json",
    "supervisor.contact": "private.json（公開しない）→ 監修の確認依頼（editorial_review）・準備状況",
    "tone.": _BRIEF + "（書き方のきまり）",
    "tone.regulation": "sites/<id>.json の rules.regulation・brief.json → 執筆の案内・公開前の確認の勧め（review）",
    "ng_words": "sites/<id>.json の rules.ng_words → 含む記事の公開を止める（publish.py）・口コミの返信案（review_reply）",
    "asset.": _BRIEF + "（既存のページ・過去の施策）",
    "asset.photos": _BRIEF + "・" + _OB,
    "channels.": "sites/<id>.json の channels → 動画・SNS の投稿先（youtube_upload・post_social）・準備状況",
    "channels.contact": "private.json（公開しない）→ 許可の手続きの連絡先",
    "channels.tags": "sites/<id>.json の x_tags → SNS の投稿のタグ（social_post・post_social）",
    "gbp.status": _OB + "（Googleビジネスプロフィール）",
    "gbp.invite": _OB + "（Googleビジネスプロフィール）",
    "gbp.description": "sites/<id>.json の gbp.description → 地図の説明文（gbp.py --sync）",
    "renovate.want": _OB + "（サイト改修）",
    "renovate_auto": "sites/<id>.json の renovate_auto → 確認なしで反映してよい直し（site_renovate.auto_ok）",
    "renovate.protect": "sites/<id>.json の renovate_protect → 改修の検査で止める（site_renovate）",
    "renovate.wish": "private.json → 導入後の改修の提案の控え",
    "report_to": "private.json（公開しない）→ レポートの送付先・準備状況",
    "report_issuer": "sites/<id>.json → 月次レポートの名義（monthly_report.issuer）",
    "review_before_publish": "sites/<id>.json の rules → 確認の記録が付くまで配信しない（publish.py）",
    "monthly_cap": "sites/<id>.json の rules.monthly_cap → 月の上限（daily_audit）",
    "languages": "sites/<id>.json → 多言語の要約ページ（i18n.py・publish.py）",
    "note": "private.json（公開しない）→ 社内の申し送り",
    "link.": "brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手）",
    "shop.": "brief.json の industry_detail → 執筆の案内（業種の詳細）",
    "menu.": "brief.json の industry_detail → 執筆の案内（業種の詳細）",
    "attract.": "brief.json の industry_detail → 執筆の案内（業種の詳細）",
    "food.": "brief.json の industry_detail → 執筆の案内（業種の詳細）",
    "flink.": "brief.json の industry_detail → 執筆の案内（業種の詳細）",
}


def flow_of(key):
    """その欄の流れ先。キーそのもの、無ければ一番長い接頭辞。無ければ空（門が止める）"""
    if key in FLOW:
        return FLOW[key]
    hit = [p for p in FLOW if p.endswith(".") and key.startswith(p)]
    return FLOW[max(hit, key=len)] if hit else ""


HEAD_ROW = 3 + len(HOWTO)      # 1行目は題、2行目は一言、その下に「記入のしかた」の枠、続いて見出し
SAMPLE_ROW = HEAD_ROW + 1      # 記入欄の開始行


# ============================================================
# シートを作る
# ============================================================
def fields_for(industry=""):
    """そのシートで聞く項目。共通（1〜8章）＋外部との接点（9章）＋（あれば）業種別"""
    out = list(FIELDS) + list(BACKLINK)
    if industry:
        if industry not in INDUSTRY:
            raise SystemExit(f"未対応の業種です（{' / '.join(INDUSTRY)}）")
        out += INDUSTRY[industry][1]
        out += INDUSTRY_LINK.get(industry, [])
    return out


def req_tags(req):
    """必須の印を方式の印の集合にする。True は全方式、False は空"""
    if req is True:
        return {"*"}
    if not req:
        return set()
    return {t.strip() for t in str(req).split(",") if t.strip()}


def required_for(req, site_type):
    """その形式の社で必須か"""
    tags = req_tags(req)
    return "*" in tags or any(site_type in REQ_TYPES.get(t, ()) for t in tags)


def req_label(req):
    tags = req_tags(req)
    if "*" in tags:
        return "必須"
    if not tags:
        return ""
    return "・".join(REQ_LABEL.get(t, t) for t in sorted(tags)) + "なら必須"


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
    font = "游ゴシック"

    label = INDUSTRY[industry][0] if industry else ""
    ws["A1"] = "オウンドメディア運用 ヒアリングシート" + (f"【{label}向け】" if label else "")
    ws["A1"].font = Font(name=font, size=16, bold=True, color=navy)
    ws["A2"] = ("このシート1枚で、記事の作成・計測・検索エンジンへの通知・月次レポート・動画とSNS・"
                "サイトの改修まで、すべての機能の準備がそろいます。")
    ws["A2"].font = Font(name=font, size=10, color="5B6B84")
    ws.merge_cells("A1:E1")
    ws.merge_cells("A2:E2")
    # 記入のしかた（必須の印・別経路で預かるもの・所要時間）。読む前に書き始めると、パスワードを書かれてしまう
    for i, t in enumerate(HOWTO):
        r = 3 + i
        c = ws.cell(row=r, column=1, value=t)
        c.font = Font(name=font, size=10 if i else 11, bold=not i, color=navy if not i else "3A4A63")
        c.alignment = Alignment(wrap_text=True, vertical="center")
        for col in range(1, 6):
            ws.cell(row=r, column=col).fill = PatternFill("solid", start_color="FFF8E1")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
        ws.row_dimensions[r].height = 20 if not i else 30

    head = ["項目", "ご記入欄", "必須", "説明", "記入例（見本）"]
    for i, h in enumerate(head, 1):
        c = ws.cell(row=HEAD_ROW, column=i, value=h)
        c.font = Font(name=font, size=10, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", start_color=navy)
        c.alignment = Alignment(vertical="center")
        c.border = border
    ws.row_dimensions[HEAD_ROW].height = 22

    r = SAMPLE_ROW
    rows = {}
    for key, label, desc, ex, req in fields_for(industry):
        if key.startswith("#"):
            c = ws.cell(row=r, column=1, value=label)
            c.font = Font(name=font, size=11, bold=True, color=navy)
            for col in range(1, 6):
                ws.cell(row=r, column=col).fill = PatternFill("solid", start_color="E9EFF7")
                ws.cell(row=r, column=col).border = border
            d = ws.cell(row=r, column=4, value=desc)
            d.font = Font(name=font, size=9, color="5B6B84")
            d.alignment = Alignment(wrap_text=True, vertical="center")
            ws.row_dimensions[r].height = 30
            r += 1
            continue
        ws.cell(row=r, column=1, value=label).font = Font(name=font, size=10)
        inp = ws.cell(row=r, column=2)
        inp.fill = PatternFill("solid", start_color="EEF6FD")
        inp.alignment = Alignment(wrap_text=True, vertical="top")
        mark = req_label(req)
        rq = ws.cell(row=r, column=3, value=mark)
        rq.font = Font(name=font, size=9, bold=True, color="B42318" if mark == "必須" else "9A5B00" if mark else "5B6B84")
        rq.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        opts = CHOICES.get(key)
        note = desc + (f"\n選択肢: {' / '.join(opts)}" if opts else "")
        n = ws.cell(row=r, column=4, value=note)
        n.font = Font(name=font, size=9, color="5B6B84")
        n.alignment = Alignment(wrap_text=True, vertical="top")
        e = ws.cell(row=r, column=5, value=ex or None)
        e.font = Font(name=font, size=9, color="7A869A", italic=True)
        e.alignment = Alignment(wrap_text=True, vertical="top")
        for col in range(1, 6):
            ws.cell(row=r, column=col).border = border
        tall = max(note.count("\n"), (ex or "").count("\n"))
        ws.row_dimensions[r].height = 22 + 13 * min(tall, 6) if tall else (30 if len(note) > 60 else 22)
        # キーは右端の隠し列に置く。読み取り時に見出しの表記ゆれで壊れないため
        ws.cell(row=r, column=6, value=key)
        rows[key] = r
        r += 1

    # 選べるのは新規受付のある形式だけ（zip は新規受付なし: client_add.RETIRED）
    dv = DataValidation(type="list", formula1='"' + ",".join(NEW_TYPES) + '"')
    ws.add_data_validation(dv)
    if "type" in rows:
        dv.add(ws.cell(row=rows["type"], column=2))
    # 同じ選択肢の欄は1つの入力規則にまとめる（規則の数を増やさない）
    by_opts = {}
    for key, opts in CHOICES.items():
        if key in rows:
            by_opts.setdefault(tuple(opts), []).append(rows[key])
    for opts, rs in by_opts.items():
        v = DataValidation(type="list", formula1='"' + ",".join(opts) + '"', allow_blank=True)
        # 「済（10/7）」のような書き足しも受ける（止めずに知らせるだけ）
        v.showErrorMessage = False
        ws.add_data_validation(v)
        for row in rs:
            v.add(ws.cell(row=row, column=2))

    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 44
    ws.column_dimensions["C"].width = 10
    ws.column_dimensions["D"].width = 58
    ws.column_dimensions["E"].width = 36
    ws.column_dimensions["F"].hidden = True
    ws.freeze_panes = ws.cell(row=SAMPLE_ROW, column=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ============================================================
# シートを読む
# ============================================================
def read_sheet(path):
    """F列（隠し列）にキーのある行の、B列の値。1行目から見る（記入のしかたの枠の行数が変わっても、
    以前の版のシート（4行目から記入欄）でも読める）"""
    from openpyxl import load_workbook
    ws = load_workbook(path, data_only=True).active
    got = {}
    for row in range(1, ws.max_row + 1):
        key = ws.cell(row=row, column=6).value
        if not key or str(key).startswith("#"):
            continue
        v = ws.cell(row=row, column=2).value
        if v is None or str(v).strip() == "":
            continue
        got[str(key)] = str(v).strip()
    # 以前の版の欄の名前（gsc_ready・asset.gbp）を今の欄へ寄せる
    if "gbp.status" not in got and got.get("asset.gbp"):
        got["gbp.status"] = got["asset.gbp"]
    return got


def choice(got, key):
    """プルダウンの欄の値を選択肢に寄せる（先頭が一致するもの）。無ければ空"""
    v = str(got.get(key) or "").strip()
    opts = CHOICES.get(key, [])
    if v in opts:
        return v
    hit = [o for o in opts if v.startswith(o) or v.startswith(o.split("（")[0])]
    return max(hit, key=len) if hit else ""


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
        # 動画・SNSの投稿先（鍵は持たない。接続は youtube_upload --auth / social_connect で当社が行う）。
        # 手続きの担当者（氏名とメール）は public の sites/ に置かず private.json へ（to_private）
        "channels": {k: got.get(f"channels.{k}", "") for k in
                     ("youtube", "video", "facebook", "instagram", "threads", "linkedin", "x", "admin_added")},
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
    # 計測を当社が入れるのは、ページを当社が出す方式だけ。WordPress は当社のプラグイン、ftp（と互換で残す zip）は
    # 当社が書き出す記事の雛形が、測定IDのある社だけ計測を置く。Git の方式は先方のテンプレートが持つ
    if cfg["type"] in ("wordpress", "ftp", "zip") and got.get("ga4_measurement_id"):
        cfg["ga4_measurement_id"] = str(got["ga4_measurement_id"]).strip()
    mix = pairs(got.get("category_mix"), num=True)
    if mix:
        cfg["category_mix"] = mix
    # 検索エンジンへの最初の接続。オーナーでなければ Indexing API で送らない（notify_indexing.gsc_owner_ok）。
    # Bing は「可」と書いた社だけ当社のアカウントへ足す（bing_webmaster.client_cfgs）。空欄は同意なしとして扱う
    cfg["gsc_owner"] = str(got.get("gsc_owner", "")).startswith("済")
    cfg["bing_consent"] = str(got.get("bing_consent", "")).strip() == "可"
    # 月次レポートの名義（monthly_report.issuer）。「お客様名だけ」以外は当社名義（既定）
    cfg["report_issuer"] = "client" if "お客様" in (got.get("report_issuer") or "") else "operator"
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

    # ── ここから下は、シートの欄を各機能が読む設定へ流す（docs/intake-requirements.md の「流れ先」）
    # Git の方式のまとめのページ（業種・用語集・比較）の置き場（publish.py が読む）
    if got.get("pages_dir"):
        cfg["pages_dir"] = got["pages_dir"].strip().strip("/")
    # 地域（sites.region_of: 他社と同じ語を持ったときの判断）と優先業種（kw_plan の枠と加点）
    if lines(got.get("kw.regions")):
        cfg["kw_seeds"]["regions"] = lines(got["kw.regions"])
    if lines(got.get("kw_seeds.priority")):
        cfg["kw_seeds"]["priority"] = lines(got["kw_seeds.priority"])
    # 繁忙期（season.py: 1年分の検索データがそろうまでは、この申告で山の月を決める）
    peaks = season_peaks(got.get("season.peaks"))
    if peaks:
        cfg["season"] = {"peaks": peaks}
    # 競合（compete.py: AIの出典に出た回数が少なくても、挙げた社は毎月の比較に入れる）
    rivals = rival_domains(got.get("compete.sites"), cfg["domain"])
    if rivals:
        cfg["compete"] = {"rivals": rivals}
    # 記事の中ほどの軽い入口（publish.mid_cta_block）
    if got.get("cta_mid.url"):
        cfg["cta_mid"] = {"label": got.get("cta_mid.label") or cfg["cta"]["label"], "url": got["cta_mid.url"]}
    # SNS のタグ（social_post / post_social が読む x_tags）
    if lines(got.get("channels.tags")):
        cfg["x_tags"] = [t.lstrip("#＃") for t in lines(got["channels.tags"])]
    # 地図の説明文（gbp.py --sync が揃える。店舗の location は鍵をもらった後に gbp.py --check で当社が書く）
    if got.get("gbp.description"):
        cfg["gbp"] = {"description": got["gbp.description"][:750]}
    # サイトの改修: 確認なしで反映してよい範囲（site_renovate.auto_ok）と、触ってはいけないページ（site_renovate の検査）
    auto = {"CSSのみ": ["css"], "文言のみ": ["text"], "CSSと文言": ["css", "text"]}.get(choice(got, "renovate_auto"))
    if auto:
        cfg["renovate_auto"] = auto
    protect = [("/" + p.strip().strip("/") + "/").replace("//", "/") for p in lines(got.get("renovate.protect"))]
    if protect:
        cfg["renovate_protect"] = protect
    # 業種の表現の決まり（site_brief が書き手に渡す・準備状況が公開前の確認と突き合わせる）
    if lines(got.get("tone.regulation")):
        cfg.setdefault("rules", {})["regulation"] = lines(got["tone.regulation"])
    # 最初の接続の状況（鍵ではなく、済/未などの印だけ）。準備状況（intake_readiness）が読む
    ob = {k: v for k, v in {
        "ga4_viewer": choice(got, "ga4.viewer") == "済",
        "ga4_installed": choice(got, "ga4.installed") == "入っている",
        "gsc_property": choice(got, "gsc.property"),
        "git_invited": choice(got, "git.invited") == "済",
        "wp_plugin": choice(got, "wp.plugin"),
        "wp_admin_key": choice(got, "wp.admin_key") == "出せる",
        "ftp_ok": choice(got, "wp.ftp") == "出せる",
        "keys_sent": choice(got, "keys.sent"),
        "dns_access": choice(got, "dns.access"),
        "renovate": choice(got, "renovate.want") == "あり",
        "gbp_status": choice(got, "gbp.status"),
        "gbp_invite": choice(got, "gbp.invite") == "可",
        "photos": choice(got, "asset.photos") == "あり",
    }.items() if v}
    cfg["onboarding"] = ob
    return cfg


def season_peaks(v):
    """「12月: 年末調整、決算」の並びを [{"month": 12, "words": [...]}] にする"""
    out = []
    for ln in lines(v):
        months = [int(m) for m in re.findall(r"(\d{1,2})\s*月", ln) if 1 <= int(m) <= 12]
        words = [w for w in re.split(r"[、,，・/／\s]+", re.split(r"[:：]", ln, maxsplit=1)[-1]) if w and "月" not in w]
        for m in months:
            out.append({"month": m, "words": words})
    return out


def rival_domains(v, own=""):
    """競合のURLの並びからドメインだけを取る（自社のドメインは除く）"""
    out = []
    for ln in lines(v):
        d = re.sub(r"^https?://", "", ln.strip()).split("/")[0].lower().removeprefix("www.")
        if "." in d and d != (own or "").lower().removeprefix("www.") and d not in out:
            out.append(d)
    return out


def to_private(got):
    """公開リポジトリに置けないもの（担当者のメール・社内の申し送り・接続先のホスト名）。
    data/clients/<id>/private.json に書き、.gitignore で外す。パスワード類はシートで聞かない"""
    out = {}
    if got.get("report_to"):
        out["report_to"] = [x.strip() for x in got["report_to"].replace("、", ",").split(",")
                            if x.strip()]
    if got.get("note"):
        out["note"] = got["note"]
    for k in ("channels.contact", "supervisor.contact"):
        if got.get(k):
            out[k.replace(".", "_")] = got[k]
    # 担当者・接続先（パスワード以外）。鍵を登録するときの雛形（--creds）と準備状況が読む
    for sec, keys in (("contact", ("name", "email", "tel")), ("wp", ("admin_url", "user")),
                      ("ftp", ("host", "protocol", "user", "root")), ("dns", ("provider",))):
        d = {k: got[f"{sec}.{k}"] for k in keys if got.get(f"{sec}.{k}")}
        if d:
            out[sec] = d
    if got.get("wp_note"):               # 以前の版のシートの欄
        out.setdefault("wp", {})["note"] = got["wp_note"]
    if got.get("renovate.wish"):
        out["renovate_wish"] = got["renovate.wish"]
    return out


def creds_template(site_id, priv):
    """別経路で受け取った鍵を登録するときの形（パスワードの欄は空）。
    FTP_CREDENTIALS_JSON / WP_CREDENTIALS_JSON に、この社の分として足す"""
    out = {}
    f = priv.get("ftp") or {}
    if f.get("host"):
        out["FTP_CREDENTIALS_JSON"] = {site_id: {"protocol": (f.get("protocol") or "ftps").lower(), "host": f["host"],
                                                 "user": f.get("user", ""), "password": "<別経路で受け取ったもの>",
                                                 "root": f.get("root", "")}}
    w = priv.get("wp") or {}
    if w.get("user"):
        out["WP_CREDENTIALS_JSON"] = {site_id: {"user": w["user"], "password": "<アプリケーションパスワード>"}}
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
        # 監修者の資格・範囲を書き手に渡す（範囲の外のことを「監修済み」のように書かせない）
        "supervisor": {k: v for k, v in to_supervisor(got).items() if k != "contact"},
        "tone": pick("tone"),
        "compete": pick("compete"),
        "asset": pick("asset"),
        "backlink": pick("link"),
        "target": pick("target"),
        "keyword": pick("kw"),
        "subjects": subjects(got),
        # 掲載が「可」で、ご本人の確認が済んだものだけ（事業者が作った感想を声として出さない）
        "cases": usable_cases(got),
        "voices": usable_voices(got),
    }
    # 業種別の項目だけを拾う（業種別の章に定義された接頭辞の許可リスト）。
    # 接頭辞を除外リストで見ていたため、章を足すたびに担当者のメールなどが public の brief.json に出うる
    allowed = {k.split(".")[0] for _, fields in INDUSTRY.values() for k, *_ in fields if not k.startswith("#")}
    allowed |= {k.split(".")[0] for fields in INDUSTRY_LINK.values() for k, *_ in fields if not k.startswith("#")}
    for pre in sorted(set(k.split(".")[0] for k in got if "." in k) & allowed):
        brief.setdefault("industry_detail", {})[pre] = pick(pre)
    # 改行区切りで書かれたものは配列にしておく。記事側で1つずつ使える
    multi = {"backlink": ["orgs", "portals", "partners", "awards", "press",
                         "gov", "person", "known"],
             "target": ["decide"],
             "keyword": ["main", "sub", "area_word", "exclude", "known", "regions"],
             "service": ["list", "strength", "priority", "why_chosen"],
             "customer": ["problem", "faq", "ng", "lost"],
             "author": ["credential"], "tone": ["avoid", "regulation"],
             "compete": ["sites"], "asset": ["sns", "top_pages", "failed"]}
    for sec, keys in multi.items():
        for k in keys:
            if brief.get(sec, {}).get(k):
                brief[sec][k] = lines(brief[sec][k])
    for sec in (brief.get("industry_detail") or {}).values():
        for k, v in list(sec.items()):
            if isinstance(v, str) and chr(10) in v:
                sec[k] = lines(v)
    return brief


def usable_cases(got):
    """記事に使ってよい事例。掲載が「可」でご本人の確認が「済」のものだけ"""
    out = []
    for i in ("1", "2"):
        if not got.get(f"case.{i}.summary"):
            continue
        pub = choice(got, f"case.{i}.publish")
        if pub.startswith("可") and choice(got, f"case.{i}.confirmed") == "済":
            out.append({"summary": got[f"case.{i}.summary"], "result": got.get(f"case.{i}.result", ""),
                        "show_name": pub == "可（社名を出す）"})
    return out


def usable_voices(got):
    """記事に使ってよいお客様の声。掲載が「可」で、本人が書いたか本人が内容を確認したものだけ"""
    out = []
    for i in ("1", "2"):
        if not got.get(f"voice.{i}.text"):
            continue
        if choice(got, f"voice.{i}.publish") == "可" and choice(got, f"voice.{i}.by") in ("本人が書いた", "本人が内容を確認した"):
            out.append({"text": got[f"voice.{i}.text"], "name": got.get(f"voice.{i}.name", "")})
    return out


def to_supervisor(got):
    """記事の監修者（お客様ご本人）。表示・構造化データ（reviewedBy）に使う。
    確認の連絡先は記事に出さないので、表示用の項目と分けて持つ"""
    s = {k.split(".", 1)[1]: v for k, v in got.items() if k.startswith("supervisor.")}
    if not s:
        return {}
    for k in ("qualification", "career", "same_as"):
        if s.get(k):
            s[k] = lines(s[k])
    s["display"] = str(s.get("consent", "")).strip() == "可"
    return s


def to_company(got):
    out = {k.split(".", 1)[1]: v for k, v in got.items() if k.startswith("company.")}
    sup = to_supervisor(got)
    if sup:
        out["supervisor"] = {k: v for k, v in sup.items() if k != "contact"}
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

    # シートに出す項目と同じ一覧で見る。FIELDS だけを見ていたため、書き手・監修者の章の必須が効いていなかった。
    # 方式の印（WordPressなら必須など）は、選んだ形式の社でだけ必須にする
    site_type = cfg.get("type") or got.get("type", "")
    for key, label, _, _, req in fields_for():
        # 配信先と接頭辞は下で理由つきの文言で見る（同じ不備を2回出さない）
        if key.startswith("#") or key in ("repo", "url_prefix") or got.get(key) or not required_for(req, site_type):
            continue
        tags = req_tags(req)
        ng.append(f"「{label}」が空です" + ("" if "*" in tags else f"（{req_label(req)}）"))
    # 選択肢の欄に選択肢に無い値（止めずに知らせる。読めない値は「未」と同じ扱いになる）
    for key, opts in CHOICES.items():
        if got.get(key) and not choice(got, key):
            warn.append(f"「{next((f[1] for f in FIELDS if f[0] == key), key)}」の値「{str(got[key])[:20]}」が"
                        f"選択肢（{' / '.join(opts)}）にありません")
    if got.get("contact.email") and "@" not in str(got["contact.email"]):
        warn.append("ご担当者のメールがメールアドレスになっていません（導入の連絡が届きません）")
    if site_type == "wordpress" and choice(got, "wp.plugin") == "置けない":
        warn.append("品質の検査のプラグインを置けないと、90点に届かない記事を WordPress 側で止められません"
                    "（管制塔は90点未満を送りませんが、管理画面で公開されたものは止まりません）")
    if choice(got, "gsc.property") == "ドメインだけ":
        warn.append(f"Search Console がドメインのプロパティだけです。https://{cfg.get('domain') or 'ドメイン'}/ の"
                    "URLプレフィックスのプロパティを足して当社を追加していただくまで、順位・検索語が取れません")
    if lines(got.get("tone.regulation")) and not str(got.get("review_before_publish", "")).startswith("要"):
        warn.append("業種の表現の決まりがあるのに、公開前の確認が「要」ではありません（医療・金融などは「要」を推奨）")
    for i in ("1", "2"):
        if got.get(f"voice.{i}.text") and choice(got, f"voice.{i}.by") not in ("本人が書いた", "本人が内容を確認した"):
            warn.append(f"お客様の声 {'①' if i == '1' else '②'} は本人の確認が無いため記事に使いません")
    # 同意が「可」でない方を監修者として表示すると、事実と違う表示になる
    if got.get("supervisor.name") and str(got.get("supervisor.consent", "")).strip() != "可":
        ng.append("監修者の「掲載の同意」が「可」ではありません（同意をいただいてから登録します）")
    if got.get("supervisor.contact") and "@" not in str(got["supervisor.contact"]):
        ng.append("監修者の「確認のご連絡先」がメールアドレスになっていません")

    if cfg.get("id") and not re.fullmatch(r"[a-z][a-z0-9-]*", cfg["id"]):
        ng.append("サイトIDは英小文字とハイフンのみで書いてください")
    if cfg.get("type") in RETIRED:
        ng.append(f"サイトの形式「{cfg['type']}」は選べません: {RETIRED[cfg['type']]}")
    elif cfg.get("type") not in TYPES:
        ng.append(f"サイトの形式が不正です（{' / '.join(NEW_TYPES)}）")
    # wordpress は REST API で投稿するのでリポジトリは要らない（client_add と同じ条件）。
    # ここで止めると、repo 欄を空にした WordPress の社がいつまでも登録できない
    if cfg.get("type") not in ("self-static", "wordpress", "ftp", "zip") and not cfg.get("repo"):
        ng.append("配信先リポジトリが空です（自社構築以外は書き込み先が要ります）")
    # 以前は空欄に "/blog" を補っていた。実際の記事URLが違えば、sitemap も通知も
    # 存在しないURLを指す。推測で埋めず、書いてもらう。
    # WordPress は記事のURLを先方のパーマリンク設定が決め、管制塔は REST で実際のURLを読む（wp_bridge）。
    # /%postname%/ の社は接頭辞が無いので、空欄で止めると登録できなかった
    if (cfg.get("type") in TYPES and cfg["type"] not in ("self-static", "wordpress")
            and not cfg.get("url_prefix")):
        ng.append("記事URLの接頭辞が空です（記事が /blog/xxx/ に出るなら /blog と書いてください）")
    if cfg.get("ga4_measurement_id") and not re.fullmatch(r"G-[A-Z0-9]{4,20}", cfg["ga4_measurement_id"]):
        ng.append("GA4の測定IDは G- で始まる形で書いてください（例: G-AB12CD34EF）")
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
    if not cfg.get("gsc_owner"):
        warn.append(f"要対応: {cfg.get('name') or cfg.get('id')} の Search Console にサービスアカウントをオーナーで追加"
                    "（オーナーになるまで、新しい記事を Indexing API で知らせません。追加されれば設定を直さなくても送り始めます）")
    if not cfg.get("bing_consent"):
        warn.append("Bing への登録の同意が「可」ではありません。Bing（ChatGPT の検索も使う索引）へは送りません"
                    "（IndexNow の通知だけ届きます）")

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
    if "--creds" in sys.argv:
        k = sys.argv.index("--creds")
        return print_creds(sys.argv[k + 1]) if k + 1 < len(sys.argv) else 1
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
    print(f"    2. 別経路で受け取った鍵を登録する（形は python scripts/client_intake.py --creds {cfg['id']}）")
    print("    3. python scripts/search_connect.py --check   … 検索エンジンへの接続で残っていることを見る")
    if cfg.get("type") != "self-static":
        print("    4. python scripts/token_check.py   … 配信先に書き込めるか確認する")
    if (cfg.get("rules") or {}).get("review_before_publish"):
        print("    ※ このクライアントは公開前の確認が必要です。自動公開を切ってください")
    # 機能ごとの準備状況（シートと鍵の有無で判定。本番の点検は onboard_check）
    print()
    import intake_readiness as R
    for line in R.check_site(cfg["id"]):
        print("  " + line)
    return 0


def print_creds(site_id):
    """別経路で受け取った鍵を登録するときの形（パスワードの欄は空）。private.json の接続先から作る"""
    p = ROOT / "data" / "clients" / site_id / "private.json"
    priv = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    t = creds_template(site_id, priv)
    if not t:
        print(f"{site_id}: 登録の形を作れる接続先（FTP のホスト・WordPress のユーザー名）がシートにありません")
        return 1
    for name, body in t.items():
        print(f"■ {name} に足す分（<…> を受け取った値に置き換える。Secret と手元の鍵ファイルの両方）")
        print(json.dumps(body, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
