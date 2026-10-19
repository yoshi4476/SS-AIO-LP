# -*- coding: utf-8 -*-
"""2026-10-20 補助金サイトの古い9本を取り下げたとき、配信先は直ったが、管制塔に残った参照
（AI集客ラボの site/_redirects の転送先と、補助金の記事1本の絶対URLのリンク）が取り下げたページを指したまま残り、
2段の転送になっていた。retract.repoint_refs が取り下げのたびに最終の記事へ付け替える。
"""
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_retract_repoints_control_tower_refs():
    import retract as R
    import sites as S
    print("\n■ 取り下げたページへ向いた管制塔の原稿のリンク・転送を、最終の記事へ付け替える")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "articles").mkdir()
        (root / "site").mkdir()
        (root / "articles" / "zz-a.md").write_text(
            "---\ncategory: zzcat\n---\n[GビズID](https://zz.example/blog/old/)と[同じサイト](/blog/old/)と[別の記事](/blog/older/)\n",
            encoding="utf-8")
        (root / "articles" / "yy-b.md").write_text(
            "---\ncategory: yycat\n---\n[別サイトの同じパス](/blog/old/)と[外から](https://zz.example/blog/old/#a)\n",
            encoding="utf-8")
        (root / "site" / "_redirects").write_text(
            "/x/  https://zz.example/blog/old/   301\n/y/  https://zz.example/blog/older/   301\n", encoding="utf-8")
        orig = S.find_category_owner
        S.find_category_owner = lambda c: {"zzcat": "zz", "yycat": "yy"}[c]
        try:
            touched = R.repoint_refs({"domain": "zz.example"}, "zz",
                                     {"from": "/blog/old/", "to": "/blog/new/"}, root=root)
        finally:
            S.find_category_owner = orig
        a = (root / "articles" / "zz-a.md").read_text(encoding="utf-8")
        b = (root / "articles" / "yy-b.md").read_text(encoding="utf-8")
        red = (root / "site" / "_redirects").read_text(encoding="utf-8")
        check("同じサイトの記事: 絶対URLと相対リンクを付け替え、似た別のパスは触らない",
              ("https://zz.example/blog/new/)" in a, "](/blog/new/)" in a, "](/blog/older/)" in a), (True, True, True))
        check("別のサイトの記事: 絶対URLだけ付け替え、自分のサイトの同じパスは触らない",
              ("](/blog/old/)" in b, "https://zz.example/blog/new/#a" in b), (True, True))
        check("site/_redirects の転送先も付け替え、似た別のパスは触らない",
              ("https://zz.example/blog/new/ " in red, "https://zz.example/blog/older/ " in red), (True, True))
        check("付け替えた場所を返す", sorted(touched), ["site/_redirects", "yy-b.md", "zz-a.md"])
    src = (ROOT / "scripts" / "retract.py").read_text(encoding="utf-8")
    check("取り下げを終えた記事（--push）で呼ぶ", 'if r.get("done_at") and a.push:' in src and "repoint_refs(S.load(sid), sid, r)" in src, True)


def test_quality_loop_records_weak_points():
    print("\n■ 公開前の採点の弱い点を台帳に残す（80点で止まる原因を後から調べられるように。2026-10-20）")
    src = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("採点の記録2か所に weak を残す", src.count('"weak": sc.get("weak", {})'), 2)
