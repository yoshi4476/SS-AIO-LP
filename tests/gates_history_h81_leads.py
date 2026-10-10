# -*- coding: utf-8 -*-
"""2026-10-10 「このシステムの効果はどうか」の検算で見つけた、問い合わせの数え違い2つ。

1. 突き合わせ（lead_reconcile）が、9/25 より前の診断・サイト診断の「結果を出しただけ」（連絡先なし）を問い合わせの
   送信と数え、8月の4件を「台帳に行が無い＝取りこぼし」と出していた。当時の診断は完了の記録（diagnosis_complete /
   site_audit_complete）と1対1で lead_capture を出していた。運用者に「受信箱を見てほしい」と誤って頼んでいた
2. 補助金のサービスのページのフォームがサイトIDを送っていなかった時期の2行が、台帳でサイト名「（不明）」のまま、
   サイト別の件数から漏れていた。サービスアカウントは台帳を読むだけなので、受け口（lead_fix_site）で直す
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
GAS = ROOT / "automation" / "gas"

HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const out = (o) => ({ setMimeType: () => JSON.parse(o) });
const day = (s) => new Date(s + 'T03:00:00Z');
const rows = {
  'サイト一覧': [['サイトID', 'サイト名', 'ドメイン'], ['subsidy', 'AI導入補助金サポート', 'lp.7senses.co.jp', '', '', '', '', '']],
  '問い合わせ': [['受信日時', 'サイト'], [day('2026-09-02'), '（不明）'], [day('2026-09-02'), 'AI集客ラボ (ai.7senses.co.jp)'],
                 [day('2026-10-01'), '（不明）'], [day('2026-10-01'), '（不明）']],
};
const sheet = (name) => ({
  getLastRow: () => rows[name].length,
  getRange: (r, c, nr, nc) => ({
    getValues: () => rows[name].slice(r - 1, r - 1 + (nr || 1)).map((x) => { const y = x.slice(c - 1, c - 1 + (nc || 1)); while (y.length < (nc || 1)) y.push(''); return y; }),
    setValue: (v) => { rows[name][r - 1][c - 1] = v; },
  }),
});
const book = { getSheetByName: (n) => rows[n] ? sheet(n) : null, insertSheet: (n) => { rows[n] = [[]]; return sheet(n); } };
const ctx = { ContentService: { createTextOutput: out, MimeType: { JSON: 'json' } },
  SpreadsheetApp: { openById: () => book, getActiveSpreadsheet: () => book },
  PropertiesService: { getScriptProperties: () => ({ getProperty: () => '' }) },
  Utilities: { formatDate: (d) => d.toISOString().slice(0, 10) }, console };
vm.createContext(ctx);
for (const f of process.argv.slice(2)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f });
ctx.sheet_ = (n) => sheet(n);
const secret = vm.runInContext('SHARED_SECRET', ctx);
const post = (b) => ctx.doPost({ postData: { contents: JSON.stringify(b) } });
const res = {
  ok: post({ action: 'lead_fix_site', secret, day: '2026-09-02', site: 'subsidy' }),
  two: post({ action: 'lead_fix_site', secret, day: '2026-10-01', site: 'subsidy' }),
  unknownSite: post({ action: 'lead_fix_site', secret, day: '2026-10-01', site: 'nope' }),
  noSecret: post({ action: 'lead_fix_site', day: '2026-09-02', site: 'subsidy' }),
  sites: rows['問い合わせ'].slice(1).map((r) => r[1]),
};
console.log(JSON.stringify(res));
"""


def test_lead_counting_and_site_fix():
    print("\n■ 問い合わせの数え方: 古い診断の完了は数えず、サイト名の無い行は1対1で合うときだけ直す")
    import lead_reconcile as LR
    check("9/25 より前の診断の完了（結果を見ただけ）は問い合わせに数えない",
          (LR.count_rows([("20260821", "diagnosis_complete", "/diagnosis/aio/", 1), ("20260821", "lead_capture", "/diagnosis/aio/", 1)]),
           LR.count_rows([("20260804", "site_audit_complete", "/site-audit/", 1), ("20260804", "lead_capture", "/site-audit/", 1)])),
          ({}, {}))
    check("完了より送信が多い日は、その差を結果の送付の依頼として数える",
          LR.count_rows([("20260901", "diagnosis_complete", "/diagnosis/meo/", 1), ("20260901", "lead_capture", "/diagnosis/meo/", 2)]),
          {"2026-09-01": 1})
    check("9/25 の直し以降は、完了と同じ日の送信も数える（いまは連絡先を受け取ったときだけ出す）",
          LR.count_rows([("20261001", "diagnosis_complete", "/tools/diagnosis/aio/", 1),
                         ("20261001", "lead_capture", "/tools/diagnosis/aio/", 1)]), {"2026-10-01": 1})
    check("週次の検査は --fix で呼ぶ", '"lead_reconcile.py --fix"' in (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8"), True)

    node = shutil.which("node")
    if not node:
        print("  WARN  node が無いため受け口の動きは確かめられません")
        return
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "h.js"
        h.write_text(HARNESS, encoding="utf-8")
        p = subprocess.run([node, str(h), str(GAS / "hub.gs"), str(GAS / "contact.hub.gs")], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
    if p.returncode:
        raise RuntimeError(f"受け口を動かせませんでした: {(p.stderr or p.stdout)[-300:]}")
    r = json.loads(p.stdout.strip().splitlines()[-1])
    check("その日のサイト名の無い行が1行なら、サイト一覧の名前を入れる", (r["ok"].get("ok"), r["ok"].get("label")),
          (True, "AI導入補助金サポート (lp.7senses.co.jp)"))
    check("2行以上ある日・サイト一覧に無い id・合言葉なしは直さない",
          (r["two"].get("ok"), r["unknownSite"].get("ok"), r["noSecret"].get("error")), (False, False, "unauthorized"))
    check("名前の入っていた行と、直さなかった行はそのまま", r["sites"],
          ["AI導入補助金サポート (lp.7senses.co.jp)", "AI集客ラボ (ai.7senses.co.jp)", "（不明）", "（不明）"])
