# -*- coding: utf-8 -*-
"""語の計画: 運用者が「ほかのサイトと狙う語が重なってもよい」と決めた社（kw_overlap_ok）は、執筆済み・食い合いを
その社の記事とだけ照らす。連携・取り扱いをするサービス名（rival_ok）は他社名として落とさない（2026-11-16）。
新しく受けたお客様の社で、経理BPO・MEO対策・AIO対策などの買い手の語が当社のほかのサイトの記事を理由に「執筆済み」で落ち、
「マネーフォワード 連携」「freee 連携」が他社名で落ちた"""
from pathlib import Path

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent


def test_overlap_ok_checks_only_own_articles():
    import kw_plan as KP
    print("\n■ 語の計画: 重なってよい社は、自分の記事とだけ照らす")
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("kw_overlap_ok の社は own_corpus（その社の記事だけ）で照らす",
          ('if (S.get("cfg") or {}).get("kw_overlap_ok"):' in src, "corpus, arts = own_corpus(site_id)" in src), (True, True))
    corpus, arts = KP.own_corpus("site-that-owns-nothing")
    check("持ち主のいないサイトの記事は0本（ほかのサイトの記事を数えない）", (corpus, arts), ([], []))
    full = KP.written_corpus()
    check("良い例: 重なってよい印の無い社は、今までどおり当社の全記事と照らす（全記事が1本以上ある）", len(full) > 0, True)


def test_rival_ok_lets_integration_names_through():
    import kw_fit
    import kw_plan as KP
    print("\n■ 語の計画: 社が連携するサービス名（rival_ok）は他社名にしない")
    ok = {"cfg": {"rival_ok": ["マネーフォワード", "freee"]}}
    check("rival_ok の社: 「マネーフォワード 連携」「freee 導入 手順」は他社名にしない",
          (KP.rival_of("マネーフォワード 連携", ok), KP.rival_of("freee 導入 手順", ok)), (None, None))
    check("悪い例: rival_ok に無い名前は今までどおり他社名（kintone）",
          KP.rival_of("kintone 開発 費用", ok), "kintone")
    check("悪い例: rival_ok の無い社は今までどおり他社名", KP.rival_of("マネーフォワード 連携", {"cfg": {}}), "マネーフォワード")
    rules = {"rival_ok": {"マネーフォワード"}}
    check("kw_fit の判定材料に rival_ok がある（設定の無い社でも空の集合）", "rival_ok" in (kw_fit._rules("corporate") or rules), True)


def test_photo_shelf_can_be_turned_off():
    print("\n■ 配信: 「AIで作った人物は使わない」社は、写真の棚（生成の人物写真）を使わない")
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("external-html の写真選びは sites の photo_shelf: false で棚を飛ばし、配信先の在庫写真へ戻る",
          'if cfg.get("photo_shelf", True) else ("", "")' in src, True)
