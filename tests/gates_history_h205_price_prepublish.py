# -*- coding: utf-8 -*-
"""2026-11-21 相場の決まり（外部委託の月額を数十万円より下に書かない）に外れた要約の文が、AI集客ラボで公開された。

決まりは全部の門（gates_history_e）だけが見ていて、公開前の機械採点（score_check。agent_guard --publish が配信の前に
呼ぶ）と、公開前の直しへの指示（quality_loop.machine_note）に無かった。公開の後に全部の門が落ちて気づいた。
同じ判定（scripts/price_claims.py）を、機械採点の止める項目と、直しの指示の両方に入れる。本物の claude は呼ばない。
"""
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

BAD = "**ホームページのSEO対策費用は、記事作成ツール・内製と有料ツール・部分支援・一括委託の4区分で、月数万円から月20万円以上まで開きます。**"
GOOD = ("**ホームページのSEO対策費用は4区分で、記事作成ツールは月4〜5万円前後、内製＋有料ツールは月数万〜数十万円、"
        "外部委託は部分支援で月数十万円〜、一括で月20万円以上です。**")


def _article(lead, cat="seo"):
    return (f"---\ntitle: ホームページのSEO対策の費用の目安と選び方\nslug: h205\ncategory: {cat}\n"
            f"keyword: ホームページ SEO対策 費用\ndescription: 試し\n---\n\n{lead}\n\n## 費用の区分\n\n本文です。\n")


def _price_checks(text):
    import score_check as SC
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "h205.md"
        p.write_text(text, encoding="utf-8")
        return [(n, ok, w) for n, ok, _d, w in SC.run("h205", path=p) if n.startswith("相場:")]


def test_price_rule_in_prepublish_check():
    import score_check as SC
    import quality_loop as QL
    print("\n■ 相場の決まりを、公開前の機械採点と直しの指示でも見る（全部の門だけでは公開の後に気づく）")
    bad = _price_checks(_article(BAD))
    check("機械採点: 外部委託を月数万円からの幅にまとめた文を止める（警告ではなく不合格）",
          [(ok, w) for n, ok, w in bad if "外部委託" in n], [(False, False)])
    check("機械採点: 区分ごとの額に直した文は通る",
          [ok for n, ok, _w in _price_checks(_article(GOOD))], [True, True])
    check("機械採点: 当社の価格を書いた文を止める",
          [ok for n, ok, _w in _price_checks(_article(GOOD + f"\n\n当社のAIO対策は月{__import__('price_claims').OWN_PRICE_MAN}万円です。"))
           if "当社" in n], [False])
    check("機械採点: AI集客ラボの外の記事（MEO・ほかの社）には当てない", _price_checks(_article(BAD, cat="meo")), [])
    check("配信の前（agent_guard）が止める項目の名前で、採点の観点の検査（SOFT）に入らない",
          [n for n, _ok, _w in bad if n.startswith(SC.SOFT)], [])
    with mock.patch.object(QL, "read", lambda s: _article(BAD)), mock.patch.object(QL, "site_of", lambda s: "ai-lab"):
        note = QL.machine_note("h205")
    check("直しの指示: 外れた文と、正しい相場（外部委託・部分支援は月数十万円〜）を名指しする",
          ("外部委託の月額を数十万円より下" in note, "月数十万円〜" in note, "月数万円から月20万円以上まで" in note),
          (True, True, True))
    with mock.patch.object(QL, "read", lambda s: _article(GOOD)), mock.patch.object(QL, "site_of", lambda s: "ai-lab"):
        check("直しの指示: 決まりどおりの文には出さない", "外部委託の月額" in QL.machine_note("h205"), False)
