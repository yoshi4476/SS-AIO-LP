# -*- coding: utf-8 -*-
"""内部リンクの送り先を書く AI・直す AI に渡し、直している途中の記事を隔離しない（2026-11-17）。

新しく受けた社の1本目が、内部リンク0本で配信の前の機械採点に落ち、articles/_conflicted/ へ隔離された。
その社には仕組みの外で書いた公開済みのコラムが12本あったのに、送り先として渡っておらず、記事は会社のページ
（サービス・事例）にしかリンクしていなかった。隔離された記事は、公開前の直し（quality_loop）が翌日に直すはずの記事だった
"""
import contextlib
import hashlib
import io
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import ROOT, check

sys.path.insert(0, str(ROOT / "scripts"))

CFG = {"id": "x", "domain": "example.jp", "url_prefix": "/column", "categories": {"a": "A", "b": "B"},
       "link_pages": [{"url": "/column/b/hand-b/", "title": "手書きB", "category": "b"},
                      {"url": "/column/a/hand-a/", "title": "手書きA", "category": "a"},
                      {"url": "/service/", "title": "会社のページ", "category": "a"},
                      {"url": "/column/a/no-title/", "title": "", "category": "a"}]}
ARTS = {"x": [{"slug": "pub", "title": "公開済み", "category": "a", "date": "2026-11-01", "score": "90"},
              {"slug": "self", "title": "この記事", "category": "a", "date": "2026-11-17", "score": "90"}]}


def _targets(**k):
    import daily_audit as D
    import score_check as SC
    import sites
    with mock.patch.object(sites, "load_all", return_value={"x": CFG}), \
            mock.patch.object(D, "articles_by_site", return_value=ARTS), \
            mock.patch.object(D, "_is_published", return_value=True):
        return SC.link_targets("x", **k)


def test_link_targets_include_hand_written_pages():
    print("\n■ 内部リンクの送り先: 仕組みの記事と、仕組みの外で書いた公開済みのページ（link_pages）を、同じ分野を先に渡す")
    got = _targets(category="a", skip="self")
    check("同じ分野（a）が先・自分自身と会社のページと題の無いページは入れない",
          [t for t, _ in got], ["公開済み", "手書きA", "手書きB"])
    import score_check as SC
    with mock.patch.object(SC.sites_mod, "load_all", return_value={"x": CFG}):
        check("渡す URL はどれも機械採点が内部リンクに数える形",
              all(SC.internal_links(f"[t]({u})") for _, u in got), True)
        check("悪い例: 会社のページ（/service/）は内部リンクに数えない", bool(SC.internal_links("[t](/service/)")), False)


def test_machine_note_names_link_targets():
    import quality_loop as QL
    import score_check as SC
    print("\n■ 直す AI への指示: 内部リンクが3本に満たない記事には、送り先を名指しする")
    body = "---\ntitle: t\ncategory: a\n---\n本文です。[会社](/service/)\n"
    with mock.patch.object(QL, "read", return_value=body), mock.patch.object(QL, "site_of", return_value="x"), \
            mock.patch.object(SC, "link_targets", return_value=[("手書きA", "/column/a/hand-a/")]), \
            mock.patch.object(SC, "internal_links", return_value=set()):
        note = QL.machine_note("s")
    check("内部リンクの行に送り先の Markdown のリンクが入る", "[手書きA](/column/a/hand-a/)" in note, True)
    with mock.patch.object(QL, "read", return_value=body), mock.patch.object(QL, "site_of", return_value="x"), \
            mock.patch.object(SC, "internal_links", return_value={"/a", "/b", "/c"}):
        check("良い例: 3本あれば内部リンクの行は出さない", "内部リンク" in QL.machine_note("s"), False)


def test_brief_warns_when_targets_are_short():
    import score_check as SC
    import site_brief as B
    print("\n■ 指示書: 送り先を出し、3本に満たない社は要対応にする")
    for got, want in (([("A", "/column/a/1/"), ("B", "/column/a/2/"), ("C", "/column/a/3/")], False), ([("A", "/column/a/1/")], True)):
        buf = io.StringIO()
        with mock.patch.object(SC, "link_targets", return_value=got), mock.patch.object(B.sites_mod, "is_client", return_value=False), \
                contextlib.redirect_stdout(buf):
            B.link_brief({"id": "x", "name": "x"}, "a")
        check(f"送り先 {len(got)}本 → 要対応 {want}", ("要対応:" in buf.getvalue(), "/column/a/1/" in buf.getvalue()), (want, True))


def test_improving_article_is_not_quarantined():
    import agent_guard as G
    import quality_loop as QL
    import score_check as SC
    import yaml
    print("\n■ 配信: 公開前の直しが引き受けた記事（improving）は、機械採点に落ちても隔離せず改善中に残す")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "articles").mkdir()
        for s, st in (("new-imp", "improving"), ("new-bad", None)):
            fm = {"title": "題", "slug": s, "date": "2026-11-17", "category": "aio", "score": 83}
            if st:
                fm["quality_state"] = st
            (root / "articles" / f"{s}.md").write_text("---\n" + yaml.safe_dump(fm, allow_unicode=True) + "---\n本文\n",
                                                       encoding="utf-8")
        fail = lambda slug, path=None: [("内部リンク3本以上", False, "0本", False)]
        with mock.patch.object(G, "_load_state", return_value={"articles": {}}), \
                mock.patch.object(G.subprocess, "run", side_effect=AssertionError("配信した")), \
                mock.patch.object(SC, "run", side_effect=fail), \
                mock.patch.object(QL, "released", return_value=[]), \
                contextlib.redirect_stdout(io.StringIO()):
            res = G.publish(root, None)
        q = sorted(p.stem for p in (root / "articles" / "_conflicted").glob("*.md"))
        check("直している途中の記事は articles/ に残り、改善中に数える", ((root / "articles" / "new-imp.md").is_file(), res["improving"]),
              (True, 1))
        check("悪い例: 直しが引き受けていない記事は今までどおり隔離する", q, ["new-bad"])
