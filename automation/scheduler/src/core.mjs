// 定時の起動役（Cloudflare Workers の Cron Triggers・無料プラン）の中身。入口は index.mjs、説明は ../README.md
// （入口のファイルが定数や関数を出すと、Workers の実行環境がそれを入口とみなして起動しない。出すのはここ）
//
// GitHub Actions の schedule は3〜8時間遅れて始まる（2026-09-24〜10-07 の実測）。この Worker が5分ごとに起き、
// 予定の表（../schedule.json。scripts/scheduler_build.py が .github/workflows/*.yml の cron から作る）のうち、
// 直前の窓に予定の時刻が入るものを GitHub の workflow_dispatch で起動する。
// - 表は毎回 master の最新を読む（cron を変えても配り直さなくてよい）。読めない・形が違うときは配ったときの表
// - 起動の前に、その予定の回（この Worker の回か、予備の GitHub の定時の回）がもう作られていないかを一覧で見る。
//   窓は2回分あるので、同じ予定を2回起動しない。失敗して再試行するときも、確かめてから起動する
// - 鍵は Worker の secret（GITHUB_TOKEN）。コードにもリポジトリにも書かない
// - 応答ヘッダーの鍵の期限（github-authentication-token-expiration）を入力 token_expiry で渡す（管制塔が見張る）
import BUNDLED from "../schedule.json" with { type: "json" };

const API = "https://api.github.com";
const UA = "ss-aio-scheduler";
// 失敗したときの待ち（再試行は2回まで）。1回の問い合わせは10秒まで
export const RETRY_WAIT_MS = [15000, 45000];
export const TIMEOUT_MS = 10000;
const TITLE_AT = /(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2}))$/;

const has = (list, v) => list === null || list.includes(v);

// cron の決まり: 日と曜日の両方を指定したときは、どちらかに合えばよい（scripts/schedule_guard.py と同じ）
export function matches(e, d) {
  if (!has(e.minute, d.getUTCMinutes()) || !has(e.hour, d.getUTCHours()) || !has(e.month, d.getUTCMonth() + 1)) {
    return false;
  }
  const dom = has(e.dom, d.getUTCDate());
  const dow = has(e.dow, d.getUTCDay());
  return e.dom !== null && e.dow !== null ? dom || dow : dom && dow;
}

// 日本時間の ISO（分まで）。run-name の末尾に出て、予備の定時の回と突き合わせる鍵になる
export function jstIso(ms) {
  return new Date(ms + 9 * 3600000).toISOString().slice(0, 16) + "+09:00";
}

// 窓（起きた時刻から lookback 分さかのぼる。起きた時刻を含み、始まりは含まない）に予定の時刻が入る行。
// fresh は今回が初めて見る予定（前の回の窓に入っていない）
export function due(entries, tickMs, lookbackMin, tickMin) {
  const end = Math.floor(tickMs / 60000) * 60000;
  const out = [];
  for (let k = lookbackMin - 1; k >= 0; k--) {
    const ms = end - k * 60000;
    const d = new Date(ms);
    for (const e of entries) {
      if (matches(e, d)) out.push({ e, ms, at: jstIso(ms), fresh: k < tickMin });
    }
  }
  return out;
}

// GitHub のヘッダーの形（2026-12-31 00:00:00 UTC・+0900）を ISO（UTC）に。無い・読めなければ空
export function expiryIso(h) {
  const m = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})\s*(UTC|Z|[+-]\d{2}:?\d{2})?$/.exec(String(h || "").trim());
  if (!m) return "";
  const off = !m[3] || m[3] === "UTC" || m[3] === "Z" ? "Z" : `${m[3].slice(0, 3)}:${m[3].slice(-2)}`;
  const t = Date.parse(`${m[1]}T${m[2]}${off}`);
  return Number.isNaN(t) ? "" : new Date(t).toISOString().replace(/\.\d{3}Z$/, "Z");
}

// その予定の回がもう作られているか（この Worker が起動した回か、予備の GitHub の定時の回）
export function alreadyStarted(runs, it) {
  for (const r of runs || []) {
    if (Date.parse(r.created_at) < it.ms - 60000) continue;
    const title = String(r.display_title || "");
    if (r.event === "workflow_dispatch") {
      const m = TITLE_AT.exec(title);
      if (m && Date.parse(m[1]) === it.ms) return r;
    } else if (r.event === "schedule" && title.endsWith(" " + it.e.cron)) {
      return r;
    }
  }
  return null;
}

const list = (v, lo, hi) => v === null || (Array.isArray(v) && v.length > 0 && v.every((x) => Number.isInteger(x) && x >= lo && x <= hi));

// master から読んだ表を使ってよいか（起動先のリポジトリ・ブランチは配ったときの表から変えさせない）
export function validTable(t, base) {
  return !!t && t.version === base.version && t.repo === base.repo && t.ref === base.ref &&
    Array.isArray(t.entries) && t.entries.length > 0 &&
    t.entries.every((e) => e && typeof e.wf === "string" && /^[A-Za-z0-9._-]+\.ya?ml$/.test(e.wf) &&
      typeof e.cron === "string" && list(e.minute, 0, 59) && list(e.hour, 0, 23) && list(e.dom, 1, 31) &&
      list(e.month, 1, 12) && list(e.dow, 0, 6) && !!e.inputs && typeof e.inputs === "object" &&
      Object.values(e.inputs).every((v) => typeof v === "string"));
}

