# ヒアリングシートで受けるもの（機能ごと）

> `python scripts/intake_readiness.py --doc` で作り直す（手で直さない）。欄の定義は `scripts/client_intake.py`、判定は `scripts/intake_readiness.py`。
> シートを `intake/` に置く（または `client_intake.py <シート> --apply`）と、最後に下の機能ごとの準備状況が出て、`data/clients/<id>/readiness.json`（public に置かない）に残る。要対応は週次の通知（findings）にも載る。

## 機能ごとに要るもの

| 機能 | シートの欄 | 別経路で受け取るもの | 無いとどうなるか |
|:--|:--|:--|:--|
| 記事の配信（新記事・書き直し・まとめのページ・統合の転送） | サイトの形式（`type`）・公開ドメイン（`domain`）・記事URLの接頭辞（`url_prefix`）・管理画面のURL（`wp.admin_url`）・投稿用のユーザー名（`wp.user`）・配信先リポジトリ（`repo`）・ブランチ（`branch`）・記事の置き場所（`content_dir`）・画像の置き場所（`images_dir`）・まとめのページの置き場所（`pages_dir`）・当社アカウントの招待（Write）（`git.invited`）・FTP のホスト名（`ftp.host`）・接続の方式（`ftp.protocol`）・FTP のユーザー名（`ftp.user`）・公開フォルダ（`ftp.root`）・DNS の管理会社（`dns.provider`）・DNS の設定（`dns.access`）・別経路でお送りする鍵（`keys.sent`） | WordPress: アプリケーションパスワード（WP_CREDENTIALS_JSON）／FTP: パスワード（FTP_CREDENTIALS_JSON）／Git: 当社の配信用トークン（SITE_PUSH_TOKEN）／新規構築: DNS のログイン情報（当社が行う場合） | 記事が1本も届かない |
| 品質ゲート（WordPress 側で90点未満を公開させない） | 品質の検査のプラグイン（`wp.plugin`）・FTP の接続情報（`wp.ftp`） | 当社が置く場合は FTP のパスワード | 管理画面から公開された記事を止められない（管制塔からは90点未満を送らない） |
| 記事の中身（一次情報・FAQ・著者・監修の表示） | 実績・数値 ①（`facts.1.claim`）・よく聞かれる質問（`customer.faq`）・著者名（`author.name`）・掲載の同意（`supervisor.consent`） | — | どこにでもある記事になり、AI検索に引用されない。監修の表示が出せない |
| 監修の確認依頼（editorial_review） | 確認のご連絡先（`supervisor.contact`）・記事の確かめ方（`supervisor.review`） | — | 公開前の確認が「要」の社は、確認依頼が届かず記事が止まったままになる |
| 計測（GA4・CTA・フォーム・入口） | GA4プロパティID（`ga4_property_id`）・GA4 に当社を閲覧者で追加（`ga4.viewer`）・サイトに GA4 が入っているか（`ga4.installed`）・GA4の測定ID（G-で始まる）（`ga4_measurement_id`） | — | 月次レポートに流入・問い合わせの数字が出ない。導線の効きが測れない |
| 検索の実績（順位・検索語: 月次レポート・競合比較・効果判定・季節） | Search Consoleのオーナー権限（`gsc_owner`）・Search Console のプロパティの種類（`gsc.property`） | — | 順位と検索語が取れず、レポート・書き直しの判定・押し上げが動かない |
| Indexing API（Google への即時通知） | Search Consoleのオーナー権限（`gsc_owner`） | — | 新しい記事を Google へすぐ知らせられない（サイトマップで後から拾われる） |
| Bing（Webmaster API） | Bing・検索エンジンへの登録の同意（`bing_consent`） | — | Bing・ChatGPT の検索へは IndexNow の通知だけになる |
| 月次レポートの宛先と名義 | レポートの送付先（`report_to`）・月次レポートの発行者の表示（`report_issuer`）・問い合わせメール（`company.email`） | — | レポートの宛先が決まらない |
| 競合比較の相手 | 競合のサイト（3社）（`compete.sites`） | — | AIの出典から自動で選ぶ（挙げた競合が比較に出ないことがある） |
| 季節の前出し | 繁忙期と、その時期に増える相談（`season.peaks`） | — | 1年分の検索データがそろうまで、繁忙期の前に記事を前へ出せない |
| YouTube への動画の投稿 | YouTubeチャンネル（`channels.youtube`）・動画を上げるか（`channels.video`）・当社を管理者に追加済みか（`channels.admin_added`） | 先方の Google アカウントでの許可（1回・当社が手続き） | 動画を作らない（当社のチャンネルには上げない） |
| SNS への投稿（Facebook・Instagram・Threads・LinkedIn） | Facebookページ（`channels.facebook`）・Instagram（`channels.instagram`）・Threads（`channels.threads`）・LinkedIn会社ページ（`channels.linkedin`）・当社を管理者に追加済みか（`channels.admin_added`）・SNS に付けるタグ（`channels.tags`） | 先方のアカウントでの許可（1回・当社が手続き） | その社の SNS には投稿しない |
| Googleビジネスプロフィール（説明文・属性・口コミの返信案） | Googleビジネスプロフィール（`gbp.status`）・当社をプロフィールの管理者に追加（`gbp.invite`）・地図に出す説明文（`gbp.description`） | 先方の Google アカウントでの許可（1回・当社が手続き） | 地図の説明文・属性を揃えられない。口コミの件数を知らせられない |
| 多言語の要約ページ | 多言語の要約ページ（`languages`） | — | 作らない（既定） |
| 指示でのサイト改修 | 改修のご希望（`renovate.want`）・確認なしで反映してよい範囲（`renovate_auto`）・触ってはいけないページ（`renovate.protect`）・直したいところ（`renovate.wish`）・改修用の管理者の鍵（`wp.admin_key`）・FTP の接続情報（`wp.ftp`）・当社アカウントの招待（Write）（`git.invited`） | WordPress: 管理者のアプリケーションパスワード／FTP: パスワード／Git: 招待 | サイトの改修を管制塔から行えない（記事の配信だけになる） |
| 表示速度の直し（WordPress のテーマ） | FTP の接続情報（`wp.ftp`）・FTP のホスト名（`ftp.host`） | FTP のパスワード | テーマに直書きのフォント・計測タグは測って知らせるだけになる |

