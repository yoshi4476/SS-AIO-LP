# SEOオウンドメディア 全自動パイプライン【AIO/LLMO/GEO対応版】

> 記事制作をKW選定から公開後処理まで全自動化する。人間は「品質チェックの最終承認」と「事業方向性の決定」のみ。
> プロジェクト固有の設定（ドメイン・ペルソナ・カテゴリ・CTA等）は [PROJECT.md](PROJECT.md) を参照。**各Phaseの実行前に必ず PROJECT.md を読み込むこと。**

**このファイルは芯（要点と索引）だけを置く。** 全文は [docs/pipeline/](docs/pipeline/) に章ごとにある（2026-10-25 に文言を変えずに移した。
つなげると移す前の CLAUDE.md と1字も違わない）。作業に入る前に、下の「索引」で該当するファイルを読むこと。
CI の AI には `scripts/agent_memory.py` が、この芯の代わりに仕事に要る章の全文（writer・weekly）を組み立てて渡す。

## トリガーコマンド

- 「記事を書いて」「パイプライン実行」→ Phase 1〜7 を順番に実行（[04-phases.md](docs/pipeline/04-phases.md)・[06-quality-rules.md](docs/pipeline/06-quality-rules.md)）
- 「KPI確認」→ Phase 7 の KPIレポート生成を実行（[07-kpi.md](docs/pipeline/07-kpi.md)）
- 「リライト」→ 第8章の週次最適化を実行（[08-weekly.md](docs/pipeline/08-weekly.md)）
- 「AIO監査」→ 第8.5章の AIO監査を実行（[08-weekly.md](docs/pipeline/08-weekly.md)）

---

## 索引（作業の種類 → 読むファイル）

| 作業 | 読むファイル（docs/pipeline/） |
|:--|:--|
| 数字・件数を出す／学びを残す／確かめた事実（0.1〜0.3の全文） | [00-principles.md](docs/pipeline/00-principles.md) |
| 工程の全体像・本数の上限・量産の兆候での減速・社ごとの本数（1章） | [01-overview.md](docs/pipeline/01-overview.md) |
| 必須ツールとAPI・**守秘の置き場の細部**（公開の id・重ねて置く仕組み・コマンド。2章・2.1） | [02-prereq-confidentiality.md](docs/pipeline/02-prereq-confidentiality.md) |
| **お客様の導入**（ヒアリングシート・intake/・一次データ・材料の質問シート・実績）・**納品方式**（self-static/外部/WordPress/FTP/ZIP）・サイトの構成の変更・ディレクトリ構成・Cloudflare Pages・robots.txt/llms.txt（3章） | [03-setup-intake-delivery.md](docs/pipeline/03-setup-intake-delivery.md) |
| **記事を書く**（Phase 1〜7 の全手順・在庫の作り方とラッコの上限・食い合い審査・構成事前審査14項目・採点プロトコル・公開・通知） | [04-phases.md](docs/pipeline/04-phases.md) ＋ [06-quality-rules.md](docs/pipeline/06-quality-rules.md) ＋ [appendix-checklist.md](docs/pipeline/appendix-checklist.md) |
| 定時の工程（記事の枠・同日救済・日次KPI・週次・月次。5章） | [05-schedule.md](docs/pipeline/05-schedule.md) |
| 品質ルール（AI感排除7項目・AIO対応12ルール・装飾・文章・画像・機械品質ゲート・公開条件。6章） | [06-quality-rules.md](docs/pipeline/06-quality-rules.md) |
| KPIレポート・kpi_feedback.md の形式（7章） | [07-kpi.md](docs/pipeline/07-kpi.md) |
| **週次・リライト・統合・内部リンク・自動修正と見直し・通知（findings）・月次の改善・3倍計画・競合比較・多言語・20社の枠**（8章） | [08-weekly.md](docs/pipeline/08-weekly.md) |
| スプレッドシートの列（9章） | [09-sheets.md](docs/pipeline/09-sheets.md) |
| 503・画像・ビルド・インデックス・AI引用・GSC生成AIレポートの困りごと（10章） | [10-troubleshooting.md](docs/pipeline/10-troubleshooting.md) |
| 公開前の最終確認（AIO対応チェックリスト） | [appendix-checklist.md](docs/pipeline/appendix-checklist.md) |

