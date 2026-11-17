# -*- coding: utf-8 -*-
"""週次の本体が3時間で打ち切られた（2026-11-16）ときに見つけた、時間の無駄の門。

- お客様の社への push が20分止まり、失敗の理由も捨てていた → 上限（PUSH_TIMEOUT 秒）をつけ、理由を伏せ字つきで出す
- AIっぽい言い回しの機械の直しが、記事1本ごとに node を起動していた（559本で8分・直した数0）→ まとめて1回
- 題の判定期間中の記事が、--skip-recent の無い呼び出しで本数の枠を使っていた（題の戻しの約9割）→ いつも先に外す
- 同型記事の統合が、組が0の週にも先に自己診断（17分半）を回していた → 組があるときだけ（--guarded）
- 直しの指示に機械の検査の決まり（FAQ の字数・H2 の数）が無く、検査に外れて戻されていた → 指示に書く
本物の git の push・claude・textlint は呼ばない。
"""
import contextlib
import inspect
import io
import json
import sys
import time

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


@contextlib.contextmanager
def patched(*items):
    old = [(o, n, getattr(o, n)) for o, n, _ in items]
    try:
        for o, n, v in items:
            setattr(o, n, v)
        yield
    finally:
        for o, n, v in old:
            setattr(o, n, v)


def out_of(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a, **k)
    return rc, buf.getvalue()


