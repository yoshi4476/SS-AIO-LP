# -*- coding: utf-8 -*-
"""書き直し・配信の点検で見つけた穴（2026-10-20）。

  1. auto_rewrite の直す前の原稿（data/rewrite_before/）は公開側で追跡している。お客様の記事の原稿もそこへ書き、
     次の commit で公開されていた → お客様の社は非公開の置き場（private/clients/<id>/data/rewrite_before/）へ。
     読む側（rewrite_rollback）も同じ場所を見る。公開側に残った分は commit の前（private_store.overlay_out）に移す
  2. 検算で差し戻すとき、直す対象の1本しか戻していなかった。AI が書き換えたほかの記事が commit・配信されていた
  3. AI・検算・ビルドの時間切れ（TimeoutExpired）で、書きかけの記事が残っていた
  4. build.py: aio→seo→aio と2回移すと、公開中の記事を転送元にした行が残って転送の輪になっていた
  5. rewrite_rollback: 28〜31日目に入った2回目の題の直しを、1回目の「直す前の題」で上書きしていた。
     題を戻すとき「: 」を含む題をそのまま書き、フロントマターが壊れうる形だった
  6. publish_rerender: 公開基準しか見ずに送り直し、publish.py が止める記事（入れてはいけない HTML など）まで届いていた
  7. publish_changed: 門で止まった記事も「3本続けて失敗＝環境の問題」に数え、1本ごとに20秒待ってやり直していた
架空の社（client-zz・zz.example）と一時の場所だけで試す。記事・配信先・非公開の置き場には触れない。
"""
import io
import os
import subprocess
import sys
import tempfile
import time
import types
from contextlib import redirect_stdout
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_client_rewrite_before_goes_to_private_store():
    import auto_rewrite as AR
    import client_private as CP
    import private_store as PS
    import rewrite_rollback as RR
    print("\n■ お客様の記事の直す前の原稿は非公開の置き場へ（公開側の data/rewrite_before/ に書かない）")
    saved = (CP.owner_of_slug, CP.is_private, os.environ.get("SS_PRIVATE_DIR"), PS.ROOT, PS.client_slug)
    with tempfile.TemporaryDirectory(prefix="gate_h119_", ignore_cleanup_errors=True) as td:
        priv = Path(td) / "private"
        try:
            os.environ["SS_PRIVATE_DIR"] = str(priv)
            CP.owner_of_slug = lambda slug: "client-zz" if slug.startswith("zz-") else None
            CP.is_private = lambda sid: sid == "client-zz"
            PS.client_slug = lambda slug: str(slug).startswith("zz-")
            out = AR.keep_before("zz-post", b"before\n", b"after\n")
            name = f"zz-post@{time.strftime('%Y-%m-%d')}.md"
            check("台帳の before_path はどの社でも data/rewrite_before/<名前>", out["before_path"], f"data/rewrite_before/{name}")
            check("お客様の記事の原稿は非公開の置き場にある",
                  (priv / "clients" / "client-zz" / "data" / "rewrite_before" / name).read_bytes(), b"before\n")
            check("公開側の data/rewrite_before/ には書いていない", (ROOT / "data" / "rewrite_before" / name).exists(), False)
            got = RR.before_file({"slug": "zz-post", "before_path": out["before_path"]})
            check("rewrite_rollback は同じ場所から読む", got is not None and got.read_bytes(), b"before\n")
            buf = io.StringIO()
            with redirect_stdout(buf):
                bad = RR.before_file({"slug": "zz-post", "before_path": "data/rewrite_before/../../.env"})
            check("置き場の外を指す before_path は読まない（お客様の記事でも）", bad, None)
            check("お客様の記事の slug をログに出さない", "zz-post" in buf.getvalue(), False)
            check("自社の記事は公開側の置き場", CP.rewrite_before_dir(None), ROOT / "data" / "rewrite_before")

            # 以前に公開側へ書いた分は、commit の前に非公開の置き場へ移す
            pub = Path(td) / "pub"
            (pub / "data" / "rewrite_before").mkdir(parents=True)
            (pub / "data" / "rewrite_before" / "zz-old@2026-09-01.md").write_bytes(b"old\n")
            (pub / "data" / "rewrite_before" / "own-post@2026-09-01.md").write_bytes(b"own\n")
            PS.ROOT = pub
            moved = PS.rehome_rewrite_before({"zz-old": "client-zz"})
            check("お客様の記事の分だけを移す", moved, ["data/rewrite_before/zz-old@2026-09-01.md"])
            check("移した先は社の置き場・公開側から消える",
                  ((priv / "clients" / "client-zz" / "data" / "rewrite_before" / "zz-old@2026-09-01.md").is_file(),
                   (pub / "data" / "rewrite_before" / "zz-old@2026-09-01.md").exists(),
                   (pub / "data" / "rewrite_before" / "own-post@2026-09-01.md").is_file()), (True, False, True))
        finally:
            CP.owner_of_slug, CP.is_private, env, PS.ROOT, PS.client_slug = saved
            if env is None:
                os.environ.pop("SS_PRIVATE_DIR", None)
            else:
                os.environ["SS_PRIVATE_DIR"] = env
    src = (ROOT / "scripts" / "private_store.py").read_text(encoding="utf-8")
    check("commit の前（overlay_out）で移す", "rehome_rewrite_before(client_slugs())" in src, True)


