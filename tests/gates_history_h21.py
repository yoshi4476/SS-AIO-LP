# -*- coding: utf-8 -*-
"""定時の取りこぼし・題を戻す判定の対照群・登録漏れの押し込み（2026-10-05）。

1. 2026-10-05（月）の Weekly Optimize は予定（10:23 JST）を3時間過ぎても始まらず手で起動し、前の週も5.5時間遅れた。
   落ちた run は自動修復が拾うが、始まらなかった run は誰も拾わなかった。手で起動した回と遅れて来た予定の回が
   重なると、同じ週に2回直す。固定すること: 見張りが取りこぼしを起動し、各ワークフローは区切りに済んだ run が
   あれば何もしない。
2. 題を戻す判定（rewrite_rollback）の対照群に公開からの週数が違う記事（と記事以外のページ）が混ざり、
   公開から日の浅い記事の自然な落ち込みを「直しが効かなかった」と読んでいた
   （実測: 前の対照38本のうち記事は3本。同じ週数の記事にそろえると対照の倍率は1.61→0.15〜0.36）。
3. コーポレートで公開3週を過ぎても「検出 - インデックス未登録」の記事が残る。再通知だけでは届かないので、
   検索1ページ目の記事から内部リンクを送る入口（link_boost --unindexed）を足す。
GitHub・Search Console には触れない（gh を呼ぶ関数と日別の表示は手元で作ったものに差し替える）。
"""
import io
import json
import tempfile
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from test_gates import check, ROOT

WF = ROOT / ".github" / "workflows"
UTC = timezone.utc


def _t(s):
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


def _run(i, created, status="completed", conclusion="success", event="schedule"):
    return {"id": i, "created_at": created, "status": status, "conclusion": conclusion, "event": event}


