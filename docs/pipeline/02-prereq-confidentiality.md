## 2. 前提条件

### 必須ツール/API

| ツール | 用途 | 備考 |
|:--|:--|:--|
| Claude Code | パイプライン実行基盤 | Scheduled Tasks / cron で定期実行 |
| 静的HTMLサイト（Cloudflare Pages） | 記事公開先 | Gitリポジトリ連携で自動デプロイ。メタ情報・SchemaはHTMLテンプレートに直書き（WordPress/Rank Math不使用） |
| Ahrefs API（MCP経由） | KW調査・競合分析・SERP分析・AI Overview表示確認 | MCP設定が必要 |
| X(Twitter) API v2 | 一次情報収集（投稿） | Bearer Token必須。note_tweetフィールド対応 |
| YouTube Data API v3 | 一次情報収集（動画） | APIキー必須 |
| Google Sheets API | データ管理・KPIレポート | MCP経由推奨 |
| Google Indexing API | 即時インデックス登録 | サービスアカウント+GSCオーナー権限 |
| Google Search Console | 検索計測+生成AIパフォーマンスレポート（2026年6月導入） | AIO計測の中核 |
| IndexNow（オプション） | Bing/Copilot系への即時URL通知 | キーをサイトルートに設置 |
| 画像生成（Pillow） | アイキャッチ+図解 | `scripts/make_images.py` がローカルで描画。外部APIは呼ばないため、キーの設定は不要 |
| yt-dlp | YouTube自動字幕取得 | `pip install yt-dlp` |
| Python 3.10+ | Markdown→HTML変換 | `markdown` ライブラリ（tables, extra） |

認証情報は [.env](.env) に設定する（雛形あり）。スプレッドシートIDは PROJECT.md で管理。

### 2.1 守秘義務（どこに何を置くか・最優先）

管制塔（yoshi4476/SS-AIO-LP）は GitHub Actions を無料で使うため **public のまま**運用する（2026-10-10 運用者の指示）。
public なので、**リポジトリの中身・コミットの履歴・CI のログ（90日）・成果物（artifact）は誰でも読める**。
お客様から預かったもの・お客様について調べたもの、当社の料金と営業の台本、レポートの数字は、
**非公開のリポジトリ `yoshi4476/ss-aio-private`（workflow は置かない＝料金はかからない）にだけ置く**。
手元と CI は管制塔の直下 `private/` に取得する（`.gitignore` 済み）。読み書きは必ず `scripts/private_store.py` を通す。

| 置き場 | 置くもの |
|:--|:--|
| 非公開 `clients/<id>/company.json` | まだ公開していない会社情報（住所・電話・代表者・資本金・問い合わせのメール・監修者の名前と資格と登録番号） |
| 非公開 `clients/<id>/brief.json` | 記事の材料（売り物と料金・読者の困りごと・FAQ・狙う語・狙わない語・競合・事例・お客様の声） |
| 非公開 `clients/<id>/facts.json` | 一次情報 |
| 非公開 `clients/<id>/kw.md` | キーワード計画（週次の補充が積む） |
| 非公開 `clients/<id>/site_private.json` | サイト設定の全部（社名・ドメイン・納品方式・配信先・カテゴリと、狙う業種・禁止語・配分・優先・読者・テーマ・売り物・監修・CTA・計測の ID など）と公開の id（`public_id`）。`sites.load_all()` がここから読む |
| 非公開 `articles/`・`site/images/<slug>/`・`data/duo_scripts/`・`data/duo_shorts/` | お客様の社の原稿（公開前・85点未満で止めたものも）・図・動画の台本。取得のたびに作業場所へ重ねて置く（下記） |
| 非公開 `clients/<id>/data/` | 全社1ファイルの記録のその社の行（`videos.json`・`youtube_connected.json`・`editorial_reviews.jsonl`・`bing_backfill.json`・`pace_manual.json`。`client_private.REPO_BACKED`。読むときに公開側と合わせる） |
| 非公開 `clients/<id>/private.json` | 担当者の連絡先・接続先（パスワードは入れない。鍵は Secrets） |
| 非公開 `sales/` | 当社の料金（`prices.json`・提案書の料金のページ `proposal_pricing.json`・`sales_prices.py`）、営業の台本（`sales_script_*.py`）、提案資料の生成（`sales_deck.py`・`sales_pptx.py`）と出来上がり |
| 非公開 `reports/` | 月次・週次・グループのレポート（PDF・HTML）、翌月の目標（`targets*.json`）、3倍計画（`growth_plan.json`・`growth-plan.md`） |
| CI のキャッシュ（`data/clients/<id>/private/`） | お客様の順位・AIの答え・共起語などの派生データ（7日使わないと消えるので、元の情報の置き場にしない） |
| **public（このリポジトリ）** | 社が特定できない印だけ: `sites/<公開の id>.json` に `sites.PUBLIC_KEYS`（id・`"client": true`・1日の本数）。枠の割り当て（`site_order`）を、非公開のデータが取れない回も同じにするために残す |

