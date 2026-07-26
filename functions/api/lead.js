/**
 * リード受付API（Cloudflare Pages Functions）
 * 全フォーム（LP無料相談 / お問い合わせ / 資料DL）の action="/api/lead" を受ける。
 *
 * 必要な環境変数（Cloudflare Pages > Settings > Environment variables）:
 *   RESEND_API_KEY   … Resend (https://resend.com) のAPIキー
 *   LEAD_TO_EMAIL    … 通知の宛先（例: info@7senses.co.jp）
 *   LEAD_FROM_EMAIL  … 送信元（Resendでドメイン認証したアドレス）
 */
export async function onRequestPost({ request, env }) {
  const data = {};
  const fd = await request.formData();
  for (const [k, v] of fd) data[k] = String(v).slice(0, 2000);

  // ハニーポット（botはこの不可視フィールドを埋める）
  if (data._gotcha) return Response.redirect(new URL("/thanks/", request.url), 303);

  for (const k of ["name", "company", "email"]) {
    if (!data[k] || !data[k].trim()) return new Response("必須項目が未入力です。", { status: 400 });
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email)) {
    return new Response("メールアドレスの形式が正しくありません。", { status: 400 });
  }

  if (!env.RESEND_API_KEY || !env.LEAD_TO_EMAIL || !env.LEAD_FROM_EMAIL) {
    return new Response("送信設定が未完了です。恐れ入りますが 06-4305-7547 までお電話ください。", { status: 500 });
  }

  const label = data.form_type || "お問い合わせ";
  const lines = Object.entries(data)
    .filter(([k]) => !k.startsWith("_"))
    .map(([k, v]) => `${k}: ${v}`)
    .join("\n");

  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${env.RESEND_API_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({
      from: env.LEAD_FROM_EMAIL,
      to: [env.LEAD_TO_EMAIL],
      reply_to: data.email,
      subject: `【AI集客ラボ】${label}: ${data.company} ${data.name}様`,
      text: `AI集客ラボのフォームから${label}が届きました。\n\n${lines}\n\n---\n送信元ページ: ${request.headers.get("referer") || "不明"}`,
    }),
  });

  if (!res.ok) {
    return new Response("送信に失敗しました。時間をおいて再度お試しいただくか、06-4305-7547 までお電話ください。", { status: 502 });
  }
  return Response.redirect(new URL("/thanks/", request.url), 303);
}
