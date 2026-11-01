# -*- coding: utf-8 -*-
"""2026-11-01 の月次で、3サイトと合算のレポートが照合で止まり、1通も送られなかった。
1. レポートに載せるリードは台帳の相談の数なのに、GA4 の lead_capture と内訳の印のずれ（14 と 38）で止めていた
2. 合算はサイトごとの数も並ぶので、台帳で本当に0件のサイトの「リード 0件」を誤記として止めていた
3. 「0件」の検出が「リード 10件」の「0件」も拾っていた
GA4・GSC・台帳は差し替えて呼ばない。サイトは架空の zz-a・zz-b。
"""
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _group(text, ledger):
    import group_report as GR
    import lead_reconcile as LR
    import report_audit as RA
    import report_verify as RV
    cfgs = {"zz-a": {"id": "zz-a", "domain": "a.example", "ga4_property_id": "1"},
            "zz-b": {"id": "zz-b", "domain": "b.example", "ga4_property_id": "2"}}
    old = (GR.own_cfgs, RV._gsc, RV._ga_events, LR.leads, RA.pdf_text)
    GR.own_cfgs = lambda: cfgs
    RV._gsc = lambda *a, **k: {"rows": [{"impressions": 100, "clicks": 7}]}
    RV._ga_events = lambda pid, s, e: {"lead_capture": 14, "lead_form": 5, "lead_site_audit": 30}
    LR.leads = lambda sid, s, e, ga4_n=0: ({"n": ledger[sid], "source": "ledger"} if sid in ledger
                                            else {"n": None, "source": "ga4"})
    RA.pdf_text = lambda p: (text, 3)
    try:
        with tempfile.TemporaryDirectory() as d:
            return RA.audit_group(Path(d) / "r.pdf", "2026-10")
    finally:
        GR.own_cfgs, RV._gsc, RV._ga_events, LR.leads, RA.pdf_text = old


def test_group_audit_uses_ledger_leads():
    import contextlib
    import io
    print("\n■ 1. 合算の照合: 台帳で数えるリードは GA4 の印のずれで止めない／0件のサイトがあれば「リード 0件」は正しい")
    good = "表示回数 200 クリック 14 リード 3件。zz-a はリード 0件、zz-b はリード 3件"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _group(good, {"zz-a": 0, "zz-b": 3})
    out = buf.getvalue()
    check("良い例: 台帳の数なら傘と内訳のずれでは止めず、0件のサイトの「リード 0件」も止めない",
          ("AUDIT_OK=yes" in out, "不一致" in out, "「0件」と書かれています" in out), (True, False, False))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _group(good, {})
    check("悪い例: 台帳が無く GA4 の送信を載せるときは、傘と内訳のずれで止める", "不一致" in buf.getvalue(), True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _group("表示回数 200 クリック 14 リード 3件。合計はリード 0件", {"zz-a": 1, "zz-b": 2})
    check("悪い例: どのサイトも0件でないのに「リード 0件」と書けば止める", "「0件」と書かれています" in buf.getvalue(), True)


def test_landing_judge_reads_cv_and_small_samples():
    import monthly_report as M
    print("\n■ 3. 入口ページの判定: (not set) は計測外／問い合わせのある入口は良好／流入10未満は割合で判定しない")
    rows = [{"path": "(not set)", "sessions": 52, "engagement": 0.0, "cv": 0},
            {"path": "/contact", "sessions": 36, "engagement": 27.8, "cv": 5},
            {"path": "/zz-a", "sessions": 9, "engagement": 0.0, "cv": 0},
            {"path": "/zz-b", "sessions": 31, "engagement": 0.0, "cv": 0},
            {"path": "/zz-c", "sessions": 40, "engagement": 60.0, "cv": 0}]
    check("悪い例は要改善のまま、計測外・問い合わせ・小さい母数を要改善にしない",
          [M.landing_judge(x)[0] for x in rows], ["計測外", "良好", "母数不足", "要改善", "良好"])


def test_client_report_drops_operator_name_queries():
    import monthly_report as M
    import sites as S
    print("\n■ 4. お客様名義の月次: お客様のサイトが当社の社名で出た検索語は表に出さない（社名が残って発行されなかった）")
    seen = {}
    mark = S.OPERATOR_MARKS[0]

    def stop(d):
        seen["q"] = [q["q"] for q in d["queries"]]
        raise SystemExit(0)
    old = (M.fetch_real, M.fetch_demo, M.analyze, M.issuer)
    M.fetch_real = M.fetch_demo = lambda: {"queries": [{"q": f"{mark}株式会社"}, {"q": "zz 外注"}]}
    M.analyze = stop
    try:
        for op in (False, True):
            M.issuer = lambda op=op: {"operator": op}
            try:
                M._main()
            except SystemExit:
                pass
            seen[op] = seen.pop("q")
    finally:
        M.fetch_real, M.fetch_demo, M.analyze, M.issuer = old
    check("お客様名義では社名の語を外し、当社名義ではそのまま", (seen[False], len(seen[True])), (["zz 外注"], 2))


def test_zero_detector_ignores_ten():
    import report_audit as RA
    print("\n■ 2. 「0件」の検出は「10件」「20件」を拾わない")
    check("悪い例は拾い、良い例は拾わない",
          [bool(RA.ZERO_LEADS.search(t)) for t in ("リード 0件", "CVは０件", "リード 10件", "リード 1,200件", "CV 20 件")],
          [True, True, False, False, False])
