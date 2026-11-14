# -*- coding: utf-8 -*-
"""2026-11-15 運用者の承認: 1位を狙う語を「業種×サービスの組」ごとに台帳で持ち、毎週の順位と、担う記事の無い組を知らせ、
表示ゼロの記事をその語へ付け替える（担う記事があれば統合する）。
前は主要クエリが1社30語の決め打ちで、AI集客ラボの業種（8）×サービス（SEO・AIO・MEO・HP制作）のどの組を
どの記事が担っているか・担う記事の無い組がいくつあるかを、どこからも言えなかった。
表示ゼロの記事は近い記事へ統合するだけで、まだ誰も狙っていない買い手の語へ向け直す手が無かった"""
import sys
from datetime import date, timedelta

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

CONF = {
    "kw_seeds": {"priority": ["クリニック", "不動産"]},
    "key_queries": {
        "max": 28, "per_group": [3, 5],
        "industry_terms": {"クリニック": ["クリニック", "病院"], "不動産": ["不動産"]},
        "services": {"SEO": {"terms": ["seo", "上位表示"], "seed": "SEO対策"},
                     "AIO": {"terms": ["aio", "llmo", "ai検索"], "seed": "AIO対策"},
                     "MEO": {"terms": ["meo", "googleマップ"], "seed": "MEO対策"},
                     "HP制作": {"terms": ["ホームページ", "hp"], "seed": "ホームページ制作"}},
        "buyer_words": ["外注", "費用", "会社", "比較", "代行"],
    },
}


def _ledger():
    import key_queries as KQ
    n = KQ.norm
    declared = {n("クリニック SEO対策 費用"): ("クリニック SEO対策 費用", "clinic-seo-hiyou")}
    hub = ["クリニック seo 外注", "クリニック seo やり方", "歯科 seo 費用",
           "クリニックでseoとllmoの両方に強いコンサル会社は", "不動産に強いai検索対策の会社を教えてください"]
    ranks = {n("不動産 meo 費用"): {"q": "不動産 meo 費用", "imp": 40, "pos": 12.4,
                                   "url": "https://x.example/meo/fudousan-meo/"},
             n("クリニック seo 外注"): {"q": "クリニック seo 外注", "imp": 3, "pos": 25.0,
                                      "url": "https://x.example/seo/zz-none/"}}
    vols = {n("クリニック seo 外注"): 90}
    prev = [{"q": "クリニック SEO対策 費用", "base": 33.0, "base_at": "2026-09-23"}]
    rows = KQ.build_ledger(CONF, declared, hub, ranks, vols, prev=prev, today="2026-11-15",
                           slugs={"clinic-seo-hiyou", "fudousan-meo"})
    return KQ, rows


def test_key_query_cap_is_configurable():
    import key_queries as KQ
    import sites as S
    print("\n■ 主要クエリ: 1社30語の上限を sites/<id>.json の key_queries.max で変えられる")
    check("設定が無ければ今までどおり30語", KQ.limit_of({}), 30)
    check("設定があればその数", KQ.limit_of({"key_queries": {"max": 120}}), 120)
    check("壊れた設定は既定に戻す", KQ.limit_of({"key_queries": {"max": "abc"}}), 30)
    check("AI集客ラボは約120語（100〜130）", 100 <= KQ.limit_of(S.load("ai-lab")) <= 130, True)
    check("コーポレートは30語のまま", KQ.limit_of(S.load("corporate")), 30)
    conf = KQ.ledger_conf(S.load("ai-lab"))
    check("AI集客ラボの組は優先業種（8）×サービス（SEO・AIO・MEO・HP制作）",
          (len(conf["industries"]), [s for s, _t, _seed in conf["services"]]), (8, ["SEO", "AIO", "MEO", "HP制作"]))
    check("組の設定の無い社は台帳を作らない", KQ.ledger_conf(S.load("corporate")), None)


