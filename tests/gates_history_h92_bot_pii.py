# -*- coding: utf-8 -*-
"""2026-10-11 運用者「すべて行って 自動ですべてやること」（セキュリティの案 7・8）。

7. ロボットよけ（Turnstile）は 2026-10-10 から記録だけ。「断る」へは、本物の相談がロボットよけを通っていることを記録で
   確かめてから、週次の turnstile_status.py --decide --apply が管制塔と AI集客ラボの受付の2か所を同時に切り替える
8. 個人情報は保存期間を過ぎたら個人の情報の列だけを消す（持っていなければ漏れない）。既存客・契約中・成約は消さない
"""
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
GAS = ROOT / "automation" / "gas"
HARNESS = ROOT / "tests" / "gas_leads_harness.js"


LAB, SUB, CORP = "AI集客ラボ (ai.7senses.co.jp)", "AI導入補助金サポート (lp.7senses.co.jp)", "コーポレート (corp.7senses.co.jp)"
SRV, PAGE = "サーバーで確認", "ページから直接"


def _bot(at, res, site, route, probe=False, act="受付"):
    return (at, res, probe, site, route, act)


def test_turnstile_switches_only_after_real_leads_passed():
    print("\n■ ロボットよけ: 本物の相談が通っていることを、断る対象の経路ごとに記録で確かめてから「断る」に切り替える")
    import turnstile_status as T
    now = datetime(2026, 11, 1, 12, 0, tzinfo=T.JST)
    d0 = now - timedelta(days=20)
    at = lambda days, mins=0: d0 + timedelta(days=days, minutes=mins)
    # AI集客ラボ（受付が確かめる）2件・補助金とコーポレート（ページから直接）2件。記録は相談の1分後
    bots = [_bot(at(0), "ok", LAB, SRV)] + [_bot(at(d, 1), "ok", s, r) for d, s, r in
                                             ((2, LAB, SRV), (5, LAB, SRV), (7, SUB, PAGE), (9, CORP, PAGE))]
    leads = [(at(d), "HOT", s, "") for d, s in ((2, LAB), (5, LAB), (7, SUB), (9, CORP))] + [(at(3), "営業", SUB, "")]
    check("切り替える: 14日以上の記録・両方の経路で本物の相談が2件ずつ ok（売り込みは数えない）", T.decide(bots, leads, now)[0], "switch")
    # 別の社・断る対象でない経路の相談（別事業のサイト・AI紹介チェック）は、記録が無くても数えない
    other = leads + [(at(10), "WARM", "別事業 (partner.example.jp)", ""), (at(11), "COOL", LAB, "form_type: \"AI紹介チェック（診断）\"")]
    check("数えない: 断る対象でない社の相談・AI紹介チェックの行（記録が無くても待たない）", T.decide(bots, other, now)[0], "switch")
    bad = leads + [(at(12), "HOT", SUB, "")]
    near_other = bots + [_bot(at(12, 0.2), "none", SUB, PAGE), _bot(at(12, 1), "ok", LAB, SRV), _bot(at(12, 2), "ok", SUB, PAGE)]
    check("止める: 本物の相談の一番近い記録が none（近くに別の社・別の送信の ok があっても見逃さない）",
          T.decide(near_other, bad, now)[0], "hold")
    check("止める: 以前に断った送信がある（断られた相談は台帳に残らない）",
          T.decide(bots + [_bot(at(13), "none", SUB, PAGE, act="断った")], leads, now)[0], "hold")
    check("判断を再開した時刻より前の記録は見ない（再開から14日たつまで待つ）",
          T.decide(bots + [_bot(at(13), "none", SUB, PAGE, act="断った")], leads, now, since=at(14))[0], "wait")
    only_lab = [b for b in bots if b[3] == LAB]
    check("待つ: 片方の経路しか相談が無い・記録が14日に満たない・記録の無い相談・疎通確認だけ",
          [T.decide(only_lab, [x for x in leads if x[2] == LAB], now)[0], T.decide(bots, leads, at(5))[0],
           T.decide(bots, leads + [(at(15), "HOT", CORP, "")], now)[0],
           T.decide([_bot(d0, "ok", LAB, SRV, probe=True)], leads, now)[0]],
          ["wait", "wait", "wait", "wait"])
    js = (ROOT / "functions" / "_turnstile.js").read_text(encoding="utf-8")
    dec = (ROOT / "functions" / "_turnstile_enforce.js").read_text(encoding="utf-8")
    check("AI集客ラボの受付は判断のファイルを読む（手で書かない）",
          ('import { DECIDED } from "./_turnstile_enforce.js";' in js, "export const ENFORCE = DECIDED;" in js,
           bool(re.search(r"export const DECIDED = \{ lead: (true|false), subscribe: (true|false) \};", dec))),
          (True, True, True))
    gs = (GAS / "contact.hub.gs").read_text(encoding="utf-8")
    hub = (GAS / "hub.gs").read_text(encoding="utf-8")
    check("管制塔は Script Properties の TURNSTILE_ENFORCE でも断れる（断る判定は turnstileEnforce_ を通す）",
          ("const refuse = turnstileEnforce_()" in gs, "TURNSTILE_ENFORCE &&" in gs), (True, False))
    m = re.search(r"const AGENT_POSTS = \{(.*?)\};", hub, re.S)
    check("切り替え・個人情報の消去は AI 用の合言葉では通らない",
          (bool(m), [a for a in ("bot_enforce", "pii_retention", "bot_status") if m and f"{a}: true" in m.group(1)]), (True, []))
    fd = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次が判断して当て、切り替えた記録をコミットし、その場で AI集客ラボの受付へ配信する",
          ("turnstile_status.py --decide --apply" in fd, "functions/_turnstile_enforce.js; do" in wk,
           "TURNSTILE_SWITCHED" in wk), (True, True, True))


