## 3. セットアップ手順

### 3.0 クライアントの導入（受託運用の入口）

**ヒアリングシートを1枚埋めれば、運用に必要なものが全部そろう。**

```bash
python scripts/client_intake.py --sheet                  # 汎用シートを作る
python scripts/client_intake.py --sheet restaurant       # 飲食店向け（業種別の項目つき）
```

**記入済みのシートは `intake/` に置くだけでよい。** ファイル名を指定し損ねたり、
不備の確認を飛ばしたりするのを防ぐため、置き場を決めて機械に拾わせる。

```bash
python scripts/intake_watch.py            # 何が起きるかを見るだけ
python scripts/intake_watch.py --apply    # 登録まで行う
```

| 結果 | 行き先 |
|:--|:--|
| 登録できた | `intake/done/` |
| 不備があった | `intake/todo/` と、同じ名前の `.不備.txt`（直す箇所を書く） |

**シートそのものはコミットされない**（`.gitignore` 済み）。会社名・住所・電話・
担当者のメールが入るうえ、このリポジトリは public のため。**登録した内容は非公開のリポジトリ（`private/`）にだけ書いて
commit・push し**（`client_intake.save_private`）、公開側には `sites/<公開の id>.json` の印だけを書く（2.1 節）。
社の id はシートに書かれた id や社名から作らず、推測できない公開の id にする（`client_intake.assign_id`）。
手元に `private/` が無ければ登録しない（`python scripts/private_store.py --fetch` で取得してから）。
**20社を超えるシートは受け付けずに止める。**

1枚ずつ指定したいときは従来どおり `client_intake.py <記入済み.xlsx> --apply` も使える。

**自社の一次データも同じ置き場で公開する**（`python scripts/data_intake.py --sheet` で
`intake/データ記入シート.xlsx` を作る → 埋めて intake/ に置く → `intake_watch.py --apply`）。
`site/data/<slug>/` に表・棒グラフ・引用用の一文・Dataset 構造化データ・CSV のページができ、
llms.txt と sitemap に載り、同じカテゴリの記事末に「自社の一次データ」枠が出て、引用用の一文は
一次情報として登録される（記事から使われる）。**AIが根拠に選ぶのは「そこにしか無い数字」**で、
これが引用を取る最大の手。母数10未満・期間なし・個社名入りは公開しない。

**材料の質問シートも同じ置き場で回す**（2026-10-21 運用者「採点で材料が足りないと出た記事の質問シートを、社ごとに機械で作る」）。
`python scripts/intake_watch.py --apply` の最後に、材料の依頼（`material_requests.json`）が残る社ごとの質問シートをデスクトップに作る
（`scripts/material_sheet.py --make`。依頼の記事の質問＋事例カード・失敗の件数・判断の根拠・費用の実例（お客様の社だけ）・
確認の一覧・担当者の経歴・お客様の声）。答えを書いて intake/ に置くと、次の回に一次情報・体験として登録する。
**答えに無い数字・既存の記録と食い違う答え・掲載不可・お客様の声は登録せず**、`<シート名>.保留.txt` に理由を残す。
食い違ったときは、先に受け取ったシート（既存の記録）を基準にする（運用者「数字は先に渡したシートを基準に」）。
自社サイトでやったことの前後28日は `material_sheet.py --measure <site> <URL> <日付> --what "〜した"` で一次情報の文にする。
次に書く題は、材料のある題を先に選ぶ（お客様の社はすべての題、自社は主力の語に当たる題。`hub_client._with_material`）。

