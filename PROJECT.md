# PROJECT.md — プロジェクト固有設定

> パイプライン（[CLAUDE.md](CLAUDE.md)）が参照するこのメディア固有の設定。
> 残りの `TODO:` を埋めれば運用開始可能。

## サイト基本情報

| 項目 | 値 |
|:--|:--|
| メディア名 | AI集客ラボ（仮称 — 変更する場合は全ファイル一括置換） |
| ドメイン | **未取得**（仮値: `https://ai.7senses.co.jp` — 取得後に全ファイル一括置換） |
| サイト形式 | **静的HTML**（WordPress不使用） |
| ホスティング | **Cloudflare Pages**（Gitリポジトリ連携で自動デプロイ） |
| メディアの目的 | 自社のAIO・SEO・MEO集客支援サービスへのリード獲得（記事→LP→CV導線） |
| 運営会社 | セブンセンシズ株式会社（大阪市東成区・[7senses.co.jp](https://corp.7senses.co.jp/)） |
| 既存事業 | MEO/ローカルSEO店舗集客支援「G-ran」、造園・環境サービス等 |
| CVポイント | ①無料相談・問い合わせ（`/lp/#form`・`/contact/`） ②資料ダウンロード（`/download/`） |
| CV導線 | 記事内CTA 2箇所以上 → `/lp/`（リード獲得LP）→ フォーム |

## E-E-A-T 著者情報

| 項目 | 値 |
|:--|:--|
| 著者名 | セブンセンシズ編集部 |
| 監修者 | 代表取締役 原口 優（写真: `site/images/company/company_img2.jpg`） |
| 肩書き | AI集客・MEO/SEO運用の実務チーム |
| 会社実績 | 2020年3月10日設立 / 資本金500万円 / MEO対策「G-ran」＝**通算3,200店舗以上の運営実績**（2026-07 ご本人提供・サイト反映済み） |
| MEOスタンダード | 月額3万円: 口コミ返信代行 / NAP統一 / 最新情報投稿 月10〜14回 / 月次レポート / 基本おまかせ（税込・税別と初期費用はTODO確認） |
| おまかせパック特典 | MEOスタンダード（月額3万円相当）が無料付帯 |
| プロフィールURL | `https://ai.7senses.co.jp/about/`（会社概要・代表メッセージ掲載済み） |

## ターゲット業種（優先順）

| 優先 | 業種 | 刺さる訴求 | 主力施策 |
|:--|:--|:--|:--|
| 1 | BtoB・SaaS/IT | 商談前にAI・検索で比較される。「AIに聞いたら候補に挙がる」状態づくり | 記事SEO・AIO/LLMO・導入事例 |
| 2 | 専門サービス業（士業・コンサル・医療/クリニック） | 「地域×専門分野」で探され信頼で選ばれる。専門家の第一想起 | 監修記事・E-E-A-T・MEO・FAQ |
| 3 | 不動産・住宅・リフォーム | 高単価・長期検討。比較段階の情報収集で接点を作る | 事例記事・MEO・資料請求導線 |
| 補助 | 店舗ビジネス全般（飲食・美容等） | G-ranの実績領域 | MEO中心 |

※ 医療系はmedical広告ガイドライン（誇大表現・体験談制限等）に配慮した表現で制作すること。

## ターゲットペルソナ（Phase 5 ペルソナエージェント用）

- 上記3業種の経営者・マーケティング責任者（従業員5〜100名）、ITリテラシー中程度
- 主な悩み: 「広告費が上がり続けリード単価が悪化」「商談前にAIで比較され、土俵に乗れていない気がする」「専門性はあるのに検索・マップで埋もれている」
- 検索行動: 「AIO 対策」「LLMO とは」「SaaS リード獲得 方法」「クリニック MEO」「工務店 集客」等を検索。ChatGPT/Perplexityでも質問する層

## 業種別KWクラスター案（Phase 1 の攻め順の初期仮説。Ahrefs接続後に検証）

- **BtoB・SaaS**: 「SaaS リード獲得」「BtoB コンテンツマーケティング」「導入事例 書き方」「比較サイト 対策」
- **士業・コンサル**: 「税理士 集客」「行政書士 ホームページ 集客」「コンサル 見込み客 獲得」
- **医療・クリニック**: 「クリニック MEO」「病院 口コミ 返信」「クリニック ホームページ 集患」（広告規制配慮）
- **不動産・住宅**: 「工務店 集客」「リフォーム会社 集客」「不動産 ポータル 依存 脱却」「住宅会社 SEO」

## 記事カテゴリ（静的サイトのディレクトリ構成に対応）

| カテゴリ名 | スラッグ | カテゴリカラー |
|:--|:--|:--|
| AIO・LLMO運用（AI検索・AIチャット最適化） | `aio` | 朱 `#d9481c` |
| SEO運用 | `seo` | 藍 `#2b4c8c` |
| MEO運用（マップ検索最適化） | `meo` | 深緑 `#2e6e4e` |
| AI集客・活用全般 | `ai-marketing` | 金茶 `#a67a2d` |

※ LLMO（ChatGPT/Perplexity/Gemini等のAIチャット対策）は `aio` カテゴリで扱う。記事テーマとしても積極的に採用する（CLAUDE.md 第0章の用語定義参照）。

記事URL形式: `https://ai.7senses.co.jp/{カテゴリスラッグ}/{記事スラッグ}/`

## CTA設定

| CTA | 文言 | リンク先 |
|:--|:--|:--|
| CTA 1（無料相談） | TODO:（例: AI集客の無料相談を予約する） | `https://ai.7senses.co.jp/contact/` |
| CTA 2（資料DL） | TODO:（例: AIO対策チェックリストを無料ダウンロード） | `https://ai.7senses.co.jp/download/` |

## 競合サイト（3C分析用・Phase 1で自動発見後に確定）

1. TODO:（Ahrefs `site-explorer-organic-competitors` で自動発見）
2. TODO:
3. TODO:

## データ管理

| 項目 | 値 |
|:--|:--|
| スプレッドシートID | TODO:（[spreadsheet_template.xlsx](spreadsheet_template.xlsx) をGoogle Sheetsにインポート後、IDを記入） |
| GA4プロパティID | .env の GA4_PROPERTY_ID（サイト公開後に設定） |
| GSCサイトURL | .env の GSC_SITE_URL（ドメイン取得後に設定） |

## 運用パラメータ

| 項目 | 値 | 備考 |
|:--|:--|:--|
| 品質スコア閾値 | 114 / 120（95%） | 厳しい場合は108（90%）に調整可。推奨95% |
| 記事公開ペース | 毎日2本（5:00 / 14:00 JST） | CLAUDE.md 第5章 |
| Phase 3 ユーザー確認 | 有効 | 自動実行モードにする場合は「スキップ」に変更 |
| Phase 6 公開承認 | ビルド→ユーザー確認後にデプロイ | 自動実行モードは114点以上で自動デプロイ |
| 年号表記 | 2026年 | 運用年に合わせて更新 |

## 画像スタイル

- ブランドカラー: TODO:
- スタイル: フラットイラスト（CLAUDE.md 第6章 画像ルール準拠）
- 人物イラスト: 日本人素材をデフォルト使用

## 月次コンサルティングレポート（毎月1日自動発行）

- 生成: `python scripts/monthly_report.py`（実データ） / `--demo`（サンプル） / `--email`（Resendで送付）
- 出力: `reports/YYYY-MM/report.pdf`（GA4+GSC+スプレッドシート → 6ヶ月トレンド・前月比・クエリ別・LPヒートマップ・改善対比表・翌月プラン）
- ヒートマップのデータ源: LP/トップに実装済みの `section_view_*` / `area_reach` GA4イベント
- **毎月1日 9:00 の自動実行**（Windowsタスクスケジューラ登録コマンド — 管理者PowerShellで1回実行）:
  ```
  schtasks /Create /TN "AI集客ラボ月次レポート" /SC MONTHLY /D 1 /ST 09:00 ^
    /TR "python \"C:\Users\user\Desktop\システム開発\SSオウンドメディア（AIO）\scripts\monthly_report.py\" --email"
  ```
- 実データ化の前提: GA4/GSC/Sheetsにサービスアカウント閲覧権限 + `.env` の GA4_PROPERTY_ID / GSC_SITE_URL / SPREADSHEET_ID + `pip install google-analytics-data google-api-python-client google-auth`

## セットアップ進捗チェックリスト

- [x] プロジェクト初期構築（ディレクトリ・CLAUDE.md・PROJECT.md）
- [x] Ahrefs MCP 設定ファイル（.mcp.json — APIキー記入は未）
- [x] スプレッドシート雛形（spreadsheet_template.xlsx）
- [x] 静的サイト本体（トップ・カテゴリ4・about・contact・download・リード獲得LP）
- [x] 記事テンプレート（templates/article.html）+ ビルドスクリプト（scripts/build.py）— サンプル記事でビルド検証済み
- [ ] ドメイン取得 → 全ファイルの `ai.7senses.co.jp` を一括置換 + `scripts/build.py` の SITE_URL 更新
- [ ] Cloudflare Pages プロジェクト作成+Gitリポジトリ連携（ビルド出力: `site/`）
- [x] フォーム送信の実装（`functions/api/lead.js` — 3フォーム共通、ハニーポット+バリデーション付き）
- [ ] メール送信の有効化: [Resend](https://resend.com) でアカウント作成+送信ドメイン認証 → Cloudflare Pages の環境変数に `RESEND_API_KEY` / `LEAD_TO_EMAIL`（通知先） / `LEAD_FROM_EMAIL`（認証済み送信元）を設定
- [ ] ニュースレターの有効化: Resendで Audience（購読者リスト）を作成 → `RESEND_AUDIENCE_ID` を Cloudflare Pages（購読API用）と GitHub Secrets（週刊配信用）の両方に設定。ローカルから配信する場合は .env にも追記
- [ ] LPの実績数値（支援社数・継続率等）を実データで差し替え
- [ ] サービス紹介動画・写真素材の制作 → LPのプレースホルダー差し替え
- [ ] spreadsheet_template.xlsx をGoogle Sheetsにインポート → IDを本ファイルに記入
- [ ] .env に全認証情報を設定（X / YouTube / Sheets / Indexing / 画像生成）
- [ ] GA4作成+AI参照元セグメント設定
- [ ] GSC登録+生成AIパフォーマンスレポート確認
- [ ] 本ファイルの残TODO（著者情報・CTA文言・ブランドカラー）を記入
