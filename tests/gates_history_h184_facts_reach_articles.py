# -*- coding: utf-8 -*-
"""一次情報が記事に届くか（2026-11-16 運用者「一次情報は十分か」を調べて見つけた2つ）。
1. 補助金サイトは使う一次情報を id の型（facts_allow）で絞っていて、自社の補助金の一次情報（sub-*・質問シートの
   subsidy-m*）48件のうち45件が記事に渡っていなかった（他サイトの数字を外す絞り込みに、後から増えた自社の分が入っていない）
2. 質問シートの記事ごとの答えから作った文が「本記事」「この記事」のまま22件登録された。一次情報はサイトのどの記事にも入るので、
   別の記事では事実と違う文になる。登録の時に記事の題へ置き換え、記事の行でなければ保留にする"""
import json
import re
from pathlib import Path

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent
THIS = re.compile(r"本記事|この記事|同記事|当記事")


def test_site_facts_reach_their_own_site():
    import facts as F
    print("\n■ 一次情報: 自社サイトに登録した一次情報は、そのサイトの記事に渡る")
    d = json.loads((ROOT / "data" / "first_party_facts.json").read_text(encoding="utf-8"))["facts"]
    for site, own in (("subsidy", ("sub-", "subsidy-")), ("corporate", ("corporate-",)), ("ai-lab", ("ai-lab-",))):
        mine = [f["id"] for f in d if site in f.get("sites", []) and str(f["id"]).startswith(own)]
        used = {f["id"] for f in F.load_for(site)[1]}
        check(f"{site}: そのサイトだけの一次情報で、記事に渡らないもの", [i for i in mine if i not in used], [])
    used = {f["id"] for f in F.load_for("subsidy")[1]}
    check("悪い例: 補助金に他サイトの MEO の店舗数は渡さない（絞り込みは残す）", "meo-3200" in used, False)


def test_no_this_article_in_site_wide_facts():
    print("\n■ 一次情報: 「本記事」「この記事」と書いた文を残さない（どの記事にも入るため）")
    d = json.loads((ROOT / "data" / "first_party_facts.json").read_text(encoding="utf-8"))["facts"]
    e = json.loads((ROOT / "data" / "experiences.json").read_text(encoding="utf-8"))["experiences"]
    check("一次情報・体験の文に「本記事」「この記事」", [x["id"] for x in d + e if THIS.search(str(x.get("claim") or x.get("text") or ""))], [])


def test_sheet_names_the_article():
    import material_sheet as M
    print("\n■ 質問シート: 記事の行の「本記事」は記事の題に置き換え、記事の行でなければ保留")
    titles = lambda: {"x-slug": "Xの題"}  # noqa: E731
    row = {"key": "req:x-slug:1"}
    check("記事の行: 題に置き換える", M._name_article("当社が2026年11月9日に本記事の論点5問を聞きました。", row, titles),
          "当社が2026年11月9日に当社の記事「Xの題」の論点5問を聞きました。")
    check("記事の行:「当社のこの記事も」", M._name_article("当社のこの記事も5件のうち3件で出典に挙がりました。", row, titles),
          "当社の記事「Xの題」も5件のうち3件で出典に挙がりました。")
    check("悪い例: 記事の行でない（決まった質問）なら None（保留）", M._name_article("本記事で5件を数えました。", {"key": "fixed:1"}, titles), None)
    check("良い例: 「本記事」が無ければそのまま", M._name_article("120件を支援しました。", {"key": "fixed:1"}, titles), "120件を支援しました。")
    base = {"no": "1", "key": "fixed:1", "item": "決まった質問", "period": "", "count": "", "ok": "可", "target": "",
            "question": "q", "answer": "本記事の論点を5問聞き、3件で出典に挙がりました"}
    reply = json.dumps({"facts": [{"no": "1", "claim": "当社が本記事の論点を5問聞き、3件で出典に挙がりました。"}]}, ensure_ascii=False)
    f, _e, held = M.plan("ai-lab", [base], ask=lambda *_: reply)
    check("plan: 記事の行でない「本記事」の文は登録せず保留", (f, [w.split("：")[0] for _, w in held]), ([], ["どの記事か分からない"]))
