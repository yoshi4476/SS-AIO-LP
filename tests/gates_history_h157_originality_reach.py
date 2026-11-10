# -*- coding: utf-8 -*-
"""2026-11-09 コーポレートのクリニックの記帳代行が、公開前の採点で一次性73点のまま下書きにしまわれた。
自社の数字は業種を問わない集計しか無く、直しで主題に固有の数字を足すと検算で戻された。
運用者「一次性で届かない記事はなんとか85点以上にしてほしい」（2026-11-10）。基準は下げず、作り話もさせずに:
1. 当社調べの論点ごとの数を直しの材料に入れる  2. 一次情報で確かめた公的資料の数字を直しの材料に入れる
3. しまった下書きを翌日から戻す  4. 業種の材料も公的資料も無い業種の題は後回しにする
"""
import json
import re
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_public_facts_ledger_is_sourced_and_scoped():
    import public_facts as PF
    print("\n■ 公的資料の台帳: 文ごとに公的機関・法令の URL と確かめた日があり、業種の語のある題にだけ当たる")
    rows = PF.load()
    official = re.compile(r"^https://([a-z0-9-]+\.)*(go\.jp|e-gov\.go\.jp|or\.jp|lg\.jp)/")
    bad = [f.get("claim", "")[:20] for f in rows
           if not (official.match(str(f.get("url", ""))) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(f.get("checked", "")))
                   and f.get("words") and re.search(r"\d", str(f.get("claim", ""))) and f.get("org"))]
    check("台帳の文はすべて公的な URL・確かめた日・当てる語・数字・出どころの名前がある", (len(rows) > 0, bad), (True, []))
    check("クリニックの題には当たり、業種の無い題には当たらない",
          (len(PF.for_text("クリニック 記帳代行")) > 0, PF.for_text("記帳代行 費用")), (True, []))
    check("業種の語の見分け", (PF.industry_of("介護事業所 経理代行"), PF.industry_of("経理代行 費用")), ("介護", ""))


def test_topic_claims_go_to_materials_not_to_default_claims():
    import own_survey as OS
    print("\n■ 当社調べ: 論点ごとの数は直しの材料にだけ出し、記事の既定の文には足さない")
    res = {"ok": True, "v": OS.VERSION, "date": "2026-11-09", "slug": "zz", "engines": ["A", "B"], "answers": 10,
           "questions": ["q"] * 5, "official": [{"term": "健康保険法", "org": "国税庁", "of": 10, "hits": 0}],
           "topics": [{"topic": "t1", "words": ["保険診療"], "hits": 8, "of": 8},
                      {"topic": "t2", "words": ["診療報酬"], "hits": 2, "of": 8}],
           "dims": {}, "sources": {}}
    got = OS.topic_claims(res)
    check("触れた答えの少ない論点から、件数つきの文にする", got[0], "同じ調べで、ほかの論点を聞いた答え8件のうち、『診療報酬』に触れたものは2件でした。")
    check("既定の文（claims）には論点ごとの文を入れない", any("診療報酬" in c for c in OS.claims(res)), False)
    src = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("直しの材料が論点ごとの文と公的資料を読む",
          ("own_survey.topic_claims(res)" in src, "PF.for_text(" in src, '"出典: 公的資料"' in src), (True, True, True))


def test_shelved_drafts_come_back_next_day_then_weekly():
    import quality_loop as QL
    print("\n■ しまった下書き: 最初の4回は翌日に戻し、その後は7日ごとに戻す")
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "q.jsonl"

        def run(n_shelves, days_after):
            rows = [{"slug": "zz", "site": "corporate", "action": "shelve", "at": "2026-11-01 10:00"}] * n_shelves
            log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            day = (__import__("datetime").date(2026, 11, 1) + __import__("datetime").timedelta(days=days_after)).isoformat()
            with mock.patch.object(QL, "unshelve", lambda s: True), mock.patch.object(QL, "record", lambda r: None), \
                    mock.patch.object(QL, "site_of", lambda s: "corporate"):
                return QL.retry_shelved(path=log, today=day)
        check("1回目にしまった翌日に戻す", run(1, 1), ["zz"])
        check("しまった当日は戻さない", run(1, 0), [])
        check("5回目からは7日待つ", (run(5, 1), run(5, 7)), ([], ["zz"]))


def test_industry_topics_without_backing_go_later():
    import hub_client as HC
    print("\n■ 語の選び方: 業種の材料も公的資料も無い業種の題は、公的資料のある業種の題・業種に絞らない題の後ろに回す")
    got = {"keyword": "介護事業所 記帳代行", "site": "corporate"}
    todo = [{"keyword": k} for k in ("介護事業所 記帳代行", "記帳代行 費用", "クリニック 経理代行")]
    no_mat = lambda k: False
    check("公的資料のある業種の題を先に", HC._industry_backed("corporate", got, got["keyword"], todo, no_mat)["keyword"],
          "クリニック 経理代行")
    check("無ければ業種に絞らない題を先に",
          HC._industry_backed("corporate", got, got["keyword"], todo[:2], no_mat)["keyword"], "記帳代行 費用")
    check("業種に絞らない題・公的資料のある題はそのまま",
          (HC._industry_backed("corporate", {"keyword": "記帳代行 費用"}, "記帳代行 費用", todo, no_mat),
           HC._industry_backed("corporate", {"keyword": "クリニック 経理代行"}, "クリニック 経理代行", todo, no_mat)),
          (None, None))
