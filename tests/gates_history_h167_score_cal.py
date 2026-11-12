# -*- coding: utf-8 -*-
"""2026-11-13 採点が公開後の成果を当てているかを月1回照合する（score_calibrate）。自社のデータでは「品質の点数は順位と逆」
という結果が過去に出ていたのに、点数と成果を突き合わせる定期の仕組みが無かった。1つの測り方を事実にしない（0.1節）ため、
順位相関（方法A）と上位・下位の中央値（方法B）が一致したときだけ「当てている／当てていない」と書き、母数が少ない・
2つが食い違う・点数の幅が狭いときは「判断できない」とする。重みと基準（rubric.py）は変えず、明細は非公開の置き場へ置く。
ネットワークには出ない（作り物のデータだけ）"""
import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _rows(scores, clk, pos, imp=100):
    return [{"slug": f"zz-art{i}", "kind": "v3", "scores": {"originality": float(s), "total": float(s)},
             "imp": imp, "clk": c, "pos": p, "touched": False, "ai": None, "url": f"https://zz.example/zz-art{i}"}
            for i, (s, c, p) in enumerate(zip(scores, clk, pos))]


def _wide(n=40):
    return [60 + i for i in range(n)]


def test_score_cal_needs_two_methods_to_agree():
    import score_calibrate as C
    print("\n■ 採点と成果の照合: 2つの方法が一致したときだけ結論を出す")
    s = _wide()
    rev = _rows(s, [40 - i for i in range(40)], [5 + i * 0.5 for i in range(40)])
    res = {m: C.judge(rev, "originality", m) for m in C.METRICS}
    check("(a) 点数が高いほどクリックが少ない例は「当てていない」（両方の方法が逆向き）",
          (res["clk"]["a"], res["clk"]["b"], res["clk"]["verdict"]), ("-", "-", C.MISS))
    check("(a) 順位も逆向きなら観点の結論は「当てていない」", C.combine(res), C.MISS)

    ok = _rows(s, list(range(40)), [25 - i * 0.5 for i in range(40)])
    res = {m: C.judge(ok, "originality", m) for m in C.METRICS}
    check("(b) 点数とクリック・順位がそろう例は「当てている」",
          (res["clk"]["verdict"], res["pos"]["verdict"], C.combine(res)), (C.HIT, C.HIT, C.HIT))

    few = _rows(s[:10], list(range(10)), [25 - i for i in range(10)])
    j = C.judge(few, "originality", "clk")
    check("(c) 母数が30本に届かなければ「判断できない」", (j["verdict"], "母数10本" in j["reason"]), (C.UNKNOWN, True))

    clk = [5 if i >= 34 or 20 <= i <= 24 else 0 for i in range(40)]
    mix = _rows(s, clk, [10.0] * 40)
    j = C.judge(mix, "originality", "clk")
    check("(d) 順位相関は良い向きでも、上位と下位の中央値が同じなら「判断できない」（食い違い）",
          (j["a"], j["b"], j["verdict"], "食い違う" in j["reason"]), ("+", "0", C.UNKNOWN, True))
    res = {"clk": {"verdict": C.HIT}, "pos": {"verdict": C.MISS}}
    check("(d) クリックでは当てている・順位では当てていない、のように成果で割れたら「判断できない」",
          C.combine(res), C.UNKNOWN)


def test_score_cal_does_not_read_noise_as_no_relation():
    import score_calibrate as C
    print("\n■ 採点と成果の照合: 点数の幅が狭い・クリックが少ない・点が重なるときの扱い")
    narrow = [93, 94, 95] * 14
    clk = [(i * 7) % 5 for i in range(42)]
    j = C.judge(_rows(narrow, clk, [10.0] * 42), "originality", "clk")
    check("点数がほぼ同じ幅（93〜95点）での無相関は「判断できない」（見かけの無相関の注記）",
          (j["verdict"], "幅が狭い" in j["reason"]), (C.UNKNOWN, True))

    sparse = _rows(_wide(), [1 if i in (3, 39) else 0 for i in range(40)], [10.0] * 40)
    j = C.judge(sparse, "originality", "clk")
    check("クリックのあった記事が10本未満なら「判断できない」（0ばかりを無相関と読まない）",
          (j["verdict"], "クリックのあった記事が2本" in j["reason"]), (C.UNKNOWN, True))

    tied = [90] * 12 + [95] * 20 + [99] * 12
    j = C.judge(_rows(tied, [0] * 12 + [3] * 20 + [9] * 12, [10.0] * 44), "originality", "clk")
    check("半数が同じ点でも、重なった点より上と下で2群に分けて比べる",
          (j["b"], j["med_hi"], j["med_lo"]), ("+", 9, 0))


