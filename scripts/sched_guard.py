# -*- coding: utf-8 -*-
"""定時の起動役（Cloudflare Worker）が起動した回と、予備の GitHub の定時を突き合わせ、同じ予定を2回動かさない

GitHub Actions の schedule は3〜8時間遅れて始まる（2026-09-24〜10-07 の実測）。Cloudflare Workers の定時
（automation/scheduler。予定の表は scripts/scheduler_build.py が作る）が予定の時刻に workflow_dispatch で起動し、
GitHub の schedule は Worker が止まったときの予備として残す。

  python scripts/sched_guard.py           対象のワークフローの最初のジョブが呼ぶ（GitHub Actions の中だけ）。
                                          同じ予定を先に受け持った回があれば、この回は何もしない（sched_go=no）
  python scripts/sched_guard.py --watch   見張り（日次の自動修復・週次の findings）。Worker からの起動が途絶えた・
                                          予定を起動しそびれた・鍵の期限が近い、を要対応で出す

予定の鍵（同じ鍵の回のうち、先に作られた回だけが動く。先の回の成否は問わない。落ちた回・取り消された回は
自動修復 selfheal が受け持つ。後の回まで動くと、同じ枠の記事・同じ日の動画が2本になる）:
  記事の枠（pipeline-multi.yml） 枠の番号＋予定の日（日本時間）
  ほか                          予定の時刻（分まで）
実行の一覧の API は inputs を返さないので、run-name から読む。Worker の回は「記事の枠 12 2026-10-08T20:07+09:00」
（末尾が予定の時刻）、予備の定時の回は「記事の枠（予備の定時） 7 11 * * *」（末尾が cron。予定の時刻は作られた
時刻からさかのぼる）。手で起動した回（scheduled_for が空）は鍵が無く、今までどおり動く（API も呼ばない）。

Worker の回は、渡された鍵の期限（GitHub の応答ヘッダー github-authentication-token-expiration）と最初に動いた時刻を
data/scheduler.json に残す（変わったときだけ GitHub の API でコミットする。公開してよい値だけ）。

出力の印: SCHED_GO=yes|no（判定が動かなかったときも yes。止めると、その予定がまるごと抜ける）
          --watch は SCHEDULER_OK=yes|no|unset（まだ配っていない）|unknown（一覧を読めない・終了コード1）
"""
import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import schedule_guard as SG  # noqa: E402
import scheduler_build as SB  # noqa: E402

JST = timezone(timedelta(hours=9))
STATE = ROOT / "data" / "scheduler.json"
STATE_REL = "data/scheduler.json"
# Worker の起動の間がいちばん空くのは日本時間 03:37〜08:07 の4.5時間（記事の枠が無い）。それより長く無ければ止まっている
WATCH_HOURS = 8
# 予定の時刻からこれだけ過ぎても起動が無ければ「起動しそびれ」（Worker の窓10分＋再試行の待ち）
GRACE_MINUTES = 30
EXPIRY_WARN_DAYS = 30
AT = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})"
TITLE_AT = re.compile(r"(?:^|\s)(?:(?P<slot>\d+)\s+)?(?P<at>" + AT + r")$")
TITLE_CRON = re.compile(r"（予備の定時） (?P<cron>\S+ \S+ \S+ \S+ \S+)$")
EXP_HDR = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s*(UTC|Z|[+-]\d{2}:?\d{2})?$")


def parse_at(s):
    """ISO 8601（2026-10-08T20:07+09:00 など）を UTC の時刻に。時差の無い形・読めない形は None"""
    s = str(s or "").strip()
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.astimezone(timezone.utc) if t.tzinfo else None


def norm_expiry(s):
    """鍵の期限を ISO（UTC）に。GitHub のヘッダーの形（2026-12-31 00:00:00 UTC・+0900）も読む。無い・読めなければ空"""
    s = str(s or "").strip()
    t = parse_at(s)
    if t is None and s:
        m = EXP_HDR.match(s)
        if m:
            off = m.group(3) or "UTC"
            off = "+00:00" if off in ("UTC", "Z") else off[:3] + ":" + off[-2:]
            t = parse_at(f"{m.group(1)}T{m.group(2)}{off}")
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t else ""


def jst_day(t):
    return t.astimezone(JST).date().isoformat()


def _created(r):
    return parse_at((r or {}).get("created_at"))