def test_schedule_guard_decides_missed_and_already_ran():
    import schedule_guard as G
    print("\n■ schedule_guard: 始まらなかった定時の回を見つけ、同じ区切りに2回動かさない")
    wk = G.crons("weekly-optimize.yml")
    check("予定の時刻はワークフローの cron をそのまま読む", wk, ["23 1 * * 1"])
    check("月曜 13:30 JST から見た直近の予定は月曜 10:23 JST",
          G.last_slot(wk, _t("2026-10-05T04:30:00")), _t("2026-10-05T01:23:00"))
    check("cron の曜日（UTC の月・木 19:13）を日本時間の火・金と取り違えない",
          G.last_slot(["13 19 * * 1,4"], _t("2026-10-06T20:00:00")), _t("2026-10-05T19:13:00"))
    check("月次の2本の cron（1日・15日）から直近を選ぶ",
          G.last_slot(G.crons("monthly-report.yml"), _t("2026-10-15T03:00:00")), _t("2026-10-15T00:00:00"))
    last_week = [_run(36389480023, "2026-09-28T07:02:15Z")]
    v = lambda now, runs, after=6, mx=48, per="week": G.missed(wk, runs, _t(now), after, mx, per)[0]
    check("6時間たつまでは待つ", v("2026-10-05T04:30:00", last_week), "wait")
    check("6時間たっても今週の run が無ければ取りこぼし（先週の run は数えない）", v("2026-10-05T07:53:00", last_week), "missed")
    check("手で起動した run があれば始まっている扱い",
          v("2026-10-05T07:53:00", [_run(37265388199, "2026-10-05T04:52:55Z", event="workflow_dispatch")] + last_week),
          "started")
    check("落ちた run も始まった扱い（落ちた回は自動修復が受け持つ）",
          v("2026-10-05T07:53:00", [_run(1, "2026-10-05T06:00:00Z", conclusion="failure")]), "started")
    check("起動してよい時間を過ぎたら起動しない", v("2026-10-07T15:00:00", last_week), "too_late")
    mo = G.crons("monthly-report.yml")
    check("月次は日の区切り（前の日の手動 run では済んだことにしない）",
          G.missed(mo, [_run(5, "2026-10-14T03:00:00Z")], _t("2026-10-15T06:53:00"), 6, 14, "day")[0], "missed")

    done = [_run(37265388199, "2026-10-05T04:52:55Z", event="workflow_dispatch")]
    ar = lambda now, runs, me, per="week": (G.already_ran(runs, _t(now), per, me) or {}).get("id")
    check("今週に成功で終わった run があれば、遅れて来た予定の run は何もしない",
          ar("2026-10-05T08:30:00", done, 37300000000), 37265388199)
    check("翌週の run は先週の成功を見ない", ar("2026-10-12T01:30:00", done, 37900000000), None)
    check("落ちた run は済んだことにしない（直し切れていない）",
          ar("2026-10-05T08:30:00", [_run(3, "2026-10-05T04:00:00Z", conclusion="failure")], 9), None)
    both = [_run(301, "2026-10-05T07:00:01Z", status="in_progress", conclusion=None),
            _run(300, "2026-10-05T07:00:00Z", status="in_progress", conclusion=None)]
    check("同時に始まった2つは、先に始まった方だけが動く（後の方が止まる・先の方は止まらない）",
          (ar("2026-10-05T07:01:00", both, 301), ar("2026-10-05T07:01:00", both, 300)), (300, None))
    check("同じグループで待っている run を見つける（起動するとそれが取り消される）",
          G.busy({"pipeline-multi.yml": [_run(7, "2026-10-05T07:00:00Z", status="pending", conclusion=None),
                                         _run(8, "2026-10-05T06:00:00Z")]}), ["pipeline-multi.yml run 7"])

    # main: gh を差し替えて、起動する・しないを確かめる
    calls = []
    real = (G.gh_api, G.dispatch, G._now)
    state = {"state": "active", "runs": last_week, "busy": []}

    def fake_api(path):
        if path.endswith("weekly-optimize.yml"):
            return {"state": state["state"]}
        if "weekly-optimize.yml/runs" in path:
            return {"workflow_runs": state["runs"]}
        return {"workflow_runs": state["busy"]}
    try:
        G.gh_api, G.dispatch, G._now = fake_api, lambda r, w, ref: calls.append(w), lambda: _t("2026-10-05T07:53:00")
        args = ["--repo", "o/r", "--missed", "weekly-optimize.yml", "--after-hours", "6", "--max-hours", "48",
                "--period", "week", "--avoid-busy", "--dispatch"]

        def go():
            with redirect_stdout(io.StringIO()) as o:
                rc = G.main(args)
            return rc, o.getvalue()
        rc, out = go()
        check("取りこぼしなら起動して SCHEDULE_OK=no・DISPATCHED=yes", (rc, calls, "DISPATCHED=yes" in out,
              "SCHEDULE_OK=no" in out), (0, ["weekly-optimize.yml"], True, True))
        calls.clear()
        state["busy"] = [_run(9, "2026-10-05T07:50:00Z", status="pending", conclusion=None)]
        rc, out = go()
        check("同じグループで待っている run があれば起動しない（次の見張りで見る）", (calls, "SCHEDULE_OK=no" in out), ([], True))
        state["busy"], state["state"] = [], "disabled_manually"
        rc, out = go()
        check("止めてあるワークフローは起動しない", (calls, "SCHEDULE_OK=yes" in out), ([], True))
        state["state"], state["runs"] = "active", done
        rc, out = go()
        check("今週の run があれば起動しない", (calls, "SCHEDULE_OK=yes" in out), ([], True))

        def boom(path):
            raise RuntimeError("gh が無い")
        G.gh_api = boom
        rc, out = go()
        check("gh が動かなければ終了コード1（見つかった・見つからないと区別する）", rc, 1)
    finally:
        G.gh_api, G.dispatch, G._now = real