def _decide_out(status, rows, file_on):
    """run_decide を、管制塔と台帳を作り物に差し替えて動かす（何も書かない・送らない。apply しない）"""
    import contextlib
    import io
    import types
    import turnstile_status as T
    keep = (T._status, T.decided_on, sys.modules.get("hub_sheets"))
    T._status = lambda days: status
    T.decided_on = lambda: file_on
    sys.modules["hub_sheets"] = types.SimpleNamespace(rows=lambda tab, n: rows)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            T.run_decide(False)
    finally:
        T._status, T.decided_on = keep[0], keep[1]
        if keep[2] is None:
            sys.modules.pop("hub_sheets", None)
        else:
            sys.modules["hub_sheets"] = keep[2]
    return buf.getvalue()


def test_turnstile_marks_reach_the_weekly_findings():
    print("\n■ ロボットよけ: 手で止めた印が週次の判断より強く、hold・片側だけ・読めないは週次の知らせに載る")
    import findings as F
    rec = lambda iso, res, site, route, act="受付": [iso, site, route, "contact", res, "", "", "", act]
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    base = {"ok": True, "enforce": False, "manual_off": "", "resumed_at": "", "counts": {}, "recent": [rec(old, "ok", LAB, SRV)]}
    off = _decide_out(dict(base, manual_off="2026-10-11T00:00:00Z"), [], False)
    check("手で止めた印がある間は判断しない（off・要対応にしない）",
          ("BOT_ENFORCE=off" in off, F.judge(off, 0)), (True, "問題なし"))
    half = _decide_out(dict(base, enforce=True), [], False)
    check("片側だけ断っている（管制塔は断る・受付は記録だけ）は要対応", F.judge(half, 0), "要対応")
    held = _decide_out(dict(base, recent=base["recent"] + [rec(old, "none", SUB, PAGE, "断った")]), [], False)
    check("断った記録が残っている（hold）は要対応", ("BOT_ENFORCE=hold" in held, F.judge(held, 0)), (True, "要対応"))
    unk = _decide_out({"ok": False, "error": "x"}, [], False)
    check("記録を読めないときは「動かせず」", F.judge(unk, 0), "動かせず")
    hub = (GAS / "contact.hub.gs").read_text(encoding="utf-8")
    ts = (ROOT / "scripts" / "turnstile_status.py").read_text(encoding="utf-8")
    check("--off は手で止めた印を残し、--resume で外す",
          ('"manual": True' in ts, '"resume": True' in ts, "TURNSTILE_MANUAL_OFF" in hub), (True, True, True))


def test_pii_is_erased_after_its_period():
    print("\n■ 個人情報の保存期間: 期限を過ぎた行は個人の情報だけを消し、取引のある行は残す")
    fd = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("週次が個人情報の保存期間を当てる", "pii_retention.py --apply" in fd, True)
    node = shutil.which("node")
    if not node:
        print("  WARN  node が無いため受付の動きは確かめられません")
        return
    now = datetime.now(timezone.utc)
    ago = lambda d: (now - timedelta(days=d)).isoformat()
    row = lambda at, temp, st: [at, "AI集客ラボ (ai.7senses.co.jp)", "お問い合わせ", "例株式会社", "山田", "", "a@example.com",
                                "06-0000-0000", "相談です", "詳細", "", "/contact", temp, st]
    rows = [row(ago(1500), "HOT", "対応済み"), row(ago(1500), "HOT", "成約"), row(ago(700), "WARM", "対応済み"),
            row(ago(700), "営業", "対応不要"), row(ago(30), "テスト", "対応不要")]
    def run(dry):
        r = subprocess.run([node, str(HARNESS), str(GAS / "hub.gs"), str(GAS / "contact.hub.gs")],
                           input=json.dumps({"rows": rows, "calls": [["piiRetention_", {"dry": dry}]]}),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if r.returncode:
            raise RuntimeError(f"受付を動かせませんでした: {(r.stderr or r.stdout)[-300:]}")
        return json.loads(r.stdout.strip().splitlines()[-1])
    dry = run(True)
    check("見るだけ（dry）は数えるだけで消さない",
          ((dry["calls"][0]["lead"], dry["calls"][0]["noise"]), [x[6] for x in dry["rows"]].count("a@example.com")),
          ((1, 1), 5))
    got = run(False)["rows"]
    erased = [bool(str(x[8]).startswith("（保存期間を過ぎたため")) and x[6] == "" and x[4] == "" and x[7] == "" for x in got]
    check("消すのは4年前の相談と2年前の売り込みだけ（成約・3年以内の相談・最近のテストは残す）",
          erased, [True, False, False, True, False])
    check("消した行も日付・会社名・温度・対応状況は残る（件数の集計は変わらない）",
          [(bool(x[0]), x[3], x[12], x[13]) for x in got if str(x[8]).startswith("（保存期間")],
          [(True, "例株式会社", "HOT", "対応済み"), (True, "例株式会社", "営業", "対応不要")])
