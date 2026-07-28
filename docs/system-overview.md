# システム全体図: 全フローと使用コンポーネント（2026-07-28時点・v2）

> このドキュメントは自動投稿システムの「地図」。フロー・使うもの・現在の状態をすべて記載する。

---

## 1. 全フロー一覧

| フロー | トリガー | 内容 | 状態 |
|---|---|---|---|
| ① 記事作成（朝） | 毎日 8:00（Task Scheduler） | Phase 1〜7で記事1本を作成・審査・公開 | 🟢 稼働中 |
| ② 記事作成（夜） | 毎日 19:00（同上） | 同上 | 🟢 稼働中 |
| ③ 即時リトライ | ①②の直後（内蔵） | 90点未満の記事をその場で修正→再審査（最大2回） | 🟢 稼働中 |
| ④ 同日救済 | 毎日 21:30（Task Scheduler） | 不合格残り or 本日分ゼロのときだけ再挑戦 | 🟢 稼働中 |
| ⑤ 手動実行 | 「記事を書いて」等の指示 | 同じPhase 1〜7を対話セッションで実行 | 🟢 いつでも |
| ⑥ 週刊ニュースレター | 毎週月曜 9:00（GitHub Actions） | 直近1週間の合格記事をメール配信 | 🟡 Actions接続後 |
| ⑦ 月次コンサルレポート | 毎月1日 9:00 | GA4+GSC実データからPDFレポート生成 | 🟡 GA4稼働後に登録 |
| ⑧ 週次最適化 | 月曜 10:23（CLAUDE.md定義） | カニバリ検出・リライト・内部リンク・AIO監査 | 🟡 GSC稼働後に登録 |
| ⑨ 日次KPIレポート | 毎日 22:13（CLAUDE.md定義） | KPI計測→kpi_feedback.md更新（翌朝の学習源） | 🟢 **ローカル版が稼働中**（local_kpi.pyが毎実行後に記事数・スコア・文字数を自動集計）。GA4/GSC版は稼働後に登録 |
| ⑩ 月次AI引用チェック | 毎月1日 11:00（CLAUDE.md定義） | 主要KWのAI検索引用状況をスポットチェック | 🟡 公開後に登録 |
| ⑪ クラウド版①〜④ | GitHub Actions（cron） | ①〜④と同一内容をPC不要で実行 | 🟡 リポジトリ接続後 |

## 2. 記事作成フローの詳細（①②⑤共通）

```
run_pipeline.ps1 起動
 ├ git pull（リモートあれば）/ 古いログ削除
 ├ Claude Code ヘッドレス起動（pipeline_prompt.txt）
 │   Phase 1  KW選定      … Ahrefs MCP（認証後）／代替: 業種ピラー30KWリスト・記事作成ログ
 │   Phase 2  一次情報    … X API v2・YouTube API+yt-dlp（キー設定後。未設定はスキップ記録）
 │   Phase 3  設計        … 上位構造分析・Query Fan-Out（自動モードは承認スキップ）
 │   Phase 4  執筆        … 5,000字以上・AIO12ルール・AI感排除7項目・マーカー12-18
 │   Phase 5  品質審査    … 6エージェント120点→100点換算。90点未満は公開不可
 │   Phase 6  画像+公開   … make_images.py（アイキャッチ+図解flow/list/vs・自動軽量化）
 │                         → build.py（HTML/Schema/目次/前後ナビ/診断バナー/購読フォーム自動挿入、
 │                            sitemap・llms.txt・feed同期、トップ新着+カテゴリ一覧の自動同期、
 │                            機械検査8種、連鎖隔離防止）
 │                         → git commit（リモート設定後はpush→Cloudflare自動デプロイ）
 │   Phase 7  分析        … Indexing API/IndexNow送信・シート更新（各API設定後）
 ├ BLOCKED検知→即時リトライ（retry_prompt.txt・最大2回）
 ├ local_kpi.py … kpi_feedback.md のサイト概況を自動更新（学習ループの公開前版）
 └ summary.log に1行記録（OK/WARN/NG）
```

