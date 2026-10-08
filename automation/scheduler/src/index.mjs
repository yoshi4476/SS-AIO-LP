// 定時の起動役（Cloudflare Workers の Cron Triggers）の入口。中身は core.mjs、説明は ../README.md
// ここは default だけを出す（定数や関数を出すと、Workers の実行環境がそれを入口とみなして起動しない。2026-10-08 に手元で確かめた）
import { tick } from "./core.mjs";

export default {
  async scheduled(controller, env) {
    await tick(controller.scheduledTime, env);
  },
};
