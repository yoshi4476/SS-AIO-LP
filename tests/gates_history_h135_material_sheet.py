# -*- coding: utf-8 -*-
"""2026-10-21 運用者「採点で材料が足りないと出た記事の質問シートを、社ごとに機械で作る」「コンフレックス以外も」。
材料の依頼（material_requests.json）と、採点で何度も足りないと言われる材料の決まった質問から、社ごとの質問シートを作る。
返ってきたシートは intake/ に置けば intake_watch.py が拾い、答えに無い数字・既存と食い違う答え・掲載不可・お客様の声を
登録せずに保留にする（material_sheet.py）。AI は差し替えて呼ばない。
"""
import json
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _fill(path, answers):
    from openpyxl import load_workbook
    wb = load_workbook(path)
    ws = wb["質問"]
    for row in ws.iter_rows(min_row=5):
        no = str(row[0].value or "")
        if no in answers:
            ans, ok = answers[no]
            row[4].value = ans
            row[5].value = "2024年1月〜2026年9月"
            row[7].value = ok
    wb.save(path)


def test_make_sheet_per_site_with_requests_and_template():
    import material_sheet as MS
    print("\n■ 質問シート: 依頼の質問を先に、決まった質問（事例カード・失敗の件数・判断の根拠…）を後に。隠しタブで見分ける")
    reqs = {"zz-slug": {"keyword": "庭木 剪定 業者", "since": "2026-10-20",
                        "questions": ["実際にあったことを2〜3件", "全体で何件か", "1件の事例"], "scorer": ["母数が無い"]}}
    old = MS.requests_of, MS.display_name
    MS.requests_of, MS.display_name = (lambda s: reqs), (lambda s: "テストの社")
    try:
        with tempfile.TemporaryDirectory() as d:
            p, n = MS.make("ai-lab", d, today="2026-10-21")
            from openpyxl import load_workbook
            wb = load_workbook(p)
            meta = {str(r[0]): str(r[1]) for r in wb["材料の質問"].iter_rows(values_only=True)}
            items = [str(r[1]) for r in wb["質問"].iter_rows(min_row=5, values_only=True) if r[0]]
            check("依頼の3問＋決まった質問（自社は費用の実例を聞かない）",
                  (n, items[0].startswith("記事「庭木"), "事例カード" in items, "費用の実例" in items), (10, True, True, False))
            check("隠しタブに社と各問の印", (meta.get("site"), meta.get("1"), wb["材料の質問"].sheet_state), ("ai-lab", "req:zz-slug:0", "hidden"))
            import intake_watch as IW
            check("intake_watch が材料の質問シートと見分ける", IW.kind(p), "material")
    finally:
        MS.requests_of, MS.display_name = old


def test_apply_holds_invented_numbers_conflicts_and_voices():
    import material_sheet as MS
    print("\n■ 登録: 答えに無い数字・既存と食い違う答え・掲載不可・お客様の声は登録しない")
    old = MS.requests_of, MS.display_name, MS.existing
    MS.requests_of, MS.display_name = (lambda s: {}), (lambda s: "テストの社")
    MS.existing = lambda s: ([("zz-hiyou", "代表的な12件の費用は80万〜800万円でした")], [])
    try:
        with tempfile.TemporaryDirectory() as d:
            p, _ = MS.make("ai-lab", d, today="2026-10-21")
            # 1=事例カード（正しい）、2=事例カード（AI が数字を作る）、3=失敗（既存と食い違い）、4=不可、7=お客様の声（自社は費用の実例を聞かないので7問目）
            _fill(p, {"1": ("2025年3月に卸売の会社で入力が月40時間から8時間になった", "可"),
                      "2": ("2024年に飲食店で予約が増えた", "可"),
                      "3": ("代表的な12件の費用は80万〜650万円", "可"),
                      "4": ("社外秘の件", "不可"),
                      "7": ("「とても良かった」と言われた", "可")})
            reply = json.dumps({"facts": [
                {"no": "1", "claim": "2025年3月に卸売の会社で、入力が月40時間から8時間になりました", "topic": ["卸売"]},
                {"no": "2", "claim": "2024年に飲食店で予約が月20件から35件に増えました", "topic": ["飲食"]}],
                "experiences": [], "conflicts": [{"no": "3", "existing": "zz-hiyou", "why": "上限が800万円と650万円で違う"}]},
                ensure_ascii=False)
            site, answers = MS.read(p)
            f, e, held = MS.plan(site, answers, ask=lambda prompt: reply)
            reasons = " ".join(w for _, w in held)
            check("答えのとおりの文だけ登録する", [x["no"] for x in f], ["1"])
            check("答えに無い数字（20・35）を入れた文は保留", "答えに無い数字" in reasons and "20" in reasons, True)
            check("既存と食い違う答えは保留（記録の id を添える）", "zz-hiyou" in reasons, True)
            check("掲載不可とお客様の声は登録しない", sorted(n for n, w in held if "記事に出さない" in w), ["4", "7"])
            ok, msg = MS.apply(p, False, ask=lambda prompt: reply)
            check("--write なしは書かない（見るだけ）", (ok, "--write" in msg), (True, True))
    finally:
        MS.requests_of, MS.display_name, MS.existing = old


def test_measure_claim_needs_past_tense_and_ci_skip():
    print("\n■ 施策の前と後: やったことは「〜した」で書かせる・CI では質問シートを作らない")
    src = (ROOT / "scripts" / "material_sheet.py").read_text(encoding="utf-8")
    check("「〜した」の形でなければ止める・CI では作らない",
          ('if not a.what.endswith("た"):' in src, 'MATERIAL_SHEET=skip' in src), (True, True))
    iw = (ROOT / "scripts" / "intake_watch.py").read_text(encoding="utf-8")
    check("intake_watch --apply の後に、依頼の残る社の質問シートを作り直す", iw.count("MS.make(s, MS.Path.home() / \"Desktop\")"), 2)
