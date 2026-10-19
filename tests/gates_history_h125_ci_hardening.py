# -*- coding: utf-8 -*-
"""2026-10-20 全体点検（担当6: 自動運用の手順・守秘）の門。

1. 週次の書き直し・統合（auto_rewrite・auto_merge・retire_stale）、集中モードの書き直し、月次の改善の実行（report_actions）は
   中から AI を呼ぶのに、作業場に鍵（Google の鍵・push の資格・.env）と全権の合言葉（HUB_SECRET）を置いたまま動いていた。
   記事の枠と同じく agent_guard の --lock／--verify と --protect／--unlock（always）で挟み、管制塔へは通行証で入る
2. 自動修復の案の取り込み（patch_policy）: 記事・データの変更、scripts/ の新しいファイル・40行を超える書き足し、
   文字列の連結で名前を隠す書き方、ファイルへの書き込み・写しは枝へ回す
3. 当社の料金の額を公開側（data/price_ranges.json・門の例）に書いていた（門 h76 が data/・tests/ も見る）
4. CI のログで伏せる語（ci_mask）: 社が特定できる語（社名・ドメイン・題・slug）は上限の外で全部伏せる
5. 週次がラッコの古い利用記録を rakko- の鍵で残し、毎日の見張りが前方一致で戻して消費を失いえた
6. zizmor（運用者の指示）: ワークフローの危ない書き方を直し、週次の読むだけの検査で ZIZMOR_OK を出す
お客様の語は書かない（client-zz・zz.example）。本物の通信・課金・本番の書き込みはしない。
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from unittest import mock

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
WF = ROOT / ".github" / "workflows"
ACT = ROOT / ".github" / "actions"
# 中から AI を呼ぶ道具（書く回だけ）
AI_TOOL = re.compile(r"scripts/(?:auto_rewrite|auto_merge|retire_stale)\.py[^\n]*--write|scripts/report_actions\.py --apply")


def _y(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _run(s):
    return str(s.get("run") or "")


# ── 1. AI を呼ぶ道具は鍵を外した作業場で動く ─────────────────────────────

def jail_problems(y):
    """AI を呼ぶ道具の工程のうち、鍵を外した作業場で動いていないもの [(ジョブ, 工程, 理由)]"""
    import agent_guard as AG
    out = []
    for jn, job in (y.get("jobs") or {}).items():
        steps = job.get("steps") or []
        locked = False
        for i, s in enumerate(steps):
            run = _run(s)
            if "agent_guard.py --lock" in run:
                locked = True
                continue
            if "agent_guard.py --unlock" in run:
                locked = False
                continue
            env = s.get("env") or {}
            if locked and "agent_guard.py --protect" not in run:
                bad = sorted(k for k in env if k in AG.KNOWN_SECRETS)
                if bad:
                    out.append((jn, s.get("name"), "鍵を外した間に鍵を渡す: " + ",".join(bad)))
            if not AI_TOOL.search(run):
                continue
            if not locked:
                out.append((jn, s.get("name"), "鍵を外さずに AI を呼ぶ"))
            if env.get("HUB_SECRET", None) != "":
                out.append((jn, s.get("name"), "全権の合言葉を空にしていない"))
            first = AI_TOOL.search(run).start()
            if "agent_guard.py --verify" not in run or run.index("agent_guard.py --verify") > first:
                out.append((jn, s.get("name"), "--verify より前に AI を呼ぶ"))
            if "HUB_AGENT_TOKEN" not in run:
                out.append((jn, s.get("name"), "通行証を渡していない"))
            rest = steps[i + 1:]
            prot = next((k for k, t in enumerate(rest) if "agent_guard.py --protect" in _run(t)), None)
            unl = next((k for k, t in enumerate(rest) if "agent_guard.py --unlock" in _run(t)), None)
            add = next((k for k, t in enumerate(rest) if re.search(r"git add (-A|-f|--)", _run(t))), len(rest))
            if prot is None or unl is None or not (prot < unl <= add) \
                    or "always()" not in str(rest[prot].get("if", "")) or "always()" not in str(rest[unl].get("if", "")):
                out.append((jn, s.get("name"), "AI の後に always で戻して（--protect・--unlock）から git add していない"))
        if locked:
            out.append((jn, "（最後）", "鍵を外したまま終わる"))
    return out


def test_ai_tool_steps_run_in_the_jail():
    print("\n■ 週次・集中モード・月次の AI を呼ぶ道具は、鍵を外した作業場で、通行証で動く（2026-10-20）")
    bad = {"jobs": {"x": {"steps": [
        {"name": "直す", "env": {"HUB_SECRET": "${{ secrets.HUB_SECRET }}"},
         "run": "python scripts/auto_rewrite.py --write --limit 3"},
        {"name": "保存", "run": "git add -A"}]}}}
    good = {"jobs": {"x": {"steps": [
        {"name": "外す", "run": "python scripts/agent_guard.py --lock"},
        {"name": "直す", "env": {"HUB_SECRET": "", "CLAUDE_CODE_OAUTH_TOKEN": "x"},
         "run": "python scripts/agent_guard.py --verify\nexport HUB_AGENT_TOKEN=x\npython scripts/auto_merge.py --write"},
        {"name": "戻す", "if": "always()", "run": "python scripts/agent_guard.py --protect"},
        {"name": "鍵", "if": "always()", "env": {"SITE_PUSH_TOKEN": "x"}, "run": "python scripts/agent_guard.py --unlock"},
        {"name": "保存", "run": "git add -A"}]}}}
    check("検出器: 鍵を外さず・合言葉のまま・確かめずに AI を呼ぶ工程を拾う",
          sorted({w for _j, _s, w in jail_problems(bad)}),
          sorted({"鍵を外さずに AI を呼ぶ", "全権の合言葉を空にしていない", "--verify より前に AI を呼ぶ", "通行証を渡していない",
                  "AI の後に always で戻して（--protect・--unlock）から git add していない"}))
    check("検出器: 挟んだ形は通す", jail_problems(good), [])
    leak = {"jobs": {"x": {"steps": [
        {"name": "外す", "run": "python scripts/agent_guard.py --lock"},
        {"name": "訳す", "env": {"SITE_PUSH_TOKEN": "x"}, "run": "python scripts/i18n.py --publish"},
        {"name": "鍵", "if": "always()", "run": "python scripts/agent_guard.py --unlock"}]}}}
    check("検出器: 鍵を外した間に配信の鍵を渡す工程を拾う", len(jail_problems(leak)), 1)
    for name in ("weekly-optimize.yml", "focus-mode.yml", "monthly-report.yml"):
        y = _y(name)
        check(f"{name}: AI を呼ぶ道具は鍵を外した作業場で、通行証で動き、戻してから保存する", jail_problems(y), [])
    wk = _y("weekly-optimize.yml")["jobs"]["optimize"]["steps"]
    names = [s.get("name") for s in wk]
    i18n = names.index("多言語の要約を訳す（指示のある社だけ・週10記事）")
    unl = [i for i, s in enumerate(wk) if "agent_guard.py --unlock" in _run(s)]
    check("週次: 配信先へ push する多言語の要約は、鍵を戻した後に回す", any(i < i18n for i in unl), True)
    roll = next(s for s in wk if "rewrite_rollback.py --write" in _run(s))
    check("週次: 戻し・統合・鮮度の工程に配信の鍵を渡さない",
          sorted(k for k in (roll.get("env") or {}) if k in ("SITE_PUSH_TOKEN", "FTP_CREDENTIALS_JSON", "WP_CREDENTIALS_JSON")), [])


def test_read_only_token_is_enough_for_search_console():
    print("\n■ 鍵を外した後の「読むだけの許可証」で、書き直しの候補選び（Search Console・GA4）が読める")
    import agent_guard as AG
    import gcreds
    import gsc_detail
    check("許可証の範囲は Search Console と GA4 の読むだけ（書き直しの GSC の範囲を含む）",
          (set(gsc_detail.SCOPE) <= set(AG.TOKEN_SCOPES), all(x.endswith(".readonly") for x in AG.TOKEN_SCOPES)), (True, True))
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "indexing-service-account.json"
        p.write_text(json.dumps({"type": gcreds.TOKEN_TYPE, "token": "zz-token", "scopes": AG.TOKEN_SCOPES}), encoding="utf-8")
        c = gcreds.load(p, gsc_detail.SCOPE)
        check("gcreds は許可証を読み、そのまま使える資格を返す", (type(c).__name__, c.token), ("Credentials", "zz-token"))
    direct = [p.name for p in (ROOT / "scripts").glob("*.py")
              if re.search(r"from_service_account_(file|info)", p.read_text(encoding="utf-8", errors="ignore"))]
    check("鍵のファイルを直に読むのは gcreds と agent_guard だけ（ほかは許可証で読める）", sorted(direct), ["agent_guard.py", "gcreds.py"])


def test_agent_guard_stashes_env_and_mints_tools_token():
    print("\n■ agent_guard: .env は作業場所の外へよけて戻す・全社を回す道具の通行証を作る")
    import agent_guard as AG
    import hub_token as HT
    check(".env は鍵のファイルとして外す", ".env" in AG.SECRET_FILES, True)
    with tempfile.TemporaryDirectory() as d:
        root, tmp, home = Path(d) / "repo", Path(d) / "tmp", Path(d) / "home"
        for x in (root / "articles", tmp, home):
            x.mkdir(parents=True)
        (root / ".env").write_text("RESEND_API_KEY=zz-not-a-key\n", encoding="utf-8")
        env = {"RUNNER_TEMP": str(tmp), "AGENT_GUARD_HOME": str(home), "GITHUB_ACTIONS": ""}
        with mock.patch.dict(os.environ, env):
            AG.lock(root, mint=False)
            gone = not (root / ".env").exists()
            stashed = [p for p in (tmp / "agent_guard.stash").glob("*") if p.is_file()]
            probs = [x for x in AG.problems(root, env={}) if ".env" in x]
            AG.lock(root, mint=False)          # 戻さずにもう一度外しても、よけた分の記録を失わない
            ok = AG.unlock(root)
            back = (root / ".env").read_text(encoding="utf-8") if (root / ".env").exists() else ""
        check("lock で .env を作業場所の外へよけ、AI の確かめに残らない・unlock で同じ中身に戻る（2回 lock しても）",
              (gone, len(stashed), probs, ok, back), (True, 1, [], True, "RESEND_API_KEY=zz-not-a-key\n"))
        out = Path(d) / "tok"
        secret = "zz-agent-secret-0123456789"
        with mock.patch.dict(os.environ, {"HUB_AGENT_SECRET": secret, "GITHUB_ACTIONS": ""}):
            made = AG.tools_token(str(out), "ai-lab,corporate")
        good, w, r = HT.verify(out.read_text(encoding="utf-8"), secret) if out.is_file() else (False, [], [])
        check("道具の通行証: 指定した社に書け・読める（管制塔の hub_token と同じ照合）", (made, good, sorted(w), sorted(r)),
              (True, True, ["ai-lab", "corporate"], ["ai-lab", "corporate"]))
        out2 = Path(d) / "tok2"
        with mock.patch.dict(os.environ, {"HUB_AGENT_SECRET": "", "GITHUB_ACTIONS": ""}):
            made2 = AG.tools_token(str(out2))
        check("道具の通行証: 鍵が無ければ作らない", (made2, out2.exists()), (False, False))


def test_monthly_moves_env_and_notifies_after_unlock():
    print("\n■ 月次: 改善の実行の間はメールの鍵（.env）をよけ、人へ知らせる文は鍵を戻した後に送る")
    st = _y("monthly-report.yml")["jobs"]["report"]["steps"]
    act = next(s for s in st if s.get("id") == "actions")
    send = next(s for s in st if s.get("name") == "改善の実行で直した記事をコミットし配信先へ届ける")
    names = [s.get("name") for s in st]
    check("改善の実行の手順に通知の鍵を置かず、知らせる文を一時の場所へ渡す",
          (sorted(k for k in (act.get("env") or {}) if k in ("SLACK_WEBHOOK_URL", "RESEND_API_KEY")),
           "report_actions_notice.txt" in _run(act)), ([], True))
    check("鍵を戻した後の手順が、知らせる文を送る",
          ("report_actions_notice.txt" in _run(send) and "notify_slack.py" in _run(send),
           names.index("改善の実行の後に作業場へ鍵を戻す") < names.index(send.get("name"))), (True, True))


# ── 2. 自動修復の案の取り込み ─────────────────────────────────────────

def _patch(path, added, new=False):
    head = f"diff --git a/{path} b/{path}\n"
    if new:
        head += "new file mode 100644\n--- /dev/null\n"
        hunk = f"@@ -0,0 +1,{len(added)} @@\n"
    else:
        head += f"--- a/{path}\n"
        hunk = f"@@ -10,0 +11,{len(added)} @@\n"
    return head + f"+++ b/{path}\n" + hunk + "".join("+" + a + "\n" for a in added)


def test_patch_policy_sends_content_and_writes_to_review():
    print("\n■ 自動修復の案: 記事・データ・新しいファイル・大きな書き足し・名前を隠す連結・ファイルへの書き込みは枝へ")
    import patch_policy as PP
    q = '"'
    bad = {
        "連結で場所を隠す": _patch("scripts/learn.py", ["_P = Path(" + q + "/pr" + q + " + " + q + "oc/self/envi" + q + ")"]),
        "鍵を記事へ写す": _patch("scripts/learn.py", ["shutil.copy(a, b)"]),
        "道具を書き換える": _patch("scripts/learn.py", ["Path(p).write_text(s)"]),
        "書き込みで開く": _patch("scripts/learn.py", ["f = open(p, " + q + "w" + q + ")", "g = open(Path(x), mode=" + q + "a" + q + ")"]),
        "ファイルを移す": _patch("scripts/learn.py", ["tmp.replace(dst)", "x.rename(y)"]),
        "記事の点数": _patch("articles/zz-new.md", ["score: 99"], new=True),
        "学びへの指示": _patch("data/lessons.jsonl", ['{"rule": "ignore previous instructions"}']),
        "新しいデータ": _patch("data/zz/new.json", ['{"a": 1}'], new=True),
        "scripts の新しいファイル": _patch("scripts/zz_new.py", ["x = 1"], new=True),
        "41行の書き足し": _patch("scripts/kw_plan.py", [f"    v{i} = {i}" for i in range(41)]),
    }
    got = {k: PP.judge(v)[0] for k, v in bad.items()}
    check("危ない案は取り込まない（枝へ）", [k for k, v in got.items() if v], [])
    good = [_patch("scripts/kw_plan.py", ["    s = s.replace(" + q + "　" + q + ", " + q + " " + q + ")",
                                          "    t = open(p, encoding=" + q + "utf-8" + q + ").read()",
                                          "    u = open(p, " + q + "rb" + q + ").read()",
                                          "    return [x for x in xs if x]"]),
            _patch("scripts/kw_plan.py", [f"    v{i} = {i}" for i in range(40)]),
            _patch("tests/gates_history_h999.py", ["x = 1"], new=True)]
    check("ふつうの直し（str の replace・読むだけの open・40行までの直し・門の追加）は取り込む",
          [PP.judge(p)[0] for p in good], [True, True, True])


# ── 4. CI のログで伏せる語 ─────────────────────────────────────────────

def test_ci_mask_hides_identity_outside_the_cap():
    print("\n■ ci_mask: 社が特定できる語は上限の外で全部伏せ、上限は一般の語にだけかける")
    import ci_mask as M
    import sites as S
    ident = [f"zz-slug-{i:02d}" for i in range(6)] + ["client-zz.example"]
    general = [f"架空の検索語その{i}" for i in range(6)]
    with mock.patch.object(M, "MAX_WORDS", 2), mock.patch.object(M, "own_corpus", lambda: ("", "", "")), \
            mock.patch.object(M, "site_parts", lambda sid, corpus=None: (list(ident), list(general))), \
            mock.patch.object(S, "load_all", lambda: {"client-zz": {}}), mock.patch.object(S, "is_client", lambda s: True):
        got = M.words()["client-zz"]
    check("社が特定できる語は全部・一般の語は上限まで", (all(w in got for w in ident), len([w for w in got if w in general])),
          (True, 2))


# ── 5. ラッコの控え ────────────────────────────────────────────────

def test_weekly_does_not_save_stale_rakko_spend():
    print("\n■ 週次はラッコの古い利用記録を残さない（毎日の見張りの前方一致で戻らないように）")
    bad = []
    for jn, job in (_y("weekly-optimize.yml").get("jobs") or {}).items():
        for s in job.get("steps") or []:
            if not str(s.get("uses", "")).startswith("actions/cache/save"):
                continue
            w = s.get("with") or {}
            if "rakko_spend" in str(w.get("path", "")) or str(w.get("key", "")).startswith("rakko-"):
                bad.append(f"{jn}: {s.get('name')}")
    check("週次の保存に rakko_spend.jsonl・rakko- の鍵が無い", bad, [])


# ── 6. zizmor ─────────────────────────────────────────────────────

def test_zizmor_findings_are_fixed_and_checked_weekly():
    print("\n■ zizmor: 危ない書き方を直し、外す指摘には理由を書き、週次の読むだけの検査で ZIZMOR_OK を出す")
    rep = _y("weekly-optimize.yml")["jobs"]["reports"]["steps"]
    z = next((s for s in rep if "zizmor" in _run(s) and "ZIZMOR_OK" in _run(s)), {})
    run = _run(z)
    check("週次の読むだけの検査が、版を固定した zizmor を中・高で回して印を出す",
          (bool(re.search(r'zizmor==[0-9]+\.[0-9]+\.[0-9]+"', run)), "--min-severity medium" in run,
           ".github/workflows .github/actions" in run, "ZIZMOR_OK=$ok" in run, "要対応:" in run),
          (True, True, True, True, True))
    files = sorted(WF.glob("*.yml")) + sorted(ACT.glob("*/action.yml"))
    no_reason = []
    for p in files:
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = re.search(r"zizmor: ignore\[[a-z-]+\](.*)$", ln)
            if m and len(m.group(1).strip()) < 6:
                no_reason.append(f"{p.name}:{i}")
    check("外す指摘には理由を書く", no_reason, [])
    wide, creds = [], []
    for p in sorted(WF.glob("*.yml")):
        y = yaml.safe_load(p.read_text(encoding="utf-8"))
        jobs = y.get("jobs") or {}
        top = y.get("permissions") or {}
        if len(jobs) > 1 and any(v == "write" for v in top.values()):
            wide.append(p.name)
        lines = p.read_text(encoding="utf-8").splitlines()
        for i, ln in enumerate(lines):
            if re.match(r"^\s*- uses: actions/checkout@", ln):
                block = "\n".join(lines[i:i + 4])
                if "persist-credentials: false" not in block and "zizmor: ignore[artipacked]" not in block:
                    creds.append(f"{p.name}:{i + 1}")
    check("複数のジョブのワークフローは、書き込みの権限をジョブごとに付ける", wide, [])
    check("checkout は資格を残さないか、push する理由を書く", creds, [])
    raw = "\n".join(_run(s) for p in files for j in ((yaml.safe_load(p.read_text(encoding="utf-8")).get("jobs") or {}).values()
                                                    if p.parent == WF else [{"steps": yaml.safe_load(p.read_text(encoding="utf-8"))["runs"]["steps"]}])
                    for s in (j.get("steps") or []))
    check("run に直接埋めない値（入力の社・mode・kinds・ワークフローの名前・落ちた回の名前）",
          [x for x in ("${{ inputs.site }}", "${{ inputs.mode }}", "inputs.kinds", "${{ github.workflow }}",
                       "${{ github.event.workflow_run.name }}", "${{ github.event.inputs.failed }}") if x in raw], [])
