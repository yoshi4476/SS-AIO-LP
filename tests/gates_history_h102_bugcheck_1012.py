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
        st.enter_context(mock.patch.object(wp_bridge, "add_redirects", lambda c, pairs: (1, [])))
        st.enter_context(mock.patch.object(wp_bridge, "push_settings", lambda c: None))
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
