# 自動更新システムを別サイトへ移行する手順

このリポジトリの「記事を毎日自動生成して公開し続ける仕組み」を、別のサイトへ丸ごと移す手順です。
所要時間はおよそ1〜2時間（うち待ち時間がDNS伝播の30分ほど）。

移行するのは**仕組みだけ**で、記事・画像・ドメイン設定は新サイト用に作り直します。

---

## 全体の流れ

| # | 工程 | 誰が | 目安 |
|---|---|---|---|
| 1 | リポジトリを複製 | ユーザー | 5分 |
| 2 | 設定ファイルを書いて一括置換 | Claude | 10分 |
| 3 | Cloudflare Pages を作成しドメイン接続 | ユーザー+Claude | 20分 |
| 4 | GitHub Secrets を登録 | ユーザー | 10分 |
| 5 | Google連携（GSC / GA4 / Indexing） | ユーザー+Claude | 20分 |
| 6 | メール・フォーム（GAS or Resend） | ユーザー+Claude | 15分 |
| 7 | コンテンツ設計（PROJECT.md・KWリスト） | Claude | 20分 |
| 8 | 初回テスト実行 | Claude | 15分 |

---

## 1. リポジトリを複製する

GitHubで新しいリポジトリを作り、このリポジトリの中身をコピーします。

```bash
git clone https://github.com/yoshi4476/SS-AIO-LP.git 新サイト名
cd 新サイト名
git remote set-url origin https://github.com/<自分>/<新リポジトリ>.git
git push -u origin master
```

**必ず新しいリポジトリで作業してください。** 元のリポジトリで置換すると既存サイトが壊れます。

実行時間の無料枠を使い切らないよう、新リポジトリも **public** にすることを推奨します
（private の場合は月2,000分の枠を全リポジトリで分け合う形になります）。

---

## 2. 設定を書いて一括置換する

`site.config.json` をコピーして新サイトの値に書き換えます。

```json
{
  "domain": "media.example.co.jp",
  "site_name": "新メディア名",
  "site_tagline": "サイトの一言説明",
  "org_name": "運営会社名",
  "brand_en": "Brand",
  "author_name": "◯◯編集部",
  "author_role": "◯◯の実務チーム",
  "tel": "00-0000-0000",
  "address": "〒000-0000 ...",
  "cf_project": "cloudflare-pages-project-name",
  "github_repo": "user/repo",
  "ga4_measurement_id": "G-XXXXXXXXXX",
  "notify_email": "info@example.co.jp",
  "from_email": "新メディア名 <info@media.example.co.jp>",
  "corporate_url": "https://www.example.co.jp/",
  "categories": { "cat1": "カテゴリ1", "cat2": "カテゴリ2" }
}
```

```bash
python scripts/init_site.py new-site.json                        # 差分の確認だけ
python scripts/init_site.py new-site.json --apply --clear-content  # 置換+記事を初期化
```

`--clear-content` を付けると、記事・生成HTML・画像・レポートが消えて新品の状態になります。
仕組み（スクリプト・ワークフロー・テンプレート・CSS）はそのまま残ります。

**カテゴリを変える場合**は置換だけでは足りません。`scripts/build.py` の `CATEGORIES` と
`STATIC_PAGES`、`site/` 配下のカテゴリ一覧ページ、ヘッダー・フッターのナビを合わせて直す必要があります。
Claudeに「カテゴリを◯◯に変えて」と依頼してください。

---

## 3. Cloudflare Pages を作成する

1. Cloudflareダッシュボード → Workers & Pages → Create → Pages
2. プロジェクト名は `cf_project` に書いた名前にする
3. デプロイはワークフローが自動で行うため、Git連携は不要（`wrangler pages deploy` 方式）
4. 独自ドメインを追加 → 表示された値をDNSにCNAMEで登録 → 30分ほどで開通

APIトークンは既存のものを流用できます（アカウントが同じ場合）。
新規に作る場合は「Cloudflare Pages: Edit」権限のトークンを発行してください。

---

## 4. GitHub Secrets を登録する

新リポジトリの Settings → Secrets and variables → Actions に以下を登録します。