**実績・お客様の声も同じ置き場で登録する**（`python scripts/jisseki_intake.py --sheet` で
`intake/実績記入シート.xlsx` を作る → 埋めて intake/ に置く → `intake_watch.py --apply`）。
経理BPOの効果・継続率は一次情報（記事に使われる）に、お客様の声は `data/voices.json` と
運営者情報・LP（AI集客ラボ）に載る。**数字は本人が入れたものだけ。機械は作らない。**
割合は母数10件以上・期間つきのときだけで、未満は実数に落とす（`add_fact` と同じ条件）。
掲載可否が「可」でない声は載せない。「可」にできるのは本人が書いたか、本人が内容を確認して許可した声だけ
（事業者が作った感想を「お客様の声」として表示するのはステルスマーケティング規制の違反）。
会社名を出さない場合は表示名（例: 大阪市の歯科医院）。

`--apply` で作られるもの:

| 生成物 | 置き場 | 中身 |
|:--|:--|:--|
| `sites/<公開の id>.json` | public | 社が特定できない印だけ（公開の id・`"client": true`・1日の本数） |
| `clients/<id>/site_private.json` | 非公開 | サイト設定の全部（社名・ドメイン・納品方式・配信先・カテゴリ・主力商材・カテゴリ配分・守備範囲・CTA・計測・禁止語）と公開の id |
| `clients/<id>/company.json` | 非公開 | 会社の正規表記（著者情報・構造化データ・レポートの宛名） |
| `clients/<id>/facts.json` | 非公開 | その会社にしか出せない一次情報 |
| `clients/<id>/brief.json` | 非公開 | 記事を書くための材料（売り物・読者の困りごと・FAQ・著者・文体・狙う語・外部接点） |
| `clients/<id>/kw.md` | 非公開 | KW計画の雛形 |
| `clients/<id>/private.json` | 非公開 | 担当者の連絡先・接続先（パスワードは入れない） |

**記事の自動化に効く部分**: シートの回答は `site_brief.py` が執筆時に読み込む。売っているもの・読者の困りごと・よく聞かれる質問（そのままFAQになる）・著者情報・文体・メイン/サブキーワード・外部との接点まで渡るため、「その会社にしか書けない記事」になる。**書かれていないことは書かせない**（憶測で補うと事実と違う記事が公開される）。

**主題キーワードの生成**: メインKW × サブKW × 意図 × 業種 を掛け合わせて主題候補を作る（`client_intake.subjects()`）。同じ語の重なりと「狙わない語」は除外する。候補はそのまま書かず、`kw_guard`（食い合い）と `kw_intent`（開く理由）を必ず通す。

**先に進ませない条件（不備として止める）**:
- 主力商材・主力カテゴリが空 → 表示は増えても相談につながらない記事が量産される
- 一次情報が1件も無い → どのサイトでも書ける記事になり、AI検索に引用されない
- 既存サイトとカテゴリ・ドメインが重複 → 記事がどちらのものか決まらない
- 主力カテゴリの配分が35%未満 → 警告（40〜50%を推奨）

**受託運用での分離**: クライアントの記事に運用会社の実績を書くと事実と違う記事になる。お客様の社では、`facts.py` は非公開の置き場の `clients/<id>/facts.json` だけを使い、自社の一次情報を混ぜない（読めなければ一次情報は空）。

**動画とSNSは先方のアカウントにだけ上げる**（当社のアカウントに落とさない。門が確かめる）:

| 媒体 | つなぎ方（先方のアカウントで1回だけ許可） | CI の鍵 |
|:--|:--|:--|
| YouTube | `python scripts/youtube_upload.py --auth --site <id>` → `youtube-token-<id>.json` | Secret `YOUTUBE_TOKENS_JSON`（`{"<id>": {...}}`。許可した時点で自動で登録される） |
| Facebook・Instagram・Threads・LinkedIn | `python scripts/social_connect.py --site <id> --facebook` など | Secret `SOCIAL_TOKENS_JSON` の `<id>`（つないだ時点で自動で登録される） |

つなぐまで、その社の記事は動画を作らず、SNS にも投稿しない。動画の名乗りと締めは `sites/<id>.json` の社名とドメインになる。

JSONを直接書く場合は `client_add.py`（既存クライアントの設定変更など）。

**一次情報の追加**: `scripts/add_fact.py` で登録する。JSONを手で書かない。

