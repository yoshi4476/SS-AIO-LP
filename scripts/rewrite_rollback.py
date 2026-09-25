# -*- coding: utf-8 -*-
"""打った手が効かなかったら、元に戻す。

**なぜ要るか**: auto_rewrite はタイトル・説明文を直して終わりだった。効いたかは
effect_ab が出すが、悪化した記事もそのまま残る。「当てる」と「戻す」が揃って
初めて、直しは実験になる。

判定は effect_ab と同じ: 直した日の前後28日で表示の倍率を出し、**同じ期間の
触っていない記事（対照群）の中央値**と比べる。対照の8割を下回り、順位も
良くなっていなければ、直す前のタイトル・説明文へ戻す。

  python scripts/rewrite_rollback.py            # 判定だけ
  python scripts/rewrite_rollback.py --write    # 戻す
出す印: ROLLBACK_OK=yes / ROLLED_BACK=<本> / KEPT=<本>
戻せるのは、直したときに before_title を台帳（auto_fix.jsonl）に残した分だけ。
判定した分は data/rollback_decisions.json に残し、二度は判定しない。
"""
import argparse
import json
import re
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
DECIDED = ROOT / "data" / "rollback_decisions.json"
DAYS = 28
WORSE = 0.8


def entries():
    out = []
    if not LOG.is_file():
        return out
    for ln in LOG.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("by") == "auto_rewrite" and d.get("kind") == "title" and d.get("ok") \
                and d.get("before_title") and str(d.get("note", "")).startswith("直しました"):
            out.append(d)
    return out


def restore(slug, d):
    p = ROOT / "articles" / f"{slug}.md"
    t = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", t, re.S)
    if not m:
        return False
    fm = m.group(1)
    fm2 = re.sub(r"^title:.*$", "title: " + d["before_title"], fm, count=1, flags=re.M)
    if d.get("before_description"):
        fm2 = re.sub(r"^description:.*$", "description: " + d["before_description"], fm2, count=1, flags=re.M)
    if fm2 == fm:
        return False
    p.write_text(t.replace(fm, fm2, 1), encoding="utf-8", newline="")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    import effect_ab as EA
    decided = json.loads(DECIDED.read_text(encoding="utf-8")) if DECIDED.is_file() else {}
    todo = [d for d in entries() if f'{d["slug"]}@{d["at"][:10]}' not in decided]
    cutoff = date.today() - timedelta(days=DAYS + 3)
    todo = [d for d in todo if date.fromisoformat(d["at"][:10]) <= cutoff]
    print(f"■ 直してから{DAYS}日以上たった記事: {len(todo)}本")
    if not todo:
        print("ROLLBACK_OK=yes\nROLLED_BACK=0\nKEPT=0")
        return 0
    try:
        daily, _, _ = EA.daily_by_slug()
    except Exception as e:
        print(f"   日次データが取れません（{str(e)[:60]}）。判定を見送ります")
        print("ROLLBACK_OK=yes\nROLLED_BACK=0\nKEPT=0")
        return 0
    touched = {x["slug"] for x in EA.interventions()}
    rolled = kept = 0
    for d in todo:
        slug, at = d["slug"], date.fromisoformat(d["at"][:10])
        me = EA.change(daily, slug, at, DAYS)
        if me is None:
            continue                                  # 観測が足りない／表示が少ない
        ctrl = [c[0] for s in daily if s not in touched
                for c in [EA.change(daily, s, at, DAYS)] if c is not None]
        if len(ctrl) < EA.MIN_N:
            continue
        base = statistics.median(ctrl)
        worse = me[0] < base * WORSE and (me[1] is None or me[1] <= 0)
        key = f"{slug}@{d['at'][:10]}"
        verdict = {"ratio": round(me[0], 2), "control": round(base, 2),
                   "pos_gain": me[1], "rolled_back": False}
        print(f"   {'×' if worse else '○'} {slug[:38]:<38} 表示×{me[0]:.2f}（対照×{base:.2f}）"
              f" 順位{'+' if (me[1] or 0) > 0 else ''}{me[1] if me[1] is not None else '-'}")
        if worse and a.write and restore(slug, d):
            verdict["rolled_back"] = True
            rolled += 1
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "by": "rewrite_rollback",
                                    "slug": slug, "kind": "rollback", "ok": True,
                                    "note": f"表示×{me[0]:.2f}（対照×{base:.2f}）のため元のタイトルへ戻した"},
                                   ensure_ascii=False) + "\n")
        else:
            kept += 1
        if a.write:
            decided[key] = verdict
    if a.write:
        DECIDED.parent.mkdir(exist_ok=True)
        DECIDED.write_text(json.dumps(decided, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ROLLBACK_OK=yes\nROLLED_BACK={rolled}\nKEPT={kept}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
