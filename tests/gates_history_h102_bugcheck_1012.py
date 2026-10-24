# -*- coding: utf-8 -*-
"""2026-10-12 運用者「自動化システムはばぐないか」の点検で見つけた不具合の門。

1. 取り下げ（retract）: 1社・1件の失敗（鍵が無い・接続できない）で、ほかの社の分と済んだ印を失わない。
   お客様の社の slug・URL を CI のログに出さない
2. 重複の検査（cannibal_check）: お客様の社の語・題・URL は、その社の回（--site）でだけ出す。
   ほかの社の回・週次の出力は CI のログ（public）とほかの社の AI に渡る
3. 配信先の記事の一覧（external_index）: お客様の社の分は public の data/external_articles.json に書かず置き場へ
4. 自動修復: git が実際に当てた形でもう一度判定し、直近24時間に自動で入れた修復があれば続けて入れない。
   書き直しは落ちた回の日を数え、push に失敗したら知らせる
架空の社（client-zz・zz.example）で試す。お客様の社の名前・記事の題・slug は書かない。
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

CL = "client-zz"
PUB = "c00000zz"


def _fake_sites():
    import sites as S
    return [mock.patch.object(S, "is_client", lambda s: s in (CL, PUB)),
            mock.patch.object(S, "public_id", lambda s: PUB if s in (CL, PUB) else s),
            mock.patch.object(S, "resolve", lambda s: CL if s in (CL, PUB) else s)]


def test_retract_survives_one_failure_and_hides_client_names():
    print("\n■ 取り下げ: 1社・1件の失敗で残りと済んだ印を失わず、お客様の slug・URL をログに出さない")
    import retract as R
    import sites as S
    rows = [{"site": CL, "slug": "zz-secret-slug", "from": "/blog/zz-secret-slug/", "to": "/blog/zz-x/"},
            {"site": "corporate", "slug": "zz-own", "from": "/blog/zz-own/", "to": "/blog/zz-b/"}]
    saved, seen = [], []

    def fake_site(sid, items, push):
        seen.append(sid)
        if sid == CL:
            raise SystemExit("鍵がありません")
        for r in items:
            r["done_at"] = "2026-10-12"
    with contextlib.ExitStack() as st:
        for p in _fake_sites():
            st.enter_context(p)
        st.enter_context(mock.patch.object(R, "load", lambda: rows))
        st.enter_context(mock.patch.object(R, "save", saved.append))
        st.enter_context(mock.patch.object(R, "_site", fake_site))
        st.enter_context(mock.patch.object(sys, "argv", ["retract.py", "--pending", "--push"]))
        out = st.enter_context(contextlib.redirect_stdout(io.StringIO()))
        R.main()
    check("1社目が止まっても2社目を続け、済んだ印を書き残す（お客様の社の id はログに出さない）",
          (seen, len(saved), saved[0][1].get("done_at"), CL in out.getvalue()),
          ([CL, "corporate"], 1, "2026-10-12", False))
    with contextlib.ExitStack() as st:
        for p in _fake_sites():
            st.enter_context(p)
        out = st.enter_context(contextlib.redirect_stdout(io.StringIO()))
        R._say(CL, rows[0], "下書きに戻しました", "（/blog/zz-secret-slug/ → /blog/zz-x/）")
        R._say("corporate", rows[1], "済み", "（/blog/zz-own/ → /blog/zz-b/）")
    t = out.getvalue()
    check("お客様の社は公開の id と「（お客様の記事）」だけ・自社は slug と URL を出す",
          ("zz-secret-slug" in t, PUB in t, "zz-own" in t and "/blog/zz-b/" in t), (False, True, True))
    import publish
    import wp_bridge
    items = [{"slug": "zz-a", "from": "/blog/zz-a/", "to": "/blog/zz-x/"},
             {"slug": "zz-b", "from": "/blog/zz-b/", "to": "/blog/zz-x/"}]

    def wp_call(cfg, path, data=None):
        if "slug=zz-a" in path:
            raise SystemExit("接続できません")
        return [{"id": 7, "link": "https://zz.example/blog/zz-b/"}] if path.startswith("posts?") else {}
    with contextlib.ExitStack() as st:
        for p in _fake_sites():
            st.enter_context(p)
        st.enter_context(mock.patch.object(S, "load", lambda s: {"type": "wordpress", "id": s}))
        st.enter_context(mock.patch.object(publish, "_wp_call", wp_call))
        st.enter_context(mock.patch.object(wp_bridge, "post_link", lambda c, s: None))
        out = st.enter_context(contextlib.redirect_stdout(io.StringIO()))
        R._site(CL, items, True)
    check("WordPress: 1件目の接続の失敗で止まらず、2件目は下書きに戻して済みにする（slug はログに出さない）",
          ([bool(r.get("done_at")) for r in items], "zz-a" in out.getvalue() or "zz-b" in out.getvalue()),
          ([False, True], False))


def test_dup_checks_show_client_words_only_in_their_own_run():
    print("\n■ 重複の検査: お客様の社の語・題・URL は、その社の回（--site）でだけ出す")
    import cannibal_check as C
    with contextlib.ExitStack() as st:
        for p in _fake_sites():
            st.enter_context(p)
        st.enter_context(mock.patch.object(sys, "argv", ["cannibal_check.py", "--cross", "--site", "corporate"]))
        other = (C._t(CL, "zz-秘密の語"), C._t("corporate", "経理代行 費用"), C._site_name(CL))
        st.enter_context(mock.patch.object(sys, "argv", ["cannibal_check.py", "--cross", "--site", PUB]))
        mine = C._t(CL, "zz-秘密の語")
        st.enter_context(mock.patch.object(sys, "argv", ["cannibal_check.py"]))
        weekly = C._t(CL, "zz-秘密の語")
    check("ほかの社の回・週次は伏せ（社は公開の id）、その社の回（公開の id で渡しても）は出す・自社はいつも出す",
          (other, mine, weekly), (("（お客様の語）", "経理代行 費用", PUB), "zz-秘密の語", "（お客様の語）"))
    src = (ROOT / "scripts" / "cannibal_check.py").read_text(encoding="utf-8")
    import re
    raw = [ln.strip() for ln in src.splitlines()
           if ln.strip().startswith("print(") and re.search(r"\{(a|b|other|h\['kw'\]|h\['art'\])\['keyword'\]\}", ln)]
    check("横断・同じサイト内・領域の侵食の行は、語をそのまま出さない（_t を通す）", raw, [])
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    check("記事の枠は横断の検査にその回の社を渡す（3か所）",
          wf.count('cannibal_check.py --cross --site "${{ steps.site.outputs.id }}"'), 3)


def test_external_index_keeps_client_lists_private():
    print("\n■ 配信先の記事の一覧: お客様の社の分は public の一覧に書かず置き場へ")
    import external_index as E
    import client_private as CP
    import sites as S
    cfgs = {"corporate": {"id": "corporate", "type": "external-md", "domain": "corp.example"},
            CL: {"id": CL, "type": "ftp", "domain": "zz.example"}}
    with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as st:
        d = Path(d)
        for p in _fake_sites():
            st.enter_context(p)
        st.enter_context(mock.patch.object(S, "load_all", lambda: cfgs))
        st.enter_context(mock.patch.object(E, "CACHE", d / "external_articles.json"))
        st.enter_context(mock.patch.object(CP, "private_path", lambda sid, rel: d / "clients" / sid / rel))
        st.enter_context(mock.patch.object(E, "site_articles", lambda cfg: [
            {"url": f"https://{cfg['domain']}/blog/zz-1/", "slug": "zz-1", "title": f"{cfg['id']} の記事"}]))
        out = st.enter_context(contextlib.redirect_stdout(io.StringIO()))
        built = E.build()
        pub = json.loads((d / "external_articles.json").read_text(encoding="utf-8"))
        priv = (d / "clients" / CL / "data" / "external_articles.json").is_file()
        again = E.load()
    check("public の一覧は自社だけ・置き場にお客様の分・読むときは両方・ログに社の id とドメインを出さない",
          (sorted(pub["sites"]), priv,
           sorted(built["sites"]), sorted(again["sites"]), CL in out.getvalue() or "zz.example" in out.getvalue()),
          (["corporate"], True, sorted(["corporate", CL]), sorted(["corporate", CL]), False))


def test_widen_keeps_the_run_baseline():
    print("\n■ 範囲を戻しても「この回の始まり」（ss_base）は置き直さない（AI の前の機械の直しも配り直しに入れる）")
    import private_store as PS
    with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as st:
        b = Path(d)
        (b / ".git").mkdir()
        (b / ".git" / "ss_base").write_text("OLD", encoding="utf-8")
        st.enter_context(mock.patch.object(PS, "base", lambda: b))
        st.enter_context(mock.patch.object(PS, "_write_exclude", lambda rels: None))
        st.enter_context(mock.patch.object(PS, "_write_record", lambda rels: None))
        st.enter_context(mock.patch.object(PS, "_exclude_entries", lambda: []))
        st.enter_context(mock.patch.object(PS, "_git", lambda *a: mock.Mock(stdout="NEW\n", returncode=0)))
        PS.overlay_in(mark=False)
        after_widen = (b / ".git" / "ss_base").read_text(encoding="utf-8")
        PS.overlay_in()
        after_fetch = (b / ".git" / "ss_base").read_text(encoding="utf-8")
    src = (ROOT / "scripts" / "private_store.py").read_text(encoding="utf-8")
    w = src[src.index("def widen("):]
    w = w[:w.index("\ndef ", 10)]
    check("範囲を戻すときは置き直さず、取得の後だけ置く（widen は overlay_in(mark=False)）",
          (after_widen, after_fetch, "overlay_in(mark=False)" in w, "overlay_in()" in w), ("OLD", "NEW", True, False))


def test_selfheal_rejudges_applied_diff_and_limits_auto_fixes():
    print("\n■ 自動修復: 当てた形で判定し直す・24時間に1回まで・書き直しは落ちた回の日・push の失敗を知らせる")
    wf = (ROOT / ".github" / "workflows" / "selfheal.yml").read_text(encoding="utf-8")
    rb = wf[wf.index("  repair-branch:"):wf.index("  rerun:")]
    check("取り込む前に、git が当てた差分（--no-renames）を patch_policy でもう一度判定する",
          ("diff --cached --no-renames --binary > /tmp/applied.patch" in rb,
           rb.index("/tmp/applied.patch") < rb.index('git -C /tmp/apply commit -q -m "selfheal: 不具合を自動修復')),
          (True, True))
    check("直近24時間に自動で取り込んだ修復があれば、枝に置く",
          ("24 hours ago" in rb and "grep -c '^selfheal: 不具合を自動修復'" in rb), True)
    heal = wf[:wf.index("  repair-branch:")]
    lock = heal[heal.index("- name: 書き直しの前にAIの作業場から鍵を外す"):heal.index("- name: 修復後に記事を書き直す（AI）")]
    check("書き直しは落ちた回が始まった時刻から数える日を決める（AUDIT_DAY）",
          ('daily_audit.py --rescue-day "$FAILED_STARTED"' in lock and "GITHUB_ENV" in lock), True)
    pub = heal[heal.index("- name: 修復後に記事を書き直す（配信とコミット）"):]
    pub = pub[:pub.index("- name:", 10)]
    check("書き直した記事の push は3回まで試し、だめなら知らせて失敗にする",
          ("for i in 1 2 3" in pub, "notify_slack.py" in pub, "exit 1" in pub), (True, True, True))
    import daily_audit as DA
    from datetime import datetime
    check("落ちた回の時刻: 最初の枠より前（0:28）は前日・後（10:10）はその日",
          (DA.rescue_day(datetime.fromisoformat("2026-10-12T00:28:00+09:00")),
           DA.rescue_day(datetime.fromisoformat("2026-10-11T10:10:00+09:00"))), ("2026-10-11", "2026-10-11"))


# ── 2つ目のまとまり（範囲の絞り込み・AI の読み取り・本数の見張り・KPI の未取得） ─────────────

def _art(cat, body="本文"):
    return f"---\ntitle: t\ncategory: {cat}\nkeyword: k\n---\n{body}\n"


def test_protect_never_deletes_without_a_checkpoint_and_catches_category_swaps():
    print("\n■ 範囲の外を戻す: 控えの無い回は何もしない・追跡している原稿は消さない・カテゴリの付け替えも戻す")
    import subprocess
    import agent_guard as G
    import sites as S
    owners = {"keiri-bpo": "corporate", "zzcat": CL}
    with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as st:
        d = Path(d)
        root, tmp = d / "w", d / "tmp"
        (root / "articles").mkdir(parents=True)
        tmp.mkdir()
        g = lambda *a: subprocess.run(["git", "-C", str(root), *a], capture_output=True)
        g("init", "-q")
        a = root / "articles"
        (a / "zz-tracked.md").write_text(_art("zzcat"), encoding="utf-8")
        g("add", "-A")
        g("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init")
        (a / "zz-own.md").write_text(_art("keiri-bpo"), encoding="utf-8")
        (a / "zz-client.md").write_text(_art("zzcat"), encoding="utf-8")
        st.enter_context(mock.patch.object(G, "_state_path", lambda: tmp / "agent_guard.json"))
        st.enter_context(mock.patch.object(G, "_scope_sites", lambda site, root=None: {"corporate"}))
        st.enter_context(mock.patch.object(S, "find_category_owner", lambda c: owners.get(c)))
        out = st.enter_context(contextlib.redirect_stdout(io.StringIO()))
        # 1) 控えが無い（鍵を外す手順も範囲ごとの控えも動かなかった）回は、何も消さない
        nolock = G._protect_other_sites(root, "corporate"), G._protect_other_sites(root, "corporate", by_pass=True)
        files0 = sorted(p.name for p in a.glob("*.md"))
        # 2) 控えを作ってから AI が動いた形
        (a / "zz-tracked.md").unlink()           # 範囲を絞って作業場所から外れた、追跡している原稿（控えに無い）
        G.checkpoint(root)
        (a / "zz-tracked.md").write_text(_art("zzcat"), encoding="utf-8")
        (a / "zz-own.md").write_text(_art("zzcat", "持ち出し"), encoding="utf-8")       # 自社の記事をお客様のカテゴリへ
        (a / "zz-client.md").write_text(_art("keiri-bpo", "付け替え"), encoding="utf-8")  # お客様の記事を自社のカテゴリへ
        (a / "zz-new-own.md").write_text(_art("keiri-bpo"), encoding="utf-8")
        (a / "zz-new-client.md").write_text(_art("zzcat"), encoding="utf-8")
        (a / "zz-new-unknown.md").write_text(_art("nope"), encoding="utf-8")
        G._protect_other_sites(root, "corporate", by_pass=True)
        left = sorted(p.name for p in a.glob("*.md"))
        own_back = (a / "zz-own.md").read_text(encoding="utf-8")
        client_back = (a / "zz-client.md").read_text(encoding="utf-8")
        aside = (tmp / "agent_unowned" / "zz-new-unknown.md").is_file()
    check("控えの無い回は何もしない（全部を新しい記事とみなして消さない）",
          (nolock, files0), (([], []), ["zz-client.md", "zz-own.md", "zz-tracked.md"]))
    check("追跡している原稿は消さない・範囲の外の新しい記事は消す・社の決まらない新しい記事はよける・範囲の新しい記事は残す",
          (left, aside), (["zz-client.md", "zz-new-own.md", "zz-own.md", "zz-tracked.md"], True))
    check("カテゴリを付け替えた記事は、今の社か前の社が範囲の外なら控えへ戻す",
          ("category: keiri-bpo" in own_back and "持ち出し" not in own_back,
           "category: zzcat" in client_back and "付け替え" not in client_back), (True, True))
    check("知らせる: 控えが無い・社の決まらない記事をよけた", ("AGENT_PROTECT=skip" in out.getvalue(),
          "要対応: 社の決まらない新しい記事 1本" in out.getvalue()), (True, True))
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    prot = wf[wf.index("- name: AIの変更のうち触ってはいけない場所を戻す"):wf.index("- name: AIの作業場に鍵を戻す")]
    unl = wf[wf.index("- name: AIの作業場に鍵を戻す"):]
    unl = unl[:unl.index("- name:", 10)]
    check("記事の枠: 鍵を外す手順（id: lock）が動かなかった回は、戻す・鍵を戻す手順も動かさない",
          ("id: lock" in wf, "steps.lock.outcome != 'skipped'" in prot, "steps.lock.outcome != 'skipped'" in unl),
          (True, True, True))
    ap = (ROOT / "scripts" / "agent_passes.sh").read_text(encoding="utf-8")
    check("範囲ごとの回: 絞れない・控えを作れない範囲は AI を起こさない",
          ('if ! python scripts/private_store.py --scope "$sc"; then' in ap,
           "if ! python scripts/agent_guard.py --checkpoint; then" in ap), (True, True))


def test_scope_fails_closed_and_keeps_its_record_per_workspace():
    print("\n■ 絞り込み: 落ちたら全部へ戻して非0・記録は作業場所ごと・新しく入る他社カテゴリの記事は commit を止める")
    import private_store as PS
    calls = []
    with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as st:
        st.enter_context(mock.patch.dict("os.environ", {"RUNNER_TEMP": d, "PRIVATE_SCOPE_FORCE": "1"}))
        st.enter_context(mock.patch.object(PS, "_narrow", mock.Mock(side_effect=RuntimeError("試験"))))
        st.enter_context(mock.patch.object(PS, "widen", lambda: calls.append("widen") or True))
        st.enter_context(contextlib.redirect_stdout(io.StringIO()))
        ok = PS.scope("own")
        rec = PS._scope_state().is_file()
    check("途中で落ちたら False・記録を残して全部へ戻す（呼び出し側は AI を起こさない）", (ok, calls, rec), (False, ["widen"], True))
    src = (ROOT / "scripts" / "private_store.py").read_text(encoding="utf-8")
    check("--scope は絞れなければ終了コード1", 'return 0 if scope(a[i + 1] if i + 1 < len(a) else "all") else 1' in src, True)
    a_ = PS._scope_state().name
    with mock.patch.object(PS, "ROOT", Path(tempfile.gettempdir()) / "zz-other-workspace"):
        b_ = PS._scope_state().name
    check("絞りの記録は作業場所ごと（手元で一時の場所を共有しても、別の作業場所の記録で戻さない）",
          (a_ != b_, a_.startswith("private_scope_") and b_.startswith("private_scope_")), (True, True))
    check("絞るときは無視されたファイル（__pycache__）も消し、記事は category で外す（_merged・_conflicted も）",
          ('b.rglob("__pycache__")' in src, 'for q in sorted((ROOT / "articles").rglob("*.md"))' in src,
           '"core.quotePath=false", "ls-files", "-t"' in src), (True, True, True))
    import sites as S
    own_cat = next(c for s, cfg in S.load_all().items() if not S.is_client(s) for c in (cfg.get("categories") or {}))
    with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as st:
        d = Path(d)
        (d / "articles").mkdir()
        (d / "articles" / "zz-x.md").write_text(_art("zzcat"), encoding="utf-8")
        (d / "articles" / "zz-own.md").write_text(_art(own_cat), encoding="utf-8")
        st.enter_context(mock.patch.object(PS, "ROOT", d))
        st.enter_context(mock.patch.object(PS, "_public_git", lambda *a: mock.Mock(
            stdout="articles/zz-x.md\narticles/zz-own.md\nscripts/x.py\n", returncode=0)))
        bad = PS.foreign_new_articles()
    check("commit の見張り: 公開側に新しく入る記事のうち自社のカテゴリでないものを止める", bad, ["articles/zz-x.md"])
    pc = src[src.index("def pre_commit("):]
    pc = pc[:pc.index("\ndef ", 5)]
    check("見張りはお客様の記事を外した後に見る（非公開の置き場が無い回も見る）",
          (pc.index("overlay_out(unstage=True)") < pc.index("bad = foreign_new_articles()"),
           "return 0\n" not in pc[:pc.index("bad = foreign_new_articles()")]), (True, True))


def test_ai_cannot_read_private_git_or_gate_caches():
    print("\n■ 記事を書く AI: 非公開の置き場の git・読むだけの Bash・お客様の門を読ませない")
    s = json.loads((ROOT / "automation" / "agent_settings_article.json").read_text(encoding="utf-8"))
    deny = s["permissions"]["deny"]
    need = ["Bash(git *)", "Bash(git)", "Bash(cat *)", "Bash(ls *)", "Bash(ls)", "Bash(head *)", "Bash(find *)",
            "Bash(grep *)", "Read(private/tests/**)", "Read(//**/private/tests/**)"]
    check("拒む一覧に git・cat・ls・head・find・grep と private/tests がある", [x for x in need if x not in deny], [])
    allow = s["permissions"]["allow"]
    check("許す一覧の Bash は決まった scripts の python だけ（拒む一覧と重ならない）",
          [x for x in allow if x.startswith("Bash(") and not x.startswith(("Bash(python scripts/", "Bash(python3 scripts/"))], [])
    jc = (ROOT / ".github" / "workflows" / "agent-jail-check.yml").read_text(encoding="utf-8")
    check("点検のワークフローが git・cat・通行証の読み取りを試し、動いたら失敗にする",
          ("7) Bash で git -C private rev-parse --short HEAD" in jc, "10) Bash で cat $RUNNER_TEMP/hub_tokens/own" in jc,
           "AI が止めるべき操作を実行できました" in jc), (True, True, True))


def test_watchers_flag_too_many_articles_and_missing_search_numbers():
    print("\n■ 見張り: 1日の本数より多い日も知らせる・Search Console の数字がまだ無い日を0で送らない")
    import outcome_watch as OW
    import daily_audit as D
    import sites as S
    from datetime import date
    arts = [{"slug": f"zz-{i}", "date": "2026-10-11", "category": "aio"} for i in range(3)]
    bad = []
    with contextlib.ExitStack() as st:
        st.enter_context(mock.patch.object(D, "articles_by_site", lambda: {"ai-lab": arts}))
        st.enter_context(mock.patch.object(S, "load_all", lambda: {"ai-lab": {"name": "試験", "domain": "zz.example"}}))
        st.enter_context(mock.patch.object(D, "_is_published", lambda a, need_review=True: True))
        st.enter_context(mock.patch.object(OW, "expected_articles", lambda sid, arts, day: 2))
        st.enter_context(mock.patch.object(S, "article_url", lambda cfg, a: "https://zz.example/x/"))
        st.enter_context(mock.patch("urllib.request.urlopen", lambda *a, **k: mock.Mock(status=200)))
        st.enter_context(contextlib.redirect_stdout(io.StringIO()))
        OW.check_articles(date(2026, 10, 11), bad)
    check("記事が1日の本数より多い日は要対応（3/2本）", sum(1 for b in bad if "3/2 本" in b and "1日の本数より多い" in b), 1)
    import daily_kpi as DK

    class _Q:
        def __init__(self, plan):
            self.plan = plan

        def searchanalytics(self):
            return self

        def query(self, siteUrl, body):
            return mock.Mock(execute=lambda: self.plan("dimensions" in body))

    def run(plan):
        with mock.patch.object(DK, "creds", lambda s: None), \
                mock.patch("googleapiclient.discovery.build", lambda *a, **k: _Q(plan)):
            return DK.gsc("https://zz.example/", "2026-10-08")
    full = {"rows": [{"impressions": 330, "clicks": 4, "ctr": 0.012, "position": 9.1}]}
    got = (run(lambda dated: full)["impressions"],
           run(lambda dated: {"rows": [{"keys": ["2026-10-09"], "impressions": 5}]} if dated else {})["impressions"],
           run(lambda dated: {"rows": []} if dated else {}))
    check("確定の数字があれば使う・後の日だけ数字があれば本当に0・どちらも無ければ未取得（0を送らない）",
          got, (330, 0, {"gsc_missing": True}))
    hub = (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")
    check("管制塔は送られなかった表示・クリックを空欄で書く（0にしない）・食い合いの応答はいつも overlaps を返す",
          ("sc(r.impressions), sc(r.clicks)" in hub, "return { ok: true, overlaps: other.map(" in hub), (True, True))


def test_small_fixes_from_ci_records():
    print("\n■ 実行記録の点検: アンカーの詰め戻し・AI Overview と AIO・他社の評判の語・小さい母数の割合・CI の .env")
    import anchor_audit as AA
    import shorten_anchors as SA
    t = "現金払いは否認の落とし穴？外注費の請求書なしで経費にする証憑3つ【2026年】"
    got = AA.natural_anchor("外注費 請求書なし", t)
    check("アンカーは shorten_anchors の上限まで（付けた直後に詰め戻されない）",
          (got is None or (len(got) <= SA.MAX and SA.shorten(got) == got)), True)
    from cannibal_check import norm_kw
    check("「AI Overview」と「AIO」は同じ語として扱う（管制塔も同じ置き換え）",
          (norm_kw("ai overview seo 対策") == norm_kw("aio seo 対策"), norm_kw("AIOverviews 表示") == norm_kw("aio 表示"),
           r"ai\s*overviews?(?![a-z])|ai\s*オーバービュー/gi" in (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")),
          (True, True, True))
    import kw_fit
    check("他社の名前の評判の語は担当の外", kw_fit.judge("エフアンドエム 記帳代行 評判", "corporate")[0], 2)
    import facts
    check("割合（クリック率）は母数が足りるときだけ", (facts.CTR_MIN_IMP, facts.CTR_MIN_CLICKS), (200, 5))
    import sheet_format as SF
    with mock.patch.dict("os.environ", {"SPREADSHEET_ID": "zz-sheet", "HUB_SHEET_ID": ""}), \
            mock.patch.object(SF, "ROOT", Path(tempfile.gettempdir()) / "zz-none"):
        check("管制塔の表の id は環境変数を先に見る（CI に .env は無い）", SF._sheet_id(), "zz-sheet")
    import auto_rewrite as AR
    rcs = iter([2, 0])
    with mock.patch.object(AR, "meta", lambda slug: ("t", "語", "")), mock.patch.object(AR, "site_of", lambda s: "subsidy"), \
            mock.patch.object(AR, "sh", lambda *a, **k: mock.Mock(returncode=next(rcs))), \
            contextlib.redirect_stdout(io.StringIO()):
        picked = AR.spare_guarded([{"slug": "zz-a", "kind": "stuck"}, {"slug": "zz-b", "kind": "stuck"}], 1)
    check("浮いた枠: 書き直す前から食い合う候補は外して次を取る", [x["slug"] for x in picked], ["zz-b"])


# ── 3つ目のまとまり（2026-10-12 運用者「これら修正」: 残りの4件） ─────────────

def test_own_pass_counts_work_with_the_map_taken_before_narrowing():
    print("\n■ 範囲ごとの仕事の数え方: 絞る前の全社の対応表で数える（自社の回がお客様の TODO を数えない）")
    import agent_work as AW
    import sites as S
    audit = ("===== 結果 =====\nTODO: zz-client-post を品質基準まで直して score を更新し、再ビルドする\n"
             "TODO: corporate の記事を本日あと 1 本作成して公開する\n--- 以下は今日やらないこと\n")
    with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as st:
        st.enter_context(mock.patch.dict("os.environ", {"RUNNER_TEMP": d}))
        for p in _fake_sites():
            st.enter_context(p)
        st.enter_context(mock.patch.object(S, "own_ids", lambda: ["ai-lab", "corporate", "subsidy"]))
        st.enter_context(mock.patch.object(S, "load_all", lambda: {"ai-lab": {}, "corporate": {}, "subsidy": {}, CL: {}}))
        # 絞る前（全社の原稿が見える）に控える
        st.enter_context(mock.patch.object(AW, "_slug_owner", lambda: {"zz-client-post": CL, "zz-own": "corporate"}))
        st.enter_context(contextlib.redirect_stdout(io.StringIO()))
        AW.snapshot()
        # 絞った後（お客様の原稿・設定が作業場所に無い）
        st.enter_context(mock.patch.object(AW, "_slug_owner", lambda: {"zz-own": "corporate"}))
        st.enter_context(mock.patch.object(S, "load_all", lambda: {"ai-lab": {}, "corporate": {}, "subsidy": {}}))
        got = (AW.rescue_count("own", audit), AW.rescue_count(PUB, audit))
    check("自社の回は自社の TODO だけ（1件）・お客様の回はその社の TODO だけ（1件）", got, (1, 1))
    ap = (ROOT / "scripts" / "agent_passes.sh").read_text(encoding="utf-8")
    check("範囲ごとの回は、絞る前に対応表を控える", ap.index("agent_work.py --snapshot") < ap.index("for sc in $scopes"), True)


def test_kw_gate_skips_keywords_that_a_published_article_already_targets():
    print("\n■ 執筆前の門: 同じサイトの公開済みの記事と同じ検索（言い換え・年の違いだけ）の語は書かない")
    import kw_gate as KG
    import sites as S
    cfg = {"subsidy": {"categories": {"hojokin": {}}, "kw_same": [["デジタル化・AI導入補助金", "AI導入補助金", "IT導入補助金"]]}}
    arts = [{"slug": "zz-it-kojin", "cat": "hojokin", "kw": "it導入補助金 2026 個人事業主"},
            {"slug": "zz-it-joken", "cat": "hojokin", "kw": "it導入補助金 条件"},
            {"slug": "zz-other", "cat": "keiri-bpo", "kw": "it導入補助金 学習塾"}]
    with mock.patch.object(S, "load_all", lambda: cfg):
        got = [KG.same_site_published(k, "subsidy", arts) for k in
               ("デジタル化 ai導入補助金2026 個人事業主", "it導入補助金 学習塾", "it導入補助金 条件 2027", "AI導入補助金 飲食店")]
    check("言い換え・年の違いだけの語は同じ検索・語の組が違えば別（文字の似かたで決めない）・別のサイトの記事は見ない",
          got, [["zz-it-kojin"], [], ["zz-it-joken"], []])
    src = (ROOT / "scripts" / "kw_gate.py").read_text(encoding="utf-8")
    check("執筆前の門は、同じ検索の公開済みの記事があれば台帳から外して次の候補へ",
          ("dup = same_site_published(kw, a.site)" in src, "同じサイトの公開済みの記事と同じ検索のため自動退避" in src), (True, True))
    sub = json.loads((ROOT / "sites" / "subsidy.json").read_text(encoding="utf-8-sig"))
    check("補助金の言い換え（旧称の IT導入補助金）は設定に書く", any("IT導入補助金" in g for g in sub.get("kw_same") or []), True)


def test_brief_cross_check_can_read_search_console():
    print("\n■ ブリーフの横断の検査: Search Console を読めるように鍵を置いてから始め、検査の後に消す")
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["write"]["steps"]
    brief = next(s for s in steps if str(s.get("name", "")).startswith("執筆ブリーフの表示"))
    cross = next(s for s in steps if s.get("name") == "全サイト横断のカニバリ・領域チェック")
    run = brief["run"]
    check("ブリーフの手順に鍵があり、裏の検査を始める前に置く",
          ("GCP_SERVICE_ACCOUNT_JSON" in (brief.get("env") or {}),
           0 <= run.find("> indexing-service-account.json") < run.find("cannibal_check.py --cross")), (True, True))
    check("横断の検査の手順の最後に鍵を消す", cross["run"].rstrip().endswith("rm -f indexing-service-account.json"), True)


def test_undelivered_warning_only_for_real_gaps():
    print("\n■ 未配信の警告: 本当に公開されていない記事と配り直しの失敗だけ（内容が古い記事の配り直しは警告にしない）")
    src = (ROOT / "scripts" / "publish_gap.py").read_text(encoding="utf-8")
    check("publish_gap は未配信と配り直しの失敗を分けて出す",
          ('print(f"PUBLISH_MISSING={total_missing}")' in src, 'print(f"PUBLISH_FAILED={total_failed}")' in src,
           "total_missing += len(missing)" in src), (True, True, True))
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    step = wf[wf.index("- name: 未配信の記事がないかの確認"):]
    step = step[:step.index("- name:", 10)]
    warn = [ln for ln in step.splitlines() if "::warning::未配信" in ln]
    check("警告は未配信か失敗があるときだけ（内容が古い分は件数をログに残すだけ）",
          (len(warn), 'if [ "${miss:-0}" -gt 0 ] || [ "${fail:-0}" -gt 0 ]; then' in step,
           "警告にしません" in step), (1, True, True))


def test_speed_records_of_clients_stay_private():
    print("\n■ 表示速度の記録: お客様の社の行・CrUX は非公開の置き場へ（2026-10-12 の週次が public に1行 push した）")
    import client_private as CP
    import cwv_check as CW
    import sites as S
    check("cwv.jsonl は分け書きの記録で、お客様の行は非公開のリポジトリに残す",
          ("data/cwv.jsonl" in CP.SPLIT_JSONL, "data/cwv.jsonl" in CP.REPO_BACKED), (True, True))
    with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as st:
        d = Path(d)
        for p in _fake_sites():
            st.enter_context(p)
        st.enter_context(mock.patch.object(CP, "is_private", lambda sid: sid == CL))
        st.enter_context(mock.patch.object(CP, "private_path", lambda sid, rel: d / "priv" / sid / rel))
        st.enter_context(mock.patch.object(CP, "site_file", lambda sid, rel: d / "priv" / sid / rel))
        st.enter_context(mock.patch.object(CW, "CRUX_DIR", d / "crux"))
        st.enter_context(mock.patch.object(CP, "_split_rel", lambda p: "data/cwv.jsonl"))
        log = d / "cwv.jsonl"
        CP.append_jsonl(log, {"site": CL, "url": "https://zz.example/"}, sid=CL)
        CP.append_jsonl(log, {"site": "ai-lab", "url": "https://ai.example/"}, sid="ai-lab")
        pub = log.read_text(encoding="utf-8")
        priv = (d / "priv" / CL / "data/cwv.jsonl").read_text(encoding="utf-8")
        crux = (CW.crux_path(CL), CW.crux_path("ai-lab"))
    check("お客様の行は置き場へ・自社の行は public へ・CrUX の置き場も同じ",
          ("zz.example" in pub, "ai.example" in pub, "zz.example" in priv, "priv" in str(crux[0]), "priv" in str(crux[1])),
          (False, True, True, True, False))
    src = (ROOT / "scripts" / "cwv_check.py").read_text(encoding="utf-8")
    check("cwv_check は行を client_private で書き、ログ・知らせる文にお客様の URL を出さない",
          ("CP.append_jsonl(LOG, r, sid=r[\"site\"])" in src, 'with LOG.open("a"' not in src,
           src.count("（お客様のページ）") >= 3), (True, True, True))
    rows = [json.loads(x) for x in (ROOT / "data" / "cwv.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    check("いまの public の data/cwv.jsonl にお客様の社の行が無い", [r.get("date") for r in rows if S.is_client(r.get("site", ""))], [])


def test_priority_boost_never_links_to_noindexed_articles():
    print("\n■ 主力の語の底上げ（priority_boost）: 検索から外した記事へリンクを送らない・送り元にもしない")
    import priority_boost as PB
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "articles").mkdir()
        (d / "articles" / "zz-live.md").write_text("---\ntitle: t\ncategory: hojokin\n---\n本文\n", encoding="utf-8")
        (d / "articles" / "zz-hidden.md").write_text(
            "---\ntitle: t\ncategory: hojokin\nnoindex: true\nnoindex_reason: 試験\n---\n本文\n", encoding="utf-8")
        with mock.patch.object(PB, "ROOT", d):
            got = sorted(PB.load_articles())
    check("検索から外した記事は送り先にも送り元にも入らない（2026-10-12 の週次が12本の原稿からリンクを足した）",
          got, ["zz-live"])


def test_season_peaks_of_clients_stay_private():
    print("\n■ 季節の山の記録: お客様の社の分は非公開の置き場へ（ファイル名に社の id が入る。2026-10-12 の週次が commit した）")
    import client_private as CP
    import season as SE
    with tempfile.TemporaryDirectory() as d, contextlib.ExitStack() as st:
        d = Path(d)
        for p in _fake_sites():
            st.enter_context(p)
        st.enter_context(mock.patch.object(CP, "site_file", lambda sid, rel: d / "priv" / sid / rel))
        st.enter_context(mock.patch.object(SE, "STORE", d / "season"))
        got = (SE.store_path(CL), SE.store_path("ai-lab"))
    check("お客様の社は置き場・自社は data/season のまま", ("priv" in str(got[0]), got[1] == d / "season" / "ai-lab.json"),
          (True, True))
    src = (ROOT / "scripts" / "season.py").read_text(encoding="utf-8")
    check("書く・読むの両方が store_path を通す", (src.count("store_path(site_id)") >= 2, 'STORE / f"{site_id}.json").write_text' not in src),
          (True, True))


def test_live_audit_flags_internal_links_to_redirects():
    print("\n■ 本番の巡回: 内部リンクの先が転送（統合・取り下げの 301）なら警告する（末尾のスラッシュの違いは数えない）")
    import seo_audit as SA
    page = ('<html><head><title>{t}</title></head><body><h1>{t}</h1>'
            '<a href="/blog/zz-old/">古い</a><a href="/blog/zz-live">生きている</a><a href="/tools/zz-tool">道具</a></body></html>')
    site = {
        "https://zz.example/sitemap.xml": (200, "<loc>https://zz.example/blog/zz-a/</loc><loc>https://zz.example/blog/zz-live/</loc>",
                                           "https://zz.example/sitemap.xml"),
        "https://zz.example/blog/zz-a/": (200, page.format(t="試験の記事A"), "https://zz.example/blog/zz-a/"),
        "https://zz.example/blog/zz-live/": (200, page.format(t="試験の記事B"), "https://zz.example/blog/zz-live/"),
        "https://zz.example/blog/zz-old/": (200, page.format(t="転送先"), "https://zz.example/blog/zz-new/"),
        "https://zz.example/tools/zz-tool/": (200, page.format(t="道具"), "https://zz.example/tools/zz-tool"),
    }
    with mock.patch.object(SA, "_get", lambda u, timeout=30: site.get(u, (404, "", u))):
        rows, _pages = SA.live("zz.example", 50)
    red = [(r[2], r[3]) for r in rows if r[1] == "転送されるURLへの内部リンク"]
    check("統合済みの記事へのリンクは警告・末尾のスラッシュだけ違う道具のページは警告しない",
          (len(red) > 0, all(d == "/blog/zz-old/" for _p, d in red)), (True, True))


def test_aggregate_pages_have_readable_titles_and_descriptions():
    print("\n■ まとめのページ: 題は主力のカテゴリ名で補い、説明文は記事の題で100〜160字にそろえる（ページに無いことは書かない）")
    import aggregate_pages as AP
    cfg = {"categories": {"zz-main": "試験の主力", "zz-sub": "試験の副"}, "main_category": "zz-main"}
    by = {f"zz-{i}": {"title": f"試験の記事その{i}の題です", "date": f"2026-10-0{i}"} for i in range(1, 9)}
    short = {"title": "用語集", "description": "用語をまとめました。", "members": ["zz-1", "zz-2", "zz-3"]}
    index = {"title": "比較表から探す", "description": "", "members": []}
    long_ = {"title": "試験の主力の比較表", "description": "あ" * 200, "members": []}
    for p in (short, index, long_):
        AP.fit_meta(p, cfg, by)
    check("題: 短い題は主力のカテゴリ名を添え、すでに入っている題は変えない",
          (short["title"], long_["title"]), ("用語集（試験の主力）", "試験の主力の比較表"))
    check("説明文: 短いものは記事の題で補い、長すぎるものは切る（どれも100〜160字）",
          [100 <= len(p["description"]) <= 160 for p in (short, index, long_)], [True, True, True])
    check("足すのは実在する記事の題だけ", ("試験の記事その1の題です" in short["description"],
                                       "試験の記事その8の題です" in index["description"]), (True, True))