def test_schedule_guard_is_wired():
    import schedule_guard as G
    print("\n■ schedule_guard: 見張りと二重実行の防止がワークフローにつながっている")
    heal = yaml.safe_load((WF / "selfheal.yml").read_text(encoding="utf-8"))
    job = heal["jobs"]["schedule-guard"]
    run = "\n".join(s.get("run", "") for s in job["steps"])
    specs = {}
    for ln in run.splitlines():
        if ".yml --after-hours" in ln:
            parts = ln.split('"')[1].split()
            specs[parts[0]] = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2) if parts[i + 1][:1] != "-"}
    check("見張りは週次・月次・集中モードの3本", sorted(specs), ["focus-mode.yml", "monthly-report.yml", "weekly-optimize.yml"])
    check("見張りは起動まで行い、定期実行と手動だけで動く（workflow_run では動かない）、起動の権限がある",
          ("--dispatch" in run, job["if"], job["permissions"]["actions"]), (True, "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'", "write"))
    guard_crons = [c["cron"] for c in heal[True]["schedule"]]
    # 見張りの cron は、対象の予定から after-hours 以上・max-hours 以内に来る（来なければ毎日 0 15 の回だけが頼り）
    for wf, sp in specs.items():
        hits = []
        for gc in guard_crons:
            for back in range(0, 35):
                now = G.last_slot([gc], _t("2026-10-31T23:59:00") - timedelta(days=back))
                slot = G.last_slot(G.crons(wf), now)
                late = (now - slot).total_seconds() / 3600
                if float(sp["--after-hours"]) <= late <= float(sp["--max-hours"]):
                    hits.append(gc)
                    break
        check(f"{wf}: 予定の回の後、起動してよい時間内に来る見張りの cron がある", bool(hits), True)
    check("heal は 0 15 の定期実行だけで動く（見張りの cron で heal を1日に何度も回さない）",
          "github.event.schedule == '0 15 * * *'" in heal["jobs"]["heal"]["if"], True)
    for wf, flag in (("weekly-optimize.yml", "--week"), ("monthly-report.yml", "--day"), ("focus-mode.yml", "--day")):
        src = (WF / wf).read_text(encoding="utf-8")
        y = yaml.safe_load(src)
        check(f"{wf}: 最初に区切りの済んだ run を見て、force で飛ばせる",
              (f"--already-ran {wf} {flag}" in src, "force" in y[True]["workflow_dispatch"]["inputs"],
               "actions" in (y.get("permissions") or {})), (True, True, True))
    wk = yaml.safe_load((WF / "weekly-optimize.yml").read_text(encoding="utf-8"))
    check("週次は guard の後でだけ、ほかの全ジョブが動く",
          {k: (v.get("needs"), v.get("if")) for k, v in wk["jobs"].items() if k != "guard"},
          {k: ("guard", "needs.guard.outputs.go == 'true'") for k in wk["jobs"] if k != "guard"})
    mo = yaml.safe_load((WF / "monthly-report.yml").read_text(encoding="utf-8"))
    check("月次の report は guard の後（各社の作り直し resend_sites は止めない）",
          (mo["jobs"]["report"].get("needs"), "inputs.resend_sites" in str(mo["jobs"]["guard"])), ("guard", True))
    fo = (WF / "focus-mode.yml").read_text(encoding="utf-8")
    check("集中モードは済んでいれば state を done にし、直す・止めるのどちらにも進まない",
          ("s=done" in fo, "state == 'active'" in fo, "state == 'expired'" in fo), (True, True, True))


def _curve(age):
    """公開からの日数ごとの表示（1〜3週で山・4〜6週で山の1/4・その後は少し）"""
    w = age // 7
    return 0 if age < 0 else (40 if w <= 2 else 10 if w <= 5 else 8)


