# -*- coding: utf-8 -*-
"""2026-10-11 守秘義務の続き。CI のログ（public・保存14日）に、10/09〜10/10 の16回にわたりお客様の社の記事の名前・題・
ドメインが出ていた。門（gates_history_h77）はコードを読むだけで、実際のログは見ていなかった。

決めたこと: 週次の findings が log_leak_check.py で直近8日の実際のログを取り、守秘の語の出現を数える。
出たら「要対応」（期限あり）。語そのもの・該当行は出さず、回・公開の id・件数・種類だけ。
非公開のデータが無い・API に失敗した・対象の回が0回は unknown（「問題なし」にしない）。
架空の社（client-zz）で確かめる
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

JST = timezone(timedelta(hours=9))
WORDS = ("zz-secret-title", "zz.example")
IDENT = {"client-zz": (["zz.example"], ["zz-secret-title"], "zz.example")}
BAD = "Run publish\n[1] ○ zz-secret-title\nhttps://zz.example/blog/zz-secret-title/ に配信\nZZ-SECRET-TITLE\n"
GOOD = ("zz-secret-titles を書いた\nxzz.example へ\nzz-secret-title-2\nhttps://other.example/zz-secret-titlex/\n"
        "LOG_LEAK_OK=yes\n")


def _zip(text):
    """ジョブの全文（1_job.txt）と、同じ中身を工程ごとに分けたもの（job/1_step.txt）"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("1_job.txt", text)
        z.writestr("job/1_step.txt", text)
    return buf.getvalue()


def _run(i, when, conclusion="success"):
    return {"id": i, "created_at": when, "conclusion": conclusion, "path": ".github/workflows/pipeline-multi.yml"}


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a, **k)
    return rc, buf.getvalue()


def test_log_leak_detector_both_ways():
    print("\n■ 守秘義務: CI のログの見張りは、守秘の語を拾い、似ているが別の語は拾わない（2026-10-11）")
    import log_leak_check as L
    pats = L.patterns(IDENT)
    check("悪い例: slug・題・ドメイン（URL の中も・大文字も）を数える",
          L.scan(BAD, pats), {"client-zz": (4, {L.DOMAIN, L.OTHER})})
    check("良い例: 別の slug・別のドメインの一部・語を含まないログは拾わない", L.scan(GOOD, pats), {})
    check("zip は全文だけを読む（工程ごとの写しと二重に数えない）",
          (L.scan_zip(_zip(BAD), pats), L.scan_zip(_zip(GOOD), pats)), ({"client-zz": (4, {L.DOMAIN, L.OTHER})}, {}))
    check("4文字未満の語は照らさない（一般の語と重なる）", L.patterns({"client-zz": (["zz"], ["abc"], "")}), {})


def test_log_leak_output_never_shows_the_words():
    print("\n■ 守秘義務: 見張りの出力（これも CI のログ）は回・公開の id・件数・種類だけで、語そのものを出さない")
    import log_leak_check as L
    import sites as S
    runs = [_run(1001, "2026-10-12T01:00:00Z"), _run(1002, "2026-10-12T00:30:00Z"),
            _run(1003, "2026-10-12T00:10:00Z", "skipped"),
            # 2026-10-11 0時（日本時間）より前の回は、ログに語があっても数えない（直す前の回は把握済み）
            _run(999, "2026-10-10T14:00:00Z")]
    logs = {1001: _zip(BAD), 1002: _zip(GOOD), 1003: _zip(BAD), 999: _zip(BAD)}
    now = datetime(2026, 10, 12, 12, tzinfo=JST)
    got = {}
    with mock.patch.object(L, "list_runs", return_value=runs), mock.patch.object(L, "remaining", return_value=None), \
            mock.patch.object(L, "fetch_log", side_effect=lambda repo, tok, rid: got.setdefault(rid, logs[rid])), \
            mock.patch.object(S, "public_id", side_effect=lambda s: "c0a1b2c3d" if s == "client-zz" else s):
        rc, out = _quiet(L.check, days=8, now=now, ident=IDENT, token="t")
        rc2, out2 = _quiet(L.check, days=8, now=now, ident={"client-zz": (["zz-other.example"], [], "")}, token="t")
    check("当たった回だけ要対応で、印は no・終了コードは0",
          (rc, out.strip().splitlines()[-1], "run 1001 c0a1b2c3d: 4件（domain, name・title・slug）" in out, "1002" in out),
          (0, "LOG_LEAK_OK=no", True, False))
    check("skipped の回と 2026-10-11 より前の回はログを取らない", sorted(got), [1001, 1002])
    check("出力に守秘の語が1つも出ない", [w for w in WORDS if w in out.lower()], [])
    check("当たりが無ければ yes", (rc2, out2.strip().splitlines()[-1]), (0, "LOG_LEAK_OK=yes"))


