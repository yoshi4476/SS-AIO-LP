# -*- coding: utf-8 -*-
"""2026-10-11 運用者の承認: AI紹介チェックを、運用者が許可した別事業のサイトのページからも使えるようにした。

安全の仕組みは弱めない。サーバー同士の合言葉でロボットよけを省く案は採らず（権限の判定で止められた）、次の形にした:
- Turnstile の部品は AI集客ラボと同じもの（許可ドメインにそのサイトを足す）。答えは /api/ai-check がこれまでどおり確かめる
- 利用者のブラウザが /api/ai-check を直接呼ぶ。回数の上限は利用者の回線（CF-Connecting-IP）とメールで、これまでと同じに数える
- 許すサイトは Cloudflare の環境変数 AI_CHECK_PARTNERS（{"<Origin>": "<台帳のサイトID>"}）。公開のリポジトリにお客様の
  名前・ドメインを書かない（守秘義務の門 gates_history_h77）。CORS は * にせず、その Origin だけを返す
- そのサイトからの申し込みは記録をそのサイトの名義・silent にし、当社名義のメール（結果の送付・自動返信・後追い・測り直し）を
  出さない。測り直し・改善の案内の申し込みは受けない
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from test_gates import check, ROOT

FN = ROOT / "functions" / "api" / "ai-check.js"
GAS = ROOT / "automation" / "gas" / "contact.hub.gs"
PARTNER = "https://partner.example"           # 試しの別事業のサイト（実在の社の名前・ドメインは使わない）

HARNESS = r"""
import { pathToFileURL } from "node:url";
const [file, P] = process.argv.slice(2);
const m = await import(pathToFileURL(file).href);
let calls = [], quota = {};
globalThis.fetch = async (url, o = {}) => {
  url = String(url);
  if (url.includes("turnstile/v0/siteverify")) {
    const token = o.body.get("response") || "";
    calls.push({ kind: "turnstile", token });
    return Response.json({ success: token === "GOOD" });
  }
  if (url.startsWith("https://hub.test/")) {
    const b = JSON.parse(o.body);
    calls.push({ kind: "hub", body: b });
    if (b.action === "ai_check_quota") return Response.json(quota);
    return Response.json({ ok: true });
  }
  if (url.includes("generativelanguage.googleapis.com")) {
    calls.push({ kind: "gemini" });
    return Response.json({ candidates: [{ content: { parts: [{ text: "テスト社がおすすめです" }] },
      groundingMetadata: { groundingChunks: [{ web: { uri: "https://r.test/x", title: "example.co.jp" } }], webSearchQueries: ["q"] } }] });
  }
  calls.push({ kind: "other", url });
  return new Response("", { status: 404 });
};
const base = { TURNSTILE_SECRET: "s", TURNSTILE_SITEKEY: "k", GEMINI_API_KEY: "g", GAS_WEBHOOK_URL: "https://hub.test/exec", GAS_SHARED_SECRET: "x" };
const env = { ...base, AI_CHECK_PARTNERS: JSON.stringify({ [P]: "partner-x" }) };
const body = { industry: "zeirishi", area: "大阪市北区", company: "テスト社", site: "https://example.co.jp", name: "山田",
               email: "a@example.co.jp", recheck: "1", optin: "1" };
