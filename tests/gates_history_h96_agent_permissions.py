# -*- coding: utf-8 -*-
"""2026-10-11 点検の指摘。記事を書く AI・自動修復の AI・道具の中から呼ぶ AI の許可が広すぎた所を狭める。
AI は外の文章（字幕・検索上位の見出し・競合のページ）を読むので、仕込まれた指示に従う前提で守る。

  指摘9  `Bash(rm articles/*)` は `rm articles/*` にも一致し、全記事を消せた。消した分は後の git add -A でコミットされ、
         お客様の原稿は非公開の置き場へ「削除」として push される
         → 消せるのは、その回に書いた git 未追跡の原稿だけ（scripts/discard_draft.py）。許可と指示書から rm を外す
  指摘8  `Edit(automation/logs/**)` で、公開側で追跡している台帳（auto_fix.jsonl）・運用者へのメールの本文（findings.txt）まで
         書けた。rewrite_rollback は台帳の before_path を確かめずに、その中身を記事へ書き写していた
         → 記事の AI が書けるのは automation/logs/*.md だけ。直す前の原稿は data/rewrite_before/ の中だけを読む
  指摘3  道具の中から呼ぶ AI（auto_rewrite・auto_merge）は Read が無制限で、鍵のファイルや /proc/<親>/environ（親の python の
         環境変数）を読めた。浮いた枠は鍵を外さずにこの道具を動かすので、許可の deny だけが守りになる
         → 自動修復の AI と同じ Read の拒否を足す（一時フォルダで動かす回にも効く // の絶対の形も）
  指摘13 記事の AI が Bash の grep・ls を拒否されて既存記事を探せなかった → 指示書で Grep・Glob を案内する。
         スキルが一次情報の読み先に挙げる補助金ポータル・TOKYO創業ステーション・arXiv を WebFetch に足す
架空の記事（zz-…）と一時の git で確かめる（本物の記事・作業場所には触れない）
"""
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

AUTO = ROOT / "automation"
FM = "---\ntitle: t\ncategory: aio\n---\nb\n"


def _settings(name):
    with open(AUTO / f"agent_settings_{name}.json", encoding="utf-8") as f:
        return json.load(f)["permissions"]


