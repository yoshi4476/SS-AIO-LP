// 門（tests/gates_history_h62.py）が Worker の動きを確かめる道具。Worker には束ねない（src から読まない）。
// 判定は門の側でする。ここは結果を JSON で出すだけ
//   node automation/scheduler/test/harness.mjs fires <開始 ISO> <終わり ISO>  その間の各回（5分ごと）が窓に入れる予定
//   node automation/scheduler/test/harness.mjs scenarios                      GitHub を偽物にして起動の流れを試す
import { due, tick } from "../src/core.mjs";
import TABLE from "../schedule.json" with { type: "json" };

const [cmd, a, b] = process.argv.slice(2);

if (cmd === "fires") {
  const out = [];
  const step = TABLE.tick_minutes * 60000;
  for (let t = Date.parse(a) + step; t <= Date.parse(b); t += step) {
    for (const it of due(TABLE.entries, t, TABLE.lookback_minutes, TABLE.tick_minutes)) {
      out.push([it.e.wf, it.e.cron, new Date(it.ms).toISOString(), it.fresh]);
    }
  }
  console.log(JSON.stringify(out));
}

function fake({ runs = [], dispatch = [], table = null, expiry = "2026-12-31 00:00:00 UTC", getStatus = 200 } = {}) {
  const calls = [];
  let posts = 0;
  const f = async (url, init = {}) => {
    const method = init.method || "GET";
    calls.push({ url: String(url), method, body: init.body ? JSON.parse(init.body) : null,
      auth: (init.headers || {}).Authorization || "", ua: (init.headers || {})["User-Agent"] || "" });
    const headers = new Headers(expiry ? { "github-authentication-token-expiration": expiry } : {});
    if (String(url).startsWith("https://raw.githubusercontent.com/")) {
      return table === "fail" ? new Response("unavailable", { status: 503 })
        : new Response(JSON.stringify(table || TABLE), { status: 200 });
    }
    if (method === "GET") {
      if (getStatus !== 200) return new Response("{\"message\":\"Bad credentials\"}", { status: getStatus, headers });
      const list = typeof runs === "function" ? runs(posts) : runs;
      return new Response(JSON.stringify({ workflow_runs: list }), { status: 200, headers });
    }
    const st = dispatch[posts++] ?? 200;
    return st === 200
      ? new Response(JSON.stringify({ workflow_run_id: 1, html_url: "https://github.com/x/actions/runs/1" }), { status: 200, headers })
      : new Response("{\"message\":\"error\"}", { status: st, headers });
  };
  return { f, calls };
}

async function scenario(at, opts = {}, env = { GITHUB_TOKEN: " test-token\n" }) {
  const { f, calls } = fake(opts);
  const sleeps = [];
  const logs = [];
  const log = { log: (s) => logs.push(["log", s]), warn: (s) => logs.push(["warn", s]), error: (s) => logs.push(["error", s]) };
  const results = await tick(Date.parse(at), env, { fetch: f, sleep: async (ms) => { sleeps.push(ms); }, log });
  const gh = calls.filter((c) => c.url.startsWith("https://api.github.com/"));
  return {
    results, sleeps,
    posts: gh.filter((c) => c.method === "POST").map((c) => ({ url: c.url, body: c.body })),
    gets: gh.filter((c) => c.method === "GET").map((c) => c.url),
    auth: [...new Set(gh.map((c) => c.auth))],
    ua: [...new Set(calls.map((c) => c.ua))],
    logs: logs.map(([lv, s]) => [lv, JSON.parse(s).result]),
  };
}

if (cmd === "scenarios") {
  const worker = { event: "workflow_dispatch", display_title: "記事の枠 12 2026-10-08T20:07+09:00", created_at: "2026-10-08T11:10:03Z", html_url: "u" };
  const backup = { event: "schedule", display_title: "記事の枠（予備の定時） 7 11 * * *", created_at: "2026-10-08T11:08:00Z", html_url: "u" };
  const old = { event: "workflow_dispatch", display_title: "記事の枠 12 2026-10-07T20:07+09:00", created_at: "2026-10-07T11:10:03Z", html_url: "u" };
  const out = {
    fresh_dispatch: await scenario("2026-10-08T11:10:00Z"),
    already_by_worker: await scenario("2026-10-08T11:10:00Z", { runs: [worker] }),
    already_by_backup: await scenario("2026-10-08T11:10:00Z", { runs: [backup] }),
    yesterday_does_not_count: await scenario("2026-10-08T11:10:00Z", { runs: [old] }),
    retry_finds_it: await scenario("2026-10-08T11:10:00Z", { dispatch: [502], runs: (posts) => (posts ? [worker] : []) }),
    retry_until_gave_up: await scenario("2026-10-08T11:10:00Z", { dispatch: [502, 502, 502] }),
    rejected_422: await scenario("2026-10-08T11:10:00Z", { dispatch: [422] }),
    second_tick_confirms: await scenario("2026-10-08T11:15:00Z", { runs: [worker] }),
    nothing_due: await scenario("2026-10-08T11:20:00Z"),
    table_fallback: await scenario("2026-10-08T11:10:00Z", { table: "fail" }),
    no_token: await scenario("2026-10-08T11:10:00Z", {}, {}),
    auth_401: await scenario("2026-10-08T11:10:00Z", { getStatus: 401 }),
    no_expiry_header: await scenario("2026-10-08T11:10:00Z", { expiry: "" }),
    monthly: await scenario("2026-10-01T00:00:00Z"),
    rescue: await scenario("2026-10-08T12:30:00Z"),
  };
  console.log(JSON.stringify(out));
}
