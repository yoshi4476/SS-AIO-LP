# -*- coding: utf-8 -*-
"""毎週の知らせに、直近7日の問い合わせの件数を目標（週7件＝毎日1件）と先週と並べて出す
（2026-11-15 運用者「毎日問い合わせが来るようなレベルにして」）。打ち手が効いたかは、作った担当の外の物差し
（問い合わせの台帳）で毎週見る。要対応の無い週も送る。台帳には触れない（行は作って渡す）"""
from datetime import date
from pathlib import Path

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent


def test_week_line_counts_and_target():
    import lead_reconcile as LR
    import notify_slack as N
    print("\n■ 毎週の知らせ: 問い合わせの件数と目標")
    rows = [
        {"day": "2026-11-14", "sid": "corporate", "type": "無料相談", "temp": "HOT", "route": ""},
        {"day": "2026-11-13", "sid": "corporate", "type": "無料相談", "temp": "営業", "route": ""},
        {"day": "2026-11-10", "sid": "ai-lab", "type": "AIチェック", "temp": "HOT", "route": ""},
        {"day": "2026-11-09", "sid": "ai-lab", "type": "無料相談", "temp": "テスト", "route": ""},
        {"day": "2026-11-05", "sid": "corporate", "type": "無料相談", "temp": "HOT", "route": ""},
    ]
    line = LR.week_line(today=date(2026, 11, 15), rows=rows)
    check("直近7日は11/08〜11/14", "11/08〜11/14" in line, True)
    check("売り込み・テストを除き、相談と申し込みを分けて数える",
          "2件（相談のフォーム 1件・無料診断などの申し込み 1件。先週 1件）" in line, True)
    check("目標（週7件＝毎日1件）を書く", "目標は週7件＝毎日1件" in line, True)
    check("サイトごとの内訳", ("corporate 相談1・申し込み0" in line, "ai-lab 相談0・申し込み1" in line), (True, True))
    head = "🔧 週次最適化: success\n"
    check("要対応の無い週も、この行があれば送る", N.worth_sending(head + f"{N.INFO_MARK}\n{line}\n", True), True)
    f = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("週次の知らせ（findings の情報の欄）が呼ぶ", '"lead_reconcile.py --week-line"' in f, True)