def _git(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _article_prompts():
    """記事の許可の一覧（agent_settings_article.json）で AI を動かす指示書"""
    out = set()
    for p in (ROOT / ".github" / "workflows").glob("*.yml"):
        t = re.sub(r"\\\n\s*", " ", p.read_text(encoding="utf-8"))
        for m in re.finditer(r'claude\s+-p\s+"\$\(cat (automation/[\w.]+_prompt\.txt)\)"[^\n]*agent_settings_article\.json', t):
            out.add(m.group(1))
        # 範囲ごとに回す手順（scripts/agent_passes.sh）は、記事の許可の一覧で指示書を動かす（2026-10-11）
        for m in re.finditer(r"bash scripts/agent_passes\.sh (automation/[\w.]+_prompt\.txt)", t):
            out.add(m.group(1))
    ap = (ROOT / "scripts" / "agent_passes.sh").read_text(encoding="utf-8")
    if "agent_settings_article.json" not in ap:
        out = {x for x in out if x == "automation/multi_site_prompt.txt"}
    return sorted(out)


def test_discard_draft_removes_only_untracked_drafts():
    print("\n■ discard_draft: 消せるのは、その回に書いた git 未追跡の原稿だけ（一時の git で確かめる）")
    import discard_draft as DD
    with tempfile.TemporaryDirectory(prefix="gate_h96_", ignore_cleanup_errors=True) as td:
        root = Path(td) / "w"
        for d in ("articles", "private/articles", "nested/articles"):
            (root / d).mkdir(parents=True)
        _git(root, "init", "-q")

        def w(rel, text=FM):
            (root / rel).write_bytes(text.encode("utf-8"))
        w("articles/zz-old-post.md")
        _git(root, "add", "-A")
        _git(root, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init")
        w("articles/zz-staged-post.md")
        _git(root, "add", "--", "articles/zz-staged-post.md")
        w("articles/zz-new-draft.md")
        w("articles/zz-client-post.md")
        excl = root / ".git" / "info" / "exclude"
        excl.parent.mkdir(parents=True, exist_ok=True)
        with open(excl, "a", encoding="utf-8", newline="\n") as f:
            f.write("/articles/zz-client-post.md\n")
        w("articles/zz-dup-post.md")
        w("private/articles/zz-dup-post.md")
        w("secret.txt", "s\n")
        w("nested/articles/zz-nested.md")

        bad = ["../secret", "articles/zz-new-draft", "Zz-New-Draft", "", "-rf", "zz-new-draft.md", "*", "..",
               "zz-new-draft/..", "zz new"]
        check("slug が英小文字・数字・ハイフン以外（../・パス・大文字・*・先頭のハイフン・空白）なら何もしない",
              ([s for s in bad if DD.discard(s, root)[0]], (root / "articles" / "zz-new-draft.md").exists(),
               (root / "secret.txt").exists()), ([], True, True))
        names = ("zz-old-post", "zz-staged-post", "zz-client-post", "zz-dup-post", "zz-no-such")
        got = {s: DD.discard(s, root) for s in names}
        check("追跡している記事・git に加えた記事・git から外した原稿（お客様の社）・非公開の置き場にある原稿・無い原稿は消さない",
              ({s: r[0] for s, r in got.items()},
               [s for s in names[:4] if not (root / "articles" / f"{s}.md").exists()]),
              ({s: False for s in names}, []))
        check("断った理由を言う（追跡している・外している・非公開の置き場）",
              ["追跡" in got["zz-old-post"][1], "追跡" in got["zz-staged-post"][1],
               "外している" in got["zz-client-post"][1], "非公開" in got["zz-dup-post"][1]], [True] * 4)
        check("git の作業場所の根でなければ消さない（親のリポジトリへさかのぼって判定しない）",
              (DD.discard("zz-nested", root / "nested")[0], (root / "nested" / "articles" / "zz-nested.md").exists()),
              (False, True))
        ok, _ = DD.discard("zz-new-draft", root)
        check("その回に書いた未追跡の原稿は消せる（ほかは残る）",
              (ok, (root / "articles" / "zz-new-draft.md").exists(),
               sorted(p.name for p in (root / "articles").glob("*.md"))),
              (True, False, ["zz-client-post.md", "zz-dup-post.md", "zz-old-post.md", "zz-staged-post.md"]))
    with contextlib.redirect_stdout(io.StringIO()) as o:
        rc = DD.main(["zz-a", "zz-b"])
    check("1本ずつしか受けない（引数が2つなら何もしない）", (rc, "DISCARD_OK=no" in o.getvalue()), (1, True))
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "discard_draft.py"), "zz-h96-not-there"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    check("道具として呼べて、無い原稿は DISCARD_OK=no・終了コード1", (r.returncode, "DISCARD_OK=no" in r.stdout), (1, True))


def test_agent_settings_drop_rm_and_wide_log_edits():
    print("\n■ 許可の一覧: rm を外し、作業メモは .md だけ、読み先は スキルが挙げるところ")
    art, mnt = _settings("article"), _settings("maint")
    check("許可の一覧は JSON として読める（記事・自動修復）", (bool(art["allow"]), bool(mnt["allow"])), (True, True))
    check("rm の許可が無い（記事・自動修復）", [a for a in art["allow"] + mnt["allow"] if re.match(r"Bash\(\s*rm\b", a)], [])
    need = ["Bash(python scripts/discard_draft.py *)", "Bash(python3 scripts/discard_draft.py *)"]
    check("原稿を消す道具は discard_draft を名指しで許す（記事・自動修復）",
          [n for n in need if n not in art["allow"] or n not in mnt["allow"]], [])
    check("記事の AI が書ける作業メモは automation/logs/*.md だけ（台帳・メールの本文・学びは書けない）",
          [a for a in art["allow"] if a.startswith(("Edit(", "Write(")) and "automation" in a],
          ["Edit(automation/logs/*.md)"])
    check("自動修復の AI は、自分を動かすコンテナの作り（ai_container.Dockerfile）を書き換えられない",
          "Edit(automation/ai_container.Dockerfile)" in mnt["deny"], True)
    doms = ("hojyokin-portal.jp", "startup-station.jp", "arxiv.org")
    check("補助金ポータル・TOKYO創業ステーション・arXiv を読める（記事・自動修復。*. 付きも）",
          [d for d in doms for perm in (art, mnt)
           if not {f"WebFetch(domain:{d})", f"WebFetch(domain:*.{d})"} <= set(perm["allow"])], [])
    skills = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in (ROOT / ".claude" / "skills").rglob("*.md")
                     if "ui-ux-pro-max" not in p.parts)
    check("足した読み先は、スキルが一次情報として実際に挙げている", [d for d in doms if d not in skills], [])


