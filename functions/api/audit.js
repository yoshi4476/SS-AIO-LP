/**
 * サイト診断API（Cloudflare Pages Functions）
 * POST { url } → 対象ページ+robots.txt+llms.txt を取得し、
 * AIO/SEO対応12項目を100点満点で採点して返す。
 */
const PRIVATE = /^(localhost|127\.|10\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|0\.|\[::1\])/i;

async function get(url, limit = 400000) {
  try {
    const res = await fetch(url, {
      redirect: "follow",
      headers: { "User-Agent": "SevenSenses-SiteAudit/1.0 (+https://example.com/site-audit/)" },
    });
    // リダイレクト先が内部アドレスに向いた場合も拒否（SSRF対策）
    if (PRIVATE.test(new URL(res.url).hostname)) {
      return { ok: false, status: 0, text: "", finalUrl: url };
    }
    const text = (await res.text()).slice(0, limit);
    return { ok: res.ok, status: res.status, text, finalUrl: res.url };
  } catch {
    return { ok: false, status: 0, text: "", finalUrl: url };
  }
}

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
  if (PRIVATE.test(host)) return json({ error: "このURLは診断できません" }, 400);

  const page = await get(target);
  if (!page.ok) return json({ error: `ページを取得できませんでした（HTTP ${page.status || "接続失敗"}）` }, 422);
  const html = page.text;
  const origin = new URL(page.finalUrl).origin;
  const [robots, llms] = await Promise.all([get(origin + "/robots.txt", 50000), get(origin + "/llms.txt", 50000)]);

  const pick = (re) => (html.match(re) || [])[1] || "";
  const title = pick(/<title[^>]*>([\s\S]*?)<\/title>/i).trim();
  const desc = pick(/<meta[^>]+name=["']description["'][^>]+content=["']([^"']*)["']/i) ||
               pick(/<meta[^>]+content=["']([^"']*)["'][^>]+name=["']description["']/i);
  const h1s = (html.match(/<h1[\s>]/gi) || []).length;
  const imgs = html.match(/<img\b[^>]*>/gi) || [];
  const withAlt = imgs.filter((t) => /alt=["'][^"']+["']/i.test(t)).length;
  const altRate = imgs.length ? withAlt / imgs.length : 1;

  // robots.txt: AIボットが明示的にDisallowされていないか
  const rt = robots.ok ? robots.text : "";
  const uaGroup = (bot) => {
    const m = rt.match(new RegExp(`User-agent:\\s*${bot}[\\s\\S]*?(?=User-agent:|$)`, "i"));
    return m ? m[0] : null;
  };
  const botBlocked = (bot) => {
    // 個別UAの指定がなければ「User-agent: *」のルールが適用される（robots.txt仕様）
    const g = uaGroup(bot) ?? uaGroup("\\*");
    return g ? /Disallow:\s*\/\s*$/im.test(g) : false;
  };
  const aiBlocked = ["GPTBot", "PerplexityBot", "ClaudeBot", "OAI-SearchBot"].filter(botBlocked);

  const checks = [
    { name: "タイトルタグ（15〜45字）", pts: 10, ok: title.length >= 15 && title.length <= 45,
      detail: title ? `${title.length}字: 「${title.slice(0, 40)}」` : "タイトルがありません",
      advice: "検索キーワードを前半に含む15〜45字のタイトルにしてください" },
    { name: "メタディスクリプション（60〜160字）", pts: 10, ok: desc.length >= 60 && desc.length <= 160,
      detail: desc ? `${desc.length}字` : "設定なし",
      advice: "検索結果とAIが要約に使う説明文です。60〜160字で結論を書いてください" },
    { name: "H1見出し（1ページに1つ）", pts: 8, ok: h1s === 1, detail: `${h1s}個`,
      advice: "H1はページの主題です。1つに整理してください" },
    { name: "canonicalタグ", pts: 7, ok: /rel=["']canonical["']/i.test(html), detail: "",
      advice: "重複URLの評価分散を防ぐcanonicalを設定してください" },
    { name: "モバイル対応（viewport）", pts: 5, ok: /name=["']viewport["']/i.test(html), detail: "",
      advice: "viewportメタタグを設定し、スマホ表示に対応してください" },
    { name: "OGP（SNS/チャット共有時の見た目）", pts: 8,
      ok: /property=["']og:title["']/i.test(html) && /property=["']og:image["']/i.test(html), detail: "",
      advice: "og:title・og:imageを設定すると共有時にカード表示されます" },
    { name: "構造化データ（JSON-LD）", pts: 12, ok: /application\/ld\+json/i.test(html), detail: "",
      advice: "Article・FAQPage等のJSON-LDで、内容の意味をAIに伝えてください" },
    { name: "FAQの構造化", pts: 8, ok: /FAQPage/i.test(html), detail: "",
      advice: "FAQPageスキーマはAI回答に引用されやすい形式です。FAQ5問以上+スキーマを推奨" },
    { name: "AIクローラー許可（robots.txt）", pts: 12, ok: robots.ok ? aiBlocked.length === 0 : true,
      detail: aiBlocked.length ? `ブロック中: ${aiBlocked.join(", ")}` : (robots.ok ? "主要AIボット許可" : "robots.txtなし（デフォルト許可）"),
      advice: "GPTBot等をブロックするとAIの回答に引用されません。引用獲得を狙うなら許可してください" },
    { name: "llms.txt（AI向けサイト案内）", pts: 8, ok: llms.ok && llms.text.trim().length > 10, detail: "",
      advice: "サイト概要と主要ページをまとめたllms.txtの設置を推奨します" },
    { name: "HTTPS", pts: 4, ok: page.finalUrl.startsWith("https://"), detail: "",
      advice: "常時SSL化は信頼性の前提条件です" },
    { name: "画像のalt属性（80%以上）", pts: 8, ok: altRate >= 0.8,
      detail: imgs.length ? `${withAlt}/${imgs.length}枚に設定（${Math.round(altRate * 100)}%）` : "画像なし",
      advice: "altは画像内容をAI・検索エンジンに伝えます。全画像への設定を推奨" },
  ];
  const score = checks.reduce((s, c) => s + (c.ok ? c.pts : 0), 0);
  const grade = score >= 85 ? "A（AI検索対応は高水準）" : score >= 65 ? "B（土台あり。あと一歩）"
              : score >= 45 ? "C（重要項目に抜けあり）" : "D（基礎から整備が必要）";
  return json({ url: page.finalUrl, score, grade, checks });
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}
