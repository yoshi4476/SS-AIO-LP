# PROJECT.md — プロジェクト固有設定

> パイプライン（[CLAUDE.md](CLAUDE.md)）が参照するこのメディア固有の設定。
> 残りの `TODO:` を埋めれば運用開始可能。

## サイト基本情報

| 項目 | 値 |
|:--|:--|
| メディア名 | AI集客ラボ（仮称 — 変更する場合は全ファイル一括置換） |
| ドメイン | **未取得**（仮値: `https://example.com` — 取得後に全ファイル一括置換） |
| サイト形式 | **静的HTML**（WordPress不使用） |
| ホスティング | **Cloudflare Pages**（Gitリポジトリ連携で自動デプロイ） |
| メディアの目的 | 自社のAIO・SEO・MEO集客支援サービスへのリード獲得（記事→LP→CV導線） |
| 運営会社 | セブンセンシズ株式会社（大阪市東成区・[7senses.co.jp](https://www.7senses.co.jp/)） |
| 既存事業 | MEO/ローカルSEO店舗集客支援「G-ran」、造園・環境サービス等 |
| CVポイント | ①無料相談・問い合わせ（`/lp/#form`・`/contact/`） ②資料ダウンロード（`/download/`） |
| CV導線 | 記事内CTA 2箇所以上 → `/lp/`（リード獲得LP）→ フォーム |

## E-E-A-T 著者情報

| 項目 | 値 |
|:--|:--|
| 著者名 | セブンセンシズ編集部（仮 — 個人著者を立てる場合は変更。`scripts/build.py` の AUTHOR_* も更新） |
| 肩書き | AI集客・MEO/SEO運用の実務チーム |
| 実績・専門性 | TODO:（G-ran支援社数・運用年数など実数値を確認して記入 — E-E-A-T強化に必須） |
| プロフィールURL | `https://example.com/about/`（作成済み） |

## ターゲットペルソナ（Phase 5 ペルソナエージェント用）

- 中小企業の経営者・事業責任者（従業員5-100名）、ITリテラシー中程度
- 主な悩み: 「検索やAI検索からの集客ができていない」「SEO/MEOを何から始めればいいか分からない」「AI時代に自社の集客手法が通用するか不安」
- 検索行動: 「AIO 対策」「MEO 上位表示 方法」「SEO 外注 費用」等を検索。AI検索（ChatGPT/Perplexity）でも質問する層

## 記事カテゴリ（静的サイトのディレクトリ構成に対応）

| カテゴリ名 | スラッグ | カテゴリカラー（画像用） |
|:--|:--|:--|
| AIO運用（AI検索最適化） | `aio` | TODO: |
| SEO運用 | `seo` | TODO: |
| MEO運用（マップ検索最適化） | `meo` | TODO: |
| AI集客・活用全般 | `ai-marketing` | TODO: |

記事URL形式: `https://example.com/{カテゴリスラッグ}/{記事スラッグ}/`

## CTA設定

| CTA | 文言 | リンク先 |
|:--|:--|:--|
| CTA 1（無料相談） | TODO:（例: AI集客の無料相談を予約する） | `https://example.com/contact/` |
| CTA 2（資料DL） | TODO:（例: AIO対策チェックリストを無料ダウンロード） | `https://example.com/download/` |

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

## セットアップ進捗チェックリスト

- [x] プロジェクト初期構築（ディレクトリ・CLAUDE.md・PROJECT.md）
- [x] Ahrefs MCP 設定ファイル（.mcp.json — APIキー記入は未）
- [x] スプレッドシート雛形（spreadsheet_template.xlsx）
- [x] 静的サイト本体（トップ・カテゴリ4・about・contact・download・リード獲得LP）
- [x] 記事テンプレート（templates/article.html）+ ビルドスクリプト（scripts/build.py）— サンプル記事でビルド検証済み
- [ ] ドメイン取得 → 全ファイルの `example.com` を一括置換 + `scripts/build.py` の SITE_URL 更新
- [ ] Cloudflare Pages プロジェクト作成+Gitリポジトリ連携（ビルド出力: `site/`）
- [ ] フォーム送信先の実装（Cloudflare Pages Functions推奨 — `/lp/` `/contact/` `/download/` の3箇所）
- [ ] LPの実績数値（支援社数・継続率等）を実データで差し替え
- [ ] サービス紹介動画・写真素材の制作 → LPのプレースホルダー差し替え
- [ ] spreadsheet_template.xlsx をGoogle Sheetsにインポート → IDを本ファイルに記入
- [ ] .env に全認証情報を設定（X / YouTube / Sheets / Indexing / 画像生成）
- [ ] GA4作成+AI参照元セグメント設定
- [ ] GSC登録+生成AIパフォーマンスレポート確認
- [ ] 本ファイルの残TODO（著者情報・CTA文言・ブランドカラー）を記入
