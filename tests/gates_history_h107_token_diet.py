# -*- coding: utf-8 -*-
"""2026-10-17 の「自動運用のトークンを減らす・実行時間を縮める」の門。

  1. claude は起動時に CLAUDE.md（約7.8万字）を文脈に入れ、1手ごとに読み直す。記事を書く AI は1本で100手を超えるのに、
     導入・納品方式・週次の工程表など書く仕事に使わない章が毎手の大半を占めていた → CI の AI の間だけ要る章に絞る
  2. 1手で答えるだけの呼び出し（台本・訳・返信案）も CLAUDE.md を丸ごと読んでいた → CLAUDE.md の無い場所で起こす
  3. 週次の実測で ai_cite_check が未定義の変数で毎回落ちていた（引用の実測が記録されない）
  4. 週次の実測で速度（約3分）とAIへの質問（約4分）を順に待っていた → 同時に回す
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_claude_md_is_slimmed_for_ci_agents_and_restored():
    import agent_memory as M
    print("\n■ CLAUDE.md は芯だけ・全文は docs/pipeline/。CI の AI には書く仕事に要る章の全文を組み立てて渡す（戻すのは芯）")
    core = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    full = M.source()
    pdir = ROOT / M.PIPELINE
    check("docs/pipeline/ のファイルと PARTS が一致する（足したファイルが組み立てから漏れない）",
          sorted(p.name for p in pdir.glob("*.md")), sorted(M.PARTS))
    th = [M._title(b, 2) for b in M._blocks(full, 2)]
    want = ("トリガー", "0.1", "0.2", "0.3", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.", "付録")
    check("全文に全部の章が順にそろう（移すときに章を落としていない）",
          [next((i for i, t in enumerate(th) if t.startswith(w)), -1) for w in want] == sorted(
              next((i for i, t in enumerate(th) if t.startswith(w)), -1) for w in want) and all(
              any(t.startswith(w) for t in th) for w in want), True)
    check("芯は2万字以内で、全文の25%未満（起動のたびに読む量）", (len(core) <= 20000, len(core) < len(full) * 0.25), (True, True))
    check("芯の索引が docs/pipeline/ の全ファイルを指す", [p for p in M.PARTS if f"docs/pipeline/{p}" not in core], [])
    check("芯に守秘の「守ること」と公開の基準が残る",
          [w in core for w in ("PUBLIC_KEYS", "private_store.require", "pull_request_target", "::add-mask::",
                               "一次性80点以上", "75点以上", "85点以上", "目標90点", "build.py` がビルド対象から除外")], [True] * 9)
    w = M.slim(full, "writer")
    heads = [ln for ln in w.splitlines() if ln.startswith("#")]
    has = lambda pre: any(h.lstrip("# ").startswith(pre) for h in heads)
    check("writer: 0章・Phase 2〜6・6章・付録の全文が残る",
          [has(p) for p in ("0.1", "0.3", "Phase 2", "Phase 3", "Phase 5", "Phase 6", "6.", "付録")], [True] * 8)
    check("writer: 6章と Phase 5 の本文は docs/pipeline/ と1字も違わない",
          [b in w for b in M._blocks((pdir / "06-quality-rules.md").read_text(encoding="utf-8"), 2)]
          + [s in w for s in M._blocks((pdir / "04-phases.md").read_text(encoding="utf-8"), 3)
             if M._title(s, 3).startswith(("Phase 2", "Phase 3", "Phase 4", "Phase 5", "Phase 6"))], [True] * 6)
    check("writer: 導入・納品・守秘の置き場・週次・Phase 7・在庫の作り方は載せない",
          [has(p) for p in ("2.1", "3.0", "3.0.1", "8.", "Phase 7", "9.", "10.")] + ["在庫の作り方" in w], [False] * 8)
    wk = M.slim(full, "weekly")
    # AI に渡る量が元（移す前の CLAUDE.md＝全文。CI の外の呼び出しはこれを丸ごと読んでいた）より減ったこと
    check("writer: 全文の35%未満・weekly: 全文の65%未満", (len(w) < len(full) * 0.35, len(wk) < len(full) * 0.65), (True, True))
    check("weekly: 8章（週次最適化）を足す", ("## 8." in wk, "## 8." in w), (True, False))
    check("先頭に絞った印がある（二重に絞らない・戻す判定）", w.startswith(M.MARK), True)
    fake = "# t\n## 0.1 a\nx\n## 3. b\n```\n## 0.9 コードの中\n```\n## 6. c\ny\n"
    check("コードブロックの中の見出しでは分けない", "コードの中" in M.slim(fake, "writer"), False)

    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["git", "init", "-q", d], check=True)
        (Path(d) / "CLAUDE.md").write_text(core, encoding="utf-8")
        (Path(d) / M.PIPELINE).mkdir(parents=True)
        for p in M.PARTS:
            (Path(d) / M.PIPELINE / p).write_text((pdir / p).read_text(encoding="utf-8"), encoding="utf-8")
        subprocess.run(["git", "-C", d, "add", "CLAUDE.md"], check=True)
        subprocess.run(["git", "-C", d, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], check=True)
        old = os.environ.get("GITHUB_ACTIONS")
        os.environ["GITHUB_ACTIONS"] = "true"
        try:
            first = M.write_slim("writer", d)
            again = M.write_slim("writer", d)
            mid = (Path(d) / "CLAUDE.md").read_text(encoding="utf-8")
            slimmed = mid.startswith(M.MARK) and mid == M.slim(full, "writer")
            M.restore(d)
        finally:
            if old is None:
                os.environ.pop("GITHUB_ACTIONS", None)
            else:
                os.environ["GITHUB_ACTIONS"] = old
        back = (Path(d) / "CLAUDE.md").read_text(encoding="utf-8")
    check("組み立てる（docs/pipeline/ から）→ 二度目は触らない → 戻すと芯と同じ", (first, again, slimmed, back == core),
          (True, False, True, True))

    import agent_guard as G
    check("戻し損ねても protect が CLAUDE.md を HEAD へ戻す・全文の docs/pipeline も守る場所",
          ("CLAUDE.md" in G.PROTECTED, M.PIPELINE in G.PROTECTED), (True, True))
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    i, j = wf.find("agent_memory.py --slim writer"), wf.find("agent_memory.py --restore")
    k = wf.find('claude -p "$(cat automation/multi_site_prompt.txt)"')
    check("記事の枠: 執筆の前に絞り、試し直しの輪の後で戻す", (0 < i < k < j), True)
    sh = (ROOT / "scripts" / "agent_passes.sh").read_text(encoding="utf-8")
    a, b, c = sh.find("agent_memory.py --slim"), sh.find("  claude -p \"$(cat"), sh.find("agent_memory.py --restore")
    check("範囲ごとの AI の回: claude の前に絞り、後で戻す", 0 < a < b < c, True)
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次の AI の回は 8章を載せる版", "AGENT_MEMORY=weekly AGENT_WORK_KIND=weekly bash scripts/agent_passes.sh automation/weekly_optimize_prompt.txt" in wk, True)


def test_one_turn_calls_run_without_claude_md():
    import auto_rewrite as AR
    print("\n■ 1手で答えるだけの呼び出しは CLAUDE.md の無い場所で起こす。ファイルを読む呼び出しは ROOT のまま")
    seen = []
    real = AR._run      # 起動は AR._run を通る（Windows は Popen なので subprocess.run の差し替えでは止まらない。2026-10-20）

    def fake(args, cwd=None, **kw):
        seen.append(Path(cwd))
        return subprocess.CompletedProcess(args, 0, "", "")
    AR._run = fake
    try:
        AR.sh(["claude", "-p", "--max-turns", "1"], stdin_text="x")
        AR.sh(["claude", "-p", "--max-turns", "40", "--allowedTools", "Read,Edit"], stdin_text="x")
        AR.sh(["claude", "-p", "--max-turns", "1"], stdin_text="x", cwd=ROOT / "scripts")
    finally:
        AR._run = real
    check("1手: ROOT の外・CLAUDE.md が無い", (seen[0] != ROOT, (seen[0] / "CLAUDE.md").exists()), (True, False))
    check("40手（Read・Edit）: ROOT", seen[1], ROOT)
    check("呼ぶ側が場所を決めていればそのまま", seen[2], ROOT / "scripts")


def test_weekly_cite_check_runs_and_cwv_overlaps():
    print("\n■ 週次の実測: ai_cite_check が落ちない・速度の実測はAIへの質問と同時に回す")
    src = (ROOT / "scripts" / "ai_cite_check.py").read_text(encoding="utf-8")
    check("quiet を社ごとに決めてから使う（未定義で毎週落ちていた）",
          0 < src.find("quiet = S.is_client(sid)") < src.find("if quiet:"), True)
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    bg, cite, wait = wk.find("cwv_check.py > /tmp/measure_cwv.txt 2>&1 &"), wk.find("ai_cite_check.py --limit 5"), wk.find('wait "$CWV_PID"')
    check("速度の実測を裏で始め、AIへの質問の後で待って結果を集める", 0 < bg < cite < wait, True)
    check("待った後に速度の結果を要対応の集計（/tmp/measure.txt）へ足す", "tee -a /tmp/measure.txt < /tmp/measure_cwv.txt" in wk, True)


def test_eyecatch_line_and_public_run_keys():
    import make_images as MI
    import kw_plan as K
    print("\n■ 画像を作った記事に eyecatch: を足す・在庫を組んだ月の記録は公開の id で書く")
    slug = "zz-h107-eyecatch"
    img = ROOT / "site" / "images" / slug
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / f"{slug}.md"
        p.write_text("---\ntitle: t\ndiagrams:\n  - name: a\n    items: [\"x\"]\n---\n本文\n", encoding="utf-8")
        img.mkdir(parents=True, exist_ok=True)
        try:
            none = MI.ensure_eyecatch_line(p, slug)
            (img / "eyecatch.png").write_bytes(b"x")
            added = MI.ensure_eyecatch_line(p, slug)
            twice = MI.ensure_eyecatch_line(p, slug)
            text = p.read_text(encoding="utf-8")
        finally:
            for f in img.glob("*"):
                f.unlink()
            img.rmdir()
    import yaml
    fm = yaml.safe_load(text.split("---")[1])
    check("画像があれば1回だけ足す・本文は残る・YAML として読める",
          (none, added, twice, fm.get("eyecatch"), text.rstrip().endswith("本文")),
          (False, True, False, f"/images/{slug}/eyecatch.png", True))
    import sites as S
    cl = next((s for s in S.load_all() if S.is_client(s) and S.public_id(s) != s), None)
    if cl:
        check("お客様の社の記録の鍵は公開の id", K._run_key(cl), S.public_id(cl))
    import json
    keys = set(json.loads((ROOT / "data" / "kw_plan_runs.json").read_text(encoding="utf-8")))
    check("公開側の記録に社の id（公開の id と違うもの）が無い",
          sorted(k for k in keys if k in S.load_all() and S.public_id(k) != k), [])


def test_after_gate_does_not_treat_shallow_checkout_as_new():
    import kw_gate as KG
    print("\n■ 食い合いの検査（--after）: 浅い取得で記事を書かなかった回に、全記事を新しい記事として隔離しない")
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "src", Path(d) / "dst"
        (src / "articles").mkdir(parents=True)
        g = lambda *a, cwd=src: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
        g("init", "-q")
        for i in range(3):
            (src / "articles" / f"a{i}.md").write_text(f"---\nkeyword: 語{i}\n---\n本文\n", encoding="utf-8")
        g("add", "-A"); g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "1")
        (src / "x.txt").write_text("x", encoding="utf-8")
        g("add", "-A"); g("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "2")
        subprocess.run(["git", "clone", "-q", "--depth", "1", "--no-local", str(src), str(dst)], capture_output=True)
        old = KG.ROOT
        KG.ROOT = dst
        try:
            none = KG.written_keyword("ai-lab")
            (dst / "articles" / "new1.md").write_text("---\nkeyword: 新しい語\n---\n本文\n", encoding="utf-8")
            one = KG.written_keyword("ai-lab")
        finally:
            KG.ROOT = old
    check("浅い取得・新しい記事なし → 0本（以前は全記事を拾った）", none, [])
    check("浅い取得・新しい記事1本 → その1本だけ", [s for s, _ in one], ["new1"])
    check("新しい記事が上限を超えたら隔離しない", 0 < KG.MAX_NEW <= 10, True)


def test_rewrite_guard_blocks_only_new_cannibalization():
    print("\n■ 書き直しの食い合いの検査: 直す前の題でも同じ判定なら止めない（悪化したときだけ止める）")
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    body = src[src.index("def check(slug, before"):src.index("def mechanically_fixable")]
    check("直す前の題（before[0]）でも検査し、悪化したときだけ戻す",
          ('"--title", before[0]' in body, "r.returncode > r0" in body, "r.returncode == 3 or" in body), (True, True, True))
    check("--slugs: 選んだ記事だけにする（材料の要る種類は候補に無ければ飛ばす）",
          ("def pick_slugs" in src, 'kind in ("title", "question", "fresh")' in src), (True, True))


def test_actions_are_pinned_to_commit():
    import re
    print("\n■ 公開リポジトリ: 外のアクションは版の記号ではなくコミットの番号で固定する（記号は付け替えられる）")
    files = list((ROOT / ".github" / "workflows").glob("*.yml")) + list((ROOT / ".github" / "actions").glob("*/action.yml"))
    loose = [f"{f.name}: {m.group(1)}" for f in files for m in
             re.finditer(r"uses:\s*([\w-]+/[\w./-]+@(?![0-9a-f]{40}\b)[^\s#]+)", f.read_text(encoding="utf-8"))]
    check("番号で固定していない外のアクション", loose, [])
    check("固定したアクションには元の版を注記する（Dependabot が更新できる）",
          all(re.search(r"@[0-9a-f]{40} # v\d", ln) for f in files for ln in f.read_text(encoding="utf-8").splitlines()
              if re.search(r"uses:\s*[\w-]+/[\w./-]+@[0-9a-f]{40}", ln)), True)
    dep = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    check("Dependabot がアクションの番号を更新する", "github-actions" in dep, True)
