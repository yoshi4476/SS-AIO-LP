# -*- coding: utf-8 -*-
"""2026-11-23 auto_review --fix が、同じ言い回しの3本目を振り直さずに終わる回があった（歯科の記事の
「関連する内容として<L>も公開しています。」3本が週次のあとも残り、手元で --fix しても直らなかった）。
振り直しの型を hash(slug) で選んでいて、実行ごとに変わる値が同じ型を引いた回は、何も変えずに終わっていた。
同じ型・上限に達した型を引いたら次の型を試し、種は実行ごとに変わらない値にする。"""
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

SAME = "関連する内容として[{t}]({u})も公開しています。"
OTHER = "あわせて[{t}]({u})もご覧ください。"


def _article():
    paras = "\n\n".join(SAME.format(t=f"記事{i}", u=f"/aio/kiji-{i}/") for i in range(3))
    return f"---\ntitle: 試し\nslug: h208\n---\n\n## 見出し\n\n本文です。\n\n{paras}\n\n本文の続きです。\n"


def test_review_rerolls_same_form():
    import auto_review as R
    print("\n■ 自動修正の見直し: 同じ言い回しの3本目は、同じ型を引いても次の型を試して必ず振り直す")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h208.md"
        p.write_text(_article(), encoding="utf-8")
        head, body, paras = R.scan(p)
        check("前提: 同じ言い回しのリンク段落が3本", [x["form"] for x in paras].count(R.form_of(SAME.format(t="a", u="/b/"))), 3)
        calls = []

        def sentence(title, url, seed, fit):
            calls.append(seed)
            # 1回目は必ず同じ型（実行ごとの hash が同じ型を引いた回）。2回目からは別の型
            return (SAME if len(calls) % 2 == 1 else OTHER).format(t=title, u=url)

        import link_new as ln
        with mock.patch.object(ln, "sentence", sentence):
            edits = R.rewrite("h208", paras, head)
        check("同じ型を引いても次の型を試し、3本目を別の言い回しに振り直す",
              [R.form_of(new) for _s, _e, new in edits], [R.form_of(OTHER.format(t="a", u="/b/"))])
        with mock.patch.object(ln, "sentence", lambda t, u, seed, fit: OTHER.format(t=t, u=u)):
            seeds = []
            with mock.patch.object(ln, "sentence", lambda t, u, seed, fit: seeds.append(seed) or OTHER.format(t=t, u=u)):
                R.rewrite("h208", paras, head)
                first = list(seeds)
                seeds.clear()
                R.rewrite("h208", paras, head)
        check("種は実行ごとに変わらない（同じ記事なら毎回同じ型を選ぶ）", first == seeds and bool(first), True)
    src = (ROOT / "scripts" / "auto_review.py").read_text(encoding="utf-8")
    check("振り直しの型を hash() で選ばない（実行ごとに変わる）", "hash(slug)" in src, False)
