# -*- coding: utf-8 -*-
"""定時のワークフローの取りこぼしを拾って起動し、同じ回を2度動かさない

GitHub の schedule は遅れも取りこぼしもある。2026-10-05（月）の Weekly Optimize は予定（10:23 JST）を
3時間過ぎても始まらず手で起動し、前の週も5.5時間遅れた。落ちた run は自動修復（selfheal.yml）が拾うが、
**始まらなかった run は何も起きないので誰も拾わなかった**。

  --missed <file>       予定の時刻から --after-hours 時間たっても、その回（--period の区切り）に run が1つも
                        無ければ取りこぼし。--dispatch を付けると gh workflow run で起動する
  --already-ran <file>  この区切りで、ほかの run が既に成功で終わったか、先に始まって動いている最中か。
                        各ワークフローの最初のジョブが呼び、済んでいれば何もせずに終わる
                        （遅れて来た予定の run と、手で起動した run・見張りが起動した run が重ならない）

区切り（--period）: week = 日本時間の月曜0時から / day = 日本時間のその日の0時から。
予定の時刻は、そのワークフローの cron をそのまま読む（ここに時刻を書き写さない）。

使い方:
    python scripts/schedule_guard.py --missed weekly-optimize.yml --after-hours 6 --max-hours 48 --period week --avoid-busy --dispatch
    python scripts/schedule_guard.py --already-ran weekly-optimize.yml --week --run-id "$GITHUB_RUN_ID"

出力の印:
  --missed       SCHEDULE_OK=yes（始まっている・まだ待つ・止めてある）/ no（取りこぼし）。起動したら DISPATCHED=yes
  --already-ran  ALREADY_RAN=yes|no
判定が動かなかった（gh が使えない等）ときだけ終了コード1（8.7節の決まり）。
gh を呼ぶのは gh_api と dispatch だけ（門で差し替える。今の時刻は _now）。
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WF = ROOT / ".github" / "workflows"
JST = timezone(timedelta(hours=9))
# 同じ concurrency グループ（article-pipeline）で待っている run。ここで起動すると、待っている方が
# 後から来た方に取り消される（GitHub の仕様で、同じグループで待てるのは1件だけ）
BUSY_WORKFLOWS = ("pipeline-multi.yml", "pipeline.yml", "weekly-optimize.yml", "focus-mode.yml")
WAITING = ("queued", "pending", "waiting", "requested")


def gh_api(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(f"gh api {path[:60]}: {(r.stderr or '').strip()[:120]}")
    return json.loads(r.stdout or "{}")


def dispatch(repo, wf, ref):
    cmd = ["gh", "workflow", "run", wf, "--repo", repo] + (["--ref", ref] if ref else [])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(f"gh workflow run {wf}: {(r.stderr or '').strip()[:120]}")


def _now():
    return datetime.now(timezone.utc)


def crons(wf, text=None):
    """ワークフローの schedule の cron（UTC）。時刻を書き写すと、cron を変えたときに見張りだけ古いまま残る"""
    t = text if text is not None else (WF / wf).read_text(encoding="utf-8")
    return re.findall(r'^\s*-\s*cron:\s*"([^"]+)"', t, re.M)


def _field(s, lo, hi):
    """cron の1つの欄。"*" は None（どれでもよい）。"1,4"・"1-5"・"*/4"・"0-30/10" を読む"""
    if s == "*":
        return None
    out = set()
    for part in s.split(","):
        rng, _, step = part.partition("/")
        if rng == "*":
            a, b = lo, hi
        elif "-" in rng:
            a, b = (int(x) for x in rng.split("-"))
        else:
            a = b = int(rng)
            if step:
                b = hi
        out.update(range(a, b + 1, int(step) if step else 1))
    return {v for v in out if lo <= v <= hi}


def fields(cron):
    """cron（UTC）の5つの欄（分・時・日・月・曜日）。曜日の 7（日曜）は 0 にそろえる"""
    mi, ho, dom, mon, dow = cron.split()
    mi, ho = _field(mi, 0, 59), _field(ho, 0, 23)
    dom, mon, dow = _field(dom, 1, 31), _field(mon, 1, 12), _field(dow, 0, 7)
    if dow is not None and 7 in dow:
        dow = (dow - {7}) | {0}
    return mi, ho, dom, mon, dow


def day_ok(d, dom, mon, dow):
    """その日（UTC の日付）に予定があるか"""
    ok_dom = dom is None or d.day in dom
    ok_dow = dow is None or (d.weekday() + 1) % 7 in dow
    # cron の決まり: 日と曜日の両方を指定したときは、どちらかに合えばよい
    ok = (ok_dom or ok_dow) if (dom is not None and dow is not None) else (ok_dom and ok_dow)
    return ok and (mon is None or d.month in mon)


def fires(cron_list, start, end):
    """start 以上 end 未満の予定の時刻（UTC）を早い順に（定時の起動役の表を確かめる門が使う）"""
    out = set()
    for c in cron_list:
        mi, ho, dom, mon, dow = fields(c)
        d = start.date()
        while d <= end.date():
            if day_ok(d, dom, mon, dow):
                for h in (ho if ho is not None else range(24)):
                    for m in (mi if mi is not None else range(60)):
                        t = datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)
                        if start <= t < end:
                            out.add(t)
            d += timedelta(days=1)
    return sorted(out)


def last_slot(cron_list, now):
    """now 以前でいちばん新しい予定の時刻（UTC）。cron の曜日は 0=日曜"""
    best = None
    for c in cron_list:
        mi, ho, dom, mon, dow = fields(c)
        for back in range(0, 40):
            d = (now - timedelta(days=back)).date()
            if not day_ok(d, dom, mon, dow):
                continue
            hits = [datetime(d.year, d.month, d.day, h, m, tzinfo=timezone.utc)
                    for h in sorted(ho if ho is not None else range(24))
                    for m in sorted(mi if mi is not None else range(60))]
            hits = [t for t in hits if t <= now]
            if hits:
                best = max(best, hits[-1]) if best else hits[-1]
                break
    return best


def period_start(t, period):
    """t を含む区切りの始まり（UTC）。週は日本時間の月曜0時、日は日本時間のその日の0時"""
    j = t.astimezone(JST)
    s = datetime(j.year, j.month, j.day, tzinfo=JST)
    if period == "week":
        s -= timedelta(days=j.weekday())
    return s.astimezone(timezone.utc)


def _at(r):
    return datetime.fromisoformat(str(r.get("created_at", "")).replace("Z", "+00:00"))


def missed(cron_list, runs, now, after_hours, max_hours, period):
    """(判定, 理由)。判定は started / wait / none / missed / too_late"""
    slot = last_slot(cron_list, now)
    if slot is None:
        return "none", "予定の時刻がありません"
    since = period_start(slot, period)
    got = [r for r in runs if _at(r) >= since]
    if got:
        return "started", f"{slot.astimezone(JST):%m/%d %H:%M} の回は始まっています（run {got[-1].get('id')}）"
    late = (now - slot).total_seconds() / 3600
    if late < after_hours:
        return "wait", f"{slot.astimezone(JST):%m/%d %H:%M} の回はまだ {late:.1f} 時間（{after_hours} 時間までは待つ）"
    if late > max_hours:
        return "too_late", f"{slot.astimezone(JST):%m/%d %H:%M} の回が始まらないまま {late:.1f} 時間（起動してよいのは {max_hours} 時間まで）"
    return "missed", f"{slot.astimezone(JST):%m/%d %H:%M} の回が {late:.1f} 時間たっても始まっていません"


def already_ran(runs, now, period, my_id):
    """この区切りで、ほかに成功で終わった run か、自分より先に始まって動いている run。無ければ None。
    先に始まった方だけを残すのは、同時に始まった2つが互いを見て両方とも止まらないため"""
    since = period_start(now, period)
    for r in runs:
        if str(r.get("id")) == str(my_id) or _at(r) < since:
            continue
        if r.get("status") == "completed":
            if r.get("conclusion") == "success":
                return r
        elif my_id is None or int(r.get("id", 0)) < int(my_id):
            return r
    return None


def busy(runs_by_wf):
    """同じグループで待っている run があるか（あれば起動を見送る。次の見張りがもう一度見る）"""
    return [f"{wf} run {r.get('id')}" for wf, rs in runs_by_wf.items() for r in rs if r.get("status") in WAITING]


def runs_of(repo, wf, n=30):
    return gh_api(f"repos/{repo}/actions/workflows/{wf}/runs?per_page={n}").get("workflow_runs") or []


def _arg(a, k, default=None):
    return a[a.index(k) + 1] if k in a else default


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    repo = _arg(a, "--repo", os.environ.get("GITHUB_REPOSITORY", ""))
    period = "week" if "--week" in a else "day" if "--day" in a else _arg(a, "--period", "week")
    now = _now()
    if not repo:
        print("GITHUB_REPOSITORY がありません")
        return 1
    try:
        if "--already-ran" in a:
            wf = _arg(a, "--already-ran")
            r = already_ran(runs_of(repo, wf), now, period, _arg(a, "--run-id", os.environ.get("GITHUB_RUN_ID")))
            if r:
                print(f"この区切りは run {r.get('id')}（{r.get('event')}・{r.get('conclusion') or r.get('status')}）が"
                      "受け持っています。この回は何もしません")
            print(f"ALREADY_RAN={'yes' if r else 'no'}")
            return 0
        wf = _arg(a, "--missed")
        if not wf:
            print(__doc__)
            return 1
        st = gh_api(f"repos/{repo}/actions/workflows/{wf}").get("state", "")
        if st != "active":
            print(f"{wf} は止めてあります（{st}）。起動しません\nSCHEDULE_OK=yes")
            return 0
        verdict, why = missed(crons(wf), runs_of(repo, wf), now, float(_arg(a, "--after-hours", 6)),
                              float(_arg(a, "--max-hours", 48)), period)
        print(f"{wf}: {why}")
        if verdict == "too_late":
            # 毎日の見張りで同じ回を何度も知らせない（起動してよい時間を過ぎた最初の1日だけ）
            slot = last_slot(crons(wf), now)
            if (now - slot).total_seconds() / 3600 <= float(_arg(a, "--max-hours", 48)) + 24:
                print(f"要対応: {wf} の予定の回が始まらず、自動で起動してよい時間も過ぎました（必要なら手で起動）")
        if verdict != "missed":
            print("SCHEDULE_OK=yes")
            return 0
        if "--avoid-busy" in a:
            b = busy({w: runs_of(repo, w, 10) for w in BUSY_WORKFLOWS})
            if b:
                print(f"同じグループで待っている run があるため、今は起動しません（{', '.join(b[:3])}）。次の見張りで見ます")
                print("SCHEDULE_OK=no")
                return 0
        if "--dispatch" in a:
            dispatch(repo, wf, os.environ.get("GITHUB_REF_NAME", ""))
            print(f"取りこぼしを起動しました: {wf}\nDISPATCHED=yes")
        print("SCHEDULE_OK=no")
        return 0
    except Exception as e:
        print(f"見張りが動きませんでした（{str(e)[:120]}）")
        return 1


if __name__ == "__main__":
    sys.exit(main())