def test_ledger_rows_by_industry_and_service():
    KQ, rows = _ledger()
    print("\n■ 1位を狙う語の台帳: 業種×サービスの組ごとに買い手の語を3〜5個（検索の量の出どころ・担う記事・順位つき）")
    groups = {}
    for r in rows:
        groups.setdefault((r["ind"], r["svc"]), []).append(r)
    check("組は 2業種×4サービス＝8組", len(groups), 8)
    check("語の数は上限（28）ちょうど", len(rows), 28)
    check("どの組も3〜5語", all(3 <= len(v) <= 5 for v in groups.values()), True)
    import kw_intent
    check("台帳の語は全部が買い手の語（外注・費用・会社・比較・代行など）",
          all(kw_intent.is_buyer(r["q"]) for r in rows), True)
    by = {KQ.norm(r["q"]): r for r in rows}
    a = by.get(KQ.norm("クリニック seo 外注")) or {}
    check("ラッコの控えに量がある語は rakko の量（90）", (a.get("vol"), a.get("vol_src")), (90, "rakko"))
    check("量のある語を組の先頭に置く", groups[("クリニック", "SEO")][0]["q"], "クリニック seo 外注")
    check("着地ページが記事でなければ担う記事なし", a.get("slug"), "")
    b = by.get(KQ.norm("不動産 meo 費用")) or {}
    check("控えが無く GSC に表示がある語は gsc の表示（40）", (b.get("vol"), b.get("vol_src")), (40, "gsc"))
    check("狙う語の記事が無ければ GSC の着地ページを担う記事にする", (b.get("slug"), b.get("slug_src")), ("fudousan-meo", "gsc"))
    check("今の順位は GSC の記録から", b.get("pos"), 12.4)
    c = by.get(KQ.norm("クリニック SEO対策 費用")) or {}
    check("狙う語が一致する記事を担う記事にする", (c.get("slug"), c.get("slug_src")), ("clinic-seo-hiyou", "keyword"))
    check("前から追っている語は起点（base）をそのまま残す", (c.get("base"), c.get("base_at")), (33.0, "2026-09-23"))
    check("自分でやる人の語（やり方）は入れない", KQ.norm("クリニック seo やり方") in by, False)
    check("組に無い業種（歯科）の語は入れない", KQ.norm("歯科 seo 費用") in by, False)
    check("AI に聞くような文の問い（〜は・教えてください）は検索の語ではないので入れない",
          [q for q in ("クリニックでseoとllmoの両方に強いコンサル会社は", "不動産に強いai検索対策の会社を教えてください")
           if KQ.norm(q) in by], [])
    seed = by.get(KQ.norm("不動産 ホームページ制作 外注")) or {}
    check("データの無い組は kw_seeds の組み合わせで埋め、量は「なし」", (seed.get("vol_src"), seed.get("pos")), ("なし", KQ.OUT))
    check("新しい語の起点は今日の順位", (seed.get("base"), seed.get("base_at")), (KQ.OUT, "2026-11-15"))


def test_weekly_ledger_lines():
    import key_queries as KQ
    print("\n■ 毎週の知らせ: 順位の分布・先週との比較・担う記事の無い組（お客様の社は語も組も出さない）")
    rows = [{"q": "a 外注", "ind": "クリニック", "svc": "SEO", "slug": "x"},
            {"q": "b 外注", "ind": "クリニック", "svc": "MEO", "slug": ""},
            {"q": "c 外注", "ind": "不動産", "svc": "AIO", "slug": ""},
            {"q": "d 外注", "ind": "不動産", "svc": "SEO", "slug": ""},
            {"q": "e 外注", "ind": "工務店", "svc": "HP制作", "slug": ""},
            {"q": "f 外注", "ind": "買取店", "svc": "MEO", "slug": ""}]
    hist = [{"at": "2026-11-09", "site": "s", "q": "a 外注", "pos": 8.0},
            {"at": "2026-11-09", "site": "s", "q": "b 外注", "pos": 101.0},
            {"at": "2026-11-16", "site": "s", "q": "a 外注", "pos": 2.6},
            {"at": "2026-11-16", "site": "s", "q": "b 外注", "pos": 25.0},
            {"at": "2026-11-16", "site": "s", "q": "c 外注", "pos": 9.0},
            {"at": "2026-11-16", "site": "other", "q": "d 外注", "pos": 1.0}]
    out = KQ.ledger_lines("s", rows, hist, client=False)
    text = "\n".join(out)
    check("どの行も「情報:」で始まる（findings が拾う形）", all(x.startswith("情報:") for x in out), True)
    check("今週の分布（1〜3位1・4〜10位1・11〜30位1・圏外3）", "1〜3位 1語／4〜10位 1語／11〜30位 1語／圏外 3語" in text, True)
    check("先週の分布と、記録の無かった語の数", "先週 1〜3位 0語／4〜10位 1語／11〜30位 0語／圏外 1語（先週の記録が無い語 4）" in text, True)
    check("上がった・下がった語の数", "上がった 2語・下がった 0語" in text, True)
    gap = next((x for x in out if "担う記事が無い組" in x), "")
    check("担う記事の無い組の数（5組）と例は3つまで", ("担う記事が無い組 5組" in gap, gap.count("×")), (True, 3))
    secret = "\n".join(KQ.ledger_lines("s", rows, hist, client=True))
    check("お客様の社は語も組も出さない", any(w in secret for w in ("a 外注", "クリニック", "×MEO")), False)
    check("お客様の社も数は出す", "担う記事が無い組 5組" in secret, True)
    import findings
    check("週次の findings の本文に台帳の行を添える（情報。これだけでは通知しない）",
          "key_queries.py --line" in findings.INFO, True)


