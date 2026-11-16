# -*- coding: utf-8 -*-
"""質問シートの答えに、下書きの印（【案】・（仮・要確認）・（推定・要確認））が残った行は、「可」でも AI に渡す前に保留にする
（2026-11-16 運用者「◯のまま残した数字を仮で入れて」「書いてくれたら合っているか確認して出す」）。
仮の年月・業種・件数で組んだ事例の文は、「要確認」の部分を AI が抜いても、残りが実際にあった事例に読める。
抜き方を AI に任せず、印が残る行は機械で止める（運用者が実際の値に直して印を消した行だけ登録する）"""
from test_gates import check


def test_draft_marks_are_held_before_ai():
    import material_sheet as M
    print("\n■ 質問シート: 下書きの印が残る行は「可」でも保留")
    base = {"no": "1", "key": "req:x:1", "item": "記事「x」", "period": "", "count": "", "ok": "可", "target": "", "question": "q"}
    rows = [dict(base, no="1", answer="【案】2026年4月に建設業の会社で、入力が月20時間から6時間になりました"),
            dict(base, no="2", answer="入力は月20時間から6時間（仮・要確認）になりました"),
            dict(base, no="3", answer="締めは翌月20日から8日（推定・要確認）になりました")]
    f, e, held = M.plan("ai-lab", rows, ask=lambda *_: (_ for _ in ()).throw(AssertionError("AI を呼んだ")))
    check("悪い例: 【案】・仮・推定の印が残る3行は、AI を呼ばずに保留", (f, e, sorted(n for n, _ in held)), ([], [], ["1", "2", "3"]))
    check("保留の理由に「下書きの印」と書く", all("下書きの印" in w for _, w in held), True)
    ok = dict(base, no="4", answer="2026年10月19日に4つのAIへ15語を聞き、60回の答えのうち3回で出典に挙がりました")
    check("良い例: 印の無い行は保留にしない（下書きの印では）", M.draft_mark(ok), "")