def test_prompts_point_to_grep_glob_and_discard_draft():
    print("\n■ 指示書: 探すのは Grep・Glob、消すのは discard_draft、作業メモは .md")
    used = _article_prompts()
    check("記事の許可の一覧で動かす指示書が見つかる（記事・救済・週次・旧パイプライン）",
          sorted(set(used) & {"automation/multi_site_prompt.txt", "automation/retry_prompt.txt",
                              "automation/pipeline_prompt.txt", "automation/weekly_optimize_prompt.txt"}),
          ["automation/multi_site_prompt.txt", "automation/pipeline_prompt.txt", "automation/retry_prompt.txt",
           "automation/weekly_optimize_prompt.txt"])
    miss = []
    for f in used:
        t = (ROOT / f).read_text(encoding="utf-8")
        if "Grep・Glob の道具を使う" not in t or "automation/logs/ の .md" not in t:
            miss.append(f)
    check("記事の AI の指示書: ファイルを探すのは Grep・Glob、作業メモは automation/logs/ の .md と書いてある", miss, [])
    texts = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8", errors="ignore")
             for p in [*AUTO.glob("*_prompt.txt"), *(ROOT / ".claude" / "skills").rglob("*.md")]
             if "ui-ux-pro-max" not in p.parts}
    check("指示書・スキルが rm で記事を消すよう案内していない",
          sorted(f for f, t in texts.items() if re.search(r"\brm\s+(-\w+\s+)*articles/|articles/<slug>\.md を削除", t)), [])
    rp = texts["automation/retry_prompt.txt"]
    # 公開済みの記事は機械（dup_retract）が実績で決めて取り下げる（2026-10-11 運用者「自動的に直して」）。AI は要対応にしない
    check("救済の指示書: 重複の取り下げは discard_draft で消し、断られたら残りの手順を行わず機械に任せる",
          ("`python scripts/discard_draft.py <slug>`" in rp, "DISCARD_OK=no" in rp, "機械の手順（dup_retract）" in rp),
          (True, True, True))