## シートの欄が要らない機能

配信の接続（上の「記事の配信」）が済めば、欄を追加でもらわずに動く: 表の数字の横棒グラフ・一覧の写真・サムネイル・OGP画像・robots.txt（AIクローラーの許可）・IndexNow・構造化データ: 実体（about・mentions）・検索での見え方（robots の meta・画像/動画のサイトマップ）・記事内の入口（inline_tool・CTA の差し込み）・多言語メニュー（/menu/）・サイト監査（Ahrefs 相当）・描画の検査（原稿→HTML の崩れ）・検索から外す記事（noindex）。

お客様のサイトには置かない（運用会社自身のページ）: 業種別LP（/lp/<業種>/）・一次データ・調査ページ（/data/・/research/）・無料ツール（/tools/）・問い合わせの自動回答・追いかけ。

## 欄ごとの流れ先

シートの全欄が、どこかの設定か準備状況へ流れる（流れない欄は作らない。門 `tests/gates_history_h38.py` が欄を1つずつ抜いて、出力が変わることを確かめる）。

| 章 | 欄 | キー | 流れ先 |
|:--|:--|:--|:--|
| 1. 会社・担当・連絡先 | 会社名（正式） | `company.name` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | 英語表記 | `company.name_en` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | 法人番号 | `company.corporate_number` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | 郵便番号 | `company.postal` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | 住所 | `company.address` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | 電話番号 | `company.tel` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | 営業時間 | `company.hours` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | 創業年月日 | `company.founded` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | 資本金 | `company.capital` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | 代表者名 | `company.ceo` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | 問い合わせメール | `company.email` | data/clients/<id>/company.json → 発行元・著者の構造化データ・月次レポートの宛名・表記ゆれの検査（nap_check） |
| 1. 会社・担当・連絡先 | ご担当者のお名前 | `contact.name` | private.json（公開しない）→ 導入の手続きの連絡先 |
| 1. 会社・担当・連絡先 | ご担当者のメール | `contact.email` | private.json（公開しない）→ 導入の手続きの連絡先 |
| 1. 会社・担当・連絡先 | ご担当者の電話 | `contact.tel` | private.json（公開しない）→ 導入の手続きの連絡先 |
| 2. サイトと納品方式 | サイトID | `id` | sites/<id>.json のファイル名 → 全工程のサイトID |
| 2. サイトと納品方式 | メディア名 | `name` | sites/<id>.json → 記事一覧・レポート・通知の表示名 |
| 2. サイトと納品方式 | 公開ドメイン | `domain` | sites/<id>.json → 記事URL・sitemap・通知（IndexNow・Indexing API・Bing）・Search Console の https://ドメイン/ |
| 2. サイトと納品方式 | サイトの形式 | `type` | sites/<id>.json → 配信の方式（publish.py）・準備状況の判定 |
| 2. サイトと納品方式 | 記事URLの接頭辞 | `url_prefix` | sites/<id>.json → 記事URL（sites.article_url） |
| 2. サイトと納品方式 | 別経路でお送りする鍵 | `keys.sent` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（受領待ちか要対応か） |
| 2-1. WordPress の場合 | 管理画面のURL | `wp.admin_url` | private.json → 準備状況・導入の手続き |
| 2-1. WordPress の場合 | 投稿用のユーザー名 | `wp.user` | private.json → 鍵の登録の雛形（--creds の WP_CREDENTIALS_JSON）・準備状況（配信） |
| 2-1. WordPress の場合 | 品質の検査のプラグイン | `wp.plugin` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（品質ゲート） |
| 2-1. WordPress の場合 | 改修用の管理者の鍵 | `wp.admin_key` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（サイト改修） |
| 2-1. WordPress の場合 | FTP の接続情報 | `wp.ftp` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（品質ゲート・表示速度の直し） |
| 2-1. WordPress の場合 | WordPressのAPIのURL | `wp_api` | sites/<id>.json → WordPress の REST の入口（publish.py） |
| 2-2. Git（GitHub）の場合 | 配信先リポジトリ | `repo` | sites/<id>.json → 配信先（publish.py・site_change.py） |
| 2-2. Git（GitHub）の場合 | ブランチ | `branch` | sites/<id>.json → 配信先のブランチ（publish.py） |
| 2-2. Git（GitHub）の場合 | 記事の置き場所 | `content_dir` | sites/<id>.json → 記事の置き場所（publish.py） |
| 2-2. Git（GitHub）の場合 | 画像の置き場所 | `images_dir` | sites/<id>.json → 画像の置き場所（publish.py） |
| 2-2. Git（GitHub）の場合 | まとめのページの置き場所 | `pages_dir` | sites/<id>.json → まとめのページの置き場所（publish.py・aggregate_pages） |
| 2-2. Git（GitHub）の場合 | 当社アカウントの招待（Write） | `git.invited` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（配信・改修） |
| 2-3. FTP（レンタルサーバー）の場合 | FTP のホスト名 | `ftp.host` | private.json → 鍵の登録の雛形（--creds の FTP_CREDENTIALS_JSON）・準備状況 |
| 2-3. FTP（レンタルサーバー）の場合 | 接続の方式 | `ftp.protocol` | private.json → 鍵の登録の雛形（--creds の FTP_CREDENTIALS_JSON）・準備状況 |
| 2-3. FTP（レンタルサーバー）の場合 | FTP のユーザー名 | `ftp.user` | private.json → 鍵の登録の雛形（--creds の FTP_CREDENTIALS_JSON）・準備状況 |
| 2-3. FTP（レンタルサーバー）の場合 | 公開フォルダ | `ftp.root` | private.json → 鍵の登録の雛形（--creds の FTP_CREDENTIALS_JSON）・準備状況 |
| 2-4. 当社で新しく作る場合（self-static） | DNS の管理会社 | `dns.provider` | private.json → 準備状況（新規構築） |
| 2-4. 当社で新しく作る場合（self-static） | DNS の設定 | `dns.access` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（新規構築） |
| 3. 計測と検索エンジン | GA4プロパティID | `ga4_property_id` | sites/<id>.json → GA4 の数字（daily_kpi・月次レポート・lead_reconcile ほか） |
| 3. 計測と検索エンジン | GA4 に当社を閲覧者で追加 | `ga4.viewer` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（計測） |
| 3. 計測と検索エンジン | サイトに GA4 が入っているか | `ga4.installed` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（計測） |
| 3. 計測と検索エンジン | GA4の測定ID（G-で始まる） | `ga4_measurement_id` | sites/<id>.json → WordPress のプラグイン・FTP の記事の雛形が計測タグを置く |
| 3. 計測と検索エンジン | Search Console のプロパティの種類 | `gsc.property` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（Search Console のプロパティの形） |
| 3. 計測と検索エンジン | Search Consoleのオーナー権限 | `gsc_owner` | sites/<id>.json → Indexing API で送るか（notify_indexing）・接続の点検（search_connect） |
| 3. 計測と検索エンジン | Bing・検索エンジンへの登録の同意 | `bing_consent` | sites/<id>.json → 当社の Bing への登録と確認ファイル（bing_webmaster・search_connect） |
| 4. 商材・強み・読者 | 主力商材（1行） | `main_offer` | sites/<id>.json → 執筆の案内（記事の着地点）・月次レポート |
| 4. 商材・強み・読者 | 利益の大きい順の商材 | `service.priority` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（売っているもの・記事の結論） |
| 4. 商材・強み・読者 | 主力カテゴリ | `main_category` | sites/<id>.json → カテゴリの配分の主力（site_brief） |
| 4. 商材・強み・読者 | カテゴリ一覧 | `categories` | sites/<id>.json → 記事のカテゴリ（publish.py が定義外を止める） |
| 4. 商材・強み・読者 | カテゴリの配分 | `category_mix` | sites/<id>.json → カテゴリの配分（site_brief が不足を出す） |
| 4. 商材・強み・読者 | 提供しているもの | `service.list` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（売っているもの・記事の結論） |
| 4. 商材・強み・読者 | 価格帯 | `service.price` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（売っているもの・記事の結論） |
| 4. 商材・強み・読者 | 価格の載せ方 | `service.price_policy` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（売っているもの・記事の結論） |
| 4. 商材・強み・読者 | 提供エリア | `service.area` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（売っているもの・記事の結論） |
| 4. 商材・強み・読者 | 他社と違う点 | `service.strength` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（売っているもの・記事の結論） |
| 4. 商材・強み・読者 | 選ばれる理由 | `service.why_chosen` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（売っているもの・記事の結論） |
| 4. 商材・強み・読者 | よく失注する理由 | `customer.lost` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（読者の困りごと・FAQ・失注の理由） |
| 4. 商材・強み・読者 | 問い合わせから成約・開始までの流れ | `service.flow` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（売っているもの・記事の結論） |
| 4. 商材・強み・読者 | 何を扱うメディアか | `theme` | sites/<id>.json → 執筆の案内・KWの選定（kw_plan） |
| 4. 商材・強み・読者 | 誰に向けたものか | `audience` | sites/<id>.json → 執筆の案内（読者像） |
| 4. 商材・強み・読者 | 自社が扱う語 | `owns` | sites/<id>.json → 守備範囲（kw_guard・kw_discover・kw_plan） |
| 4. 商材・強み・読者 | 扱わない領域 | `avoid` | sites/<id>.json → 書いてはいけない領域（site_brief・kw_guard） |
| 4-1. 読者（誰に読ませるか） | いちばん来てほしいお客様 | `target.persona` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（ターゲット） |
| 4-1. 読者（誰に読ませるか） | その次に来てほしい層 | `target.second` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（ターゲット） |
| 4-1. 読者（誰に読ませるか） | 商圏・エリア | `target.area` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（ターゲット） |
| 4-1. 読者（誰に読ませるか） | 検討の段階 | `target.stage` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（ターゲット） |
| 4-1. 読者（誰に読ませるか） | 決め手になること | `target.decide` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（ターゲット） |
| 4-1. 読者（誰に読ませるか） | お客様が困っていること | `customer.problem` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（読者の困りごと・FAQ・失注の理由） |
| 4-1. 読者（誰に読ませるか） | よく聞かれる質問 | `customer.faq` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（読者の困りごと・FAQ・失注の理由） |
| 4-1. 読者（誰に読ませるか） | 問い合わせのきっかけ | `customer.trigger` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（読者の困りごと・FAQ・失注の理由） |
| 4-1. 読者（誰に読ませるか） | よくある誤解 | `customer.ng` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（読者の困りごと・FAQ・失注の理由） |
| 4-2. 競合 | 競合のサイト（3社） | `compete.sites` | sites/<id>.json の compete.rivals（毎月の競合比較に必ず入れる: compete.py）・data/clients/<id>/brief.json → 執筆の案内（site_brief） |
| 4-2. 競合 | 競合にはない自社の強み | `compete.diff` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（競合との差） |
| 4-3. 記事から問い合わせへの導線 | ボタンの文言 | `cta.label` | sites/<id>.json の cta → 記事のボタン（publish.py） |
| 4-3. 記事から問い合わせへの導線 | 遷移先URL | `cta.url` | sites/<id>.json の cta → 記事のボタン（publish.py） |
| 4-3. 記事から問い合わせへの導線 | 記事下の見出し | `cta_title` | sites/<id>.json → 記事下の導線の見出し（publish.py） |
| 4-3. 記事から問い合わせへの導線 | 記事下の説明文 | `cta_desc` | sites/<id>.json → 記事下の導線の説明（publish.py） |
| 4-3. 記事から問い合わせへの導線 | 補足 | `cta.note` | sites/<id>.json の cta → 記事のボタン（publish.py） |
| 4-3. 記事から問い合わせへの導線 | 記事の中ほどの軽い入口 | `cta_mid.label` | sites/<id>.json の cta_mid → 記事の中ほどの軽い入口（publish.mid_cta_block） |
| 4-3. 記事から問い合わせへの導線 | 軽い入口のURL | `cta_mid.url` | sites/<id>.json の cta_mid → 記事の中ほどの軽い入口（publish.mid_cta_block） |
| 5. 記事の材料：狙う語 | メインキーワード | `kw.main` | data/clients/<id>/brief.json → 執筆の案内（site_brief）・主題の候補（subjects） |
| 5. 記事の材料：狙う語 | サブキーワード | `kw.sub` | data/clients/<id>/brief.json → 執筆の案内（site_brief）・主題の候補（subjects） |
| 5. 記事の材料：狙う語 | 狙いたい地域 | `kw.regions` | sites/<id>.json の kw_seeds.regions（同じ語を持つ他社との地域の判断: sites.region_of）・data/clients/<id>/brief.json → 執筆の案内（site_brief） |
| 5. 記事の材料：狙う語 | 地域を付けて狙う語 | `kw.area_word` | data/clients/<id>/brief.json → 執筆の案内（site_brief）・主題の候補（subjects） |
| 5. 記事の材料：狙う語 | 狙わない語 | `kw.exclude` | data/clients/<id>/brief.json → 執筆の案内（site_brief）・主題の候補（subjects） |
| 5. 記事の材料：狙う語 | すでに上位に出ている語 | `kw.known` | data/clients/<id>/brief.json → 執筆の案内（site_brief）・主題の候補（subjects） |
| 5. 記事の材料：狙う語 | 業種・対象 | `kw_seeds.industries` | sites/<id>.json の kw_seeds → KWの計画（kw_plan・kw_discover・ai_kw_research） |
| 5. 記事の材料：狙う語 | 優先して狙う業種 | `kw_seeds.priority` | sites/<id>.json の kw_seeds.priority → KWの計画の枠と加点（kw_plan） |
| 5. 記事の材料：狙う語 | 検索の意図 | `kw_seeds.intents` | sites/<id>.json の kw_seeds → KWの計画（kw_plan・kw_discover） |
| 5. 記事の材料：狙う語 | 繁忙期と、その時期に増える相談 | `season.peaks` | sites/<id>.json の season.peaks → 季節の前出し（season.py。1年分の検索データがそろうまで） |
| 5-1. 一次情報（最重要） | 実績・数値 ① | `facts.1.claim` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ① の出典 | `facts.1.source` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ① の時点 | `facts.1.as_of` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ① の母数 | `facts.1.denominator` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ① の集計期間 | `facts.1.period` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | 実績・数値 ② | `facts.2.claim` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ② の出典 | `facts.2.source` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ② の時点 | `facts.2.as_of` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ② の母数 | `facts.2.denominator` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ② の集計期間 | `facts.2.period` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | 実績・数値 ③ | `facts.3.claim` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ③ の出典 | `facts.3.source` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ③ の時点 | `facts.3.as_of` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ③ の母数 | `facts.3.denominator` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | ③ の集計期間 | `facts.3.period` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-1. 一次情報（最重要） | 事例・体験 | `facts.note` | data/clients/<id>/facts.json → 記事の一次情報（facts.py。割合は母数と期間が無いと登録しない） |
| 5-2. 事例とお客様の声 | 事例 ①（どんな会社の、何を） | `case.1.summary` | brief.json の cases（掲載が「可」で本人の確認が「済」だけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | 事例 ① の結果 | `case.1.result` | brief.json の cases（掲載が「可」で本人の確認が「済」だけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | 事例 ① の掲載 | `case.1.publish` | brief.json の cases（掲載が「可」で本人の確認が「済」だけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | 事例 ① のご本人の確認 | `case.1.confirmed` | brief.json の cases（掲載が「可」で本人の確認が「済」だけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | 事例 ②（どんな会社の、何を） | `case.2.summary` | brief.json の cases（掲載が「可」で本人の確認が「済」だけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | 事例 ② の結果 | `case.2.result` | brief.json の cases（掲載が「可」で本人の確認が「済」だけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | 事例 ② の掲載 | `case.2.publish` | brief.json の cases（掲載が「可」で本人の確認が「済」だけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | 事例 ② のご本人の確認 | `case.2.confirmed` | brief.json の cases（掲載が「可」で本人の確認が「済」だけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | お客様の声 ① | `voice.1.text` | brief.json の voices（掲載が「可」で本人が書いた・確認したものだけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | お客様の声 ① の表示名 | `voice.1.name` | brief.json の voices（掲載が「可」で本人が書いた・確認したものだけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | お客様の声 ① の掲載 | `voice.1.publish` | brief.json の voices（掲載が「可」で本人が書いた・確認したものだけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | お客様の声 ① の書き手 | `voice.1.by` | brief.json の voices（掲載が「可」で本人が書いた・確認したものだけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | お客様の声 ② | `voice.2.text` | brief.json の voices（掲載が「可」で本人が書いた・確認したものだけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | お客様の声 ② の表示名 | `voice.2.name` | brief.json の voices（掲載が「可」で本人が書いた・確認したものだけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | お客様の声 ② の掲載 | `voice.2.publish` | brief.json の voices（掲載が「可」で本人が書いた・確認したものだけ）→ 執筆の案内 |
| 5-2. 事例とお客様の声 | お客様の声 ② の書き手 | `voice.2.by` | brief.json の voices（掲載が「可」で本人が書いた・確認したものだけ）→ 執筆の案内 |
| 5-3. 記事の書き手 | 著者名 | `author.name` | brief.json の author → 記事の著者（publish.client_credit の Person）・執筆の案内 |
| 5-3. 記事の書き手 | 肩書き | `author.title` | brief.json の author → 記事の著者（publish.client_credit の Person）・執筆の案内 |
| 5-3. 記事の書き手 | 保有資格・経歴 | `author.credential` | brief.json の author → 記事の著者（publish.client_credit の Person）・執筆の案内 |
| 5-4. 記事の監修者 | 監修者のお名前 | `supervisor.name` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | 役職 | `supervisor.title` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | 資格 | `supervisor.qualification` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | 登録番号 | `supervisor.registration` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | 経歴 | `supervisor.career` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | 監修する範囲 | `supervisor.scope` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | プロフィールページ | `supervisor.profile_url` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | 外部のプロフィール | `supervisor.same_as` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | 顔写真 | `supervisor.photo` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | 掲載の同意 | `supervisor.consent` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | 記事の確かめ方 | `supervisor.review` | company.json の supervisor → 記事の監修の表示と reviewedBy（publish.py）・brief.json |
| 5-4. 記事の監修者 | 確認のご連絡先 | `supervisor.contact` | private.json（公開しない）→ 監修の確認依頼（editorial_review）・準備状況 |
| 5-5. 書き方と表現のきまり | 自社の呼び方 | `tone.person` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（書き方のきまり） |
| 5-5. 書き方と表現のきまり | 文体 | `tone.style` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（書き方のきまり） |
| 5-5. 書き方と表現のきまり | 専門用語の扱い | `tone.level` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（書き方のきまり） |
| 5-5. 書き方と表現のきまり | 使いたくない言い回し | `tone.avoid` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（書き方のきまり） |
| 5-5. 書き方と表現のきまり | 使ってはいけない表現 | `ng_words` | sites/<id>.json の rules.ng_words → 含む記事の公開を止める（publish.py）・口コミの返信案（review_reply） |
| 5-5. 書き方と表現のきまり | 業種の表現の決まり | `tone.regulation` | sites/<id>.json の rules.regulation・brief.json → 執筆の案内・公開前の確認の勧め（review） |
| 5-6. すでにあるもの | 既存サイト | `asset.site` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（既存のページ・過去の施策） |
| 5-6. すでにあるもの | 既存の記事数 | `asset.articles` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（既存のページ・過去の施策） |
| 5-6. すでにあるもの | よく読まれている既存のページ | `asset.top_pages` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（既存のページ・過去の施策） |
| 5-6. すでにあるもの | 過去にうまくいかなかった施策 | `asset.failed` | data/clients/<id>/brief.json → 執筆の案内（site_brief）（既存のページ・過去の施策） |
| 5-6. すでにあるもの | 写真素材 | `asset.photos` | data/clients/<id>/brief.json → 執筆の案内（site_brief）・sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness） |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | YouTubeチャンネル | `channels.youtube` | sites/<id>.json の channels → 動画・SNS の投稿先（youtube_upload・post_social）・準備状況 |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | 動画を上げるか | `channels.video` | sites/<id>.json の channels → 動画・SNS の投稿先（youtube_upload・post_social）・準備状況 |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | Facebookページ | `channels.facebook` | sites/<id>.json の channels → 動画・SNS の投稿先（youtube_upload・post_social）・準備状況 |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | Instagram | `channels.instagram` | sites/<id>.json の channels → 動画・SNS の投稿先（youtube_upload・post_social）・準備状況 |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | Threads | `channels.threads` | sites/<id>.json の channels → 動画・SNS の投稿先（youtube_upload・post_social）・準備状況 |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | LinkedIn会社ページ | `channels.linkedin` | sites/<id>.json の channels → 動画・SNS の投稿先（youtube_upload・post_social）・準備状況 |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | X（旧Twitter） | `channels.x` | sites/<id>.json の channels → 動画・SNS の投稿先（youtube_upload・post_social）・準備状況 |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | SNS に付けるタグ | `channels.tags` | sites/<id>.json の x_tags → SNS の投稿のタグ（social_post・post_social） |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | 許可の手続きの担当者 | `channels.contact` | private.json（公開しない）→ 許可の手続きの連絡先 |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | 当社を管理者に追加済みか | `channels.admin_added` | sites/<id>.json の channels → 動画・SNS の投稿先（youtube_upload・post_social）・準備状況 |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | Googleビジネスプロフィール | `gbp.status` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（Googleビジネスプロフィール） |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | 当社をプロフィールの管理者に追加 | `gbp.invite` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（Googleビジネスプロフィール） |
| 6. 発信（動画・SNS・Googleビジネスプロフィール） | 地図に出す説明文 | `gbp.description` | sites/<id>.json の gbp.description → 地図の説明文（gbp.py --sync） |
| 7. サイトの改修 | 改修のご希望 | `renovate.want` | sites/<id>.json の onboarding（済/未などの印だけ）→ 準備状況（intake_readiness）（サイト改修） |
| 7. サイトの改修 | 確認なしで反映してよい範囲 | `renovate_auto` | sites/<id>.json の renovate_auto → 確認なしで反映してよい直し（site_renovate.auto_ok） |
| 7. サイトの改修 | 触ってはいけないページ | `renovate.protect` | sites/<id>.json の renovate_protect → 改修の検査で止める（site_renovate） |
| 7. サイトの改修 | 直したいところ | `renovate.wish` | private.json → 導入後の改修の提案の控え |
| 8. レポートと運用のきまり | レポートの送付先 | `report_to` | private.json（公開しない）→ レポートの送付先・準備状況 |
| 8. レポートと運用のきまり | 月次レポートの発行者の表示 | `report_issuer` | sites/<id>.json → 月次レポートの名義（monthly_report.issuer） |
| 8. レポートと運用のきまり | 公開前の確認 | `review_before_publish` | sites/<id>.json の rules → 確認の記録が付くまで配信しない（publish.py） |
| 8. レポートと運用のきまり | 月の公開本数 | `monthly_cap` | sites/<id>.json の rules.monthly_cap → 月の上限（daily_audit） |
| 8. レポートと運用のきまり | 多言語の要約ページ | `languages` | sites/<id>.json → 多言語の要約ページ（i18n.py・publish.py） |
| 8. レポートと運用のきまり | その他の申し送り | `note` | private.json（公開しない）→ 社内の申し送り |
| 9. 外部との接点（被リンクの起点） | 加盟している団体・協会 | `link.orgs` | brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手） |
| 9. 外部との接点（被リンクの起点） | 掲載中のポータル・媒体 | `link.portals` | brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手） |
| 9. 外部との接点（被リンクの起点） | 取引先・パートナー | `link.partners` | brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手） |
| 9. 外部との接点（被リンクの起点） | 受賞歴・認定・表彰 | `link.awards` | brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手） |
| 9. 外部との接点（被リンクの起点） | 取材・メディア掲載の実績 | `link.press` | brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手） |
| 9. 外部との接点（被リンクの起点） | プレスリリースの配信 | `link.release` | brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手） |
| 9. 外部との接点（被リンクの起点） | 自治体・公的機関との関わり | `link.gov` | brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手） |
| 9. 外部との接点（被リンクの起点） | 代表者・担当者の発信 | `link.person` | brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手） |
| 9. 外部との接点（被リンクの起点） | 寄稿できそうな媒体 | `link.writable` | brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手） |
| 9. 外部との接点（被リンクの起点） | すでに把握している被リンク | `link.known` | brief.json の backlink → 執筆の案内（記事で触れると自然にリンクが生まれる相手） |
| 10. 店舗の基本【飲食店】 | 業態 | `shop.type` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 10. 店舗の基本【飲食店】 | 席数 | `shop.seats` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 10. 店舗の基本【飲食店】 | 客単価 | `shop.budget` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 10. 店舗の基本【飲食店】 | 営業時間・定休日 | `shop.hours` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 10. 店舗の基本【飲食店】 | 最寄駅と徒歩分数 | `shop.access` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 10. 店舗の基本【飲食店】 | 駐車場 | `shop.parking` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 10. 店舗の基本【飲食店】 | 貸切・団体の可否 | `shop.capacity` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 10. 店舗の基本【飲食店】 | 喫煙・禁煙 | `shop.smoking` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 10. 店舗の基本【飲食店】 | お子様連れ対応 | `shop.kids` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 11. メニューと食材【飲食店】 | 看板メニュー | `menu.signature` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 11. メニューと食材【飲食店】 | 食材のこだわり・産地 | `menu.ingredient` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 11. メニューと食材【飲食店】 | コース・宴会プラン | `menu.course` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 11. メニューと食材【飲食店】 | ドリンクの特徴 | `menu.drink` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 11. メニューと食材【飲食店】 | アレルギー・食事制限への対応 | `menu.allergy` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 11. メニューと食材【飲食店】 | テイクアウト・デリバリー | `menu.takeout` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 12. 集客と予約【飲食店】 | 予約の受付方法 | `attract.reserve` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 12. 集客と予約【飲食店】 | いまの集客経路 | `attract.now` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 12. 集客と予約【飲食店】 | 来てほしいお客様 | `attract.target` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 12. 集客と予約【飲食店】 | 埋めたい時間帯・曜日 | `attract.want` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 12. 集客と予約【飲食店】 | 繁忙期・閑散期 | `attract.season` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 12. 集客と予約【飲食店】 | 季節の催し | `attract.event` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 13. 表示のきまり【飲食店】 | 使ってよい表現 | `food.claim` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 13. 表示のきまり【飲食店】 | 使えない表現 | `food.ng` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 13. 表示のきまり【飲食店】 | 資格・認証 | `food.cert` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 14. 飲食店の外部掲載【飲食店】 | 登録中のグルメサイト | `flink.gourmet` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 14. 飲食店の外部掲載【飲食店】 | Googleビジネスプロフィールの状況 | `flink.map` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 14. 飲食店の外部掲載【飲食店】 | SNSアカウント | `flink.sns` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 14. 飲食店の外部掲載【飲食店】 | 地域のポータル・観光協会 | `flink.local` | brief.json の industry_detail → 執筆の案内（業種の詳細） |
| 14. 飲食店の外部掲載【飲食店】 | グルメ媒体の取材 | `flink.media` | brief.json の industry_detail → 執筆の案内（業種の詳細） |

## 状態の意味

| 状態 | 意味 |
|:--|:--|
| ok | 動く。鍵の要る機能は「別経路で受領済み」＝鍵が管制塔に登録されている（Secret・.env・手元の鍵ファイル。中身は見ない） |
| 要対応 | お客様にお願いすること（シートの欄・権限の追加・鍵の送付） |
| 受領待ち | 当社の作業（シートの「別経路でお送りする鍵」が「送付済み」で、まだ登録していない鍵・許可の手続き） |
| 任意 | 無くても動くが効きが落ちる（通知には載せない） |
| 対象外 | その社では使わない |
