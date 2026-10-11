# -*- coding: utf-8 -*-
"""2026-10-11 運用者「全部バグはないか」の点検で見つけた、管制塔の受付の穴（動きで確かめる）。

- AI 用の合言葉で、読む操作の名前を POST で送る・toString などの元の名前・配列の名前を送ると、受付に該当が無いため
  フォーム（問い合わせの台帳・自動返信）に落ちていた。読む操作は GET、書く操作は POST の決めた名前だけを通す
- 本来の合言葉で知らない操作名を送っても、フォームとして受けていた（転送の action 'contact' だけはフォームへ）
- AI 用の合言葉で通る error_log などが、外の文字を数式のまま表に書いていた（問い合わせのタブを読み出せる）
- 保存期間: 日付の列が数値だと 1970年として読み、その日のうちに個人の情報を消していた
- AI紹介チェックの後追いが、自由入力の業種名で案内を選んでいた（「矯正歯科」では歯科の案内にならない）
"""
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from test_gates import check, ROOT

GAS = ROOT / "automation" / "gas"
HARNESS = ROOT / "tests" / "gas_leads_harness.js"
AGENT = "agent-test-secret-0123456789abcd"


def _run(plan):
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.TemporaryDirectory() as d:
        hub = (GAS / "hub.gs").read_text(encoding="utf-8").replace("'AGENT_SECRET_XXXXXXXX'", f"'{AGENT}'")
        hp = Path(d) / "hub.gs"
        hp.write_text(hub, encoding="utf-8")
        r = subprocess.run([node, str(HARNESS), str(hp), str(GAS / "contact.hub.gs")], input=json.dumps(plan),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode:
        raise RuntimeError(f"受付を動かせませんでした: {(r.stderr or r.stdout)[-300:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_hub_rejects_names_it_does_not_know():
    print("\n■ 管制塔の受付: AI 用の合言葉は決めた操作だけ・知らない操作名はフォームにしない・外の文字を数式にしない")
    err_head = [["日時", "サイト", "工程", "エラー内容", "対応", "状態"]]
    form = {"type": "contact", "name": "山田", "email": "a@example.com", "message": "相談です", "company": "例"}
    out = _run({"tabs": {"エラーログ": err_head}, "show": ["エラーログ"], "posts": [
        {"action": "next_kw", "secret": AGENT},                      # 読む操作の名前を POST で
        {"action": "toString", "secret": AGENT},                     # 元の名前
        {"action": ["add_kw"], "secret": AGENT},                     # 配列の名前
        {"action": "lead_status", "secret": AGENT},                  # AI に許していない操作
        {"action": "nope", "secret": "$SECRET"},                     # 本来の合言葉でも知らない名前
        {"action": "error_log", "secret": AGENT, "site": "ai-lab", "phase": "p", "message": '=IMPORTDATA("https://x.example/")'},
        {"action": "contact", "secret": "$SECRET", "site": "partner", "silent": True, "data": dict(form)},
        dict(form, site="ai-lab", email="b@example.com"),            # 合言葉の無いフォーム（これまでどおり受ける）
    ]})
    if out is None:
        print("  WARN  node が無いため受付の動きは確かめられません")
        return
    res = out["results"]
    check("AI 用の合言葉: 読む操作の POST・元の名前・配列・許していない操作は通らない",
          [r.get("error") for r in res[:4]], ["unauthorized"] * 4)
    check("本来の合言葉でも、知らない操作名はフォームとして受けない", res[4], {"ok": False, "error": "unknown action"})
    check("問い合わせの台帳に入ったのは、転送（contact）と合言葉の無いフォームの2件だけ",
          ([r.get("ok") for r in res[6:]], [x[6] for x in out["rows"]]), ([True, True], ["a@example.com", "b@example.com"]))
    check("転送の行の詳細欄に合言葉・操作名を書き写さない",
          any("secret" in str(c) or "action" in str(c) for x in out["rows"] for c in x), False)
    errs = out["shown"]["エラーログ"][1:]
    check("AI 用の合言葉の error_log は、= で始まる文字を数式でなく文字として置く",
          (res[5].get("ok"), [x[3] for x in errs]), (True, ["'=IMPORTDATA(\"https://x.example/\")"]))


def test_hub_agent_names_and_retention_and_industry():
    print("\n■ 管制塔の受付: 操作名の照合・保存期間の日付・手で止めた印・AI紹介チェックの業種のキー")
    now = int(time.time() * 1000)
    calls = [["agentOk_", AGENT, "next_kw", True], ["agentOk_", AGENT, "next_kw", False],
             ["agentOk_", AGENT, "add_kw", False], ["agentOk_", AGENT, "add_kw", True],
             ["agentOk_", AGENT, "constructor", False], ["agentOk_", AGENT, "hasOwnProperty", True],
             ["piiOld_", 45000, 1, now], ["piiOld_", "45000", 1, now], ["piiOld_", "2020-01-01T00:00:00Z", 1, now],
             ["botEnforce_", {"on": True}], ["botEnforce_", {"on": False, "manual": True}], ["botEnforce_", {"on": True}],
             ["botEnforce_", {"resume": True}], ["botEnforce_", {"on": True}],
             ["aiCheckLog_", {"email": "c@example.com", "company": "=HYPERLINK(\"x\")", "word": "矯正歯科", "ind": "dental",
                              "area": "大阪市", "optin": True}],
             ["aiCheckFollowText_", "様", ["", "", "", "", "", "", "", "", "サイト: https://x.example/"],
              {"word": "矯正歯科", "ind": "dental"}],
             ["aiCheckFollowText_", "様", ["", "", "", "", "", "", "", "", "サイト: https://x.example/"],
              {"word": "toString", "ind": "constructor"}]]
    out = _run({"calls": calls, "show": ["AI紹介チェック"]})
    if out is None:
        print("  WARN  node が無いため受付の動きは確かめられません")
        return
    c = out["calls"]
    check("AI 用の合言葉は、読む操作を GET・書く操作を POST でだけ通し、元の名前は通さない",
          c[:6], [True, False, True, False, False, False])
    check("保存期間: 数値の日付は消さない側に倒し、文字の日付は期限で判定する", c[6:9], [False, False, True])
    check("手で止めた印がある間は「断る」へ戻さず、resume で外してから戻せる",
          [(x.get("ok"), x.get("enforce"), bool(x.get("manual_off"))) for x in c[9:14]],
          [(True, True, False), (True, False, True), (False, False, True), (True, False, False), (True, True, False)])
    row = out["shown"]["AI紹介チェック"][-1]
    check("AI紹介チェックの記録: 業種のキーを14列目に残し、会社名は数式にしない", (row[13], row[2]), ("dental", "'=HYPERLINK(\"x\")"))
    check("後追いは業種のキーで歯科の案内を選ぶ（言い方が「矯正歯科」でも）・元の名前では選ばない",
          ("/lp/medical/" in c[15]["body"] and "ind=dental" in c[15]["body"], "ind=" in c[16]["body"]), (True, False))