```bash
python scripts/add_fact.py --pending              # 何を入れれば記事が書けるか
python scripts/add_fact.py --template saitaku     # 記入用の雛形
python scripts/add_fact.py --check <file.json>    # 条件を満たすか検査
python scripts/add_fact.py --add <file.json>      # 通れば登録
```

**割合を書くなら、母数と集計期間を本文に含める。** 「採択率90%」だけでは、何社中何社か・いつからいつまでかが分からず、優良誤認になる（景品表示法・根拠の明示）。登録の時点で機械が止める。母数が10件未満なら割合では書かせず、実数で書かせる。

| 止める書き方 | 通る書き方 |
|:--|:--|
| 当社の採択率は90%です | 2025年4月〜2026年3月に支援した42社のうち38社が採択されました（採択率90.5%） |
| 多くの企業を支援してきました | 2026年9月までに42社の申請を支援しました |


### 3.0.1 納品方式（クライアントごとに選ぶ）

| 形式 | 配信先 | 品質ゲートの効き方 |
|:--|:--|:--|
| `self-static` | 本リポジトリの静的サイト | build.py がビルド対象から除外。**ファイルが存在しない** |
| `external-md` / `external-html` / `nextjs-json` | 別リポジトリの静的サイト | publish.py が85点未満を配信しない |
| `wordpress` | WordPress（本体の REST API・投稿者の権限の鍵だけ） | publish.py が85点未満を送らない（先方には何も置かない。下記） |
| `ftp` | Gitを使わないレンタルサーバー（FTPS既定 / FTP / SFTP） | publish.py が85点未満を上げない（`deliver_files.py`） |
| `zip` | 先方が自分で上げる（`deliveries/<id>/` にZIP） | 同上。公開の照合（publish_gap）からは外す |

**どの形式でも、記事・書き直しの再配信・動画・SNSはすべて管制塔のCIから出る**（先方にGitも作業も要らない）。
接続情報は社ごとの Secret を並べず、全社分を1つのJSONで持つ: `FTP_CREDENTIALS_JSON`
（`{"<id>": {"protocol":"ftps","host":"…","user":"…","password":"…","root":"/public_html"}}`、手元は `ftp-credentials.json`）・
`WP_CREDENTIALS_JSON`（`{"<id>": {"user":"…","password":"<アプリケーションパスワード>"}}`）。
`ftp`/`zip` の見た目は `data/clients/<id>/template.html` があればそれ、無ければ `templates/external_article.html`。
配信した記事の一覧（関連記事に使う）は `data/clients/<id>/delivered.json`。

**サイトの構成（ナビ・トップ・固定ページ・CSS・メニュー・配色）も、どの形式でも管制塔から変える**（先方は何もしない）:

```bash
python scripts/site_change.py --site <id> --pull       # 先方のサイトを .publish-work/<id>-site/ へ取る（控えを残す）
python scripts/site_change.py --site <id> --diff       # 変える内容を見る
python scripts/site_change.py --site <id> --push       # 変えた分だけ反映（先方が取った後に変えたものがあれば止まる）
python scripts/site_change.py --site <id> --rollback   # 直前の反映の前へ戻す
```

**指示の一文で改修する**（Claude が作業場所の中だけを直し、通してよいかは機械が決める。中身は `site_renovate.py`）:

```bash
python scripts/site_change.py --site <id> --ask "トップの施工事例の見出しを…"   # 取る→直す→検査→変更前後の写真→止まる
python scripts/site_renovate.py --site <id> --apply      # 写真（.publish-work/<id>-site/_preview/）と差分を見て反映
python scripts/site_renovate.py --site <id> --discard    # 捨てる（--ask … --yes なら検査が通りしだい反映）
```

