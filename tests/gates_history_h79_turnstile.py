# -*- coding: utf-8 -*-
"""2026-10-10 運用者「問い合わせ先の情報を守りたい」→ ロボットよけ（Cloudflare Turnstile）を付けることを承認。

フォームには隠し欄しか無く、機械で大量に送ると (1) 問い合わせの台帳が埋まり、(2) 管制塔の自動返信で他人のアドレスへ
当社のメールを出させられ、MailApp の1日の上限を食い切ると本物の問い合わせの通知・自動返信まで止まる。

最優先は「本物の問い合わせを1件も落とさないこと」。そのため:
- 断る/断らないは定数1つ（管制塔 TURNSTILE_ENFORCE・AI集客ラボ functions/_turnstile.js の ENFORCE）。まず記録だけ
- Cloudflare に確かめられない（error）・鍵が無い（unset）ときは断らない。疎通確認（@pipeline-check.invalid）も断らない
- 合言葉つき（サーバーで確かめ済み）は管制塔で確かめ直さない（答えは1回きりなので、確かめ直すと必ず不正になる）
- ページの部品はフォームに触れるまで読まない（約590KB。表示速度の方針）。答えが遅れても最大6秒待って送る
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
GAS = ROOT / "automation" / "gas"
FN = ROOT / "functions"
SITE = ROOT / "site"

GAS_HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const [mode, ...files] = process.argv.slice(2);
const out = (o) => ({ setMimeType: () => JSON.parse(o) });
let sheets = {}, fetches = [], mails = 0, cache = {};
const sheet = (rows) => ({ rows, appendRow: (r) => rows.push(r), getLastRow: () => rows.length,
  getRange: (r, c, nr, nc) => ({ getValues: () => rows.slice(r - 1, r - 1 + nr).map((x) => x.slice(c - 1, c - 1 + nc)) }) });
const book = { getSheetByName: (n) => sheets[n] || null, insertSheet: (n) => (sheets[n] = sheet([])), getUrl: () => 'u' };
const ctx = { ContentService: { createTextOutput: out, MimeType: { JSON: 'json' } },
  SpreadsheetApp: { openById: () => book, getActiveSpreadsheet: () => book },
  PropertiesService: { getScriptProperties: () => ({ getProperty: () => '' }) },
  CacheService: { getScriptCache: () => ({ get: (k) => cache[k] || null, put: (k, v) => { cache[k] = v; } }) },
  Utilities: { formatDate: () => '2026101010' },
  MailApp: { sendEmail: () => { mails++; } },
  UrlFetchApp: { fetch: (url, o) => {
    fetches.push(url);
    const t = String((o.payload || {}).response || '');
    if (t.startsWith('DOWN')) throw new Error('Address unavailable');
    const j = t.startsWith('GOOD') ? { success: true, hostname: 'lp.7senses.co.jp' }
                                   : { success: false, 'error-codes': ['invalid-input-response'] };
    return { getResponseCode: () => 200, getContentText: () => JSON.stringify(j) };
  } }, console };
vm.createContext(ctx);
for (const f of files) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f });
ctx.siteLabel_ = (s) => s || '';
const secret = vm.runInContext('SHARED_SECRET', ctx);
const FORM = vm.runInContext('FORM_SECRET', ctx);
function run(body) {
  sheets = { '問い合わせ': sheet([['日時']]), 'エラーログ': sheet([]) };
  fetches = []; mails = 0;
  const r = ctx.doPost({ postData: { contents: JSON.stringify(body) } });
  const leads = sheets['問い合わせ'].rows.slice(1);
  const bot = (sheets['ロボットよけ'] || { rows: [] }).rows.slice(1);
  const probe = (sheets['疎通確認'] || { rows: [] }).rows.slice(1);
  return { r, leads: leads.length, leadText: JSON.stringify(leads), bot, probe: probe.length, fetches: fetches.length, mails };
}
const base = (x) => Object.assign({ site: 'subsidy', type: 'contact', name: '山田', email: 'a@example.co.jp',
  message: '相談です', silent: true }, x);
const res = {
  none: run(base({})),
  good: run(base({ 'cf-turnstile-response': 'GOOD-token' })),
  bad: run(base({ 'cf-turnstile-response': 'BAD-token' })),
  down: run(base({ 'cf-turnstile-response': 'DOWN-token' })),
  nested: run({ site: 'corporate', silent: true, data: { type: 'contact', name: '山田', email: 'b@example.co.jp', detail: 'x',
    'cf-turnstile-response': 'GOOD-nested' } }),
  trusted: run({ secret, site: 'ai-lab', silent: true, turnstile: { result: 'none' },
    data: { type: 'contact', name: '山田', email: 'c@example.co.jp', message: 'x' } }),
  trustedQuiet: run({ secret, site: 'ai-lab', silent: true, data: { type: 'contact', name: '山田', email: 'd@example.co.jp', message: 'x' } }),
  probe: run(base({ email: 'probe-subsidy-1@pipeline-check.invalid' })),
  unsub: run(base({ type: 'unsubscribe', email: 'e@example.co.jp' })),
  status: (() => { run(base({})); return ctx.doPost({ postData: { contents: JSON.stringify({ action: 'bot_status', secret }) } }); })(),
  statusNoSecret: ctx.doPost({ postData: { contents: JSON.stringify({ action: 'bot_status' }) } }),
  formOk: run({ form_secret: FORM, site: 'client-x', type: 'contact', silent: true, name: '山田', email: 'f@example.co.jp',
    message: 'x', turnstile: { result: 'ok', host: 'client.example.jp' } }),
  formWrong: run({ form_secret: 'wrong-secret', site: 'client-x', type: 'contact', silent: true, name: '山田',
    email: 'g@example.co.jp', message: 'x' }),
  formEmpty: run({ form_secret: '', site: 'client-x', type: 'contact', silent: true, name: '山田', email: 'h@example.co.jp',
    message: 'x' }),
  formAction: ctx.doPost({ postData: { contents: JSON.stringify({ action: 'bot_status', form_secret: FORM }) } }),
};
console.log(JSON.stringify(res));
"""