def test_log_leak_unknown_is_not_ok():
    print("\n■ 守秘義務: 非公開のデータが無い・API に失敗した・対象の回が0回は unknown（「問題なし」にしない）")
    import log_leak_check as L
    with tempfile.TemporaryDirectory() as td:
        env = dict(os.environ, SS_PRIVATE_DIR=os.path.join(td, "none"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        for k in L.TOKEN_ENVS:
            env.pop(k, None)
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "log_leak_check.py"), "--days", "1"], env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    check("非公開のデータが無い: LOG_LEAK_OK=unknown・終了コード1", (r.returncode, r.stdout.strip().splitlines()[-1]),
          (1, "LOG_LEAK_OK=unknown"))
    now = datetime(2026, 10, 12, 12, tzinfo=JST)
    with mock.patch.object(L, "list_runs", side_effect=OSError("down")):
        rc, out = _quiet(L.check, now=now, ident=IDENT, token="t")
    check("回の一覧が読めない: unknown・終了コード1", (rc, out.strip().splitlines()[-1]), (1, "LOG_LEAK_OK=unknown"))
    with mock.patch.object(L, "list_runs", return_value=[]):
        rc, out = _quiet(L.check, now=now, ident=IDENT, token="t")
    check("対象の回が0回: unknown", out.strip().splitlines()[-1], "LOG_LEAK_OK=unknown")
    runs = [_run(2000 + i, "2026-10-12T01:00:00Z") for i in range(20)]
    with mock.patch.object(L, "list_runs", return_value=runs), mock.patch.object(L, "remaining", return_value=None), \
            mock.patch.object(L, "fetch_log", side_effect=OSError("down")), mock.patch.object(L.time, "sleep"):
        rc, out = _quiet(L.check, now=now, ident=IDENT, token="t")
    check("ログがほとんど取れない: unknown・終了コード1", (rc, out.strip().splitlines()[-1]), (1, "LOG_LEAK_OK=unknown"))
    fetched = []
    with mock.patch.object(L, "list_runs", return_value=runs), \
            mock.patch.object(L, "remaining", return_value=L.RESERVE + 5), \
            mock.patch.object(L, "fetch_log", side_effect=lambda repo, tok, rid: fetched.append(rid) or _zip(GOOD)):
        rc, out = _quiet(L.check, now=now, ident=IDENT, token="t")
    check("API の残りが足りない: ほかの工程の分を残して新しい回だけ取り、調べなかった回が多ければ unknown",
          (len(fetched), out.strip().splitlines()[-1]), (5, "LOG_LEAK_OK=unknown"))


def test_weekly_findings_runs_the_log_leak_check():
    print("\n■ 守秘義務: 週次の findings が見張りを回し、出たら要対応。そのジョブは actions: read と鍵を持つ")
    import findings as F
    import yaml
    # ログの見張りは1つ（公開側のファイルの照らし --tracked は別の検査。2026-10-11）
    item = [c for c in F.CHECKS if c[1].split()[0] == "log_leak_check.py" and "--tracked" not in c[1]]
    check("findings の検査に入っている", len(item), 1)
    tracked = [c for c in F.CHECKS if c[1] == "log_leak_check.py --tracked"]
    check("公開側のファイルの照らしも週次に入り、出たら要対応", (len(tracked), bool(tracked) and
          bool(F.details("要対応: 公開リポジトリの…\n  data/x.jsonl: 記事の題・slug\nTRACKED_LEAK_OK=no", tracked[0][2]))),
          (1, True))
    label, script, pat = item[0]
    check("出たら要対応・動かなければ動かせず（期限ありで毎週要対応のまま）",
          (F.judge("LOG_LEAK_OK=no", 0), F.judge("LOG_LEAK_OK=unknown", 1), F.judge("LOG_LEAK_OK=yes", 0),
           label in F.DEADLINE),
          ("要対応", "動かせず", "問題なし", True))
    sample = "要対応: CI のログに…\n  - 2026-10-12 記事の枠 run 1001 c0a1b2c3d: 4件（domain）\nLOG_LEAK_OK=no"
    check("明細は要対応の行と回の行を拾う", len(F.details(sample, pat)), 2)
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8"))
    jobs = [(n, j) for n, j in (wf.get("jobs") or {}).items()
            if any("scripts/findings.py" in str(s.get("run", "")) for s in j.get("steps") or [])]
    check("findings を動かすジョブがある", len(jobs), 1)
    name, job = jobs[0]
    perms = job.get("permissions") if "permissions" in job else wf.get("permissions")
    check("そのジョブは actions: read を持つ（ジョブに無ければワークフロー全体の権限）",
          (perms or {}).get("actions") in ("read", "write"), True)
    step = [s for s in job["steps"] if "scripts/findings.py" in str(s.get("run", ""))][0]
    check("findings の工程に、見張りだけが使う鍵（LOG_LEAK_GH_TOKEN）を渡す",
          (step.get("env") or {}).get("LOG_LEAK_GH_TOKEN"), "${{ github.token }}")
