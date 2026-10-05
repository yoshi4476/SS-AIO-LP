# -*- coding: utf-8 -*-
"""公開からの経過を食い合いと読み違えない門（2026-10-05）。

AI集客ラボの既存記事の表示が前の28日比 -49% に見えたが、原因は公開からの経過だった
（どの記事も公開1〜3週で山になり、4〜6週で山の約1/4に落ちる。食い合いで新記事に移った表示は
減り1,413回のうち65回）。期間の単純比較で「既存記事が落ちた」を出し、週次の統合を4組に増やしていた。
固定すること: content_yield は公開からの週数をそろえたコホートで比べる／母数が足りなければ判定しない。
Search Console には触れない（手元で作った日別の表示だけ）。
"""
from datetime import date, timedelta

from test_gates import check, ROOT


def _curve(age):
    """公開からの日数ごとの表示（1〜3週で山・4〜6週で山の1/4）"""
    w = age // 7
    return 0 if age < 0 else (40 if w <= 2 else 10 if w <= 5 else 8)


def _site(arts, end, scale=1.0):
    day = {}
    for a in arts:
        d0 = date.fromisoformat(a["date"])
        for i in range(0, (end - d0).days + 1):
            day.setdefault(f"/{a['slug']}/", {})[(d0 + timedelta(days=i)).isoformat()] = \
                int(_curve(i) * (scale if a.get("late") else 1.0))
    return day


def test_content_yield_compares_same_age_cohorts():
    import content_yield as CY
    print("\n■ content_yield: 公開からの週数をそろえて比べる")
    end = date(2026, 10, 2)
    cw, pw = CY.windows(end)
    check("今のコホートは end の日に公開8週目を終えた記事まで・前のコホートはその28日前",
          (cw[1], pw[1], (cw[1] - cw[0]).days + 1), (end - timedelta(days=55), end - timedelta(days=83), 28))
    # 同じ経過の曲線なら、記事を急に増やしても判定は「落ちていない」
    arts = [{"slug": f"a{i}", "date": (pw[0] + timedelta(days=i * 2)).isoformat()} for i in range(28)]
    paths = {a["slug"]: f"/{a['slug']}/" for a in arts}
    day = _site(arts, end)
    c = {"cur": [*map(str, cw), *CY.cohort(arts, paths, day, *cw)],
         "prev": [*map(str, pw), *CY.cohort(arts, paths, day, *pw)]}
    check("経過の曲線が同じなら落ちたと読まない", CY.cohort_judge(c)[0], False)
    # 同じ年齢で今のコホートが半分しか取れていなければ要対応
    for a in arts:
        a["late"] = a["date"] >= cw[0].isoformat()
    day = _site(arts, end, 0.5)
    c = {"cur": [*map(str, cw), *CY.cohort(arts, paths, day, *cw)],
         "prev": [*map(str, pw), *CY.cohort(arts, paths, day, *pw)]}
    check("同じ年齢で1本あたりが半分なら要対応", CY.cohort_judge(c)[0], True)
    r = {"name": "試験", "mature": 0, "zero": 0, "cohort": c}
    check("要対応の文に公開5〜8週目と書く", "公開5〜8週目" in "".join(CY.judge(r)), True)
    small = {"cur": ["", "", 9, 500, 10.0], "prev": ["", "", 30, 3000, 20.0]}
    check("コホートが10本に満たなければ判定しない（unknown）", CY.cohort_judge(small)[0], None)
    check("コホートを測れなければ判定しない", CY.cohort_judge(None)[0], None)
    # 期間の単純比較（前からある記事 -45%）だけでは要対応にしない
    r = {"name": "試験", "mature": 0, "zero": 0, "n_prev": 91, "n_now": 139, "imp_prev": 2500, "imp_now": 2563,
         "old_prev": 2500, "old_now": 1379, "cohort": None}
    check("期間の単純比較だけでは統合を増やさない", CY.judge(r), [])
    check("どれも判定できなければ YIELD_OK=unknown の材料になる", CY.judged(r), False)
    src = (ROOT / "scripts" / "content_yield.py").read_text(encoding="utf-8")
    check("YIELD_OK に unknown がある", "'unknown'" in src, True)


