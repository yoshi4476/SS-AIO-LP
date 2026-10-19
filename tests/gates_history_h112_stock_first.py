# -*- coding: utf-8 -*-
"""2026-10-19 題の書き直しが、本文の出どころの無い体験談（「半年後に…何度も見てきました」）を拾って題にした。

サイトは7月開始で、半年後の様子を何度も見られたはずがない。決まり文句の残る記事は、題・説明文より先に
決まり文句の直し（stock）へ回す（auto_rewrite.stock_first）。
"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_title_candidates_with_stock_phrases_go_to_stock_first(tmp_path=None):
    import auto_rewrite as A
    print("\n■ 決まり文句の残る記事は、題・説明文より先に決まり文句を直す")
    arts = ROOT / "articles"
    bad, good = arts / "zz-gate-stock-bad.md", arts / "zz-gate-stock-good.md"
    fm = "---\ntitle: 架空の記事\ncategory: aio\nscore: 92\n---\n"
    try:
        bad.write_text(fm + "私も、半年後に競合へ引用を奪われている例を何度も見てきました。\n", encoding="utf-8")
        good.write_text(fm + "2026年9月の自社の計測では、表示が増えました。\n", encoding="utf-8")
        out = A.stock_first([{"kind": "title", "slug": bad.stem, "site": None, "why": ""},
                             {"kind": "desc", "slug": good.stem, "site": None, "why": ""},
                             {"kind": "stuck", "slug": bad.stem, "site": None, "why": ""}])
    finally:
        bad.unlink(missing_ok=True)
        good.unlink(missing_ok=True)
    check("決まり文句のある記事の題の直しは stock に差し替える", out[0]["kind"], "stock")
    check("決まり文句の無い記事の説明文の直しはそのまま", out[1]["kind"], "desc")
    check("題・説明文以外の直しは触らない", out[2]["kind"], "stuck")
    check("main が候補を stock_first に通す", "items = stock_first(items)" in (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8"), True)


def test_any_rewrite_keeps_changed_description_within_100_to_160():
    import auto_rewrite as A
    print("\n■ どの種類の直しでも、説明文が変わったら100〜160字を確かめる（題の直しが98字の説明文を公開した）")
    p = ROOT / "articles" / "zz-gate-desc-len.md"
    desc = "経理補助と経理事務の違いを、任せてよい作業と任せない作業に分けて整理します。" * 3
    body = f"---\ntitle: 経理補助と経理事務の違い｜任せてよい作業\nkeyword: 経理補助 違い\ncategory: aio\ndescription: {desc[:120]}\n---\n本文\n"
    try:
        p.write_text(body, encoding="utf-8")
        snap = A.snapshot()
        before = A.meta(p.stem)
        p.write_text(body.replace(desc[:120], desc[:98]), encoding="utf-8")
        ng = A.check(p.stem, before, [], snap)
    finally:
        p.unlink(missing_ok=True)
    check("説明文を98字に変えた直しは通さない", ng, "説明文が98字（100〜160字）")


def test_decor_year_titles_with_impressions_become_title_candidates():
    import rank_up
    print("\n■ 飾りの年号の題で、表示があるのにクリック0の記事は題の書き直しの候補になる")
    t = "---\ntitle: 経理代行の費用相場【2026年】\nkeyword: 経理代行 費用\ndate: 2026-08-01\n---\n本文\n"
    d = {"slug": "zz", "imp": 40, "clicks": 0, "pos": 15.0, "kws": [("経理代行 費用", 15.0, 40)]}
    kinds = [k for k, _, _ in rank_up.diagnose("zz", d, {"zz": t}, {"zz": d})]
    check("飾りの年号・表示40・クリック0 → deco", "deco" in kinds, True)
    d2 = dict(d, clicks=2)
    check("クリックが取れていれば候補にしない", "deco" in [k for k, _, _ in rank_up.diagnose("zz", d2, {"zz": t}, {"zz": d2})], False)
    t3 = t.replace("【2026年】", "と2024年問題")
    check("中身として要る年は候補にしない", "deco" in [k for k, _, _ in rank_up.diagnose("zz", d, {"zz": t3}, {"zz": d})], False)
