/**
 * 「AIにどう紹介されているか」無料チェック（/tools/ai-check/ から呼ぶ）
 *
 * 地域と業種で3問を Gemini（Google検索つき）に聞き、答えの出典に御社のサイトが入っているか、
 * 回答に社名が出ているか、代わりに何が出典になっているかを返す。
 * 連絡先は既存の問い合わせと同じ管制塔（GAS）の台帳に記録する。
 *
 * 費用: 検索つきの Gemini は無料枠では使えない（公式の料金表で確認・2026-10-04）。有料プランの
 * 「月5,000回まで検索料0円」に収めるため、実際に行われた検索の回数を台帳に残し、月5,000回で受付を止める。
 * 架空のメールアドレスでの連続申し込みを止めるため、同じ回線（IP）からは1日2回まで、ロボットよけ（Turnstile）を通す。
 * 台帳に届かないときは受け付けない（上限が効かないまま AI を呼ばない）。
 * 必要な環境変数: GEMINI_API_KEY（必須）、GEMINI_MODEL（任意）、GAS_WEBHOOK_URL / GAS_SHARED_SECRET（台帳・必須）、
 *   TURNSTILE_SITEKEY / TURNSTILE_SECRET（ロボットよけ。両方そろうと有効）
 */
const WORDS = {
  dental: "歯医者", clinic: "クリニック", fudosan: "不動産会社", koumuten: "工務店", reform: "リフォーム会社",
  zeirishi: "税理士", sharoushi: "社労士", gyousei: "行政書士", shihou: "司法書士", bengoshi: "弁護士",
};
const LP = { dental: "medical", clinic: "medical", fudosan: "fudosan", koumuten: "koumuten", reform: "koumuten",
  zeirishi: "shigyou", sharoushi: "shigyou", gyousei: "shigyou", shihou: "shigyou", bengoshi: "shigyou" };
// 予約・比較・紹介のサイト（調査 industry_ai_sources.py で多かったもの）
const PORTAL = /epark|tokyo-doctors|iqrafudosan|ieagent|ielove|town-life|chintai|homemate|eheya|yeay|ieuri|mansion-navi|t23m-navi|sumaity|haisha-yoyaku|caloo|byoinnavi|doctorsfile|qlife|medicaldoc|fdoc\.jp|hospita|clinic\.mynavi|jidv|haisha-doc|ekiten|teech|proreco|shika-pro|mrso|suumo|homes\.co\.jp|athome|ieul|home4u|sumai-step|rehome-navi|homepro|nuri-kae|reform-guide|hapisumu|meetsmore|zehitomo|biz\.ne\.jp|imitsu|zeiri4|bengo4|minnano-zeirishi|i-sozoku|all-senmonka|tabelog|hotpepper|retty/;

const norm = (s) => String(s || "").toLowerCase().replace(/[\s　・（）()「」]/g, "");
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, "").toLowerCase(); } catch (_) { return ""; } };

async function realHost(uri, title) {
  // Gemini の出典は中継アドレス。題がドメインならそれを使い、違えば行き先を1回だけ見る
  if (/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(String(title || "").trim())) return String(title).trim().toLowerCase().replace(/^www\./, "");
  try {
    const r = await fetch(uri, { method: "HEAD", redirect: "manual" });
    return host(r.headers.get("location") || uri);
  } catch (_) { return host(uri); }
}

