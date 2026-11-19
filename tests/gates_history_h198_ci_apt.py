# -*- coding: utf-8 -*-
"""2026-11-19 準備の工程が、Ubuntu の配布元の一時的な不調（取得の時間切れ・一覧の404）で止まった。
`apt-get update && apt-get install` の形は、update が失敗を返すだけで、入れたいフォントは取れる状態でも
工程ごと止める。入れ方を scripts/ci_apt.sh にまとめ、update の失敗では止めず「入れられたか」で決める。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

WF = ROOT / ".github" / "workflows"
SH = ROOT / "scripts" / "ci_apt.sh"


def _bash():
    if sys.platform != "win32":
        return shutil.which("bash")
    # Windows の bash.exe（System32）は WSL で、手元のパスを読めない。Git の bash を使う
    for p in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if Path(p).exists():
            return p
    return None


FAKE_APT = """#!/usr/bin/env bash
echo "apt-get $*" >> "$FAKE/calls"
mode=$(cat "$FAKE/mode")
case "$1" in
  update) [ "$mode" = ok ] && exit 0; exit 100 ;;
esac
n=$(grep -c "apt-get install" "$FAKE/calls")
case "$mode" in
  update_fail|ok) exit 0 ;;
  flaky) [ "$n" -ge 2 ] && exit 0; exit 100 ;;
  *) exit 100 ;;
esac
"""


def _run(bash, mode, installed=False, tries=3):
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d)
        (fake / "mode").write_text(mode, encoding="utf-8")
        (fake / "calls").write_text("", encoding="utf-8")
        files = {"sudo": '#!/usr/bin/env bash\nexec "$@"\n', "apt-get": FAKE_APT,
                 "dpkg": "#!/usr/bin/env bash\nexit %d\n" % (0 if installed else 1)}
        for name, body in files.items():
            p = fake / name
            p.write_bytes(body.encode("utf-8"))
            p.chmod(0o755)
        env = {**os.environ, "FAKE": fake.as_posix(), "CI_APT_WAIT": "0", "CI_APT_TRIES": str(tries)}
        # Windows の Git の bash では C:/... の「:」が PATH の区切りに割れるので /c/... に直す
        cmd = (f'export PATH="$(cygpath -u "$FAKE" 2>/dev/null || echo "$FAKE"):$PATH"; '
               f'bash "{SH.as_posix()}" fonts-noto-cjk')
        r = subprocess.run([bash, "-c", cmd], env=env, capture_output=True, timeout=60)
        calls = (fake / "calls").read_text(encoding="utf-8").split("\n")
        return r.returncode, sum(1 for c in calls if c.startswith("apt-get install"))


def test_ci_apt_survives_mirror_flake():
    print("\n■ CI の apt: 配布元の一時的な不調（update の失敗）では止めず、入れられなければ止める")
    bash = _bash()
    check("検査に使う bash が見つかる（見つからなければ検査が動かない）", bool(bash), True)
    if not bash:
        return
    check("update が失敗しても、入れられれば成功（2026-11-19 に止まった形）", _run(bash, "update_fail"), (0, 1))
    check("1回目に入れられなくても、やり直して入れられれば成功", _run(bash, "flaky"), (0, 2))
    check("3回とも入れられなければ失敗を返す（フォント無しで先へ進めない）", _run(bash, "broken"), (1, 3))
    check("既に入っていれば apt を呼ばない", _run(bash, "broken", installed=True), (0, 0))
    check("1回だけ試す工程は、入れられなければ1回で諦める", _run(bash, "broken", tries=1), (1, 1))
    src = SH.read_text(encoding="utf-8")
    check("やり直しの前に、時間切れで中断した dpkg を片付ける", "sudo dpkg --configure -a" in src, True)
    slow = sorted(p.name for p in WF.glob("*.yml") if "CI_APT_TRIES=1 bash scripts/ci_apt.sh" in p.read_text(encoding="utf-8"))
    check("フォント無しでも進む工程は1回だけ試す（配布元が落ちた日に長く待たない）", slow,
          ["daily-video.yml", "monthly-report.yml", "selfheal.yml"])
    check("update と install の1回ごとに時間の上限をかける（応答待ちで6分止まった）",
          ("timeout 180 sudo apt-get update" in src, "timeout 300 sudo apt-get install" in src), (True, True))

    print("\n■ CI の apt の入れ方は ci_apt.sh にそろえる（update && install の形を残さない）")
    bad = []
    for p in sorted(WF.glob("*.yml")):
        t = p.read_text(encoding="utf-8")
        if re.search(r"apt-get\s+update[^\n]*&&", t):
            bad.append(p.name)
    check("apt-get update && ... の形が残るワークフロー", bad, [])
    uses = sorted(p.name for p in WF.glob("*.yml") if "bash scripts/ci_apt.sh" in p.read_text(encoding="utf-8"))
    check("ci_apt.sh で入れるワークフロー（数え違いの検知）", uses,
          ["daily-video.yml", "deploy.yml", "focus-mode.yml", "monthly-report.yml", "pipeline-multi.yml",
           "pipeline.yml", "selfheal.yml", "weekly-optimize.yml"])
