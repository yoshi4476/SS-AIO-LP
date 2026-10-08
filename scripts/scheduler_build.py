# -*- coding: utf-8 -*-
"""定時の起動役（Cloudflare Worker・automation/scheduler）が読む予定の表を、ワークフローの cron から作る

GitHub Actions の schedule は3〜8時間遅れて始まる（2026-09-24〜10-07 の実測。記事の枠は後ろの枠ほど遅れ、
週次は6時間遅れて来た回が取り消された）。Cloudflare Workers の定時が5分ごとに起き、この表で予定の時刻を迎えた
ワークフローを workflow_dispatch で起動する。GitHub の schedule は予備として残す（scripts/sched_guard.py が
同じ予定を2回動かさない）。

**表は手で書かない。** cron を変えたら、これを流して automation/scheduler/schedule.json をコミットする。
Worker は5分ごとに master の表を読み直すので、cron の変更だけなら Worker を配り直さなくてよい
（読めないときは配ったときの表を使う）。表とワークフローがずれたら門（gates_history_h62）が止める。

    python scripts/scheduler_build.py           # 表を書く
    python scripts/scheduler_build.py --check   # 書かずに、今の表がワークフローと合っているかだけ見る

出力の印: SCHEDULE_TABLE_OK=yes|no（--check）
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import schedule_guard as SG  # noqa: E402

REPO = "yoshi4476/SS-AIO-LP"
REF = "master"
TABLE = ROOT / "automation" / "scheduler" / "schedule.json"
TABLE_URL = f"https://raw.githubusercontent.com/{REPO}/{REF}/automation/scheduler/schedule.json"
# Worker の定時（wrangler.jsonc の crons）と同じ間隔。窓は2回分（1回起きそびれても次の回が拾う。
# 同じ予定は GitHub の実行の一覧を見てから起動するので、2回分の窓で二重に起動しない）
TICK_MINUTES = 5
LOOKBACK_MINUTES = 10
# 遅れると困るもの。label は各ワークフローの run-name に出す語と同じ（門が突き合わせる）。
# slot は記事の枠: cron の並び順が枠の番号（pipeline-multi.yml の select と同じ数え方）
TARGETS = {
    "pipeline-multi.yml": {"label": "記事の枠", "slot": True},
    "pipeline.yml": {"label": "同日救済"},
    "daily-video.yml": {"label": "記事動画"},
    "weekly-optimize.yml": {"label": "週次"},
    "daily-kpi.yml": {"label": "日次KPI"},
    "focus-mode.yml": {"label": "集中モード"},
    "monthly-report.yml": {"label": "月次"},
}
# 起動のたびに Worker が足す入力（各ワークフローの workflow_dispatch に同じ名前で置く）
COMMON_INPUTS = ("scheduled_for", "token_expiry")
# pipeline.yml の定時は救済だけ（記事は pipeline-multi が書く。学び L0101）。手で起動した回の既定は main なので、
# 起動役は mode=rescue を必ず渡す。救済に回らない cron があれば表を作らない（main で起動すると記事が二重になる）
RESCUE = re.compile(r'github\.event\.schedule \}\}" = "([^"]+)" \]; then\s*\n\s*echo "mode=rescue"')


def read_wf(name):
    return (SG.WF / name).read_text(encoding="utf-8")


def rescue_crons(text):
    return set(RESCUE.findall(text))


def inputs_for(wf, cron, idx, text):
    """その予定を起動するときの入力（COMMON_INPUTS は Worker が足す）"""
    if TARGETS[wf].get("slot"):
        return {"slot": str(idx)}
    if wf == "pipeline.yml":
        if cron not in rescue_crons(text):
            raise ValueError(f"pipeline.yml の定時 {cron} が救済（mode=rescue）に回っていません。"
                             "起動役は救済しか起動しません（記事は pipeline-multi が書く）")
        return {"mode": "rescue"}
    return {}


def expand(cron):
    """Worker が読む形（欄ごとの値の一覧。null はどれでもよい）。読み方は schedule_guard と同じ"""
    mi, ho, dom, mon, dow = SG.fields(cron)
    s = lambda v: None if v is None else sorted(v)
    return {"minute": s(mi), "hour": s(ho), "dom": s(dom), "month": s(mon), "dow": s(dow)}


def build(read=read_wf):
    entries = []
    for wf, cfg in TARGETS.items():
        text = read(wf)
        crons = SG.crons(wf, text)
        if not crons:
            raise ValueError(f"{wf} に schedule の cron がありません")
        if len(set(crons)) != len(crons):
            raise ValueError(f"{wf} に同じ cron が2つあります（予定の鍵と枠の番号が決まらない）")
        for i, c in enumerate(crons):
            entries.append({"wf": wf, "label": cfg["label"], "cron": c, **expand(c),
                            "inputs": inputs_for(wf, c, i, text)})
    return {
        "version": 1,
        "note": "scripts/scheduler_build.py が .github/workflows/*.yml の cron から作る。手で書かない",
        "repo": REPO,
        "ref": REF,
        "table_url": TABLE_URL,
        "tick_minutes": TICK_MINUTES,
        "lookback_minutes": LOOKBACK_MINUTES,
        "common_inputs": list(COMMON_INPUTS),
        "entries": entries,
    }


def dumps(table):
    """1予定1行（差分が読める形）"""
    head = {k: v for k, v in table.items() if k != "entries"}
    lines = ["{"] + [f" {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}," for k, v in head.items()]
    rows = [" " + json.dumps(e, ensure_ascii=False, separators=(", ", ": ")) for e in table["entries"]]
    return "\n".join(lines + [' "entries": [', ",\n".join(rows), " ]", "}"]) + "\n"


def write():
    """表を書く。書き換えたら True"""
    new = dumps(build())
    old = TABLE.read_text(encoding="utf-8") if TABLE.is_file() else ""
    if new == old:
        return False
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    TABLE.write_text(new, encoding="utf-8", newline="\n")
    return True


def main(argv=None):
    a = sys.argv[1:] if argv is None else argv
    if "--check" in a:
        ok = TABLE.is_file() and TABLE.read_text(encoding="utf-8") == dumps(build())
        if not ok:
            print("予定の表がワークフローの cron と合いません。python scripts/scheduler_build.py を流してコミットしてください")
        print(f"SCHEDULE_TABLE_OK={'yes' if ok else 'no'}")
        return 0
    changed = write()
    t = build()
    print(f"{TABLE.relative_to(ROOT).as_posix()}: {len(t['entries'])}件の予定"
          f"（{'書き換えました。コミットしてください' if changed else '変わりません'}）")
    for wf, cfg in TARGETS.items():
        n = sum(1 for e in t["entries"] if e["wf"] == wf)
        print(f"  {cfg['label']:<6} {wf:<20} {n}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
