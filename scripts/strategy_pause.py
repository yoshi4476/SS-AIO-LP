# -*- coding: utf-8 -*-
"""対照群と比べて効きが出ない施策を、自動で4週休ませる（2026-11-23 運用者の決定「自動で休む仕組みにする」）。

週次の effect_ab が「対照群と差が無い」「効かない」と判定した種類を、ここに休止として書く。施策を当てる側
（link_boost・auto_rewrite）は paused() を見て、その種類を当てない。休んだ後は自動で戻り、PAUSE_DAYS + RETRY_DAYS
たつまでは次の休止を入れない（休む前の古い記録だけで、すぐまた休ませないため。戻ってから当てた分で測り直す）。

休ませるのは、効きが流入や順位で測れる施策だけ（PAUSABLE）。stock（出どころの無い体験談の決まり文句を直す）は
流入のためではなく、事実と違う文を残さないための直しなので休ませない。
"""
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "strategy_pause.json"
PAUSABLE = {"link_rescue", "link_decay", "title"}
PAUSE_DAYS = 28
RETRY_DAYS = 56


def _today(today=None):
    return today or date.today()


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def paused(kind, today=None):
    rec = load().get(str(kind)) or {}
    return bool(rec.get("until")) and _today(today).isoformat() < rec["until"]


def note(weak, today=None, why=""):
    """効かないと判定された種類を休ませる。新しく休ませた種類を返す"""
    t = _today(today)
    st = load()
    added = []
    for k in sorted(set(weak) & PAUSABLE):
        rec = st.get(k) or {}
        if rec.get("until") and t.isoformat() < rec["until"]:
            continue                                   # 休んでいる最中
        if rec.get("next_ok") and t.isoformat() < rec["next_ok"]:
            continue                                   # 戻ってから測り直している最中
        st[k] = {"from": t.isoformat(), "until": (t + timedelta(days=PAUSE_DAYS)).isoformat(),
                 "next_ok": (t + timedelta(days=PAUSE_DAYS + RETRY_DAYS)).isoformat(),
                 "why": why or "対照群と比べて効きが出ない（effect_ab）"}
        added.append(k)
    if added:
        FILE.write_text(json.dumps(st, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return added


def report(today=None):
    st = load()
    for k, rec in sorted(st.items()):
        if paused(k, today):
            print(f"  休止中: {k}（{rec['until']} まで。{rec.get('why', '')}）")
