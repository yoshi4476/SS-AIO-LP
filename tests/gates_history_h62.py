# -*- coding: utf-8 -*-
"""2026-10-08: GitHub Actions の定時（schedule）が3〜8時間遅れて始まる（直近14日の実測: 記事の枠は枠0が3〜4時間・
後ろの枠が6〜7時間、同日救済は中央値5.5時間・最大8.1時間、記事動画は中央値5.6時間。週次は6時間遅れて来た回が
取り消された）。運用者の承認で、Cloudflare Workers の定時（Cron Triggers・無料）から workflow_dispatch で時刻どおりに
起動する形にした（automation/scheduler）。GitHub の schedule は予備として残し、同じ予定を2回動かさない。

この門が止めるもの:
- 予定の表（automation/scheduler/schedule.json）がワークフローの cron とずれる（手で書いた・cron を変えて作り直し忘れた）
- 枠の番号の対応が select と違う（Worker の「枠12」が別の枠の社の記事を書く）
- 予備の定時の回・Worker の2回目の起動が、同じ予定をもう一度動かす（同じ枠の記事・同じ日の動画が2本）
- inputs の無い手動起動の動きが変わる
- 鍵がリポジトリに入る・コマンドラインや出力に載る
- Worker が無料プランの上限（定時の数・1回の外への問い合わせ50件・時間15分）を超える
"""
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
WF = ROOT / ".github" / "workflows"
SCHED = ROOT / "automation" / "scheduler"
TARGETS = ["pipeline-multi.yml", "pipeline.yml", "daily-video.yml", "weekly-optimize.yml",
           "daily-kpi.yml", "focus-mode.yml", "monthly-report.yml"]
OLD_INPUTS = {"pipeline-multi.yml": ["site"], "pipeline.yml": ["mode"], "daily-video.yml": [],
              "weekly-optimize.yml": ["since", "force"], "daily-kpi.yml": ["day"], "focus-mode.yml": ["force"],
              "monthly-report.yml": ["resend_sites", "force"]}


