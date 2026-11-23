# -*- coding: utf-8 -*-
"""2026-11-23 ロボットよけを「断る」へ切り替える判断が、本物の相談2件（11/06 AI集客ラボ・11/10 コーポレート）が答え無し（none）で
届いたため止まっている。記録からは、部品が読めなかったのか、待ち切れなかったのかが分からず、直し方を決められなかった。
答えが無いまま送るときに、ページが部品の状態と待った秒（ts_state。例 wait:6）を添え、受付が記録の codes に page-<状態> と残す。
台帳（問い合わせの行）には入れない。"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from test_gates import check, ROOT

import gates_history_h79_turnstile as H79

GAS_RES = r"""
const res = {
  noneWithState: run(base({ ts_state: 'wait:6' })),
  noneOld: run(base({})),
  nastyState: run(base({ ts_state: '<script>x' })),
  good: run(base({ 'cf-turnstile-response': 'GOOD-token', ts_state: 'run:1' })),
};
console.log(JSON.stringify(res));
"""

FN_TEST = r"""
import { pathToFileURL } from "node:url";
const [dir] = process.argv.slice(2);
const T = await import(pathToFileURL(dir + "/_turnstile.js").href);
const env = { TURNSTILE_SECRET: "s", TURNSTILE_SITEKEY: "k" };
console.log(JSON.stringify({
  none: await T.verify(env, "", "", "err:2"),
  noneOld: await T.verify(env, "", ""),
  nasty: await T.verify(env, "", "", "<b>x\"y"),
  state: T.STATE,
}));
"""


def _node(script, *args):
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.mjs"
        p.write_text(script, encoding="utf-8")
        r = subprocess.run([node, str(p), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout)[-400:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_turnstile_none_records_page_state():
    print("\n■ ロボットよけ: 答え無しで届いた送信に、ページの部品の状態（ts_state）を記録し、台帳には入れない")
    fn = _node(FN_TEST, str(ROOT / "functions"))
    if fn is None:
        check("node がある（無いと確かめられない）", False, True)
        return
    check("AI集客ラボの受付: 答え無しは codes に page-<状態>", (fn["none"]["result"], fn["none"]["codes"]), ("none", "page-err:2"))
    check("AI集客ラボの受付: 状態を送らない古いページは page-unknown", fn["noneOld"]["codes"], "page-unknown")
    check("AI集客ラボの受付: 状態の文字は英数字とコロンだけ残す", fn["nasty"]["codes"], "page-bxy")
    lead = (ROOT / "functions" / "api" / "lead.js").read_text(encoding="utf-8")
    check("AI集客ラボの受付: ts_state を台帳へ送るデータに入れず、確かめに渡す",
          ("k !== STATE" in lead, "fd.get(STATE)" in lead), (True, True))
    js = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    check("ページ（site.js）: 答えが無いまま送る2か所で状態を添える", js.count("note(f);"), 2)

    harness = H79.GAS_HARNESS.split("const res = {")[0] + GAS_RES
    with mock_harness(harness):
        g = H79._gas("record")
    if g is None:
        return
    bot = g["noneWithState"]["bot"]
    check("管制塔: 答え無しの記録の codes に page-<状態>（ページから直接の送信）",
          [(r[4], r[6]) for r in bot], [("none", "page-wait:6")])
    check("管制塔: ts_state を台帳の行に残さない", "ts_state" in g["noneWithState"]["leadText"] or "wait:6" in g["noneWithState"]["leadText"], False)
    check("管制塔: 状態を送らない古いページは page-unknown", [r[6] for r in g["noneOld"]["bot"]], ["page-unknown"])
    check("管制塔: 状態の文字は英数字とコロンだけ残す", [r[6] for r in g["nastyState"]["bot"]], ["page-scriptx"])
    check("管制塔: 答えがある送信は状態で codes を上書きしない", [r[4] for r in g["good"]["bot"]], ["ok"])
    ts = (ROOT / "scripts" / "subsidy" / "turnstile_block.py").read_text(encoding="utf-8")
    check("補助金のページの部品: 答えが無いときに ts_state を添える", "ts_state:" in ts, True)


class mock_harness:
    """h79 の Apps Script の土台を使い、確かめる送信だけ差し替える"""
    def __init__(self, harness):
        self.h = harness

    def __enter__(self):
        self.old = H79.GAS_HARNESS
        H79.GAS_HARNESS = self.h

    def __exit__(self, *a):
        H79.GAS_HARNESS = self.old