def test_score_cal_reports_counts_and_keeps_details_private():
    import rubric
    import score_calibrate as C
    import sites as S
    print("\n■ 採点と成果の照合: ログは件数と結論だけ・明細は非公開の置き場・基準は変えない")
    s = _wide()
    rows = _rows(s, [40 - i for i in range(40)], [5 + i * 0.5 for i in range(40)])
    got = {"rows": rows, "start": "2026-10-01", "end": "2026-10-28", "skip": {"公開から日が浅い": 3},
           "brand_day": "2026-10-31", "ai_note": "取らない（--no-ga4）"}
    before = (ROOT / "scripts" / "rubric.py").read_bytes()
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "clients").mkdir()
        with mock.patch.dict(os.environ, {"SS_PRIVATE_DIR": td}), \
                mock.patch.object(S, "own_ids", lambda: ["zz-lab"]), \
                mock.patch.object(C, "collect", lambda site, age, ga4=True: got):
            with redirect_stdout(io.StringIO()) as o:
                rc = C.main(["--no-ga4"])
        out = o.getvalue()
        md = list((Path(td) / "reports" / "score_cal").glob("*.md"))
        js = list((Path(td) / "reports" / "score_cal").glob("*.json"))
        detail = js[0].read_text(encoding="utf-8") if js else ""
    check("当てていない観点があれば 0 で終わり SCORE_CAL_OK=no と要対応を出す",
          (rc, out.strip().splitlines()[-1], "要対応: 採点の観点" in out), (0, "SCORE_CAL_OK=no", True))
    check("ログに記事の slug・URL を出さない（件数と結論だけ）", ("zz-art" in out, "zz.example" in out), (False, False))
    check("明細（記事ごと）は非公開の置き場の reports/score_cal に書く", (len(md), len(js), "zz-art0" in detail), (1, 1, True))
    check("重みと基準（rubric.py）は変えない（提案だけ）", (ROOT / "scripts" / "rubric.py").read_bytes() == before, True)
    check("基準の数字は rubric.py の1か所から読む（観点の並びが rubric.AXES と同じ）",
          C.AXIS_KEYS, [a["key"] for a in rubric.AXES])

    with mock.patch.object(S, "own_ids", lambda: ["zz-lab"]), mock.patch.object(C, "collect", lambda *a, **k: None):
        with redirect_stdout(io.StringIO()) as o:
            rc = C.main(["--no-ga4"])
    check("順位の控えが1つも無く照合できなかったときだけ 1 で終わる（8.7）", (rc, "SCORE_CAL_OK" in o.getvalue()), (1, False))


def test_score_cal_runs_in_the_monthly_job():
    print("\n■ 採点と成果の照合: 既存の月次のジョブの月初に1ステップ（新しい workflow は増やさない）")
    wf = ROOT / ".github" / "workflows"
    steps = yaml.safe_load((wf / "monthly-report.yml").read_text(encoding="utf-8"))["jobs"]["report"]["steps"]
    names = [x.get("name", "") for x in steps]
    at = next((i for i, x in enumerate(steps) if "score_calibrate.py" in (x.get("run") or "")), -1)
    st = steps[at] if at >= 0 else {}
    check("月次のジョブに照合の手順がある", at >= 0, True)
    check("月初だけ動く（15日の途中経過の回と各社の作り直しでは動かない）",
          all(k in str(st.get("if")) for k in ("mid == 'false'", "!inputs.resend_sites")), True)
    check("鍵を外す前（GA4 を読む）・非公開の置き場へ残す前に動く",
          at < names.index("改善の実行の前に作業場から鍵を外す") and at < names.index("レポートと目標値を非公開のリポジトリへ残す"), True)
    check("要対応の行だけを通知（findings.txt）へ渡し、止めない", ("'^要対応'" in st.get("run", ""), "|| true" in st.get("run", "")),
          (True, True))
    check("照合のために workflow を増やしていない", [p.name for p in wf.glob("*.yml") if "score" in p.name], [])
    doc = (ROOT / "docs" / "pipeline" / "08-weekly.md").read_text(encoding="utf-8")
    check("文書（8章）に照合の決まりがある", ("score_calibrate.py" in doc, "SCORE_CAL_OK" in doc), (True, True))
