# -*- coding: utf-8 -*-
"""集中モード（4週間・focus-mode.yml）の門（2026-10-05）。

運用者の決定: 4〜10位の題と11〜30位の欠けた問いを、週次に上乗せして4週間だけ直す。
期限を過ぎたら何もせず自分を無効にし、週次（weekly-optimize.yml）と既存の道具の既定の動きは
集中モードの前後で変えない。本物の GSC・claude は動かさない。
"""
import json
import re
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
WF = ROOT / ".github" / "workflows"


def _wf(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _on(y):
    return y.get("on") or y.get(True) or {}


def _steps_text(job):
    return "\n".join(str(s.get("run", "")) + " " + str(s.get("uses", "")) for s in job.get("steps", []))


def test_focus_mode_stops_after_deadline():
    print("\n■ 集中モードは期限を過ぎたら何もせず、自分を無効にする")
    import focus_report as F
    conf = json.loads((ROOT / "data" / "focus_mode.json").read_text(encoding="utf-8"))
    check("期限の台帳（start・until・本数）", {"start", "until", "title_per_run", "stuck_per_run"} <= set(conf), True)
    check("期間は4週間", (date.fromisoformat(conf["until"]) - date.fromisoformat(conf["start"])).days, 28)
    until = date.fromisoformat(conf["until"])
    check("期限の翌日は expired", F.status(conf, until + timedelta(days=1)), "expired")
    check("期限の日までは active", F.status(conf, until), "active")
    check("開始前は before", F.status(conf, date.fromisoformat(conf["start"]) - timedelta(days=1)), "before")
    rep = dict(conf, reports={"w01": {"measured": conf["start"], "window": ["a", "b"], "disagree": "x"}})
    check("期限後は週次の通知に何も足さない", F.line(rep, until + timedelta(days=1)), "")
    check("開始前も何も足さない", F.line(rep, date.fromisoformat(conf["start"]) - timedelta(days=1)), "")

    y = _wf("focus-mode.yml")
    jobs = y["jobs"]
    check("書き直すジョブは active のときだけ", "state == 'active'" in str(jobs["focus"].get("if")), True)
    stop = jobs["stop"]
    check("期限後のジョブは expired のときだけ", "state == 'expired'" in str(stop.get("if")), True)
    st = _steps_text(stop)
    check("期限後は gh workflow disable で自分を止める", "gh workflow disable focus-mode.yml" in st, True)
    check("期限後は書き直しも内部リンクもしない",
          any(x in st for x in ("auto_rewrite", "link_boost", "auto_review", "publish_changed", "wrangler")), False)
    added = set(re.findall(r"for p in ([^;]+); do", st)[0].split()) if "for p in" in st else set()
    check("期限後に残すのは台帳とまとめだけ", added, {"docs/focus-mode-result.md", "data/focus_mode.json"})
    check("自分を止める権限（actions: write）", (y.get("permissions") or {}).get("actions"), "write")


def test_focus_mode_skips_recently_rewritten():
    print("\n■ 直近7日に週次や前の回が手を付けた記事は直さない")
    import auto_rewrite as AR
    today = date(2026, 10, 7)
    rows = [{"at": "2026-10-05 10:40", "by": "auto_rewrite", "slug": "weekly-fixed", "ok": True, "note": "直しました: x"},
            {"at": "2026-10-03 11:00", "by": "auto_rewrite", "slug": "reverted", "ok": False, "note": "検算で戻しました"},
            {"at": "2026-09-20 11:00", "by": "auto_rewrite", "slug": "old", "ok": True, "note": "直しました: x"},
            {"at": "2026-10-06 11:00", "by": "link_boost", "slug": "linked", "ok": True, "note": "x"}]
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "auto_fix.jsonl"
        log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        got = AR.recently_touched(7, log=log, today=today)
        check("7日以内に直した・戻した記事を外す", sorted(got), ["reverted", "weekly-fixed"])
        check("0日なら何も外さない（既定）", AR.recently_touched(0, log=log, today=today), set())
    body = (WF / "focus-mode.yml").read_text(encoding="utf-8")
    calls = re.findall(r"auto_rewrite\.py --write[^\n]*\n?[^\n]*", body)
    check("書き直しは2回（title と stuck）", len(calls), 2)
    check("どちらも --skip-recent 7", all("--skip-recent 7" in c for c in calls), True)
    check("どちらも集中モードの印（--tag focus）", all("--tag focus" in c for c in calls), True)


def test_focus_mode_uses_existing_tools_and_guards():
    print("\n■ 既存の道具と検算だけを使う")
    y = _wf("focus-mode.yml")
    steps = y["jobs"]["focus"]["steps"]
    names = [s.get("name", "") for s in steps]
    runs = [str(s.get("run", "")) for s in steps]
    idx = {n: i for i, n in enumerate(names)}
    check("検算の自己診断を先に通す", "auto_rewrite.py --selftest" in runs[idx["検算が効くか確かめる"]], True)
    for n, kind in (("4〜10位の題を直す", "--kind title"), ("11〜30位の欠けた問いを足す", "--kind stuck")):
        s = steps[idx[n]]
        check(f"{n}: 検算が効くときだけ・最初の回だけ",
              "steps.guard.outputs.ok == 'yes'" in str(s.get("if")) and "run_attempt == 1" in str(s.get("if")), True)
        check(f"{n}: 既存の種別（{kind}）", kind in s["run"], True)
        m = re.search(r"--budget-min (\d+)", s["run"])
        check(f"{n}: 時間の上限がある", bool(m) and int(m.group(1)) <= 60, True)
    budget = sum(int(x) for x in re.findall(r"--budget-min (\d+)", "\n".join(runs)))
    check("書き直しの予算の合計はジョブの上限（180分）に余裕を残す", budget <= 100, True)
    lk = runs[idx["内部リンクを寄せる（11〜30位・4〜10位）"]]
    check("11〜30位へ link_boost --rescue", "--rescue --write" in lk, True)
    check("4〜10位へ link_boost --band=4-10", "--band=4-10 --write" in lk, True)
    check("内部リンクの後に見直し（auto_review --fix）",
          idx["自動修正の見直し（積み上がりと言い回しの偏り）"] > idx["内部リンクを寄せる（11〜30位・4〜10位）"]
          and "auto_review.py --fix" in runs[idx["自動修正の見直し（積み上がりと言い回しの偏り）"]], True)
    check("コミットの前にビルド（機械ゲート）", runs[idx["最終ビルドとコミット"]].lstrip().startswith("python scripts/build.py"), True)
    check("書き直しの種類を足していない（auto_rewrite の WHAT に無い種別を使わない）",
          set(re.findall(r"--kind (\w+)", "\n".join(runs))) <= {"title", "stuck"}, True)

    import link_boost as LB
    arts = {s: {} for s in ("a", "b", "c", "d")}
    pages = {"u/a": {"slug": "a", "pos": 6.0, "imp": 300}, "u/b": {"slug": "b", "pos": 2.0, "imp": 900},
             "u/c": {"slug": "c", "pos": 15.0, "imp": 500}, "u/d": {"slug": "d", "pos": 8.0, "imp": 5}}
    tg, ranks = LB.band_targets("x", arts, {"a": 3, "b": 20, "c": 1, "d": 0}, 4, 10, pages=pages)
    check("--band は帯の中で表示のある記事だけ", [t[0] for t in tg], ["a"])
    check("送り元の判定に使う順位を返す（上位の記事からだけ送る）", ranks["b"] < ranks["a"] < ranks["c"], True)


def test_focus_mode_publishes_and_notifies():
    print("\n■ 直した記事を配信し、検索エンジンへ知らせるまで行う")
    y = _wf("focus-mode.yml")
    st = _steps_text(y["jobs"]["focus"])
    wk = _steps_text(_wf("weekly-optimize.yml")["jobs"]["optimize"])
    for what, s in (("他サイトへ配信", "publish_changed.py --all --since \"$BASE_SHA\" --push"),
                    ("公開前のサイト監査の門", "seo_audit.py --gate"),
                    ("Cloudflare Pages へデプロイ", "wrangler@4.121.0 pages deploy site --project-name=ss-aio-lp"),
                    ("IndexNow", "notify_indexnow.py"), ("Indexing API", "notify_indexing.py"),
                    ("介入の台帳を残す", "git add -f automation/logs/auto_fix.jsonl")):
        check(f"{what}（週次と同じ呼び方）", s in st and s in wk, True)
    check("Bing へ本日更新のURL", "bing_webmaster.py --site" in st, True)
    check("通知は知らせることがある回だけ（--routine）", "notify_slack.py --routine" in st, True)
    env = str(y["jobs"]["focus"]["steps"])
    check("鍵は secrets から渡す（直書きしない）", "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}" in
          (WF / "focus-mode.yml").read_text(encoding="utf-8") and "sk-" not in env, True)


def test_focus_mode_never_runs_with_weekly():
    print("\n■ 週次・記事の執筆と同時に動かない")
    y, w = _wf("focus-mode.yml"), _wf("weekly-optimize.yml")
    check("週次と同じ concurrency のグループ",
          y["jobs"]["focus"]["concurrency"]["group"], w["concurrency"]["group"])
    check("期限後のジョブも同じグループ", y["jobs"]["stop"]["concurrency"]["group"], w["concurrency"]["group"])
    check("期間の判定はグループに並ばない（待機中の run を取り消さない）", "concurrency" in y["jobs"]["gate"], False)
    check("ワークフロー全体にはグループを付けない", "concurrency" in y, False)
    crons = [c["cron"] for c in _on(y)["schedule"]]
    wcrons = [c["cron"] for c in _on(w)["schedule"]]
    # cron は UTC。日本時間の曜日で比べる（UTC 月曜 19:13 は日本時間の火曜 04:13 で、月曜 10:23 の週次とは重ならない）
    def days(c):
        f = c.split()
        shift = 1 if int(f[1]) + 9 >= 24 else 0
        return {str((int(d) + shift) % 7) for d in f[4].split(",")}
    check("週次と同じ曜日（日本時間）に動かない", any(days(a) & days(b) for a in crons for b in wcrons), False)
    check("週2回（日本時間の火・金。初回を 10/6 にするため水・土から変えた）", sorted(days(crons[0])), ["2", "5"])
    pm = _wf("pipeline-multi.yml")
    hours = {int(c["cron"].split()[1]) for c in _on(pm)["schedule"]}
    check("記事の枠が並んでいない時間に始める", any(int(c.split()[1]) in hours for c in crons), False)
    heal = (WF / "selfheal.yml").read_text(encoding="utf-8")
    import ci_rerun as C
    check("落ちたら一時的な失敗だけ再実行（書き直しは最初の回だけ）", "Focus Mode" in C.watch_lists(heal).get("rerun", []), True)


def test_weekly_and_tool_defaults_unchanged():
    print("\n■ 週次と既存の道具の既定の動きは、集中モードの前後で同じ")
    wk = (WF / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次のワークフローは集中モードを参照しない", any(x in wk for x in ("focus", "--skip-recent", "--band", "--tag")), False)
    import auto_rewrite as AR
    import argparse
    import inspect
    src = inspect.getsource(AR.main)
    check("--skip-recent の既定は0（外さない）", 'add_argument("--skip-recent", type=int, default=0' in src, True)
    check("--tag の既定は空", 'add_argument("--tag", default=""' in src, True)
    with tempfile.TemporaryDirectory() as d:
        old_log, old_tag = AR.LOG, AR.TAG
        try:
            AR.LOG, AR.TAG = Path(d) / "log.jsonl", ""
            AR.note("x", "title", True, "直しました: t")
            rec = json.loads(AR.LOG.read_text(encoding="utf-8"))
            check("印の無い既定の台帳は今までと同じ項目", sorted(rec), ["at", "by", "kind", "note", "ok", "slug"])
            AR.TAG = "focus"
            AR.note("y", "title", True, "直しました: t")
            check("--tag を付けたときだけ印が残る",
                  json.loads(AR.LOG.read_text(encoding="utf-8").splitlines()[1]).get("tag"), "focus")
        finally:
            AR.LOG, AR.TAG = old_log, old_tag
    import link_boost as LB
    check("link_boost: --band が無ければ順位帯の指定なし（既定の動き）", LB.parse_band(["x", "ai-lab", "--write"]), None)
    check("link_boost: --rescue だけでは順位帯にならない", LB.parse_band(["ai-lab", "--rescue", "--write"]), None)
    check("link_boost: --band=4-10 を読む", LB.parse_band(["ai-lab", "--band=4-10"]), (4.0, 10.0))
    check("link_boost: 既定の上限は変えていない", (LB.LOW, LB.ADD_PER, LB.RESCUE_FLOOR, LB.RESCUE_ADD), (5, 2, 12, 3))
    msrc = inspect.getsource(LB.main)
    check("link_boost: 種別の台帳は --band のときだけ link_band",
          'note(tgt, src, "link_band" if band else kind)' in msrc
          and 'kind = "link_decay" if tgt in decayed else "link_rescue" if rescue else "link"' in msrc, True)
    del argparse


def test_focus_report_measures_two_ways():
    print("\n■ 効き目は2通りで測り、一致した回だけ出す（0.1節）")
    import focus_report as F
    # 運用者の決定の数字（2026-09-02〜09-29: 4〜10位 201ページ・表示3,956）は整数の境目で出ている
    check("順位帯の境目（整数）", [F.band(p) for p in (3.0, 3.1, 10.0, 10.1, 20.0, 20.1)],
          ["1-3", "4-10", "4-10", "11-20", "11-20", "21+"])
    rows = [{"keys": ["https://x/a/"], "impressions": 10, "clicks": 1, "position": 5.0},
            {"keys": ["https://x/a"], "impressions": 30, "clicks": 2, "position": 9.0}]
    m = F.merge(rows, 0)
    check("末尾スラッシュ違いを1ページに足す", (len(m), m["https://x/a"]["imp"], m["https://x/a"]["clk"]), (1, 40, 3))
    check("順位は表示で重みづけ", m["https://x/a"]["pos"], 8.0)
    a = F.summarize({"u1": {"imp": 100, "clk": 5, "pos": 6.0}, "u2": {"imp": 50, "clk": 1, "pos": 15.0}})
    b = F.summarize({"u1": {"imp": 100, "clk": 5, "pos": 6.0}, "u2": {"imp": 70, "clk": 1, "pos": 15.0}})
    check("一致すれば空", F.agree(a, a), "")
    check("1%を超える食い違いは数字を出さない理由になる", bool(F.agree(a, b)), True)
    old = F.measure
    try:
        F.measure = lambda s, e, *_: {}
        rec = F.run({"start": "2026-10-05", "baseline": ["2026-09-02", "2026-09-29"]}, date(2026, 10, 10))
        check("どのサイトも読めなければ0件を数字として残さない", bool(rec.get("disagree")) and "groups" not in rec, True)
    finally:
        F.measure = old
    rows = [{"at": "2026-10-07 05:00", "by": "auto_rewrite", "slug": "fx", "ok": True, "note": "直しました: t", "tag": "focus"},
            {"at": "2026-10-05 10:00", "by": "auto_rewrite", "slug": "wk", "ok": True, "note": "直しました: t"},
            {"at": "2026-10-07 05:00", "by": "auto_rewrite", "slug": "ng", "ok": False, "note": "戻しました", "tag": "focus"},
            {"at": "2026-10-08 05:00", "by": "link_boost", "slug": "lk", "kind": "link_band", "ok": True, "note": "x"}]
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "auto_fix.jsonl"
        log.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        mine, touched = F.focus_edits("2026-10-05", log)
        check("直した記事＝集中モードの印があり検算を通った分", mine, {"fx"})
        check("対照群から外す＝期間中に直した・上乗せのリンクを受けた記事", touched, {"fx", "wk", "lk"})
    import notify_slack as N
    conf = {"start": "2026-10-05", "until": "2026-11-02",
            "reports": {"w01": {"measured": "2026-10-07", "window": ["2026-09-07", "2026-10-04"],
                                "baseline": a, "current": a,
                                "groups": {"edited": {"n": 1, "before": {"clk": 1}, "after": {"clk": 2}},
                                           "control": {"n": 3, "before": {"clk": 4}, "after": {"clk": 5}}}}}}
    ln = F.line(conf, date(2026, 10, 10))
    check("週次の通知の1行は「情報:」", ln.startswith("情報: 集中モード"), True)
    check("情報の1行だけでは通知を送らない（要対応の語を含まない）", bool(N.NEEDS_ATTENTION.search(ln)), False)
    import findings
    check("findings は情報の行を添える（要対応にはしない）", "focus_report.py --line" in findings.INFO, True)
    y = _wf("focus-mode.yml")
    check("期間中の回は効きを測って残す", "focus_report.py --write" in _steps_text(y["jobs"]["focus"]), True)
    check("期限後にまとめを docs/focus-mode-result.md へ", "focus_report.py --final" in _steps_text(y["jobs"]["stop"])
          and F.DOC.name == "focus-mode-result.md", True)