def test_stale_articles_retarget_or_merge():
    import retire_stale as RS
    print("\n■ 表示ゼロの記事: 台帳の近い語（同じ業種・サービス）へ付け替える／担う記事があれば統合する")
    import key_queries as KQ
    conf = KQ.ledger_conf(CONF)
    ledger = [{"q": "クリニック SEO対策 外注", "ind": "クリニック", "svc": "SEO", "slug": ""},
              {"q": "不動産 MEO対策 会社", "ind": "不動産", "svc": "MEO", "slug": "fudousan-meo-kaisha"},
              {"q": "不動産 SEO対策 外注", "ind": "不動産", "svc": "SEO", "slug": ""}]
    arts = {"c1": {"title": "クリニックのSEO対策を外注する前に", "keyword": "クリニック seo 外注 注意"},
            "f1": {"title": "不動産会社のMEO対策の始め方", "keyword": "不動産 meo 始め方"},
            "s1": {"title": "歯科医院のSEO対策", "keyword": "歯科 seo"},
            "c2": {"title": "クリニックのSEO対策の外注先", "keyword": "クリニック seo 外注先"},
            "c3": {"title": "クリニックSEOの外注で失敗しない", "keyword": "クリニック seo 外注 失敗"},
            "c4": {"title": "クリニックSEOの費用の決め方", "keyword": "クリニック seo 費用 決め方"},
            "fudousan-meo-kaisha": {"title": "不動産のMEO会社の選び方", "keyword": "不動産 MEO対策 会社"}}
    stale = [{"site": "s", "loser": s, "title": arts[s]["title"], "survivor": "", "sim": 0.0}
             for s in ("c1", "f1", "s1", "c2", "c3")]
    stale.append({"site": "s", "loser": "c4", "title": arts["c4"]["title"], "survivor": "near", "sim": 0.5})
    got = {r["loser"]: r for r in RS.route(stale, ledger, arts, conf, tried={"c3"}, pending={"c2"})}
    check("担う記事の無い語へは付け替える（狙う語を渡す）",
          (got["c1"]["action"], got["c1"].get("kw")), ("retarget", "クリニック SEO対策 外注"))
    check("担う記事のある語へは、その記事へ統合する",
          (got["f1"]["action"], got["f1"].get("survivor")), ("merge", "fudousan-meo-kaisha"))
    check("台帳の組に無い業種の記事は付け替えない（近い記事が無ければ残す）", got["s1"]["action"], "none")
    check("付け替えの判定期間中の記事は統合にも回さない", "c2" in got, False)
    check("一度付け替えを試した記事は付け替えず、今までの統合へ（毎週同じ記事に AI を使わない）",
          got["c3"]["action"], "none")
    check("同じ語へ2本は付け替えない（2本目は今までの統合へ）", got["c4"]["action"], "merge")
    check("今までの統合（近い記事）の吸収先は変えない", got["c4"].get("survivor"), "near")
    check("業種が違えば題が近くても別の業種の語を選ばない",
          RS.route([{"site": "s", "loser": "f9", "title": "不動産のSEO対策を外注", "survivor": "", "sim": 0}],
                   [ledger[0]], {"f9": {"title": "不動産のSEO対策を外注", "keyword": "不動産 seo 外注"}}, conf)[0]["action"],
          "none")
    check("すでに台帳の語を担う記事は、別の語へ付け替えない（担っている語を手放させない）",
          RS.route([{"site": "s", "loser": "f8", "title": "不動産SEO会社への外注の費用", "survivor": "", "sim": 0}],
                   [ledger[2], {"q": "不動産 SEO 会社", "ind": "不動産", "svc": "SEO", "slug": "f8"}],
                   {"f8": {"title": "不動産SEO会社への外注の費用", "keyword": "不動産 seo 会社"}}, conf)[0]["action"],
          "none")
    # 実データ: 「医療広告ガイドラインとは？クリニックHPの禁止6表現」→「クリニック ホームページ制作 外注」は 0.19（主題が違う）
    check("同じ組でも題と語が遠ければ付け替えない（近さの下限）",
          RS.route([{"site": "s", "loser": "g1", "title": "医療広告ガイドラインとは？クリニックHPの禁止6表現", "survivor": "", "sim": 0}],
                   [{"q": "クリニック ホームページ制作 外注", "ind": "クリニック", "svc": "HP制作", "slug": ""}],
                   {"g1": {"title": "医療広告ガイドラインとは？クリニックHPの禁止6表現", "keyword": "医療広告ガイドライン Web"}},
                   conf)[0]["action"], "none")
    check("週の上限は付け替えと統合を合わせて6本", RS.WEEK_LIMIT, 6)


