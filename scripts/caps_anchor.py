# -*- coding: utf-8 -*-
"""方式×機能の表（data/capabilities.json）の根拠の行（evidence「ファイル:行」）を、行の中身で引き直す。

**なぜ要るか**: 根拠は行番号で持つので、コードを1行足すだけで別の行を指す。並行作業の結合で行番号がずれ、
引き直したつもりの表に古い判定が混ざった（2026-10-06）。行番号のずれは目で見ても気づけない。
そこで各セルに、その行の中身（anchor）を持たせ、ファイルが変わったら中身で行を探し直す。

  anchor      … 根拠の行の中身（前後の空白を除いた先頭 ANCHOR_MAX 字）。行がこれで始まれば同じ行とみなす
  anchor_prev … 同じ中身の行がファイルに複数あるときだけ、直前の空でない行の中身を近い順に（1つに決まるまで・最大 CTX_MAX 行）

探し直しで候補が複数残れば、元の行番号に近いものを採る。見つからないセルは要対応（判定を見直す）。

  python scripts/caps_anchor.py                 # ずれと、探し直せないセルを見るだけ（何も書かない）
  python scripts/caps_anchor.py --write         # 行番号を引き直し、anchor の無いセルに付ける
  python scripts/caps_anchor.py --write --init <rev>
      # anchor の無いセルの中身を、git の版 <rev> のファイルから取る（行番号を付けた時点の版。その後にずれた分も引き直せる）

終了コード: 検査が動けば0（ずれ・探し直せないセルは CAPS_ANCHOR_OK=no と明細で知らせる）
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CAPS = ROOT / "data" / "capabilities.json"
ANCHOR_MAX = 120


def _lines(text):
    return [x.strip() for x in text.splitlines()]


def read_lines(rel, rev=None, root=ROOT):
    """ファイルの各行（前後の空白を除いたもの）。rev があれば git のその版から読む。読めなければ None"""
    if rev:
        r = subprocess.run(["git", "-C", str(root), "show", f"{rev}:{rel}"], capture_output=True)
        return _lines(r.stdout.decode("utf-8-sig", errors="replace")) if r.returncode == 0 else None
    p = root / rel
    return _lines(p.read_text(encoding="utf-8-sig", errors="replace")) if p.is_file() else None


CTX_MAX = 6


def _prevs(lines, i, k):
    """i 行目（0始まり）の直前の空でない行を、近い順に k 個"""
    out = []
    for j in range(i - 1, -1, -1):
        if len(out) >= k:
            break
        if lines[j]:
            out.append(lines[j][:ANCHOR_MAX])
    return out


def _ctx_ok(lines, i, prev):
    got = _prevs(lines, i, len(prev))
    return len(got) == len(prev) and all(g.startswith(p) for g, p in zip(got, prev))


def make_anchor(lines, n):
    """n 行目（1始まり）の anchor。同じ中身の行が他にもあれば、直前の行を足して1つに決まるまで広げる
    （「}」「return out」のような行は、直前の行が無いとどれのことか決まらない）。空行・範囲外は None"""
    if not 1 <= n <= len(lines) or not lines[n - 1]:
        return None
    a = lines[n - 1][:ANCHOR_MAX]
    same = [i for i, x in enumerate(lines) if x.startswith(a) and i != n - 1]
    out = {"anchor": a}
    for k in range(1, CTX_MAX + 1):
        if not same:
            break
        prev = _prevs(lines, n - 1, k)
        out["anchor_prev"] = prev
        same = [i for i in same if _ctx_ok(lines, i, prev)]
    return out


def matches(lines, n, cell):
    """n 行目がそのセルの anchor の行か"""
    if not 1 <= n <= len(lines) or not lines[n - 1].startswith(cell["anchor"]):
        return False
    prev = cell.get("anchor_prev") or []
    return _ctx_ok(lines, n - 1, [prev] if isinstance(prev, str) else prev)


def locate(lines, cell, near):
    """anchor の行を探す（候補が複数なら near に近いもの）。無ければ None"""
    hits = [i + 1 for i in range(len(lines)) if matches(lines, i + 1, cell)]
    return min(hits, key=lambda n: (abs(n - near), n)) if hits else None


def split_ev(ev):
    m = re.fullmatch(r"(.+):(\d+)", str(ev or ""))
    return (m.group(1), int(m.group(2))) if m else (None, None)


def cells(caps):
    for fid, f in (caps.get("features") or {}).items():
        for meth, c in (f.get("cells") or {}).items():
            yield fid, meth, c


def run(caps, write=False, init_rev=None, root=ROOT):
    """表を検査し（write なら直し）、(直した行, 要対応の行) を返す。caps はその場で書き換える"""
    cache = {}

    def lines_of(rel, rev=None):
        k = (rel, rev)
        if k not in cache:
            cache[k] = read_lines(rel, rev, root)
        return cache[k]

    fixed, todo = [], []
    for fid, meth, c in cells(caps):
        rel, n = split_ev(c.get("evidence"))
        name = f"{fid} × {meth}"
        if rel is None:
            todo.append(f"{name}: 根拠 {c.get('evidence')!r} が「ファイル:行」ではありません")
            continue
        cur = lines_of(rel)
        if cur is None:
            todo.append(f"{name}: 根拠のファイル {rel} がありません")
            continue
        if not c.get("anchor"):
            src = lines_of(rel, init_rev) if init_rev else cur
            a = make_anchor(src, n) if src is not None else None
            if not a:
                todo.append(f"{name}: 根拠 {rel}:{n} の行が空か範囲外で、中身を記録できません")
                continue
            if write:
                c.update(a)
                fixed.append(f"{name}: 中身を記録 「{a['anchor'][:40]}」")
            else:
                todo.append(f"{name}: 根拠の行の中身（anchor）がありません")
                continue
        if matches(cur, n, c):
            continue
        got = locate(cur, c, n)
        if got is None:
            todo.append(f"{name}: {rel} に「{c['anchor'][:40]}」の行が見つかりません（判定を見直す）")
            continue
        if write:
            c["evidence"] = f"{rel}:{got}"
            fixed.append(f"{name}: {rel}:{n} → {got}")
        else:
            todo.append(f"{name}: 根拠 {rel}:{n} がずれています（中身の行は {got} 行目）")
    return fixed, todo


def save(caps, path=CAPS):
    path.write_text(json.dumps(caps, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="行番号を引き直し、anchor の無いセルに付ける")
    ap.add_argument("--init", default="", help="anchor の無いセルの中身を、この git の版のファイルから取る")
    a = ap.parse_args()
    caps = json.loads(CAPS.read_text(encoding="utf-8"))
    fixed, todo = run(caps, write=a.write, init_rev=a.init or None)
    if a.write and fixed:
        save(caps)
    for x in fixed:
        print(f"  直した: {x}")
    for x in todo:
        print(f"  要対応: {x}")
    print(f"CAPS_ANCHOR_OK={'no' if todo else 'yes'}")
    if todo and not a.write:
        print("  → python scripts/caps_anchor.py --write で引き直す（見つからない行は判定を見直す）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
