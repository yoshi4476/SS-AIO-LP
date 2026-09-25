/**
 * リード受付API（Cloudflare Pages Functions）
 * 全フォーム（LP無料相談 / お問い合わせ / 資料DL）の action="/api/lead" を受ける。
 *
 * 送信経路は2系統。GASを設定していればそちらを優先し、失敗時はResendへ自動フォールバックする。
 *
 * A) Google Apps Script（推奨・無料 / スプレッドシート台帳に自動蓄積）
 *   GAS_WEBHOOK_URL    … ウェブアプリのURL（/exec で終わる）
 *   GAS_SHARED_SECRET  … contact.gs の SHARED_SECRET と同じ文字列
 *
 * B) Resend（フォールバック）
 *   RESEND_API_KEY / LEAD_TO_EMAIL / LEAD_FROM_EMAIL
 */
export async function onRequestPost({ request, env }) {
  const data = {};
  let fd;
  try {
    fd = await request.formData();
  } catch (_) {
    return new Response("フォーム形式で送信してください。", { status: 400 });
  }
  for (const [k, v] of fd) data[k] = String(v).slice(0, 2000);

  // ハニーポット（botはこの不可視フィールドを埋める）
  if (data._gotcha) return Response.redirect(new URL("/thanks/", request.url), 303);

  for (const k of ["name", "company", "email"]) {
    if (!data[k] || !data[k].trim()) return new Response("必須項目が未入力です。", { status: 400 });
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.email)) {
    return new Response("メールアドレスの形式が正しくありません。", { status: 400 });
  }

  const hasGas = Boolean(env.GAS_WEBHOOK_URL);
  const hasResend = Boolean(env.RESEND_API_KEY && env.LEAD_TO_EMAIL && env.LEAD_FROM_EMAIL);
  if (!hasGas && !hasResend) {
    return new Response("送信設定が未完了です。恐れ入りますが 06-4305-7547 までお電話ください。", { status: 500 });
  }

  const referer = request.headers.get("referer") || "不明";

  // A) Google Apps Script（スプレッドシート台帳＋Gmail通知）
  if (hasGas) {
    // 管制塔の受付（contact.hub.gs の form_）は type が無いと contact として本文を必須にする。
    // LPヒーローと資料DLは本文欄が無いため「必須項目が入力されていません」で弾かれ、
    // 台帳に残っていなかった。種別を form_type から決め、本文が無ければ相談テーマか種別で補う
    const ft = String(data.form_type || "");
    const type = ft.includes("資料") ? "download"
      : (ft.includes("診断") || ft.includes("結果送付")) ? "diagnosis" : "contact";
    const hub = { ...data, site: "ai-lab", type };
    if (!String(hub.message || "").trim()) hub.message = data.topic || ft || "（本文なし）";
    try {
      const gas = await fetch(env.GAS_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ secret: env.GAS_SHARED_SECRET || "", site: "ai-lab", data: hub, referer }),
      });
      // GASは失敗時も200で {ok:false} を返すため、本文まで確認する
      const out = await gas.json().catch(() => ({}));
      if (gas.ok && out.ok) return Response.redirect(new URL("/thanks/", request.url), 303);
    } catch (_) {
      // 通信失敗時は下のResendへフォールバックする
    }
    if (!hasResend) {
      return new Response("送信に失敗しました。時間をおいて再度お試しいただくか、06-4305-7547 までお電話ください。", { status: 502 });
    }
  }

  // B) Resend（フォールバック）
  // 件名用サニタイズ（改行・長大入力による件名破壊/インジェクション防止）
  const subj = (s) => String(s || "").replace(/[\r\n]+/g, " ").slice(0, 80);
  const label = subj(data.form_type) || "お問い合わせ";
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
      subject: `【AI集客ラボ】${label}: ${subj(data.company)} ${subj(data.name)}様`,
      text: `AI集客ラボのフォームから${label}が届きました。\n\n${lines}\n\n---\n送信元ページ: ${referer}`,
    }),
  });

  if (!res.ok) {
    return new Response("送信に失敗しました。時間をおいて再度お試しいただくか、06-4305-7547 までお電話ください。", { status: 502 });
  }
  return Response.redirect(new URL("/thanks/", request.url), 303);
}