def test_rewrite_rollback_reads_only_rewrite_before():
    import rewrite_rollback as R
    print("\n■ rewrite_rollback: 直す前の原稿は data/rewrite_before/ の中だけを読む（台帳は書き換えられうる）")
    with tempfile.TemporaryDirectory(prefix="gate_h96_", ignore_cleanup_errors=True) as td:
        r = Path(td)
        for d in ("articles", "data/rewrite_before", "scripts"):
            (r / d).mkdir(parents=True)
        secret = b"SECRET-h96\n"
        (r / ".env").write_bytes(secret)
        (r / "scripts" / "x.py").write_bytes(secret)
        after = b"after\n"
        art = r / "articles" / "zz-post.md"
        good = "data/rewrite_before/zz-post@2026-09-01.md"
        (r / good).write_bytes(b"before\n")
        sha = hashlib.sha1(after).hexdigest()

        def line(bp, kind="compete"):
            return {"slug": "zz-post", "kind": kind, "before_path": bp, "after_sha": sha,
                    "before_title": "t", "after_title": "t"}
        bads = [".env", "scripts/x.py", "data/rewrite_before/../../.env", "data\\rewrite_before\\..\\..\\.env",
                str(r / ".env"), (r / ".env").as_posix(), "/etc/passwd", "C:/Windows/win.ini", "data/rewrite_before"]
        link = r / "data" / "rewrite_before" / "zz-link.md"
        try:
            os.symlink(r / ".env", link)
            bads.append("data/rewrite_before/zz-link.md")
        except (OSError, NotImplementedError):
            pass
        old = R.ROOT
        try:
            R.ROOT = r
            res = []
            for bp in bads:
                for kind in ("compete", "early", "serp"):
                    art.write_bytes(after)
                    with contextlib.redirect_stdout(io.StringIO()) as o:
                        ok = R.restore("zz-post", line(bp, kind))
                    res.append((bp, kind, ok, art.read_bytes() == after, "要対応" in o.getvalue()))
            check("before_path が置き場の外（..・絶対パス・コード・鍵・置き場そのもの・外を指すリンク）なら読まず、記事も変えず要対応",
                  [x[:2] for x in res if x[2] or not x[3] or not x[4]], [])
            art.write_bytes(after)
            check("置き場の中の直す前の原稿は今までどおり戻せる", (R.restore("zz-post", line(good)), art.read_bytes()),
                  (True, b"before\n"))
            with contextlib.redirect_stdout(io.StringIO()) as o:
                ok = R.restore("../scripts/x", line(good))
            check("台帳の slug が記事の名前の形でなければ戻さない（articles/ の外へ書かない）",
                  (ok, (r / "scripts" / "x.py").read_bytes(), "要対応" in o.getvalue()), (False, secret, True))
        finally:
            R.ROOT = old


def test_tool_agent_cannot_read_keys():
    import auto_rewrite as AR
    print("\n■ 道具の中から呼ぶ AI（auto_rewrite・auto_merge）: 鍵のファイル・/proc・ホームの鍵・非公開の置き場を読ませない")
    p = json.loads(AR.PERM)["permissions"]
    deny = p.get("deny") or []
    must = ["Read(.env)", "Read(**/.env)", "Read(**/.env.*)", "Read(//proc/**)", "Read(~/.ssh/**)", "Read(~/.config/**)",
            "Read(~/.git-credentials)", "Read(~/.codex/**)", "Read(**/.git/config)", "Read(indexing-service-account.json)",
            "Read(**/*token*.json)", "Read(**/*credentials*.json)", "Read(private/**)"]
    check("鍵のファイル・/proc（親の python の環境変数）・ホームの鍵・非公開の置き場の Read を拒む", [m for m in must if m not in deny], [])
    mnt = _settings("maint")
    check("自動修復の AI の Read の拒否を全部含む（非公開の置き場は private/** でまとめて拒む）",
          [d for d in mnt["deny"] if d.startswith("Read(") and d not in deny and not d.startswith("Read(private/")], [])
    absol = ["Read(//**/.env)", "Read(//**/.env.*)", "Read(//**/.git/config)", "Read(//**/indexing-service-account.json)",
             "Read(//**/*token*.json)", "Read(//**/*credentials*.json)", f"Read({AR._abs_rule(ROOT)}/private/**)"]
    check("一時フォルダで動かす回（draft_all。接頭辞なしの形は作業の場所からの相対）にも効く // の絶対の形がある",
          [a for a in absol if a not in deny], [])
    check("// の形への直し方（Windows はドライブを /c/ に）", (AR._abs_rule("C:/x/y"), AR._abs_rule("/home/r/w")),
          ("//c/x/y", "//home/r/w"))
    check("書けるのは記事だけで、承認なしで Edit が通る形は変えない", (p["allow"], p["defaultMode"]),
          (["Read", "Edit(articles/**)"], "acceptEdits"))
    ar = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    am = (ROOT / "scripts" / "auto_merge.py").read_text(encoding="utf-8")
    calls = (ar.count('"--allowedTools", "Read,Edit"'), ar.count('"--settings", PERM]'),
             am.count('"--allowedTools", "Read,Edit"'), am.count('"--settings", AR.PERM]'))
    check("auto_rewrite・auto_merge の claude の呼び出しはすべてこの許可（PERM）を渡す",
          (calls[0] == calls[1] >= 2, calls[2] == calls[3] >= 1), (True, True))