const line = (o) => JSON.stringify({ at: new Date().toISOString(), ...o });

async function loadTable(f, log) {
  try {
    const r = await f(BUNDLED.table_url, { headers: { "User-Agent": UA }, signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (r.ok) {
      const t = await r.json();
      if (validTable(t, BUNDLED)) return t;
      log.warn(line({ result: "table_invalid", msg: "master の表の形が違うため、配ったときの表を使います" }));
    } else {
      log.warn(line({ result: "table_unreadable", status: r.status, msg: "master の表を読めないため、配ったときの表を使います" }));
    }
  } catch (e) {
    log.warn(line({ result: "table_unreadable", error: String(e && e.message || e).slice(0, 200) }));
  }
  return BUNDLED;
}

function client(f, token) {
  let expiry = "";
  const call = async (method, path, body) => {
    const headers = {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": UA,
    };
    if (body) headers["Content-Type"] = "application/json";
    const res = await f(`${API}${path}`, {
      method, headers, body: body ? JSON.stringify(body) : undefined, signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    const exp = expiryIso(res.headers.get("github-authentication-token-expiration"));
    if (exp) expiry = exp;
    const text = await res.text();
    if (!res.ok) {
      const err = new Error(text.slice(0, 200));
      err.status = res.status;
      throw err;
    }
    return text ? JSON.parse(text) : {};
  };
  const repo = BUNDLED.repo;
  return {
    expiry: () => expiry,
    // 予定の1分前より後に作られた回だけを読む（応答を小さく保つ。無料プランの CPU は1回10ミリ秒）
    runs: async (wf, sinceMs) => {
      const since = new Date(sinceMs).toISOString().replace(/\.\d{3}Z$/, "Z");
      const q = `per_page=20&exclude_pull_requests=true&created=${encodeURIComponent(">=" + since)}`;
      return (await call("GET", `/repos/${repo}/actions/workflows/${wf}/runs?${q}`)).workflow_runs || [];
    },
    dispatch: (wf, inputs) => call("POST", `/repos/${repo}/actions/workflows/${wf}/dispatches`, { ref: BUNDLED.ref, inputs }),
  };
}

async function handle(it, gh, sleep, log) {
  const base = { wf: it.e.wf, label: it.e.label, scheduled_for: it.at, ...it.e.inputs };
  for (let n = 1; n <= RETRY_WAIT_MS.length + 1; n++) {
    if (n > 1) await sleep(RETRY_WAIT_MS[n - 2]);
    try {
      const hit = alreadyStarted(await gh.runs(it.e.wf, it.ms - 60000), it);
      if (hit) {
        // 前の回が起動した予定を次の回が確かめただけのときは書かない（ログが倍になる）
        if (it.fresh || n > 1) log.log(line({ ...base, result: "exists", run: hit.html_url, attempt: n }));
        return "exists";
      }
    } catch (e) {
      log.error(line({ ...base, result: "check_failed", status: e.status || 0, error: String(e.message || e).slice(0, 200), attempt: n }));
      if (e.status === 401) return "auth";
      continue; // 起動済みか確かめられないうちは起動しない（同じ予定を2回起動しない）
    }
    try {
      const r = await gh.dispatch(it.e.wf, { ...it.e.inputs, scheduled_for: it.at, token_expiry: gh.expiry() });
      log.log(line({ ...base, result: "dispatched", run: r.html_url || "", attempt: n }));
      return "dispatched";
    } catch (e) {
      log.error(line({ ...base, result: "dispatch_failed", status: e.status || 0, error: String(e.message || e).slice(0, 200), attempt: n }));
      if (e.status === 401) return "auth";
      if (e.status === 404 || e.status === 422) return "rejected"; // ワークフローが無い・入力が合わない（やり直しても同じ）
    }
  }
  log.error(line({ ...base, result: "gave_up", msg: "予備の GitHub の定時が遅れて動きます" }));
  return "gave_up";
}

export async function tick(scheduledTime, env, deps = {}) {
  const f = deps.fetch || ((...a) => fetch(...a));
  const sleep = deps.sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
  const log = deps.log || console;
  const table = await loadTable(f, log);
  const items = due(table.entries, scheduledTime, BUNDLED.lookback_minutes, BUNDLED.tick_minutes);
  if (!items.length) return [];
  const token = String((env && env.GITHUB_TOKEN) || "").trim();
  if (!token) {
    log.error(line({ result: "no_token", msg: "GITHUB_TOKEN が未設定です（python scripts/scheduler_deploy.py --set-token）" }));
    return items.map(() => "no_token");
  }
  const gh = client(f, token);
  const out = [];
  for (const it of items) {
    const r = await handle(it, gh, sleep, log);
    out.push(r);
    if (r === "auth") {
      log.error(line({ result: "auth", msg: "鍵が通りません（失効・権限）。python scripts/scheduler_deploy.py --set-token で入れ直す" }));
      break;
    }
  }
  return out;
}