def test_retarget_kind_allows_only_the_designated_keyword():
    import auto_rewrite as AR
    print("\n■ 付け替えの直し（auto_rewrite の retarget）: 狙う語を変えてよいのはこの種類で、決めた語へだけ")
    check("指示がある", "retarget" in AR.WHAT, True)
    check("直す前の原稿を残す（28日後に効かなければ戻す）", AR.keep_original("retarget"), True)
    check("別工程の採点を通す", "retarget" in AR.SCORE_GATED, True)
    check("ほかの種類は狙う語を変えると止める", bool(AR.kw_change_ng("title", "a b", "c d", "")), True)
    check("ほかの種類で狙う語が同じなら通す", AR.kw_change_ng("title", "a b", "a b", ""), "")
    check("付け替えで決めた語へ変えたら通す", AR.kw_change_ng("retarget", "a b", "c d", "c d"), "")
    check("付け替えでも決めた語と違う語は止める", bool(AR.kw_change_ng("retarget", "a b", "e f", "c d")), True)
    check("付け替えなのに語を変えなかったら止める", bool(AR.kw_change_ng("retarget", "a b", "a b", "c d")), True)
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("検算（check）がこの判定を使う", "ng_kw = kw_change_ng(" in src, True)
    check("付け替えは食い合いの判定を直す前の題で甘くしない", "if kw != kw0 and r.returncode >= 2" in src, True)


def test_retarget_rollback_after_28_days():
    import rewrite_rollback as RR
    import effect_ab as EA
    print("\n■ 付け替えの28日後: 表示が出なければ直す前の原稿へ戻す（直す前の表示は0なので倍率では測れない）")
    at = date(2026, 9, 1)
    today = date(2026, 11, 15)
    day = lambda n: (at + timedelta(days=n)).isoformat()
    check("観測が28日に足りなければ判定しない", RR.retarget_verdict({}, "a", date(2026, 11, 1), today), None)
    check("28日に表示が出た付け替えは残す",
          RR.retarget_verdict({"a": {day(3): [EA.MIN_IMP, 0, 50.0 * EA.MIN_IMP]}}, "a", at, today), (EA.MIN_IMP, False))
    check("28日の表示が足りなければ戻す",
          RR.retarget_verdict({"a": {day(3): [1, 0, 50.0], day(40): [99, 0, 99.0]}}, "a", at, today), (1, True))


def test_weekly_wiring():
    print("\n■ 週次の配線: 台帳を作ってから順位を記録し、表示ゼロの整理は6本まで")
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    i_led, i_track = wk.find("key_queries.py --ledger --write"), wk.find("key_queries.py --track")
    check("台帳を作る工程がある", i_led > 0, True)
    check("台帳を作ってから順位を記録する（広げた語にも順位が付く）", 0 < i_led < i_track, True)
    check("台帳はラッコの控え（検索の量）を戻してから作る", 0 < wk.find("name: ラッコの控えを戻す") < i_led, True)
    check("表示ゼロの記事は付け替えと統合を合わせて週6本", "retire_stale.py --retarget --write --limit 6" in wk, True)
    check("前の2本だけの統合は残さない", "retire_stale.py --write --limit 2" in wk, False)
