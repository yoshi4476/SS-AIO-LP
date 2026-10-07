# -*- coding: utf-8 -*-
"""問い合わせフォームの離脱を項目ごとに数え、直し方の候補を出す（2026-10-07 運用者の依頼）。

GA4 には触れず、偽の行で確かめる:

  - 入力開始が30件未満の月は「判定前」で、項目を挙げない（候補も出さない）
  - フォームの種類 × 最後に触った項目で数える。種類の無い form_start（GA4 の自動計測・記事の入力欄）は除く
  - 送信は lead_reconcile.is_lead の数え方（form_submit と lead_capture を足さない・/contact 以外の form_submit は数えない）
  - 割合は母数10以上のときだけ
  - 提案は月次レポートの節と、report_actions の「人の手が要るもの」に出る（RUNNERS には入れない）
  - フォーム（site/ の HTML と site.js）を書き換えない
  - 検算: 項目別の行を日×出来事に足し戻し、次元なしの件数と比べる（保持期間の外は分けて出す）
"""
import hashlib
import sys
import types
from datetime import date

from test_gates import check, ROOT


def _ym():
    import funnel as FN
    return FN.last_month()


def _rows(start_typed=40):
    d = _ym().replace("-", "") + "05"
    return [
        (d, "form_start", "contact", "", "/contact/", start_typed),
        (d, "form_start", "", "", "/aio/aio-checker/", 5),               # 種類の無い開始（数えない）
        (d, "form_abandon", "contact", "company", "/contact/", 12),
        (d, "form_abandon", "contact", "message", "/contact/", 4),
        (d, "form_abandon", "contact", "name", "/contact/", 2),
        (d, "form_abandon", "contact", "(not set)", "/contact/", 1),
        (d, "form_submit", "contact", "", "/contact/", 3),                # 同じ送信で両方飛ぶ → 足さない
        (d, "lead_capture", "contact", "", "/contact/", 3),
        (d, "form_submit", "contact", "", "/", 1),                         # トップの診断入力は送信に数えない
        (d, "generate_lead", "", "", "/contact/", 1),
    ]


def _site_hashes():
    files = [ROOT / "site" / "js" / "site.js"] + [p for p in (ROOT / "site").rglob("index.html")
                                                    if "form-panel" in p.read_text(encoding="utf-8", errors="ignore")]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}


def test_form_fields_are_counted_and_judged():
    import funnel as FN
    s = FN.summarize_forms(_rows())[_ym().replace("-", "")]
    t = s["types"]["contact"]
    check("フォームの項目: 種類の無い form_start は除き、別に数える", (t["start"], s["untyped_start"]), (40, 5))
    check("フォームの項目: 離脱を最後に触った項目ごとに数える",
          (t["abandon"], dict(t["fields"])), (19, {"company": 12, "message": 4, "name": 2, "(不明)": 1}))
    check("フォームの項目: 送信は is_lead の数え方（form_submit と lead_capture を足さない）", t["sent"], 3)
    check("フォームの項目: 月の送信の合計は lead_reconcile.count_rows と同じ", s["sent_total"], 3)

    j = FN.judge_form(t)
    check("フォームの項目: 入力開始30件以上なら判定する", j["status"], "判定済み")
    check("フォームの項目: 挙げるのは離脱3件以上・離脱の2割以上の項目",
          [h["field"] for h in j["hot"]], ["company", "message"])
    check("フォームの項目: 会社名の候補に「任意にする」「届いた後に聞く」",
          any("任意" in x for x in j["hot"][0]["ideas"]) and any("後に聞く" in x for x in j["hot"][0]["ideas"]), True)
    check("フォームの項目: 割合は母数10以上のときだけ", (FN.rate(3, 9), FN.rate(3, 10)), ("—", "30%"))

    few = FN.judge_form(FN.summarize_forms(_rows(29))[_ym().replace("-", "")]["types"]["contact"])
    check("フォームの項目: 入力開始30件未満は判定前で、項目を挙げない", (few["status"], few["hot"]), ("判定前", []))


