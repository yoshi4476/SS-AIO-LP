# -*- coding: utf-8 -*-
"""2026-11-12 キーワードの計画に、買い手の語（頼む先を探す・比べる・値段を知る語）の候補が少なかった。
計画は買い手の語に加点するが、起点は「業種×意図」で作るため、意図に買い手の言葉を足しても
「エステサロン 申請サポート 費用」のような誰も打たない組になり、候補が増えなかった（課金なしの試行で確かめた）。
自社のサイトにも「狙う語」（kw_seeds.targets）を置き、シートの狙う語と同じく単体で起点にする"""
import json
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_own_sites_can_seed_buyer_terms_as_they_are():
    import kw_intent
    import kw_plan as KP
    print("\n■ 狙う語（kw_seeds.targets）: 自社のサイトの買い手の語を、単体で起点にする")
    S = {"cfg": {"kw_seeds": {"targets": ["経理代行　費用", "経理代行 費用", " 記帳代行 比較 ", ""]}}}
    check("空白をそろえ、同じ語は1つにし、空は捨てる", KP.own_targets(S), ["経理代行 費用", "記帳代行 比較"])
    check("置いていないサイト（お客様の社など）は空", (KP.own_targets({"cfg": {}}), KP.own_targets({"cfg": {"kw_seeds": {}}})), ([], []))
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("シートの狙う語に続けて起点にする（シートの語が先・重ねない）",
          'S["sheet"] = S["sheet"] + [t for t in own_targets(S) if t.lower() not in [x.lower() for x in S["sheet"]]]' in src, True)
    for sid in ("ai-lab", "corporate", "subsidy"):
        cfg = json.loads((ROOT / "sites" / f"{sid}.json").read_text(encoding="utf-8"))
        ts = cfg.get("kw_seeds", {}).get("targets") or []
        owns = [str(o).lower() for o in cfg.get("owns") or []]
        check(f"{sid}: 狙う語が10以上あり、どれも買い手の語で、担当の領域の語を含む",
              (len(ts) >= 10, [t for t in ts if not kw_intent.BUYER.search(t.lower())], [t for t in ts if not any(o in t.lower() for o in owns)]),
              (True, [], []))
