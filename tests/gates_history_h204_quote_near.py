# -*- coding: utf-8 -*-
"""2026-11-21 採点役が本文の文を写すときに数文字を落とし、採点が2回とも無効になって記事の採点が止まった。

お客様の記事2本で「一次性（抽出性）の引用が本文にありません」が続いた。手元で同じ記事を本番と同じ版の claude で5回
採点すると、引用15個のうち1個が、53字の文の途中の3字を落とした写しだった（作った文ではない）。
1割以内の字の違いで本文の1か所と一致し、数字が同じなら引用として認める。作った文・数字を変えた文・
離れた2文の継ぎはぎ・短い引用の違いは今まで通り無効にする。本物の claude は呼ばない。
"""
import json
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

S1 = "紙の申込書が多かった店舗では、80枚の申込書で読み取りを試し、正しく読めたのは52枚でした（2025年4月）。"
S2 = "例外の多い窓口では、人の確認が1日40件から36件にしか減りませんでした。"
HEAD = f"---\ntitle: 試しの記事\n---\n\n## 試作をやめる判断\n\n試作をやめる判断の材料もあります。**{S1}** 途中の段落です。\n\n"
ART = HEAD + "ここから先は別の話題です。" * 20 + f"\n\n{S2}\n"


def _answer(quote):
    return "```json\n" + json.dumps({k: {"score": 90, "quote": quote, "weaknesses": ["弱い点"]}
                                     for k in ("originality", "extractability", "decision")}, ensure_ascii=False) + "\n```"


def test_dropped_chars_pass_and_made_up_quotes_fail():
    import quality_loop as QL
    print("\n■ 採点役の写し違い（途中の数文字を落とした）は認め、作った引用は今まで通り無効")
    ok = lambda q: QL.quote_ok(q, ART)
    check("本文そのまま（強調の記号つきの文）", ok(S1), True)
    check("途中の4字を落とした写し", ok(S1.replace("紙の申込書が", "紙が")), True)
    check("途中に2字を足した写し", ok(S1.replace("正しく読めた", "正しく文字を読めた")), True)
    check("数字を変えた写し", ok(S1.replace("52枚", "62枚")), False)
    check("頭だけ同じで中身を作った文", ok("紙の申込書が多かった店舗では、すべての申込書をAIが一度で正しく読み取りました。"), False)
    check("離れた2文の継ぎはぎ", ok(S1[:30] + S2[10:]), False)
    check("短い引用の1字違い（1割に満たない長さは許さない）", ok("人の確認が1日40件から"), True)
    check("短い引用の1字違い", ok("人の確認は1日40件から"), False)
    check("本文に無い文", ok("当社は3,000社の採択を支援しました。"), False)
    check("「…」で省いた引用の各部分に写し違い", ok("紙が多かった店舗では、80枚の申込書で…正しく読めたのは52枚でした"), True)
    got, why = QL.parse(_answer(S1.replace("紙の申込書が", "紙が")), ART)
    check("採点の応答の形でも、写し違いの引用で採点が通る", (bool(got), why), (True, ""))
    got, why = QL.parse(_answer(S1.replace("52枚", "62枚")), ART)
    check("数字を変えた引用は採点ごと無効", (got, why.endswith("（言い換え・作った引用は無効）")), (None, True))