async function ask(env, q) {
  const model = env.GEMINI_MODEL || "gemini-3.6-flash";
  const r = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${env.GEMINI_API_KEY}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contents: [{ parts: [{ text: q }] }], tools: [{ google_search: {} }] }),
  });
  if (r.status === 429) throw new Error("quota");
  if (!r.ok) throw new Error("http" + r.status);
  const d = await r.json();
  const c = (d.candidates || [])[0] || {};
  const text = ((c.content || {}).parts || []).map((p) => p.text || "").join("");
  const chunks = ((c.groundingMetadata || {}).groundingChunks || []).map((x) => x.web || {}).filter((w) => w.uri);
  const hosts = [...new Set(await Promise.all(chunks.slice(0, 12).map((w) => realHost(w.uri, w.title))))].filter(Boolean);
  // 料金は「実際に行われた検索」1回ごと（1つの質問で何回も検索されうる）。台帳に残して月の上限に使う
  const searches = Math.max(1, ((c.groundingMetadata || {}).webSearchQueries || []).length);
  return { text, hosts, searches };
}

export async function onRequestPost({ request, env }) {
  let d;
  try { d = await request.json(); } catch (_) { return Response.json({ ok: false, error: "送信の形式が正しくありません。" }, { status: 400 }); }
  const v = (k, n = 200) => String(d[k] || "").trim().slice(0, n);
  if (v("_gotcha")) return Response.json({ ok: false, error: "送信できませんでした。" }, { status: 400 });
  const ind = v("industry", 20), area = v("area", 40), company = v("company", 80), site = v("site", 300);
  const name = v("name", 60), email = v("email", 200), pages = v("pages", 400);
  // 最初に来たときの流入元と最初に見たページ（site.js の ssFirst が足す）。台帳の送信元ページの列に入る
  const first = {};
  for (const k of ["first_ref", "first_utm", "first_ad", "first_land", "first_at", "send_page"]) if (k in d) first[k] = v(k, 200);
  const word = WORDS[ind] || v("word", 20);
  if (!word || !area || !company || !name || !email) {
    return Response.json({ ok: false, error: "未入力の項目があります。" }, { status: 400 });
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return Response.json({ ok: false, error: "メールアドレスの形式が正しくありません。" }, { status: 400 });
  }
  const closed = "ただいまチェックを受け付けていません。06-4305-7547 までお電話ください。";
  if (!env.GEMINI_API_KEY || !env.GAS_WEBHOOK_URL) {
    return Response.json({ ok: false, error: closed }, { status: 503 });
  }
  const ip = request.headers.get("CF-Connecting-IP") || "";
  // ロボットよけ（鍵が両方そろっているときだけ。そろう前はページにも出さない）
  if (env.TURNSTILE_SECRET && env.TURNSTILE_SITEKEY) {
    const form = new FormData();
    form.append("secret", env.TURNSTILE_SECRET);
    form.append("response", v("cf-turnstile-response", 4096));
    if (ip) form.append("remoteip", ip);
    let human = false;
    try {
      const t = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: form });
      human = Boolean((await t.json()).success);
    } catch (_) { human = false; }
    if (!human) {
      return Response.json({ ok: false, error: "ロボットでないことの確認ができませんでした。ページを読み込み直して、もう一度お試しください。" }, { status: 403 });
    }
  }
  // 回数の上限（メールごと累計3回・同じ回線から1日2回・月の検索5,000回）。AIに聞く前に確かめる。
  // 台帳に届かないときは受け付けない（上限が効かないまま有料の AI を呼ばない）
  const quota = await hub(env, { action: "ai_check_quota", email, ip });
  if (!quota || !quota.ok) {
    return Response.json({ ok: false, error: closed }, { status: 503 });
  }
  if (!quota.allowed) {
    const error = quota.reason === "email"
      ? `このメールアドレスでは${quota.perEmail || 3}回調べました。詳しく調べたい場合は、お問い合わせください。`
      : quota.reason === "ip"
        ? `同じ回線からのチェックは1日${quota.perIpDay || 2}回までです。明日もう一度お試しいただくか、お問い合わせください。`
        : "今月の無料チェックの受付数に達しました。詳しく調べたい場合は、お問い合わせください。";
    return Response.json({ ok: false, limit: quota.reason, error }, { status: 429 });
  }
  const own = host(/^https?:\/\//.test(site) ? site : "https://" + site);
  const qs = [`${area} ${word} おすすめ`, `${area} ${word} 評判 いい`, `${area} ${word} 人気`];
  let results;
  try {
    results = await Promise.all(qs.map(async (q) => {
      const a = await ask(env, q);
      return {
        q, searches: a.searches,
        cited: Boolean(own) && a.hosts.some((h) => h === own || h.endsWith("." + own)),
        mentioned: norm(a.text).includes(norm(company)),
        sources: a.hosts.slice(0, 8).map((h) => ({ host: h, portal: PORTAL.test(h), own: Boolean(own) && (h === own || h.endsWith("." + own)) })),
      };
    }));
  } catch (e) {
    const msg = String(e.message) === "quota"
      ? "今月の無料チェックの受付数に達しました。結果は担当者からメールでお送りします。"
      : "AIへの問い合わせに失敗しました。時間をおいてもう一度お試しください。";
    results = null;
    // 受け付けた連絡先は残し、結果は人が送る
    await record(env, request, { ind, area, company, site, name, email, word, pages, first, summary: "チェック未実行（" + e.message + "）" });
    return Response.json({ ok: false, error: msg }, { status: 503 });
  }
  const cited = results.filter((r) => r.cited).length, mentioned = results.filter((r) => r.mentioned).length;
  // 何に負けているかが分かるよう、出典に多く使われたサイト（御社以外）の上位3つも結果メールに載せる（F2）
  const freq = {};
  results.forEach((r) => r.sources.forEach((s) => { if (!s.own) freq[s.host] = (freq[s.host] || 0) + 1; }));
  const top = Object.keys(freq).sort((a, b) => freq[b] - freq[a]).slice(0, 3);
  const summary = `AI紹介チェック: ${area} ${word}｜出典に御社サイト ${cited}/3問・回答に社名 ${mentioned}/3問`
    + (top.length ? `\n主な出典: ${top.join("、")}` : "");
  await record(env, request, { ind, area, company, site, name, email, word, pages, first, summary });
  // 翌月の測り直しは、本人が印をつけたときだけ（同意のない配信はしない）
  const searches = results.reduce((n, r) => n + (r.searches || 1), 0);
  await hub(env, { action: "ai_check_log", email, company, word, area, cited, mentioned, site, ip, searches,
    recheck: v("recheck", 2) === "1", optin: v("optin", 2) === "1" });
  results.forEach((r) => { delete r.searches; });
  const used = quota.used + 1;
  return Response.json({ ok: true, results, cited, mentioned, lp: LP[ind] || "", used, perEmail: 3 });
}

