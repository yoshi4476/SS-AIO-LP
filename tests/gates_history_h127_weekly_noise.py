# -*- coding: utf-8 -*-
"""2026-10-20 週次の「要対応」に、実際には問題の無い項目が出ていた所を直す。

- 最初の接続の点検（onboard_check）: 自前で作るサイトのまとめのページは、題が配る形（「比較表から探す（AIO・LLMO運用）」）と
  違う（「比較表から探す｜料金・違い…」）。中身のある3ページを「開けますが中身が出ていません」と要対応にしていた。
- 動画の読み違い（yomi_guard）: 直した語の記録に resolved を付け忘れ、直す前の記録を14日分数えていた。
"""
import json
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_onboard_check_matches_self_built_aggregate_titles():
    print("\n■ 自前で作るまとめのページは、題の括弧書きを除いた形でも照らす")
    src = (ROOT / "scripts" / "onboard_check.py").read_text(encoding="utf-8")
    check("括弧書きを除いた題（base）で照らす", 'base = re.sub(r"（[^（）]*）$", "", title)' in src and "base in page" in src, True)
    import re
    title = "比較表から探す（AIO・LLMO運用）"
    base = re.sub(r"（[^（）]*）$", "", title).strip()
    page = "<title>比較表から探す｜料金・違い・選び方の一覧｜AI集客ラボ</title>"
    check("自前の題「比較表から探す｜…」に当たる", base in page, True)
    check("中身の無いページ（題が無い）には当たらない", base in "<title>404</title>", False)


def test_reading_issues_are_resolved_or_still_listed():
    print("\n■ 読み違いの記録: 直した語には理由がある・確かめていない語は直ったと書かない")
    rows = [json.loads(l) for l in (ROOT / "data" / "yomi_issues.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    jiin = [r for r in rows if any("自院" in d[0] for d in r.get("diff", []))]
    check("自院の記録は「次の動画で確かめる」と書く（直ったとは書かない）",
          all("確かめる" in str(r.get("resolved", "")) for r in jiin) and bool(jiin), True)
    d = json.loads((ROOT / "data" / "yomi_dict.json").read_text(encoding="utf-8"))
    check("辞書に 自院・迷う品・別料金", [d.get("自院"), d.get("迷う品"), d.get("別料金")], ["じいん", "まようしな", "べつりょうきん"])
