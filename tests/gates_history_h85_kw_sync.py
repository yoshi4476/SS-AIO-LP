# -*- coding: utf-8 -*-
"""2026-10-11 運用者の決定「（KW台帳の止まった2行を）なおしてよい」から。

記事は公開済み（90点以上・本番200）なのに、KW台帳で「執筆中」のまま止まった語が8件あった（AI集客ラボ・コーポレート・
補助金・お客様の社）。公開の記録（publish_log）が台帳の行に当たらなかった回がある。直すときに publish_log を呼ぶと
記事作成ログに同じ公開が2行になるので、台帳だけを直す受け口（kw_published）と、週次で見つけて直す道具
（kw_published_sync.py --write）を足した
"""
import io
import json
import contextlib
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
const rows = {
  'KW台帳': [['サイト', 'キーワード', '状態', '優先度', '想定カテゴリ', '狙い', '登録日', '着手日', '公開日', '記事URL', '備考'],
             ['ai-lab', 'クリニック 建築 事例', '執筆中', 'B', '', '', '', '', '', '', ''],
             ['ai-lab', '工務店 meo対策', '未着手', 'B', '', '', '', '', '', '', '']],
  '記事作成ログ': [['公開日時']],
};
const sheet = (name) => ({
  getLastRow: () => rows[name].length,
  appendRow: (r) => rows[name].push(r),
  getRange: (r, c, nr, nc) => ({
    getValues: () => rows[name].slice(r - 1, r - 1 + (nr || 1)).map((x) => { const y = x.slice(c - 1, c - 1 + (nc || 1)); while (y.length < (nc || 1)) y.push(''); return y; }),
    setValue: (v) => { rows[name][r - 1][c - 1] = v; },
  }),
});
const book = { getSheetByName: (n) => rows[n] ? sheet(n) : null };
const ctx = { ContentService: { createTextOutput: out, MimeType: { JSON: 'json' } },
  SpreadsheetApp: { openById: () => book, getActiveSpreadsheet: () => book },
  PropertiesService: { getScriptProperties: () => ({ getProperty: () => '' }) }, console };
vm.createContext(ctx);
for (const f of process.argv.slice(2)) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f });
Object.assign(ctx, { sheet_: (n) => sheet(n), siteLabel_: (s) => s });
const secret = vm.runInContext('SHARED_SECRET', ctx);
const post = (b) => ctx.doPost({ postData: { contents: JSON.stringify(b) } });
const res = {
  noSecret: post({ action: 'kw_published', site: 'ai-lab', keyword: 'クリニック 建築 事例', url: 'u' }),
  ok: post({ action: 'kw_published', secret, site: 'ai-lab', keyword: 'クリニック建築事例', url: 'https://x/a/' }),
  notBusy: post({ action: 'kw_published', secret, site: 'ai-lab', keyword: '工務店 meo対策', url: 'https://x/b/' }),
};
res.kw = rows['KW台帳'].slice(1).map((r) => [r[2], r[9]]);
res.logRows = rows['記事作成ログ'].length - 1;
post({ action: 'publish_log', secret, site: 'ai-lab', keyword: '工務店 meo対策', url: 'https://x/b/', title: 't' });
res.afterPublishLog = [rows['KW台帳'][2][2], rows['記事作成ログ'].length - 1];
console.log(JSON.stringify(res));
"""


def test_stuck_keywords_are_marked_published_without_double_logging():
    print("\n■ KW台帳: 公開済みなのに執筆中のまま止まった語は、記事作成ログを増やさずに公開済みへ直す")
    import kw_published_sync as K
    import hub_sheets as HS
    rows = [{"site": "ai-lab", "keyword": "クリニック 建築 事例", "status": "執筆中"},
            {"site": "ai-lab", "keyword": "工務店 meo対策", "status": "公開済み"},
            {"site": "corporate", "keyword": "クリニック 建築 事例", "status": "執筆中"}]
    arts = {"ai-lab": {"clinic-kenchiku-jirei": "クリニック建築事例", "x": "工務店 meo対策"}}
    check("執筆中の行だけ・同じ社の同じ語（表記ゆれは吸収）だけを拾う", K.stuck(rows, arts, HS.norm_kw),
          [("ai-lab", "クリニック 建築 事例", "clinic-kenchiku-jirei")])

    posted = []
    metas = {"a": {"score": 95, "category": "seo"}, "b": {"score": 85, "category": "seo"},
             "c": {"score": 95, "category": "seo"}, "d": {"score": 95, "category": "journal"}}
    cfgs = {"ai-lab": {"domain": "ai.example", "type": "self-static"},
            "cl": {"domain": "client.example", "type": "external-md", "client": True}}
    rows2 = [{"site": "ai-lab", "keyword": k, "status": "執筆中"} for k in ("語a", "語b", "語c")] + \
            [{"site": "cl", "keyword": "語d", "status": "執筆中"}]
    out = io.StringIO()
    with mock.patch("hub_client.all_kw", return_value=rows2), \
            mock.patch("hub_client._post", side_effect=lambda b: posted.append(b["keyword"]) or {"ok": True}), \
            mock.patch("sites.load_all", return_value=cfgs), \
            mock.patch("kw_plan.site_articles", side_effect=lambda sid: {"ai-lab": {"a": "語a", "b": "語b", "c": "語c"},
                                                                         "cl": {"d": "語d"}}[sid]), \
            mock.patch("publish.read_meta", side_effect=lambda p: metas[p.stem]), \
            mock.patch.object(K, "live", side_effect=lambda u: "/c/" not in u), \
            contextlib.redirect_stdout(out):
        K.main(["--write"])
    text = out.getvalue()
    check("90点以上で本番で開けるものだけ直す（90点未満・本番に無いものは執筆中のまま）", sorted(posted), ["語a", "語d"])
    check("お客様の社の語はログに出さない", ("語d" in text, "（お客様の記事）" in text), (False, True))

    check("週次の検査が --write で呼ぶ", '"kw_published_sync.py --write"' in (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8"),
          True)
    node = shutil.which("node")
    if not node:
        print("  WARN  node が無いため受け口の動きは確かめられません")
        return
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "h.js"
        h.write_text(HARNESS, encoding="utf-8")
        p = subprocess.run([node, str(h), str(GAS / "hub.gs")], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
    if p.returncode:
        raise RuntimeError(f"受け口を動かせませんでした: {(p.stderr or p.stdout)[-300:]}")
    r = json.loads(p.stdout.strip().splitlines()[-1])
    check("合言葉なしでは直さない", r["noSecret"].get("error"), "unauthorized")
    check("執筆中の行を公開済みにし、URL を入れる（表記ゆれは吸収）", (r["ok"].get("ok"), r["kw"][0]), (True, ["公開済み", "https://x/a/"]))
    check("執筆中でない行は直さない", (r["notBusy"].get("ok"), r["kw"][1][0]), (False, "未着手"))
    check("台帳だけを直し、記事作成ログには足さない", r["logRows"], 0)
    check("公開の記録（publish_log）は今までどおりログに足して台帳を公開済みにする", r["afterPublishLog"], ["公開済み", 1])
