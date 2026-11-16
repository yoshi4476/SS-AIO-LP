# -*- coding: utf-8 -*-
"""次に書く語: 分野を順に回す社（category_rotate）は、記事の数がいちばん少ない分野の語を選び、
指示書でその分野で書くよう指定する（2026-11-17 運用者「順々に出していって、すべて同じ数になるように」）。
台帳の行に分野は入らず（kw_plan は語と狙いだけを積む）、記事の分野は書く AI が決めるので、
語の分野は category_terms の言葉で決め、指示書で分野を名指しする"""
from pathlib import Path
from unittest import mock

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent
CATS = {"a": "分野A", "b": "分野B", "c": "分野C"}
TERMS = {"a": ["りんご"], "b": ["みかん"], "c": ["ぶどう"]}


def _row(kw, status="未着手"):
    return {"site": "x", "keyword": kw, "category": "", "status": status}


def _pick(cfg, todo, counts):
    import hub_client as H
    import sites as S
    got = {"keyword": todo[0]["keyword"], "category": ""}
    with mock.patch.object(S, "load_all", return_value={"x": cfg}), mock.patch.object(S, "resolve", lambda s: s), \
            mock.patch.object(H, "_article_counts", return_value=counts):
        got, kw0, rest = H._rotate("x", got, got["keyword"], todo, todo)
    return got["category"], kw0, sorted(r["keyword"] for r in rest)


def test_rotate_picks_the_least_written_category():
    print("\n■ 次に書く語: 分野を順に回す社は、記事のいちばん少ない分野から書く")
    cfg = {"categories": CATS, "category_rotate": True, "category_terms": TERMS}
    todo = [_row("りんご 1"), _row("みかん 1"), _row("ぶどう 1"), _row("ぶどう 2")]
    check("記事が a2・b1・c0 なら c の語を選び、候補も c の語だけにする",
          _pick(cfg, todo, {"a": 2, "b": 1, "c": 0}), ("c", "ぶどう 1", ["ぶどう 1", "ぶどう 2"]))
    check("同数（b0・c0）なら categories の並び順（b）", _pick(cfg, todo, {"a": 1, "b": 0, "c": 0})[:2], ("b", "みかん 1"))
    check("いちばん少ない分野（c）に未着手が無ければ、次に少ない分野（b）",
          _pick(cfg, todo[:2], {"a": 2, "b": 1, "c": 0})[:2], ("b", "みかん 1"))


def test_category_of_and_brief():
    import hub_client as H
    print("\n■ 次に書く語: 語の分野は category_terms の言葉で決め、指示書で分野を名指しする")
    cfg = {"category_terms": dict(TERMS, _note="説明")}
    check("言葉を含む語はその分野・どれにも当たらない語は空", (H.category_of("ぶどう 費用", cfg), H.category_of("もも", cfg)),
          ("c", ""))
    src = (ROOT / "scripts" / "site_brief.py").read_text(encoding="utf-8")
    check("指示書が分野を順に回す社に分野を指定する",
          'if cfg.get("category_rotate") and nxt.get("category") in (cfg.get("categories") or {}):' in src, True)


def test_client_does_not_write_without_ledger_keyword():
    print("\n■ 記事の枠: お客様の社は、台帳に書ける語が無い日は書かない（AI が自分で題を決めない）")
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    check("執筆前の食い合いの段で、お客様の社（quiet）の KW_GATE=skip は止める",
          'if [ "${{ steps.site.outputs.quiet }}" = "yes" ] && echo "$out" | grep -q "KW_GATE=skip"; then' in wf, True)


def test_without_rotate_is_unchanged():
    print("\n■ 次に書く語: 順に回す印の無い社は、今までどおり台帳の先頭")
    todo = [_row("りんご 1"), _row("ぶどう 1")]
    check("良い例: 印の無い社は台帳の先頭のまま・候補も減らさない",
          _pick({"categories": CATS, "category_terms": TERMS}, todo, {"a": 5, "b": 0, "c": 0}),
          ("", "りんご 1", ["ぶどう 1", "りんご 1"]))
