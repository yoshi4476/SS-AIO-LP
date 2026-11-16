# -*- coding: utf-8 -*-
"""台帳: シートの狙う語（運用者が選んだ語）のうち台帳に無い語を、ラッコを使わずに足す（kw_plan --sheet-fill。2026-11-17）。
新しく受けた社の語の計画が、検索数10未満の買い手の細い語を落として50語から17語しか積めず、1日2本では約9日で尽きた。
足すのは担当・除外語・食い合い・台帳の重複（語順・語尾だけ違う語を含む）を通った語だけ。語はログに出さない"""
import io
from contextlib import redirect_stdout
from unittest import mock

from test_gates import check

SHEET = ["りんご 費用", "りんご 外注", "みかん 運用代行", "ぶどう 依頼", "もも 依頼"]
LEDGER = ["みかん 運用代行 相場", "ぶどう 依頼"]


def _run():
    import hub_client
    import kw_plan as KP
    import private_store
    added = []
    st = {"ok": True, "todo": LEDGER, "a": [], "keys": set().union(*(KP.ledger_keys(k) for k in LEDGER))}
    fit = lambda k, s: (2, "除外語") if k.startswith("もも") else (0, "")
    with mock.patch.object(KP, "stock", return_value=st), \
            mock.patch.object(KP, "sheet_terms", return_value=(SHEET, [])), \
            mock.patch.object(KP.KD, "site_config", return_value={"cfg": {"kw_overlap_ok": True}}), \
            mock.patch.object(KP, "own_corpus", return_value=([], [])), \
            mock.patch.object(KP.kw_fit, "judge_new", side_effect=fit), \
            mock.patch.object(KP, "remember_added"), \
            mock.patch.object(private_store, "require", return_value=True), \
            mock.patch.object(private_store, "read_json", return_value={"keyword": {"main": ["りんご 費用"]}}), \
            mock.patch.object(hub_client, "add_kw", side_effect=lambda s, xs: added.extend(xs) or {"added": len(xs)}), \
            mock.patch.object(KP.rakko, "call", side_effect=AssertionError("ラッコを呼んだ")):
        buf = io.StringIO()
        with redirect_stdout(buf):
            n = KP.sheet_fill("x")
    return n, added, buf.getvalue()


def test_client_price_sets_come_from_private_and_match_topic():
    import json
    import tempfile
    from pathlib import Path

    import facts as F
    import private_store
    print("\n■ 相場: お客様の社の相場は非公開の置き場から読み、主題の言葉（topics）が記事の語に合う組だけを渡す")
    own = [{"topics": ["経理"], "ranges": [{"label": "経理の委託", "range": "月10万円"}]},
           {"topics": ["AIエージェント"], "ranges": [{"label": "AIエージェント開発", "range": "100万円"}]},
           {"ranges": [{"label": "主題の無い組", "range": "1万円"}]}]
    with tempfile.TemporaryDirectory() as td:
        pub = Path(td) / "price_ranges.json"
        pub.write_text(json.dumps({"sites": ["ai-lab"], "ranges": [{"label": "公開", "range": "0円"}]}), encoding="utf-8")
        with mock.patch.object(F, "_is_client", return_value=True), \
                mock.patch.object(private_store, "read_json", return_value=own), \
                mock.patch.object(F, "ROOT", Path(td).parent):
            got = lambda kw: [s["ranges"][0]["label"] for s in F.price_sets("x", kw=kw)]
            check("非公開の組を読む（語なしなら全部）", len(F.price_sets("x")), 3)
            check("「AIエージェント 開発 費用」には AIエージェントの組と主題の無い組だけ（経理の組を混ぜない）",
                  got("AIエージェント 開発 費用"), ["AIエージェント開発", "主題の無い組"])
        check("良い例: 公開側の台帳の組は今までどおり sites で選ぶ（お客様の社でなければ非公開を読まない）",
              [s["ranges"][0]["label"] for s in F.price_sets("ai-lab", path=pub)], ["公開"])


def test_sheet_fill_adds_only_new_fitting_words_without_rakko():
    print("\n■ 台帳: シートの語をラッコを使わずに足す（台帳にある・語順や語尾だけ違う・担当外の語は足さない）")
    n, added, out = _run()
    check("足すのは「りんご 費用」（優先度A）と「りんご 外注」（B）の2件だけ",
          (n, [(a["keyword"], a["priority"]) for a in added]), (2, [("りんご 費用", "A"), ("りんご 外注", "B")]))
    check("台帳の「みかん 運用代行 相場」がある「みかん 運用代行」と、台帳にある「ぶどう 依頼」と、除外語の語は足さない",
          {a["keyword"] for a in added} & {"みかん 運用代行", "ぶどう 依頼", "もも 依頼"}, set())
    check("語をログに出さない（件数と理由の内訳だけ）", any(k in out for k in SHEET), False)
    check("出どころの印は sheet", all("出どころ:sheet" in a["note"] for a in added), True)
