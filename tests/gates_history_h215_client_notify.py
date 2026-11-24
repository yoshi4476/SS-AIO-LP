# -*- coding: utf-8 -*-
"""2026-11-24 運用者「お客様の社のサイトが出ていない気がする」。お客様の社の新しい記事が Google に未登録（URL is unknown）だった。
公開直後の通知（notify_indexing・notify_indexnow --site）が、本日の記事を公開側の articles/ だけから探しており、
非公開の置き場にあるお客様の原稿を一度も拾っていなかった。非公開の置き場の原稿も本日の記事として拾うこと。"""
import sys
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _md(slug, cat, d):
    return f"---\nslug: {slug}\ncategory: {cat}\ndate: {d}\n---\n本文\n"


def test_client_articles_are_notified():
    import notify_indexing as N
    import private_store as P
    import sites as S
    print("\n■ 公開直後の通知: お客様の社の本日の記事（非公開の置き場の原稿）も Google・IndexNow へ知らせる")
    today = date.today().isoformat()
    with tempfile.TemporaryDirectory() as pub, tempfile.TemporaryDirectory() as priv:
        (Path(pub) / "articles").mkdir()
        (Path(priv) / "articles" / "_held").mkdir(parents=True)
        (Path(priv) / "articles" / "new-cost.md").write_text(_md("new-cost", "xcat", today), encoding="utf-8")
        (Path(priv) / "articles" / "old-cost.md").write_text(_md("old-cost", "xcat", "2020-01-01"), encoding="utf-8")
        (Path(priv) / "articles" / "_held" / "held.md").write_text(_md("held", "xcat", today), encoding="utf-8")
        (Path(pub) / "articles" / "own.md").write_text(_md("own", "owncat", today), encoding="utf-8")
        owner = {"xcat": "xco", "owncat": "ai-lab"}
        with mock.patch.object(N, "ROOT", Path(pub)), mock.patch.object(P, "base", lambda: Path(priv)), \
                mock.patch.object(S, "find_category_owner", lambda c: owner.get(c)), \
                mock.patch.object(S, "article_url", lambda cfg, a: f"https://{cfg['domain']}/column/{a['slug']}/"):
            got = N.todays_urls({"id": "xco", "domain": "x.example"})
            check("お客様の社の本日の記事を拾う（保留の原稿・古い記事は拾わない）", got, ["https://x.example/column/new-cost/"])
            check("自社の記事は今までどおり拾う", N.todays_urls({"id": "ai-lab", "domain": "a.example"}),
                  ["https://a.example/column/own/"])
