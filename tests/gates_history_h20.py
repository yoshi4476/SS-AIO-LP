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
