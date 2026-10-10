# -*- coding: utf-8 -*-
"""2026-10-10 運用者「（後追いは）良いが今のものは全て対応している（今対応している場合はどのように管理すればいいのか）」。

自動の後追い（followUp）は「未対応」の行に送る。返信したのに台帳を「未対応」のまま置くと、翌日に後追いが重なって届く。
そこで、受信の日以降にこのアカウント（info.ai の別名を含む）からその人へ送ったメールがあれば「対応中」にして送らない。
対応状況はプルダウン（LEAD_STATUSES）にし、まとめて変える操作（lead_status）を足す。テストは自動で「対応不要」にする
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

GAS = ROOT / "automation" / "gas"

HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const out = (o) => ({ setMimeType: () => JSON.parse(o) });
const now = new Date();
const ago = (d) => new Date(now.getTime() - d * 86400000 - 3600000);
const mails = [];
const rows = {
  '問い合わせ': [
    ['受信日時', 'サイト', '種別', '会社名', 'お名前', '', 'メール', '電話', '本文', '詳細', '', '送信元', '温度', '対応状況', '後追い'],
    [ago(1), 'ai-lab', '無料相談', 'A社', '山田', '', 'replied@example.co.jp', '', '相談', '', '', '', 'HOT', '未対応', ''],
    [ago(1), 'ai-lab', '無料相談', 'B社', '佐藤', '', 'waiting@example.co.jp', '', '相談', '', '', '', 'HOT', '未対応', ''],
    [new Date('2026-09-02T01:02:00Z'), 'subsidy', '無料相談', 'C社', '鈴木', '', 'c@example.co.jp', '', '相談', '', '', '', 'HOT', '未対応', ''],
  ],
};
const sheet = (name) => ({
  getLastRow: () => rows[name].length,
  getMaxRows: () => 1000,
  getRange: (r, c, nr, nc) => ({
    getValues: () => rows[name].slice(r - 1, r - 1 + (nr || 1)).map((x) => { const y = x.slice(c - 1, c - 1 + (nc || 1)); while (y.length < (nc || 1)) y.push(''); return y; }),
    getValue: () => rows[name][r - 1][c - 1],
    setValue: (v) => { rows[name][r - 1][c - 1] = v; },
    setDataValidation: () => {}, setNote: () => {},
  }),
});
const book = { getSheetByName: (n) => rows[n] ? sheet(n) : null };
const ctx = { ContentService: { createTextOutput: out, MimeType: { JSON: 'json' } },
  SpreadsheetApp: { openById: () => book, getActiveSpreadsheet: () => book,
    newDataValidation: () => ({ requireValueInList: function () { return this; }, setAllowInvalid: function () { return this; }, build: () => ({}) }) },
  PropertiesService: { getScriptProperties: () => ({ getProperty: () => '' }) },
  Utilities: { formatDate: (d) => d.toISOString().slice(0, 10) },
  GmailApp: { search: (q) => (q.indexOf('replied@example.co.jp') >= 0 ? [{}] : []) },
  MailApp: { sendEmail: (m) => mails.push(m.to) }, console };
vm.createContext(ctx);
for (const f of process.argv.slice(2)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f });
Object.assign(ctx, { sheet_: (n) => sheet(n), siteLabel_: (s) => s, excludeSet_: () => ({}), syncClientExcludes_: () => 0,
  excluded_: () => false, toolFollowCtx_: () => ({}), toolKind_: () => '', scoreOf_: () => null });
const secret = vm.runInContext('SHARED_SECRET', ctx);
const post = (b) => ctx.doPost({ postData: { contents: JSON.stringify(b) } });
ctx.followUp();
const follow = { mails: mails.slice(), status: rows['問い合わせ'].slice(1, 3).map((r) => r[13]) };
const st = post({ action: 'lead_status', secret, items: [{ row: 4, day: '2026-09-02', status: '対応済み' },
  { row: 4, day: '2026-09-03', status: '対応中' }, { row: 3, day: '2026-09-02', status: 'でたらめ' }] });
const noSecret = post({ action: 'lead_status', items: [{ row: 4, day: '2026-09-02', status: '失注' }] });
rows['問い合わせ'].push([now, 'ai-lab', '無料相談', '', '', '', 't@7senses.co.jp', '', '', '', '', '', '', '未対応', '']);
ctx.leadSetKind_({ row: 5, merged: false }, vm.runInContext('LEAD_TEST', ctx), 'note');
console.log(JSON.stringify({ follow, st, noSecret, c: rows['問い合わせ'][3][13], test: rows['問い合わせ'][4][13],
  statuses: vm.runInContext('LEAD_STATUSES', ctx) }));
"""


def test_lead_status_and_follow_up_skip_replied():
    print("\n■ 問い合わせの対応状況: 返信済みの人には後追いを送らず「対応中」に、状態はプルダウンとまとめての変更で管理する")
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
        raise RuntimeError(f"受け口を動かせませんでした: {(p.stderr or p.stdout)[-400:]}")
    r = json.loads(p.stdout.strip().splitlines()[-1])
    check("返信済みの人には後追いを送らず、返信していない人には送る", r["follow"]["mails"], ["waiting@example.co.jp"])
    check("返信済みの人の対応状況は「対応中」になる", r["follow"]["status"][0], "対応中")
    check("まとめての変更は、行番号と受信日が合い、選択肢にある状態だけ",
          ([c["row"] for c in r["st"]["changed"]], len(r["st"]["skipped"]), r["c"]), ([4], 2, "対応済み"))
    check("合言葉なしでは変えられない", r["noSecret"].get("error"), "unauthorized")
    check("テストと判定した行は「対応不要」になる", r["test"], "対応不要")
    check("選択肢に、返信・商談・結果の段階がそろっている",
          all(s in r["statuses"] for s in ("未対応", "対応中", "商談中", "成約", "失注", "対応不要")), True)
    hub = (GAS / "hub.gs").read_text(encoding="utf-8")
    check("後追いの有効化とプルダウンは保守の操作から呼べる", ("case 'followup_trigger'" in hub, "case 'lead_status_menu'" in hub),
          (True, True))