**文書を直すときは docs/pipeline/ の該当ファイルを直す**（この芯に細部を書き戻さない。芯が膨らむと毎回の読み込みが増える）。
芯に書くのは、全作業に効く決まりと索引だけ。門は CLAUDE.md と docs/pipeline/*.md をつなげた文で「書いてあるか」を確かめる。

---

## 0.1 数字を出す前に必ず通す手順（最優先・例外なし・要点）

**1つの測り方の結果を、そのまま事実として報告してはならない**（1つのセッションで9回誤った数字を報告した）。
数字を1つでも出すなら4つを必ず通す: **別の方法で同じ数字を出す**／**内訳に分ける**（指名検索・ボット・重複）／
**「0件」「無い」と言う前に逆を探す**／**前提を口に出して確かめる**。数字が1つ崩れたら、そこから導いた結論をすべて取り下げる。
間違えやすい所: GSC の query次元の合計・末尾スラッシュの重複・指名検索とボットの混入・`form_submit` と `lead_capture` の二重計上・
問い合わせの件数は台帳の相談（`lead_reconcile.leads`。営業・テストの行は除き、除いた数を添える）。
数字・件数・制度名を出す作業では `/fact-checker` スキルを呼ぶ。道具: `python scripts/data_sanity.py`。全文は [00-principles.md](docs/pipeline/00-principles.md)。

## 0.2 学びは台帳に残して次に効かせる（要点）

学びは3つに仕分ける: **機械で守れる → 検査にする**（台帳の `gate` に検査名。プロンプトから外れる）／**判断が要る → `data/lessons.jsonl`**
（書く直前に `python scripts/lessons.py --brief <site>` で関係する分だけ。12件・2,600字まで）／**事実の誤り → 記事を直して `retired`**。
1回の実行で積むのは1件まで。週次の `scripts/learn.py --write` が公開後の実測を学びとして書き換える（積み増さない）。全文は [00-principles.md](docs/pipeline/00-principles.md)。

## 0.3 確かめた事実（要点）

一次情報で確認できたものだけを使う。Google は llms.txt を無視し、構造化データはAI引用に必須ではないと明言（効くのは独自の視点・
非コモディティの内容・クロールできること）。AI検索での見え方は被リンクより言及（YouTube 0.71・リンク無しの言及 0.66 ＞ 被リンク 0.22）。
AI Overview は質問形のクエリで64.7%表示。自社データでは品質スコアは順位と逆、記事の長さは成果を分けない（長さは `depth:` で変える）。
KW選定・構成・リライト・施策提案は `/aio-seo-specialist`、補助金の制度名・金額・締切は `/subsidy-advisor` スキルで確かめる。全文は [00-principles.md](docs/pipeline/00-principles.md)。

---

## 2.1 守秘義務（最優先・要点）

管制塔（yoshi4476/SS-AIO-LP）は **public**。リポジトリの中身・コミットの履歴・CI のログ（90日）・成果物（artifact）は誰でも読める。
お客様から預かったもの・お客様について調べたもの、当社の料金と営業の台本、レポートの数字は、**非公開のリポジトリ `yoshi4476/ss-aio-private`
（workflow は置かない）にだけ置く**。手元と CI は管制塔の直下 `private/` に取得し（`.gitignore` 済み）、読み書きは必ず `scripts/private_store.py` を通す。
public に置くのは社が特定できない印だけ（`sites/<公開の id>.json` の `sites.PUBLIC_KEYS`）。置き場の表・公開の id・重ねて置く仕組み・コマンドは
[02-prereq-confidentiality.md](docs/pipeline/02-prereq-confidentiality.md)。

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
- 社の id は CI で伏せる語。ジョブの間の受け渡し・コミットの文・知らせる文は公開の id、工程に渡すのは社の id（`private_store.py --resolve`）
- 受託運用での分離: お客様の記事に運用会社の実績を書かない（お客様の社の `facts.py` は非公開の `clients/<id>/facts.json` だけを使う）

---

## Phase 1〜7（1行ずつ。全手順は [04-phases.md](docs/pipeline/04-phases.md)）

各Phaseの完了を確認してから次に進む。

1. **KW選定**: 在庫は毎日の見張りが1か月分を切った社だけ `kw_plan` で積む（ラッコは `rakko.allow()` の上限内で最後に1回）。書く前に `python scripts/kw_guard.py "<KW>" --site <id>` の終了コードで判定（0 着手可／1 要差別化／2 着手禁止。目視で代えない）、`kw_intent.py` で開く理由を確かめる
2. **リサーチ**: `python scripts/research.py "<KW>" --site <id>` と `yt_quotes.py` で一次情報（YouTube の字幕・自社の一次情報）を集め、数値ファクトを3つ以上抜く。X は使わない
3. **設計**: 上位記事の見出しの共通60〜70%＋独自30〜40%、Query Fan-Out で H2 6〜8個・各H2に40〜60字の1文結論。構成事前審査14項目を全部○にし、見出し案つきの `kw_guard` が終了コード0になるまで執筆しない
4. **執筆**: 冒頭200字の断言型回答・定義ブロック・鮮度表記・対象読者の限定・一次情報20%以上。`depth:`（quick/standard/deep）で長さを決める。体験は登録した体験からだけ書く
5. **品質**: `python scripts/score_check.py <slug>` を全PASSにし `publish_flow.py --check` を通す。書いた AI は点数（`score`・`score_breakdown`・`quality_*`）を書かない。3観点の採点は公開前に別工程の `scripts/quality_loop.py --new` が行い、届かなければ直して採点し直す
6. **公開**: `make_images.py <slug>` → `build.py`（テンプレ・JSON-LD・sitemap・llms.txt）→ 配信。配信とコミットは鍵を持つ機械の手順が行う
7. **分析**: Indexing API・IndexNow（3サイトとも）・GA4/GSC の記録・内部リンクの追加・kpi_feedback.md の更新

## 全作業に効く運用の決まり（要点。全文は各ファイル）

- **本数**: 1サイト1日2本・月60本が上限（`daily_audit.MONTHLY_CAP`）。量産の兆候が出たら `pace.py` が1日の本数を 2→1→0 に落とす。社ごとの本数は `sites/<id>.json` の `daily_articles`（[01-overview.md](docs/pipeline/01-overview.md)）
- **検査の終了コード**（8.7）: 問題が見つかったら0で `<名前>_OK=no` と明細、無ければ0で `_OK=yes`、検査が動かなかったときだけ1。「見つかった」を1で表さない（例外は `nap_check`・`deploy_check`）
- **通知**: うまくいった報告は送らない（定時は `notify_slack.py --routine`）。**手元での実行は本番の宛先に送らない**（`GITHUB_ACTIONS` が無い環境では送らない）
- **自動修正は必ず見直しとセット**（8.6）: 言い回しを自前で書かない（`link_new.sentence()`）・当てた後に検算（`auto_review.guard()`）・リード導線に触れない・台帳 `automation/logs/auto_fix.jsonl` に残す。文章の判断が要る直しは `auto_rewrite.py`（検算に1つでも外れたら戻す）
- **課金APIは設計を固めてから1回だけ**: 条件を直すときは `--dry-run` とキャッシュで確かめる。ラッコへの通信は `rakko.call()` の1か所だけ（[04-phases.md](docs/pipeline/04-phases.md) Phase 1）
- **AI の作業場**: 記事を書く AI は鍵を外した作業場で動き（`agent_guard`）、配信と管制塔への記録は鍵を持つ機械の手順が行う。AI は CLAUDE.md・docs/pipeline/・scripts/・tests/ などの守る場所を変えない（変えても配信の前に戻される）
- **納品方式**はお客様ごとに選ぶ（self-static / external-* / wordpress / ftp / zip）。どの形式でも記事・書き直し・動画・SNS は管制塔の CI から出し、85点未満は配らない（[03-setup-intake-delivery.md](docs/pipeline/03-setup-intake-delivery.md)）

## 公開の基準（基準の数字は `scripts/rubric.py` の1か所だけ）

- 3観点（各100点）: **一次性80点以上・抽出性と決定支援は75点以上・総合（3観点の平均）85点以上**で公開。**目標90点**・推奨95点。85〜89点で公開した記事は公開後も直し続ける
- **`score` が85点未満・未記載の記事は `build.py` がビルド対象から除外する**（サイト・sitemap・一覧のどこにも出ない）。`quality_state: improving` の記事も公開しない
- build.py の機械品質ゲートは警告ゼロが公開条件。基準・採点プロトコル・修正ループの全文は [04-phases.md](docs/pipeline/04-phases.md) の Phase 5 と [06-quality-rules.md](docs/pipeline/06-quality-rules.md)