**公開の id**: お客様の社は、社名から推測できない `c` と16進8桁（`private_store.new_public_id`）を公開の id にする。
新しく受ける社は社の id も同じ値（`client_intake.assign_id`。シートの「id」欄は使わない）。運用者自身の事業の社は
社の id（内部の名前）と公開の id が違い、`sites.resolve`（公開の id → 社の id）・`sites.public_id`（逆）で行き来する。
ジョブの間の受け渡し・コミットの文・知らせる文は公開の id、工程に渡すのは社の id（`private_store.py --resolve`）。
社の id は CI で伏せる語なので、ジョブの出力に入れると GitHub が落とす。

**重ねて置く仕組み**（原稿・図・台本）: 取得（`--fetch`）のたびに `overlay_in` が非公開の `articles/` などを作業場所の
同じ場所へ写し、`.git/info/exclude` の管理区画に載せて公開側の git から外す。`.git/hooks/pre-commit`（`--pre-commit`）が
commit の直前にお客様の社のファイルを commit から外して非公開へ戻し、ジョブの最後の `private-data`（`mode: save`・
`if: always()`）が `--push` で残す。手元で書いた分も commit のたびに戻る。運用者自身の事業の社も同じ道を毎日通す
（外部のお客様より先に壊れた所が見つかる）。自社サイトのフッターの制作表記など、もともと公開している表示は残す。

**守ること**（門 `tests/gates_history_h76.py`・`h77.py` が止める）:
- お客様の社のファイル（company/brief/facts/site_private・`docs/kw-<id>.md`）、`reports/`・`docs/sales/`・`docs/growth-plan.md` を公開側で追跡しない
- `sites/<公開の id>.json` に `PUBLIC_KEYS` 以外の項目を書かない（`private_store.write_site` が分ける）
- 公開側で追跡しているファイル（コード・門・コメント・記録）に、お客様の社の名前・ドメイン・配信先と記事の題・slug を書かない。
  門に要るときは架空の社（`client-zz`・`zz.example`）で書く。社に依る門は非公開の `tests/gates_client_*.py`（データがある回だけ回る）
- CI のログに記事の題・slug を出さない（`private_store.shown(slug)` は「（お客様の記事）」を返す。件数で出す）。
  門の出力も `test_gates.hide` が社の id・名前を公開の id に置き換える
- 公開側のコード・指示・文書に当社の料金の数字を書かない（`proposal_make.pricing_pages` は非公開の JSON から読む）
- `pull_request` / `pull_request_target` で動く workflow を置かない（キャッシュと鍵を他人の変更提案から守る）
- お客様のデータを扱うジョブは checkout の直後に `.github/actions/private-data` を通す（取得と、守秘の語の `::add-mask::`。`scripts/ci_mask.py`）。
  お客様の社について工程が出す行は **語の一覧ではなく件数**にする（例: 「<公開の id>: 候補12語」）。執筆の案内（site_brief）はファイルにだけ書き、ログに出さない
- 成果物（artifact）にお客様の語が載りうるファイルを入れない（ジョブ間の受け渡しは CI のキャッシュ）
- **CI で非公開のデータが取れないときは、お客様の社の記事・キーワード計画・配信を止めて知らせる**（`private_store.require`。
  材料なしで書かせない）。自社3サイトはこれまでどおり動く
- 鍵: CI は Secret `PRIVATE_DATA_TOKEN`（無ければ `SITE_PUSH_TOKEN`）。fine-grained トークンなら `yoshi4476/ss-aio-private` の Contents を Read and write

```bash
python scripts/private_store.py --fetch            # 手元に private/ を取得する（あれば最新にする）。原稿を重ねて置き、hook を入れる
python scripts/private_store.py --overlay          # 取得済みの private/ の原稿・図・台本を作業場所へ重ね直す
python scripts/private_store.py --resolve <公開の id>   # 社の id（--public-id <社の id> で逆）
python scripts/private_store.py --status           # 社ごとの材料の有無（件数だけ）
python scripts/private_store.py --check-site <id>  # お客様の社の材料が読めるか（PRIVATE_OK=yes/no/own）
python scripts/private_store.py --push "<理由>"     # private/ の変更を commit・push する
python scripts/ci_mask.py --count                  # 社ごとの伏せる語の数（語は出さない）
```

過去の記録（コミットの履歴・90日以内の CI のログ）に残っているものは消していない（履歴の書き換えとログの削除は運用者が決める）。

---

