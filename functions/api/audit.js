/**
 * サイト診断API（Cloudflare Pages Functions）
 * POST { url } → 対象ページ・robots.txt・llms.txt を取得し、14項目・100点満点で採点して返す。
 *
 * 項目と配点は、2026-09 時点で一次情報で確かめたことに合わせる（CLAUDE.md 0.3節）。
 * - Google は AI 最適化ガイドで「llms.txt は使わない」「構造化データは AI 引用の必須条件ではない」と明言している。
 *   以前はこの2つを AI 引用の加点として大きく数えていたため、配点を下げて説明も事実に直した
 * - 各項目の配点の合計は98点。返す得点は100点満点に換算する（2026-10-03 まで98点満点のまま「100点満点」と表示していた）
 * - 効くと明記されているのは「クロールできること」。AI のクローラーが入れるか（robots.txt と CDN の遮断）と、
 *   検索に出さない設定（noindex）を重く見る
 *
 * 返す文字（detail）は HTML として安全な形にする。診断したサイトのタイトルをそのまま画面に差し込むと、
 * 悪意のあるタイトルが当社のドメイン上でスクリプトとして動く（XSS）。
 */
import { CHECKS, GRADES, signAudit } from "../_audit_checks.js";
import { digest, ipKey, rateHit } from "../_sign.js";

// 1回の診断で相手のサイトへ4回取りに行く。回数の上限が無いと、他人のサイトへの負荷の踏み台にされ、
// 同業の平均を偽の診断で動かせた（2026-10-24 の点検）。管制塔に届かないときは診断を止めない（無料の道具を落とさない）
const RATE = [["audit_ip_h_", 10, 3600], ["audit_ip_6h_", 30, 21600]];
const RATE_ALL = { key: "audit_all", limit: 400, sec: 3600 };

/** 登録ドメイン（a1.evil.example・a2.evil.example を同じ会社として数える）。co.jp などは3つ目の段まで */
export function siteOf(host) {
  const p = String(host).toLowerCase().replace(/\.$/, "").split(".");
  const second = /^(co|or|ne|ac|go|ed|gr|lg|ad|com|net|org|gov|edu)$/;
  return p.slice(p.length >= 3 && p[p.length - 1].length === 2 && second.test(p[p.length - 2]) ? -3 : -2).join(".");
}

const PRIVATE = /^(localhost|127\.|10\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|0\.|\[::1\])/i;
const UA = "SevenSenses-SiteAudit/1.1 (+https://ai.7senses.co.jp/lp/)";
const GPTBOT_UA = "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.1; +https://openai.com/gptbot";