def test_form_report_and_actions_show_ideas_without_touching_forms():
    import funnel as FN
    before = _site_hashes()
    FN._FORM_CACHE.clear()
    h = FN.form_report_html("1", _ym(), rows_fn=lambda p, s, e: _rows())
    check("月次レポートの節: 項目と候補を出し、フォームは自動では変えないと書く",
          "会社名" in h and "任意にする" in h and "自動では変えていません" in h, True)
    FN._FORM_CACHE.clear()
    h2 = FN.form_report_html("1", _ym(), rows_fn=lambda p, s, e: _rows(29))
    check("月次レポートの節: 母数不足の月は判定前で、候補を出さない", "判定前" in h2 and "候補</th>" not in h2, True)
    FN._FORM_CACHE.clear()
    h3 = FN.form_report_html("1", _ym(), rows_fn=lambda p, s, e: [(r[0], r[1], "<x>" if r[2] else r[2], *r[3:])
                                                               for r in _rows()])
    check("月次レポートの節: GA4 の値はエスケープする", "<x>" not in h3 and "&lt;x&gt;" in h3, True)
    mr = (ROOT / "scripts" / "monthly_report.py").read_text(encoding="utf-8")
    check("月次レポート: 節を差し込む", "_fn.form_report_html(ga4_property(), ym, THROUGH)" in mr
          and "{form_pages}" in mr, True)

    import report_actions as RA
    fake_sp = types.SimpleNamespace(plan=lambda sid: [])
    fake_sd = types.SimpleNamespace(diagnose=lambda sid: {"bands": {}, "funnel": [("x", 0), ("y", 0)], "stock": None})
    saved = {k: sys.modules.get(k) for k in ("structure_plan", "site_diagnosis")}
    old_sites, old_rows = RA._sites, FN.form_rows
    sys.modules["structure_plan"], sys.modules["site_diagnosis"] = fake_sp, fake_sd
    RA._sites = lambda only="": {"t": {"ga4_property_id": "1"}}
    try:
        FN._FORM_CACHE.clear()
        FN.form_rows = lambda p, s, e: _rows()
        items = [i for i in RA.derive(["t"]) if i["kind"] == "form"]
        FN._FORM_CACHE.clear()
        FN.form_rows = lambda p, s, e: _rows(29)
        none = [i for i in RA.derive(["t"]) if i["kind"] == "form"]

        def boom(p, s, e):
            raise RuntimeError("Field customEvent:last_field is not a valid dimension")
        FN._FORM_CACHE.clear()
        FN.form_rows = boom
        meas = [i for i in RA.derive(["t"]) if i["kind"] == "measure"]
    finally:
        RA._sites, FN.form_rows = old_sites, old_rows
        FN._FORM_CACHE.clear()
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    check("report_actions: 離脱の多い項目を人の手が要るものとして出す",
          [(i["auto"], "会社名" in i["finding"] or "相談内容" in i["finding"]) for i in items], [(False, True)] * 2)
    check("report_actions: 候補を添える", "任意にする" in items[0]["action"], True)
    check("report_actions: フォームの種類は人の項目（メールに載る）で、機械の道具は無い",
          "form" in RA.HUMAN and "form" not in RA.RUNNERS, True)
    check("report_actions: 母数不足の月は載せない", none, [])
    check("report_actions: カスタム定義が無ければ計測の項目にする", len(meas), 1)

    check("フォーム（site/ の HTML と site.js）を書き換えない", _site_hashes(), before)
    src = (ROOT / "scripts" / "funnel.py").read_text(encoding="utf-8")
    sec = src[src.index("FORM_EVENTS ="):src.index("def main():")]
    check("funnel.py のフォームの節はファイルに書かない", any(w in sec for w in ("write_text", "write_bytes", "open(")), False)


def test_form_verify_splits_retention():
    import funnel as FN
    rows = [("20261006", "form_start", "contact", "", "/contact", 1),
            ("20260803", "form_start", "(not set)", "(not set)", "/contact", 1)]
    tot = {("20261006", "form_start"): 1, ("20260803", "form_start"): 3, ("20260801", "form_start"): 2}
    bad, old = FN.verify_forms(rows, tot, date(2026, 8, 7))
    check("検算: 保持期間内は一致", bad, [])
    check("検算: 保持期間の外の食い違いは分けて出す", len(old), 2)
    bad, _ = FN.verify_forms(rows, {("20261006", "form_start"): 2}, date(2026, 8, 7))
    check("検算: 保持期間内の食い違いは不一致として出す", len(bad), 1)


def test_form_field_ideas_match_the_field():
    """2026-10-07 の見直しで再現: email_address / mail_address が住所（address）の候補になっていた"""
    import funnel as FN
    check("項目の候補: メールの項目名（email_address・mail_address・your-email）はメールの候補",
          [FN.field_ideas(f)[0] for f in ("email_address", "mail_address", "your-email", "email")],
          ["入力例を添える"] * 4)
    import os
    import subprocess
    import sys
    code = ("import sys; sys.path[:0] = [r'%s', r'%s']; import funnel as FN, gates_history_h42 as H; "
            "FN.print_forms({'t': {'name': 't', 'ga4_property_id': '1'}}, 2, "
            "rows_fn=lambda p, s, e: H._rows(5), totals_fn=lambda p, s, e: {})") % (ROOT / "scripts", ROOT / "tests")
    env = {**os.environ, "PYTHONIOENCODING": "cp932", "PYTHONUTF8": "0"}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env, cwd=ROOT)
    check("--forms: 出力が cp932（手元の Windows でファイル・パイプへ流す）でも「—」で落ちない",
          (r.returncode, b"UnicodeEncodeError" in r.stderr), (0, False))
    check("項目の候補: 住所・電話はそれぞれの候補のまま",
          (FN.field_ideas("address")[1], FN.field_ideas("tel")[1]),
          ("郵便番号から自動で入れる", "連絡方法でメールを選んだ人には聞かない"))
