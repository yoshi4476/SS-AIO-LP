# -*- coding: utf-8 -*-
"""打った手が効かなかったら、元に戻す。

**なぜ要るか**: auto_rewrite はタイトル・説明文を直して終わりだった。効いたかは
effect_ab が出すが、悪化した記事もそのまま残る。「当てる」と「戻す」が揃って
初めて、直しは実験になる。

判定は effect_ab と同じ: 直した日の前後28日で表示の倍率を出し、**同じ期間の
触っていない記事（対照群）の中央値**と比べる。対照の8割を下回り、順位も
良くなっていなければ、直す前のタイトル・説明文へ戻す。

対照群は、直した記事と**公開からの週数が近い（±1週）**記事だけにする（effect_ab.cohort()。効果判定と同じ物差し）。
記事は公開1〜3週で表示の山、4〜6週で山の約1/4に落ちる（2026-10-05 実測）。公開から日の浅い記事を直すと
自然な落ち込みが「直した後」に入り、公開の古い記事が混ざった対照群と比べると、効いた直しまで
「効かなかった」と読んで戻していた。対照が10本に満たなければ判定を保留し（判定済みにしない）、翌週以降にまた見る。

  python scripts/rewrite_rollback.py            # 判定だけ
  python scripts/rewrite_rollback.py --write    # 戻す
出す印: ROLLBACK_OK=yes / ROLLED_BACK=<本> / KEPT=<本> / HELD=<本>（対照が足りず保留）
戻せるのは、直したときに before_title（題の直し）か before_path（compete・early の本文の直し）を
台帳（auto_fix.jsonl）に残した分だけ。early（公開14〜35日の記事に細い語を入れる直し）は、
その直しで変えた部分（題・H2の1本・FAQの問い）だけを直す前の原稿から戻す。
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


def published():
    import effect_ab as EA
    return EA.published()


def controls(daily, slug, at, pubs, acts):
    """対照の表示の倍率。対照の選び方は effect_ab.cohort()（効果判定と同じ物差し）。公開日が分からなければ None"""
    import effect_ab as EA
    cs = EA.cohort(daily, slug, at, pubs, acts, DAYS)
    if cs is None:
        return None
    return [c[0] for s in cs for c in [EA.change(daily, s, at, DAYS)] if c is not None]


def min_controls():
    import effect_ab as EA
    return EA.MIN_CTRL


def entries():
    import client_private as CP
    out = []
    for ln in CP.read_lines(LOG):           # お客様の記事の行（置き場）も合わせる。見ないとお客様の直しを戻せない
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        # manual は人が手で変えた題を、git の履歴から before_title を取って後から足した記録
        # （手で変えた題は台帳に残らず、28日・対照群の判定に乗らなかった）
        if d.get("by") not in ("auto_rewrite", "manual") or not d.get("ok") \
                or not str(d.get("note", "")).startswith("直しました"):
            continue
        # compete（競合との差を埋める書き直し）は本文を足す直しなので、直す前の原稿ごと戻す。
        # early は直す前の原稿から、変えた部分だけを戻す
        if (d.get("kind") == "title" and d.get("before_title")) \
                or (d.get("kind") in ("compete", "early") and d.get("before_path")):
            out.append(d)
    return out


_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _title_line(text):
    m = _FM.match(text)
    t = re.search(r"^title:.*$", m.group(1), re.M) if m else None
    return t.group(0) if t else ""


def _faq(text):
    m = _FM.match(text)
    return [q.strip().strip('"') for q in re.findall(r"^\s*-\s*q:\s*(.+)$", m.group(1), re.M)] if m else []


def _h2(lines):
    """本文の H2 の (行番号, 行)。コードの中は数えない"""
    out, code = [], False
    for i, ln in enumerate(lines):
        if ln.startswith("```"):
            code = not code
        elif not code and ln.startswith("## "):
            out.append((i, ln))
    return out


def undo_early(before, now, d):
    """early で変えた部分（題・H2の1本・足したFAQ）だけを、直す前の原稿 before から戻した本文を返す。
    返すのは (本文, 理由)。変えた部分の形がその後に変わっていて戻し方が決まらなければ本文は None"""
    t0, t1 = _title_line(before), _title_line(now)
    if not t0 or not t1:
        return None, "フロントマターの題が読めません"
    if t1 != t0:
        cur = t1.split(":", 1)[1].strip().strip('"')
        if d.get("after_title") and cur != d["after_title"]:
            return None, "early の後に題が変わっています"
        now = now.replace(t1, t0, 1)

    # 足したFAQ: フロントマターの問いと答え・本文の1行（<details>）を外す
    new_q = [q for q in _faq(now) if q not in _faq(before)]
    if new_q:
        m = _FM.match(now)
        fm, out, skip = m.group(1).split("\n"), [], None
        for ln in fm:
            q = re.match(r"^(\s*)-\s*q:\s*(.+)$", ln)
            if q:
                skip = len(q.group(1)) if q.group(2).strip().strip('"') in new_q else None
            elif skip is not None and (len(ln) - len(ln.lstrip()) <= skip or not ln.strip()):
                skip = None
            if skip is None:
                out.append(ln)
        body = now[m.end():]
        bl = [ln for ln in body.split("\n")
              if not any(f"<summary>{q}</summary>" in ln for q in new_q)]
        now = now[:m.start(1)] + "\n".join(out) + now[m.end(1):m.end()] + "\n".join(bl)

    # H2: 1本の言い換えなら元の見出しへ、1本足していればその節を外す
    lines = now.split("\n")
    h0 = [ln for _, ln in _h2(before.split("\n"))]
    h1 = _h2(lines)
    texts = [ln for _, ln in h1]
    if texts != h0:
        diff = [i for i, (a, b) in enumerate(zip(texts, h0)) if a != b]
        if len(texts) == len(h0) and len(diff) == 1:
            lines[h1[diff[0]][0]] = h0[diff[0]]
        elif len(texts) == len(h0) + 1:
            added = [i for i in range(len(texts)) if texts[:i] + texts[i + 1:] == h0]
            if not added:
                return None, "H2 が early の後にも変わっています"
            i = added[0]
            end = h1[i + 1][0] if i + 1 < len(h1) else len(lines)
            del lines[h1[i][0]:end]
        else:
            return None, f"H2 の本数が直す前と{len(texts) - len(h0):+d}本違います（early は1本まで）"
        now = "\n".join(lines)
    if _title_line(now) != t0 or _faq(now) != _faq(before) or [ln for _, ln in _h2(now.split("\n"))] != h0:
        return None, "戻した後も題・H2・FAQ が直す前と一致しません"
    return now, ""


def later_rewrites(slug, d):
    """この直しより後に、同じ記事へ入った別の書き直し・統合・手での題の変更"""
    import client_private as CP
    out = []
    for ln in CP.read_lines(LOG):
        try:
            x = json.loads(ln)
        except ValueError:
            continue
        if x.get("slug") == slug and x.get("ok") and str(x.get("at", "")) > str(d.get("at", "")) \
                and x.get("by") in ("auto_rewrite", "auto_merge", "manual") \
                and str(x.get("note", "")).startswith(("直しました", "統合しました")):
            out.append(x)
    return out


def restore_early(slug, d):
    """直した後だれも触っていなければ原稿ごと、内部リンクの追加などだけなら early の部分だけを戻す。
    別の書き直しが入っていたら戻さない（その直しまで消してしまう）"""
    import hashlib
    p = ROOT / "articles" / f"{slug}.md"
    src = ROOT / d["before_path"]
    if not p.is_file() or not src.is_file():
        return False
    raw = p.read_bytes()
    if hashlib.sha1(raw).hexdigest() == d.get("after_sha"):
        p.write_bytes(src.read_bytes())
        return True
    later = later_rewrites(slug, d)
    if later:
        print(f"要対応: {slug} は early の後に別の直し（{later[-1].get('kind') or later[-1].get('by')}・"
              f"{str(later[-1].get('at'))[:10]}）が入ったため、自動では戻しません（{d['before_path']} と見比べてください）")
        return False
    text, why = undo_early(src.read_bytes().decode("utf-8-sig"), raw.decode("utf-8-sig"), d)
    if text is None:
        print(f"要対応: {slug} の early を自動では戻せません（{why}。{d['before_path']} と見比べてください）")
        return False
    p.write_text(text, encoding="utf-8", newline="")
    return True


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
    if d.get("kind") == "early":
        return restore_early(slug, d)
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
    import client_private as CP
    # 判定（表示の比）はお客様の記事の分を置き場に置く。読むときは合わせる
    decided = CP.load_dict("data/rollback_decisions.json", pub=DECIDED)
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
    # 対照から外すのは書き直し・統合・手での題の変更だけ（effect_ab --rewrites と同じ）。
    # 内部リンク・CTA まで外すと同じ週数の対照が10本に届かず、判定が永久に保留になる
    acts = EA.rewrites(LOG) + entries()
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
                   "pos_gain": me[1], "rolled_back": False, "control_n": len(ctrl),
                   "kind": d.get("kind") or "title"}
        print(f"   {'×' if worse else '○'} {slug[:38]:<38} 表示×{me[0]:.2f}（対照×{base:.2f}）"
              f" 順位{'+' if (me[1] or 0) > 0 else ''}{me[1] if me[1] is not None else '-'}")
        if worse and a.write and restore(slug, d):
            verdict["rolled_back"] = True
            rolled += 1
            import client_private as CP
            CP.append_jsonl(LOG, {"at": time.strftime("%Y-%m-%d %H:%M"), "by": "rewrite_rollback",
                                  "slug": slug, "kind": "rollback", "ok": True,
                                  "note": f"表示×{me[0]:.2f}（対照×{base:.2f}）のため"
                                  + {"compete": "直す前の原稿へ戻した",
                                     "early": "early で変えた題・H2・FAQを直す前へ戻した"}.get(d.get("kind"), "元のタイトルへ戻した")})
        else:
            kept += 1
        if a.write:
            decided[key] = verdict
    if a.write:
        CP.save_dict("data/rollback_decisions.json", decided, lambda k, _v: CP.owner_of_slug(k.split("@")[0]),
                     dump=lambda o: json.dumps(o, ensure_ascii=False, indent=2), pub=DECIDED)
    print(f"ROLLBACK_OK=yes\nROLLED_BACK={rolled}\nKEPT={kept}\nHELD={held}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
