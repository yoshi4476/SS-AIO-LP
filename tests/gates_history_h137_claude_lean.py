# -*- coding: utf-8 -*-
"""2026-10-25 運用者「トークンを削減できるものを、品質に関係ないところには全てに適応」「速度も最速を目指して」。

自動の起動の claude（CI の workflow・scripts/ から起こす claude -p）に、公式の資料で確かめた指定だけを付ける:
- 起動の指定（auto_rewrite.LEAN_ARGS）: --strict-mcp-config（MCP を載せない）・--exclude-dynamic-system-prompt-sections
  （場所ごとに変わる部分を最初の発言へ移し、キャッシュに当てる）。スキルを使えない起動は --disable-slash-commands
- 環境変数（agent_guard.LEAN_ENV）: 更新・送信・題の自動生成を止め、git の手順と写し・自動メモリを文脈から外す
- 版を固定した claude の npm の取得を CI のキャッシュから戻し、pip・apt・npm を同時に入れる

品質に関わるもの（モデル・思考の量・CLAUDE.md・スキル・出力の上限・ターン数）は変えない。
実行の記録（claude_usage.py が ~/.claude/projects を読む）を消す --no-session-persistence は付けない。
context-mode（MCP）は入れない: 任意のコードを動かす道具（ctx_execute）が許可の一覧の外で動き、AI の作業場の拒否
（curl・python -c・非公開の置き場）を迂回できる。効き目の大半は対話用のフック頼み（README）。
"""
import json
import re
import subprocess
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

# 品質・動きに関わるので自動の起動に足してはいけない指定と環境変数
QUALITY_FLAGS = ("--model", "--effort", "--max-turns", "--bare", "--safe-mode", "--system-prompt", "--tools",
                 "--no-session-persistence", "--mcp-config", "--setting-sources")
QUALITY_ENV = ("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "BASH_MAX_OUTPUT_LENGTH", "CLAUDE_CODE_DISABLE_CLAUDE_MDS",
               "CLAUDE_CODE_SIMPLE", "MAX_THINKING_TOKENS", "CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS",
               "MAX_MCP_OUTPUT_TOKENS", "CLAUDE_CODE_EFFORT_LEVEL", "DISABLE_PROMPT_CACHING")


def _joined(text):
    return re.sub(r"\\\n\s*", " ", text)


def _claude_lines(text):
    """claude -p から --max-turns の行の終わりまで（指示に改行を含む起動も1つにまとめる）"""
    return [m.group(0) for m in re.finditer(r"(?s)\bclaude\s+-p\b.*?--max-turns[^\n]*", _joined(text))]


def test_lean_constants_do_not_touch_quality():
    import agent_guard as G
    import auto_rewrite as AR
    print("\n■ 当てる指定と環境変数は、品質に関わらないものだけ")
    check("起動の指定", AR.LEAN_ARGS, ["--strict-mcp-config", "--exclude-dynamic-system-prompt-sections"])
    check("環境変数", sorted(G.LEAN_ENV), sorted(["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER",
                                               "CLAUDE_CODE_DISABLE_TERMINAL_TITLE", "CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS",
                                               "CLAUDE_CODE_DISABLE_AUTO_MEMORY"]))
    check("品質に関わる指定・環境変数を入れていない",
          ([f for f in AR.LEAN_ARGS if f in QUALITY_FLAGS], [k for k in G.LEAN_ENV if k in QUALITY_ENV]), ([], []))
    env = G.child_env({"PATH": "p", "DISABLE_AUTOUPDATER": "0"})
    check("道具から呼ぶ claude に渡る・呼ぶ側が決めた値はそのまま",
          (all(k in env for k in G.LEAN_ENV), env["DISABLE_AUTOUPDATER"]), (True, "0"))


