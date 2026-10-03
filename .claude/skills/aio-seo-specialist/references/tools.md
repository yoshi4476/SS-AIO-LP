# 道具の地図（どの工程に何があるか）

新しい施策の前に、同じ役目の道具が無いかここで探す。詳しい決まりは CLAUDE.md の該当節。

| 目的 | 道具 | 決まり（CLAUDE.md） |
|:--|:--|:--|
| 狙う語の食い合い | `kw_guard.py "<KW>" --site <id> [--title --h2 ...]` | Phase 1 / Phase 3 の項目3。終了コードで判定 |
| 開かないと済まない語か | `kw_intent.py "<KW>"` | Phase 1 の 4.5 |
| KW在庫の計画（課金あり） | `kw_plan.py --site <id>`（先に `--dry-run`） | Phase 1 の -1。1サイト1回400クレジットまで |
| 伸びている語の補充 | `kw_discover --append`（週次） | 定常運転の表 |
| AIで答えが出る質問形の語 | `ai_kw_research.py`（週次） | 8.9 |
| 優先度の付け直し | `kw_reorder.py --write` | 8.13 |
| 同じ語の2本を統合 | `auto_merge.py [--write] [--scaled]` | 8.1 |
| 1ページ目手前の押し上げ | `rank_up` / `rank_rescue` / `link_boost` | 8.10 |
| タイトル・説明文・見出しの書き直し | `auto_rewrite.py --kind title/desc/question/aio/stuck/fresh` | 8.6・8.13 |
| 直した題を28日後に戻すか | `rewrite_rollback.py --write` | 8.11 |
| 表示ゼロの古い記事の整理 | `retire_stale.py --write` | 8.11 |
| 内部リンクの自動追加と見直し | `auto_improve.py --write` → `auto_review.py --fix` | 8.6（言い回しの偏り・上限） |
| AIの出典に自社が入るかの実測 | `ai_cite_check.py`（月次・1サイト20語） | 8.5 の6 |
| 共起語（出典・上位が持つ語） | `cooccur.py` | 8.13 |
| タイトルの型ごとの実測CTR | `title_patterns.py` | 8.13 |
| URL検査（未登録の理由） | `index_status.py` | 8.11 |
| 量産の兆候で本数を落とす | `pace.py` | 1章 |
| 表示速度の実測 | `cwv_check.py` | 8.11 |
| 構造化データの壊れ | `rich_check.py` | 8.13 |
| 全ページのSEO監査 | `seo_audit.py` | 6章 機械品質ゲート |
| 業種・テーマ・エリアの束ね | `industry_hub.py` / `topics.py` / `area_hub.py` | 8.2.5・8.13・8.16 |
| 一次データの公開 | `data_intake.py` / `data_auto.py` | 3.0 |
| 学びの読み出し | `lessons.py --brief <site>` | 0.2 |
