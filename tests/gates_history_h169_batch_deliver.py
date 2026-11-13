# -*- coding: utf-8 -*-
"""配信先への push を1回の工程で1回にまとめる・中身の同じ配り直しをしない・失敗の理由を伏せて残す（2026-11-13）

お客様の社（配信先は push のたびに Cloudflare のビルドが走る）へ、管制塔の CI が1日34回 push し、11:28 以降のビルドが
全部失敗した。原因は2つ重なっていた。
- 比較表のまとめページの記事の並びが Python のプロセスごとに変わり、記事が同じでも配るたびに1行の差分が出て、
  publish.py の「変更なし」で push を省けなかった
- 本番の指紋が古いまま（ビルドが失敗して本番が変わらない）なので、未配信の確認（publish_gap）が毎回同じ記事を
  「内容が古い」として記事ごとに push し直し、ビルドをさらに走らせた
ここでは (a) 中身が同じなら配り直さない、(b) 何本配っても push は最後の1回、(c) お客様の社の失敗の理由の行に
題・slug・ドメインが出ない、をネットワークに出ずに確かめる（配信先は手元の空のリポジトリ。社は架空の client-zz）。
"""
import contextlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

TITLE = "架空の比較記事の題ZZ"
SLUG = "zz-hikaku-kiji"
DOMAIN = "zz.example"

_SEED_SNIPPET = """
import sys
sys.path.insert(0, sys.argv[1])
import aggregate_pages as AP
import compare_pages as CP
tbl = "| 項目 | A | B |\\n|:--|:--|:--|\\n| 費用 | 1 | 2 |"
slugs = ["zz-a", "zz-b", "zz-c", "zz-d", "zz-e"]
rows = [{"title": "架空の記事" + s, "h2": "比べる", "table": tbl, "slug": s, "date": "2026-11-0" + str(i + 1), "cols": 3}
        for i, s in enumerate(slugs)]
CP.collect = lambda sid, only=None: {"zz": rows}
cfg = {"id": "client-zz", "domain": "zz.example", "categories": {"zz": "架空の分類"}, "main_category": "zz"}
arts = [({"slug": s, "title": "架空の記事" + s, "category": "zz", "date": "2026-11-01"}, "本文") for s in slugs]
for p in AP.collect(cfg, arts=arts, kinds=("compare",), url_of=lambda m: "https://zz.example/" + m["slug"] + "/"):
    print(p["path"], p["description"], ",".join(p["members"]))
"""


def test_compare_page_is_same_in_every_process():
    print("\n■ 配信の重複: 比較表のまとめページは、プロセス（ハッシュの種）が変わっても同じ説明文・同じ並びになる")
    outs = set()
    for seed in ("1", "2", "3", "4"):
        r = subprocess.run([sys.executable, "-c", _SEED_SNIPPET, str(ROOT / "scripts")], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONHASHSEED=seed, PYTHONIOENCODING="utf-8"))
        outs.add(r.stdout.strip() or r.stderr.strip()[-200:])
    check("種を4つ変えて、比較表のページの説明文と記事の並びが1通り（配るたびに1行の差分を出さない）", len(outs), 1)
    check("並びは比較表の表の並びのまま（compare_pages.collect が新しい順に並べたもの）",
          any(" zz-a,zz-b,zz-c,zz-d,zz-e" in o for o in outs), True)