def test_push_has_a_time_limit_and_says_why():
    print("\n■ 配信先への push: 上限をつけ、失敗の理由を伏せ字つきで出す")
    import publish as P
    msg = ("To https://github.com/owner/client-site.git\n ! [rejected] HEAD -> main (fetch first)\n"
           "remote: Permission to owner/client-site.git denied to bot. ghp_abcdef123456")
    why = P.why_failed(msg)
    check("理由に git のエラー文が残る", "rejected" in why and "Permission" in why, True)
    check("URL・リポジトリ名・トークンは出さない", any(s in why for s in ("github.com", "owner/client-site", "abcdef123456")), False)
    t0 = time.time()
    rc, out = out_of(P.try_run, [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1, say=True)
    check("上限を過ぎたら止めて失敗にする（待ち続けない）", (rc, time.time() - t0 < 15), (False, True))
    check("止めたことを出す", "秒で終わらないため止めました" in out, True)
    rc, out = out_of(P.try_run, [sys.executable, "-c", "import sys; sys.stderr.write('boom-reason'); sys.exit(1)"], say=True)
    check("失敗の理由を出す", (rc, "boom-reason" in out), (False, True))
    rc, out = out_of(P.try_run, [sys.executable, "-c", "import sys; sys.exit(1)"])
    check("say の無い呼び出しは黙ったまま（rebase --abort などの後始末）", (rc, out), (False, ""))
    src = inspect.getsource(P.push_work)
    check("push と fetch に上限を渡す", src.count("timeout=PUSH_TIMEOUT") >= 2 and "say=True" in src, True)
    check("素のURLは端末で聞かない（GIT_TERMINAL_PROMPT=0）", 'GIT_TERMINAL_PROMPT="0"' in src, True)
    check("上限は数分以内", 30 <= P.PUSH_TIMEOUT <= 300, True)


def test_machine_fix_starts_textlint_once():
    print("\n■ AIっぽい言い回しの機械の直し: textlint はまとめて1回だけ起動する")
    import ai_writing as AW
    calls = []

    def fake_run(texts, mode="lint", config=None):
        calls.append((mode, len(texts)))
        return [{"output": t.replace("出来ます", "できます"), "applied": [{"ruleId": "ja-no-abusage"}] if "出来ます" in t else []}
                for t in texts]
    texts = ["本文A。\n", "増やすことが出来ます。\n", "本文C。\n"]
    with patched((AW, "run", fake_run), (AW, "mask", lambda t: t)):
        got = AW.fix_all(texts)
    check("起動は1回（3本まとめて）", calls, [("fix", 3)])
    check("直した結果は元の並びのまま", [g[0] for g in got], ["本文A。\n", "増やすことができます。\n", "本文C。\n"])
    calls.clear()
    with patched((AW, "FIXER", lambda t: (t + "x", [])), (AW, "run", fake_run)):
        got = AW.fix_all(["a"])
    check("門で差し替えた FIXER はそのまま使う（本物の textlint を呼ばない）", (got, calls), ([("ax", [])], []))
    src = inspect.getsource(AW.main)
    check("--fix はまとめた結果を1本ずつ検算に回す", "fix_all(" in src and "fixed=f" in src, True)


def test_locked_titles_are_dropped_before_drafting():
    print("\n■ 題の判定期間中の記事は、--skip-recent が無くても下書きの前に外す")
    import auto_rewrite as AR
    import article_health
    import noindex
    items = [{"kind": "title", "slug": "a-locked", "why": "w"}, {"kind": "title", "slug": "b-free", "why": "w"},
             {"kind": "aio", "slug": "a-locked", "why": "w"}]
    same = lambda xs, *a, **k: xs
    old_argv = sys.argv
    sys.argv = ["auto_rewrite.py", "--limit", "5"]
    try:
        with patched((AR, "targets", lambda: [dict(x) for x in items]), (AR, "title_locked", lambda s, **k: "2026-11-09" if s == "a-locked" else ""),
                     (AR, "only_sites", same), (AR, "stock_first", same), (AR, "buyer_first", same),
                     (AR, "shown", lambda s: s), (AR, "said", lambda s, w: w),
                     (noindex, "drop", same), (article_health, "drop_protected", same)):
            rc, out = out_of(AR.main)
    finally:
        sys.argv = old_argv
    check("判定期間中の題は候補に残らない", "[title] a-locked" in out, False)
    check("ほかの題は残る", "[title] b-free" in out, True)
    check("同じ記事の別の種類の直しは残る", "[aio] a-locked" in out, True)
    check("外したことを出す", "題の判定期間中の1本は直しません" in out, True)


def test_scaled_merge_selftest_only_when_there_is_a_pair():
    print("\n■ 統合: 自己診断は統合できる組があるときだけ、統合の前に回す")
    import auto_merge as AM
    ran = []
    old_argv = sys.argv
    try:
        sys.argv = ["auto_merge.py", "--scaled", "--guarded", "--write"]
        with patched((AM, "scaled_candidates", lambda site="": []), (AM, "selftest", lambda scaled=False: ran.append(scaled) or 0)):
            rc, out = out_of(AM.main)
        check("組が0なら自己診断を回さない", (rc, ran, "統合できる組はありません" in out), (0, [], True))
        pair = {"site": "s", "sim": 0.3, "loser": "l", "survivor": "w", "skip": "", "loser_stat": {}, "survivor_stat": {}}
        merged = []
        with patched((AM, "scaled_candidates", lambda site="": [dict(pair)]), (AM, "skip_noindex", lambda ps: ps),
                     (AM, "selftest", lambda scaled=False: ran.append(scaled) or 1),
                     (AM, "run_one", lambda *a, **k: merged.append(a) or (True, "統合しました"))):
            rc, out = out_of(AM.main)
        check("組があれば先に自己診断し、効いていなければ統合せず3で終わる", (rc, ran, merged), (3, [True], []))
    finally:
        sys.argv = old_argv
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次は2つの統合とも --guarded で呼び、3を検算の失敗として知らせる",
          wf.count("--guarded --write") == 2 and wf.count('if [ "$rc" = 3 ]; then') >= 2, True)


def test_rewrite_prompts_carry_the_machine_rules():
    print("\n■ 直しの指示に、機械の検査で戻される決まり（FAQ の字数・H2 の数）を書く")
    import auto_merge as AM
    import auto_rewrite as AR
    for name, text in (("書き直し（全種類の共通の指示）", AR.PROMPT), ("統合", AM.PROMPT)):
        check(f"{name}: FAQ の答えは30〜75字", "FAQ の答えは40〜60字（30字未満・75字超は不可）" in text, True)
        check(f"{name}: H2 は6〜12個", "6〜12個" in text, True)
    check("指示は format で崩れない", "{" not in AR.PROMPT.format(slug="s", why="w", what="x"), True)
    json.dumps(AM.PROMPT)
