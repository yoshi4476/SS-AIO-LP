# -*- coding: utf-8 -*-
"""受付が別の行へ「再送信」として書き足した送信を、取りこぼしと数えない（2026-11-15）。

受付（contact.hub.gs の leadSave_）は、同じメールアドレスから24時間以内に来た送信を新しい行にせず、
前の行の「診断・詳細」の列に「MM/dd HH:mm 再送信(種別)」と書き足す。2026-11-13 に同じ人がコーポレートと
補助金の両方から送り、補助金の分はコーポレートの行に書き足されたが、照合は行だけを数えて
「補助金に台帳の行がありません（メールにだけ届いた可能性）」と要対応にした。

ネットワーク・GA4・台帳には触れない（全部スタブ）。
"""
import collections
from datetime import date

from test_gates import check
from gates_history_h52 import _out, _patched


def test_resend_notes_are_parsed():
    import lead_reconcile as LR
    print("\n■ 問い合わせの照合: 別の行への再送信の書き足しを読む")
    note = "当初の詳細\n11/13 12:00 再送信(無料相談) 本文\n11/14 09:30 再送信(無料診断) x"
    check("書き足しの日を読む（年は行の日付から）", LR.resend_days(date(2026, 11, 13), note),
          ["2026-11-13", "2026-11-14"])
    check("年をまたぐ書き足しは翌年にする", LR.resend_days(date(2026, 12, 31), "01/01 08:00 再送信(無料相談)"),
          ["2027-01-01"])
    check("書き足しの無い行は空", LR.resend_days(date(2026, 11, 13), "11/13 の相談。再送信はなし"), [])


def test_resend_covers_missing_row():
    import lead_reconcile as LR
    import sites as S
    sub = S.load("subsidy")
    prop = str(sub.get("ga4_property_id"))
    empty = lambda start: collections.defaultdict(collections.Counter)
    ga = lambda p, s, e: {"2026-11-13": 1} if str(p) == prop else {}
    with _patched((LR, "ledger_by_site", empty), (LR, "ga4_by_day", ga), (LR, "ACKED", {}),
                  (LR, "resends_by_day", lambda start: collections.Counter({"2026-11-13": 1}))):
        _, out = _out(LR.main, argv=["lead_reconcile.py"])
    check("同じ日に別の行へ再送信の書き足しがあれば、要対応にしない",
          ("LEADS_OK=yes" in out, any("要対応" in x and sub["name"] in x for x in out.splitlines())), (True, False))
    check("書き足しで合わせたことは結果に書く", "再送信" in out, True)
    with _patched((LR, "ledger_by_site", empty), (LR, "ga4_by_day", ga), (LR, "ACKED", {}),
                  (LR, "resends_by_day", lambda start: collections.Counter({"2026-11-12": 1}))):
        _, out = _out(LR.main, argv=["lead_reconcile.py"])
    check("書き足しが別の日なら、今までどおり要対応", "LEADS_OK=no" in out, True)


def test_zero_leads_ignores_last_month():
    """2026-11-15 の月次（途中経過）で、AI集客ラボの PDF が「CV2件（前月0件）」の「前月0件」を
    「リードを0件と書いた」と読まれ、送られずに止まった。比べる前の月・前の年の0件は誤記ではない"""
    import report_audit as RA
    print("\n■ 月次レポートの検査: 前月の0件を、今月の0件と読まない")
    ok = ["CV2件（前月0件）", "リード 3件（前年 0件）", "CV 1件（先月は0件）"]
    ng = ["リード 0件", "CV 0件（前月0件）", "CVは０件"]
    check("前月・前年・先月の0件は誤記にしない", [bool(RA.ZERO_LEADS.search(t)) for t in ok], [False] * 3)
    check("今月の0件は今までどおり誤記にする", [bool(RA.ZERO_LEADS.search(t)) for t in ng], [True] * 3)