def test_rollback_compares_with_same_age_controls():
    import effect_ab as EA
    import rewrite_rollback as R
    print("\n■ rewrite_rollback: 対照群は公開からの週数が近い記事だけ（足りなければ保留）")
    at = date.today() - timedelta(days=40)
    pubs, daily = {}, {}

    def add(slug, pub, scale_after=1.0, flat=None):
        pubs[slug] = pub
        d = daily.setdefault(slug, {})
        for i in range(-60, 45):
            day = at + timedelta(days=i)
            v = flat if flat is not None else _curve((day - pub).days)
            d[day.isoformat()] = [v * (scale_after if day > at else 1.0), 0, 0.0]
    add("fixed", at - timedelta(days=21))
    for k in range(12):
        add(f"young{k}", at - timedelta(days=21 + (k % 13) - 6))
    for k in range(30):
        add(f"old{k}", at - timedelta(days=200 + k), flat=30)
    daily["top"] = {(at + timedelta(days=i)).isoformat(): [100, 0, 0.0] for i in range(-60, 45)}
    me = EA.change(daily, "fixed", at, R.DAYS)[0]
    old_ctrl = sorted(EA.change(daily, s, at, R.DAYS)[0] for s in daily if s != "fixed")
    old_base = old_ctrl[len(old_ctrl) // 2]
    check("前の物差し（触っていない全ページ）では、経過の落ち込みを「効かなかった」と読む",
          me < old_base * R.WORSE, True)
    ctrl = R.controls(daily, "fixed", at, pubs, [])
    base = sorted(ctrl)[len(ctrl) // 2]
    check("同じ週数の対照（±1週・記事だけ）なら、経過の落ち込みは両方に入り戻さない",
          (len(ctrl), me < base * R.WORSE), (12, False))
    acts = [{"slug": "young0", "at": (at + timedelta(days=5)).isoformat(), "kind": "link"},
            {"slug": "young1", "at": (at + timedelta(days=60)).isoformat(), "kind": "link"}]
    check("比べる前後28日に手を打った記事は対照から外す（期間の外の手は外さない）",
          len(R.controls(daily, "fixed", at, pubs, acts)), 11)
    check("公開日の分からない記事は判定しない（None）", R.controls(daily, "top", at, pubs, []), None)
    check("対照の下限は content_yield のコホートと同じ10本", R.min_controls(), 10)

    import sys
    with tempfile.TemporaryDirectory() as td:
        real = (R.entries, R.published, R.DECIDED, EA.daily_by_slug, EA.interventions, sys.argv)
        ent = [{"slug": "fixed", "at": f"{at.isoformat()} 10:00", "by": "auto_rewrite", "kind": "title",
                "before_title": "前の題", "ok": True, "note": "直しました"}]
        try:
            R.entries, EA.interventions = (lambda: ent), (lambda: [])
            EA.daily_by_slug = lambda: (daily, None, None)
            R.DECIDED = Path(td) / "decided.json"
            few = {k: v for k, v in pubs.items() if not k.startswith("young") or k in ("young0", "young1")}
            R.published = lambda: few
            sys.argv = ["rewrite_rollback.py", "--write"]
            with redirect_stdout(io.StringIO()) as o:
                R.main()
            held = json.loads(R.DECIDED.read_text(encoding="utf-8")) if R.DECIDED.is_file() else {}
            check("対照が10本に満たなければ保留し、判定済みにしない（翌週以降にまた見る）",
                  ("HELD=1" in o.getvalue(), held), (True, {}))
            R.published = lambda: pubs
            with redirect_stdout(io.StringIO()) as o:
                R.main()
            got = json.loads(R.DECIDED.read_text(encoding="utf-8"))
            key = f"fixed@{at.isoformat()}"
            check("対照がそろえば判定し、台帳の形（ratio・control・pos_gain・rolled_back）を保つ",
                  (sorted(got), {"ratio", "control", "pos_gain", "rolled_back"} <= set(got[key]),
                   got[key]["rolled_back"], "KEPT=1" in o.getvalue()), ([key], True, False, True))
        finally:
            R.entries, R.published, R.DECIDED, EA.daily_by_slug, EA.interventions, sys.argv = real


def test_link_boost_pushes_unindexed_articles():
    import inspect
    import time
    import link_boost as LB
    import reindex as RI
    import sites as S
    print("\n■ link_boost --unindexed: URL検査で未登録のままの記事へ、検索1ページ目の記事から")
    check("再通知（reindex --from-cache）は全サイト（コーポレートを含む）を見る",
          ("corporate" in S.load_all(), "sites_mod.load_all()" in inspect.getsource(RI._from_cache)), (True, True))
    today = date(2026, 10, 5)
    cfg = S.load("corporate")
    cat = next(iter(cfg.get("categories") or {"blog": ""}))
    url = lambda s: S.article_url(cfg, {"slug": s, "category": cat}).rstrip("/")
    now = time.mktime(today.timetuple())
    old = (today - timedelta(days=30)).isoformat()
    arts = {s: {"cat": cat, "date": old} for s in ("disc", "crawled", "pass", "dup", "stale", "many", "young")}
    arts["young"]["date"] = (today - timedelta(days=10)).isoformat()
    arts["crawled"]["date"] = (today - timedelta(days=35)).isoformat()
    cache = {url("disc"): {"verdict": "NEUTRAL", "state": "検出 - インデックス未登録", "at": now},
             url("crawled") + "/": {"verdict": "NEUTRAL", "state": "クロール済み - インデックス未登録", "at": now},
             url("pass"): {"verdict": "PASS", "state": "送信して登録されました", "at": now},
             url("dup"): {"verdict": "NEUTRAL", "state": "重複しています。", "at": now},
             url("stale"): {"verdict": "NEUTRAL", "state": "検出 - インデックス未登録", "at": now - 20 * 86400},
             url("many"): {"verdict": "NEUTRAL", "state": "検出 - インデックス未登録", "at": now},
             url("young"): {"verdict": "NEUTRAL", "state": "検出 - インデックス未登録", "at": now}}
    cnt = {s: 3 for s in arts}
    cnt["many"] = LB.RESCUE_FLOOR
    got = LB.unindexed_targets("corporate", arts, cnt, cache=cache, today=today)
    check("未登録（検出/クロール済み）で公開3週を過ぎた記事だけ・古い順（登録済み・重複・古い検査・被リンク十分・公開直後は除く）",
          [t[0] for t in got], ["crawled", "disc"])
    src = inspect.getsource(LB.main)
    check("送り元は検索1ページ目の記事だけ・台帳の種類は link_unindexed・1回5記事まで",
          ("ranks = {s: 1 for s in _page1(site)}" in src, 'kind="link_unindexed"' in src,
           "max_tgt=UNINDEXED_MAX" in src, LB.UNINDEXED_MAX <= 5), (True, True, True, True))
    check("台帳には呼び出し元の種類で残す（集中モードの link_inline と分けて効きを測れる）",
          "note(tgt, src, kind, anchor=anchor, log=log)" in inspect.getsource(LB.run_inline), True)
    wk = (WF / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次で3サイトに当てる", 'link_boost.py "$s" --unindexed --write' in wk, True)
