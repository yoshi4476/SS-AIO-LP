# -*- coding: utf-8 -*-
"""門を同時に流す仕組み（GATES_JOBS）の門（2026-11-13）

送る前の門が手元の Windows で毎回10分以上かかっていたので、子プロセスで同時に流すようにした。
同時に流すと、管制塔のファイル（site/・data/・private/ など）を書く門どうし、書く門と読む門がぶつかって
判定が変わりうる。書く門は SERIAL に入れて、同時の組より先に親で1本ずつ流す。
ここでは、(1) SERIAL の名前が今の門と合っている（名前を変えた門が黙って同時の組に入らない）、
(2) 同時の組が管制塔のファイルを変えたら、実際に止まる（新しく足した書く門を SERIAL に入れ忘れた回を見つける）、
(3) 流した門の数え落ち・二重を見つける、(4) 子の出力も伏せてから出す、を確かめる。
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent
PROBE = "gates_history_zz_parallel_probe"


def _gates():
    return sys.modules["test_gates"]


def test_serial_names_are_real_gates():
    print("\n■ 同時に流す: SERIAL に書いた名前は、今ある門かモジュールの名前（古い名前を残さない）")
    import contextlib
    import io
    T = _gates()
    with contextlib.redirect_stdout(io.StringIO()):
        names = {T._name(t) for t in T.all_tests()}
    mods = {n.rsplit(".", 1)[0] for n in names}
    check("SERIAL の名前がすべて今の門・モジュールにある", sorted(s for s in T.SERIAL if s not in names and s not in mods), [])
    check("この門も SERIAL（tests/ と管制塔の下に、試しのファイルを作って消すため）", T._serial(f"{__name__}.test_shared_writes_in_parallel_stop_the_run"), True)


def test_snapshot_sees_writes():
    print("\n■ 同時に流す: 管制塔の写しは、作る・書き換える・消す・作って消すを見つけ、__pycache__ だけの変化は数えない")
    T = _gates()
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "site").mkdir()
        (root / "site" / "a.html").write_text("a", encoding="utf-8")
        (root / "data").mkdir()
        base = T._snapshot(root)
        check("何もしなければ違いは無い", T._changed(base, T._snapshot(root), root), [])
        (root / "src").mkdir()
        time.sleep(0.05)
        before = T._snapshot(root)
        (root / "src" / "__pycache__").mkdir()
        check("__pycache__ ができただけは数えない", T._changed(before, T._snapshot(root), root), [])
        time.sleep(0.05)
        before = T._snapshot(root)
        (root / "site" / "a.html").write_text("bb", encoding="utf-8")
        (root / "site" / "new.html").write_text("n", encoding="utf-8")
        tmp = root / "data" / "tmp.json"
        tmp.write_text("{}", encoding="utf-8")
        tmp.unlink()
        got = T._changed(before, T._snapshot(root), root)
        check("書き換え・新しいファイル・作って消した（フォルダの時刻）を見つける",
              ("site/a.html" in got, "site/new.html" in got, "data" in got), (True, True, True))


def test_count_finds_missing_and_twice():
    print("\n■ 同時に流す: 予定の門と流した門を1本ずつ突き合わせる・CI の既定は1本ずつ")
    from unittest import mock
    T = _gates()
    plan = [(0, "m.a"), (1, "m.b"), (2, "m.c")]
    check("全部1回ずつなら合う", T._mismatch(plan, [2, 0, 1]), ([], []))
    check("流れなかった門と二重の門を名前で出す", T._mismatch(plan, [0, 0, 1]), (["m.c"], ["m.a"]))
    with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
        os.environ.pop("GATES_JOBS", None)
        ci = T._jobs()
    with mock.patch.dict(os.environ, {"GATES_JOBS": "3"}):
        named = T._jobs()
    check("CI は GATES_JOBS が無ければ1本ずつ・GATES_JOBS を書けばその数", (ci, named), (1, 3))


def test_worker_output_is_hidden():
    print("\n■ 同時に流す: 子プロセスの出力と門の名前も、社の id・名前を公開の id に置き換えてから出す")
    import contextlib
    import io
    T = _gates()
    saved = T._HIDE
    T._HIDE = [("zz-secret-name", "c0000zz00")]
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            T._show("  OK  zz-secret-name の記事")
        label = T._label("gates_client_zz-secret-name_h1.test_x")
    finally:
        T._HIDE = saved
    check("子の出力の社の名前を伏せる", buf.getvalue(), "  OK  c0000zz00 の記事\n")
    check("門の名前に混ざった社の id も伏せる（前後が _ でも）", label, "gates_client_c0000zz00_h1.test_x")


def _run(jobs, only):
    env = {k: v for k, v in os.environ.items() if k not in ("GATES_AUDIT", "GATES_FAST")}
    env.update({"GATES_JOBS": str(jobs), "GATES_ONLY": only, "PYTHONIOENCODING": "utf-8"})
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "test_gates.py")], cwd=ROOT, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=600)
    return r.returncode, r.stdout + r.stderr


def test_shared_writes_in_parallel_stop_the_run():
    print("\n■ 同時に流す: 同時の組の門が管制塔のファイルを書いたら止まる・順でも同時でも同じ本数を流す")
    probe = ROOT / "tests" / f"{PROBE}.py"
    mark = ROOT / "automation" / "logs" / "zz_parallel_probe.txt"
    probe.write_text(
        "from pathlib import Path\n"
        "from test_gates import check\n\n\n"
        "def test_probe_writes_shared_file():\n"
        f"    p = Path(r'{mark}')\n"
        "    p.write_text('x', encoding='utf-8')\n"
        "    p.unlink()\n"
        "    check('試しの門', True, True)\n\n\n"
        "def test_probe_reads_only():\n"
        "    check('読むだけの門', True, True)\n", encoding="utf-8")
    try:
        only = f"{PROBE}|gates_history_h111"
        rc1, out1 = _run(1, only)
        rc2, out2 = _run(2, only)
    finally:
        probe.unlink()
        if mark.exists():
            mark.unlink()
    check("順に流すと通る（1本ずつなら書いても構わない）", (rc1, "すべて通りました" in out1), (0, True))
    check("同時に流すと、書いた門を見つけて止める", (rc2, "同時に流した門が管制塔のファイルを変えました" in out2), (1, True))
    check("どちらも同じ本数を流し、数え落ち・二重が無い",
          ("■ 流した門: 4本（予定 4本）" in out1, "■ 流した門: 4本（予定 4本）" in out2), (True, True))
