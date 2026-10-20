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


def test_quality_fix_allows_fact_dates():
    sys.path.insert(0, str(ROOT / "scripts"))
    import auto_rewrite as A
    import quality_loop as Q
    print("\n■ 公開前の直しは、一次情報の時点（2026-07 → 2026年7月）を書いてよい（「7月」で2回とも差し戻された。2026-10-20）")
    check("時点の書き換え", (Q.as_of_text("2026-07"), Q.as_of_text("時期未確認"), Q.as_of_text("")), ("2026年7月", "", ""))
    after = "本文。2026年7月時点の当社の数字です。"
    check("許した時点は通り、許していない時点は止まる",
          (A.new_fact_numbers("本文。", after, Q.as_of_text("2026-07")) == {},
           bool(A.new_fact_numbers("本文。", after, Q.as_of_text("2026-08")))), (True, True))


def test_material_first_and_wait_for_materials():
    import json
    sys.path.insert(0, str(ROOT / "scripts"))
    import hub_client as H
    import material as M
    import private_store as P
    import quality_loop as Q
    print("\n■ 材料の無い題で一次性が届かない記事は、材料の依頼を残して材料が増えるまで直さない。お客様の社は材料のある題を先に書く（2026-10-20）")
    pool = ["庭木 剪定 失敗", "庭木 剪定 時期", "庭木 剪定 料金",
            "芝生 張替え 料金", "生垣 剪定 料金", "zz 剪定"]
    mats = ["2020年から植木の手入れを請け負っています", "芝生の張替えを30件請け負いました"]
    check("題を分ける語（多くの題に出るサービス名では数えない）",
          (M.subject("庭木 剪定 失敗", pool), M.hits("庭木 剪定 失敗", mats, pool),
           M.hits("芝生 張替え 料金", mats, pool)), (["失敗"], 0, 1))
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "q.jsonl"
        fp = M.fingerprint
        M.fingerprint = lambda site: "aaa"
        try:
            log.write_text(json.dumps({"slug": "zz-a", "action": "hold", "need": "materials", "materials": "aaa"}) + "\n"
                           + json.dumps({"slug": "zz-b", "action": "hold", "need": "", "materials": ""}) + "\n",
                           encoding="utf-8")
            same = Q.waiting_materials("zz-a", "client-zz", path=log)
            other = Q.waiting_materials("zz-b", "client-zz", path=log)
            M.fingerprint = lambda site: "bbb"
            grown = Q.waiting_materials("zz-a", "client-zz", path=log)
        finally:
            M.fingerprint = fp
    check("材料が同じなら待ち・材料が増えたら直す・材料の理由でない記事は待たない", (same, grown, other), (True, False, False))
    lines, is_client = M.lines, P.is_client
    M.lines, P.is_client = (lambda site: mats), (lambda sid: sid == "client-zz")
    try:
        todo = [{"keyword": k} for k in pool]
        got = {"keyword": "庭木 剪定 失敗"}
        hit = H._with_material("client-zz", got, got["keyword"], todo)
        own = H._with_material("ai-lab", got, got["keyword"], todo)
    finally:
        M.lines, P.is_client = lines, is_client
    check("お客様の社は材料のある題を先に・自社は変えない",
          ((hit or {}).get("keyword"), (hit or {}).get("picked_by"), own), ("芝生 張替え 料金", "材料のある題", None))
    src = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("止めるときに依頼を残し、通ったら消す", ("material.ask(" in src, "material.resolve(site, slug" in src), (True, True))
    check("依頼は台帳と同じフォルダに書く（門の一時フォルダの架空の記事を本物の依頼に書かない。2026-10-20 zz-pub が混ざった）",
          src.count("path=LOG.parent / material.REQUESTS"), 2)


def test_redeliver_only_changed_articles():
    import subprocess
    print("\n■ 記事の枠の配り直しは、この回に中身の変わった記事だけを送る（全記事に当てるとコーポレートは毎回約20分。2026-10-20）")
    g = (ROOT / "scripts" / "agent_guard.py").read_text(encoding="utf-8")
    check("agent_guard は変わった記事を --slugs で渡し、無い社は呼ばない",
          ('"--slugs", ",".join(mine)' in g, "if not mine:" in g), (True, True))
    src = (ROOT / "scripts" / "publish_changed.py").read_text(encoding="utf-8")
    check("publish_changed に --slugs", 'ap.add_argument("--slugs"' in src and "targets = [x for x in targets if x in want]" in src, True)
