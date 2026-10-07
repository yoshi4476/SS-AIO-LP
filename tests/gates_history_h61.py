# -*- coding: utf-8 -*-
"""2026-10-07 の2つの要対応から（運用者が通知で受け取った）。

- AI集客ラボの 10/7 の記事が 1/2 本: GitHub の定時が3〜8時間遅れ、17:07 の枠が翌 0:28 に書いたため、
  その記事は 10/8 の本数に数えられた。枠が予定されていた日（slot_day）を AUDIT_DAY に入れ、予定の日に数える
  （公開日 date: は公開した日のまま。daily_audit.stamp_makeup が data/makeup.json に記録する）
- 10/7 に動画が1本も上がらなかった: 通常の動画が0本の回はショートの置き場が作られず、ffmpeg が書き出せなかった。
  しかも失敗しても VIDEOS_OK=yes と出していた
"""
import sys
from datetime import datetime, timezone

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_slot_counts_for_its_scheduled_day():
    import daily_audit as D
    utc = lambda s: datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    # 17:07 JST の枠（"7 8 * * *"）が翌 0:28 JST（15:28 UTC）に始まった
    check("枠の日: 遅れて日付をまたいでも予定の日に数える", D.slot_day("7 8 * * *", utc("2026-10-07T15:28:00")), "2026-10-07")
    # 08:07 JST の枠（"7 23 * * *" = 前日 23:07 UTC）が 11:16 JST（02:16 UTC）に始まった
    check("枠の日: UTC で前日に予定された朝の枠は JST の当日", D.slot_day("7 23 * * *", utc("2026-10-07T02:16:00")), "2026-10-07")
    check("枠の日: 予定どおりに始まった回はその日", D.slot_day("7 8 * * *", utc("2026-10-07T08:07:30")), "2026-10-07")
    check("枠の日: 手で動かした回（予定が無い）は今日", D.slot_day("", utc("2026-10-07T15:28:00")), "2026-10-08")
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    check("枠の日: 記事の枠のワークフローが予定の日を AUDIT_DAY として書く工程に渡す",
          ("--slot-day" in wf, "slot_day: ${{ steps.site.outputs.slot_day }}" in wf,
           "AUDIT_DAY: ${{ needs.select.outputs.slot_day }}" in wf), (True, True, True))


def test_short_video_creates_its_folder_and_reports_failure():
    src = (ROOT / "scripts" / "article_videos.py").read_text(encoding="utf-8")
    body = src.split("def shorts(", 1)[1].split("\ndef ", 1)[0]
    check("ショート: 書き出す前に置き場を作る（通常の動画が0本の回でも）",
          body.find("out.parent.mkdir") != -1 and body.find("out.parent.mkdir") < body.find("DS.make("), True)
    check("ショート: 作れなかったら VIDEOS_OK=no にする",
          ("SHORT_FAILS.append(slug)" in body, "if SHORT_FAILS:" in src), (True, True))