def key(at, slot, slot_mode):
    """予定の鍵。記事の枠は (枠の番号, 予定の日)、ほかは予定の時刻（分まで・UTC）"""
    if at is None:
        return None
    if slot_mode:
        return ("slot", int(slot), jst_day(at)) if str(slot or "").isdigit() else None
    return ("at", at.strftime("%Y-%m-%dT%H:%M"))


def sched_key(cron, created, crons_list, slot_mode):
    """予備の定時の回の鍵。予定の時刻は作られた時刻からさかのぼった直近の cron（定時は遅れても早まらない）"""
    if not cron or created is None:
        return None
    at = SG.last_slot([cron], created)
    return key(at, crons_list.index(cron) if cron in crons_list else None, slot_mode)


def run_key(r, crons_list, slot_mode):
    """実行の一覧の1件から予定の鍵。手で起動した回・読めない回は None"""
    title = str(r.get("display_title") or "")
    if r.get("event") == "workflow_dispatch":
        m = TITLE_AT.search(title)
        return key(parse_at(m.group("at")), m.group("slot"), slot_mode) if m else None
    if r.get("event") == "schedule":
        m = TITLE_CRON.search(title)
        # run-name を足す前の回は表示名がワークフロー名だけ。cron が1つのワークフローならそれと分かる
        cron = m.group("cron") if m else (crons_list[0] if len(crons_list) == 1 else "")
        return sched_key(cron, _created(r), crons_list, slot_mode)
    return None


def my_key(event, cron, inputs, created, crons_list, slot_mode):
    """この回の鍵。手で起動した回（scheduled_for が空）は None"""
    inputs = inputs or {}
    if event == "workflow_dispatch":
        at = parse_at(inputs.get("scheduled_for"))
        return key(at, inputs.get("slot"), slot_mode) if at else None
    if event == "schedule":
        return sched_key(cron, created, crons_list, slot_mode)
    return None


def decide(my_id, mkey, my_created, runs, crons_list, slot_mode):
    """(動かすか, 先に受け持った回)。同じ鍵の回のうち、先に作られた回（同じ時刻なら番号の小さい回）だけが動く"""
    if mkey is None:
        return True, None
    order = lambda r, c: (c, int(r.get("id") or 0))
    mine = (my_created, int(my_id or 0))
    first, first_at = None, None
    for r in runs:
        if str(r.get("id")) == str(my_id) or run_key(r, crons_list, slot_mode) != mkey:
            continue
        c = _created(r)
        if c is None or order(r, c) >= mine:
            continue
        if first is None or order(r, c) < first_at:
            first, first_at = r, order(r, c)
    return first is None, first