def test_lean_args_keep_skills_where_ai_can_use_them():
    import auto_rewrite as AR
    import quality_loop as Q
    print("\n■ 起動の指定: 全部の claude -p に付ける。スキルの一覧を外すのは、スキルを使えない起動だけ")
    one = AR.lean(["claude", "-p", "--max-turns", "1", "--model", "m"])
    check("1手: 指定が -p の直後に付き、元の引数は順も値も同じ・スキルの一覧は外す",
          (one[:2], [a for a in one if a not in AR.LEAN_ARGS + ["--disable-slash-commands"]],
           "--disable-slash-commands" in one), (["claude", "-p"], ["claude", "-p", "--max-turns", "1", "--model", "m"], True))
    check("二度通しても重ねない", AR.lean(one), one)
    rw = AR.lean(AR.claude_args(["zz-a"], 40))
    check("書き直し（Read・Edit だけ・dontAsk）: 指定が付き、スキルは使えないので一覧も外す",
          (all(a in rw for a in AR.LEAN_ARGS), "--disable-slash-commands" in rw, rw[rw.index("--max-turns") + 1]),
          (True, True, "40"))
    sc = AR.lean(Q.scorer_args())
    check("採点（Read だけ・dontAsk）: 指定が付き、モデルと手数は同じ",
          (all(a in sc for a in AR.LEAN_ARGS), "--disable-slash-commands" in sc,
           sc[sc.index("--max-turns") + 1], AR.model_args() == [] or sc[sc.index("--model") + 1] == AR.model_args()[1]),
          (True, True, "4", True))
    skill = json.dumps({"permissions": {"allow": ["Read", "Skill(fact-checker)"], "defaultMode": "dontAsk"}})
    sk = AR.lean(["claude", "-p", "--max-turns", "40", "--settings", skill])
    check("許可に Skill がある起動はスキルを残す", ("--disable-slash-commands" in sk, all(a in sk for a in AR.LEAN_ARGS)),
          (False, True))
    free = AR.lean(["claude", "-p", "--max-turns", "12", "--allowedTools", "Read"])
    check("dontAsk でない複数手の起動もスキルを残す（使えるかを決めつけない）", "--disable-slash-commands" in free, False)
    check("-p の無い呼び出し（--version）には付けない", AR.lean(["claude", "--version"]), ["claude", "--version"])

    seen = []
    real = AR._run

    def fake(args, **kw):
        seen.append((list(args), kw.get("env") or {}))
        return subprocess.CompletedProcess(args, 0, "", "")
    AR._run = fake
    try:
        AR.sh(["claude", "-p", "--max-turns", "1"], stdin_text="x")
        AR.sh(AR.claude_args(["zz-a"], 40), stdin_text="x")
    finally:
        AR._run = real
    import agent_guard as G
    check("sh() を通る claude は全部、指定と環境変数が付く",
          [all(a in s for a in AR.LEAN_ARGS) and all(e.get(k) for k in G.LEAN_ENV) for s, e in seen], [True, True])