def test_manual_title_changes_join_rollback():
    import json
    import tempfile
    from pathlib import Path
    import rewrite_rollback as R
    print("\n■ rewrite_rollback: 手で変えた題も28日・対照群の判定に乗せる")
    got = {d["slug"]: d for d in R.entries() if d.get("by") == "manual"}
    check("8/25 に手で変えた2本が判定の対象に入る", sorted(got), ["aio-shindan-yarikata", "btob-llmo-taisaku"])
    check("before_title は git の履歴（f1c6d5136 の前）の題",
          (got["btob-llmo-taisaku"]["before_title"], got["aio-shindan-yarikata"]["before_title"]),
          ("BtoB AI検索対策（LLMO）とは？発注候補に残る条件", "AIO診断とは？AI検索対応度がわかる8つの視点"))
    check("変更日は 2026-08-25", {d["at"][:10] for d in got.values()}, {"2026-08-25"})
    with tempfile.TemporaryDirectory() as td:
        old = R.ROOT
        try:
            R.ROOT = Path(td)
            (Path(td) / "articles").mkdir()
            p = Path(td) / "articles" / "x.md"
            d = {"by": "manual", "kind": "title", "before_title": "前の題", "after_title": "後の題"}
            p.write_text("---\ntitle: 別の題\n---\n本文\n", encoding="utf-8")
            check("記録の後に題が変わっていれば戻さない", (R.restore("x", d), "別の題" in p.read_text(encoding="utf-8")),
                  (False, True))
            p.write_text("---\ntitle: 後の題\n---\n本文\n", encoding="utf-8")
            check("題が記録のままなら前の題へ戻せる", (R.restore("x", d), "title: 前の題" in p.read_text(encoding="utf-8")),
                  (True, True))
        finally:
            R.ROOT = old
    check("手で足した記録には印がある", all(json.dumps(x, ensure_ascii=False).count("手で") for x in got.values()), True)


def test_rescue_picks_articles_fallen_from_their_peak():
    import inspect
    import content_yield as CY
    import link_boost as LB
    import sites as S
    print("\n■ link_boost --rescue: 公開後の山から1/4以下に落ちた記事も拾う（題は変えない）")
    end = date(2026, 10, 2)
    pub = (end - timedelta(days=60)).isoformat()

    def series(weekly):
        d = {}
        for k, v in enumerate(weekly):        # k=0 が直近の週
            d[(end - timedelta(days=7 * k)).isoformat()] = v
        return d
    check("山40 → 直近8 は (40, 8)", LB.peak_drop(series([8, 10, 20, 40, 30]), pub, end), (40, 8))
    check("直近の週が山なら拾わない", LB.peak_drop(series([50, 10, 20]), pub, end), None)
    check("公開4週未満は拾わない", LB.peak_drop(series([1, 30]), (end - timedelta(days=20)).isoformat(), end), None)
    sid = "ai-lab" if "ai-lab" in S.load_all() else next(iter(S.load_all()))
    cfg = S.load(sid)
    cat = next(iter(cfg.get("categories") or {"aio": ""}))
    arts = {s: {"cat": cat, "date": pub} for s in ("fell", "steady", "small", "linked")}
    path = lambda s: CY._path(S.article_url(cfg, {"slug": s, "category": cat}))
    day = {path("fell"): series([5, 10, 40, 60, 30]), path("steady"): series([30, 35, 40, 60, 30]),
           path("small"): series([1, 2, 10, 12]), path("linked"): series([5, 10, 40, 60, 30])}
    cnt = {"fell": 3, "steady": 3, "small": 3, "linked": LB.RESCUE_FLOOR}
    got = LB.decay_targets(sid, arts, cnt, day=day, end=end)
    check("山の1/4以下に落ちた記事だけ（山が小さい・被リンクが下限以上は除く）", [t[0] for t in got], ["fell"])
    check("11〜30位の経路で拾った記事は二重に数えない", LB.decay_targets(sid, arts, cnt, skip={"fell"}, day=day, end=end), [])
    msrc = inspect.getsource(LB.main)
    check("--rescue から呼ばれ、内部リンクだけを足す（台帳の種類は link_decay）",
          ("decay_targets(" in msrc, '"link_decay"' in msrc), (True, True))
    check("1回に拾う本数に上限がある", LB.DECAY_MAX <= 5, True)


