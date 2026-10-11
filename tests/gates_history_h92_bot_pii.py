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


def test_turnstile_switches_only_after_real_leads_passed():
    print("\n■ ロボットよけ: 本物の相談が通っていることを記録で確かめてから「断る」に切り替える")
    import turnstile_status as T
    now = datetime(2026, 11, 1, 12, 0, tzinfo=T.JST)
    d0 = now - timedelta(days=20)
    bots = [(d0, "ok", False)] + [(d0 + timedelta(days=i, minutes=1), "ok", False) for i in (2, 5, 9)]
    leads = [(d0 + timedelta(days=i), "相談") for i in (2, 5, 9)] + [(d0 + timedelta(days=3), "営業")]
    check("切り替える: 14日以上の記録・本物の相談3件がすべて ok（売り込みは数えない）", T.decide(bots, leads, now)[0], "switch")
    check("止める: 本物の相談がロボットよけを通っていない（断っていたら落としていた）",
          T.decide(bots + [(d0 + timedelta(days=12, minutes=1), "none", False)],
                   leads + [(d0 + timedelta(days=12), "相談")], now)[0], "hold")
    check("待つ: 記録が14日に満たない・相談が3件に満たない・記録の無い相談がある・疎通確認だけ",
          [T.decide(bots, leads, d0 + timedelta(days=5))[0], T.decide(bots, leads[:2], now)[0],
           T.decide(bots, leads + [(d0 + timedelta(days=15), "相談")], now)[0],
           T.decide([(d0, "ok", True)], leads, now)[0]],
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
    m = re.search(r"const AGENT_ACTIONS = \{(.*?)\};", hub, re.S)
    check("切り替え・個人情報の消去は AI 用の合言葉では通らない",
          [a for a in ("bot_enforce", "pii_retention", "bot_status") if m and f"{a}: true" in m.group(1)], [])
    fd = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次が判断して当て、切り替えた記録をコミットして配信する",
          ("turnstile_status.py --decide --apply" in fd, "functions/_turnstile_enforce.js; do" in wk), (True, True))


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
