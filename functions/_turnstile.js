/**
 * ロボットよけ（Cloudflare Turnstile）の確かめ。/api/lead と /api/subscribe が使う（ai-check.js は自前で確かめている）。
 *
 * 機械で大量に送られると、問い合わせの台帳が埋まり、管制塔の自動返信で他人のアドレスへ当社のメールを出させられる。
 * MailApp の1日の上限を食い切ると、本物の問い合わせの通知・自動返信まで止まる（2026-10-10 運用者の承認）。
 *
 * ページの部品（site.js）はフォームに触れた時点で読み込み、答えを cf-turnstile-response として一緒に送る。
 * ここで Cloudflare に確かめ、結果は管制塔の「ロボットよけ」タブに残る（lead.js は転送の本文に添え、subscribe.js は bot_log で送る）。
 * 鍵は Cloudflare Pages の TURNSTILE_SITEKEY / TURNSTILE_SECRET（deploy.yml が入れる）。片方でも無ければ確かめない。
 * ファイル名の先頭の _ は、ここが受付の URL にならないことを示す（onRequest を持たないので経路は作られない）。
 */

// 断るかどうか。false の間は確かめて記録するだけで、断らない。
// 本物のブラウザで ok が記録されたのを確かめてから true にする（記録は python scripts/turnstile_status.py で読む）
export const ENFORCE = { lead: false, subscribe: false };

export const REFUSAL = "ロボットでないことの確認ができませんでした。ページを読み込み直してもう一度お送りいただくか、"
  + "06-4305-7547 までお電話ください。";

export const FIELD = "cf-turnstile-response";

/** 週次の疎通確認（lead_probe.py）のアドレス。断らない（ページを通らないので答えを持たない） */
export function isProbe(email) {
  return /@pipeline-check\.invalid$/i.test(String(email || ""));
}

/** result: ok / none（答えが無い）/ invalid / error（確かめられない）/ unset（鍵が無い） */
export async function verify(env, token, ip) {
  if (!env.TURNSTILE_SECRET || !env.TURNSTILE_SITEKEY) return { result: "unset" };
  const t = String(token || "").trim();
  if (!t) return { result: "none" };
  if (t.length > 2048) return { result: "invalid", codes: "format" };
  const form = new FormData();
  form.append("secret", env.TURNSTILE_SECRET);
  form.append("response", t);
  if (ip) form.append("remoteip", ip);
  try {
    const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: form });
    if (r.status >= 500) return { result: "error", codes: "http" + r.status };
    const j = await r.json();
    return { result: j.success ? "ok" : "invalid", host: String(j.hostname || ""), codes: (j["error-codes"] || []).join(",") };
  } catch (_) {
    return { result: "error", codes: "fetch" };
  }
}

/** 断るか。確かめられない（error・unset）ときは断らない（Cloudflare の不調で本物の問い合わせを落とさない） */
export function refuse(kind, ts, email) {
  return Boolean(ENFORCE[kind]) && !isProbe(email) && (ts.result === "none" || ts.result === "invalid");
}

// 断った送信を管制塔へ記録するのは、この受付の実体1つにつき10分で20件まで（大量に送られたときに管制塔を巻き込まない）
let win = 0, sent = 0;

/** 管制塔の「ロボットよけ」タブへ1行。失敗しても受付は止めない */
export async function log(env, site, type, ts, email, refused) {
  if (!env.GAS_WEBHOOK_URL || !ts || ts.result === "unset") return;
  if (refused) {
    const now = Date.now();
    if (now - win > 600000) { win = now; sent = 0; }
    if (++sent > 20) return;
  }
  try {
    await fetch(env.GAS_WEBHOOK_URL, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "bot_log", secret: env.GAS_SHARED_SECRET || "", site, type, turnstile: ts,
        probe: isProbe(email), refused: Boolean(refused) }),
    });
  } catch (_) { /* 記録より受付が先 */ }
}
