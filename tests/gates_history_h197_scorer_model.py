# -*- coding: utf-8 -*-
"""採点は本番と同じモデルでしか行わない（2026-11-18 運用者「手元と本番で採点が7〜15点違う原因も調べて」）。

claude の版が古いと auto_rewrite.model_args は1つ下のモデルに黙って落ちる。同じ本文を3回ずつ採点すると、
本番の版（2.1.302・claude-sonnet-5-5）は 84・88・84点（本番の記録も84）、手元の版（2.1.218・claude-sonnet-5）は
91・89・93点。別の記事は 75・75・76点に対し 93・92・92点。合否の物差しが変わるので、採点せずに止めて知らせる。
本物の claude は呼ばない。
"""
import subprocess
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_scorer_refuses_a_fallback_model():
    import auto_rewrite as A
    import quality_loop as QL
    print("\n■ 採点のモデルが本番と違う（版が古く1つ下のモデルに落ちた）なら、採点せずに止める")
    calls = []
    old = (A.model_args, A.sh)
    try:
        A.sh = lambda *a, **k: calls.append(a) or subprocess.CompletedProcess([], 0, "応答", "")
        A.model_args = lambda: ["--model", A.MODELS[1][0]]
        try:
            QL._ask("採点して", ".")
            why = ""
        except QL.ScorerModelMismatch as e:
            why = str(e)
        check("落ちたモデルでは claude を呼ばずに止め、上げる版を書く",
              (calls, A.MODELS[0][0] in why, "2.1.280" in why), ([], True, True))
        A.model_args = lambda: []
        try:
            QL._ask("採点して", ".")
            stopped = False
        except QL.ScorerModelMismatch:
            stopped = True
        check("モデルを指定できない版（とても古い・claude が無い）でも止める", (stopped, calls), (True, []))
        A.model_args = lambda: ["--model", A.MODELS[0][0]]
        check("本番と同じモデルなら採点する", (QL._ask("採点して", "."), len(calls)), ("応答", 1))
    finally:
        A.model_args, A.sh = old


def test_every_workflow_installs_a_version_that_scores_with_the_main_model():
    import re
    import auto_rewrite as A
    print("\n■ 本番の手順が入れる claude の版は、どれも採点のモデル（MODELS の先頭）を使える")
    need = A.MODELS[0][1]
    bad, seen = [], 0
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for v in re.findall(r"@anthropic-ai/claude-code@(\d+)\.(\d+)\.(\d+)", wf.read_text(encoding="utf-8")):
            seen += 1
            if tuple(map(int, v)) < need:
                bad.append(f"{wf.name}: {'.'.join(v)}")
    check("版を決めて入れている手順がある", seen >= 5, True)
    check("どの手順の版も採点のモデルを使える", bad, [])