FORM_FOR_TEST = "form-secret-for-test-0123456789abcdef"


def _gas(mode, filled=True, form=True):
    """管制塔の受付を Node の上で動かす。filled=True は gas_deploy.fill で鍵を埋めた形（配る形と同じ）"""
    import gas_deploy as GD
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name in ("hub.gs", "contact.hub.gs"):
            src = (GAS / name).read_text(encoding="utf-8")
            if filled:
                src = GD.fill(src, {"TURNSTILE_SECRET": "sekret-for-test", "HUB_SECRET": "hub-secret-for-test",
                                    **({"HUB_FORM_SECRET": FORM_FOR_TEST} if form else {})})
            if mode == "enforce":
                src = src.replace("const TURNSTILE_ENFORCE = false;", "const TURNSTILE_ENFORCE = true;")
            p = Path(d) / name.replace(".gs", ".js")
            p.write_text(src, encoding="utf-8")
            paths.append(str(p))
        h = Path(d) / "h.js"
        h.write_text(GAS_HARNESS, encoding="utf-8")
        r = subprocess.run([node, str(h), mode, *paths], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
    if r.returncode:
        raise RuntimeError(f"Apps Script を動かせませんでした: {(r.stderr or r.stdout)[-400:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


FN_HARNESS = r"""
import { pathToFileURL } from "node:url";
const [dir] = process.argv.slice(2);
const calls = [];
globalThis.fetch = async (url, o = {}) => {
  url = String(url);
  if (url.includes("siteverify")) {
    const t = String(o.body.get("response"));
    calls.push(["verify", t.length]);
    if (t.startsWith("DOWN")) throw new Error("offline");
    return Response.json(t.startsWith("GOOD") ? { success: true, hostname: "ai.7senses.co.jp" } : { success: false, "error-codes": ["invalid-input-response"] });
  }
  if (url.includes("gas.test")) { calls.push(["gas", JSON.parse(o.body)]); return Response.json({ ok: true }); }
  calls.push(["other", url]);
  return Response.json({ id: "x" });
};
const env = { TURNSTILE_SITEKEY: "0xKEY", TURNSTILE_SECRET: "s", GAS_WEBHOOK_URL: "https://gas.test/exec", GAS_SHARED_SECRET: "hs",
  RESEND_API_KEY: "r", RESEND_AUDIENCE_ID: "a" };
const lead = await import(pathToFileURL(dir + "/api/lead.js").href);
const sub = await import(pathToFileURL(dir + "/api/subscribe.js").href);
async function post(m, fields, e = env) {
  calls.length = 0;
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, v);
  const waits = [];
  const r = await m.onRequestPost({ request: new Request("https://ai.7senses.co.jp/api/x", { method: "POST", body: fd }), env: e,
    waitUntil: (p) => waits.push(p) });
  await Promise.all(waits);
  const text = r.status >= 400 ? await r.text() : "";
  return { status: r.status, text, calls: JSON.parse(JSON.stringify(calls)) };
}
const f = (x) => Object.assign({ name: "山田", company: "テスト", email: "a@example.co.jp", form_type: "お問い合わせ", message: "x" }, x);
const longTok = "GOOD" + "x".repeat(2040);
const out = {
  get: await (await lead.onRequestGet({ env })).json(),
  getNoKey: await (await lead.onRequestGet({ env: {} })).json(),
  none: await post(lead, f({})),
  good: await post(lead, f({ "cf-turnstile-response": longTok })),
  bad: await post(lead, f({ "cf-turnstile-response": "BAD" })),
  down: await post(lead, f({ "cf-turnstile-response": "DOWN" })),
  probe: await post(lead, f({ email: "probe-ai-lab-1@pipeline-check.invalid" })),
  unset: await post(lead, f({}), Object.assign({}, env, { TURNSTILE_SECRET: "" })),
  subNone: await post(sub, { email: "a@example.co.jp" }),
  subGood: await post(sub, { email: "a@example.co.jp", "cf-turnstile-response": "GOOD" }),
};
console.log(JSON.stringify(out));
"""


def _fn(enforce):
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.TemporaryDirectory() as d:
        dst = Path(d) / "functions"
        shutil.copytree(FN, dst)
        t = dst / "_turnstile.js"
        src = t.read_text(encoding="utf-8")
        if enforce:
            src = src.replace("export const ENFORCE = { lead: false, subscribe: false };",
                              "export const ENFORCE = { lead: true, subscribe: true };")
        t.write_text(src, encoding="utf-8")
        h = Path(d) / "h.mjs"
        h.write_text(FN_HARNESS, encoding="utf-8")
        r = subprocess.run([node, str(h), dst.as_posix()], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
    if r.returncode:
        raise RuntimeError(f"受付（functions）を動かせませんでした: {(r.stderr or r.stdout)[-400:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])


def _gas_body(res):
    return next((c[1] for c in res["calls"] if c[0] == "gas"), {})


def test_h79_hub_records_then_refuses_only_when_told():
    print("\n■ ロボットよけ（管制塔）: 記録だけの間は断らない／強制でも合言葉つき・疎通確認・Cloudflare の不調では断らない")
    src = (GAS / "contact.hub.gs").read_text(encoding="utf-8")
    check("管制塔は記録だけの段階（TURNSTILE_ENFORCE = false）", "const TURNSTILE_ENFORCE = false;" in src, True)
    import gas_deploy as GD
    check("配るときに鍵を埋める（gas_deploy.fill）・鍵はリポジトリに書かない",
          ("'TURNSTILE_SECRET_XXXXXXXX'" in src, "'k'" in GD.fill("'TURNSTILE_SECRET_XXXXXXXX'", {"TURNSTILE_SECRET": "k"})),
          (True, True))
    rec = _gas("record")
    if rec is None:
        print("  WARN  node が無いため管制塔の受付の動きは確かめられません")
        return
    row = lambda r: [r["bot"][0][2], r["bot"][0][4], r["bot"][0][5], r["bot"][0][8]] if r["bot"] else []
    check("記録: 答え無しでも受け付け、台帳に1行・記録は none", (rec["none"]["r"], rec["none"]["leads"], row(rec["none"])),
          ({"ok": True}, 1, ["ページから直接", "none", "", "受付"]))
    check("記録: 正しい答えは ok とドメイン", row(rec["good"]), ["ページから直接", "ok", "lp.7senses.co.jp", "受付"])
    check("記録: 不正な答えも受け付ける（invalid と残す）", (rec["bad"]["leads"], row(rec["bad"])[1]), (1, "invalid"))
    check("記録: 答えの文字列は台帳に入らない", "GOOD-token" in rec["good"]["leadText"] or "GOOD-nested" in rec["nested"]["leadText"],
          False)
    check("記録: data の中に入れて送る形（コーポレート）も確かめる", (rec["nested"]["leads"], row(rec["nested"])[1]), (1, "ok"))
    check("合言葉つきは Cloudflare に問い合わせず、届いた結果を記録する",
          (rec["trusted"]["fetches"], row(rec["trusted"])[:2], rec["trusted"]["leads"]), (0, ["サーバーで確認", "none"], 1))
    check("合言葉つきで結果を添えない送り元は記録しない", (rec["trustedQuiet"]["bot"], rec["trustedQuiet"]["leads"]), ([], 1))
    check("集計は合言葉つきでだけ読める", (rec["status"]["ok"], rec["status"]["enforce"], rec["status"]["secret"],
                                         rec["statusNoSecret"].get("error")), (True, False, True, "unauthorized"))

    enf = _gas("enforce")
    refused = enf["none"]["r"]
    check("強制: 答え無しは断り、電話番号を案内する。台帳にもメールにも入らない",
          (refused.get("ok"), "06-4305-7547" in refused.get("error", ""), enf["none"]["leads"], enf["none"]["mails"],
           row(enf["none"])[3]), (False, True, 0, 0, "断った"))
    check("強制: 不正な答えも断る", (enf["bad"]["r"].get("ok"), enf["bad"]["leads"]), (False, 0))
    check("強制: 正しい答えは受け付ける", (enf["good"]["r"], enf["good"]["leads"]), ({"ok": True}, 1))
    check("強制: Cloudflare に確かめられないときは受け付ける（error と残す）",
          (enf["down"]["r"], enf["down"]["leads"], row(enf["down"])[1]), ({"ok": True}, 1, "error"))
    check("強制: 合言葉つき（サーバーで確かめ済み）は断らない", (enf["trusted"]["r"], enf["trusted"]["leads"]), ({"ok": True}, 1))
    check("強制: 疎通確認は答え無しでも断らず、疎通確認の表にだけ残る",
          (enf["probe"]["r"].get("ok"), enf["probe"]["probe"], enf["probe"]["leads"]), (True, 1, 0))
    check("強制: 配信停止も答え無しは断る（他人のアドレスへ確認メールを出させない）",
          (enf["unsub"]["r"].get("ok"), enf["unsub"]["mails"]), (False, 0))
    unset = _gas("enforce", filled=False)
    check("強制でも鍵が無ければ断らず、記録もしない（鍵を入れ忘れた配布で問い合わせを落とさない）",
          (unset["none"]["r"], unset["none"]["leads"], unset["none"]["bot"]), ({"ok": True}, 1, []))


def test_h79_ai_lab_functions_verify_and_forward_the_result():
    print("\n■ ロボットよけ（AI集客ラボの受付）: 確かめて結果を管制塔へ添える／強制は定数1つ")
    t = (FN / "_turnstile.js").read_text(encoding="utf-8")
    check("AI集客ラボの受付は記録だけの段階（ENFORCE がどちらも false）",
          "export const ENFORCE = { lead: false, subscribe: false };" in t, True)
    rec = _fn(False)
    if rec is None:
        print("  WARN  node が無いため受付の動きは確かめられません")
        return
    check("ページへ返すのはサイトキーと強制の有無だけ（鍵が無ければ空）",
          (rec["get"], rec["getNoKey"]["turnstile"]), ({"turnstile": "0xKEY", "enforce": {"lead": False, "subscribe": False}}, ""))
    b = _gas_body(rec["none"])
    check("記録: 答え無しでも受け付け、管制塔へ none を添える。答えの欄は本文に入れない",
          (rec["none"]["status"], b.get("turnstile", {}).get("result"), "cf-turnstile-response" in b.get("data", {})),
          (303, "none", False))
    g = _gas_body(rec["good"])
    check("記録: 長い答え（2,044字）を切らずに確かめ、ok を添える",
          ([c for c in rec["good"]["calls"] if c[0] == "verify"], g.get("turnstile", {}).get("result"),
           g.get("turnstile", {}).get("host")), ([["verify", 2044]], "ok", "ai.7senses.co.jp"))
    check("記録: 不正・確かめられない答えも受け付ける", (rec["bad"]["status"], rec["down"]["status"],
                                                   _gas_body(rec["down"]).get("turnstile", {}).get("result")), (303, 303, "error"))
    check("鍵が無ければ確かめない（unset のまま受け付ける）",
          (rec["unset"]["status"], [c for c in rec["unset"]["calls"] if c[0] == "verify"]), (303, []))
    sb = next((c[1] for c in rec["subGood"]["calls"] if c[0] == "gas"), {})
    check("購読: 確かめて受け付け、結果を管制塔の記録へ送る（合言葉つき）",
          (rec["subNone"]["status"], rec["subGood"]["status"], sb.get("action"), sb.get("secret"), sb.get("turnstile", {}).get("result")),
          (303, 303, "bot_log", "hs", "ok"))

    enf = _fn(True)
    n = enf["none"]
    check("強制: 答え無しは 403 と電話番号。管制塔へは問い合わせを送らず、断った記録だけ送る",
          (n["status"], "06-4305-7547" in n["text"], [c[1].get("action") for c in n["calls"] if c[0] == "gas"],
           _gas_body(n).get("refused")), (403, True, ["bot_log"], True))
    check("強制: 不正な答えは断る・正しい答えは受け付ける", (enf["bad"]["status"], enf["good"]["status"]), (403, 303))
    check("強制: 確かめられない・鍵が無い・疎通確認は断らない",
          (enf["down"]["status"], enf["unset"]["status"], enf["probe"]["status"]), (303, 303, 303))
    check("強制: 購読も答え無しは断る", (enf["subNone"]["status"], enf["subGood"]["status"]), (403, 303))


FAKE_API = r"""
(function () {
  var mode = window.__tsMode || "fast";
  window.__tsReset = 0;
  window.turnstile = {
    render: function (el, o) {
      var i = document.createElement("input"); i.type = "hidden"; i.name = "cf-turnstile-response"; el.appendChild(i);
      var face = document.createElement("div"); face.style.height = "65px"; el.appendChild(face);   // 本物は常に iframe を置く
      window.__tsOpts = { appearance: o.appearance, action: o.action };
      var give = function () { i.value = "GOOD-" + Date.now(); o.callback(i.value); };
      if (mode === "fast") setTimeout(give, 50);
      if (mode === "slow") setTimeout(give, 1500);
      if (mode === "ask") setTimeout(function () { o["before-interactive-callback"](); }, 50);
      window.__tsGive = give;
      return "w1";
    },
    reset: function () { window.__tsReset++; var i = document.querySelector('input[name="cf-turnstile-response"]'); if (i) i.value = "";
      if (mode === "fast") setTimeout(window.__tsGive, 50); },
  };
  var cb = new URL(document.currentScript.src).searchParams.get("onload");
  setTimeout(function () { window[cb](); }, 10);
})();
"""


def _browser_case(page, path, mode, api="ok", enforce=False, form_sel="form.form-panel", fill=None, sub=False):
    """site/ のページを偽の Cloudflare で開き、送信を1回する。送った本文と、部品を読んだ時点を返す"""
    import time
    got = {"posts": [], "api_at": None, "loaded_on_open": False}

    def handle(route):
        u = route.request.url
        if u.startswith("http://ss.test/api/"):
            if route.request.method == "GET":
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"turnstile": "0xKEY", "enforce": {"lead": enforce, "subscribe": enforce}}))
            got["posts"].append(route.request.post_data or "")
            if sub:
                return route.fulfill(status=200, body="ok")
            return route.fulfill(status=200, content_type="text/html", body="<p id=done>thanks</p>")
        if u.startswith("http://ss.test/"):
            rel = u.split("http://ss.test/", 1)[1].split("?")[0].split("#")[0]
            f = SITE / rel
            if f.is_dir() or not rel:
                f = f / "index.html"
            if not f.is_file():
                return route.fulfill(status=404, body="")
            ct = {"html": "text/html; charset=utf-8", "js": "application/javascript", "css": "text/css"}.get(f.suffix[1:], "")
            return route.fulfill(status=200, body=f.read_bytes(), headers={"Content-Type": ct} if ct else {})
        if "challenges.cloudflare.com/turnstile" in u:
            got["api_at"] = time.time()
            if api == "blocked":
                return route.abort()
            return route.fulfill(status=200, content_type="application/javascript", body=FAKE_API)
        return route.abort()

    page.unroute("**/*")
    page.route("**/*", handle)
    page.add_init_script(f"window.__tsMode = {json.dumps(mode)};")
    page.goto("http://ss.test" + path, wait_until="load")
    page.wait_for_timeout(300)
    got["loaded_on_open"] = got["api_at"] is not None
    for sel, val in (fill or {}).items():
        page.fill(f"{form_sel} {sel}", val)
    for cb in page.query_selector_all(f"{form_sel} input[type=checkbox][required]"):
        cb.check()
    for s in page.query_selector_all(f"{form_sel} select[required]"):
        s.select_option(index=1)
    page.wait_for_timeout(400)
    # 送る前に測る（ふつうのフォームは送ると次のページへ移る）
    got["opts"] = page.evaluate("window.__tsOpts || null")
    got["box"] = page.evaluate("(() => { const b = document.querySelector('.ts-box'); return b ? b.getBoundingClientRect().height : -1; })()")
    t0 = time.time()
    page.click(f"{form_sel} button[type=submit]")
    for _ in range(90):
        if got["posts"]:
            break
        page.wait_for_timeout(100)
    got["waited"] = round(time.time() - t0, 1)
    def look(js, default):
        # ふつうのフォームは送ると次のページへ移る。移っている途中なら読めないので既定の値にする
        try:
            return page.evaluate(js)
        except Exception:
            return default
    got["msg"] = look("(document.querySelector('.ts-msg') || {}).textContent || ''", "") if not got["posts"] else ""
    got["reset"] = look("window.__tsReset || 0", 0) if sub else 0
    return got


def test_h79_page_widget_loads_late_and_never_blocks_a_real_send():
    print("\n■ ロボットよけ（ページの部品）: 触れるまで読まない・答えを添える・読めなくても送る（偽の Cloudflare で確かめる）")
    js = (SITE / "js" / "site.js").read_text(encoding="utf-8")
    pages = [p for p in SITE.rglob("*.html") if "challenges.cloudflare.com" in p.read_text(encoding="utf-8", errors="ignore")]
    check("部品（challenges.cloudflare.com）を開いた時点で読むページが無い", [p.relative_to(SITE).as_posix() for p in pages], [])
    check("部品の読み込みはフォームに触れた時点（focusin・pointerdown）・明示描画・interaction-only",
          ('document.addEventListener("focusin", touch, true)' in js, "render=explicit" in js, '"interaction-only"' in js),
          (True, True, True))
    acts = sorted({a for p in SITE.rglob("*.html") for a in re.findall(r'<form[^>]*action="(/api/(?:lead|subscribe))"',
                                                                       p.read_text(encoding="utf-8", errors="ignore"))})
    check("部品を付ける対象に、ページにある問い合わせ・購読の送り先が全部入っている",
          [a for a in acts if f'form[action="{a}"]' not in js], [])
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as e:
        print(f"  SKIP  chromium が使えないため、ページの部品の動きは確かめられません: {str(e)[:80]}")
        return
    contact = {"input[name=name]": "山田", "input[name=company]": "テスト", "input[name=email]": "a@example.co.jp"}
    try:
        def case(*a, **k):
            ctx = browser.new_context()
            try:
                return _browser_case(ctx.new_page(), *a, **k)
            finally:
                ctx.close()
        fast = case("/contact/", "fast", fill=contact)
        check("お問い合わせ: 開いた時点では部品を読まない", fast["loaded_on_open"], False)
        check("お問い合わせ: 答えを添えて送る・見た目は interaction-only・ふだんは高さ0",
              ("cf-turnstile-response" in (fast["posts"] or [""])[0] and "GOOD-" in (fast["posts"] or [""])[0], fast["opts"],
               fast["box"]), (True, {"appearance": "interaction-only", "action": "lead"}, 0))
        slow = case("/contact/", "slow", fill=contact)
        check("答えが遅れたら待ってから、答えを添えて送る", (bool(slow["posts"]), "GOOD-" in (slow["posts"] or [""])[0]), (True, True))
        never = case("/contact/", "never", fill=contact)
        check("答えが出なくても6秒ほどで送る（記録だけの段階では止めない）",
              (bool(never["posts"]), 5 <= never["waited"] <= 8.5), (True, True))
        blocked = case("/contact/", "fast", api="blocked", fill=contact)
        check("部品を読めない（塞がれた）ときは待たずに送る", (bool(blocked["posts"]), blocked["waited"] < 3), (True, True))
        ask = case("/contact/", "ask", enforce=True, fill=contact)
        check("強制の段階で人の操作を求められたら、送らずに案内を出す（電話番号つき）・欄を見せる",
              (ask["posts"], "06-4305-7547" in ask["msg"], ask["box"] > 0), ([], True, True))
        ask_rec = case("/contact/", "ask", enforce=False, fill=contact)
        check("記録だけの段階では、人の操作を求められても送る", bool(ask_rec["posts"]), True)
        arts = sorted(p for p in SITE.glob("aio/*/index.html") if 'action="/api/subscribe"' in p.read_text(encoding="utf-8"))
        if arts:
            path = "/" + arts[0].parent.relative_to(SITE).as_posix() + "/"
            nl = case(path, "fast", form_sel="form.nl-form", fill={"input[name=email]": "a@example.co.jp"}, sub=True)
            check("購読（画面内で送る）: 答えを添えて送り、送った後に答えを作り直す",
                  ("GOOD-" in (nl["posts"] or [""])[0], nl["opts"]["action"] if nl["opts"] else None, nl["reset"] >= 1),
                  (True, "subscribe", True))
    finally:
        browser.close()
        pw.stop()


SUB = ROOT / ".publish-work" / "subsidy"
CORP = ROOT / ".publish-work" / "corporate"

SUB_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<form id="contactForm" novalidate><input id="f-name" name="name"><input name="website" type="text">
<button type="submit" id="submitBtn">送る</button></form>
<script>
const GAS_ENDPOINT="https://script.google.com/macros/s/AKfyTEST/exec";
const form=document.getElementById("contactForm");
function sendPayload(data){
  const payload=Object.assign({site:"subsidy"},data);
  return fetch(GAS_ENDPOINT,{method:"POST",headers:{"Content-Type":"text/plain;charset=utf-8"},body:JSON.stringify(payload)})
    .then(r=>r.json()).then(j=>{ window.__done=j; });
}
form.addEventListener("submit",e=>{ e.preventDefault(); sendPayload({type:"contact",name:"x"}); });
</script>
</body></html>"""


def test_h79_subsidy_and_corporate_pages_send_the_answer():
    print("\n■ ロボットよけ（補助金・コーポレート）: 管制塔へ直接送るページは答えを添える／読めなくても送る")
    import importlib.util
    # scripts/subsidy を検索の道に足さない（同じ場所の pages.py は読み込むだけで補助金サイトを組み直す）
    spec = importlib.util.spec_from_file_location("turnstile_block", ROOT / "scripts" / "subsidy" / "turnstile_block.py")
    TB = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(TB)
    once = TB.apply(SUB_PAGE)
    check("補助金: 部品と送り口を当て、何度当てても同じ", (TB.apply(once) == once, TB.unsent(once), once.count('id="ss-turnstile-js"')),
          (True, 0, 1))
    check("補助金: 管制塔へ送らないページには当てない", TB.apply("<html><body>x</body></html>"), "<html><body>x</body></html>")
    pages_src = (ROOT / "scripts" / "subsidy" / "pages.py").read_text(encoding="utf-8")
    check("補助金: 毎回の配信（subsidy/pages.py の sync_chrome）が部品を揃える", "TB.apply(chrome(t, root))" in pages_src, True)
    if SUB.is_dir():
        bad = []
        for p in SUB.rglob("*.html"):
            if TB.SKIP & set(p.relative_to(SUB).parts):
                continue
            t = p.read_text(encoding="utf-8", errors="ignore")
            if "const GAS_ENDPOINT" in t and (TB.unsent(t) or 'id="ss-turnstile-js"' not in t):
                bad.append(p.relative_to(SUB).as_posix())
        check("補助金の作業コピー: 管制塔へ直接送るページは全部、答えを添える送り口", sorted(bad), [])
    if (CORP / "src").is_dir():
        form = (CORP / "src" / "components" / "ContactForm.tsx").read_text(encoding="utf-8")
        hdr = (CORP / "public" / "_headers").read_text(encoding="utf-8")
        csp = next((ln for ln in hdr.splitlines() if "Content-Security-Policy" in ln), "")
        need = [d for d in ("script-src", "frame-src", "connect-src")
                if not re.search(d + r"[^;]*https://challenges\.cloudflare\.com", csp)]
        check("コーポレートの作業コピー: フォームが答えを添え、CSP が部品を許す（script・frame・connect）",
              ("useTurnstile(" in form and '"cf-turnstile-response"' in form, need), (True, []))
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as e:
        print(f"  SKIP  chromium が使えないため、補助金の部品の動きは確かめられません: {str(e)[:80]}")
        return
    try:
        def run(api):
            ctx = browser.new_context()
            page = ctx.new_page()
            posts = []

            def handle(route):
                u = route.request.url
                if u.startswith("http://sub.test/"):
                    return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=once)
                if "challenges.cloudflare.com/turnstile" in u:
                    if api == "blocked":
                        return route.abort()
                    return route.fulfill(status=200, content_type="application/javascript", body=FAKE_API)
                if "script.google.com" in u:
                    posts.append(route.request.post_data or "")
                    return route.fulfill(status=200, content_type="application/json", body='{"ok":true}',
                                         headers={"Access-Control-Allow-Origin": "*"})
                return route.abort()
            page.route("**/*", handle)
            page.add_init_script("window.__tsMode = 'fast';")
            page.goto("http://sub.test/", wait_until="load")
            page.wait_for_timeout(200)
            before = page.evaluate("!!document.querySelector('script[src*=challenges]')")
            page.fill("#f-name", "山田")
            page.wait_for_timeout(400)
            page.click("#submitBtn")
            for _ in range(80):
                if posts:
                    break
                page.wait_for_timeout(100)
            page.wait_for_timeout(200)
            done = page.evaluate("window.__done || null")
            ctx.close()
            return before, posts, done
        before, posts, done = run("ok")
        body = json.loads(posts[0]) if posts else {}
        check("補助金: 開いた時点では部品を読まず、触れた後の送信に答えを添える。ページの続きの処理も動く",
              (before, str(body.get("cf-turnstile-response", "")).startswith("GOOD-"), body.get("site"), done),
              (False, True, "subsidy", {"ok": True}))
        _, posts, done = run("blocked")
        check("補助金: 部品を読めなくても、答え無しで送る", (len(posts), "cf-turnstile-response" in (posts or ["{}"])[0], done),
              (1, False, {"ok": True}))
    finally:
        browser.close()
        pw.stop()


def test_h79_form_secret_is_trusted_but_opens_nothing_else():
    """2026-10-10 運用者「持たせて良い 鍵入れて」。別事業のサイトはサーバーでロボットよけを確かめてから、管制塔へ記録だけを
    合言葉なしで送っていた。強制に切り替えるとその記録が落ちるので、フォーム専用の合言葉（HUB_FORM_SECRET）を持たせる。
    本体の合言葉と違い、管理の操作は開けない"""
    print("\n■ ロボットよけ（管制塔）: 別事業のサイトのフォーム専用の合言葉は、フォームの信用にだけ効く")
    rec = _gas("record")
    if rec is None:
        print("  WARN  node が無いため管制塔の受付の動きは確かめられません")
        return
    bot = lambda r: [r["bot"][0][2], r["bot"][0][4], r["bot"][0][5]] if r["bot"] else []
    check("合言葉が合えば Cloudflare に問い合わせず「サーバーで確認」と記録する",
          (rec["formOk"]["r"], rec["formOk"]["fetches"], bot(rec["formOk"]), rec["formOk"]["leads"]),
          ({"ok": True}, 0, ["サーバーで確認", "ok", "client.example.jp"], 1))
    check("合言葉は台帳に残らない", FORM_FOR_TEST in rec["formOk"]["leadText"], False)
    check("違う合言葉・空の合言葉は「ページから直接」と同じ扱い（Cloudflare に確かめる）",
          (bot(rec["formWrong"])[:2], bot(rec["formEmpty"])[:2]), (["ページから直接", "none"], ["ページから直接", "none"]))
    check("フォーム専用の合言葉では管理の操作を開けない", rec["formAction"].get("error"), "unauthorized")
    enf = _gas("enforce")
    check("強制: 合言葉つきは受け付け、違う合言葉は断る",
          (enf["formOk"]["r"], enf["formOk"]["leads"], enf["formWrong"]["r"].get("ok"), enf["formWrong"]["leads"]),
          ({"ok": True}, 1, False, 0))
    no_form = _gas("enforce", form=False)
    check("強制: 合言葉を入れ忘れて配った（空で埋まった）ときに、空の合言葉で通り抜けられない",
          (no_form["formEmpty"]["r"].get("ok"), no_form["formEmpty"]["leads"]), (False, 0))
