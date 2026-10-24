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
 *
 * ロボットよけ（Turnstile）は functions/_turnstile.js。答えを確かめ、結果を管制塔への転送に添える（台帳には残さない）。
 */
import { ENFORCE, FIELD, REFUSAL, verify, refuse, log } from "../_turnstile.js";
import { readAudit } from "../_audit_checks.js";

// 管制塔の受付が別の意味に読む項目は、フォームから受け取らない（自動返信の本文・通知の止め方を外から決めさせない）
const RESERVED = ["audit", "diagnosis", "secret", "silent", "site", "type", "audit_url", "audit_score", "audit_grade", "audit_fixes"];

// ページの部品（site.js）が読むサイトキーと、断るかどうか（公開してよい値だけ返す）
export async function onRequestGet({ env }) {
  return Response.json({ turnstile: env.TURNSTILE_SECRET && env.TURNSTILE_SITEKEY ? env.TURNSTILE_SITEKEY : "", enforce: ENFORCE },
    { headers: { "Cache-Control": "public, max-age=300" } });
}

export async function onRequestPost(context) {
  const { request, env } = context;
  const data = {};
  let fd;
  try {
    fd = await request.formData();
  } catch (_) {
    return new Response("フォーム形式で送信してください。", { status: 400 });
  }
  // ロボットよけの答え（最長2048字）は切らずに別に持ち、台帳へは送らない
  for (const [k, v] of fd) if (k !== FIELD && !RESERVED.includes(k)) data[k] = String(v).slice(0, 2000);
  const token = String(fd.get(FIELD) || "");

  // ハニーポット（botはこの不可視フィールドを埋める）
  if (data._gotcha) return Response.redirect(new URL("/thanks/", request.url), 303);

  for (const k of ["name", "company", "email"]) {
    if (!data[k] || !data[k].trim()) return new Response("必須項目が未入力です。", { status: 400 });
  }
  // 長さも見る。管制塔は80字で切るため、長いアドレスは管制塔で弾かれて予備の送り方（Resend）へ回り、回数の上限なく送らせられた
  const email = data.email.trim();
  if (!/^[^\s@]{1,64}@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 80) {
    return new Response("メールアドレスの形式が正しくありません。", { status: 400 });
  }
  data.email = email;
  // お名前は自動返信の宛名になる。長い文や URL を入れて、当社名義のメールに好きな文を載せさせない
  data.name = data.name.trim();
  if (data.name.length > 50 || /:\/\/|www\.|https?:/i.test(data.name)) {
    return new Response("お名前は50字以内で、URL を含めずにご入力ください。", { status: 400 });
  }
  // AI紹介チェックの結果メールは /api/ai-check だけが作る（この入口から種別を名乗らせない）
  if (String(data.form_type || "").includes("AI紹介チェック")) {
    return new Response("このフォームからは送れない種別です。", { status: 400 });
  }

  const ts = await verify(env, token, request.headers.get("CF-Connecting-IP") || "");
  if (refuse("lead", ts, data.email)) {
    const done = log(env, "ai-lab", String(data.form_type || "").slice(0, 40), ts, data.email, true);
    if (context.waitUntil) context.waitUntil(done);
    return new Response(REFUSAL, { status: 403, headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }

  const hasGas = Boolean(env.GAS_WEBHOOK_URL);
  const hasResend = Boolean(env.RESEND_API_KEY && env.LEAD_TO_EMAIL && env.LEAD_FROM_EMAIL);
  if (!hasGas && !hasResend) {
    return new Response("送信設定が未完了です。恐れ入りますが 06-4305-7547 までお電話ください。", { status: 500 });
  }

  // 参照元が無い送信（ブラウザが送らない設定・自動の疎通確認）は空で送る。「不明」と入れると台帳にそのまま残った（2026-10-10）
  const referer = request.headers.get("referer") || "";
  const ft = String(data.form_type || "");
  // 資料ダウンロードの後は、資料の案内と次の一歩のページへ。
  // 以前は「2営業日以内に担当者よりご連絡」と出ていた（資料はメールで届くのに）（2026-10-08）
  const thanks = new URL(ft.includes("資料") ? "/thanks/?type=download" : "/thanks/", request.url);

  // A) Google Apps Script（スプレッドシート台帳＋Gmail通知）
  if (hasGas) {
    // 管制塔の受付（contact.hub.gs の form_）は type が無いと contact として本文を必須にする。
    // LPヒーローと資料DLは本文欄が無いため「必須項目が入力されていません」で弾かれ、
    // 台帳に残っていなかった。種別を form_type から決め、本文が無ければ相談テーマか種別で補う
    // サイト診断の結果（URL・点数・直し方）が付いていれば site_audit。
    // これが無いと「無料診断」の汎用返信になり、画面で約束した直し方がメールに入らなかった
    // 診断の結果は /api/audit の署名を確かめたものだけ使い、直し方の文は決まった文から作り直す（利用者が送った文を載せない）
    const audit = await readAudit(env.GAS_SHARED_SECRET, data.audit_token);
    const type = audit ? "site_audit"
      : ft.includes("資料") ? "download"
      : (ft.includes("診断") || ft.includes("結果送付")) ? "diagnosis" : "contact";
    const hub = { ...data, site: "ai-lab", type };
    delete hub.audit_token;
    if (audit) hub.audit = audit;
    if (!String(hub.message || "").trim()) hub.message = data.topic || ft || "（本文なし）";
    // 業種別のページ（/lp/medical/ など）から来た相談は、業種を本文の末尾に添える（台帳の列は増やさない）
    const ind = String(data.industry || "").replace(/\s+/g, " ").trim().slice(0, 30);
    if (ind) hub.message = String(hub.message) + "\n\n【業種】" + ind + "（業種別のページから）";
    try {
      const gas = await fetch(env.GAS_WEBHOOK_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // turnstile は管制塔の「ロボットよけ」タブにだけ残る（台帳の行には入らない）
        body: JSON.stringify({ secret: env.GAS_SHARED_SECRET || "", site: "ai-lab", data: hub, referer, turnstile: ts }),
      });
      // GASは失敗時も200で {ok:false} を返すため、本文まで確認する
      const out = await gas.json().catch(() => ({}));
      if (gas.ok && out.ok) return Response.redirect(thanks, 303);
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
    .filter(([k]) => !k.startsWith("_") && k !== "audit_token")
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
      text: `AI集客ラボのフォームから${label}が届きました。\n\n${lines}\n\n---\n送信元ページ: ${referer || "（ブラウザが送らなかった）"}`,
    }),
  });

  if (!res.ok) {
    return new Response("送信に失敗しました。時間をおいて再度お試しいただくか、06-4305-7547 までお電話ください。", { status: 502 });
  }
  return Response.redirect(thanks, 303);
}
