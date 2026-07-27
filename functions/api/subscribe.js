/**
 * ニュースレター購読API（Cloudflare Pages Functions）
 * 記事下・一覧ページの購読フォーム action="/api/subscribe" を受ける。
 *
 * 必要な環境変数:
 *   RESEND_API_KEY      … Resend のAPIキー
 *   RESEND_AUDIENCE_ID  … Resend Audiences で作成した購読者リストのID
 *   LEAD_TO_EMAIL       … 購読通知の宛先（任意。設定時のみ通知メールも送る）
 *   LEAD_FROM_EMAIL     … 送信元（ドメイン認証済みアドレス）
 */
export async function onRequestPost({ request, env }) {
  const fd = await request.formData();
  const email = String(fd.get("email") || "").slice(0, 320).trim();
  const gotcha = String(fd.get("_gotcha") || "");

  if (gotcha) return Response.redirect(new URL("/thanks/?type=newsletter", request.url), 303);
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return new Response("メールアドレスの形式が正しくありません。", { status: 400 });
  }
  if (!env.RESEND_API_KEY || !env.RESEND_AUDIENCE_ID) {
    return new Response("購読設定が未完了です。恐れ入りますがお問い合わせフォームからご連絡ください。", { status: 500 });
  }

  // Resend Audiences に登録（重複はResend側で吸収される）
  const res = await fetch(`https://api.resend.com/audiences/${env.RESEND_AUDIENCE_ID}/contacts`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ email, unsubscribed: false }),
  });
  if (!res.ok) {
    return new Response("登録に失敗しました。時間をおいて再度お試しください。", { status: 502 });
  }

  // 任意: 社内通知
  if (env.LEAD_TO_EMAIL && env.LEAD_FROM_EMAIL) {
    await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from: env.LEAD_FROM_EMAIL,
        to: [env.LEAD_TO_EMAIL],
        subject: "【AI集客ラボ】ニュースレター購読が追加されました",
        text: `新しい購読者: ${email}\n送信元ページ: ${request.headers.get("referer") || "不明"}`,
      }),
    }).catch(() => {});
  }

  return Response.redirect(new URL("/thanks/?type=newsletter", request.url), 303);
}
