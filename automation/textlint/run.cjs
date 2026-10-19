// 記事の本文を textlint に当てる（scripts/ai_writing.py が呼ぶ）。標準入力の JSON:
//   {"config": ".textlintrc.json のパス", "mode": "lint" | "fix", "items": [{"name": "...", "text": "..."}]}
// 標準出力の JSON: [{"name", "messages": [...], "output"?: 直した全文 (fix のとき), "error"?: 理由}]
// 1本ずつ受け止める（あるルールが特定の文で落ちても、ほかの記事の結果を失わない。CLI は1本の失敗で全部止まった）
"use strict";
const path = require("path");
const { createLinter, loadTextlintrc } = require("textlint");

async function main() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  const req = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const descriptor = await loadTextlintrc({
    configFilePath: req.config,
    node_modulesDir: path.join(__dirname, "node_modules"),
  });
  const linter = createLinter({ descriptor, cwd: __dirname });
  const out = [];
  for (const it of req.items) {
    const file = path.join(__dirname, "_input", `${it.name}.md`);
    try {
      if (req.mode === "fix") {
        const r = await linter.fixText(it.text, file);
        out.push({ name: it.name, output: r.output, messages: r.remainingMessages || [],
                   applied: (r.applyingMessages || []).map((m) => ({ ruleId: m.ruleId, line: m.line })) });
      } else {
        const r = await linter.lintText(it.text, file);
        out.push({ name: it.name, messages: r.messages });
      }
    } catch (e) {
      out.push({ name: it.name, messages: [], error: String((e && e.message) || e).slice(0, 300) });
    }
  }
  process.stdout.write(JSON.stringify(out));
}

main().catch((e) => {
  process.stderr.write(String((e && e.stack) || e));
  process.exit(1);
});
