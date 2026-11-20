# -*- coding: utf-8 -*-
"""2026-11-20 お客様の社の正しいカテゴリの記事が、配信も拾い直しも「理由が出力にありません」で止まり続けた。

check_contract は、配信先で2本以上使われている表示名だけを認める。送った記事が4本の社では、
2本目に届かないカテゴリが全部止まった（その社の一覧のページにはそのカテゴリがあり、組み立ても落ちない）。
止めた文も、お客様の社のログに出す決まった語の一覧（publish_flow._KINDS）に無かった。
架空の配信先（一時フォルダ）だけで試す。
"""
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _stopped(publish, cfg, dest, cat):
    try:
        publish.check_contract(cfg, dest, {"category": cat, "slug": "new"})
        return ""
    except SystemExit as e:
        return str(e)


def test_category_on_destination_list_is_allowed():
    import publish
    import publish_flow
    print("\n■ 配信先の一覧のページにあるカテゴリは、送った記事が少なくても通す（1文字違いは今まで通り止める）")
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d)
        blog = dest / "column"
        for i, label in enumerate(["Web集客", "Web集客", "経理BPO", "システム開発"]):
            (blog / f"a{i}").mkdir(parents=True)
            (blog / f"a{i}" / "index.html").write_text(f'<span class="cat">{label}</span>', encoding="utf-8")
        cfg = {"id": "t", "type": "external-html", "page_dir": "column",
               "categories": {"design": "経営と設計（代表コラム）", "typo": "経営と設計", "bpo": "経理BPO"}}
        old = publish.page_dir
        publish.page_dir = lambda c: "column"
        try:
            check("一覧のページが無ければ、2本に届かないカテゴリは止める（今まで通り）", bool(_stopped(publish, cfg, dest, "design")), True)
            (blog / "index.html").write_text('<div><h3>経営と設計（代表コラム）</h3><p>代表のコラム</p></div>'
                                             '<span class="note">2026/11/16・経理BPO</span>', encoding="utf-8")
            check("一覧のページの見出しにある表示名は通す", _stopped(publish, cfg, dest, "design"), "")
            check("1文字違う表示名（一覧の文字の一部だけ一致）は止める", bool(_stopped(publish, cfg, dest, "typo")), True)
            check("文の途中に出るだけの表示名（「・経理BPO」）は一覧のカテゴリと認めない", bool(_stopped(publish, cfg, dest, "bpo")), True)
            msg = _stopped(publish, cfg, dest, "typo")
        finally:
            publish.page_dir = old
    kind, why = publish_flow.fail_reason(msg)
    check("止めた理由を、お客様の社のログに出せる決まった語で出す", why, "段: 配信の前の門 / カテゴリの表示名が配信先に無い")
    check("決まった語に表示名そのもの（社のカテゴリ）を入れない", "経営と設計" in why, False)
