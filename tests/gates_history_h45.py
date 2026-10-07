# -*- coding: utf-8 -*-
"""Search Console「代替ページ（適切な canonical タグあり）」の新しい要因（2026-10 ai.7senses.co.jp）。

URL 検査 API で1本ずつ当てて分かった、意図しない URL の作り方を止める。
  - 業種の LP が無い調査ページが /lp// へリンクしていた（T['lp'] が空。/lp// は 200 で返り、/lp/ の代替になる）
  - チェックリストの無い業種で /download/?ind= （値が空）へリンクしていた（/download/ の代替になる）
  - 一次データ（/data/）を非公開にしたあと、コーポレートの8本が AI集客ラボの 404 へリンクしていた。
    publish.py の main() だけで外しており、描き直し（publish_rerender・republish_images）が素の原稿で書き戻した
ツールの初期値（/tools/kuchikomi-henshin/?ind=clinic）は意図どおりの代替なので止めない。
"""
import re
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_no_empty_query_or_double_slash_links():
    import industry_ai_sources as IAS
    check("代替ページ: チェックリストの無い調査は ?ind= を付けない",
          (IAS.checklist_url("ec"), IAS.checklist_url(""), IAS.checklist_url(None)),
          ("/download/", "/download/", "/download/"))
    check("代替ページ: チェックリストのある業種は ?ind=<業種>", IAS.checklist_url("dental"), "/download/?ind=dental")
    check("代替ページ: LP の無い業種は /lp/ （/lp// を作らない）", IAS._lpu({"lp": ""}), "/lp/")
    for name in ("industry_ai_sources.py", "industry_lp.py", "question_pages.py"):
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        check(f"代替ページ: {name} が空になりうる値で ?ind= を組まない",
              re.findall(r'/download/\?ind=\{[^}]*\.get\([^)]*""\)\}', src), [])
        check(f"代替ページ: {name} が空になりうる値で /lp/<業種>/ を組まない",
              re.findall(r"""/lp/\{T\[['"]lp['"]\]\}/(?!" if T\.get\()""", src), [])
    site = ROOT / "site"
    bad = []
    pat = re.compile(r'href="(?:https://ai\.7senses\.co\.jp)?(/[^"#]*?(?://|\?[a-z_]+=(?=["&#])))')
    for f in site.rglob("*.html"):
        rel = f.relative_to(site).as_posix()
        if rel.startswith(("images/", "wp/")):
            continue
        for m in pat.finditer(f.read_text(encoding="utf-8", errors="ignore")):
            bad.append(f"{rel}: {m.group(1)}")
    check("代替ページ: 生成したページに /x// や値の空のクエリへのリンクが無い", bad[:5], [])


def test_private_data_links_are_removed_on_every_delivery_path():
    import data_intake
    import publish
    import sites as S
    if data_intake.PUBLIC:
        return
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.md"
        p.write_text('---\nslug: x\n---\n根拠は<a href="https://ai.7senses.co.jp/data/a/" target="_blank">当社の集計</a>と'
                     "[実測](https://ai.7senses.co.jp/data/b/)、[推奨](/data/reco.json)。\n", encoding="utf-8")
        body = publish.parse_article(p)[1]
    check("非公開の /data/: 配信の入口（parse_article）でリンクを文字に戻す",
          ("ai.7senses.co.jp/data/" in body, "当社の集計" in body and "実測" in body), (False, True))
    for name in ("publish_rerender.py", "republish_images.py", "wp_bridge.py"):
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        check(f"非公開の /data/: {name} は publish.parse_article で本文を読む",
              "publish.parse_article(" in src and "split(\"---\"" not in src, True)
    left = []
    for a in sorted((ROOT / "articles").glob("*.md")):
        t = a.read_text(encoding="utf-8-sig")
        cat = (re.search(r"^category:\s*(\S+)", t, re.M) or [0, ""])[1]
        if S.find_category_owner(cat) not in (None, "ai-lab") and "ai.7senses.co.jp/data/" in t:
            left.append(a.stem)
    check("非公開の /data/: 他サイトの原稿に AI集客ラボの /data/ への URL が無い", left, [])
