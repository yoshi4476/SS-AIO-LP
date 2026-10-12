# -*- coding: utf-8 -*-
"""範囲ごとに AI を回す回（scripts/agent_passes.sh）で、その範囲に今日の仕事があるかを数える。0件なら AI を起こさない
（2026-10-12 運用者「仕事が無い社は飛ばす」。お客様が増えても、仕事のある社の分だけ AI が動く）。

  python scripts/agent_work.py --kind rescue --scope <own|公開の id>   # 救済: AI の前の監査の TODO のうち、その範囲の社の分
  python scripts/agent_work.py --kind weekly --scope <own|公開の id>   # 週次: その範囲の社の記事の本数（全記事を見直す仕事）
  python scripts/agent_work.py --snapshot                              # 範囲を絞る前に、全社の記事→社の対応を控える
出す印: AGENT_WORK=<件数> / unknown（数えられない。そのときは飛ばさない）
救済の監査の出力は、鍵のある「救済の監査」の手順が $RUNNER_TEMP/audit_out.txt に残す（AI の手順では監査をやり直さない）
"""
import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def scope_sites(scope):
    """範囲に入る社の id（own なら自社。お客様なら同じ組の社。公開の id も含める）"""
    import sites as S
    if scope == "own":
        ids = set(S.own_ids())
    else:
        sid = S.resolve(scope)
        if not S.is_client(sid):
            ids = set(S.own_ids())
        else:
            g = S.group_key(sid)
            ids = {c for c in S.load_all() if S.is_client(c) and S.group_key(c) == g} | {sid}
    return ids | {S.public_id(x) for x in ids}


def _snapshot_path():
    # 作業場所の外（AI の許可の一覧で読ませない一時置き場）。社の id と記事の slug が入る
    return Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / "agent_work_map.json"


def snapshot():
    """範囲を絞る前に、全社の記事→社と、全社の id（公開の id も）を控える。絞った後はほかの社の原稿と設定が
    作業場所から外れるため、自社の回がお客様の記事に触れる TODO を「社の分からない行」として自社に数え、
    余計に AI を起こしていた（2026-10-12 の点検）"""
    import json
    import sites as S
    every = sorted(set(S.load_all()) | {S.public_id(x) for x in S.load_all()})
    _snapshot_path().write_text(json.dumps({"owner": _slug_owner(), "every": every}, ensure_ascii=False),
                                encoding="utf-8")
    return len(every)


def _load_snapshot():
    import json
    try:
        d = json.loads(_snapshot_path().read_text(encoding="utf-8"))
        return d.get("owner") or {}, set(d.get("every") or [])
    except (OSError, ValueError):
        return None, None


def _slug_owner():
    """作業場所の原稿の slug → 社の id（カテゴリから）"""
    import sites as S
    cat = {c: sid for sid, cfg in S.load_all().items() for c in (cfg.get("categories") or {})}
    out = {}
    for p in (ROOT / "articles").glob("*.md"):
        m = re.search(r"^category:\s*[\"']?([^\"'\n]+)", p.read_text(encoding="utf-8-sig")[:3000], re.M)
        if m and m.group(1).strip() in cat:
            out[p.stem] = cat[m.group(1).strip()]
    return out


def todo_lines(text):
    """監査の出力のうち「今日やる」TODO の行（「以下は今日やらないこと」より前）"""
    head = text.split("--- 以下は今日やらないこと", 1)[0]
    if "===== 結果 =====" in head:
        head = head.split("===== 結果 =====", 1)[1]
    return [ln.strip() for ln in head.splitlines() if ln.strip().startswith("TODO:")]


def rescue_count(scope, text, owner=None):
    """TODO のうち、その範囲の社か、その範囲の社の記事に触れているものの数。社にも記事にも触れない行は自社の回で数える"""
    import sites as S
    ids = scope_sites(scope)
    every = None
    if owner is None:
        owner, every = _load_snapshot()
        if owner is None:
            owner = _slug_owner()
    if every is None:
        every = set(S.load_all()) | {S.public_id(x) for x in S.load_all()}
    n = 0
    for ln in todo_lines(text):
        words = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", ln))
        if any(w in ids or owner.get(w) in ids for w in words):
            n += 1
        elif scope == "own" and not any(w in every or w in owner for w in words):
            n += 1
    return n


def weekly_count(scope, owner=None):
    ids = scope_sites(scope)
    if owner is None:
        owner = _load_snapshot()[0]
        if owner is None:
            owner = _slug_owner()
    return sum(1 for s, sid in owner.items() if sid in ids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["rescue", "weekly"])
    ap.add_argument("--scope")
    ap.add_argument("--snapshot", action="store_true")
    a = ap.parse_args()
    if a.snapshot:
        try:
            print(f"AGENT_WORK_MAP=ok（社 {snapshot()}）")
        except Exception as e:
            print(f"AGENT_WORK_MAP=unknown（控えを作れませんでした: {type(e).__name__}）")
        return 0
    if not (a.kind and a.scope):
        ap.error("--kind と --scope を指定してください")
    try:
        if a.kind == "rescue":
            p = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / "audit_out.txt"
            if not p.is_file():
                print("AGENT_WORK=unknown（救済の監査の出力がありません）")
                return 0
            n = rescue_count(a.scope, p.read_text(encoding="utf-8", errors="replace"))
        else:
            n = weekly_count(a.scope)
    except Exception as e:
        print(f"AGENT_WORK=unknown（数えられませんでした: {type(e).__name__}）")
        return 0
    print(f"AGENT_WORK={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
