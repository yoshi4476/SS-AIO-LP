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


def test_converter_change_redelivers_only_the_affected_format():
    import publish as P
    import publish_gap as G
    print("\n■ 配信の変換を変えた方式の社だけ、原稿が同じでも指紋が変わって配り直される（ほかの社の指紋は変えない）")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "a.md"
        src.write_text("本文", encoding="utf-8")
        plain = P.source_hash(src)
        md_no_slash = {"type": "external-md", "trailing_slash": False}
        check("末尾の / が無い形で原稿のまま配る社は指紋が変わる", P.source_hash(src, md_no_slash) != plain, True)
        check("ほかの方式・/ が正の社・設定なしは今までと同じ指紋",
              [P.source_hash(src, c) == plain for c in ({"type": "nextjs-json", "trailing_slash": False},
                                                         {"type": "external-md"}, {"type": "self-static"}, None)], [True] * 4)
        check("照合の側も配信と同じ指紋を作る", G.source_hash(src, md_no_slash), P.source_hash(src, md_no_slash))


def test_lead_is_counted_only_after_the_endpoint_accepts():
    print("\n■ 計測: 問い合わせ（lead_capture）は受付が受け取ったあとにだけ数える（送信の時点・購読では数えない）")
    js = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    nl = js.split("document.querySelectorAll('form.nl-form').forEach", 1)[1].split("document.querySelectorAll('form.form-panel')", 1)[0]
    panel = js.split("document.querySelectorAll('form.form-panel').forEach", 1)[1].split("document.querySelectorAll('.inline-tool')", 1)[0]
    check("購読フォームの送信で lead_capture を出さない", "ga('lead_capture'" in nl, False)
    check("相談フォームの送信の時点では lead_capture を出さず、控えを残す",
          ("ga('lead_capture'" in panel, "sessionStorage.setItem('ss_lead'" in panel), (False, True))
    thanks = js.split("location.pathname.indexOf('/thanks') === 0", 1)[1][:700] if "indexOf('/thanks') === 0" in js else ""
    check("お礼のページで1回だけ数え、送ったページの場所を付け、控えを消す",
          ("ga('lead_capture'" in thanks, "page_location: kept.url" in thanks, "removeItem('ss_lead')" in thanks), (True, True, True))


def test_every_article_has_an_entry_that_takes_contact():
    import industry_ai_sources as IAS
    print("\n■ 導線: 業種の調査が無い記事にも、連絡先を残す入口（チェックリストの受け取り）を置く")
    box = IAS.checklist_box()
    check("調査の無い記事の箱は、受け取りページへの入口を持ち、数字を書かない",
          ('href="/download/"' in box, 'data-cta="article_checklist_general"' in box, bool(re.search(r"\d+\s*(?:%|件|社)", box))),
          (True, True, False))
    check("調査はあるがチェックリストの無い業種の箱にも、受け取りの入口を出す",
          IAS.research_box.__code__.co_names.count("GENERAL_CHECKLIST") >= 1, True)
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("記事の末尾は、調査の箱が無ければチェックリストの箱を出す", "or IAS.checklist_box()" in src, True)


def test_price_ranges_reach_each_business():
    import facts as F
    print("\n■ 費用の相場: 事業ごとの相場が、その社の記事にだけ渡る（出どころつき。当社の語を金額の行に書かない）")
    corp, lab = F.price_sets("corporate"), F.price_sets("ai-lab")
    check("コーポレートには経理の相場、AI集客ラボには AIO の相場、補助金には無し",
          (bool(corp) and corp[0]["ranges"][0]["id"], lab[0]["ranges"][0]["id"], F.price_sets("subsidy")),
          ("kicho", "article_tool", []))
    check("足した相場には、公開の出どころ（URL と確かめた日）がある",
          [bool(re.search(r"https://\S+", s.get("source", ""))) and "確認" in s.get("source", "") for s in corp], [True] * len(corp))
    src = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("直しの材料も同じ入口（facts.price_sets）から読む", "F.price_sets(site)" in src, True)
