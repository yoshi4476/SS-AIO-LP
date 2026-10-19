# -*- coding: utf-8 -*-
"""2026-10-19 運用者の決定: 補助金は新しい記事を止め、2枠とも表示が出始めた既存記事の書き直しに回す。

浮いた枠の書き直しは主力の語の記事に絞っていたため、10/14 から候補が尽きて空振りしていた。
spare_scope: "emerging" の社は主力の語に絞らず、足す語が見つからない日は題の直しを候補にする。
"""
import json
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_subsidy_writes_no_new_articles_and_rewrites_both_slots():
    import pace
    print("\n■ 補助金は新しい記事0本・2枠とも書き直し（表示が出始めた記事）")
    cfg = json.loads((ROOT / "sites" / "subsidy.json").read_text(encoding="utf-8"))
    check("daily_articles は 0", cfg.get("daily_articles"), 0)
    check("spare_scope は emerging", cfg.get("spare_scope"), "emerging")
    if pace.signal_quota("subsidy") >= 2:
        check("1本目・2本目の枠はどちらも書き直し", [pace.slot("subsidy", r)[0] for r in (0, 1)], ["rewrite", "rewrite"])


def test_emerging_scope_widens_main_only():
    import auto_rewrite as A
    print("\n■ emerging の社は --main-only でも主力の語に絞らない（他の社は従来どおり主力の語だけ）")
    A._MAIN["zz-main"] = lambda s: "主力" in s
    orig = A.emerging_scope
    try:
        A.emerging_scope = lambda s: s == "zz-emerging"
        A.is_main = (lambda f: (lambda slug, site="": False))(A.is_main)
        check("emerging の社の主力でない記事は対象", A.in_scope("x", "zz-emerging"), True)
        check("emerging でない社の主力でない記事は対象外", A.in_scope("x", "zz-main"), False)
    finally:
        A.emerging_scope = orig
        import importlib
        importlib.reload(A)
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("無料の補充（free_spare_items）も in_scope で絞る", "not in_scope(slug, sid)" in src, True)
    check("足す語が無い日は題の直しを候補にする", "emerging_title_items(a.sites" in src, True)
