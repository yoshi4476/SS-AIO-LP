/**
 * ニュースレター購読API（Cloudflare Pages Functions）
 * 記事下・一覧ページの購読フォーム action="/api/subscribe" を受ける。
 *
 * 登録は本人の確認を挟む（2026-10-24 の点検）。以前は入れたアドレスをそのまま購読者リストに入れていたため、
 * 他人のアドレスを確認なしで何件でも登録でき、同意のない人へ配信が届いた（特定電子メール法）。
 * 1. フォームの送信（POST email）… 確認のメールを送るだけ（宛先ごと・回線ごと・全体の回数に上限）
 * 2. メールのリンク（GET ?t=）… 「登録を確定する」ボタンのページを返す。メールの安全確認の仕組みがリンクを
 *    自動で開いても登録されないよう、確定はボタンの送信（POST t）で行う
 * 3. 確定（POST t）… 署名と期限（3日）を確かめて、購読者リストに入れる
 *
 * 必要な環境変数:
 *   RESEND_API_KEY      … Resend のAPIキー
 *   RESEND_AUDIENCE_ID  … Resend Audiences で作成した購読者リストのID
 *   LEAD_FROM_EMAIL     … 送信元（ドメイン認証済みアドレス）。確認のメールに使う
 *   LEAD_TO_EMAIL       … 購読通知の宛先（任意。設定時のみ通知メールも送る）
 *   GAS_SHARED_SECRET   … 確認のリンクの署名と、管制塔の回数の上限に使う
 *
 * ロボットよけ（Turnstile）は functions/_turnstile.js。結果は管制塔の「ロボットよけ」タブに残る。
 */
import { FIELD, REFUSAL, verify, refuse, log } from "../_turnstile.js";
import { sign, read, digest, ipKey, rateHit } from "../_sign.js";

const PURPOSE = "ss-subscribe";
const TTL_MS = 3 * 86400 * 1000;
const EMAIL_RX = /^[^\s@]{1,64}@[^\s@]+\.[^\s@]+$/;
const text = (body, status) => new Response(body, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });

export async function onRequestPost(context) {
  const { request, env } = context;
  // フォーム以外の本文で例外になると Cloudflare の生の500が返る（2026-09-02 に lead.js で起きたのと同じ穴）
  let fd;
  try {
    fd = await request.formData();
  } catch (_) {
    return text("フォーム形式で送信してください。", 400);
  }
  if (fd.get("t")) return confirm(context, String(fd.get("t")));

  const email = String(fd.get("email") || "").slice(0, 320).trim();
  const gotcha = String(fd.get("_gotcha") || "");
  if (gotcha) return Response.redirect(new URL("/thanks/?type=newsletter_confirm", request.url), 303);
  if (!EMAIL_RX.test(email) || email.length > 120) return text("メールアドレスの形式が正しくありません。", 400);

  const ip = request.headers.get("CF-Connecting-IP") || "";
  const ts = await verify(env, fd.get(FIELD), ip);
  const refused = refuse("subscribe", ts, email);
  const done = log(env, "ai-lab", "newsletter", ts, email, refused);
  if (context.waitUntil) context.waitUntil(done);
  if (refused) return text(REFUSAL, 403);
  if (!env.RESEND_API_KEY || !env.RESEND_AUDIENCE_ID || !env.LEAD_FROM_EMAIL || !env.GAS_SHARED_SECRET) {
    return text("購読設定が未完了です。恐れ入りますがお問い合わせフォームからご連絡ください。", 500);
  }

  // 確認のメールも他人のアドレスへ送れるので、回数に上限をかける。数えられないときは送らない（購読は急ぎではない）
  const rate = await rateHit(env, [
    { key: "sub_mail_" + await digest(email.toLowerCase()), limit: 2, sec: 21600 },
    { key: "sub_ip_" + await digest(ipKey(ip)), limit: 5, sec: 21600 },
    { key: "sub_all", limit: 60, sec: 3600 },
  ]);
  if (rate.allowed !== true) {
    return text("ただいま登録を受け付けられません。時間をおいてもう一度お試しください。", rate.allowed === false ? 429 : 503);
  }

  const link = new URL("/api/subscribe", request.url);
  link.searchParams.set("t", await sign(env.GAS_SHARED_SECRET, PURPOSE, { m: email }, TTL_MS));
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: env.LEAD_FROM_EMAIL,
      to: [email],
      subject: "【AI集客ラボ】ニュースレター登録の確認",
      text: ["AI集客ラボのニュースレターへの登録のお申し込みを受け付けました。",
             "下のリンクを開き、「登録を確定する」を押すと登録が完了します（3日間有効）。", "", link.toString(), "",
             "お心当たりがない場合は、このメールを破棄してください。押さなければ登録されず、今後メールは届きません。", "",
             "セブンセンシズ株式会社 AI集客ラボ", "https://ai.7senses.co.jp/"].join("\n"),
    }),
  });
  if (!res.ok) return text("確認のメールを送れませんでした。時間をおいて再度お試しください。", 502);
  return Response.redirect(new URL("/thanks/?type=newsletter_confirm", request.url), 303);
}

