/**
 * サイト診断API（Cloudflare Pages Functions）
 * POST { url } → 対象ページ・robots.txt・llms.txt を取得し、13項目・100点満点で採点して返す。
 *
 * 項目と配点は、2026-09 時点で一次情報で確かめたことに合わせる（CLAUDE.md 0.3節）。
 * - Google は AI 最適化ガイドで「llms.txt は使わない」「構造化データは AI 引用の必須条件ではない」と明言している。
 *   以前はこの2つを AI 引用の加点として大きく数えていたため、配点を下げて説明も事実に直した
 * - 効くと明記されているのは「クロールできること」。AI のクローラーが入れるか（robots.txt と CDN の遮断）と、
 *   検索に出さない設定（noindex）を重く見る
 *
 * 返す文字（detail）は HTML として安全な形にする。診断したサイトのタイトルをそのまま画面に差し込むと、
 * 悪意のあるタイトルが当社のドメイン上でスクリプトとして動く（XSS）。
 */
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

export async function onRequestPost({ request }) {
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

  const checks = [
    { group: "AIが入れるか", name: "AIのクローラーを拒否していない（robots.txt）", pts: 12,
      ok: robots.ok ? aiBlocked.length === 0 : true,
      detail: aiBlocked.length ? `拒否中: ${aiBlocked.join(", ")}` : (robots.ok ? "主要なAIのクローラーを許可" : "robots.txtなし（既定で許可）"),
      advice: "robots.txt で拒否しているクローラーの Disallow を外してください。拒否されたAIは、ページの中身を読めないため回答に使えません" },
    { group: "AIが入れるか", name: "AIのクローラーが入口で弾かれていない（CDN・WAF）", pts: 8, ok: !cdnBlocked,
      detail: cdnBlocked ? `GPTBotを名乗るアクセスがHTTP ${asBot.status}で拒否されました` : "拒否されませんでした",
      advice: "Cloudflare等の「AIボットをブロック」設定を確認してください。AIのクローラーを既定で止める設定のCDNがあります" },
    { group: "AIが入れるか", name: "常時SSL（HTTPS）", pts: 6, ok: page.finalUrl.startsWith("https://"), detail: "",
      advice: "http のままのページは信頼性の前提を満たしません。常時SSLにしてください" },
    { group: "検索に出るか", name: "検索に出さない設定（noindex）になっていない", pts: 12, ok: !noindex,
      detail: noindex ? "noindex が指定されています" : "指定なし",
      advice: "noindex が付いたページは検索にもAIの回答にも出ません。公開したいページなら外してください" },
    { group: "検索に出るか", name: "タイトル（15〜45字）", pts: 10, ok: title.length >= 15 && title.length <= 45,
      detail: title ? `${title.length}字: 「${title.slice(0, 40)}」` : "タイトルがありません",
      advice: "検索される言葉を前半に入れ、15〜45字にしてください" },
    { group: "検索に出るか", name: "説明文（メタディスクリプション・60〜160字）", pts: 8, ok: desc.length >= 60 && desc.length <= 160,
      detail: desc ? `${desc.length}字` : "設定なし",
      advice: "検索結果に出る説明文です。60〜160字で、このページで分かることを書いてください" },
    { group: "検索に出るか", name: "正規URLの指定（canonical）", pts: 6, ok: /rel=["']canonical["']/i.test(html), detail: "",
      advice: "同じ内容が複数のURLで見えると評価が分かれます。canonical で正規のURLを示してください" },
    { group: "検索に出るか", name: "スマホ表示（viewport）", pts: 4, ok: /name=["']viewport["']/i.test(html), detail: "",
      advice: "viewport を設定し、スマホで読める表示にしてください" },
    { group: "内容を読み取れるか", name: "見出しH1がページに1つ", pts: 8, ok: h1s === 1, detail: `${h1s}個`,
      advice: "H1はページの主題です。1つに整理してください" },
    { group: "内容を読み取れるか", name: "会社情報（電話番号・所在地）の記載", pts: 8, ok: hasTel && hasAddr,
      detail: `電話番号${hasTel ? "あり" : "なし"}・所在地${hasAddr ? "あり" : "なし"}`,
      advice: "電話番号と所在地を文字で書いてください（画像だけでは読み取れません）。地域の質問で候補に入る前提です" },
    { group: "内容を読み取れるか", name: "構造化データ（JSON-LD）", pts: 6, ok: /application\/ld\+json/i.test(html), detail: "",
      advice: "会社情報やFAQを検索エンジンに正確に伝える記述です。リッチリザルトに使われます（AIに引用されるための必須条件ではない、とGoogleは明言しています）" },
    { group: "内容を読み取れるか", name: "画像の代替テキスト（alt・80%以上）", pts: 4, ok: altRate >= 0.8,
      detail: imgs.length ? `${withAlt}/${imgs.length}枚に設定（${Math.round(altRate * 100)}%）` : "画像なし",
      advice: "画像の中の情報は読み取られません。alt に内容を書き、大事なことは本文にも書いてください" },
    { group: "内容を読み取れるか", name: "SNS・チャット共有時の表示（OGP）", pts: 4,
      ok: /property=["']og:title["']/i.test(html) && /property=["']og:image["']/i.test(html), detail: "",
      advice: "og:title・og:image を設定すると、共有されたときにカードで表示されます" },
    { group: "内容を読み取れるか", name: "llms.txt（参考）", pts: 2, ok: llms.ok && llms.text.trim().length > 10,
      detail: llms.ok ? "あり" : "なし",
      advice: "AI向けのサイト案内です。Googleは使わないと明言しているため優先度は低めです" },
  ];
  const score = checks.reduce((s, c) => s + (c.ok ? c.pts : 0), 0);
  const critical = checks.filter((c) => !c.ok && c.pts >= 12).map((c) => c.name);
  const grade = critical.length ? "D（読まれない原因があります）"
              : score >= 85 ? "A（土台は整っています）" : score >= 65 ? "B（あと一歩）"
              : score >= 45 ? "C（重要項目に抜けあり）" : "D（基礎から整備が必要）";
  const safe = checks.map((c) => ({ ...c, detail: esc(c.detail) }));
  return json({ url: esc(page.finalUrl), score, grade, critical, checks: safe, measured_at: new Date().toISOString() });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}
