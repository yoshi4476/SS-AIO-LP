# SNSへの自動投稿

記事を公開すると `scripts/post_social.py` が走り、設定済みの媒体へ配信する。
未設定の媒体は黙って飛ばすため、必要なものから順に足せばよい。

3サイトの記事を**1つのアカウント**から配る前提の設定になっている。
サイトごとにアカウントを分ける場合だけ、環境変数の末尾にサイトIDを付ける
（`X_ACCESS_TOKEN_CORPORATE` のように。無ければ共通の値が使われる）。

## 対応状況

| 媒体 | 自動投稿 | 画像 | 本文中のリンク | 必要なもの |
|:--|:--|:--|:--|:--|
| X | ○ | 添付可 | ○ | APIキー4つ（OAuth 1.0a） |
| Facebookページ | ○ | OGPが展開される | ○ | ページアクセストークン |
| Instagram | ○ | **必須** | ×（プロフィール誘導） | プロアカウント＋FBページ連携 |
| Threads | ○ | 任意 | ○ | Threads APIのトークン |
| LinkedIn | ○ | OGPが展開される | ○ | 会社ページのトークン |
| note | **×** | — | — | 公開APIが無い（後述） |

## X（設定済みの有料プラン）

**https://developer.x.com/en/portal/dashboard**

App → **Keys and tokens** で4つを発行する。
User authentication settings で **Read and write** にしておくこと（Readのままだと投稿できない）。

```
X_API_KEY=
X_API_SECRET=
X_ACCESS_TOKEN=
X_ACCESS_SECRET=
```

## Facebookページ / Instagram

どちらも Meta の同じトークンを使う。Instagramは**プロアカウント**にして
Facebookページと連携しておく必要がある。

**https://developers.facebook.com/apps/**

1. アプリを作成 → 製品に「Facebookログイン」「Instagram Graph API」を追加
2. グラフAPIエクスプローラで `pages_manage_posts` `instagram_content_publish` の権限を付けてトークンを取得
3. 長期トークンに交換する（短期は約2時間で切れる）

```
FB_PAGE_ID=
FB_PAGE_TOKEN=
IG_USER_ID=
```

Instagramは**本文にリンクを置けない**。プロフィールのリンクへ誘導する形になるため、
プロフィールに記事一覧のURLを設定しておくこと。

## Threads

**https://developers.facebook.com/docs/threads**

```
THREADS_TOKEN=
THREADS_USER_ID=
```

## LinkedIn 会社ページ

経理BPOや補助金の記事は法人担当者に届きやすい。

**https://www.linkedin.com/developers/apps**

1. アプリを作成し、会社ページを紐づける
2. 製品から **Community Management API** を申請（審査あり・無料）
3. 権限 `w_organization_social` を付けてトークンを取得
4. 会社ページIDは、管理画面のURL `linkedin.com/company/<数字>/admin` の数字部分

```
LINKEDIN_TOKEN=
LINKEDIN_ORG_ID=
```

トークンは60日で失効する。切れたら再取得が要る（`post_social.py` は失敗を表示して次へ進む）。

## note について

note には投稿用の公開APIが無い。ブラウザ操作を自動化する方法は技術的には
可能だが、規約が想定していない使い方であり、アカウント停止の risk を負う。
**自動投稿の対象にしない。**

転載したい場合は次のいずれかになる。

- 手動で転載する（正規URLを本文に置き、canonical代わりに出典として明記する）
- noteでは記事の要約だけを載せ、本文は自サイトへ誘導する

なお、同じ本文をそのまま note に載せると自サイトと重複コンテンツになり、
note側が検索で上位に出て自サイトの評価を吸うことがある。全文転載は勧めない。

## 確認

```bash
python scripts/post_social.py ai-lab <slug> --dry     # 投稿文と画像URLを表示
python scripts/post_social.py --today                 # 本日公開分を配信
```

## トークンの期限について

**失効しないようにできる媒体と、できない媒体がある。**

| 媒体 | 期限 | 対応 |
|:--|:--|:--|
| X | **なし** | OAuth 1.0a のアクセストークンは、取り消すまで有効 |
| Facebookページ | **なし** | 長期ユーザートークンから発行したページトークンは失効しない |
| Instagram | 60日 | Metaのユーザートークンを延長すると連動して延びる |
| Threads | 60日 | APIで交換して延長（自動） |
| LinkedIn | アクセス60日 / リフレッシュ365日 | リフレッシュトークンで自動更新 |

### 失効しないトークンの取り方

**Facebookページ**: グラフAPIエクスプローラで短期ユーザートークンを取得 →
「アクセストークンツール」で**長期ユーザートークン**に交換 → そのトークンで
`/me/accounts` を叩き、返ってきた**ページトークン**を使う。これは失効しない。
短期トークンから直接取ったページトークンは2時間で切れるので注意。


### 自動更新

期限のある3つは、週次で自動更新する（`weekly-optimize.yml`）。

```bash
python scripts/refresh_tokens.py          # 期限が近いものを更新
python scripts/refresh_tokens.py --check  # 残り日数の確認だけ
```

期限の**14日前**から更新する。当日更新にすると、失敗したときに打つ手が無くなるため。

LinkedInの自動更新には次の3つが要る。

```
LINKEDIN_REFRESH_TOKEN=
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
```

更新した値は `.env` に書き戻す。CIでも使うため、`GH_SECRET_TOKEN`（Actions secrets を
書ける権限のPAT）を設定しておくと GitHub Secrets も自動で更新される。
設定しない場合は手動での更新が要る。

日次監査が残り日数を見ており、14日を切ると `TODO:` に出る。
LinkedInのリフレッシュトークン（365日）だけは、年1回の再取得が避けられない。

## 媒体ごとの最適化と導線

同じ文面を全媒体に流すと、どこでも中途半端になる。媒体の性質に合わせて作り分けている。

| 媒体 | 要点の長さ | ハッシュタグ | 記事URL | 相談窓口への導線 |
|:--|--:|--:|:--|:--|
| X | 70字 | 2個 | 本文に記載 | なし（280字で窮屈になるため） |
| Facebook | 110字 | **0個** | 本文に記載 | **あり** |
| LinkedIn | 140字 | 3個 | 本文に記載 | **あり** |
| Instagram | 110字 | 5個 | **不可** | プロフィール誘導 |
| Threads | 80字 | 2個 | 本文に記載 | なし |

Facebookでハッシュタグを付けないのは、付けるほど表示が伸びない傾向があるため。
逆にInstagramはタグ経由の発見が多いので多めにする。

### 流入元の計測（UTM）

すべてのURLに `utm_source` を自動で付ける。付けないとSNS経由の流入が
GA4でまとめて「Referral」になり、どの媒体が効いているか分からないまま
投稿を続けることになる。

```
https://ai.7senses.co.jp/aio/aio-taisaku-guide/?utm_source=x&utm_medium=social&utm_campaign=article
```

GA4の「トラフィック獲得」で `x` `facebook` `linkedin` `instagram` `threads` が
別々に見えるようになる。

### 相談窓口の行き先

`sites/*.json` の `cta` で決まる。記事だけ読ませて終わりでは問い合わせにつながらない。

| サイト | 行き先 |
|:--|:--|
| AI集客ラボ | `/lp/`（リード獲得LP） |
| コーポレート | `/contact/` |
| AI導入補助金 | `lp.7senses.co.jp/#contact` |

### Instagramのプロフィールリンク

本文にURLを置けないため、**プロフィールのリンクを必ず設定しておくこと**。
未設定だと投稿を見た人の行き先が無くなる。記事一覧かLPを指定する。