def test_gap_does_not_resend_what_the_repo_already_has():
    print("\n■ 配信の重複: 本番が古くても、配信先のリポジトリに今の原稿の指紋で届いている記事は配り直さない")
    import publish_gap as G
    hashes = {"zz-new": "h1", "zz-old": "h2", "zz-edit": "h3", "zz-conv": "h4"}
    why = {"zz-old": "内容", "zz-edit": "内容", "zz-conv": "変換漏れ"}
    repo = ({"zz-new": "h1", "zz-old": "h2", "zz-edit": "古い指紋", "zz-conv": "h4"}, 1_000_000)
    got, at = G.unreflected({"type": "external-md"}, ["zz-new", "zz-old", "zz-edit", "zz-conv"], hashes, why, repo=repo)
    check("届いている記事（未配信・内容が古いとも）だけを外す。原稿を直した記事と変換漏れは配り直す",
          (sorted(got), at), (["zz-new", "zz-old"], 1_000_000))
    check("配信先の指紋が読めなければ、今までどおり全部を配り直す", G.unreflected({}, ["zz-new"], hashes, why, repo=(None, None)),
          ([], None))
    cfg = {"id": "client-zz", "public_id": "cc000zz", "name": "架空の社ZZ", "domain": DOMAIN}
    with mock.patch("sites.is_client", lambda s: s == "client-zz"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            G.report_unreflected(cfg, "client-zz", ["zz-new", "zz-old"], 1_000_000, now=1_000_000 + 10 * 60)
        young = buf.getvalue()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            G.report_unreflected(cfg, "client-zz", ["zz-new", "zz-old"], 1_000_000, now=1_000_000 + 45 * 60)
        old = buf.getvalue()
    check("届いて10分はビルド待ちとして件数だけ・45分たっても本番に無ければ要対応（配信先のビルドを確かめる）",
          ("要対応" in young, "2本" in young, "要対応: cc000zz" in old and "ビルド" in old), (False, True, True))
    check("お客様の社の行に社名・ドメイン・slug を出さない（公開の id と件数だけ）",
          [w for w in ("架空の社ZZ", DOMAIN, "zz-new", "zz-old", "client-zz") if w in young + old], [])


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def test_batch_sends_one_push():
    print("\n■ 配信の push: PUBLISH_BATCH=1 の間はコミットまで。最後の flush で1回だけ送り、中身が同じなら送らない")
    import publish as P
    tmp = Path(tempfile.mkdtemp(prefix="gate_h169_"))
    bare, other = tmp / "bare.git", tmp / "other"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    _git(bare, "config", "core.logAllRefUpdates", "true")
    subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        _git(other, "config", k, v)
    (other / "README.md").write_text("x\n", encoding="utf-8")
    _git(other, "add", "-A")
    _git(other, "commit", "-qm", "init")
    _git(other, "push", "-q", str(bare), "main")
    env = {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{bare.as_posix()}.insteadOf",
           "GIT_CONFIG_VALUE_0": "https://github.com/zz/site.git", "GITHUB_ACTIONS": "true"}
    cfg = {"id": "client-zz", "repo": "zz/site", "branch": "main", "type": "external-md"}

    def pushes():
        return len(_git(bare, "reflog", "show", "main").splitlines())

    def deliver(slug, body):
        dest = P.ensure_clone(cfg, "")
        (dest / "content").mkdir(exist_ok=True)
        (dest / "content" / f"{slug}.md").write_text(body, encoding="utf-8")
        return P.commit_and_send(cfg, dest, "", f"publish: {slug}", slug)

    keep = {k: os.environ.get(k) for k in (*env, P.BATCH, "SITE_PUSH_TOKEN")}
    os.environ.update(env)
    os.environ.pop("SITE_PUSH_TOKEN", None)
    try:
        with mock.patch.object(P, "WORK", tmp / "work"), contextlib.redirect_stdout(io.StringIO()):
            os.environ[P.BATCH] = "1"
            base = pushes()
            ok = [deliver(s, f"{s} 1\n") for s in ("zz-a", "zz-b")]
            # まとめている途中で配信先が先に進んでも（先方・ほかの工程の push）、最新の上に重ねて送る
            (other / "theirs.md").write_text("先方\n", encoding="utf-8")
            _git(other, "add", "-A")
            _git(other, "commit", "-qm", "theirs")
            _git(other, "push", "-q", str(bare), "main")
            base += 1
            ok.append(deliver("zz-c", "zz-c 1\n"))
            during = pushes() - base
            os.environ.pop(P.BATCH)
            flushed = P.flush(cfg)
            after = pushes() - base
            files = [_git(bare, "show", f"main:{f}") for f in ("content/zz-a.md", "content/zz-c.md", "theirs.md")]
            base = pushes()
            same = deliver("zz-a", "zz-a 1\n") and P.flush(cfg)
            unchanged = pushes() - base
            os.environ[P.BATCH] = "1"
            deliver("zz-b", "zz-b 2\n")
            os.environ.pop(P.BATCH)
            base = pushes()
            deliver("zz-new", "新しい記事\n")
            carried = (pushes() - base, _git(bare, "show", "main:content/zz-b.md"), P.pending(cfg))
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    check("3本を書き出す間は push 0回・最後の flush で1回（途中で先に進んだ配信先の上に重ねる）",
          (all(ok), during, flushed, after), (True, 0, True, 1))
    check("送った中身に3本と先方の変更がそろう", files, ["zz-a 1", "zz-c 1", "先方"])
    check("中身が同じ記事を配り直しても、コミットも push もしない", (same, unchanged), (True, 0))
    check("まとめていた分は、次にその場で送る記事（公開を確かめる新しい記事）の push で一緒に届く",
          carried, (1, "zz-b 2", None))


def test_callers_batch_and_flush():
    print("\n■ 配信の push: 記事を何本も配る道具は、子に PUBLISH_BATCH=1 を渡し、最後に1回だけ送る")
    src = {n: (ROOT / "scripts" / n).read_text(encoding="utf-8")
           for n in ("publish_gap.py", "publish_changed.py", "publish_flow.py", "i18n.py", "agent_guard.py")}
    check("publish_gap・publish_changed・公開の後のリンク・i18n は子をまとめ、自分が始めたときだけ flush する",
          [n for n in ("publish_gap.py", "publish_changed.py", "publish_flow.py", "i18n.py")
           if not ("batch_env()" in src[n] and "flush(" in src[n] and "batched()" in src[n])], [])
    check("agent_guard は publish_flow・publish_changed をまとめて呼び、最後に社ごとに --flush",
          ('PUBLISH_BATCH="1"' in src["agent_guard.py"], '"--flush"' in src["agent_guard.py"]), (True, True))
    check("新しい記事はその場で送る（publish_flow の publish.py は PUBLISH_BATCH を外して呼ぶ）",
          "run_out(args, env=publish.unbatched_env())" in src["publish_flow.py"], True)


def _fake_run(outputs, calls):
    def run(args, **kw):
        calls.append([str(a) for a in args])
        name = Path(str(args[1])).name if len(args) > 1 else ""
        if name == "publish_flow.py":
            rc, out = outputs.pop(0)
            return subprocess.CompletedProcess(args, rc, out, "")
        if name == "publish.py" and "--flush" in args:
            return subprocess.CompletedProcess(args, 0, "まとめた配信: 1本分のコミットを1回の push で送りました\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    return run


def test_client_failure_reason_is_masked_and_split():
    print("\n■ 配信の失敗: お客様の社でも理由の行を出す（題・slug・ドメインなし）。本番で確かめられないだけの記事は失敗と分ける")
    import publish_flow as PF
    leaky = [
        (1, f"PUBLISH_STAGE=gate\nPUBLISH_STAGE=deliver\nコマンド失敗: git push https://github.com/zz/site.git HEAD:main\n"
            f"publish: {TITLE}\npushできません。次の順に確かめてください。\n"),
        (1, f"PUBLISH_STAGE=deliver\nPUBLISH_STAGE=verify\n  https://{DOMAIN}/blog/{SLUG}/ が 404\n{PF.UNVERIFIED}\n"
            f"配信しましたが公開が確認できません。\n  確認: python scripts/verify_publish.py --site client-zz --slug {SLUG}\n"),
        (1, f"PUBLISH_STAGE=gate\nBLOCKED(食い合い): 「{TITLE}」は既存ページと食い合うため配信しません。\n"),
        (1, f"PUBLISH_STAGE=deliver\nTraceback (most recent call last):\nKeyError: '{SLUG}'\n"),
        (1, f"PUBLISH_STAGE=deliver\nコマンド失敗: git commit -m publish: {TITLE}（score 90）\n"),
    ]
    got = [PF.fail_reason(o) for _, o in leaky]
    check("種類: push の失敗・本番で確かめられない・門・例外・git の失敗を分ける",
          [k for k, _ in got], ["failed", "unverified", "failed", "failed", "failed"])
    check("理由の行は段と決まった語だけ", [w.split(" / ", 1)[1] for _, w in got],
          ["配信先へ push できない", "配信は済みましたが、本番で記事を確かめられません", "配信の門 BLOCKED(食い合い)",
           "例外 KeyError", "配信先の git commit が失敗"])
    check("理由の行に題・slug・ドメイン・配信先のリポジトリが出ない",
          [w for _, w in got if any(x in w for x in (TITLE, SLUG, DOMAIN, "zz/site", "client-zz"))], [])

    import agent_guard as A
    import quality_loop as QL
    import rubric
    import score_check
    import sites as S
    tmp = Path(tempfile.mkdtemp(prefix="gate_h169_ag_"))
    (tmp / "articles").mkdir()
    for s in (SLUG, SLUG + "-2"):
        (tmp / "articles" / f"{s}.md").write_text(f"---\ntitle: {TITLE}\ncategory: zz\n---\n本文\n", encoding="utf-8")
    calls = []
    real_load = S.load
    with mock.patch.object(A, "changes", lambda root: ([SLUG, SLUG + "-2"], [])), \
            mock.patch.object(A, "_site_of", lambda slug, root=None: "client-zz"), \
            mock.patch.object(S, "is_client", lambda s: s == "client-zz"), \
            mock.patch.object(S, "public_id", lambda s: "cc000zz", create=True), \
            mock.patch.object(S, "load", lambda s: {"id": s, "type": "external-md"} if s == "client-zz" else real_load(s)), \
            mock.patch.object(score_check, "run", lambda slug, path=None: []), \
            mock.patch.object(QL, "released", lambda: []), \
            mock.patch.object(QL, "machine_passed", lambda slug, meta: True), \
            mock.patch.object(rubric, "improving", lambda meta: False), \
            mock.patch.object(A.subprocess, "run", _fake_run([leaky[0], leaky[1]], calls)):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            res = A.publish(tmp, only="client-zz")
    out = buf.getvalue()
    fd = (tmp / "automation" / "logs" / "findings.txt").read_text(encoding="utf-8")
    check("push の失敗は失敗・本番で確かめられないだけの記事は別に数える", (res["failed"], res["unverified"]), (1, 1))
    check("お客様の社でも理由の行を出す（段と種類）",
          ("理由: 段: 配信（書き出し・push） / 配信先へ push できない" in out, "△" in out
           and "理由: 段: 配信後の本番の確かめ" in out), (True, True))
    check("ログと通知の本文に題・slug・ドメイン・社の id を出さない",
          [w for w in (TITLE, SLUG, DOMAIN, "zz/site", "client-zz") if w in out + fd], [])
    check("通知の文を分ける（配信できなかった・配信は済んだが本番で確かめられない）",
          ("配信できませんでした" in fd, "本番で確かめられません（配信先には届いています" in fd), (True, True))
    flow = [c for c in calls if len(c) > 1 and Path(c[1]).name in ("publish_flow.py", "publish.py")]
    check("publish_flow を2本呼んだ後、社ごとに1回だけ --flush", [Path(c[1]).name + (" --flush" if "--flush" in c else "")
                                                         for c in flow],
          ["publish_flow.py", "publish_flow.py", "publish.py --flush"])
