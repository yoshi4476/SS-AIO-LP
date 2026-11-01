# -*- coding: utf-8 -*-
"""2026-11-01 一次性（80点）に届かない記事に具体的な数字を足したいが、記入済みのヒアリングシートの数字は台帳に
登録済みのものだけだった。AI に「仮の実績」を作らせるのは優良誤認なので断り、運用者が認めた2つの手だけを入れた。
1. 計算で作る一次情報（derived_facts.py）: AI は登録済みの一次情報どうしの計算の候補を出すだけ。式と文の数は元の文の数か
   計算し直した値だけ・割合は母数10以上・期間の違うものは文に両方の期間。外れた候補は登録しない。同じ元と式は同じ id を上書き
2. 記事の試算（score_check.estimate_issues）: 「試算」「仮に」の文を結果・実績の言い方で書けば FAIL、前提が無ければ警告。
   「試算表」（会計の帳票）と「試算します」（手順）は試算として見ない
3. お客様の社は一次情報の文も id もログに出さず、非公開の置き場にだけ書く
社は架空の zz-*。AI は呼ばず、ask を差し替える。
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

FACTS = [
    {"id": "zz-total", "sites": ["zz-own"], "topic": ["記帳代行"], "period": "2024-04〜2026-09", "denominator": 48,
     "claim": "2024年4月から2026年9月までに記帳代行を担当したのは累計48社です", "as_of": "2026-09"},
    {"id": "zz-active", "sites": ["zz-own"], "topic": ["記帳代行"], "period": "2024-04〜2026-09",
     "claim": "2026年9月時点で記帳代行を続けているのは31社です", "as_of": "2026-09"},
    {"id": "zz-small", "sites": ["zz-own"], "topic": ["給与計算"], "period": "2026-04〜2026-09", "denominator": 6,
     "claim": "給与計算を担当した6社のうち4社で締めの日数が減りました", "as_of": "2026-09"},
    {"id": "zz-hours", "sites": ["zz-own"], "topic": ["経費精算"], "period": "2025-10〜2026-03",
     "claim": "経費精算の作業時間は、担当した5社の合計で月40時間でした", "as_of": "2026-03"},
    {"id": "zz-close", "sites": ["zz-own"], "topic": ["経理代行"], "period": "2023-04〜2026-09",
     "claim": "経理代行を担当した9社では、月次の締めが平均で翌月20日から翌月8日に早まりました", "as_of": "2026-09"},
    {"id": "zz-aio", "sites": ["zz-own"], "topic": ["AIO"], "period": "2026-05",
     "claim": "2026年5月に運用を始めた10件のうち6件が、1か月以内に平均順位が上がりました", "as_of": "2026-06"},
    {"id": "zz-cite", "sites": ["zz-own"], "topic": ["AI検索"], "period": "2026-10",
     "claim": "4つのAIへ15の語を聞いたところ、出典に挙がったのは計3回でした", "as_of": "2026-10"},
    {"id": "zz-imp", "sites": ["zz-own"], "topic": ["検索"], "period": "2026-09〜2026-10",
     "claim": "1日あたりの表示は約130回から約252回に増えました", "as_of": "2026-10"},
]
GOOD = {"inputs": ["zz-total", "zz-active"], "expr": "31/48*100",
        "claim": "累計48社のうち継続中は31社で、継続している割合は約65%です"}


def test_derived_facts_are_verified():
    import derived_facts as DF
    print("\n■ 1. 計算で作る一次情報: 元の数と計算し直した値だけを通す")
    row, why = DF.verify(GOOD, FACTS)
    check("登録済みの2つの数の割合（31÷48＝約65%）は通り、元の id と母数が残る",
          (why, row and row["inputs"], row and row["denominator"]), (None, ["zz-total", "zz-active"], 48))
    bad = {
        "文に元にも結果にも無い数（52社）": dict(GOOD, claim="累計48社のうち継続中は31社で約65%、紹介は52社です"),
        "結果を盛った（約70%）": dict(GOOD, claim="累計48社のうち継続中は31社で、約70%です"),
        "式に元に無い数（1.2倍）": dict(GOOD, expr="31/48*100*1.2", claim="約77%です"),
        "母数10未満の割合（4÷6）": {"inputs": ["zz-small"], "expr": "4/6*100", "claim": "6社のうち4社、約67%です"},
        "登録に無い id": dict(GOOD, inputs=["zz-total", "zz-nothing"]),
        "見込みの言い方": dict(GOOD, claim="累計48社のうち31社が継続し、来年も約65%が続く見込みです"),
        "式に使っていない一次情報を元に挙げる": dict(GOOD, inputs=["zz-total", "zz-active", "zz-hours"]),
        "計算になっていない（言い直し）": {"inputs": ["zz-total"], "expr": "48*1", "claim": "累計48社です"},
        "数えた物の違う数の割合（3回÷15の語）": {"inputs": ["zz-cite"], "expr": "3/15*100", "claim": "15の語のうち3回、約20%です"},
        "概数からの計算に小数（約93.8%）": {"inputs": ["zz-imp"], "expr": "(252-130)/130*100",
                                       "claim": "約130回から約252回で、約93.8%増えました"},
        "対象9社の短縮率（割る数は日数20でも母数は9社）": {"inputs": ["zz-close"], "expr": "(20-8)/20*100",
                                              "claim": "9社では締めが翌月20日から翌月8日に早まり、短縮率は約60%です"},
    }
    aio = {"inputs": ["zz-aio"], "expr": "6/10*100", "claim": "10件のうち6件が1か月以内に上がり、割合は60%です"}
    check("母数10件の割合（10件のうち6件＝60%）は通す", DF.verify(aio, FACTS)[1], None)
    for name, cand in bad.items():
        row, why = DF.verify(cand, FACTS)
        check(f"却下: {name}", (row is None, bool(why)), (True, True))
    mix = {"inputs": ["zz-active", "zz-hours"], "expr": "40/31", "claim": "31社で月40時間、1社あたり約1.3時間です"}
    check("期間の違う一次情報を混ぜ、文に両方の期間が無ければ却下", DF.verify(mix, FACTS)[1],
          "期間の違う一次情報を混ぜ、文に両方の期間が無い")
    mix["claim"] = "2024年4月〜2026年9月の31社と、2025年10月〜2026年3月の月40時間では、1社あたり約1.3時間です"
    check("文に両方の期間を書けば通す", DF.verify(mix, FACTS)[1], None)
    one = {"inputs": ["zz-hours"], "expr": "40/5",
           "claim": "2025年10月〜2026年3月の経費精算は、5社の合計月40時間で、1社あたり月8時間です"}
    check("1つの一次情報の割り算（1社あたり）は「1社あたり」の1を数に数えず通す", DF.verify(one, FACTS)[1], None)


def test_propose_write_and_confidentiality():
    import derived_facts as DF
    import private_store as P
    import sites as S
    print("\n■ 2. 候補は ask を差し替えて作る・同じ元と式は同じ id を上書き・お客様の社はログに文も id も出さない")
    reply = json.dumps({"calcs": [GOOD, dict(GOOD, claim="累計48社のうち31社、約70%です"),
                                  dict(GOOD, claim="継続中31社÷累計48社＝約65%")]}, ensure_ascii=False)
    asked = []
    ok, bad = DF.propose("zz-own", FACTS, ask=lambda p: asked.append(p) or reply)
    check("候補は1回の問いで作り、同じ元と式は1件にまとめ、盛った候補は却下",
          (len(asked), len(ok), len(bad), ok[0]["id"].startswith("zz-own-calc-")), (1, 1, 1, True))
    old = (S.is_client, P.is_client, DF.OWN_FACTS, DF.usable, os.environ.get("SS_PRIVATE_DIR"))
    with tempfile.TemporaryDirectory() as td:
        try:
            S.is_client = P.is_client = lambda s: False
            DF.OWN_FACTS = Path(td) / "f.json"
            DF.OWN_FACTS.write_text(json.dumps({"facts": FACTS}, ensure_ascii=False), encoding="utf-8")
            DF.usable = lambda s: FACTS
            DF.run("zz-own", True, ask=lambda p: reply)
            DF.run("zz-own", True, ask=lambda p: reply.replace("約65%です", "約65%でした"))
            fs = json.loads(DF.OWN_FACTS.read_text(encoding="utf-8"))["facts"]
            calc = [f for f in fs if f.get("derived_from")]
            check("入れ直しても積み増さず、元の一次情報は残り、出典は「計算（元: …）」",
                  (len(fs), len(calc), calc[0]["source"], calc[0]["claim"].endswith("でした")),
                  (len(FACTS) + 1, 1, "計算（元: zz-total・zz-active）", True))
            many = json.dumps({"calcs": [dict(GOOD, expr=e) for e in ("31/48*100", "31*100/48", "100*31/48")]})
            check("1回に登録する数には上限がある", len(DF.run("zz-own", False, ask=lambda p: many, cap=1)[0]), 1)
            os.environ["SS_PRIVATE_DIR"] = str(Path(td) / "private")
            S.is_client = P.is_client = lambda s: True
            out = io.StringIO()
            with redirect_stdout(out):
                DF.run("zz-client", True, ask=lambda p: reply)
            log = out.getvalue()
            got = P.read_json("zz-client", "facts.json", {}) or {}
            check("お客様の社: ログは件数だけ（文・id を出さない）、登録は非公開の置き場",
                  ("31社" in log or "zz-total" in log or "zz-client-calc" in log, "（お客様の社）" in log,
                   len(got.get("facts", []))), (False, True, 1))
        finally:
            S.is_client, P.is_client, DF.OWN_FACTS, DF.usable = old[:4]
            if old[4] is None:
                os.environ.pop("SS_PRIVATE_DIR", None)
            else:
                os.environ["SS_PRIVATE_DIR"] = old[4]


def test_estimates_in_articles():
    import score_check as SC
    print("\n■ 3. 記事の試算: 結果・実績の言い方は FAIL、前提の無い試算は警告、試算表と手順は見ない")
    good = ("試算：月100枚の請求書を1枚3分で処理すると、月5時間です。\n\n"
            "仮に時給2,000円の担当者が月10時間かけるなら、月2万円分の手間になります。\n")
    check("前提つきの試算は通す", SC.estimate_issues(good), ([], []))
    bad = ("試算では、月100枚の請求書の処理が月5時間削減できました。\n\n"
           "仮に月100枚とした場合の当社の実績は月5時間です。\n\n"
           "当社調べの試算で、作業時間は月20時間になりました。\n")
    check("試算を結果・実績・当社調べの言い方で書けば3文とも拾う", len(SC.estimate_issues(bad)[0]), 3)
    check("前提の無い試算は警告に拾う", len(SC.estimate_issues("試算：月5時間・年60時間の節約です。\n")[1]), 1)
    other = ("会計ソフトの試算表を月5日までに出します。\n\n"
             "規模別に3パターンで試算します。\n\n## 自己負担を試算する4ステップ\n")
    check("試算表・手順の「試算します」・見出しは試算として見ない", SC.estimate_issues(other), ([], []))
