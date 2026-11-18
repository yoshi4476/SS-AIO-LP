# -*- coding: utf-8 -*-
"""週次の書き直しを同時に回す（2026-11-18 運用者「もっとすべての時間を短縮できないのか」→「進めて」）。

2026-11-16 の週次で、書き直しの2工程が22分・36分かかった。下書きは3本ずつ同時でも、検算の採点（1本あたり claude
2〜4回）は1本ずつ順に待ち、7種類の直しは種類ごとに順に呼んでいた。
- 7種類を1回で集める（--kind "question:2,early:2,..."）。同じ記事は1つの種類だけ
- 検算で使う直す前・後の採点を、下書きと同じ並列の中で済ませる。使うのは中身が同じ検算の1回だけ
- 機械の検査で警告が増える下書きは先に採点しない（AI の呼び出しを無駄にしない）
- 予算の DRAFT_SHARE の時刻を過ぎたら新しい下書きを始めない
本物の claude は呼ばない。
"""
import contextlib
import io
import sys
import time

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


@contextlib.contextmanager
def patched(*items):
    old = [(o, n, getattr(o, n)) for o, n, _ in items]
    try:
        for o, n, v in items:
            setattr(o, n, v)
        yield
    finally:
        for o, n, v in old:
            setattr(o, n, v)


def out_of(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a)
    return rc, buf.getvalue()


def _sc(total):
    import quality_loop as QL
    return {"axes": {k: total for k in QL.AXIS_KEYS}, "total": total, "ok": True, "why": ""}, ""


def test_kinds_are_collected_in_one_call():
    print("\n■ 7種類を1回で集める（同じ記事は1つの種類だけ・種類ごとの本数）")
    import auto_rewrite as AR
    check("並びを読む", AR.parse_kinds("question:2, stock:3,desc", 5), [("question", 2), ("stock", 3), ("desc", 5)])
    check("1つだけなら今までどおり", AR.parse_kinds("title", 7), [("title", 7)])
    check("空なら全種類（今までどおり）", AR.parse_kinds("", 7), [("", 7)])
    pool = {"question": ["a", "b", "c"], "stock": ["a", "d", "e", "f"]}
    picked = lambda a, k, n: [{"kind": k, "slug": s, "why": "w"} for s in pool[k]]
    old = sys.argv
    try:
        sys.argv = ["auto_rewrite.py", "--kind", "question:2,stock:2"]
        with patched((AR, "pick_items", picked), (AR, "shown", lambda s: s), (AR, "said", lambda s, w: w)):
            rc, out = out_of(AR.main)
        rows = [ln.split("]")[0].strip(" [") + ":" + ln.split("]")[1].split()[0] for ln in out.splitlines() if ln.strip().startswith("[")]
        check("種類ごとの本数で、同じ記事は先の種類だけ", rows, ["question:a", "question:b", "stock:d", "stock:e"])
        sys.argv = ["auto_rewrite.py", "--kind", "question:2,spare"]
        rc, out = out_of(AR.main)
        check("浮いた枠（spare）は並べられない", (rc, "並べられない" in out), (1, True))
    finally:
        sys.argv = old
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    line = next(ln for ln in wk.splitlines() if ln.strip().startswith('KINDS="'))
    check("週次は7種類を1行に並べる", sorted(p.split(":")[0] for p in line.split('"')[1].split(",")),
          sorted(["question", "early", "stock", "aisplit", "desc", "split", "compete"]))
    check("週次はそれを1回で、同時に呼ぶ", '--kind "$KINDS" --parallel 3 --budget-min' in wk, True)


def test_scores_are_done_beside_the_drafts_and_used_once():
    print("\n■ 検算の採点を下書きと同時に済ませ、中身が同じ検算の1回だけ使う")
    import auto_rewrite as AR
    import quality_loop as QL
    calls = []

    def fake_score(slug, ask=None, text=None):
        calls.append(text)
        return _sc(80 if "前" in text else 90)
    item = {"kind": "stuck", "slug": "x"}
    AR.PRESCORED.clear()
    with patched((QL, "score", fake_score), (AR, "warns_of", lambda s, t: [])):
        AR.prescore(item, "直す前", "直した後")
        check("直す前・後の2回を先に採点する", calls, ["直す前", "直した後"])
        ok, why, _ = AR.score_gate("x", "直す前", "直した後")
        check("検算は済ませた採点を使う（呼び直さない）", (ok, len(calls)), (True, 2))
        AR.score_gate("x", "直す前", "直した後")
        check("使うのは1回だけ（次の検算はその場で採点する）", len(calls), 4)
        AR.prescore(item, "直す前", "直した後")
        calls.clear()
        AR.score_gate("x", "直す前", "直した後（機械の直しで変わった）")
        check("中身が1文字でも違えば使わない", calls, ["直した後（機械の直しで変わった）"])
        AR.PRESCORED.clear()
        calls.clear()
        AR.prescore({"kind": "title", "slug": "x"}, "直す前", "直した後")
        check("採点で判定しない種類（題）は採点しない", calls, [])
    with patched((QL, "score", fake_score), (AR, "warns_of", lambda s, t: ["FAIL | H2が6〜12個 | 17個"] if "後" in t else [])):
        AR.prescore(item, "直す前", "直した後")
        check("機械の検査で警告が増える下書きは採点しない（検算で戻る）", calls, [])

    def boom(slug, ask=None, text=None):
        raise RuntimeError("採点の失敗")
    with patched((QL, "score", boom), (AR, "warns_of", lambda s, t: [])):
        AR.prescore(item, "直す前", "直した後")
    check("先の採点が落ちても下書きは捨てない（何も残さない）", AR.PRESCORED, {})


def test_drafts_stop_starting_after_the_deadline_and_stay_inside_the_guard():
    print("\n■ 予算の時刻を過ぎたら新しい下書きを始めない／本物の機械の検査を見張りの中で動かしても下書きは捨てない")
    import auto_rewrite as AR
    import quality_loop as QL
    slug = next(p.stem for p in sorted((ROOT / "articles").glob("*.md")) if not p.name.startswith("_"))
    drafted = []

    def fake_draft(item, prompt):
        drafted.append(item["slug"])
        return (ROOT / "articles" / f"{item['slug']}.md").read_bytes().decode("utf-8-sig") + "\n", None
    items = [{"kind": "fresh", "slug": slug, "why": "w"}]
    with patched((AR, "draft_one", fake_draft)):
        got = AR.draft_all(items, 2, deadline=time.time() - 1)
    check("時刻を過ぎていれば始めない（None）", (got, drafted), ([None], []))
    AR.PRESCORED.clear()
    with patched((AR, "draft_one", fake_draft), (QL, "score", lambda s, ask=None, text=None: _sc(85))):
        got = AR.draft_all(items, 2, deadline=time.time() + 600)
    check("時刻の前なら書く", (len(got), got[0] is not None, drafted), (1, True, [slug]))
    check("本物の score_check で警告を比べ、採点を済ませる（見張りが下書きを捨てない）", len(AR.PRESCORED), 2)
    AR.PRESCORED.clear()
