# -*- coding: utf-8 -*-
"""2026-11-01 材料の質問シートの答えの多くが「記録はありません。不足しているのは対象案件の全件一覧・問題の発生件数・
理由別内訳です」だった。主題ごとに聞くのをやめ、1案件1行の案件台帳を機械が数える（case_ledger.py）。
1. 数字は台帳の行から数えるだけ。割合は母数10以上、2〜9社は各社の値、1社は「1社では」
2. 「可」の行だけ・「例」の行は読まない。数字の欠けた行は登録せず直してほしい行として返す
3. 同じ台帳を入れ直すと同じ id を上書きする（積み増さない）
4. intake/ に入れると、隠しタブで案件台帳と見分ける
社は架空の zz-*（自社扱い）。
"""
import json
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _case(no, kind, metric="", b="", a="", unit="", ok="可", start="2026-04"):
    return {"案件番号（社名は書かない）": no, "業種": kind, "規模（従業員数）": "", "地域": "", "業務の種類": "記帳代行",
            "開始月": start, "終了月（続いていれば空）": "", "測った指標": metric, "前": b, "後": a, "単位": unit,
            "前と後を測った期間": "", "記事に出してよいか": ok}


def _event(no, k, tot, why, act="1件ずつ確かめる", res="翌月0件"):
    return {"案件番号": no, "起きた月": "2026-06", "業務の種類": "記帳代行", "起きたこと": "仕訳の誤り", "件数": k,
            "対象の総件数": tot, "理由": why, "決めた対応": act, "結果": res, "記事に出してよいか": "可"}


def test_counts_only_from_rows():
    import case_ledger as CL
    print("\n■ 1. 案件台帳: 数字は行から数えるだけ・割合は母数10以上・2〜9社は各社の値")
    one = [_case("A1", "製造業", "月の作業時間", 20, 6, "時間")]
    f, e, bad = CL.count("zz-own", one, [], today="2026-11-01")
    m = [x["claim"] for x in f if "月の作業時間" in x["claim"]]
    check("1社だけなら「1社では前→後」と書き、割合も中央値も出さない",
          (len(m), "1社" in m[0], "20時間から6時間" in m[0], "%" in m[0], "中央値" in m[0]), (1, True, True, False, False))
    two = one + [_case("A2", "小売業", "月の作業時間", 15, 9, "時間")]
    f, _, _ = CL.count("zz-own", two, [], today="2026-11-01")
    m = next(x["claim"] for x in f if "月の作業時間" in x["claim"])
    check("2社なら各社の値を並べ、中央値は出さない", ("2社" in m, "20→6" in m, "中央値" in m), (True, True, False))
    ten = [_case(f"A{i}", "製造業", "月の作業時間", 20, 6 if i < 7 else 25, "時間") for i in range(10)]
    f, _, _ = CL.count("zz-own", ten, [], today="2026-11-01")
    m = next(x["claim"] for x in f if "月の作業時間" in x["claim"])
    check("10社なら中央値と割合（減った7社＝70%）", ("中央値は20時間から6時間" in m, "70%" in m, "減った7社" in m),
          (True, True, True))
    w = next(x for x in f if x["topic"] == ["記帳代行"])
    check("担当した社の数と期間は案件番号の重なりを数えない", ("10社" in w["claim"], w["denominator"]), (True, 10))
    ev = [_event("A1", 3, 120, "科目の読み違い"), _event("A2", 1, 80, "証憑の欠け")]
    f, e, _ = CL.count("zz-own", [], ev, today="2026-11-01")
    m = next(x["claim"] for x in f if "仕訳の誤り" in x["claim"])
    check("問題は「対象N件のうちk件（%）」と理由の内訳、判断の行は体験に",
          ("対象200件のうち" in m, "4件（2.0%）" in m, "科目の読み違い1件" in m, len(e)), (True, True, True, 2))
    f, _, _ = CL.count("zz-own", [], [_event("A1", 2, 6, "x")], today="2026-11-01")
    check("母数10未満の問題は割合を出さない", "%" in f[0]["claim"], False)


def test_reads_only_allowed_rows_and_overwrites():
    import case_ledger as CL
    import private_store as P
    import sites as S
    print("\n■ 2. 「可」の行だけ・例は読まない・欠けた行は直してほしい行・入れ直しは同じ id を上書き・intake で見分ける")
    old = (S.load, S.is_client, P.is_client, CL.OWN_FACTS, CL.OWN_EXPS)
    with tempfile.TemporaryDirectory() as td:
        try:
            S.load = lambda s: {"name": "ZZ商店"}
            S.is_client = P.is_client = lambda s: False
            CL.OWN_FACTS, CL.OWN_EXPS = Path(td) / "f.json", Path(td) / "e.json"
            CL.OWN_FACTS.write_text('{"facts": [{"id": "keep", "claim": "x"}]}', encoding="utf-8")
            CL.OWN_EXPS.write_text('{"experiences": []}', encoding="utf-8")
            src = CL.make("zz-own", td, today="2026-11-01")
            import intake_watch as W
            check("intake_watch は隠しタブで案件台帳と見分ける", W.kind(src), "case")
            from openpyxl import load_workbook
            wb = load_workbook(src)
            ws = wb["案件"]
            ws.append(["A1", "製造業", "", "", "記帳代行", "2026-04", "", "月の作業時間", 20, 6, "時間", "", "可"])
            ws.append(["A2", "小売業", "", "", "記帳代行", "2026-05", "", "月の作業時間", 18, "", "時間", "", "可"])
            ws.append(["A3", "建設業", "", "", "記帳代行", "2026-05", "", "", "", "", "", "", "不可"])
            wb.save(src)
            site, cases, events, skipped = CL.read(src)
            f, e, bad = CL.count(site, cases, events, today="2026-11-01")
            check("例と不可の行は読まず、前後の欠けた行は登録しないで直してほしい行に",
                  (site, len(cases), skipped, len(bad), "2社" in f[0]["claim"]), ("zz-own", 2, 1, 1, True))
            CL.apply(src, True, today="2026-11-01")
            n1 = len(json.loads(CL.OWN_FACTS.read_text(encoding="utf-8"))["facts"])
            CL.apply(src, True, today="2026-11-02")
            fs = json.loads(CL.OWN_FACTS.read_text(encoding="utf-8"))["facts"]
            check("入れ直しても積み増さず、元からある一次情報は残す",
                  (len(fs) == n1, any(x["id"] == "keep" for x in fs), n1), (True, True, 3))
        finally:
            S.load, S.is_client, P.is_client, CL.OWN_FACTS, CL.OWN_EXPS = old