def test_direct_claude_calls_in_scripts_are_lean():
    print("\n■ scripts/ で sh() を通らずに claude -p を起こす所も AR.lean を通す")
    bad = []
    for f in sorted((ROOT / "scripts").glob("*.py")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            if re.search(r"subprocess\.(run|Popen)\(\[(AR\.claude_bin\(\)|exe|claude_bin\(\)|\"claude\")\s*,\s*\"-p\"", ln):
                bad.append(f.name)
    check("subprocess で直に起こす claude -p（AR.lean を通していない）", bad, [])


def test_workflow_claude_calls_are_lean():
    import agent_guard as G
    import auto_rewrite as AR
    print("\n■ workflow と agent_passes.sh の claude -p: 指定と環境変数が付く・記事の AI のスキルは残す")
    files = sorted((ROOT / ".github").rglob("*.yml")) + [ROOT / "scripts" / "agent_passes.sh"]
    lines = [(f.name, ln) for f in files for ln in _claude_lines(f.read_text(encoding="utf-8"))]
    check("claude -p の起動が見つかる（数え違いの検知）", len(lines) >= 6, True)
    check("全部の claude -p に起動の指定が付く", [n for n, ln in lines if not all(a in ln for a in AR.LEAN_ARGS)], [])
    check("記事の許可（スキルを使う）の起動はスキルを残す",
          [n for n, ln in lines if "agent_settings_article.json" in ln and "--disable-slash-commands" in ln], [])
    check("保守の許可（Skill の許可なし・dontAsk）の起動はスキルの一覧を外す",
          [n for n, ln in lines if "agent_settings_maint.json" in ln and "--disable-slash-commands" not in ln], [])
    art = json.loads((ROOT / "automation" / "agent_settings_article.json").read_text(encoding="utf-8"))["permissions"]
    mnt = json.loads((ROOT / "automation" / "agent_settings_maint.json").read_text(encoding="utf-8"))["permissions"]
    check("前提: 記事の許可に Skill があり、保守の許可には無い（変えたらこの門の判定も見直す）",
          (any(a.startswith("Skill(") for a in art["allow"]), any(a.startswith("Skill") for a in mnt["allow"])), (True, False))
    check("品質に関わる指定を足していない（--mcp-config・--no-session-persistence・--bare など）",
          [n for n, ln in lines for f in ("--mcp-config", "--no-session-persistence", "--bare", "--safe-mode",
                                         "--setting-sources", "--effort") if f in ln], [])
    sh = (ROOT / "scripts" / "agent_passes.sh").read_text(encoding="utf-8")
    pm = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    step = pm[pm.index("- name: 記事生成（Phase 1〜7）"):pm.index("run: |", pm.index("- name: 記事生成（Phase 1〜7）"))]
    sf = (ROOT / ".github" / "workflows" / "selfheal.yml").read_text(encoding="utf-8")
    check("環境変数: 範囲ごとの AI の回・記事の枠・自動修復のコンテナに全部渡す",
          ([k for k in G.LEAN_ENV if f"{k}=1" not in sh], [k for k in G.LEAN_ENV if f'{k}: "1"' not in step],
           [k for k in G.LEAN_ENV if f"-e {k}=1" not in sf]), ([], [], []))
    check("実行の記録（claude_usage）が読む会話の保存を止めていない",
          [f.name for f in sorted((ROOT / "scripts").glob("*.py")) if "--no-session-persistence" in f.read_text(encoding="utf-8")], [])


def test_no_code_running_mcp_in_ci():
    print("\n■ context-mode などの MCP を CI の AI に渡さない（任意のコードを動かす道具が許可の一覧の外で動く）")
    files = sorted((ROOT / ".github").rglob("*.yml")) + sorted((ROOT / "scripts").glob("*.py")) + \
        [ROOT / "scripts" / "agent_passes.sh", ROOT / "automation" / "ai_container.Dockerfile"]
    check("context-mode・--mcp-config を使う所",
          [f.name for f in files if re.search(r"context-mode|--mcp-config", f.read_text(encoding="utf-8"))], [])
    for name in ("agent_settings_article.json", "agent_settings_maint.json"):
        allow = json.loads((ROOT / "automation" / name).read_text(encoding="utf-8"))["permissions"]["allow"]
        check(f"{name}: MCP の道具を許可しない", [a for a in allow if a.startswith("mcp__")], [])


def test_npm_cli_cache_matches_pinned_version():
    print("\n■ 速さ: 版を固定した claude の npm の取得を控えから戻す（鍵の版と入れる版が同じ）・取得は同時に行う")
    wf = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    bad, users = [], []
    for f in wf:
        t = f.read_text(encoding="utf-8")
        keys = re.findall(r"key:\s*npm-cli-v1-\$\{\{ runner\.os \}\}-claude-code-(\d+\.\d+\.\d+)", t)
        offline = re.findall(r"npm install -g --prefer-offline @anthropic-ai/claude-code@(\d+\.\d+\.\d+)", t)
        if keys or offline:
            users.append(f.name)
            if sorted(set(keys)) != sorted(set(offline)) or not keys or not offline:
                bad.append(f"{f.name}: 鍵{keys} 入れる版{offline}")
            for k in re.finditer(r"key:\s*npm-cli-v1-", t):
                if t.rfind("path: ~/.npm/_cacache", 0, k.start()) < t.rfind("- uses:", 0, k.start()):
                    bad.append(f"{f.name}: 控えの場所が ~/.npm/_cacache でない")
    check("控えの鍵の版と入れる版がそろう", bad, [])
    check("記事の枠・週次・自動修復・動画・集中・旧パイプラインで使う",
          sorted(users), sorted(["daily-video.yml", "focus-mode.yml", "pipeline-multi.yml", "pipeline.yml",
                                 "selfheal.yml", "weekly-optimize.yml"]))
    for name in ("weekly-optimize.yml", "focus-mode.yml", "pipeline.yml"):
        t = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        check(f"{name}: pip・apt・npm を同時に入れ、どれかが失敗したら止める（前と同じ）",
              all(x in t for x in ("& p1=$!", "& p2=$!", "& p3=$!", '[ "$ok" = 1 ] || exit 1')), True)
    sf = (ROOT / ".github" / "workflows" / "selfheal.yml").read_text(encoding="utf-8")
    check("selfheal.yml: 同時に入れ、止めるのは claude が入らなかったときだけ（前と同じ）",
          ("wait $p3 || { cat /tmp/npm.log; exit 1; }" in sf, "wait $p2 || true" in sf), (True, True))
