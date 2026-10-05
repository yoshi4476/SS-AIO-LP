# -*- coding: utf-8 -*-
"""打った手が効かなかったら、元に戻す。

**なぜ要るか**: auto_rewrite はタイトル・説明文を直して終わりだった。効いたかは
effect_ab が出すが、悪化した記事もそのまま残る。「当てる」と「戻す」が揃って
初めて、直しは実験になる。

判定は effect_ab と同じ: 直した日の前後28日で表示の倍率を出し、**同じ期間の
触っていない記事（対照群）の中央値**と比べる。対照の8割を下回り、順位も
良くなっていなければ、直す前のタイトル・説明文へ戻す。

対照群は、直した記事と**公開からの週数が近い（±1週）**記事だけにする（content_yield のコホートと同じ考え）。
記事は公開1〜3週で表示の山、4〜6週で山の約1/4に落ちる（2026-10-05 実測）。公開から日の浅い記事を直すと
自然な落ち込みが「直した後」に入り、公開の古い記事が混ざった対照群と比べると、効いた直しまで
「効かなかった」と読んで戻していた。対照が10本に満たなければ判定を保留し（判定済みにしない）、翌週以降にまた見る。

  python scripts/rewrite_rollback.py            # 判定だけ
  python scripts/rewrite_rollback.py --write    # 戻す
出す印: ROLLBACK_OK=yes / ROLLED_BACK=<本> / KEPT=<本> / HELD=<本>（対照が足りず保留）
戻せるのは、直したときに before_title（題の直し）か before_path（compete の本文の直し）を
台帳（auto_fix.jsonl）に残した分だけ。
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
AGE_TOL = 7          # 対照に入れる公開からの日数の差（±1週）


def published():
    """slug → 公開日。日付の無い原稿は入れない（週数をそろえられない）"""
    import content_yield as CY
    out = {}
    for p in (ROOT / "articles").glob("*.md"):
        a = CY._fm(p)
        try:
            out[a["slug"]] = date.fromisoformat(a["date"])
        except (TypeError, ValueError):
            continue
    return out


def controls(daily, slug, at, pubs, acts):
    """直した記事と公開からの週数が近く、比べる前後28日に触っていない記事の表示の倍率。公開日が分からなければ None。
    「一度でも触った記事」を外すと、内部リンク・CTA を全記事に足してきたため同じ週数の記事が1本も残らない
    （2026-10-05 実測: 同じ週数73本のうち1本）。比べる期間の外の手は、この判定の表示に入らない。
    記事以外（トップ・カテゴリ・著者のページ）も公開日が無いので入らない（前は対照38本のうち35本がそれだった）"""
    import effect_ab as EA
    if slug not in pubs:
        return None
    age = (at - pubs[slug]).days
    lo, hi = (at - timedelta(days=DAYS)).isoformat(), (at + timedelta(days=DAYS)).isoformat()
    touched = {x["slug"] for x in acts if lo <= x["at"] <= hi}
    out = []
    for s in daily:
        if s == slug or s in touched or s not in pubs or abs((at - pubs[s]).days - age) > AGE_TOL:
            continue
        c = EA.change(daily, s, at, DAYS)
        if c is not None:
            out.append(c[0])
    return out


def min_controls():
    import content_yield as CY
    return CY.MIN_COHORT


def entries():
    out = []
    if not LOG.is_file():
        return out
    for ln in LOG.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        # manual は人が手で変えた題を、git の履歴から before_title を取って後から足した記録
        # （手で変えた題は台帳に残らず、28日・対照群の判定に乗らなかった）
        if d.get("by") not in ("auto_rewrite", "manual") or not d.get("ok") \
                or not str(d.get("note", "")).startswith("直しました"):
            continue
        # compete（競合との差を埋める書き直し）は本文を足す直しなので、直す前の原稿ごと戻す
        if (d.get("kind") == "title" and d.get("before_title")) or (d.get("kind") == "compete" and d.get("before_path")):
            out.append(d)
    return out


def restore_file(slug, d):
    """直す前の原稿へ戻す。直した後にだれかが触っていたら戻さない（その直しまで消してしまう）"""
    import hashlib
    p = ROOT / "articles" / f"{slug}.md"
    src = ROOT / d["before_path"]
    if not p.is_file() or not src.is_file():
        return False
    if hashlib.sha1(p.read_bytes()).hexdigest() != d.get("after_sha"):
        print(f"要対応: {slug} は直した後に別の変更が入ったため、自動では戻しません（{d['before_path']} と見比べてください）")
        return False
    p.write_bytes(src.read_bytes())
    return True


def restore(slug, d):
    if d.get("kind") == "compete":
        return restore_file(slug, d)
    p = ROOT / "articles" / f"{slug}.md"
    t = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", t, re.S)
    if not m:
        return False
    fm = m.group(1)
    # 後から足した記録は、その後に題がまた変わっていれば戻さない（後の直しまで消してしまう）
    now = re.search(r"^title:\s*(.*)$", fm, re.M)
    if d.get("by") == "manual" and d.get("after_title") and (now.group(1).strip().strip('"') if now else "") != d["after_title"]:
        print(f"要対応: {slug} は記録の後に題が変わったため、自動では戻しません")
        return False
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
        print("ROLLBACK_OK=yes\nROLLED_BACK=0\nKEPT=0\nHELD=0")
        return 0
    try:
        daily, _, _ = EA.daily_by_slug()
    except Exception as e:
        print(f"   日次データが取れません（{str(e)[:60]}）。判定を見送ります")
        print("ROLLBACK_OK=yes\nROLLED_BACK=0\nKEPT=0\nHELD=0")
        return 0
    acts = EA.interventions()
    pubs = published()
    rolled = kept = held = 0
    for d in todo:
        slug, at = d["slug"], date.fromisoformat(d["at"][:10])
        me = EA.change(daily, slug, at, DAYS)
        if me is None:
            continue                                  # 観測が足りない／表示が少ない
        ctrl = controls(daily, slug, at, pubs, acts)
        if ctrl is None or len(ctrl) < min_controls():
            # 判定済みにしない。翌週以降に同じ週数の記事が育てば判定できる
            held += 1
            print(f"   保留 {slug[:38]:<38} 公開からの週数が近い対照が"
                  + ("分かりません（公開日なし）" if ctrl is None else f"{len(ctrl)}本（{min_controls()}本以上で判定）"))
            continue
        base = statistics.median(ctrl)
        worse = me[0] < base * WORSE and (me[1] is None or me[1] <= 0)
        key = f"{slug}@{d['at'][:10]}"
        verdict = {"ratio": round(me[0], 2), "control": round(base, 2),
                   "pos_gain": me[1], "rolled_back": False, "control_n": len(ctrl)}
        print(f"   {'×' if worse else '○'} {slug[:38]:<38} 表示×{me[0]:.2f}（対照×{base:.2f}）"
              f" 順位{'+' if (me[1] or 0) > 0 else ''}{me[1] if me[1] is not None else '-'}")
        if worse and a.write and restore(slug, d):
            verdict["rolled_back"] = True
            rolled += 1
            with LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M"), "by": "rewrite_rollback",
                                    "slug": slug, "kind": "rollback", "ok": True,
                                    "note": f"表示×{me[0]:.2f}（対照×{base:.2f}）のため"
                                    + ("直す前の原稿へ戻した" if d.get("kind") == "compete" else "元のタイトルへ戻した")},
                                   ensure_ascii=False) + "\n")
        else:
            kept += 1
        if a.write:
            decided[key] = verdict
    if a.write:
        DECIDED.parent.mkdir(exist_ok=True)
        DECIDED.write_text(json.dumps(decided, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ROLLBACK_OK=yes\nROLLED_BACK={rolled}\nKEPT={kept}\nHELD={held}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
