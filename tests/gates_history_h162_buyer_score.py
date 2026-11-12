# -*- coding: utf-8 -*-
"""2026-11-12 運用者「買い手の記事を第一優先として行ってほしい。また評価値は必ず上げること」。
1. 書き直しの候補は、買い手の語（頼む先を探す・比べる・値段を知る）の記事を先に並べる
2. 本文の書き直しは、書いた AI とは別の工程で3観点を採点し直し、平均が上がり・下限を新しく割らず・
   公開の基準を満たすときだけ採用する。採点できなければ採用しない（上がったと確かめられないため）
それまでの本文の書き直し（stuck・serp など）は、検算は通しても採点し直さず、点が下がっても残っていた"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

BEFORE = "---\ntitle: 経理代行の費用｜x\nkeyword: 経理代行 費用\nscore: 86\nscore_breakdown: {originality: 82, extractability: 86, decision: 90}\n---\n本文\n"
NO_SCORE = "---\ntitle: 経理代行の費用｜x\nkeyword: 経理代行 費用\n---\n本文\n"


def _fake(axes_after, axes_before=None):
    import quality_loop as QL
    import rubric as R

    def score(slug, ask=None, text=None):
        axes = axes_before if (axes_before is not None and "直す前" in (text or "")) else axes_after
        if axes is None:
            return None, "採点の失敗"
        got = R.judge(axes)
        return {"axes": dict(axes), "total": got["total"], "ok": got["ok"], "why": got["why"]}, ""
    QL.score = score


def test_rewrites_keep_only_higher_scores_and_buyer_articles_go_first():
    import auto_rewrite as AR
    import quality_loop as QL
    real = QL.score
    keys = QL.AXIS_KEYS
    print("\n■ 書き直し: 買い手の記事を先に・点が上がったときだけ採用")
    try:
        check("原稿に書いた3観点の点を読む", AR._breakdown(BEFORE), {"axes": dict(zip(keys, (82, 86, 90))), "total": 86})
        check("点の無い原稿は None（直す前の原稿を採点する）", AR._breakdown(NO_SCORE), None)
        b0 = BEFORE + "直す前"
        good = dict(zip(keys, (82, 86, 90)))
        _fake(dict(zip(keys, (86, 90, 92))), good)
        ok, why, sc = AR.score_gate("x", b0, "後")
        check("平均が上がり、下限を割らず、基準を満たせば採用", (ok, sc["total"], sc["ok"]), (True, 89, True))
        _fake(good, good)
        check("平均が同じなら採用しない（上がっていない）", AR.score_gate("x", b0, "後")[0], False)
        _fake(dict(zip(keys, (78, 95, 99))), good)
        ok, why, _ = AR.score_gate("x", b0, "後")
        check("平均が上がっても、下限（一次性80）を新しく割れば採用しない", (ok, "下限" in why), (False, True))
        _fake(None, good)
        ok, why, _ = AR.score_gate("x", b0, "後")
        check("採点できなければ採用しない", (ok, "採点できません" in why), (False, True))
        _fake(dict(zip(keys, (88, 90, 90))), dict(zip(keys, (84, 86, 88))))
        ok, why, _ = AR.score_gate("x", NO_SCORE + "直す前", "後")
        check("点の無い原稿は、直す前の原稿を採点して比べる", (ok, "86→89" in why), (True, True))
        # 2026-11-12: 原稿に残る点（前の回の採点）とその場の採点を比べ、直した後が基準に届かないとして5本を戻した。
        # 直す前も同じ回に採点し直して比べる。直す前から基準に届かない記事は、どの軸も下がらなければ上がった分を採る
        _fake(dict(zip(keys, (65, 75, 75))), dict(zip(keys, (60, 70, 70))))
        ok, why, sc = AR.score_gate("x", b0, "後")
        check("原稿に残る点（86）は使わず、直す前も採点し直して比べる（67→72）", (ok, "67→72" in why), (True, True))
        check("直す前から基準に届かない記事は、上がった分を採るが基準は満たさない（点は原稿に書かない）",
              (sc["ok"], "まだ届きません" in why), (False, True))
        _fake(dict(zip(keys, (70, 76, 75))), dict(zip(keys, (60, 80, 70))))
        ok, why, _ = AR.score_gate("x", b0, "後")
        check("基準に届かない記事で、平均が上がっても下がった軸があれば採用しない", (ok, "下がった軸" in why), (False, True))
    finally:
        QL.score = real
    check("本文の直しは採点し直す・題と説明文だけの直しと公開前の直しは対象外",
          (AR.score_gated("stuck"), AR.score_gated("aio"), AR.score_gated("title"), AR.score_gated("split"), AR.score_gated("quality_loop")),
          (True, True, False, False, False))
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("採用の直前に採点の判定を通し、外れたら戻す（ng に入れる）",
          "good, why, gated = score_gate(slug, raw.decode(\"utf-8-sig\", errors=\"replace\"), after_text)" in src and "            ng = why\n" in src, True)
    check("採用したら、採点し直した点を機械が原稿に書く（基準を満たした点だけ。届かない点を書くと公開から外れる）",
          "        if gated[\"ok\"]:\n            write_score(slug, gated)\n" in src, True)
    # 買い手の記事を先に
    import kw_intent
    arts = sorted(p.stem for p in (ROOT / "articles").glob("*.md"))
    buy = next((s for s in arts if AR.is_buyer(s)), None)
    other = next((s for s in arts if not AR.is_buyer(s)), None)
    check("記事に買い手の語の記事と、そうでない記事がある", (buy is not None, other is not None), (True, True))
    items = [{"slug": other, "kind": "stuck"}, {"slug": buy, "kind": "stuck"}, {"slug": other, "kind": "title"}]
    check("買い手の記事を先に並べ、ほかの順は変えない", [x["slug"] for x in AR.buyer_first(items)], [buy, other, other])
    check("買い手の語の判定は計画と同じ（kw_intent.BUYER）", bool(kw_intent.BUYER.search("経理代行 費用")), True)
    check("候補の並びに買い手を先に当て、--buyer-only で買い手だけにできる",
          ("    items = buyer_first(items)\n" in src, "if a.buyer_only:" in src), (True, True))