async function get(url, limit = 400000, ua = UA) {
  try {
    const res = await fetch(url, { redirect: "follow", headers: { "User-Agent": ua } });
    // リダイレクト先が内部アドレスに向いた場合も拒否（SSRF対策）
    if (PRIVATE.test(new URL(res.url).hostname)) {
      return { ok: false, status: 0, text: "", finalUrl: url, headers: new Headers() };
    }
    const text = (await res.text()).slice(0, limit);
    return { ok: res.ok, status: res.status, text, finalUrl: res.url, headers: res.headers };
  } catch {
    return { ok: false, status: 0, text: "", finalUrl: url, headers: new Headers() };
  }
}

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export async function onRequestPost({ request, env, waitUntil }) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: "リクエスト形式が不正です" }, 400);
  }
  if (!body || typeof body !== "object") body = {};
  let target = String(body.url || "").trim();
  if (!/^https?:\/\//i.test(target)) target = "https://" + target;
  let host;
  try {
    host = new URL(target).hostname;
  } catch {
    return json({ error: "URLの形式が正しくありません" }, 400);
  }
  if (PRIVATE.test(host) || !host.includes(".")) return json({ error: "このURLは診断できません" }, 400);
  // 当社の営業の下書き（prospect_outreach.py）は合言葉の印を付けて送る。それ以外は回線ごと・全体の回数に上限
  const ours = env && env.GAS_SHARED_SECRET && request.headers.get("X-SS-Audit-Key") === await digest("audit-key:" + env.GAS_SHARED_SECRET);
  if (!ours) {
    const who = await digest(ipKey(request.headers.get("CF-Connecting-IP") || ""));
    const rate = await rateHit(env || {}, [...RATE.map(([k, limit, sec]) => ({ key: k + who, limit, sec })), RATE_ALL]);
    if (rate.allowed === false) {
      return json({ error: "短い時間に診断が続いたため、いったん止めています。1時間ほどおいてもう一度お試しください。" }, 429);
    }
  }

  const page = await get(target);
  if (!page.ok) return json({ error: `ページを取得できませんでした（HTTP ${page.status || "接続失敗"}）` }, 422);
  const html = page.text;
  const origin = new URL(page.finalUrl).origin;
  const [robots, llms, asBot] = await Promise.all([
    get(origin + "/robots.txt", 50000),
    get(origin + "/llms.txt", 50000),
    get(page.finalUrl, 20000, GPTBOT_UA),
  ]);

  const pick = (re) => (html.match(re) || [])[1] || "";
  const title = pick(/<title[^>]*>([\s\S]*?)<\/title>/i).replace(/\s+/g, " ").trim();
  const desc = pick(/<meta[^>]+name=["']description["'][^>]+content=["']([^"']*)["']/i) ||
               pick(/<meta[^>]+content=["']([^"']*)["'][^>]+name=["']description["']/i);
  const h1s = (html.match(/<h1[\s>]/gi) || []).length;
  const imgs = html.match(/<img\b[^>]*>/gi) || [];
  const withAlt = imgs.filter((t) => /alt=["'][^"']+["']/i.test(t)).length;
  const altRate = imgs.length ? withAlt / imgs.length : 1;
  const robotsMeta = pick(/<meta[^>]+name=["']robots["'][^>]+content=["']([^"']*)["']/i) +
                     " " + (page.headers.get("x-robots-tag") || "");
  const noindex = /noindex/i.test(robotsMeta);
  const text = html.replace(/<script[\s\S]*?<\/script>|<style[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " ");
  const hasTel = /0\d{1,4}[-‐－ー(（]\d{1,4}[-‐－ー)）]\d{3,4}/.test(text);
  const hasAddr = /(北海道|東京都|京都府|大阪府|..県)[^\s]{2,}(市|区|町|村)/.test(text);

  // robots.txt: AIのクローラーが明示的に拒否されていないか
  const rt = robots.ok ? robots.text : "";
  const uaGroup = (bot) => {
    const m = rt.match(new RegExp(`User-agent:\\s*${bot}[\\s\\S]*?(?=User-agent:|$)`, "i"));
    return m ? m[0] : null;
  };
  const botBlocked = (bot) => {
    // 個別の指定がなければ「User-agent: *」のルールが適用される（robots.txt仕様）
    const g = uaGroup(bot) ?? uaGroup("\\*");
    return g ? /Disallow:\s*\/\s*$/im.test(g) : false;
  };
  const aiBlocked = ["GPTBot", "OAI-SearchBot", "PerplexityBot", "ClaudeBot", "Googlebot"].filter(botBlocked);
  // CDN（Cloudflare等）が AI のクローラーを入口で弾いていないか。robots.txt で許可していても、ここで止まると読まれない。
  // 名乗りだけで判定される設定もあるため「拒否された」事実だけを伝え、断定はしない
  const cdnBlocked = page.ok && [401, 403, 429, 503].includes(asBot.status);

  // 項目の名前・配点・直し方は _audit_checks.js（結果送付のメールも同じ文から作る）。ここでは合否と詳細だけを決める
  const RESULT = {
    robots: { ok: robots.ok ? aiBlocked.length === 0 : true,
      detail: aiBlocked.length ? `拒否中: ${aiBlocked.join(", ")}` : (robots.ok ? "主要なAIのクローラーを許可" : "robots.txtなし（既定で許可）") },
    cdn: { ok: !cdnBlocked, detail: cdnBlocked ? `GPTBotを名乗るアクセスがHTTP ${asBot.status}で拒否されました` : "拒否されませんでした" },
    https: { ok: page.finalUrl.startsWith("https://"), detail: "" },
    noindex: { ok: !noindex, detail: noindex ? "noindex が指定されています" : "指定なし" },
    title: { ok: title.length >= 15 && title.length <= 45,
      detail: title ? `${title.length}字: 「${title.slice(0, 40)}」` : "タイトルがありません" },
    desc: { ok: desc.length >= 60 && desc.length <= 160, detail: desc ? `${desc.length}字` : "設定なし" },
    canonical: { ok: /rel=["']canonical["']/i.test(html), detail: "" },
    viewport: { ok: /name=["']viewport["']/i.test(html), detail: "" },
    h1: { ok: h1s === 1, detail: `${h1s}個` },
    nap: { ok: hasTel && hasAddr, detail: `電話番号${hasTel ? "あり" : "なし"}・所在地${hasAddr ? "あり" : "なし"}` },
    jsonld: { ok: /application\/ld\+json/i.test(html), detail: "" },
    alt: { ok: altRate >= 0.8,
      detail: imgs.length ? `${withAlt}/${imgs.length}枚に設定（${Math.round(altRate * 100)}%）` : "画像なし" },
    ogp: { ok: /property=["']og:title["']/i.test(html) && /property=["']og:image["']/i.test(html), detail: "" },
    llms: { ok: llms.ok && llms.text.trim().length > 10, detail: llms.ok ? "あり" : "なし" },
  };
  const checks = CHECKS.map((c) => ({ group: c.group, name: c.name, pts: c.pts, ok: RESULT[c.id].ok,
                                       detail: RESULT[c.id].detail, advice: c.advice, id: c.id }));
  const maxPts = checks.reduce((s, c) => s + c.pts, 0);
  const score = Math.round(checks.reduce((s, c) => s + (c.ok ? c.pts : 0), 0) * 100 / maxPts);
  const critical = checks.filter((c) => !c.ok && c.pts >= 12).map((c) => c.name);
  const grade = critical.length ? GRADES[0] : score >= 85 ? GRADES[1] : score >= 65 ? GRADES[2]
              : score >= 45 ? GRADES[3] : GRADES[4];
  const safe = checks.map((c) => ({ ...c, detail: esc(c.detail) }));
  // 同業平均のために記録する（業種・点数・紹介元と、サイトを特定できない形に変換した値だけ）。
  // 応答は待たせない。記録に失敗しても診断の結果はそのまま返す
  // 自社のサイトと例示用のドメインは数えない（同業の平均がゆがむ）
  const own = /(^|\.)(7senses\.co\.jp|example\.(com|org|net|jp))$/i.test(new URL(page.finalUrl).hostname);
  // 営業の下書き（scripts/prospect_outreach.py）が当社の側で測った分は、同業の平均にも診断の記録にも入れない
  const prospect = body.ref === "prospect";
  if (env && env.GAS_WEBHOOK_URL && waitUntil && !own && !prospect) {
    const INDUSTRIES = ["クリニック・歯科医院", "不動産", "工務店・リフォーム", "士業・コンサル", "BtoB・IT", "店舗・飲食・美容", "その他"];
    const industry = INDUSTRIES.includes(body.industry) ? body.industry : "";
    const ref = /^[A-Za-z0-9_-]{1,40}$/.test(String(body.ref || "")) ? body.ref : "";
    waitUntil((async () => {
      try {
        // 同じ会社は登録ドメインで1つに数える（サブドメインを替えた偽の診断で平均を動かさせない）
        const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode("ss-bench:" + siteOf(new URL(page.finalUrl).hostname)));
        const hostHash = [...new Uint8Array(d)].slice(0, 16).map((b) => b.toString(16).padStart(2, "0")).join("");
        await fetch(env.GAS_WEBHOOK_URL, { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "scan_log", secret: env.GAS_SHARED_SECRET || "", industry, host: hostHash, score, ref }) });
      } catch (_) {}
    })());
  }
  // 結果送付のフォームはこの署名だけを送る。メールの直し方は /api/lead がこの署名から作り直す
  const token = await signAudit(env && env.GAS_SHARED_SECRET, page.finalUrl, score, grade,
                                checks.filter((c) => !c.ok).map((c) => c.id));
  return json({ url: esc(page.finalUrl), score, grade, critical, checks: safe, token, measured_at: new Date().toISOString() });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}
