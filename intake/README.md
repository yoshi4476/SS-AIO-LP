# ヒアリングシートの置き場

記入済みのヒアリングシート（.xlsx）を**このフォルダに置いて**、次を実行します。

```bash
python scripts/intake_watch.py            # 何が起きるかを見るだけ
python scripts/intake_watch.py --apply    # 登録まで行う
```

記入用のシートは次で作れます。

```bash
python scripts/client_intake.py --sheet              # 汎用
python scripts/client_intake.py --sheet restaurant   # 業種別（項目が増えます）
```

## 置いたシートの行き先

| 結果 | 行き先 |
|:--|:--|
| 登録できた | `intake/done/` |
| 不備があった | `intake/todo/` と、同じ名前の `.不備.txt`（直す箇所を書いています） |

**不備のあるシートは登録しません。** 主力商材や一次情報が空のまま通すと、
どのサイトでも書ける記事が量産され、AI検索に引用されません。

## 登録されると作られるもの

| ファイル | 中身 |
|:--|:--|
| `sites/<id>.json` | サイト設定（主力商材・カテゴリ配分・守備範囲・CTA・計測） |
| `data/clients/<id>/company.json` | 会社の正規表記 |
| `data/clients/<id>/facts.json` | その会社にしか出せない一次情報 |
| `data/clients/<id>/brief.json` | 記事を書くための材料 |
| `docs/kw-<id>.md` | KW計画の雛形 |

翌日から、日次パイプラインがそのサイトの記事を書き始めます（1社2本/日）。

## 注意

- **シートそのものはコミットされません**（`.gitignore` 済み）。
  このリポジトリは public で、シートには会社名・住所・電話・メールが入るためです。
  登録後に生成される `sites/*.json` だけをコミットしてください
- **10社が上限**です。11社目からは記事の枠が足りず全社の本数が減ります。
  超えると取り込み時に止めて知らせるので、そのときは別リポジトリに分けてください