| Secret名 | 内容 | 必須 |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` で発行 | ✅ |
| `CLOUDFLARE_API_TOKEN` | Pages編集権限のトークン | ✅ |
| `CLOUDFLARE_ACCOUNT_ID` | CloudflareのアカウントID | ✅ |
| `GCP_SERVICE_ACCOUNT_JSON` | サービスアカウントJSONの中身 | 推奨 |
| `GA4_PROPERTY_ID` | GA4のプロパティID（数字） | 推奨 |
| `RESEND_API_KEY` | メール送信・ニュースレター用 | 任意 |
| `RESEND_AUDIENCE_ID` | 購読者リストID | 任意 |
| `LEAD_FROM_EMAIL` | 送信元アドレス | 任意 |
| `SLACK_WEBHOOK_URL` | 未設定ならメール通知になる | 任意 |

`CLAUDE_CODE_OAUTH_TOKEN` は**同じトークンを複数リポジトリで使い回せます**。

---

## 5. Google連携

**Search Console**: 新ドメインをプロパティ登録 → HTMLファイル方式で所有権確認
（`site/` にファイルを置いてデプロイ）→ sitemap.xml を送信。

**GA4**: 新しいデータストリームを作成 → 測定ID（G-から始まる）を `ga4_measurement_id` に設定して再置換。

**サービスアカウント**: 既存の `aio-report@ss-aio-media.iam.gserviceaccount.com` を流用できます。
新サイトのGA4に「閲覧者」、Search Consoleに「オーナー」で追加してください
（Indexing APIはオーナー権限が必須）。GCPプロジェクトを分けたい場合は新規作成でも構いません。

**IndexNow**: `site/{32桁hex}.txt` を新しく発行し直します（`python -c "import secrets;print(secrets.token_hex(16))"`）。
`scripts/notify_indexnow.py` はファイル名から自動検出するため、ファイルを置き換えるだけで動きます。

---

## 6. メール・フォーム

**Google Apps Script方式（推奨・無料）**: [automation/gas/contact.gs](../automation/gas/contact.gs) を
新しいスプレッドシートに設置してウェブアプリとしてデプロイ。
`GAS_WEBHOOK_URL` と `GAS_SHARED_SECRET` を Cloudflare Pages の環境変数に設定します。
共有シークレットは**サイトごとに別の値**にしてください。

**Resend方式**: 新ドメインをResendで認証（DKIM・SPFのDNSレコード3件を追加）→ APIキーを発行。
ニュースレターを使う場合は Audience も新規作成します。

---

## 7. コンテンツ設計

ここが移行で最も重要な工程です。仕組みは共通でも、**何を書くかはサイトごとに設計し直す**必要があります。

- **PROJECT.md**: ペルソナ・カテゴリ・CTA・自社の強み（E-E-A-Tの根拠）を新サイト用に書き換える
- **docs/industry-pillar-plan.md**: KWリストを新サイトのテーマで作り直す（30本程度）
- **scripts/kw_discover.py**: `INDUSTRIES` と `INTENTS` を新サイトのテーマ語に変える
  （ここを直さないと、前サイトの業種のKWを発掘し続けてしまいます）
- **site/about/**, **site/lp/**, **templates/article.html** の会社情報・監修者情報
- **site/images/company/**: ロゴ・代表写真の差し替え

Claudeに「新サイトのテーマは〇〇。PROJECT.mdとKWリストを作り直して」と依頼すれば一括で対応できます。

---

## 8. 初回テスト

```bash
python scripts/build.py          # 警告ゼロを確認
python scripts/kw_status.py      # KW候補が出るか確認
```

そのうえで GitHub Actions の「Article Pipeline」を手動実行（workflow_dispatch）し、
記事が1本生成されて公開URLで200が返れば移行完了です。

---

## 移行しないもの・注意点

- **記事の中身は引き継がない**（テーマが違えばSEO資産にならないため）。
  同じテーマの姉妹サイトを作る場合は、記事を複製すると**重複コンテンツとして両方が評価を落とします**。絶対に避けてください。
- **GSC/GA4のデータは引き継がれない**（新ドメインは実質ゼロからのスタート）
- **Claudeの認証トークンは約1年で失効**するため、複数サイトを運用する場合は
  更新時に全リポジトリのSecretsを更新する必要があります
- 複数サイトを同時に自動運転すると、privateリポジトリの場合はActions無料枠を共有します。
  publicにすれば無制限です