def test_glossary_is_seen_by_cannibal_checks():
    import cannibal_check as CC
    import kw_guard as KG
    print("\n■ 用語集（/glossary/）も食い合いの検査に入れる（知らせるだけ）")
    check("用語集のURLを見分ける（一覧の /glossary/ も・記事は違う）",
          (CC.is_glossary("https://a.example/glossary/abc/"), CC.is_glossary("https://a.example/glossary/"),
           CC.is_glossary("https://a.example/aio/glossary-x/")), (True, True, False))

    def row(q, page, pos, imp):
        return {"keys": [q, "https://a.example" + page], "position": pos, "impressions": imp}
    rows = [row("語A", "/glossary/g1/", 9.8, 4), row("語A", "/seo/art-a/", 12.2, 51),
            row("語B", "/glossary/g2/", 30.0, 5), row("語B", "/seo/art-b/", 8.0, 40),
            row("語C", "/glossary/g3/", 5.0, 3), row("語C", "/seo/", 7.0, 20),
            row("語D", "/glossary/g4/", 5.0, 1), row("語D", "/seo/art-d/", 7.0, 2)]
    got = CC.glossary_pairs(rows, {"art-a", "art-b", "art-d"})
    check("記事より上に出る用語集だけ（下にいる・相手が一覧・表示が誤差の組は除く）", [h["kw"] for h in got], ["語A"])
    check("用語集と記事の両方を残す", (got[0]["glossary"][1], got[0]["article"][0]), (9.8, "art-a"))
    src = (ROOT / "scripts" / "cannibal_check.py").read_text(encoding="utf-8")
    check("用語集は記事どうしの組から外し、印 GLOSSARY_OK を出す（noindex・正規URLは変えない）",
          ("if is_glossary(x[\"keys\"][1]):" in src, "GLOSSARY_OK=" in src, "noindex" in src), (True, True, True))
    fsrc = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("週次の要対応に載る", "cannibal_check.py --glossary" in fsrc, True)

    kw = "試験用語ぜっとぜっと"
    fake = [{"keys": [kw, "https://a.example/glossary/g9/"], "position": 6.0, "impressions": 30}]
    real_rows, real_src = KG.gsc_rows, KG.glossary_source

    def rows_fn(_sid):
        rows_fn.failed = ""
        return fake
    try:
        KG.gsc_rows = rows_fn
        KG.glossary_source = lambda page, sid: "src-article"
        lv, rs = KG.judge(kw, "ai-lab")
        check("kw_guard: 用語集が取っている語は要対応で知らせ、着手禁止（2）にはしない",
              (lv, [r[0] for r in rs]), (1, ["要対応"]))
        lv, rs = KG.judge(kw, "ai-lab", exclude_slug="src-article")
        check("kw_guard: 審査中の記事自身の定義から作った用語集は相手に数えない", (lv, rs), (0, []))
    finally:
        KG.gsc_rows, KG.glossary_source = real_rows, real_src


def test_pace_inspects_across_publish_dates():
    import pace as P
    print("\n■ 量産の兆候: URL検査は公開時期の端から端まで均等に選ぶ（名前順の先頭だけを見ない）")
    arts = [{"slug": f"a{i:02d}", "date": f"2026-09-{i + 1:02d}"} for i in range(30)]
    arts.reverse()
    got = P.spread(arts, 5)
    check("30本から5本: 最初と最後の公開日を含み、等間隔", [a["date"] for a in got],
          ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-23", "2026-09-30"])
    check("上限より少なければ全部", len(P.spread(arts[:3], 5)), 3)
    src = (ROOT / "scripts" / "pace.py").read_text(encoding="utf-8")
    check("measure は spread を通して検査する", "spread(new, INSPECT_MAX)" in src, True)
