# GitHub Actions 移行手順（記事自動作成をクラウドで動かす）

> ワークフロー本体は [.github/workflows/pipeline.yml](../.github/workflows/pipeline.yml) に作成済み。
> 以下の手順を上から実行すれば、PCの電源に関係なく毎日 8:00 / 19:00（+21:30救済）にクラウドで記事が作られます。

## 手順1: GitHubリポジトリの作成とpush（5分）

```powershell
# GitHub CLIの場合（ブラウザでリポジトリを作ってもOK）
cd "c:\Users\user\Desktop\システム開発\SSオウンドメディア（AIO）"
gh repo create ss-owned-media --private --source . --push
```

- **privateリポジトリ推奨**（営業情報を含むため）
- private の Actions 無料枠は月2,000分。1回30分×毎日3回で月内に超過する可能性あり（超過分は従量課金・数ドル/月程度）。Settings → Billing で上限を設定しておくと安心

## 手順2: Claude認証トークンの発行と登録（5分）

このPCのPowerShellで:

```powershell
claude setup-token
```

表示される長期トークン（`sk-ant-oat...`）をコピーし、GitHubリポジトリの
**Settings → Secrets and variables → Actions → New repository secret** で登録:

| Secret名 | 値 |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` で発行したトークン（Pro/Maxのサブスク枠で動く） |

※ 代わりに `ANTHROPIC_API_KEY`（APIキー・従量課金）でも動きます。両方登録した場合はOAuthトークンが優先。

## 手順3: 外部APIキーの登録（任意・あるものだけ）

同じくSecretsに登録（未登録の工程はパイプラインが自動スキップ）:

| Secret名 | 用途 |
|---|---|
| `X_BEARER_TOKEN` | X API v2（一次情報収集） |
| `YOUTUBE_API_KEY` | YouTube Data API v3（一次情報収集） |

## 手順4: Cloudflare Pages接続（10分）

1. Cloudflareダッシュボード → Workers & Pages → Create → Pages → **Connect to Git**
2. 手順1のリポジトリを選択 / ビルド出力ディレクトリ: **`site`**（ビルドコマンドは空でOK）
3. 以後、Actionsがpushするたびに自動デプロイ=公開

## 手順5: 動作テスト（3分）

GitHubリポジトリ → **Actionsタブ → Article Pipeline → Run workflow**（mode=main）で手動実行。
ログで記事生成→90点審査→コミットまで流れることを確認する。

## 手順6: PC側のタスクを停止（クラウド移行完了後）

二重実行を防ぐため、Actionsでの成功を確認したらPCのタスクを削除:

```powershell
Unregister-ScheduledTask -TaskName "AIO-Pipeline-Morning","AIO-Pipeline-Evening","AIO-Pipeline-Retry" -Confirm:$false
```

## 運用メモ

- **時刻はUTC表記**: yml内の `0 23 * * *` = JST 8:00。コミット表示・Actionsログの時刻もUTCになることがある（表示上のズレであり実行は正しい）
- **ログの見方**: Actionsタブ → 該当Run → 各ステップを展開。失敗時はGitHubからメール通知が来る
- **手動リトライ**: Actionsタブ → Run workflow → mode=rescue で「BLOCKED記事の救済チェック」だけを実行できる
- **停止したいとき**: Actionsタブ → Article Pipeline → 右上「…」→ Disable workflow
- **Ahrefs MCP**: 対話型OAuth認証はCI上で完了できないため、Phase 1のAhrefs工程は当面スキップされる（記事作成ログの未着手行やKW戦略タブからの選定で代替）。Ahrefs APIキー直叩き方式への切り替えは必要になったら実装
- **フォント**: Linux用にNoto Sans CJK対応済み（make_eyecatch.py / make_diagram.py）。文字化けが起きる場合はフォント未検出で中断する設計のため、壊れた画像が公開されることはない
