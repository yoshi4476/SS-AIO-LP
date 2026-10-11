# -*- coding: utf-8 -*-
"""2026-10-11 運用者「ほかの社の原稿も見られないように」「一番いい方法で」。

記事を書く AI が動く間だけ、作業場所に置くお客様の社をその回の範囲に絞り（private_store --scope）、終わったら戻す。
非公開の置き場は git なので、書きかけを手元で commit してから sparse-checkout で外す。戻し損ねても消えないこと、
戻した後は元と1バイトも違わないこと、絞っている間に外した場所へ書かれても commit 済みの中身を上書きしないこと、
範囲ごとの回（agent_guard --checkpoint / --protect --pass）が範囲の外の書き換えだけを戻すことを、
一時の写し（git clone。worktree は見張りの一覧 info/exclude を本物と共有するので使わない）と非公開の置き場の写しで確かめる
（本物の作業場所・置き場には触れない）。
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

CHILD = r'''
import hashlib, json, os, subprocess, sys
from pathlib import Path
W = Path.cwd()
os.environ["PRIVATE_SCOPE_FORCE"] = "1"
sys.path.insert(0, str(W / "scripts"))
import private_store as PS
import sites as S
import agent_guard as A
A.ROOT = W
out = {}
g = lambda *a: subprocess.run(["git", "-C", str(W / "private"), *a], capture_output=True, text=True, encoding="utf-8")
clients = [c for c in S.load_all() if S.is_client(c)]
out["clients"] = len(clients)
for c in clients:
    d = W / "data" / "clients" / c / "private"
    d.mkdir(parents=True, exist_ok=True)
    (d / "x.json").write_text("{}", encoding="utf-8")


def snap():
    r = {}
    for base in (W / "articles", W / "site" / "images", W / "data" / "clients", W / "private"):
        for p in base.rglob("*"):
            if p.is_file() and ".git" not in p.parts:
                r[p.relative_to(W).as_posix()] = hashlib.sha1(p.read_bytes()).hexdigest()
    return r


before = snap()
by = PS.client_slugs()
PS.scope("own")
out["own_visible"] = sum((W / "articles" / f"{s}.md").exists() for s in by) + \
    sum((W / "data" / "clients" / c).exists() for c in clients) + sum((W / "private" / "clients" / c).exists() for c in clients)
out["own_sales"] = (W / "private" / "sales").exists()
# 戻し損ねたまま保存の前半が走っても、置き場から消えない
PS.overlay_out(unstage=False)
g("add", "-A")
out["staged_deletes"] = sum(l.startswith("D") for l in g("diff", "--cached", "--name-status").stdout.splitlines())
g("reset", "-q")
# 絞っている間に、外した場所へ書かれた（commit 済みの中身を上書きしない）
tracked = [l for l in g("ls-files").stdout.splitlines() if l.startswith("clients/") and l.endswith(".json")]
if tracked:
    t = W / "private" / tracked[0]
    orig = g("show", f"HEAD:{tracked[0]}").stdout
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text("{\"x\": 1}", encoding="utf-8")
PS.widen()
after = snap()
out["diff_after_widen"] = len(set(before) ^ set(after)) + sum(before[k] != after[k] for k in before if k in after)
out["private_status"] = len(g("status", "--porcelain").stdout.splitlines())
# 範囲ごとの回: client の範囲で、範囲の外（自社）の書き換え・新しい記事は戻り、範囲の中は残る
if clients:
    own = next((p for p in sorted((W / "articles").glob("*.md")) if A._site_of(p.stem, W) in S.own_ids()), None)
    cl = next((p for p in sorted((W / "articles").glob("*.md")) if A._site_of(p.stem, W) == clients[0]), None)
    if own and cl:
        ob, cb = own.read_bytes(), cl.read_bytes()
        A.checkpoint(W)
        own.write_bytes(ob + b"\n# off\n")
        cl.write_bytes(cb + b"\n# in\n")
        (W / "articles" / "zz-new-off.md").write_text(own.read_text(encoding="utf-8"), encoding="utf-8")
        A._protect_other_sites(W, S.public_id(clients[0]), by_pass=True)
        out["pass"] = [own.read_bytes() == ob, cl.read_bytes() != cb, not (W / "articles" / "zz-new-off.md").exists()]
        cl.write_bytes(cb)
print("RESULT=" + json.dumps(out))
'''


def test_scope_narrows_and_widens_without_loss():
    print("\n■ AI の範囲: 絞る・戻すで中身が変わらず、戻し損ねても消えず、外した場所への書き込みで上書きしない")
    priv = ROOT / "private"
    if not (priv / ".git").is_dir():
        print("  WARN  非公開の置き場（private/）が無いため確かめられません")
        return
    tmp = Path(tempfile.mkdtemp(prefix="gate_scope_"))
    wt = tmp / "w"
    g = lambda *a, cwd=ROOT: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    try:
        # worktree は info/exclude を本物の作業場所と共有し、重ね置きの一覧を書き換える（2026-10-12 にそれで置き場の
        # 記事を消した）。別の .git を持つ写しで試す
        if g("clone", "-q", "--no-hardlinks", "--depth", "1", f"file://{ROOT.as_posix()}", str(wt)).returncode:
            print("  WARN  一時の写しを作れませんでした")
            return
        # 手元で直している途中の道具も試す（HEAD の写しに上書き）
        for f in ("private_store.py", "agent_guard.py", "client_private.py", "sites.py"):
            shutil.copyfile(ROOT / "scripts" / f, wt / "scripts" / f)
        g("clone", "-q", str(priv), str(wt / "private"))
        for k, v in (("user.name", "t"), ("user.email", "t@example.com")):
            g("-C", str(wt / "private"), "config", k, v)
        env = {**__import__("os").environ, "RUNNER_TEMP": str(tmp / "rt"), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        (tmp / "rt").mkdir()
        subprocess.run([sys.executable, "scripts/private_store.py", "--overlay"], cwd=wt, env=env, capture_output=True)
        (tmp / "child.py").write_text(CHILD, encoding="utf-8")
        r = subprocess.run([sys.executable, str(tmp / "child.py")], cwd=wt, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith("RESULT=")), "")
        if not line:
            check("範囲の試しが最後まで動く", (r.stderr or r.stdout)[-300:], "")
            return
        o = json.loads(line[len("RESULT="):])
        check("自社だけの範囲: お客様の社の原稿・派生データ・置き場の社が1つも見えず、営業の資料も置かない",
              (o["own_visible"], o["own_sales"]), (0, False))
        check("戻し損ねたまま保存の前半が走っても、置き場の削除は0件", o["staged_deletes"], 0)
        check("戻した後は元と1バイトも違わず、外した場所への書き込みで commit 済みの中身を上書きしない",
              (o["diff_after_widen"], o["private_status"]), (0, 0))
        if "pass" in o:
            check("範囲ごとの回: 範囲の外の書き換えは戻り、範囲の中は残り、範囲の外の新しい記事は消える", o["pass"], [True, True, True])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_overlay_out_deletes_only_what_this_workspace_placed():
    print("\n■ 重ね置きの見張り: この作業場所で置いて消したものだけ置き場からも消す（ほかの作業場所が一覧に足した分は消さない）")
    import os
    from unittest import mock
    import private_store as PS
    import sites as S
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        pub, priv = t / "pub", t / "priv"
        g = lambda cwd, *a: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
        for d in (pub, priv):
            d.mkdir()
            g(d, "init", "-q")
            g(d, "config", "user.email", "gate@example.invalid")
            g(d, "config", "user.name", "gate")
        (pub / "sites").mkdir()
        (pub / "articles").mkdir()
        (pub / "sites" / "own-x.json").write_text(json.dumps({"id": "own-x", "domain": "own.example",
                                                              "categories": {"ox": "O"}}), encoding="utf-8")
        g(pub, "add", "-A")
        g(pub, "commit", "-q", "-m", "init")
        with mock.patch.dict(os.environ, {"SS_PRIVATE_DIR": str(priv)}), \
                mock.patch.object(S, "SITES_DIR", pub / "sites"), mock.patch.object(S, "ROOT", pub), \
                mock.patch.object(PS, "ROOT", pub), mock.patch.object(PS, "_CLIENT_SLUGS", None):
            PS.write_site({"id": "c0a1b2c3d", "public_id": "c0a1b2c3d", "name": "架空の社", "domain": "zz.example",
                           "type": "external-md", "categories": {"zz-blog": "Z"}}, pub / "sites")
            for slug in ("zz-a", "zz-b"):
                (priv / "articles").mkdir(exist_ok=True)
                (priv / "articles" / f"{slug}.md").write_text(f"---\ntitle: {slug}\ncategory: zz-blog\n---\n本文\n",
                                                             encoding="utf-8")
            g(priv, "add", "-A")
            g(priv, "commit", "-q", "-m", "init")
            PS.overlay_in()
            # 別の作業場所が置いた分（この作業場所には無い）が、共有の見張りの一覧に足された
            (priv / "articles" / "zz-c.md").write_text("---\ntitle: c\ncategory: zz-blog\n---\n本文\n", encoding="utf-8")
            PS._write_exclude(PS._exclude_entries() + ["articles/zz-c.md"])
            # この作業場所では zz-a を消した（取り下げ・統合など）
            (pub / "articles" / "zz-a.md").unlink()
            PS.overlay_out(unstage=False)
            check("この作業場所で置いて消した記事は置き場からも消し、ほかの作業場所が一覧に足した記事は消さない",
                  ((priv / "articles" / "zz-a.md").exists(), (priv / "articles" / "zz-c.md").exists(),
                   (priv / "articles" / "zz-b.md").exists()), (False, True, True))


def test_scopes_without_work_are_skipped():
    print("\n■ 範囲ごとの回: その範囲の今日の仕事が0件なら AI を起こさない（救済は監査の TODO、週次は記事の本数で数える）")
    import sites as S
    import agent_work as W
    clients = [c for c in S.load_all() if S.is_client(c)]
    owner = {"zz-own-slug": "corporate"}
    if clients:
        owner["zz-client-slug"] = clients[0]
    text = "\n".join(["===== 結果 =====", "AUDIT_OK=no", "TODO: ai-lab の記事を本日あと 1 本作成して公開する",
                      "TODO: zz-own-slug を品質基準まで直して score を更新し、再ビルドする",
                      "TODO: 配信用のトークンの期限が近い", "", "--- 以下は今日やらないこと（週次で扱う / 知らせるだけ） ---",
                      "NOTE: zz-client-slug は週次で扱う"])
    check("自社の回は、自社の社・自社の記事・社に触れない TODO を数える", W.rescue_count("own", text, owner), 3)
    if clients:
        pub = S.public_id(clients[0])
        check("お客様の回は、その社の TODO が無ければ0件（今日やらないこと・自社の TODO は数えない）",
              W.rescue_count(pub, text, owner), 0)
        text2 = text.replace("TODO: 配信用", "TODO: zz-client-slug を品質基準まで直す\nTODO: 配信用")
        check("お客様の回は、その社の記事の TODO を数え、自社の回はそれを数えない",
              (W.rescue_count(pub, text2, owner), W.rescue_count("own", text2, owner)), (1, 3))
        check("週次はその範囲の記事の本数で数える", (W.weekly_count("own", owner), W.weekly_count(pub, owner)), (1, 1))
    ap = (ROOT / "scripts" / "agent_passes.sh").read_text(encoding="utf-8")
    loop = ap[ap.index("for sc in"):]
    pl = (ROOT / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("範囲ごとの回は、仕事が0件なら AI の前に飛ばし、数えられなければ飛ばさない。救済は監査の出力を残し、救済・週次が数え方を渡す",
          (loop.index("agent_work.py") < loop.index("claude -p"), '[ "$w" = "0" ]' in ap,
           'audit_out.txt' in pl and "AGENT_WORK_KIND=rescue bash scripts/agent_passes.sh" in pl,
           "AGENT_WORK_KIND=weekly bash scripts/agent_passes.sh" in wk), (True, True, True, True))