def test_tracked_rewrite_before_is_own_sites_only():
    import re
    import sites as S
    print("\n■ 公開側で追跡している直す前の原稿は、自社の記事の分だけ")
    own = {c for sid, cfg in S.load_all().items() if not S.is_client(sid) for c in (cfg.get("categories") or {})}
    files = subprocess.run(["git", "ls-files", "data/rewrite_before"], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8").stdout.split()
    bad = 0
    for f in files:
        t = (ROOT / f).read_text(encoding="utf-8-sig", errors="replace")[:3000]
        m = re.search(r"^category:\s*[\"']?([\w-]+)", t, re.M)
        bad += not (m and m.group(1) in own)
    # 名前は出さない（お客様の記事の slug が入りうる）。件数だけ
    check("自社のカテゴリでない原稿の数", bad, 0)


def _articles(d, **files):
    d.mkdir(parents=True, exist_ok=True)
    for n, t in files.items():
        (d / f"{n}.md").write_text(t, encoding="utf-8", newline="")


def test_reject_and_timeout_restore_every_touched_article():
    import auto_merge as AM
    import auto_rewrite as AR
    import shutil
    print("\n■ 差し戻し・時間切れでは、AI が触った記事を全部この時点の中身へ戻す")
    with tempfile.TemporaryDirectory(prefix="gate_h119_", ignore_cleanup_errors=True) as td:
        d = Path(td) / "articles"
        _articles(d, a="A0", b="B0")
        orig = AR.originals(d)
        (d / "a.md").write_text("A1", encoding="utf-8")
        (d / "b.md").write_text("B1", encoding="utf-8")
        (d / "c.md").write_text("C1", encoding="utf-8")
        back = AR.revert_since(orig, d)
        check("変わった記事は戻り、後から現れた記事は消える",
              (back, (d / "a.md").read_text(encoding="utf-8"), (d / "b.md").read_text(encoding="utf-8"), (d / "c.md").exists()),
              (["a.md", "b.md", "c.md"], "A0", "B0", False))

        # auto_rewrite: AI が対象とほかの記事を書き換え、検算で差し戻す／時間切れで止まる
        root = Path(td) / "root"
        art = "---\ntitle: zz の経理代行の費用と選び方5つ\nkeyword: zz 経理代行\ncategory: zz-cat\n---\n本文。\n"
        _articles(root / "articles", **{"zz-post": art, "zz-other": "---\ntitle: other\n---\n他。\n"})
        saved = (AR.ROOT, AR.sh, AR.warns, AR.build_prompt, AR.claude_bin, AR.model_args, shutil.which, AR.LAST.copy())
        mode = {"raise": False}
        built = []

        def fake_sh(args, timeout=1800, stdin_text=None, cwd=None):
            if "-p" in args:
                (root / "articles" / "zz-post.md").write_text(art.replace("本文。", "本文を直しました。"), encoding="utf-8")
                (root / "articles" / "zz-other.md").write_text("壊した", encoding="utf-8")
                if mode["raise"]:
                    raise subprocess.TimeoutExpired(args, timeout)
            elif any("build.py" in str(x) for x in args):
                built.append(1)
            return subprocess.CompletedProcess(args, 0, "", "")
        try:
            AR.ROOT, AR.sh, AR.warns = root, fake_sh, (lambda slug: [])
            AR.build_prompt = lambda item: ("p", "")
            AR.claude_bin, AR.model_args = (lambda: "claude"), (lambda: [])
            shutil.which = lambda name: "claude"
            item = {"kind": "aio", "slug": "zz-post", "site": "zz", "why": "門"}
            ok, why = AR.run_one(item, True)
            check("auto_rewrite: ほかの記事を変えたら差し戻す", (ok, why.startswith("別の記事まで変わっています")), (False, True))
            check("auto_rewrite: 対象もほかの記事も直す前の中身に戻る",
                  ((root / "articles" / "zz-post.md").read_text(encoding="utf-8"),
                   (root / "articles" / "zz-other.md").read_text(encoding="utf-8")), (art, "---\ntitle: other\n---\n他。\n"))
            mode["raise"] = True
            built.clear()
            ok, why = AR.run_one(item, True)
            check("auto_rewrite: 時間切れは差し戻しとして返る（例外で止まらない）",
                  (ok, why.startswith("途中で止まりました（TimeoutExpired）")), (False, True))
            check("auto_rewrite: 時間切れでも全部戻してビルドし直す",
                  ((root / "articles" / "zz-post.md").read_text(encoding="utf-8") == art,
                   (root / "articles" / "zz-other.md").read_text(encoding="utf-8"), bool(built)),
                  (True, "---\ntitle: other\n---\n他。\n", True))
        finally:
            AR.ROOT, AR.sh, AR.warns, AR.build_prompt, AR.claude_bin, AR.model_args, shutil.which, last = saved
            AR.LAST.clear()
            AR.LAST.update(last)

        # auto_merge: 検算で差し戻すと loser も戻る／時間切れも戻す
        md = Path(td) / "merge"
        _articles(md, s="S0", l="L0")
        pair = {"site": "zz", "survivor": "s", "loser": "l", "kws": [{"kw": "x"}], "imp": 0, "reason": "理由"}
        saved = (AM.ARTICLES, AM.is_article, AM.fm, AM._claude, AM.check, AM.url_of, AR.meta, AR.warns, AR.snapshot, AR.sh)
        try:
            AM.ARTICLES = md
            AM.is_article = lambda slug: True
            AM.fm = lambda slug: {"text": (md / f"{slug}.md").read_text(encoding="utf-8")}
            AM.url_of = lambda site, slug: f"/x/{slug}/"
            AM.check = lambda *a, **k: "検算に落ちました"
            AR.meta = lambda slug: ("t", "k", (md / f"{slug}.md").read_text(encoding="utf-8"))
            AR.warns = lambda slug: []
            AR.snapshot = lambda: {}
            AR.sh = lambda *a, **k: subprocess.CompletedProcess([], 0, "", "")

            mode["escape"] = False

            def claude(prompt, cwd=None, **kw):
                # 写し（cwd/articles）で書く。escape の回は作業場所の記事を直接書き換える（写しの外へ出た AI）
                at = md if mode["escape"] else Path(cwd) / "articles"
                (at / "s.md").write_text("S1", encoding="utf-8")
                (at / "l.md").write_text("L1", encoding="utf-8")
                if mode["raise"]:
                    raise subprocess.TimeoutExpired("claude", 2400)
                return subprocess.CompletedProcess([], 0, "", "")
            AM._claude = claude
            mode["raise"] = False
            ok, why = AM.run_one(pair, True)
            check("auto_merge: 写しで書いた統合が検算に落ちたら survivor も loser も戻る",
                  (ok, why, (md / "s.md").read_text(encoding="utf-8"), (md / "l.md").read_text(encoding="utf-8")),
                  (False, "検算に落ちました", "S0", "L0"))
            mode["escape"] = True
            ok, why = AM.run_one(pair, True)
            check("auto_merge: AI が作業場所の記事を直接変えたら、全部戻して止める",
                  (ok, why.startswith("別の記事まで変わっています"),
                   (md / "s.md").read_text(encoding="utf-8"), (md / "l.md").read_text(encoding="utf-8")),
                  (False, True, "S0", "L0"))
            mode["raise"] = True
            ok, why = AM.run_one(pair, True)
            check("auto_merge: 時間切れも差し戻しとして返り、全部戻る",
                  (ok, why.startswith("途中で止まりました（TimeoutExpired）"),
                   (md / "s.md").read_text(encoding="utf-8"), (md / "l.md").read_text(encoding="utf-8")),
                  (False, True, "S0", "L0"))
        finally:
            (AM.ARTICLES, AM.is_article, AM.fm, AM._claude, AM.check, AM.url_of,
             AR.meta, AR.warns, AR.snapshot, AR.sh) = saved


def test_markdown_source_link_removal_is_caught():
    import auto_rewrite as AR
    print("\n■ 「出典リンクが消えました」は Markdown のリンクも見る")
    before = "根拠は[中小企業庁](https://www.chusho.meti.go.jp/x)の資料です。"
    check("Markdown の出典を消すと失われた出典に数える",
          AR.sources(before) - AR.sources("根拠は中小企業庁の資料です。"), {"https://www.chusho.meti.go.jp/x"})


def test_category_round_trip_does_not_make_redirect_loop():
    import build as B
    print("\n■ カテゴリを行って戻しても、公開中の記事を転送元にした行を残さない（転送の輪を作らない）")
    with tempfile.TemporaryDirectory(prefix="gate_h119_", ignore_cleanup_errors=True) as td:
        site = Path(td)
        page = '<main class="article zz"><script type="application/ld+json">{"@type":"BlogPosting"}</script></main>'
        (site / "seo" / "zz-move").mkdir(parents=True)
        (site / "seo" / "zz-move" / "index.html").write_text(page, encoding="utf-8")
        (site / "_redirects").write_text("/old/  /new/  301\n/aio/zz-move/  /seo/zz-move/  301\n", encoding="utf-8")
        saved = (B.SITE, B.CATEGORIES)
        try:
            B.SITE, B.CATEGORIES = site, {"aio": {}, "seo": {}}
            entries = [({"category": "aio", "slug": "zz-move"}, None)]
            buf = io.StringIO()
            with redirect_stdout(buf):
                gone = B.prune_orphan_articles(entries, set())
        finally:
            B.SITE, B.CATEGORIES = saved
        rules = [ln.split()[:2] for ln in (site / "_redirects").read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
        check("移した後の古いURLを消した", gone, ["seo/zz-move"])
        check("転送の行: 公開中の /aio/zz-move/ を転送元にしない・新しい転送は1本・関係ない行は残す",
              rules, [["/old/", "/new/"], ["/seo/zz-move/", "/aio/zz-move/"]])
        srcs = {a for a, _ in rules}
        check("転送の輪が無い", any(b in srcs and dict(rules).get(b) == a for a, b in rules), False)


def test_rollback_keeps_second_title_and_writes_yaml_safely():
    import yaml
    import rewrite_rollback as RR
    print("\n■ 題を戻すのは、今の題がその直しの後の題のときだけ。戻す題は YAML として読める形で書く")
    with tempfile.TemporaryDirectory(prefix="gate_h119_", ignore_cleanup_errors=True) as td:
        r = Path(td)
        (r / "articles").mkdir()
        p = r / "articles" / "zz-post.md"
        saved = RR.ROOT
        d = {"slug": "zz-post", "kind": "title", "before_title": "経理代行の費用: 相場と #3 の選び方",
             "after_title": "経理代行の費用と選び方", "before_description": "説明: 相場の話",
             # 説明文は直した後の説明文のままのときだけ戻す（2026-10-20。違う回は h122 が確かめる）
             "after_description": "今"}
        try:
            RR.ROOT = r
            p.write_text("---\ntitle: 2回目に直した題\ndescription: 今\n---\n本文\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                ok = RR.restore("zz-post", d)
            check("2回目の直しが入った題は戻さない（理由を残す）",
                  (ok, "2回目に直した題" in p.read_text(encoding="utf-8"), bool(RR.SKIPPED.pop("zz-post", ""))),
                  (False, True, True))
            p.write_text("---\ntitle: 経理代行の費用と選び方\ndescription: 今\n---\n本文\n", encoding="utf-8")
            ok = RR.restore("zz-post", d)
            fm = yaml.safe_load(p.read_text(encoding="utf-8").split("---")[1])
            check("今の題がこの直しの後の題なら戻し、題・説明文は読み戻しても同じ",
                  (ok, fm["title"], fm["description"]), (True, d["before_title"], d["before_description"]))
            p.write_text("---\ntitle: 経理代行の費用と選び方\n---\n本文\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                ok = RR.restore("zz-post", {**d, "after_title": ""})
            RR.SKIPPED.pop("zz-post", None)
            check("直した後の題が台帳に無い行は確かめられないので戻さない", ok, False)
        finally:
            RR.ROOT = saved


def test_rerender_applies_publish_gates():
    import publish_rerender as P
    print("\n■ 描き直しの送り直しも publish.py と同じ門を通す（止める記事は送らない）")
    with tempfile.TemporaryDirectory(prefix="gate_h119_", ignore_cleanup_errors=True) as td:
        src = Path(td) / "zz-post.md"
        src.write_text("---\ntitle: t\n---\n本文\n", encoding="utf-8")
        cfg = {"id": "zz-own", "type": "external-html", "categories": {"zz-cat": {}}, "domain": "zz.example"}
        meta = {"slug": "zz-post", "category": "zz-cat", "title": "t", "description": "d", "score": 95,
                "score_breakdown": {"originality": 95, "extractability": 95, "decision": 95}}
        got = P.redeliver_problems(cfg, meta, "<<<<<<< HEAD\n本文<script>alert(1)</script>\n", src)
        check("衝突マーカー・入れてはいけない HTML を止める",
              [w in got for w in ("衝突マーカー", "入れてはいけない HTML")], [True, True])
        got = P.redeliver_problems(cfg, {**meta, "score": 70}, "本文\n", src)
        check("公開基準未達も止める", "公開基準未達" in got, True)
    rr = (ROOT / "scripts" / "publish_rerender.py").read_text(encoding="utf-8")
    check("WordPress・FTP/ZIP・Git の3つの道すべてで門を通す", rr.count(", counts, hold)"), 3)
    check("門は main と同じ検査の関数を呼ぶ",
          all(x in rr for x in ("legal_claims.find(", "publish.gate_ok(", "editorial_review.reviewed(", "operator_leaks(",
                                "ng_words", "private_store.require(", "html_safety.article_problems(",
                                "publish.pre_problems(", "publish.foreign_links(")), True)
    check("見送った数を出す", rr.count("report_held(counts, hold"), 3)


def test_publish_changed_does_not_retry_gate_blocks():
    import publish_changed as PC
    print("\n■ 門で止まった記事はやり直さず、「3本続けて失敗＝環境の問題」に数えない")
    check("門の止めを見分ける",
          [PC.gate_blocked(s, "zz") for s in ("BLOCKED(公開不可): x", "HELD(監修待ち): x", "公開基準未達のため配信しません: score=80",
                                              "カテゴリ 'a' は zz に定義されていません", "pushできません。次の順に", "Traceback")],
          [True, True, True, True, False, False])
    saved = (PC.subprocess, PC.time, PC.sites_mod.load, PC.site_articles, sys.argv)
    calls, sleeps = [], []
    out = {"err": ""}

    def run(args, **k):
        calls.append(args)
        return subprocess.CompletedProcess(args, 1, "", out["err"])
    try:
        PC.subprocess = types.SimpleNamespace(run=run, CompletedProcess=subprocess.CompletedProcess)
        PC.time = types.SimpleNamespace(sleep=lambda s: sleeps.append(s), time=time.time)
        PC.sites_mod.load = lambda sid: {"id": sid, "type": "external-html", "name": "zz", "repo": "zz/zz"}
        PC.site_articles = lambda sid: ["zz-a", "zz-b", "zz-c", "zz-d"]
        sys.argv = ["publish_changed.py", "--site", "zz-own", "--push"]
        out["err"] = "BLOCKED(公開不可): zz-a に入れてはいけない HTML"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = PC.main()
        check("門の止めは1本1回だけ呼び、待たず、打ち切らない",
              (len(calls), len(sleeps), "環境の問題" in buf.getvalue(), rc), (4, 0, False, 1))
        calls.clear()
        out["err"] = "pushできません。次の順に確かめてください。"
        with redirect_stdout(io.StringIO()):
            PC.main()
        check("環境の失敗は従来どおり1回やり直し、3本続けば打ち切る", (len(calls), len(sleeps)), (6, 3))
    finally:
        PC.subprocess, PC.time, PC.sites_mod.load, PC.site_articles, sys.argv = saved