def load_state(path=None):
    try:
        return json.loads(Path(path or STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def dump_state(st):
    return json.dumps(st, ensure_ascii=False, indent=1) + "\n"


def merged_state(cur, inputs, now):
    """Worker の回が渡した値を足した記録（変わらなければ cur と同じもの）"""
    new = dict(cur)
    if not new.get("first_seen"):
        new["first_seen"] = (parse_at(inputs.get("scheduled_for")) or now).astimezone(JST).isoformat(timespec="minutes")
    exp = norm_expiry(inputs.get("token_expiry"))
    if exp != new.get("token_expiry", ""):
        new["token_expiry"] = exp
    return new


def gh_put(path, body):
    r = subprocess.run(["gh", "api", "-X", "PUT", path, "--input", "-"], input=json.dumps(body),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(f"gh api PUT {path[:60]}: {(r.stderr or '').strip()[:160]}")
    return json.loads(r.stdout or "{}")


def record(repo, ref, inputs, now, get=SG.gh_api, put=gh_put):
    """Worker の回の記録を data/scheduler.json に残す。変わったときだけ、最新の master を読み直してコミットする"""
    if merged_state(load_state(), inputs, now) == load_state():
        return "記録は変わりません"
    path = f"repos/{repo}/contents/{STATE_REL}"
    try:
        got = get(f"{path}?ref={ref}")
        remote, sha = json.loads(base64.b64decode(got.get("content") or "e30=").decode("utf-8")), got.get("sha")
    except RuntimeError as e:
        if "404" not in str(e) and "Not Found" not in str(e):
            raise
        remote, sha = {}, None
    new = merged_state(remote, inputs, now)
    if new == remote:
        return "ほかの回が先に記録しました"
    body = {"message": "定時の起動役の記録（最初の起動・鍵の期限）", "branch": ref,
            "content": base64.b64encode(dump_state(new).encode("utf-8")).decode("ascii")}
    if sha:
        body["sha"] = sha
    put(path, body)
    return f"記録しました: {', '.join(k for k in new if new.get(k) != remote.get(k))}"


def check(wf, event, cron, inputs, run_id, now, runs_of):
    """この回を動かすか。(動かすか, 理由)。runs_of(wf) は同じワークフローの実行の一覧（新しい順）"""
    cfg = SB.TARGETS.get(wf)
    if cfg is None:
        return True, f"{wf} は定時の起動役の対象ではありません。そのまま動かします"
    if event == "workflow_dispatch" and not parse_at((inputs or {}).get("scheduled_for")):
        return True, "手で起動した回です（予定の時刻が無い）。そのまま動かします"
    slot_mode, crons_list = bool(cfg.get("slot")), SG.crons(wf)
    runs = runs_of(wf)
    me = next((r for r in runs if str(r.get("id")) == str(run_id)), None)
    created = _created(me) or now
    k = my_key(event, cron, inputs, created, crons_list, slot_mode)
    if k is None:
        return True, f"予定の鍵が決まりません（{event}・{cron or '-'}）。そのまま動かします"
    go, first = decide(run_id, k, created, runs, crons_list, slot_mode)
    what = f"{cfg['label']} {'枠' + str(k[1]) + ' ' + k[2] if k[0] == 'slot' else k[1] + 'Z'}"
    if go:
        return True, f"{what} はこの回が受け持ちます"
    return False, (f"{what} は run {first.get('id')}（{first.get('event')}・{first.get('conclusion') or first.get('status')}・"
                   f"{first.get('created_at')}）が先に受け持っています。この回は何もしません")


def emit(go):
    print(f"SCHED_GO={'yes' if go else 'no'}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"sched_go={'yes' if go else 'no'}\n")


def guard(env=None, now=None):
    env = os.environ if env is None else env
    repo = env.get("GITHUB_REPOSITORY", "")
    wf = env.get("GITHUB_WORKFLOW_REF", "").split("@")[0].rsplit("/", 1)[-1]
    event = env.get("GITHUB_EVENT_NAME", "")
    payload = {}
    p = env.get("GITHUB_EVENT_PATH", "")
    if p and Path(p).is_file():
        payload = json.loads(Path(p).read_text(encoding="utf-8"))
    inputs, cron = payload.get("inputs") or {}, payload.get("schedule") or ""
    now = now or datetime.now(timezone.utc)
    try:
        go, why = check(wf, event, cron, inputs, env.get("GITHUB_RUN_ID", ""), now,
                        lambda w: SG.runs_of(repo, w, 100))
    except Exception as e:
        go, why = True, f"判定が動きませんでした（{str(e)[:160]}）。止めるとこの予定が抜けるので動かします"
        print(f"::warning::{why}")
    print(why)
    if event == "workflow_dispatch" and parse_at(inputs.get("scheduled_for")):
        try:
            print(record(repo, SB.REF, inputs, now))
        except Exception as e:
            print(f"::warning::起動役の記録（data/scheduler.json）を書けませんでした（{str(e)[:160]}）")
    emit(go)
    return 0


def last_due(entries, now):
    """猶予（GRACE_MINUTES）より前の、いちばん新しい予定 (時刻, 予定の行)"""
    best = None
    for e in entries:
        t = SG.last_slot([e["cron"]], now - timedelta(minutes=GRACE_MINUTES))
        if t and (best is None or t > best[0]):
            best = (t, e)
    return best


def watch_verdict(state, runs_by_wf, active, table, now):
    """見張りの判定。(出す行, 状態 yes|no|unset)。runs_by_wf は workflow_dispatch の回の一覧（新しい順）"""
    lines, bad = [], []
    worker = [r for rs in runs_by_wf.values() for r in rs
              if r.get("event") == "workflow_dispatch" and TITLE_AT.search(str(r.get("display_title") or ""))]
    newest = max((c for c in map(_created, worker) if c), default=None)
    marks = [t for t in (parse_at(state.get("deployed_at")), parse_at(state.get("first_seen"))) if t]
    since = min(marks) if marks else newest
    if since is None:
        return ["定時の起動役（Cloudflare Worker）はまだ動いていません（未配備。配るまでは GitHub の定時が遅れて動きます）"], "unset"
    last = newest or since
    gap = (now - last).total_seconds() / 3600
    if gap > WATCH_HOURS:
        bad.append(f"要対応: 定時の起動役（Cloudflare Worker）からの起動が{gap:.0f}時間ありません"
                   f"（最後: {last.astimezone(JST):%m/%d %H:%M}）。Worker が止まったか、鍵（GITHUB_TOKEN）が切れた・"
                   "権限が外れています。Cloudflare の Workers のログを見て、python scripts/scheduler_deploy.py --set-token で"
                   "鍵を入れ直すか python scripts/scheduler_deploy.py で配り直す（それまでは GitHub の定時が遅れて動く）")
    else:
        lines.append(f"最後の起動: {last.astimezone(JST):%m/%d %H:%M}（{gap:.1f}時間前）")
        for wf, cfg in SB.TARGETS.items():
            if not active.get(wf, True):
                lines.append(f"{cfg['label']}: ワークフローを止めてあるので見ません")
                continue
            ents = [e for e in table["entries"] if e["wf"] == wf]
            due = last_due(ents, now)
            if not due or due[0] < since:
                continue
            slot_mode, crons_list = bool(cfg.get("slot")), [e["cron"] for e in ents]
            k = key(due[0], due[1]["inputs"].get("slot"), slot_mode)
            if not any(run_key(r, crons_list, slot_mode) == k for r in runs_by_wf.get(wf, [])):
                bad.append(f"要対応: {cfg['label']}（{wf}）の {due[0].astimezone(JST):%m/%d %H:%M} の予定を起動役が起動していません。"
                           "Cloudflare の Workers のログで、その時刻の起動の失敗（4xx/5xx）を確かめる（GitHub の定時が遅れて代わりに動く）")
    exp = norm_expiry(state.get("token_expiry")) or norm_expiry(state.get("token_expiry_manual"))
    t = parse_at(exp)
    if t:
        days = (t - now).days
        how = "" if norm_expiry(state.get("token_expiry")) else "・手で記録した期限"
        if days < EXPIRY_WARN_DAYS:
            bad.append(f"要対応: 定時の起動役の鍵（GitHub の fine-grained の鍵）の期限まで残り{days}日"
                       f"（{t.astimezone(JST):%Y-%m-%d}{how}）。同じ権限（SS-AIO-LP の Actions: Read and write）で作り直し、"
                       ".env の SCHEDULER_GITHUB_TOKEN を書き換えて python scripts/scheduler_deploy.py --set-token")
        else:
            lines.append(f"鍵の期限: {t.astimezone(JST):%Y-%m-%d}（残り{days}日{how}）")
    else:
        lines.append("鍵の期限: GitHub の応答に期限のヘッダーが無い（期限なしの鍵）。切れた・外されたときは上の起動の途絶えで知らせる"
                     "（期限つきの鍵に替えれば自動で記録する。手で入れるなら python scripts/scheduler_deploy.py --expiry YYYY-MM-DD）")
    return lines + bad, ("no" if bad else "yes")


def watch(repo, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        table = SB.build()
        active, runs = {}, {}
        for wf in SB.TARGETS:
            active[wf] = SG.gh_api(f"repos/{repo}/actions/workflows/{wf}").get("state", "active") == "active"
            runs[wf] = SG.gh_api(f"repos/{repo}/actions/workflows/{wf}/runs?event=workflow_dispatch&per_page=20"
                                 "&exclude_pull_requests=true").get("workflow_runs") or []
    except Exception as e:
        print(f"見張りが動きませんでした（{str(e)[:160]}）。GH_TOKEN と actions: read を確かめる")
        print("SCHEDULER_OK=unknown")
        return 1
    lines, ok = watch_verdict(load_state(), runs, active, table, now)
    print("\n".join(lines))
    print(f"SCHEDULER_OK={ok}")
    return 0


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if "--watch" in a:
        # 見張りだけに渡す鍵（GH_TOKEN にすると、同じ工程のほかの検査の gh の動きまで変わる）
        if os.environ.get("SCHED_GH_TOKEN"):
            os.environ["GH_TOKEN"] = os.environ["SCHED_GH_TOKEN"]
        repo = a[a.index("--repo") + 1] if "--repo" in a else os.environ.get("GITHUB_REPOSITORY", SB.REPO)
        return watch(repo)
    return guard()


if __name__ == "__main__":
    sys.exit(main())
