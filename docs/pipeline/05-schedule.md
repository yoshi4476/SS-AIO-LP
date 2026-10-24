## 5. 自動スケジュール定義

| スケジュール | 実行時刻(JST) | 内容 |
|:--|:--|:--|
| Article Pipeline | 1日20枠 | Phase 1〜7。**1社2本/日・最大10社**。枠の番号をサイト数で割った余りでサイトを選ぶ |
| 同日救済（Rescue） | 毎日 21:30（予定。GitHub の遅れで翌1〜6時に始まることが多い） | 本数・品質・領域・KW供給を監査し、不足を書き足す。その日の最初の枠（08:07）より前に始まった回は前日を数える（`daily_audit.py --rescue-day`）。書き足した記事の公開日は書いた日のまま、前日の分として `data/makeup.json` に残す |
| Daily KPI Report | 毎日 10:13（`daily-kpi.yml`。記事の枠とは別） | 前日分のKPIレポート・AIO計測・AI参照を管制塔へ（`daily_kpi.py --send --once`）。送った日を記録して同じ日は2回送らない。取りこぼした日は次の回が7日前まで埋める |
| Weekly Optimize | 月曜 10:23 | カニバリ検出・リライト・内部リンク最適化・AIO監査・**自動修正と見直し（8.6）**・新規KW提案 |
| Monthly AI Citation Check | 毎月1日 11:00 | AI引用スポットチェック |

### Morning/Afternoon Pipeline 実行フロー

1. kpi_feedback.md を読み込む（前日の成功/失敗パターンを反映）
2. Phase 1〜7 を順次実行
3. 実行ログをエラーログタブに記録
4. 完了通知

### Daily KPI Report 実行フロー

1. GA4 で前日のセッション・PV・CV（lead_capture）・AI参照元と着地ページを取る
2. GSC で3日前（確定済み）の表示回数・クリック・CTR・平均順位を取る
3. AI Overview の推定（ai_citation_check のCTR歪み）と引用の実測（ai_cite_check）を添える
4. 「KPIレポート」「AIO計測」「AI参照」タブとダッシュボードに記録し、送った日を `data/kpi_sent.json` に残す（キャッシュで持ち越す）
5. 失敗したときだけ通知する。kpi_feedback.md（成功/失敗パターン）は記事の各枠と同日救済が `local_kpi.py` で更新する

### Monthly AI Citation Check 実行フロー

1. 「KW戦略」タブから公開済み記事の主要KW上位20個を取得
2. 各KWのAI検索引用状況をスポットチェック（AI Overview引用リンク / ChatGPT・Perplexity回答出典）
3. 結果を `data/ai_citations/YYYY-MM.json` と「AIO計測」タブI列に記録
4. 「順位は高いのに引用されない」記事をリライト優先度リストに追加

---

