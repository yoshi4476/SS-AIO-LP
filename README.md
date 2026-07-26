# AI集客ラボ — SSオウンドメディア（AIO/LLMO/SEO/MEO）

セブンセンシズ株式会社の集客用オウンドメディア+リード獲得LP。
静的HTML + Cloudflare Pages 構成。記事制作は [CLAUDE.md](CLAUDE.md) の7Phaseパイプラインで自動化する。

## 構成

| パス | 役割 |
|:--|:--|
| `site/` | 公開ルート（Cloudflare Pagesの出力ディレクトリ） |
| `articles/*.md` | 記事の原稿マスター（YAMLフロントマター付き。`_`始まりは下書き） |
| `templates/article.html` | 記事HTMLテンプレート（メタ・JSON-LD・2カラムレイアウト） |
| `scripts/build.py` | 記事ビルド+sitemap.xml+feed.xml生成 |
| `functions/api/lead.js` | フォーム受付API（Cloudflare Pages Functions + Resend） |
| `CLAUDE.md` | 記事制作パイプライン定義（Phase 1〜7） |
| `PROJECT.md` | プロジェクト固有設定・セットアップチェックリスト |

## ビルド

```bash
python -m pip install markdown pyyaml
python scripts/build.py        # 全記事 → site/{cat}/{slug}/index.html + sitemap + feed
```

## ローカル確認

```bash
python -m http.server 8800 --directory site
# → http://localhost:8800/
```

## デプロイ（Cloudflare Pages）

1. このリポジトリをGitHubへpush
2. Cloudflare Pages でリポジトリを接続（ビルドコマンドなし / 出力ディレクトリ: `site`）
3. 環境変数を設定（フォーム送信用）: `RESEND_API_KEY` / `LEAD_TO_EMAIL` / `LEAD_FROM_EMAIL`
4. 以後は `git push` で自動デプロイ

## 公開前チェックリスト

[PROJECT.md](PROJECT.md) の「セットアップ進捗チェックリスト」を参照。
主要残タスク: ドメイン取得（`example.com` を一括置換+`scripts/build.py` の `SITE_URL`）/ Resend設定 / GA4・GSC設置。

## 記事の追加（手動の場合）

1. `articles/<slug>.md` を作成（フロントマター: title / description / slug / category / date / faq。書式は `scripts/build.py` 冒頭のdocstring参照）
2. `python scripts/build.py` → `site/llms.txt` とトップ/カテゴリの新着リストに1行追記
3. `git add -A && git commit && git push`

品質基準・AIO/LLMO対応ルール・自動パイプラインの詳細はすべて [CLAUDE.md](CLAUDE.md) に定義。
