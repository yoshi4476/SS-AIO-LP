"""h148: 材料待ちで止めた記事でも、薄い当社調べ（1つの AI の数件）は測り直し、答えが増えたら直しを再開する（2026-11-02）"""
import json
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT


def test_thin_survey_is_remeasured_and_releases_the_wait():
    sys.path.insert(0, str(ROOT / "scripts"))
    import own_survey as O
    import quality_loop as Q
    print("\n■ 薄い当社調べは次の日に測り直し、答えが増えたら材料待ちを解く（2026-11-01 は Gemini の5件だけで一次性79点）")
    check("薄いか（前の日の5件は薄い・今日の5件と前の日の10件は測り直さない）",
          (O.thin({"answers": 5, "date": "2026-11-01"}, "2026-11-02"),
           O.thin({"answers": 5, "date": "2026-11-02"}, "2026-11-02"),
           O.thin({"answers": O.FULL, "date": "2026-11-01"}, "2026-11-02")), (True, False, False))
    src = (ROOT / "scripts" / "own_survey.py").read_text(encoding="utf-8")
    check("同じ月の測り直しで答えが増えなかったら前の結果を残す",
          'old.get("date", "")[:7] == today[:7] and res.get("answers", 0) <= old.get("answers", 0)' in src, True)

    import material as M
    fp, load = M.fingerprint, O.load
    M.fingerprint = lambda site: "aaa"
    got = {}
    try:
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "q.jsonl"
            hold = {"slug": "zz-a", "action": "hold", "need": "materials", "materials": "aaa", "at": "2026-11-01 19:31"}
            for name, row, res in (
                    ("同じ件数", {**hold, "survey": 5}, {"answers": 5, "date": "2026-11-02"}),
                    ("増えた", {**hold, "survey": 5}, {"answers": 10, "date": "2026-11-02"}),
                    ("件数の無い行・同じ日", hold, {"answers": 5, "date": "2026-11-01"}),
                    ("件数の無い行・後の日", hold, {"answers": 10, "date": "2026-11-02"})):
                log.write_text(json.dumps(row) + "\n", encoding="utf-8")
                O.load = lambda site, slug, res=res: res
                got[name] = Q.waiting_materials("zz-a", "client-zz", path=log)
    finally:
        M.fingerprint, O.load = fp, load
    check("待つか（答えが増えた・止めた日より後に測り直したら直す）", got,
          {"同じ件数": True, "増えた": False, "件数の無い行・同じ日": True, "件数の無い行・後の日": False})
    q = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("待つ前に当社調べを測り直し、止めた行に件数を残す",
          ("waiting_materials(slug, site) and (survey(slug, budget, base) or waiting_materials(slug, site))" in q,
           '"survey": survey_of(slug, site)[0]' in q), (True, True))