## 3. 使うもの一覧

### 実行基盤
| もの | 用途 | 状態 |
|---|---|---|
| Claude Code（サブスク枠） | 全Phaseの実行エンジン | 🟢 |
| Windowsタスクスケジューラ | 8:00/19:00/21:30の起動 | 🟢 登録済み |
| GitHub Actions | クラウド実行（pipeline.yml / digest.yml） | 🟡 接続待ち |
| Cloudflare Pages | ホスティング+自動デプロイ+Functions | 🟡 接続待ち |
| Python 3.14 | build/画像/レポート/配信スクリプト | 🟢 |
| ライブラリ | markdown, pyyaml, Pillow, playwright(検証), google-api系(レポート) | 🟢 |
| git | バージョン管理・公開トリガー | 🟢（リモート未設定） |

### 外部API・サービス
| もの | 用途 | 状態 |
|---|---|---|
| Ahrefs MCP | KW選定・AI Overview確認・DR計測 | 🟠 認証待ち（`claude`起動→承認→OAuth） |
| X API v2 | 一次情報（投稿30件） | 🔴 キー未設定（.env） |
| YouTube Data API + yt-dlp | 一次情報（文字起こし） | 🔴 キー未設定 |
| Resend | リード通知・購読登録・週刊配信 | 🔴 キー未設定（3機能の実装は完了） |
| GA4 | PV・AI参照元・CV計測（イベント実装済み） | 🔴 タグID未発行 |
| GSC | 検索+生成AIパフォーマンス計測 | 🔴 公開後 |
| Google Indexing API / IndexNow | 即時インデックス | 🔴 公開後 |
| Google Sheets | 11タブの運用データ管理（雛形作成済み） | 🟡 MCP/認証は運用開始時 |

### リポジトリ内の部品
| 種類 | ファイル |
|---|---|
| 指示書 | CLAUDE.md（パイプライン定義）/ PROJECT.md（案件設定）/ automation/pipeline_prompt.txt / retry_prompt.txt |
| 実行スクリプト | automation/run_pipeline.ps1 / run_retry.ps1 / register_tasks.ps1 |
| ビルド | scripts/build.py（変換+自動挿入+機械検査8種+90点ゲート） |
| 画像生成 | scripts/make_images.py（一括）/ make_eyecatch.py / make_diagram.py（flow・list・vs） |
| 配信・分析 | scripts/send_digest.py / monthly_report.py / notify_indexnow.py / local_kpi.py（公開前KPI集計） |
| テンプレート | templates/article.html（Schema・シェア・前後ナビ・購読・診断バナーの雛形） |
| サーバレスAPI | functions/api/lead.js（フォーム）/ subscribe.js（購読）/ audit.js（サイト採点） |
| フロント | site/css/style.css・lp.css / site/js/site.js（GA4計測・A/B・読み上げ・検索等）/ quiz.js（診断） |
| 学習・記録 | kpi_feedback.md / automation/logs/（実行ログ+summary.log）/ data/ |
| 計画書 | docs/industry-pillar-plan.md（KW供給源）/ github-actions-setup.md / press-release-draft.md / external-exposure-plan.md / video-audio-plan.md |

## 4. 品質ゲート（公開を物理的に止める仕組み）

1. score 90点未満・未審査 → build.pyがビルド除外+生成済みHTML削除
2. 機械検査8種: タイトル15-45字 / メタ60-160字 / カニバリ類似80% / 内部リンク404 / マーカー8+ / 本文5,000字+ / アイキャッチ実在 / 本文画像実在
3. 連鎖隔離防止: 不合格記事へのリンクは自動テキスト化（合格後に自動復活）
4. 日本語フォント未検出時は画像生成を中断（文字化け画像を出さない）

## 5. 学習ループ

kpi_feedback.md（成功/失敗パターン）→ 翌朝のPhase 1が読み込み → 成功構造を踏襲・失敗要素を回避。
GA4/GSC稼働後は⑧⑨⑩がこのファイルを実データで自動更新し、ループが完全自動化する。