検査（タグの開閉・JSON-LD・内部リンク・速度の方針・表現・許可していない script・鍵と個人情報・20ファイル／削除5%まで）に
1つでも外れたら反映しない。反映後にトップと変えたページの200・ナビ・フッター・問い合わせの導線を確かめ、外れたら自動で戻す
（台帳 `automation/logs/renovate.jsonl`・週次の findings が要対応で知らせる）。確認なしで反映するのは、
`sites/<id>.json` の `renovate_auto`（`"css"`・`"text"`）に書いた種類だけの小さな直し（既定は無効）。

| 形式 | 変えられる範囲 |
|:--|:--|
| Git の社 | 全部（配信先リポジトリへ push） |
| `ftp` | 全部（変えたファイルだけ上げる。WordPress 本体・アップロード画像・5MB超は取らない） |
| `wordpress` | FTP の接続情報がある社だけ ftp と同じ（テーマも含む）。無い社は変えられない（預かる WordPress の鍵は投稿者の権限だけ） |
| `zip` | ZIP と手順書を先方へメール（先方の作業が残るので、登録時に ftp を勧める警告が出る） |

作業場所の git は必ずその場所の `.git` を名指しする（壊れた `.git` から親の管制塔リポジトリへさかのぼり、
本体へ4,821件を誤コミットした。門 `test_site_change_stays_in_its_own_repo` が止める）。

**WordPress のお客様（2026-10-24 運用者「PHP では作らない一番セキュリティが高いもの」）**

PHP のプラグイン（ss-quality-gate.php）は廃止し、公開サイトでの配布もやめた。先方のサーバーには何も置かない。

| 形 | いつ | 預かるもの |
|:--|:--|:--|
| ① サブドメインの静的なページ（**標準**） | 同じドメインが要らない社。例: column.御社.jp に当社が作るページで出す | DNS に1行足してもらうだけ。WordPress の鍵は預からない |
| ② WordPress へ直接投稿（`wordpress`） | 同じドメインがどうしても要る社だけ | 記事の投稿の専用ユーザー（**投稿者**の権限）のアプリケーションパスワードだけ |

- ② の鍵が管理者・編集者の権限なら、投稿せずに止める（`wp_bridge.role_problems`。漏れたときにサイト全体へ届くため）。週次の `wp_bridge.py --check` が権限を確かめる
- 公開してよいかは publish.py の門（`gate_ok`・配信の前の検査）が決める。先方の管理画面で人が公開する記事は対象外
- ② では作らないもの（投稿者の権限では固定ページ・<script>・直下のファイルを扱えない）: 構造化データ・計測・業種のまとめ・用語集・まとめのページ・
  多言語のページ・llms.txt・301（下書きに戻して先方に足してもらう）・IndexNow と Bing の確認ファイル（先方に置いてもらう）。表は `data/capabilities.json`
- サイトの構成の変更・表示速度の直しは、FTP の接続情報がある社だけ（ftp と同じ）
- 計測のスクリプトはどの方式でも `automation/measure/ss-measure.js`（廃止したプラグインから取り出した）

### 3.1 ディレクトリ構成

```
├── CLAUDE.md               ← 本ファイル（パイプライン定義）
├── PROJECT.md              ← プロジェクト設定（要カスタマイズ）
├── .env                    ← 認証情報（.gitignore対象）
├── articles/               ← 記事マークダウン（原稿マスター）
├── site/                   ← 公開ルート（Cloudflare Pagesがこのフォルダを配信）
│   ├── index.html          ← トップページ
│   ├── lp/index.html       ← リード獲得LP（記事CTAの誘導先。CV導線の中核）
│   ├── {category}/index.html ← カテゴリ一覧（aio / seo / meo / ai-marketing）
│   ├── {category}/{slug}/index.html ← 記事HTML（ビルドで生成）
│   ├── css/style.css       ← 共通スタイル
│   ├── images/             ← 公開画像（アイキャッチ・図解）
│   ├── robots.txt          ← AIクローラー許可設定
│   ├── llms.txt            ← AIクローラー向けサイト案内
│   └── sitemap.xml         ← ビルドで自動生成
├── templates/
│   └── article.html        ← 記事HTMLテンプレート（メタ+JSON-LD Schema込み）
├── scripts/
│   └── build.py            ← Markdown→HTML変換+sitemap生成ビルドスクリプト
├── automation/
│   ├── images/             ← 生成画像（作業用）
│   ├── logs/               ← 実行ログ
│   └── design/             ← デザインルール
├── data/
│   ├── x_trends/           ← X API収集データ
│   ├── youtube_transcripts/ ← YouTube文字起こし
│   └── ai_citations/       ← AI引用スポットチェック結果
└── kpi_feedback.md          ← KPIフィードバック（自動更新）
```

