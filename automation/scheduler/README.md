# 定時の起動役（Cloudflare Worker）

GitHub Actions の定時（schedule）は3〜8時間遅れて始まる（2026-09-24〜10-07 の実測: 記事の枠は枠0が3〜4時間・後ろの枠が6〜7時間、
同日救済は中央値5.5時間・最大8.1時間、記事動画は中央値5.6時間。週次は6時間遅れて来た回が取り消された）。
Cloudflare Workers の定時（Cron Triggers・無料プラン）から GitHub の workflow_dispatch で、時刻どおりに起動する。
**GitHub の定時は消さずに予備として残す**（Worker が止まっても、今までどおり遅れて動く）。

## 無料プランの上限（Cloudflare の公式文書・2026-10-08 時点）

| 項目 | 無料プラン | この Worker |
|:--|:--|:--|
| 定時（Cron Triggers）の数 | アカウントで5個 | 1個（`*/5 * * * *`） |
| 1日の要求 | 10万件 | 定時で1日288回起きる（HTTP では呼ばれない） |
| 1回の CPU 時間（定時） | 10ミリ秒（待ち時間は数えない） | 表と実行の一覧を読むだけ。一覧は予定の1分前より後に作られた回に絞って小さく取る |
| 1回の外への問い合わせ | 50件 | 最大 1＋窓に入る予定の数×3回×2件（門が表から数えて50以下を確かめる） |
| 1回の時間（定時） | 15分 | 再試行の待ち（15秒・45秒）と問い合わせの上限（1件10秒）を足しても数分 |
| ログ（Workers Logs） | 1日20万件・3日保存 | 1日数百件 |
| 定時の間隔 | 下限の記載なし（文書の例は3分ごと。cron は UTC） | 5分 |

