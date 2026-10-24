/**
 * 署名つきの短い証明（診断の結果・ニュースレターの登録の確認）と、回数の上限（管制塔の rate_hit）。
 * 鍵は GAS_SHARED_SECRET から用途ごとに分けて作る（同じ鍵で別の用途の証明を作り回せないように）。
 * ファイル名の先頭の _ は、ここが受付の URL にならないことを示す
 */
const enc = new TextEncoder();
export const b64u = (bytes) => btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
export const unb64u = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));

async function key(secret, purpose) {
  return crypto.subtle.importKey("raw", enc.encode(purpose + ":" + secret), { name: "HMAC", hash: "SHA-256" }, false,
                                 ["sign", "verify"]);
}

/** 中身 obj に期限を付けて署名する。合言葉が無ければ空 */
export async function sign(secret, purpose, obj, ttlMs) {
  if (!secret) return "";
  const body = b64u(enc.encode(JSON.stringify({ ...obj, e: Date.now() + ttlMs })));
  return body + "." + b64u(new Uint8Array(await crypto.subtle.sign("HMAC", await key(secret, purpose), enc.encode(body))));
}

/** 署名と期限を確かめて中身を返す。確かめられなければ null */
export async function read(secret, purpose, token) {
  const [body, sig] = String(token || "").split(".");
  if (!secret || !body || !sig || body.length > 2000) return null;
  try {
    if (!(await crypto.subtle.verify("HMAC", await key(secret, purpose), unb64u(sig), enc.encode(body)))) return null;
    const p = JSON.parse(new TextDecoder().decode(unb64u(body)));
    return p.e > Date.now() ? p : null;
  } catch (_) {
    return null;
  }
}

export async function digest(s) {
  const d = await crypto.subtle.digest("SHA-256", enc.encode(String(s)));
  return [...new Uint8Array(d)].slice(0, 12).map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** 回線の数え方。IPv6 は同じ契約の中でアドレスを替えられるので、先頭の /64 で数える（管制塔の ipKey_ と同じ） */
export function ipKey(ip) {
  const s = String(ip || "").trim().toLowerCase();
  if (!s.includes(":")) return s;
  const head = s.split("::")[0].split(":");
  while (head.length < 4) head.push("0");
  return head.slice(0, 4).join(":") + "::/64";
}

/**
 * 回数の上限。limits は [{ key, limit, sec }]（sec は最長6時間。管制塔のキャッシュの上限）。
 * 全部が上限の内なら数えて { allowed: true }。管制塔に届かないときは { allowed: null }（呼ぶ側が通すか決める）
 */
export async function rateHit(env, limits) {
  if (!env.GAS_WEBHOOK_URL || !env.GAS_SHARED_SECRET) return { allowed: null };
  try {
    const r = await fetch(env.GAS_WEBHOOK_URL, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "rate_hit", secret: env.GAS_SHARED_SECRET, limits }),
    });
    const j = await r.json();
    return j && j.ok ? { allowed: Boolean(j.allowed), hit: j.hit || "" } : { allowed: null };
  } catch (_) {
    return { allowed: null };
  }
}
