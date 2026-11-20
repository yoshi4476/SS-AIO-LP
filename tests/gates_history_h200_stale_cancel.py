# -*- coding: utf-8 -*-
"""2026-11-20 自動修復: 作られてから26時間を過ぎて取り消された回（古い待ち）は修復しない。

11/11 に作られて工程が1つも始まらないまま9日待った記事の回が取り消され、heal が直すもの無しで動き
「修復の案に直した中身がありません（生成物だけ）」と知らせた（run 44681623442）。その日の記事は後の回と救済が書いている。
取り消しを拾うこと自体（後の回に取り消されてその日の記事が消えた回を見つける）は残す。
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from test_gates import check, ROOT

WF = ROOT / ".github" / "workflows" / "selfheal.yml"


def _bash():
    # Windows の「bash」は WSL を指すことがあるので、Git の bash を先に使う（CI の Linux では bash）
    cands = [r"C:\Program Files\Git\bin\bash.exe", "bash"] if sys.platform == "win32" else ["bash"]
    for b in cands:
        try:
            if subprocess.run([b, "-c", "date -u -d 2026-01-01T00:00:00Z +%s"], capture_output=True).returncode == 0:
                return b
        except OSError:
            pass
    return None


def test_selfheal_skips_stale_cancel():
    print("\n■ 自動修復: 古い取り消しは修復しない")
    jobs = yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]
    sc = jobs.get("stale-cancel", {})
    heal = jobs["heal"]
    check("取り消しの年齢を見るジョブがある", bool(sc), True)
    check("heal はそのジョブを待つ", heal.get("needs"), "stale-cancel")
    hif = " ".join(heal["if"].split())
    check("飛ばされても heal が動く（!cancelled()）",
          hif.startswith("!cancelled() && needs.stale-cancel.outputs.skip != 'true' && ("), True)
    check("取り消しを拾う条件は残す", "github.event.workflow_run.conclusion == 'cancelled'" in hif, True)
    # heal の後ろのジョブも、状態の関数が無いと既定の success() が祖先の stale-cancel（定期・手動では飛ばされる）まで見て動かない
    later = {k: " ".join(str(j.get("if") or "").split()) for k, j in jobs.items()
             if k not in ("heal", "stale-cancel") and "heal" in (j.get("needs") if isinstance(j.get("needs"), list) else [j.get("needs")])}
    check("heal の後ろのジョブは状態の関数（!cancelled()・always()）を持つ",
          [k for k, c in later.items() if not re.search(r"!cancelled\(\)|always\(\)", c)], [])
    check("repair は heal が成功したときだけ", "needs.heal.result == 'success'" in later.get("repair", ""), True)
    step = sc["steps"][0]
    run = step["run"]
    check("26時間（93600秒）を境にする", "93600" in run, True)
    check("作られた時刻は env で渡す（run に埋めない）", "${{" not in run and "workflow_run.created_at" in step["env"]["CREATED"], True)

    # 起動の条件は heal の workflow_run の部分と同じ（違うと、heal が拾う回で年齢を見ずに修復する／拾わない回で無駄に動く）
    def wr_part(s):
        end = "!= 'Deploy to Cloudflare Pages'"
        return s[s.index("contains(fromJSON("):s.rindex(end) + len(end)] if "contains(fromJSON(" in s and end in s else None
    sif = " ".join(sc["if"].split())
    check("起動の条件は heal の workflow_run の条件と同じ", (wr_part(sif) is not None, wr_part(sif) == wr_part(hif)), (True, True))
    check("古いと判断するのは取り消しの回だけ（失敗の回は修復する）", '[ "$CONCLUSION" = cancelled ]' in run
          and "workflow_run.conclusion" in step["env"]["CONCLUSION"], True)

    # 年齢の判定を、実際の bash と date で確かめる（9日前は飛ばす・1時間前は修復する）
    bash = _bash()
    if not bash:
        print("  （bash の GNU date が無いため、年齢の判定の実行は省きました）")
        return
    old = "2026-11-11T20:26:58Z"
    for created, concl, want in ((old, "cancelled", "skip=true"), (None, "cancelled", "skip=false"), (old, "failure", "skip=false")):
        c = created or subprocess.run([bash, "-c", "date -u -d '-1 hour' +%Y-%m-%dT%H:%M:%SZ"],
                                      capture_output=True, text=True).stdout.strip()
        # GITHUB_OUTPUT は一時ファイルにする（Windows の Git bash には /dev/stdout が無い）
        with tempfile.TemporaryDirectory() as tmp:
            o = Path(tmp) / "out.txt"
            o.write_text("", encoding="utf-8")
            subprocess.run([bash, "-c", run], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "CREATED": c, "WR_NAME": "x", "CONCLUSION": concl, "GITHUB_OUTPUT": o.as_posix()})
            out = o.read_text(encoding="utf-8")
        check(f"{concl}・作られたのが{'9日前' if created else '1時間前'} → {want}", want in out, True)
