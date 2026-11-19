# -*- coding: utf-8 -*-
"""2026-11-19 運用者「AI集客ラボの記事も買い手の語を中心にして」。
AI集客ラボは買い手の語を先に書く社（kw_buyer_first）だが、未着手に買い手の語が0本で、買い手でない語を書いていた。
語の計画は「買い手の語の未着手 3本 < 1か月分30本」で組むと決めたのに、積む本数は未着手の全体（59本）で数え、
「目標36本に届いている」として0本しか積まず、その月の1回を使い切っていた（2026-11-12）。候補も買い手の語に絞っていなかった。
買い手の語で組む回は、積む本数を買い手の語の在庫で数え、候補も買い手の語だけにする"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_buyer_shortage_plans_buyer_words():
    import kw_intent as KI
    import kw_plan as KP
    print("\n■ 語の計画: 買い手の語が足りなくて組む回は、買い手の語の在庫で本数を数え、買い手の語だけを積む")
    buyer, other = "SEO 外注 費用", "歯医者 集客"
    check("例の語の判定（買い手の語・買い手でない語）", (KI.is_buyer(buyer), KI.is_buyer(other)), (True, False))
    todo = [buyer] * 3 + [other] * 56
    check("買い手の語で組む回は、買い手の語だけを在庫に数える（59本中3本）", len(KP.stock_have(todo, True)), 3)
    check("ほかの回は全体を数える", len(KP.stock_have(todo, False)), 59)
    cands = {"a": {"kw": buyer, "src": {"free"}}, "b": {"kw": other, "src": {"sheet"}},
             "c": {"kw": "AIO対策 会社", "src": {"free"}}}
    fate = {}
    check("買い手でない候補を外した件数", KP._keep_buyers(cands, fate), 1)
    check("残るのは買い手の語・シートの語には外した理由を残す", (sorted(cands), fate), (["a", "c"], {"b": "買い手の語でない"}))
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    run = src[src.index("def run(site_id"):src.index("def main(")]
    check("積む本数は、組むと決めた在庫と同じ数え方で引く（全体の未着手で引かない）",
          ("target - len(have)" in run, 'target - len(st["todo"])' in run), (True, False))
    check("無料の候補と予備の候補の両方で、買い手の語に絞る", run.count("_keep_buyers(cands, sheet_fate)"), 2)
    check("在庫で組む回だけ絞る（一新・主力だけ・手動の回は絞らない）",
          "buyer_only = if_needed and not replace and not main_first and hub_client._buyer_first(site_id)" in run, True)
    check("買い手の語を1本も積めなかった回は、要対応で知らせる",
          "要対応: 買い手の語を積めませんでした" in run, True)