async function post(origin, token, q, e) {
  calls = []; quota = { ok: true, allowed: true, used: 0, perEmail: 3, perIpDay: 2, reason: "", ...(q || {}) };
  const h = { "content-type": "application/json", "CF-Connecting-IP": "198.51.100.7" };
  if (origin) h.Origin = origin;
  const req = new Request("https://ai.7senses.co.jp/api/ai-check", { method: "POST", headers: h,
    body: JSON.stringify({ ...body, ...(token ? { "cf-turnstile-response": token } : {}) }) });
  const r = await m.onRequestPost({ request: req, env: e || env, waitUntil: () => {} });
  const hub = calls.filter((c) => c.kind === "hub").map((c) => c.body);
  return { status: r.status, acao: r.headers.get("Access-Control-Allow-Origin"), json: await r.json(),
           turnstile: calls.filter((c) => c.kind === "turnstile").length, gemini: calls.filter((c) => c.kind === "gemini").length,
           quota: hub.find((b) => b.action === "ai_check_quota") || null, log: hub.find((b) => b.action === "ai_check_log") || null,
           record: hub.find((b) => !b.action) || null };
}
async function options(origin, e) {
  const h = { "Access-Control-Request-Method": "POST" };
  if (origin) h.Origin = origin;
  let nexted = false;
  const r = await m.onRequestOptions({ request: new Request("https://ai.7senses.co.jp/api/ai-check", { method: "OPTIONS", headers: h }),
    env: e || env, next: async () => { nexted = true; return new Response(null, { status: 405 }); } });
  return { status: r.status, acao: r.headers.get("Access-Control-Allow-Origin"), methods: r.headers.get("Access-Control-Allow-Methods"), nexted };
}
console.log(JSON.stringify({
  pNoToken: await post(P, ""),
  pBadToken: await post(P, "BAD"),
  pOk: await post(P, "GOOD"),
  pIpLimit: await post(P, "GOOD", { allowed: false, reason: "ip" }),
  pEmailLimit: await post(P, "GOOD", { allowed: false, reason: "email", used: 3 }),
  labOk: await post("", "GOOD"),
  labNoToken: await post("", ""),
  evilOk: await post("https://evil.example", "GOOD"),
  lookalike: await post(P + ".evil.example", "GOOD"),
  unset: await post(P, "GOOD", null, base),
  broken: await post(P, "GOOD", null, { ...base, AI_CHECK_PARTNERS: "{not json" }),
  proto: await post("__proto__", "GOOD"),
  optP: await options(P),
  optEvil: await options("https://evil.example"),
  optNone: await options(""),
  optUnset: await options(P, base),
}));
"""


def run_harness(path=FN):
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "harness.mjs"
        h.write_text(HARNESS, encoding="utf-8")
        # 関数のファイルは ESM として読む（package.json の type に頼らないよう .mjs に写す）
        f = Path(d) / "ai-check.mjs"
        f.write_text(Path(path).read_text(encoding="utf-8"), encoding="utf-8")
        r = subprocess.run([node, str(h), str(f), PARTNER], capture_output=True, text=True, encoding="utf-8", timeout=60)
    if r.returncode != 0:
        raise AssertionError("検査が動かない: " + r.stderr.strip()[-300:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_h84_ai_check_from_partner_site_keeps_guards():
    print("\n■ 履歴H84: 別事業のサイトからの AI紹介チェック（ロボットよけ・回数の上限・名義・CORS）")
    o = run_harness()
    if o is None:
        print("  SKIP  node が無いため飛ばす")
        return
    # 1. 許すのは、環境変数で許可したサイトだけ
    check("CORS: 許可したサイトにだけ許可を返す（POST・答えの無いときも）", (o["pOk"]["acao"], o["pNoToken"]["acao"]), (PARTNER, PARTNER))
    check("CORS: ほかの Origin・Origin なし・似せたドメイン・__proto__ には許可を返さない",
          (o["evilOk"]["acao"], o["labOk"]["acao"], o["lookalike"]["acao"], o["proto"]["acao"]), (None, None, None, None))
    check("CORS: 環境変数が無い・壊れているときは、どのサイトにも許可を返さない（AI集客ラボと同じ扱い）",
          (o["unset"]["acao"], o["broken"]["acao"], (o["unset"]["record"] or {}).get("site")), (None, None, "ai-lab"))
    check("CORS: 事前の問い合わせは許可したサイトにだけ答え、ほかは次の処理へ渡す（これまでどおり）",
          ((o["optP"]["status"], o["optP"]["acao"], o["optP"]["methods"], o["optP"]["nexted"]),
           (o["optEvil"]["nexted"], o["optEvil"]["acao"]), (o["optNone"]["nexted"], o["optNone"]["acao"]), o["optUnset"]["nexted"]),
          ((204, PARTNER, "POST", False), (True, None), (True, None), True))
    # 2. 許可したサイトからでも、ロボットよけの答えが無ければ断る（AI にも台帳にも届かない）
    for k, what in (("pNoToken", "無い"), ("pBadToken", "不正な")):
        x = o[k]
        check(f"ロボットよけ: 許可したサイトからでも答えが{what}ときは断る（403・台帳と AI を呼ばない）",
              (x["status"], x["turnstile"], x["quota"], x["gemini"]), (403, 1, None, 0))
    check("ロボットよけ: AI集客ラボからも、これまでどおり答えが無ければ断る", o["labNoToken"]["status"], 403)
    # 3. 回数の上限は利用者の回線とメールで数える（同じ台帳）
    q = o["pOk"]["quota"] or {}
    check("回数: 許可したサイトからの申し込みも、利用者の回線（CF-Connecting-IP）とメールで台帳に聞く",
          (q.get("ip"), q.get("email")), ("198.51.100.7", "a@example.co.jp"))
    check("回数: 回線の上限を超えたら断る（429・AI を呼ばない）",
          (o["pIpLimit"]["status"], o["pIpLimit"]["json"].get("limit"), o["pIpLimit"]["gemini"]), (429, "ip", 0))
    check("回数: メールの上限を超えたら断る（429・AI を呼ばない）",
          (o["pEmailLimit"]["status"], o["pEmailLimit"]["json"].get("limit"), o["pEmailLimit"]["gemini"]), (429, "email", 0))
    # 4. 許可したサイトからの呼び出しは当社名義のメールを出さない
    r = o["pOk"]["record"] or {}
    check("名義: 許可したサイトからの記録は、そのサイトの名義・silent（管制塔の通知・自動返信を止める）",
          (r.get("site"), r.get("silent"), (r.get("data") or {}).get("site")), ("partner-x", True, "partner-x"))
    lg = o["pOk"]["log"] or {}
    check("名義: 許可したサイトからは測り直し・改善の案内の申し込みを受けない", (lg.get("recheck"), lg.get("optin")), (False, False))
    r, lg = o["labOk"]["record"] or {}, o["labOk"]["log"] or {}
    check("これまでどおり: AI集客ラボの記録は ai-lab・silent なし・申し込みはそのまま・結果を返す",
          (r.get("site"), "silent" in r, lg.get("recheck"), lg.get("optin"), o["labOk"]["status"], len(o["labOk"]["json"].get("results", []))),
          ("ai-lab", False, True, True, 200, 3))
    check("これまでどおり: ほかの Origin は AI集客ラボと同じ扱い",
          ((o["evilOk"]["record"] or {}).get("site"), "silent" in (o["evilOk"]["record"] or {})), ("ai-lab", False))
    gs = GAS.read_text(encoding="utf-8")
    form = gs[gs.find("function form_("):gs.find("function unsubscribe_(")]
    check("名義: 管制塔は silent のとき通知と自動返信を出さない", bool(re.search(r"if \(!silent\) \{[\s\S]*?leadNotify_[\s\S]*?leadReply_", form)), True)
    fu = gs[gs.find("function followUp()"):]
    check("名義: 後追いメールは AI集客ラボの行だけ（ほかのサイトの行は対象外）", "if (!aiLab[String(r[1] || '').trim()]) continue;" in fu[:3000], True)
    # 5. ほかの操作は開けない
    js = FN.read_text(encoding="utf-8")
    check("ほかの操作は開けない: AI紹介チェックが台帳に頼むのは回数の確認と記録だけ",
          sorted(set(re.findall(r'action: "(\w+)"', js))), ["ai_check_log", "ai_check_quota"])
    others = [p.name for p in (ROOT / "functions").rglob("*.js") if p != FN and "AI_CHECK_PARTNERS" in p.read_text(encoding="utf-8")]
    check("ほかの操作は開けない: 許可したサイトを読むのは AI紹介チェックの受け口だけ", others, [])
    check("CORS は * にしない", bool(re.search(r"Access-Control-Allow-Origin\"?\s*[,:]\s*\"\*\"", js)), False)
    wf = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    check("許可したサイトの一覧を、配信のたびに Cloudflare に入れる（鍵の一覧にも載せる）",
          ("AI_CHECK_PARTNERS: ${{ secrets.AI_CHECK_PARTNERS }}" in wf and "TURNSTILE_SECRET AI_CHECK_PARTNERS; do" in wf,
           '"AI_CHECK_PARTNERS"' in (ROOT / "scripts" / "set_secrets.py").read_text(encoding="utf-8")), (True, True))


def test_h84_detector_catches_wildcard_cors():
    """検出器の確認: 何でも許す CORS（*）に変えた写しは、上の検査で落ちること"""
    src = FN.read_text(encoding="utf-8")
    bad = src.replace("return partner ? withCors(res, partner.origin) : res;", 'return withCors(res, "*");')
    if bad == src or shutil.which("node") is None:
        print("  SKIP  写しを作れない・node が無い")
        return
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "ai-check.js"
        p.write_text(bad, encoding="utf-8")
        o = run_harness(p)
    check("検出器: 何でも許す CORS（*）の写しを拾う", (o["evilOk"]["acao"], o["labOk"]["acao"]), ("*", "*"))
