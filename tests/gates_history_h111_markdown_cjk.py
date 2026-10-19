# -*- coding: utf-8 -*-
"""2026-10-19 句点の直後で閉じる強調が ** のまま公開されていた（markdown 3.11 の閉じ方の変更）。

CI は requirements.txt に版の無い markdown の最新版（3.11.1）を入れ、「〜です。**文章」の ** が太字にならなかった。
手元（3.10.2）では正しく出るため、CI で作ったページだけに残った（AI集客ラボ163ページ・コーポレート147本）。
版を固定し、日本語の強調の形が太字になることを毎回確かめる。
"""
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_cjk_strong_closes_after_punctuation():
    import md2html
    print("\n■ 句点・読点・かっこの直後で閉じる強調が太字になる（** が残らない）")
    cases = ["**集客手法です。**文章作成", "**ただし、**ここが要点", "**「申請」です。**次に",
             "前の文。**強調の文です。**後ろの文"]
    out = [md2html.convert(c)[0] for c in cases]
    check("どの形も ** が残らず <strong> になる", [("**" not in o and "<strong>" in o) for o in out], [True] * len(cases))


def test_markdown_version_pinned():
    print("\n■ markdown の版を固定している（上げるときはこの門で確かめる）")
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    m = re.search(r"^markdown==([\d.]+)\s*$", req, re.M)
    check("requirements.txt で markdown の版を固定", bool(m), True)