// ページがロボットよけを出すかどうか（公開してよいサイトキーだけ返す）
export async function onRequestGet({ env }) {
  return Response.json({ turnstile: env.TURNSTILE_SECRET && env.TURNSTILE_SITEKEY ? env.TURNSTILE_SITEKEY : "" });
}

async function hub(env, body) {
  if (!env.GAS_WEBHOOK_URL) return null;
  try {
    const r = await fetch(env.GAS_WEBHOOK_URL, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, secret: env.GAS_SHARED_SECRET || "" }),
    });
    return await r.json().catch(() => null);
  } catch (_) { return null; }
}

async function record(env, request, x) {
  if (!env.GAS_WEBHOOK_URL) return;
  const data = { name: x.name, company: x.company, email: x.email, form_type: "AI紹介チェック（診断）", pages: x.pages || "", ...(x.first || {}),
    message: `${x.summary}\n業種: ${x.word}／地域: ${x.area}／サイト: ${x.site || "未入力"}` };
  try {
    await fetch(env.GAS_WEBHOOK_URL, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ secret: env.GAS_SHARED_SECRET || "", site: "ai-lab",
        data: { ...data, site: "ai-lab", type: "diagnosis" }, referer: request.headers.get("referer") || "" }),
    });
  } catch (_) { /* 台帳に書けなくても結果は返す */ }
}
