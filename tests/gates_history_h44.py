# -*- coding: utf-8 -*-
"""記事動画（通常・ショート）は、自社は AIO の記事だけで作る（2026-10-07 運用者の決定）。

sites/<id>.json の video_categories で絞る。キーの無い社（お客様）は今までどおり絞らない。
調査ページの動画は続ける（article_videos の research の枠は focus を通らない）。
"""
import json
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_videos_only_for_aio_on_own_sites():
    import article_videos as AV
    AV._CFG.clear()
    cfg = {k: json.loads((ROOT / "sites" / f"{k}.json").read_text(encoding="utf-8"))
           for k in ("ai-lab", "corporate", "subsidy")}
    check("動画の範囲: AI集客ラボは AIO だけ", cfg["ai-lab"].get("video_categories"), ["aio"])
    check("動画の範囲: コーポレート・補助金は作らない",
          (cfg["corporate"].get("video_categories"), cfg["subsidy"].get("video_categories")), ([], []))
    row = lambda site, cat: {"site": site, "category": cat, "title": "テスト"}
    check("動画の範囲: AIO の記事は作る", AV.focus(row("ai-lab", "aio")) is not None, True)
    check("動画の範囲: SEO・AI集客全般の記事は作らない",
          (AV.focus(row("ai-lab", "seo")), AV.focus(row("ai-lab", "ai-marketing"))), (None, None))
    check("動画の範囲: コーポレート・補助金の記事は作らない",
          (AV.focus(row("corporate", "keiri-bpo")), AV.focus(row("subsidy", "hojokin"))), (None, None))
    AV._CFG["client-x"] = {"main_category": "food"}
    check("動画の範囲: video_categories の無い社（お客様）は絞らない", AV.focus(row("client-x", "food")) is not None, True)
    AV._CFG.clear()
    src = (ROOT / "scripts" / "article_videos.py").read_text(encoding="utf-8")
    check("動画の範囲: 古い形式の作り直しも範囲外の記事は作らない",
          'v.get("format") != "duo"' in src and "focus(meta(k)) is not None" in src, True)