出典: [Limits](https://developers.cloudflare.com/workers/platform/limits/) ・ [Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/) ・ [Workers Logs](https://developers.cloudflare.com/workers/observability/logs/workers-logs/)

## 選んだ形

**5分ごとに1回起き、直前10分（2回分）の窓に予定の時刻が入るものを起動する。**

- 予定ごとに定時を作ると5個に収まらない（予定は47件・分は 0/7/13/23/30/37）
- 起動は予定の時刻から最大5分遅れ（例: 08:07 の枠は 08:10 に起動）。3〜8時間の遅れに比べて十分小さい
- 窓を2回分にしたのは、Cloudflare が1回起きそびれても次の回が拾うため。起動の前に GitHub の実行の一覧を見るので、同じ予定を2回起動しない
- 予定の表は毎回 master の `schedule.json` を読む（cron を変えても配り直さなくてよい）。読めない・形が違うときは配ったときの表を使う。起動先のリポジトリとブランチは配ったときの表から変えさせない

## 対象のワークフロー

| 予定 | ワークフロー | 起動の入力 |
|:--|:--|:--|
| 記事の枠（40枠・毎時7分と37分） | `pipeline-multi.yml` | `slot`（枠の番号＝cron の並び順） |
| 同日救済（21:30） | `pipeline.yml` | `mode=rescue` |
| 記事動画（10:30） | `daily-video.yml` | なし |
| 週次（月曜 10:23） | `weekly-optimize.yml` | なし |
| 日次KPI（10:13） | `daily-kpi.yml` | なし |
| 集中モード（火・金 04:13） | `focus-mode.yml` | なし |
| 月次（1日・15日 9:00） | `monthly-report.yml` | なし |

全部に `scheduled_for`（予定の時刻・日本時間の ISO）と `token_expiry`（鍵の期限）を足して起動する。
表は `schedule.json`。**手で書かない**（`python scripts/scheduler_build.py` が各ワークフローの cron から作る）。
対象を増やすときは `scripts/scheduler_build.py` の `TARGETS` に1行足し、そのワークフローに受け口
（入力2つ・`run-name`・`scripts/sched_guard.py`）を付ける。門 `tests/gates_history_h62.py` が抜けを止める。

## 同じ予定を2回動かさない仕組み

1. **Worker の側**: 起動の前に、その予定の回（Worker が起動した回か、予備の定時の回）がもう作られていないかを GitHub の一覧で見る。
   失敗して再試行するときも、確かめてから起動する。確かめられないうちは起動しない
2. **ワークフローの側**（`scripts/sched_guard.py`・各ワークフローの最初のジョブ）: 同じ予定の鍵を持つ回のうち、
   **先に作られた回だけが動く**。鍵は、記事の枠が「枠の番号＋予定の日」、ほかは「予定の時刻」。
   一覧の API は inputs を返さないので `run-name` から読む（Worker の回「記事の枠 12 2026-10-08T20:07+09:00」、
   予備の定時の回「記事の枠（予備の定時） 7 11 * * *」）
3. 先の回が落ちた・取り消されたときも、後の回は動かない（同じ枠の記事・同じ日の動画が2本になるため）。落ちた回は自動修復（selfheal）が受け持つ
4. **手で起動した回（`scheduled_for` が空）は今までどおり動く**（API も呼ばない）
5. 判定は記事のグループ（`article-pipeline`）の外で終える。何もしない回がグループに並ぶと、待っている記事の回を取り消すため
   （`pipeline.yml`・`daily-video.yml` の concurrency をジョブへ移した）

## 配り方（運用者と行う）

1. **鍵を作る**: GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token。
   Resource owner: `yoshi4476` / Repository access: Only select repositories → `SS-AIO-LP` /
   Repository permissions: **Actions = Read and write**（ほかは付けない。Metadata: Read は自動）。
   できた鍵を本体の `.env` に `SCHEDULER_GITHUB_TOKEN=...` で入れる（コミットされない）
2. `npx wrangler login`（済んでいれば不要。`npx wrangler whoami` で確かめる）
3. `python scripts/scheduler_deploy.py` … 表を作り直して配る（`--dry-run` で配らずに束ねられるかだけ確かめられる）
4. `python scripts/scheduler_deploy.py --set-token` … `.env` の鍵で Actions を読めるか・起動できるかを GitHub で確かめてから、
   Worker の secret（`GITHUB_TOKEN`）に標準入力で入れる。`.env` に無いときだけ伏せ字の入力画面が出る。鍵は画面にもログにも出ない
5. `data/scheduler.json`（配った時刻・鍵を入れた日）と、変わっていれば `schedule.json` をコミットして push
6. 10分ほどして GitHub Actions の一覧に「記事の枠 N 2026-…+09:00」などが出るのを見る。`python scripts/sched_guard.py --watch` でも確かめられる

## cron を変えたとき

`python scripts/scheduler_build.py` を流して `schedule.json` をコミットする。Worker は5分ごとに master の表を読むので、
**配り直さなくてよい**（配り直すのは Worker のコードを変えたときだけ）。作り直し忘れは門が止める。

## 見張り

`python scripts/sched_guard.py --watch`（日次の自動修復の生存監視・週次の findings が呼ぶ）。印は `SCHEDULER_OK=`。

| 状態 | 出すもの |
|:--|:--|
| Worker からの起動が8時間ない（止まった・鍵が切れた・権限が外れた） | 要対応 |
| ワークフローごとに、最後の予定（30分の猶予のあと）を Worker が起動していない | 要対応 |
| 鍵の期限まで30日を切った | 要対応 |
| 鍵の期限のヘッダーが空（期限なしの鍵） | 情報だけ。切れたら起動の途絶えで知らせる。手で記録するなら `python scripts/scheduler_deploy.py --expiry YYYY-MM-DD` |
| まだ配っていない（`data/scheduler.json` に配った時刻も最初の起動も無い） | `unset`（何も知らせない） |

期限は Worker が GitHub の応答ヘッダー `github-authentication-token-expiration` から読んで起動の入力で渡し、
受け取った回が `data/scheduler.json` に残す（変わったときだけ。公開してよい値だけ）。
起動・失敗の記録は Cloudflare のダッシュボード（Workers & Pages → ss-aio-scheduler → Logs）に残る。

## 止め方

- 一時的に止める: ダッシュボードで Worker の定時（Triggers の Cron）を外す。GitHub の定時が予備として動き続ける
- やめる: `automation/scheduler` で `npx wrangler delete`。ワークフローの受け口は残してよい（予備の定時だけで動く）

## 手元で試す

- 門が使う試験: `node automation/scheduler/test/harness.mjs scenarios`（GitHub を偽物にして起動の流れを試す）
- `npx wrangler dev --test-scheduled` → `curl "http://localhost:8787/cdn-cgi/local/scheduled?time=<ミリ秒>"`。
  `.dev.vars` に本物の鍵を書くと**本当に起動する**ので、試すときは偽の鍵にする（`.dev.vars` はコミットされない）
