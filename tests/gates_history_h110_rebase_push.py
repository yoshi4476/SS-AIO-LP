# -*- coding: utf-8 -*-
"""2026-10-19 取り込みでぶつかっても、ぶつからなかった直しを捨てずに送り出す（rebase_push.py）。

週次の工程の間に毎日の記事の枠が同じ記事を書き換え、送り出しが3回とも同じ所でぶつかって週次の直し（97ファイル）を失った。
ぶつかった記事は先に入った側を残してこちらの直しを見送り、行を足す記録（*.jsonl）は両方の行を残し、残りは送り出す。
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

SCRIPT = ROOT / "scripts" / "rebase_push.py"


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _cfg(cwd):
    _git(cwd, "config", "user.email", "t@example.com")
    _git(cwd, "config", "user.name", "t")
    _git(cwd, "config", "core.autocrlf", "false")


def test_conflicted_files_keep_upstream_and_logs_union():
    print("\n■ 取り込みでぶつかっても、ぶつからなかった直しは送り出す（記事は先に入った側・記録は両方の行）")
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        bare, a, b = d / "remote.git", d / "a", d / "b"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(bare)], check=True)
        subprocess.run(["git", "clone", "-q", str(bare), str(a)], check=True, capture_output=True)
        _cfg(a)
        (a / "articles").mkdir()
        (a / "articles" / "x.md").write_text("1行目\n2行目\n3行目\n", encoding="utf-8")
        (a / "log.jsonl").write_text('{"n":0}\n', encoding="utf-8")
        _git(a, "add", "-A"); _git(a, "commit", "-qm", "init"); _git(a, "push", "-q", "origin", "HEAD:master")
        subprocess.run(["git", "clone", "-q", str(bare), str(b)], check=True, capture_output=True)
        _cfg(b)
        # a（毎日の記事の枠）が先に同じ行と記録を書き換えて送り出す
        (a / "articles" / "x.md").write_text("1行目\n2行目（毎日の枠の直し）\n3行目\n", encoding="utf-8")
        (a / "log.jsonl").write_text('{"n":0}\n{"n":"a"}\n', encoding="utf-8")
        _git(a, "commit", "-qam", "daily"); _git(a, "push", "-q")
        # b（週次）は同じ行・記録に加えて、ぶつからないファイルも直す
        (b / "articles" / "x.md").write_text("1行目\n2行目（週次の直し）\n3行目\n", encoding="utf-8")
        (b / "log.jsonl").write_text('{"n":0}\n{"n":"b"}\n', encoding="utf-8")
        (b / "articles" / "y.md").write_text("週次だけが足した記事\n", encoding="utf-8")
        _git(b, "add", "-A"); _git(b, "commit", "-qm", "weekly")
        env = dict(os.environ, GITHUB_REF_NAME="master")
        r = subprocess.run([sys.executable, str(SCRIPT), "--branch", "master"], cwd=b, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=env)
        _git(a, "pull", "-q")
        x = (a / "articles" / "x.md").read_text(encoding="utf-8")
        log = (a / "log.jsonl").read_text(encoding="utf-8").splitlines()
        y = (a / "articles" / "y.md").exists()
        markers = any(m in x for m in ("<<<<<<<", ">>>>>>>"))
    check("送り出せた（REBASE_PUSH=ok）", "REBASE_PUSH=ok" in r.stdout, True)
    check("ぶつかった記事は先に入った側（毎日の枠）を残す・衝突の印が残らない", ("毎日の枠の直し" in x, markers), (True, False))
    check("行を足す記録は両方の行を残す", sorted(log), sorted(['{"n":0}', '{"n":"a"}', '{"n":"b"}']))
    check("ぶつからなかった直し（新しい記事）は送り出した", y, True)
    check("見送ったファイルを警告に出す", "x.md のこちらの直しを見送りました" in r.stdout, True)


def test_weekly_uses_rebase_push():
    print("\n■ 週次の最後の送り出しが rebase_push を使う")
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    i = wk.index("- name: 最終ビルドとコミット")
    check("最終ビルドとコミットが rebase_push.py で送り出す", "python scripts/rebase_push.py" in wk[i:i + 2500], True)