// メールのリンクを開いたとき。登録はせず、確定のボタンだけを出す
export async function onRequestGet({ request, env }) {
  const t = new URL(request.url).searchParams.get("t") || "";
  const ok = Boolean(await read(env.GAS_SHARED_SECRET, PURPOSE, t));
  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const body = ok
    ? `<h1>ニュースレターの登録を確定します</h1><p>下のボタンを押すと登録が完了します。</p>
<form method="post" action="/api/subscribe"><input type="hidden" name="t" value="${esc(t)}"><button type="submit">登録を確定する</button></form>`
    : `<h1>リンクの期限が切れているか、正しくありません</h1><p>お手数ですが、<a href="/">AI集客ラボ</a>の購読フォームからもう一度お申し込みください。</p>`;
  return new Response(`<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>ニュースレターの登録｜AI集客ラボ</title>
<style>body{font-family:system-ui,"Hiragino Sans","Yu Gothic",sans-serif;max-width:560px;margin:12vh auto;padding:0 16px;color:#1d2433;line-height:1.8}
h1{font-size:1.3rem}button{font:inherit;font-weight:700;background:#1b4fa0;color:#fff;border:0;border-radius:8px;padding:.8rem 1.6rem;cursor:pointer}
button:focus-visible{outline:3px solid #f5b400;outline-offset:2px}a{color:#1b4fa0}</style></head><body>${body}</body></html>`,
    { status: ok ? 200 : 400, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
                                        "Referrer-Policy": "no-referrer" } });
}

async function confirm(context, t) {
  const { request, env } = context;
  const p = await read(env.GAS_SHARED_SECRET, PURPOSE, t);
  if (!p || !EMAIL_RX.test(String(p.m || ""))) {
    return text("リンクの期限が切れているか、正しくありません。購読フォームからもう一度お申し込みください。", 400);
  }
  if (!env.RESEND_API_KEY || !env.RESEND_AUDIENCE_ID) return text("購読設定が未完了です。", 500);
  // Resend Audiences に登録（重複はResend側で吸収される）
  const res = await fetch(`https://api.resend.com/audiences/${env.RESEND_AUDIENCE_ID}/contacts`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ email: p.m, unsubscribed: false }),
  });
  if (!res.ok) return text("登録に失敗しました。時間をおいて再度お試しください。", 502);
  // 任意: 社内通知（本人が確定した分だけなので、外から数を増やせない）
  if (env.LEAD_TO_EMAIL && env.LEAD_FROM_EMAIL) {
    const sent = fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ from: env.LEAD_FROM_EMAIL, to: [env.LEAD_TO_EMAIL],
        subject: "【AI集客ラボ】ニュースレター購読が追加されました", text: `新しい購読者（本人が確認済み）: ${p.m}` }),
    }).catch(() => {});
    if (context.waitUntil) context.waitUntil(sent);
  }
  return Response.redirect(new URL("/thanks/?type=newsletter", request.url), 303);
}