### 3.2 スプレッドシート準備

Google Sheetsで11タブを用意する（列構成の詳細は第9章）:
KW戦略 / トピッククラスター / X一次情報 / YouTube一次情報 / ダッシュボード / 記事作成ログ / KPIレポート / AIO計測 / 内部リンク管理 / リライトログ / エラーログ

### 3.3 静的サイト設定（Cloudflare Pages）

1. Gitリポジトリ作成（本プロジェクト）→ Cloudflare Pages プロジェクトに接続（ビルド出力ディレクトリ: `site/`）
2. `git push` → Cloudflare Pages が自動デプロイ（これが「公開」操作）
3. 記事URL: `/{カテゴリスラッグ}/{記事スラッグ}/`（カテゴリは PROJECT.md 参照）
4. `templates/article.html` に以下を組み込む:
   - title / meta description / canonical / OGP
   - JSON-LD: BlogPosting（author=Person・datePublished・**dateModified**）+ FAQPage + BreadcrumbList（手順系はHowTo追加）
   - 目次（TOC）: `scripts/build.py` がH2/H3から自動生成
   - CTAボタン・「この記事でわかること」ボックス・定義ブロックの共通コンポーネント
5. dateModified はビルド時にJSON-LDとページ上の両方に出力（AI検索は鮮度重視のため必須）
6. `scripts/build.py` の責務: articles/*.md → site/{cat}/{slug}/index.html 変換、sitemap.xml 再生成、llms.txt 追記検証

### 3.4 AIO基盤設定（初回のみ・最重要）

**1. robots.txt: AIクローラーの許可確認**

以下がブロックされていないことを確認（ブロックされているとSEO順位が高くてもAI検索に引用されない）:

```
User-agent: GPTBot
Allow: /

User-agent: OAI-SearchBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: Bingbot
Allow: /
```

注意: Google AI Overview / AIモードは通常のGooglebotのクロール結果を使用する。**Googlebotを絶対にブロックしないこと**。Google-Extended はGemini学習用の制御であり、AI Overview表示可否とは別物。

robots.txt は `site/robots.txt` として管理する（デプロイでそのまま公開される）。

**2. llms.txt の設置**

`site/llms.txt` としてMarkdown形式で設置（サイトルートで公開される）:

```markdown
# サイト名
> サイトの概要を1-2文で記述（誰向けの、何のメディアか）

## 運営者情報
- 運営会社・著者の実績・専門性を記述（E-E-A-Tの明示）

## 主要コンテンツ
- [記事タイトル](URL): 記事の1行説明
```

Phase 6 が新規記事公開のたびに自動追記する。

**3. IndexNowキー設置（オプション）**: `site/{INDEXNOW_KEY}.txt` としてキーファイル設置。

**4. GA4: AI参照元の計測設定**

以下のリファラーを「AI検索流入」として分類:

```
chatgpt.com | chat.openai.com | perplexity.ai | gemini.google.com | copilot.microsoft.com | claude.ai
```

**5. GSC: 生成AIパフォーマンスレポートの確認**

AI Overview・AIモードのインプレッションとページ別引用状況が確認できることを確認。現時点ではインプレッション中心のデータのため、GA4のAI参照元計測と必ず併用する。

---