def _utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _y(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _on(y):
    return y.get("on") or y.get(True) or {}


def _node(*args):
    node = shutil.which("node")
    if not node:
        print("  WARN  node が無いため Worker の動きは確かめられません（Node.js を入れると確かめる）")
        return None
    r = subprocess.run([node, str(SCHED / "test" / "harness.mjs"), *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    if r.returncode:
        raise RuntimeError(f"harness.mjs が落ちました: {(r.stderr or r.stdout)[-300:]}")
    return json.loads(r.stdout)


def _jsonc(path):
    return json.loads("\n".join(ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.strip().startswith("//")))


def test_scheduler_table_matches_every_cron():
    print("\n■ 定時の起動役: 予定の表がワークフローの cron を全部拾う（手で書かない）")
    import scheduler_build as SB
    import schedule_guard as SG
    check("対象は遅れると困る7本（記事の枠・同日救済・記事動画・週次・日次KPI・集中モード・月次）", sorted(SB.TARGETS), sorted(TARGETS))
    t = SB.build()
    check("表はワークフローから作ったものと同じ（cron を変えたら python scripts/scheduler_build.py を流してコミット）",
          (SB.TABLE.is_file() and SB.TABLE.read_text(encoding="utf-8")) == SB.dumps(t), True)
    for wf in TARGETS:
        check(f"{wf}: 表の予定 = ワークフローの cron（並び順も）", [e["cron"] for e in t["entries"] if e["wf"] == wf], SG.crons(wf))
    # 検出器: cron を1本足したワークフローから作ると、置いてある表と違う（作り直し忘れを門が拾う）
    added = lambda n: SB.read_wf(n).replace('- cron: "13 1 * * *"', '- cron: "13 1 * * *"\n    - cron: "43 1 * * *"') \
        if n == "daily-kpi.yml" else SB.read_wf(n)
    check("検出器: cron を足して作り直し忘れた表を拾う", SB.dumps(SB.build(added)) != SB.TABLE.read_text(encoding="utf-8"), True)
    resc = [e["inputs"] for e in t["entries"] if e["wf"] == "pipeline.yml"]
    check("同日救済は mode=rescue で起動する（手で起動した回の既定は main＝記事を書く。学び L0101）", resc, [{"mode": "rescue"}])
    bad = lambda n: SB.read_wf(n).replace('"30 12 * * *" ]; then', '"30 11 * * *" ]; then') if n == "pipeline.yml" else SB.read_wf(n)
    try:
        SB.build(bad)
        refused = False
    except ValueError:
        refused = True
    check("救済に回らない pipeline.yml の定時は表を作らない（main で起動して記事が二重になる）", refused, True)
    for e in t["entries"]:
        for k, want in (("minute", (0, 59)), ("hour", (0, 23))):
            if not all(want[0] <= v <= want[1] for v in e[k] or []):
                check(f"{e['wf']} {e['cron']}: {k} の範囲", e[k], "範囲内")


def test_worker_fires_every_schedule_exactly_once():
    print("\n■ 定時の起動役: Worker が予定の時刻ごとにちょうど1回、初めて起動する（cron の読み方は schedule_guard と同じ）")
    import scheduler_build as SB
    import schedule_guard as SG
    a, b = _utc("2026-09-28T00:00:00Z"), _utc("2026-11-02T00:00:00Z")   # 月をまたぎ、1日・15日・月曜・木曜を含む
    got = _node("fires", a.isoformat().replace("+00:00", "Z"), b.isoformat().replace("+00:00", "Z"))
    if got is None:
        return
    fresh = sorted((wf, cron, at) for wf, cron, at, f in got if f)
    want = sorted((e["wf"], e["cron"], t.strftime("%Y-%m-%dT%H:%M:%S.000Z"))
                  for e in SB.build()["entries"] for t in SG.fires([e["cron"]], a + timedelta(minutes=1), b + timedelta(minutes=1)))
    check("予定の時刻ごとに、初めて見る回（fresh）がちょうど1回ある", fresh == want, True)
    check("同じ予定を2回 fresh にしない", len(fresh), len(set(fresh)))
    seen = {}
    for wf, cron, at, f in got:
        seen[(wf, cron, at)] = seen.get((wf, cron, at), 0) + 1
    check("窓は2回分（1回起きそびれても次の回が拾う）", set(seen.values()), {SB.LOOKBACK_MINUTES // SB.TICK_MINUTES})
    mon = sum(1 for wf, _, at in fresh if wf == "monthly-report.yml")
    check("月次は 10/1・10/15・11/1 の3回（日の欄を読む）", mon, 3)
    wk = [at for wf, _, at in fresh if wf == "weekly-optimize.yml"]
    check("週次は月曜（UTC）だけ", {_utc(x).weekday() for x in wk}, {0})


def test_worker_dispatch_flow():
    print("\n■ 定時の起動役: 起動の入力・確かめてから起動・再試行で二重に起動しない（GitHub を偽物にして）")
    s = _node("scenarios")
    if s is None:
        return
    p = s["fresh_dispatch"]["posts"]
    check("起動するのは予定の1件だけ", len(p), 1)
    if p:
        check("記事の枠: 枠の番号・予定の時刻（日本時間）・鍵の期限（ISO）を渡す",
              (p[0]["url"].endswith("/actions/workflows/pipeline-multi.yml/dispatches"), p[0]["body"]),
              (True, {"ref": "master", "inputs": {"slot": "12", "scheduled_for": "2026-10-08T20:07+09:00",
                                                  "token_expiry": "2026-12-31T00:00:00Z"}}))
    check("鍵は Authorization にだけ載せる（前後の空白・改行は落とす）", s["fresh_dispatch"]["auth"], ["Bearer test-token"])
    check("GitHub に名乗る（User-Agent が無いと断られる）", all(s["fresh_dispatch"]["ua"]), True)
    check("一覧は予定の1分前より後に作られた回に絞る（応答を小さく。CPU は1回10ミリ秒）",
          ("created=%3E%3D2026-10-08T11%3A06%3A00Z" in s["fresh_dispatch"]["gets"][0], "per_page=20" in s["fresh_dispatch"]["gets"][0]),
          (True, True))
    for name in ("already_by_worker", "already_by_backup", "second_tick_confirms"):
        check(f"{name}: その予定の回がもうあれば起動しない", (s[name]["posts"], s[name]["results"]), ([], ["exists"]))
    check("次の回が確かめただけのときはログを書かない（倍にしない）", s["second_tick_confirms"]["logs"], [])
    check("前の日の同じ枠の回は数えない", len(s["yesterday_does_not_count"]["posts"]), 1)
    check("失敗して再試行するときは、先に一覧を見て、できていれば起動しない（二重に起動しない）",
          (len(s["retry_finds_it"]["posts"]), s["retry_finds_it"]["results"], s["retry_finds_it"]["sleeps"]),
          (1, ["exists"], [15000]))
    check("失敗が続けば間を置いて3回まで。あとは予備の定時に任せる",
          (len(s["retry_until_gave_up"]["posts"]), s["retry_until_gave_up"]["sleeps"], s["retry_until_gave_up"]["results"]),
          (3, [15000, 45000], ["gave_up"]))
    check("失敗はログに残す", [x for x in s["retry_until_gave_up"]["logs"] if x[0] == "error"][-1], ["error", "gave_up"])
    check("入力が合わない（422）はやり直さない", (len(s["rejected_422"]["posts"]), s["rejected_422"]["results"]), (1, ["rejected"]))
    check("鍵が通らない（401）なら起動しない", (s["auth_401"]["posts"], s["auth_401"]["results"]), ([], ["auth"]))
    check("鍵が無ければ GitHub に問い合わせない", (s["no_token"]["gets"], s["no_token"]["posts"], s["no_token"]["results"]),
          ([], [], ["no_token"]))
    check("予定が無い回は GitHub に問い合わせない", (s["nothing_due"]["gets"], s["nothing_due"]["posts"]), ([], []))
    check("master の表を読めないときは配ったときの表で起動する", len(s["table_fallback"]["posts"]), 1)
    check("期限のヘッダーが空なら token_expiry は空", [x["body"]["inputs"]["token_expiry"] for x in s["no_expiry_header"]["posts"]], [""])
    check("月次: 1日 9:00（日本時間）の回を起動する",
          [(x["url"].rsplit("/", 2)[-2], x["body"]["inputs"]) for x in s["monthly"]["posts"]],
          [("monthly-report.yml", {"scheduled_for": "2026-10-01T09:00+09:00", "token_expiry": "2026-12-31T00:00:00Z"})])
    check("同日救済: mode=rescue で起動する",
          [x["body"]["inputs"].get("mode") for x in s["rescue"]["posts"]], ["rescue"])


def _runs():
    w = lambda i, t, c, ev="workflow_dispatch", st="completed", con="success": {
        "id": i, "event": ev, "display_title": t, "created_at": c, "status": st, "conclusion": con}
    return w


def test_guard_runs_each_schedule_once():
    print("\n■ 定時の起動役: 同じ予定は先に作られた回だけが動く（予備の定時・Worker の2回目は何もしない）")
    import schedule_guard as SG
    import sched_guard as G
    w = _runs()
    pm = SG.crons("pipeline-multi.yml")
    worker = w(100, "記事の枠 12 2026-10-08T20:07+09:00", "2026-10-08T11:10:05Z")
    backup = w(200, "記事の枠（予備の定時） 7 11 * * *", "2026-10-08T17:40:00Z", ev="schedule")
    dec = lambda me, runs, cron="", inputs=None, wf="pipeline-multi.yml", crons=pm, slot=True: G.decide(
        me["id"], G.my_key(me["event"], cron, inputs or {}, G._created(me), crons, slot), G._created(me), runs, crons, slot)[0]
    check("枠12 の時刻は select の数え方と同じ（cron の並び順）", pm.index("7 11 * * *"), 12)
    check("予備の定時の回は、同じ枠・同じ日を Worker が先に起動していれば何もしない",
          dec(backup, [backup, worker], cron="7 11 * * *"), False)
    check("Worker の回は、後から来た予備の定時があっても動く",
          dec(worker, [backup, worker], inputs={"slot": "12", "scheduled_for": "2026-10-08T20:07+09:00"}), True)
    again = w(101, "記事の枠 12 2026-10-08T20:07+09:00", "2026-10-08T11:15:02Z")
    check("Worker が同じ予定を2回起動したら、後の回は何もしない",
          (dec(again, [again, worker], inputs={"slot": "12", "scheduled_for": "2026-10-08T20:07+09:00"}),
           dec(worker, [again, worker], inputs={"slot": "12", "scheduled_for": "2026-10-08T20:07+09:00"})), (False, True))
    early = w(90, "記事の枠（予備の定時） 7 11 * * *", "2026-10-08T11:07:40Z", ev="schedule")
    check("GitHub の定時が先に来た日は、Worker の回が何もしない",
          (dec(worker, [worker, early], inputs={"slot": "12", "scheduled_for": "2026-10-08T20:07+09:00"}),
           dec(early, [worker, early], cron="7 11 * * *")), (False, True))
    failed = w(100, "記事の枠 12 2026-10-08T20:07+09:00", "2026-10-08T11:10:05Z", con="failure")
    check("先の回が落ちても後の回は書かない（同じ枠が2本になる。落ちた回は自動修復が受け持つ）",
          dec(backup, [backup, failed], cron="7 11 * * *"), False)
    other = w(201, "記事の枠（予備の定時） 7 12 * * *", "2026-10-08T18:10:00Z", ev="schedule")
    check("別の枠は止めない", dec(other, [other, worker], cron="7 12 * * *"), True)
    yday = w(50, "記事の枠 12 2026-10-07T20:07+09:00", "2026-10-07T11:10:05Z")
    check("前の日の同じ枠は止めない", dec(backup, [backup, yday], cron="7 11 * * *"), True)
    oldfmt = w(60, "Multi-Site Article Pipeline", "2026-10-08T11:30:00Z", ev="schedule")
    check("run-name を足す前の予備の回（枠が分からない）は数えない", dec(worker, [worker, oldfmt],
          inputs={"slot": "12", "scheduled_for": "2026-10-08T20:07+09:00"}), True)
    # 日本時間 00:07 の枠（UTC 15:07）は予定の日が翌日になる。予備の回が日付をまたいで来ても同じ日に数える
    w16 = w(300, "記事の枠 16 2026-10-09T00:07+09:00", "2026-10-08T15:10:04Z")
    b16 = w(301, "記事の枠（予備の定時） 7 15 * * *", "2026-10-08T22:00:00Z", ev="schedule")
    check("日付をまたぐ枠も予定の日（日本時間）で突き合わせる", dec(b16, [b16, w16], cron="7 15 * * *"), False)
    kc = SG.crons("daily-kpi.yml")
    kw = w(400, "日次KPI 2026-10-08T10:13+09:00", "2026-10-08T01:15:04Z")
    kb = w(401, "日次KPI（予備の定時） 13 1 * * *", "2026-10-08T06:40:00Z", ev="schedule")
    kold = w(402, "Daily KPI", "2026-10-08T06:41:00Z", ev="schedule")
    kd = lambda me, runs, **k: dec(me, runs, wf="daily-kpi.yml", crons=kc, slot=False, **k)
    check("日次KPI: 予備の定時は同じ予定の時刻の Worker の回があれば何もしない", kd(kb, [kb, kw], cron="13 1 * * *"), False)
    check("cron が1つのワークフローは、run-name を足す前の予備の回も予定の時刻が分かる", kd(kold, [kold, kw], cron="13 1 * * *"), False)
    manual = w(403, "Daily KPI", "2026-10-08T03:00:00Z")
    check("手で起動した回は何にも止められない", kd(manual, [manual, kw, kb]), True)
    check("鍵の読み方: Worker の回の run-name", G.run_key(worker, pm, True), ("slot", 12, "2026-10-08"))
    check("鍵の読み方: 予備の定時の回（作られた時刻からさかのぼる）", G.run_key(backup, pm, True), ("slot", 12, "2026-10-08"))


def test_manual_dispatch_is_unchanged():
    print("\n■ 定時の起動役: inputs の無い手動起動は今までどおり（API も呼ばない）")
    import daily_audit as D
    import sched_guard as G

    def boom(_):
        raise AssertionError("手で起動した回で GitHub の一覧を読んだ")
    now = _utc("2026-10-08T03:00:00Z")
    for wf in TARGETS:
        go, why = G.check(wf, "workflow_dispatch", "", {}, "1", now, boom)
        check(f"{wf}: 入力の無い手動起動は動かす（一覧を読まない）", go, True)
    check("site だけ入れた手動起動も動かす", G.check("pipeline-multi.yml", "workflow_dispatch", "", {"site": "ai-lab"}, "1", now, boom)[0], True)
    # select の枠の決め方（ワークフローに埋めた python をそのまま動かす）
    text = (WF / "pipeline-multi.yml").read_text(encoding="utf-8")
    m = re.search(r"<<'PY'\n(.*?)\n\s*PY\n", text, re.S)
    check("select の枠の決め方が読める", bool(m), True)
    if m:
        code = "\n".join(ln[10:] if ln.startswith(" " * 10) else ln for ln in m.group(1).splitlines())
        run = lambda sch, slot: subprocess.run([sys.executable, "-", sch, slot], input=code, cwd=str(ROOT),
                                               capture_output=True, text=True, encoding="utf-8").stdout.strip()
        check("select: 手で起動した回（定時も枠も無い）は枠0（今までどおり）", run("", ""), "0 40")
        check("select: 予備の定時は cron の並び順", run("7 11 * * *", ""), "12 40")
        check("select: Worker の回は入力の枠の番号", run("", "12"), "12 40")
        check("select: 枠の番号があればそれを使う", run("7 11 * * *", "3"), "3 40")
    sel = _y("pipeline-multi.yml")["jobs"]["select"]
    site = next(s for s in sel["steps"] if s.get("id") == "site")
    check("select: 入力は環境変数で受ける（run に直接埋めない）", ("${{ inputs.slot }}" in site["run"],
          (site.get("env") or {}).get("IN_SLOT"), (site.get("env") or {}).get("IN_AT")),
          (False, "${{ inputs.slot }}", "${{ inputs.scheduled_for }}"))
    check("select: 予定の日は起動役の予定の時刻から（--slot-day に渡す）", '--slot-day "${{ github.event.schedule }}" "$IN_AT"' in site["run"], True)
    t = _utc("2026-10-08T22:00:00Z")
    check("予定の日: 手で動かした回は今日（日本時間）", D.slot_day("", t), "2026-10-09")
    check("予定の日: 起動役の回は予定の時刻の日", D.slot_day("", t, at="2026-10-08T20:07+09:00"), "2026-10-08")
    check("予定の日: 予備の定時は cron からさかのぼる（今までどおり）", D.slot_day("7 8 * * *", t), "2026-10-08")
    check("予定の日: 予定の時刻が読めなければ今までどおり", D.slot_day("7 8 * * *", t, at="あ"), "2026-10-08")
    import scheduler_build as SB
    table = SB.build()
    for wf in TARGETS:
        ins = (_on(_y(wf)).get("workflow_dispatch") or {}).get("inputs") or {}
        check(f"{wf}: 前からの入力は残る", [k for k in OLD_INPUTS[wf] if k in ins], OLD_INPUTS[wf])
        keys = {k for e in table["entries"] if e["wf"] == wf for k in e["inputs"]} | set(SB.COMMON_INPUTS)
        check(f"{wf}: 起動役が渡す入力は全部受け口がある（無いと GitHub が 422 で断る）", sorted(k for k in keys if k not in ins), [])
        new = [k for k in keys if k not in OLD_INPUTS[wf] and k in ins]
        check(f"{wf}: 足した入力は既定が空で必須でない（手で動かすときは空のまま）",
              [(ins[k].get("default"), bool(ins[k].get("required"))) for k in new], [("", False)] * len(new))
    mode = next(s for s in _y("pipeline.yml")["jobs"]["pipeline"]["steps"] if s.get("id") == "mode")["run"]
    check("同日救済: 起動された回は入力の mode を使う（起動役の mode=rescue が効く）",
          'if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then\n  echo "mode=${{ inputs.mode }}"' in mode, True)


def test_receivers_are_wired():
    print("\n■ 定時の起動役: 対象のワークフローに受け口（run-name・入力・同じ予定の判定）がある")
    import scheduler_build as SB
    for wf in TARGETS:
        y, text = _y(wf), (WF / wf).read_text(encoding="utf-8")
        rn = str(y.get("run-name") or "")
        label = SB.TARGETS[wf]["label"]
        fmt = f"format('{label} {{0}} {{1}}', inputs.slot, inputs.scheduled_for)" if SB.TARGETS[wf].get("slot") \
            else f"format('{label} {{0}}', inputs.scheduled_for)"
        check(f"{wf}: run-name の末尾が予定の時刻（Worker の回）と cron（予備の定時の回）",
              (rn.startswith("${{ inputs.scheduled_for && " + fmt), f"format('{label}（予備の定時） {{0}}', github.event.schedule)" in rn,
               rn.endswith("|| github.workflow }}")), (True, True, True))
        check(f"{wf}: 同じ予定の判定（sched_guard）を呼ぶ", "python3 scripts/sched_guard.py" in text, True)
        perm = {**(y.get("permissions") or {})}
        check(f"{wf}: 実行の一覧を読める（actions: read 以上）", perm.get("actions") in ("read", "write"), True)
    for wf, job in (("pipeline.yml", "pipeline"), ("daily-video.yml", "video"), ("daily-kpi.yml", "kpi")):
        y = _y(wf)
        g = y["jobs"].get("sched") or {}
        step = next((s for s in g.get("steps", []) if "sched_guard.py" in str(s.get("run"))), {})
        check(f"{wf}: 判定のジョブ（sched）が結果を出し、鍵（GH_TOKEN）を渡す",
              ((g.get("outputs") or {}).get("go"), (step.get("env") or {}).get("GH_TOKEN")),
              ("${{ steps.g.outputs.sched_go }}", "${{ github.token }}"))
        j = y["jobs"][job]
        check(f"{wf}: 本体は判定のあと、同じ予定を先に受け持った回が無いときだけ（判定が落ちても動かす）",
              (j.get("needs"), str(j.get("if"))), ("sched", "${{ !cancelled() && needs.sched.outputs.go != 'no' }}"))
    for wf in ("pipeline.yml", "daily-video.yml"):
        y = _y(wf)
        main = "pipeline" if wf == "pipeline.yml" else "video"
        check(f"{wf}: 何もしない回がグループに並ばない（concurrency は本体のジョブだけ）",
              ("concurrency" in y, "concurrency" in y["jobs"]["sched"], bool(y["jobs"][main].get("concurrency"))), (False, False, True))
    check("同日救済: 記事のグループのまま・取り消さない",
          _y("pipeline.yml")["jobs"]["pipeline"]["concurrency"], {"group": "article-pipeline", "cancel-in-progress": False})
    sel = _y("pipeline-multi.yml")["jobs"]["select"]
    ids = [s.get("id") for s in sel["steps"]]
    check("記事の枠: 判定（sched）は枠の判定（site）より前", ids.index("sched") < ids.index("site") if "sched" in ids and "site" in ids else False, True)
    site = next(s for s in sel["steps"] if s.get("id") == "site")
    check("記事の枠: 先に受け持った回があれば、枠の判定をせず skip", (site.get("if"), sel["outputs"]["skip"]),
          ("steps.sched.outputs.sched_go != 'no'", "${{ steps.sched.outputs.sched_go == 'no' && 'yes' || steps.site.outputs.skip }}"))
    for wf, step_id, stop in (("weekly-optimize.yml", "g", 'echo "go=false"'), ("monthly-report.yml", "g", 'echo "go=false"'),
                              ("focus-mode.yml", "st", "s=done")):
        y = _y(wf)
        first = next(iter(y["jobs"]))
        st = next(s for s in y["jobs"][first]["steps"] if s.get("id") == step_id)
        run = st["run"]
        check(f"{wf}: 最初のジョブで判定し、先の回があれば止める",
              ("scripts/sched_guard.py" in run and re.search(r"SCHED_GO=no'; then " + re.escape(stop), run) is not None,
               (st.get("env") or {}).get("GH_TOKEN")), (True, "${{ github.token }}"))


def test_watch_tells_when_worker_stops_or_key_expires():
    print("\n■ 定時の起動役: 止まった・起動しそびれた・鍵の期限が近い、を要対応で知らせる")
    import findings
    import scheduler_build as SB
    import sched_guard as G
    table = SB.build()
    now = _utc("2026-10-08T12:00:00Z")
    on = {wf: True for wf in TARGETS}
    w = _runs()
    def runs_at(t):     # その時刻までの予定を Worker が全部起動していた（各ワークフローの最後の予定）
        out = {}
        for wf in TARGETS:
            due = G.last_due([e for e in table["entries"] if e["wf"] == wf], t)
            out[wf] = [w(1, f"{SB.TARGETS[wf]['label']} {due[1]['inputs'].get('slot', '')} {G.jst_day(due[0])}T".replace("  ", " ")
                         + f"{due[0].astimezone(G.JST):%H:%M}+09:00", (due[0] + timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ"))]
        return out
    lines, ok = G.watch_verdict({}, {wf: [] for wf in TARGETS}, on, table, now)
    check("まだ配っていない（記録も起動も無い）ときは知らせない（unset）", ok, "unset")
    dep = {"deployed_at": "2026-10-01T10:00+09:00", "first_seen": "2026-10-01T10:07+09:00"}
    lines, ok = G.watch_verdict(dep, runs_at(now), on, table, now)
    check("Worker が予定どおり起動していれば問題なし", (ok, [x for x in lines if x.startswith("要対応")]), ("yes", []))
    stale = runs_at(now - timedelta(hours=10))
    lines, ok = G.watch_verdict(dep, stale, on, table, now)
    check("Worker からの起動が8時間を超えて無ければ要対応（止まった・鍵が切れた）",
          (ok, any(x.startswith("要対応: 定時の起動役（Cloudflare Worker）からの起動が") for x in lines)), ("no", True))
    miss = runs_at(now)
    miss["daily-kpi.yml"] = []
    lines, ok = G.watch_verdict(dep, miss, on, table, now)
    check("ワークフローごとに、最後の予定を起動しそびれたら要対応（422 などで1本だけ落ちる）",
          (ok, [x.startswith("要対応: 日次KPI（daily-kpi.yml）の 10/08 10:13 の予定を起動役が起動していません")
                for x in lines if x.startswith("要対応")]), ("no", [True]))
    lines, ok = G.watch_verdict(dep, miss, {**on, "daily-kpi.yml": False}, table, now)
    check("止めてあるワークフロー（集中モードの期限後など）は見ない", ok, "yes")
    lines, ok = G.watch_verdict({"deployed_at": "2026-10-08T20:40+09:00"}, {wf: [] for wf in TARGETS}, on, table, now)
    check("配ってすぐ（最初の予定から30分の猶予の前）はまだ知らせない", ok, "yes")
    lines, ok = G.watch_verdict({"deployed_at": "2026-10-08T15:00+09:00"}, {wf: [] for wf in TARGETS}, on, table, now)
    check("配ってから予定があったのに起動が1つも無ければ、8時間を待たずに知らせる", ok, "no")
    lines, ok = G.watch_verdict({"deployed_at": "2026-10-07T15:00+09:00"}, {wf: [] for wf in TARGETS}, on, table, now)
    check("配ったのに一度も起動が無いまま8時間を超えたら要対応（鍵を入れていない・権限が無い）", ok, "no")
    soon = {**dep, "token_expiry": "2026-10-30T00:00:00Z"}
    lines, ok = G.watch_verdict(soon, runs_at(now), on, table, now)
    check("鍵の期限まで30日を切ったら要対応", (ok, any("期限まで残り21日" in x for x in lines)), ("no", True))
    lines, ok = G.watch_verdict({**dep, "token_expiry": "2027-10-30T00:00:00Z"}, runs_at(now), on, table, now)
    check("期限が先なら問題なし", ok, "yes")
    lines, ok = G.watch_verdict(dep, runs_at(now), on, table, now)
    check("期限のヘッダーが空（期限なしの鍵）は要対応にせず、情報として出す",
          (ok, any(x.startswith("鍵の期限: GitHub の応答に期限のヘッダーが無い") for x in lines)), ("yes", True))
    lines, ok = G.watch_verdict({**dep, "token_expiry_manual": "2026-10-20T00:00:00+09:00"}, runs_at(now), on, table, now)
    check("手で記録した期限も見る（ヘッダーが空のとき）", (ok, any("手で記録した期限" in x for x in lines)), ("no", True))
    check("鍵の期限のヘッダーの形（UTC・時差つき）を読む",
          (G.norm_expiry("2026-12-31 00:00:00 UTC"), G.norm_expiry("2026-12-31 09:00:00 +0900"), G.norm_expiry("")),
          ("2026-12-31T00:00:00Z", "2026-12-31T00:00:00Z", ""))
    lab = "定時の起動役（Cloudflare Worker）の起動と鍵の期限"
    check("週次の findings が見張りを回し、続いても要対応のまま（期限あり）",
          ([sc for l, sc, _ in findings.CHECKS if l == lab], lab in findings.DEADLINE), (["sched_guard.py --watch"], True))
    sh = _y("selfheal.yml")["jobs"]["heal"]["steps"]
    st = next((s for s in sh if "sched_guard.py --watch" in str(s.get("run"))), {})
    check("日次の生存監視が見張りを回し、要対応を通知に載せる",
          ((st.get("env") or {}).get("SCHED_GH_TOKEN"), "grep '^要対応'" in str(st.get("run"))), ("${{ github.token }}", True))
    wk = next(s for s in _y("weekly-optimize.yml")["jobs"]["optimize"]["steps"] if "scripts/findings.py" in str(s.get("run")))
    check("週次の findings の工程に見張りの鍵を渡す（見張りだけが使う名前）", (wk.get("env") or {}).get("SCHED_GH_TOKEN"), "${{ github.token }}")
    st = json.loads((ROOT / "data" / "scheduler.json").read_text(encoding="utf-8"))
    check("記録（data/scheduler.json）は公開してよい値だけ", sorted(k for k in st if k != "note"),
          ["deployed_at", "first_seen", "token_expiry", "token_expiry_manual", "token_set_at"])
    rec = G.merged_state({"first_seen": "", "token_expiry": ""}, {"scheduled_for": "2026-10-08T20:07+09:00",
                                                                    "token_expiry": "2026-12-31T00:00:00Z"}, now)
    check("Worker の回は最初の起動と鍵の期限を残す", (rec["first_seen"], rec["token_expiry"]), ("2026-10-08T20:07+09:00", "2026-12-31T00:00:00Z"))
    same = {"first_seen": "2026-10-01T10:07+09:00", "token_expiry": ""}
    check("変わらなければ書かない（毎回コミットしない）", G.merged_state(same, {"scheduled_for": "2026-10-08T20:07+09:00", "token_expiry": ""}, now), same)


def test_no_key_in_repo_or_output():
    print("\n■ 定時の起動役: 鍵がリポジトリ・コマンドライン・出力に出ない")
    pat = re.compile(r"github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,}")
    files = [p for p in SCHED.rglob("*") if p.is_file() and ".wrangler" not in p.parts and "node_modules" not in p.parts]
    files += [ROOT / "scripts" / n for n in ("sched_guard.py", "scheduler_build.py", "scheduler_deploy.py")]
    files += [ROOT / "data" / "scheduler.json"] + sorted(WF.glob("*.yml"))
    hits = [p.relative_to(ROOT).as_posix() for p in files if pat.search(p.read_text(encoding="utf-8", errors="replace"))]
    check("鍵の形の文字列がどこにも無い", hits, [])
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    check(".env・.dev.vars（wrangler dev の鍵）・.wrangler/ はコミットされない", all(x in gi for x in (".env", ".dev.vars", ".wrangler/")), True)
    wc = _jsonc(SCHED / "wrangler.jsonc")
    check("wrangler の設定に鍵を書かない（vars を持たない）", "vars" in wc, False)
    src = "\n".join(p.read_text(encoding="utf-8") for p in sorted((SCHED / "src").glob("*.mjs")))
    check("Worker は鍵を secret（env.GITHUB_TOKEN）からだけ読む",
          (re.findall(r"[\w)]+\.GITHUB_TOKEN", src), re.search(r"Bearer [A-Za-z0-9_]", src) is None), (["env.GITHUB_TOKEN"], True))
    import scheduler_deploy as SD
    import sched_guard as G
    got = {}
    fake = "github_pat_" + "x" * 40
    with tempfile.TemporaryDirectory() as d:
        envf = Path(d) / ".env"
        envf.write_text(f"OTHER=1\nSCHEDULER_GITHUB_TOKEN='{fake}'\n", encoding="utf-8")
        check(".env の SCHEDULER_GITHUB_TOKEN を読む（引用符を外す）", SD.env_token(envf), fake)
        check(".env に無ければ空（入力画面に回る）", SD.env_token(Path(d) / "none.env"), "")
        old_state, old_env = G.STATE, SD.env_token
        G.STATE = Path(d) / "scheduler.json"
        try:
            class R:
                returncode, stdout, stderr = 0, f"✨ Success! Uploaded secret GITHUB_TOKEN {fake}", ""

            def run(args, secret=None):
                got.update(args=args, secret=secret)
                return R()
            SD.env_token = lambda path=None: ""
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = SD.set_token(ask=lambda: fake, check=lambda t: (True, "", "ok"), run=run)
            out = buf.getvalue()
            check("--set-token: 鍵は標準入力で渡し、コマンドラインに載せない", (rc, got.get("args"), got.get("secret")),
                  (0, ["secret", "put", "GITHUB_TOKEN"], fake))
            check("--set-token: 鍵を画面に出さない（wrangler の出力に混ざっても伏せる）", fake in out, False)
            check("--set-token: 期限のヘッダーが空なら「期限なしの鍵」と出す", "期限なしの鍵" in out, True)
            got.clear()
            with contextlib.redirect_stdout(io.StringIO()):
                rc = SD.set_token(ask=lambda: fake, check=lambda t: (False, "", "鍵が通りません"), run=run)
            check("--set-token: GitHub で使えない鍵は入れない", (rc, got), (1, {}))
        finally:
            G.STATE, SD.env_token = old_state, old_env
    dep = (ROOT / "scripts" / "scheduler_deploy.py").read_text(encoding="utf-8")
    check("wrangler へは input= で渡す（引数の配列に鍵を入れない）", "input=secret" in dep and "[npx(), \"--yes\", WRANGLER] + args" in dep, True)


def test_worker_fits_free_plan():
    print("\n■ 定時の起動役: Cloudflare Workers の無料プランの上限に収まる")
    import scheduler_build as SB
    import schedule_guard as SG
    wc = _jsonc(SCHED / "wrangler.jsonc")
    crons = (wc.get("triggers") or {}).get("crons") or []
    check("定時は1個（無料プランはアカウントで5個まで）", crons, [f"*/{SB.TICK_MINUTES} * * * *"])
    check("HTTP の入口を作らない（定時だけ）", (wc.get("workers_dev"), wc.get("preview_urls")), (False, False))
    check("起動・失敗の記録を Workers Logs に残す", (wc.get("observability") or {}).get("enabled"), True)
    entry = SCHED / wc.get("main", "")
    check("入口のファイルがある", entry.is_file(), True)
    # 入口が定数（TIMEOUT_MS など）を出すと、実行環境がそれを入口とみなして起動しない（2026-10-08 に wrangler dev で確かめた）
    exports = re.findall(r"^export\s+(?:default\b|(?:async\s+)?function\s+\w+|const\s+\w+|let\s+\w+|class\s+\w+|\{)",
                         entry.read_text(encoding="utf-8") if entry.is_file() else "", re.M)
    check("入口は default だけを出す（定数や関数は core.mjs から）", exports, ["export default"])
    check("1日に起きる回数（無料は1日10万件）", 24 * 60 // SB.TICK_MINUTES <= 100000, True)
    src = (SCHED / "src" / "core.mjs").read_text(encoding="utf-8")
    waits = [int(x) for x in re.search(r"RETRY_WAIT_MS = \[([\d, ]+)\]", src).group(1).split(",")]
    timeout = int(re.search(r"TIMEOUT_MS = (\d+)", src).group(1))
    import bisect
    a = _utc("2026-09-28T00:00:00Z")
    fires = sorted(t for e in SB.build()["entries"] for t in SG.fires([e["cron"]], a, a + timedelta(days=35)))
    most, t, back = 0, a, timedelta(minutes=SB.LOOKBACK_MINUTES)
    while t < a + timedelta(days=35):
        most = max(most, bisect.bisect_right(fires, t) - bisect.bisect_right(fires, t - back))
        t += timedelta(minutes=SB.TICK_MINUTES)
    tries = len(waits) + 1
    sub = 1 + most * tries * 2
    check(f"1回の外への問い合わせ（窓に入る予定は最大{most}件 → 最大{sub}件。無料は50件）", sub <= 50, True)
    wall = timeout / 1000 + most * (sum(waits) / 1000 + tries * 2 * timeout / 1000)
    check(f"1回の時間（最悪でも{wall:.0f}秒。無料は15分）", wall < 15 * 60, True)
    check("表は小さい（毎回読んで JSON を開く。CPU は1回10ミリ秒）", SB.TABLE.stat().st_size < 64 * 1024, True)
    check("Worker の窓と間隔は表と同じ値を使う（配ったときの表から読む）",
          ("BUNDLED.lookback_minutes" in src, "BUNDLED.tick_minutes" in src), (True, True))
    check("起動先のリポジトリ・ブランチは配ったときの表から（master の表で変えさせない）",
          ("t.repo === base.repo" in src, "t.ref === base.ref" in src, "ref: BUNDLED.ref" in src, "const repo = BUNDLED.repo" in src),
          (True, True, True, True))
    readme = (SCHED / "README.md").read_text(encoding="utf-8")
    check("README に対象のワークフローと上限の出典がある",
          (all(wf in readme for wf in TARGETS), "developers.cloudflare.com/workers/platform/limits" in readme,
           "developers.cloudflare.com/workers/configuration/cron-triggers" in readme), (True, True, True))
