# -*- coding: utf-8 -*-
"""2026-11-01: コーポレート（Next.js の別リポジトリ）にも区画の印（data-area）を置き、記事にも見出しごとの区画を置いた。
月次のヒートマップは AI集客ラボの site/ の HTML だけを前提にしていたため、そのままでは
1. コーポレートの「/」に AI集客ラボの「/」の並びが当たり、全区画に「現在このページに無い区画」と付く
2. 記事170本超がそれぞれ1ページとして並び、紙と「CTAが下すぎる」の指摘が記事の数だけ増える
3. 出来事×ページの全部を400行で取っていたので、page_view などの行に押されて区画の行が欠ける
GA4 は呼ばない。ページと件数は架空。
"""
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_articles_merge_into_one_page():
    import report_heat as RH
    print("\n■ 1. 記事の区画は「記事（全記事の合計）」にまとめ、固定ページはページのまま数える")
    rows = [("section_view_hero", "/blog/zz-a", 40), ("section_view_hero", "/blog/zz-b", 20),
            ("section_view_h2_1", "/blog/zz-a", 30), ("section_view_h2_1", "/blog/zz-b", 10),
            ("section_view_hero", "/blog", 9), ("section_view_hero", "/", 50), ("section_view_cases", "/", 10),
            ("page_view", "/blog/zz-a", 99), ("scroll_depth_90", "/blog/zz-a", 5)]
    secs = RH.sections_from_rows(rows, "/blog")
    got = {(s["page"], s["name"]): (s["n"], s["pct"]) for s in secs}
    check("良い例: 2本の記事の hero 40+20・h2_1 30+10 を合計し、割合は合計の hero を分母にする",
          (got.get((RH.ARTICLES, "hero")), got.get((RH.ARTICLES, "h2_1"))), ((60, 100), (40, 67)))
    check("良い例: 記事の一覧（/blog）とトップは記事にまとめない",
          (got.get(("/blog", "hero")), got.get(("/", "cases"))), ((9, 100), (10, 20)))
    check("悪い例: page_view・scroll_depth は区画に入れない", any(s["name"].startswith(("page", "scroll")) for s in secs), False)
    secs = RH.sections_from_rows(rows, None)
    check("悪い例: 記事の頭が無いサイト（AI集客ラボ）は記事をまとめない（前と同じ）",
          {s["page"] for s in secs} >= {"/blog/zz-a", "/blog/zz-b"}, True)


def test_heat_without_site_html():
    import report_heat as RH
    print("\n■ 2. HTML が管制塔に無いサイトは、AI集客ラボの並びを当てず、到達の多い順に並べ、ページは6件まで")
    secs = [{"name": "hero", "page": "/", "n": 50, "pct": 100}, {"name": "cases", "page": "/", "n": 10, "pct": 20}]
    secs += [{"name": "hero", "page": f"/zz-{i}", "n": 9 - i, "pct": 100} for i in range(7)]
    html = RH.heat_html(secs, own_html=False)
    check("良い例: 「現在このページに無い区画」と付けない", "現在このページに無い区画" in html, False)
    check("良い例: 並びは到達の多い順と書き、最も落ちる区画を名指しする",
          ("到達の多い順" in html, "「cases」の手前で −80pt" in html), (True, True))
    check("良い例: 載せるのは6ページまでで、残りの件数を書く",
          (len(re.findall(r"<b>ページ:", html)), "ほかに区画を計測しているページが2件" in html), (6, True))
    own = RH.heat_html(secs, own_html=True)
    check("悪い例: 自前の HTML があるサイト（AI集客ラボ）はページの数を絞らない（前と同じ）",
          len(re.findall(r"<b>ページ:", own)), 8)


def test_monthly_fetches_only_area_events():
    print("\n■ 3. 月次は区画とスクロールの出来事だけを取り、記事をまとめ、HTML の有無を渡す")
    src = (ROOT / "scripts" / "monthly_report.py").read_text(encoding="utf-8")
    check("良い例: section_view_ と scroll_depth で絞って取る（400行で全部の出来事を取らない）",
          ('for p in ("section_view_", "scroll_depth")' in src, "limit=400))" in src), (True, False))
    check("良い例: 区画は sections_from_rows で url_prefix ごとにまとめる",
          'RH.sections_from_rows(' in src and 'site_cfg().get("url_prefix")' in src, True)
    check("良い例: heat_html に own_html（自前でビルドするサイトか）を渡す",
          "own_html=SITE_ID == _sites_mod.primary()" in src, True)
