# 配信用トークン（SITE_PUSH_TOKEN）の再発行手順

管制塔から**他リポジトリのサイト**へ記事をpushするために使う。自リポジトリ（AI集客ラボ）は
Actions標準の `GITHUB_TOKEN` で足りるため、このトークンは以下2つの配信先のためだけに要る。

| サイト | 配信先リポジトリ | ブランチ |
|:--|:--|:--|
| コーポレート | `yoshi4476/SS-CorporateHP` | `main` |
| AI導入補助金サポート | `yoshi4476/seven-HPunyou` | `master` |

## 発行

GitHub → Settings → Developer settings → Personal access tokens →
**Fine-grained tokens** →「Generate new token」

- **Repository access**: Only select repositories → 上表の2つだけを選ぶ
- **Permissions**: Repository permissions → **Contents: Read and write**
  （他は不要。広い権限を持たせるほど漏れたときの被害が大きい）
- **Expiration**: 90日程度。無期限にすると失効に気づく機会が無くなる

Classic tokenでも動くが、その場合 `repo` スコープ全体が必要になり、
アカウント上の全リポジトリへ書き込める。上の2つに絞れるfine-grainedを推奨する。

## 反映先は2か所

**片方だけ直すと片方が動かない。**

1. **GitHub Secrets**（自動運用がこちらを使う）
   `yoshi4476/SS-AIO-LP` → Settings → Secrets and variables → Actions →
   `SITE_PUSH_TOKEN` を Update
2. **`.env`**（手元から `publish.py` を直接動かすときに使う）
   `SITE_PUSH_TOKEN=＜新しい値＞`

トークンの値をチャットやIssue、コミットに貼らないこと。貼った時点で再発行が要る。

## 確認

```bash
python scripts/token_check.py
```

`TOKEN_OK=yes` なら配信先2つに書き込める状態。Secrets側は次回のパイプライン実行の
「配信トークンの事前確認」ステップで検証される（失効していれば記事を書く前に止まる）。

## 古いトークンの失効

新しいトークンで `TOKEN_OK=yes` を確認してから、古いトークンを Revoke する。
先に消すと配信が止まる。
