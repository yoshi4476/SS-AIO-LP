"""別の AI（ChatGPT・契約の Codex）による2人目の採点。合否が採点のぶれで変わりうる記事だけを採点し直し、軸ごとに平均する。

公開前の採点は Claude が2回採点して平均していたが、書くのも採点するのも同じ AI で、一次性は採点ごとに2〜5点動いた
（2026-11-02 の集計。一次性で止めた8本は77〜79点に集まっていた）。同じ AI の読み直しは独立した確かめにならないので、
境目の記事は別の AI の点と平均して合否を決める。基準の数字（rubric.py）は変えない。平均で届けば合格、届かなければ
改善中に戻す（どちらの向きにも同じに扱う）。

採点の工程は鍵を外して動くので、記事の枠では鍵のある機械の手順（.github/actions/own-survey）からこれを呼ぶ。
Codex は読むだけの砂場で、Web 検索なしで動かす。ログには件数だけを出す（記事の名前を出さない）。

  python scripts/cross_score.py --sites <社の id>     # この回に採点した記事のうち境目のものを採点し直す
"""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import quality_loop as Q  # noqa: E402
import rubric as R  # noqa: E402

ENGINE = "ChatGPT"
MAX_PER_RUN = 3             # 1回の枠で採点し直す本数（1本あたり Codex を1〜2回呼ぶ）
LAST_START = 95             # ジョブ（120分）の開始からこの分数を過ぎたら次の1本を始めない（配信の時間を残す）
PER_ONE = 8                 # 1本の採点し直しの見込み（分）


def minutes_used(now=None):
    """記事の枠のジョブの開始（RUN_START）からの分数。分からなければ 0"""
    from datetime import datetime, timezone
    try:
        start = datetime.strptime(os.environ["RUN_START"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return 0
    return ((now or datetime.now(timezone.utc)) - start).total_seconds() / 60


def _ask_codex(prompt, cwd):
    """Codex に1回採点させる（門ではこれを差し替える）。使えなければ None"""
    import shutil
    import subprocess
    import agent_guard
    exe = shutil.which("codex") or shutil.which("codex.cmd")
    if not exe:
        return None
    env = {k: v for k, v in agent_guard.child_env().items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")}
    r = subprocess.run([exe, "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only",
                        "-c", 'model_reasoning_effort="medium"', "-"], input=prompt, cwd=cwd, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=600, env=env)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "")[-160:])
    return r.stdout or ""


ASK = _ask_codex


def score_other(slug, ask=None):
    """別の AI の採点（引用が本文に無ければ1回だけ聞き直す）。返すのは (採点, 理由)"""
    ask = ask or ASK
    article = Q.drop_keys(Q.read(slug), Q.MACHINE_KEYS)
    why = ""
    with tempfile.TemporaryDirectory(prefix="cross_score_", ignore_cleanup_errors=True) as tmp:
        p = Path(tmp) / "article.md"
        p.write_text(article, encoding="utf-8", newline="")
        for retry in ("", Q.RETRY_NOTE):
            prompt = Q.SCORE_PROMPT.format(path="article.md", criteria=R.criteria_text(), retry=retry)
            out = ask(prompt, tmp)
            if out is None:
                return None, "Codex がありません"
            got, why = Q.parse(out, article)
            if got:
                return got, ""
    return None, why


def targets(sites=(), run_id=None, today=None, path=None):
    """この回（CI の実行。手元では今日）に公開前の採点を終えた記事のうち、点が境目のもの。
    返すのは [(slug, 最後の行)]。最後の行は合格（pass）か止め（hold）。すでに2人目が採点した記事は除く"""
    run_id = run_id if run_id is not None else os.environ.get("GITHUB_RUN_ID", "")
    today = today or date.today().isoformat()
    last = {}
    for r in Q.rows(path):
        s = r.get("slug")
        mine = str(r.get("run", "")) == str(run_id) if run_id else str(r.get("at", ""))[:10] == today
        if not s or not mine:
            continue
        if r.get("action") == "cross":
            last[s] = None
        elif r.get("action") in ("pass", "hold") and r.get("mode") in ("new", "pending") and r.get("axes"):
            last[s] = r
    out = []
    for s, r in last.items():
        if r and Q.path_of(s).is_file() and Q._in_sites(s, sites) and Q.near(r["axes"]):
            out.append((s, r))
    return out[:MAX_PER_RUN]


def combine(mine, other):
    """2つの AI の点を軸ごとに平均する（Q.lower と同じまとめ方）"""
    first = {"axes": mine, "quotes": {k: "" for k in Q.AXIS_KEYS}, "weak": {k: [] for k in Q.AXIS_KEYS}}
    res = Q.lower(first, other)
    got = R.judge(res["axes"])
    return {**res, "total": got["total"], "ok": got["ok"], "why": got["why"]}


def apply(slug, row, other):
    """平均で合否を決め直す。返すのは "promoted"（合格にした）/ "demoted"（改善中に戻した）/ "same" """
    sc = combine(row["axes"], other)
    was = row.get("action") == "pass"
    base = {"site": row.get("site") or Q.site_of(slug), "slug": slug, "mode": row.get("mode")}
    Q.record({**base, "action": "cross", "engine": ENGINE, "mine": row["axes"], "other": other["axes"],
              "axes": sc["axes"], "total": sc["total"], "ok": sc["ok"]})
    if sc["ok"] and not was:
        old_day = str(Q.meta_of(Q.read(slug)).get("date") or "")[:10]
        Q.write_pass(slug, sc, attempts=int(row.get("rounds") or 0) + 1,
                     refresh_date=(row.get("mode") == "pending" and old_day and old_day < date.today().isoformat()))
        Q.record({**base, "action": "pass", "state": "passed", "total": sc["total"], "axes": sc["axes"],
                  "rounds": row.get("rounds"), "since": row.get("since", ""), "by": "cross"})
        return "promoted"
    if was and not sc["ok"]:
        Q.mark_improving(slug)
        Q.record({**base, "action": "hold", "state": "improving", "total": sc["total"], "axes": sc["axes"],
                  "need": "", "rounds": row.get("rounds"), "survey": Q.survey_of(slug, base["site"])[0],
                  "body": Q.body_of(slug), "by": "cross"})
        return "demoted"
    return "same"


def main(argv=None):
    args = [a for a in (argv if argv is not None else sys.argv[1:]) if not a.startswith("--")]
    sites = Q.parse_sites(" ".join(args))
    todo = targets(sites)
    res = {"promoted": 0, "demoted": 0, "same": 0, "error": 0}
    for slug, row in todo:
        if minutes_used() + PER_ONE > LAST_START:
            res["error"] += 1
            print(f"CROSS_SCORE_TIME=残り時間が足りないため、残りの記事は1人目の採点のままにします", file=sys.stderr)
            break
        try:
            other, why = score_other(slug)
        except Exception as e:  # noqa: BLE001  ログイン切れ・使用量の上限は、この回の2人目を諦める（合否は1人目のまま）
            print(f"CROSS_SCORE_ENGINE={ENGINE} 失敗: {type(e).__name__}: {str(e)[:120]}", file=sys.stderr)
            res["error"] += 1
            break
        if not other:
            res["error"] += 1
            continue
        res[apply(slug, row, other)] += 1
    print(f"CROSS_SCORE=checked {len(todo)} promoted {res['promoted']} demoted {res['demoted']} "
          f"same {res['same']} error {res['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
