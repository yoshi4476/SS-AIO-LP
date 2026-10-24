/**
 * サイト診断（/api/audit）の項目と、結果の署名（/api/lead が確かめる）。
 * 結果送付のメールに載せる「直し方」は、利用者が送ってきた文ではなく、ここにある決まった文から作り直す。
 * 以前は画面が組み立てた文をそのまま受け取り、当社名義の自動返信に載せていたため、他人のアドレスへ
 * 好きな本文（偽のログイン案内など）を当社から送らせられた（2026-10-24 の点検）
 */
import { sign, read } from "./_sign.js";

export const CHECKS = [
  { id: "robots", group: "AIが入れるか", name: "AIのクローラーを拒否していない（robots.txt）", pts: 12,
    advice: "robots.txt で拒否しているクローラーの Disallow を外してください。拒否されたAIは、ページの中身を読めないため回答に使えません" },
  { id: "cdn", group: "AIが入れるか", name: "AIのクローラーが入口で弾かれていない（CDN・WAF）", pts: 8,
    advice: "Cloudflare等の「AIボットをブロック」設定を確認してください。AIのクローラーを既定で止める設定のCDNがあります" },
  { id: "https", group: "AIが入れるか", name: "常時SSL（HTTPS）", pts: 6,
    advice: "http のままのページは信頼性の前提を満たしません。常時SSLにしてください" },
  { id: "noindex", group: "検索に出るか", name: "検索に出さない設定（noindex）になっていない", pts: 12,
    advice: "noindex が付いたページは検索にもAIの回答にも出ません。公開したいページなら外してください" },
  { id: "title", group: "検索に出るか", name: "タイトル（15〜45字）", pts: 10,
    advice: "検索される言葉を前半に入れ、15〜45字にしてください" },
  { id: "desc", group: "検索に出るか", name: "説明文（メタディスクリプション・60〜160字）", pts: 8,
    advice: "検索結果に出る説明文です。60〜160字で、このページで分かることを書いてください" },
  { id: "canonical", group: "検索に出るか", name: "正規URLの指定（canonical）", pts: 6,
    advice: "同じ内容が複数のURLで見えると評価が分かれます。canonical で正規のURLを示してください" },
  { id: "viewport", group: "検索に出るか", name: "スマホ表示（viewport）", pts: 4,
    advice: "viewport を設定し、スマホで読める表示にしてください" },
  { id: "h1", group: "内容を読み取れるか", name: "見出しH1がページに1つ", pts: 8,
    advice: "H1はページの主題です。1つに整理してください" },
  { id: "nap", group: "内容を読み取れるか", name: "会社情報（電話番号・所在地）の記載", pts: 8,
    advice: "電話番号と所在地を文字で書いてください（画像だけでは読み取れません）。地域の質問で候補に入る前提です" },
  { id: "jsonld", group: "内容を読み取れるか", name: "構造化データ（JSON-LD）", pts: 6,
    advice: "会社情報やFAQを検索エンジンに正確に伝える記述です。リッチリザルトに使われます（AIに引用されるための必須条件ではない、とGoogleは明言しています）" },
  { id: "alt", group: "内容を読み取れるか", name: "画像の代替テキスト（alt・80%以上）", pts: 4,
    advice: "画像の中の情報は読み取られません。alt に内容を書き、大事なことは本文にも書いてください" },
  { id: "ogp", group: "内容を読み取れるか", name: "SNS・チャット共有時の表示（OGP）", pts: 4,
    advice: "og:title・og:image を設定すると、共有されたときにカードで表示されます" },
  { id: "llms", group: "内容を読み取れるか", name: "llms.txt（参考）", pts: 2,
    advice: "AI向けのサイト案内です。Googleは使わないと明言しているため優先度は低めです" },
];

export const GRADES = ["D（読まれない原因があります）", "A（土台は整っています）", "B（あと一歩）",
                       "C（重要項目に抜けあり）", "D（基礎から整備が必要）"];

// 結果送付のフォームを開いたまま置いておく時間を見込んで、2時間だけ有効にする
const TTL_MS = 2 * 3600 * 1000;

/** 診断の結果に署名する。合言葉が無い環境では空（結果送付は直し方なしの受付になる） */
export async function signAudit(secret, url, score, grade, failedIds) {
  return sign(secret, "ss-audit-token", { u: String(url).slice(0, 300), s: score, g: GRADES.indexOf(grade), f: failedIds }, TTL_MS);
}

/** 署名を確かめ、メールに載せる診断の結果を決まった文から作り直す。確かめられなければ null */
export async function readAudit(secret, token) {
  const p = await read(secret, "ss-audit-token", token);
  if (!p || !GRADES[p.g] || !Number.isInteger(p.s) || p.s < 0 || p.s > 100 || !/^https?:\/\//.test(String(p.u))) return null;
  const fixes = CHECKS.filter((c) => Array.isArray(p.f) && p.f.includes(c.id)).sort((a, b) => b.pts - a.pts)
    .map((c) => "・" + c.name + "（" + c.pts + "点）: " + c.advice).join("\n");
  return { url: p.u, total: p.s, grade: GRADES[p.g], fixes };
}
