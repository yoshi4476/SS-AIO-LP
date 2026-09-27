/**
 * 同業平均（GET /api/bench）
 * 管制塔（GAS）が集計した業種ごとの平均点を返す。10社未満の業種は含まれない。
 * GAS は呼ぶたびに数秒かかるので、1時間はCloudflareの控えを返す。
 */
export async function onRequestGet({ request, env, waitUntil }) {
  const cache = caches.default;
  const key = new Request(new URL("/api/bench", request.url).toString());
  const hit = await cache.match(key);
  if (hit) return hit;
  let data = { ok: false, industries: {} };
  if (env.GAS_WEBHOOK_URL) {
    try {
      const r = await fetch(env.GAS_WEBHOOK_URL + "?action=scan_bench", { redirect: "follow" });
      data = await r.json();
    } catch (_) {}
  }
  const res = new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=3600" },
  });
  if (data.ok && waitUntil) waitUntil(cache.put(key, res.clone()));
  return res;
}
