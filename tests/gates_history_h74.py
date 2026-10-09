# -*- coding: utf-8 -*-
"""2026-10-09 CONFLUX の記事（saas-development-cost）が、お客様の使えない表現「必ず」で配信の門に止められ、
採点も承認も通ったのに未配信のまま残った。publish_gap は「×」とだけ出し、理由はどこにも出なかった。

1. 書く段の機械採点（score_check）で rules.ng_words を見て、採点の前に直させる
2. publish_gap が配信に失敗した理由を出し、配信の門で止まったものは要対応にする
"""
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_client_ng_words_are_caught_while_writing():
    import score_check as SC
    import sites
    cfg = {"x": {"id": "x", "domain": "x.example.jp", "categories": {"xcat": "x"},
                 "rules": {"ng_words": ["必ず", "No.1"]}}}
    text = "---\ntitle: 題\ndescription: 説明\ncategory: xcat\n---\n**冒頭**。売るための機能が必ず要ります。\n"
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "articles").mkdir()
        (Path(td) / "articles" / "zz.md").write_text(text, encoding="utf-8")
        with mock.patch.object(sites, "load_all", return_value=cfg), \
                mock.patch.object(sites, "find_category_owner", return_value="x"), \
                mock.patch.object(SC, "ROOT", Path(td)):
            got = {name: (ok, detail) for name, ok, detail, _ in SC.run("zz")}
    row = got.get("お客様の使えない表現（rules.ng_words）が無い")
    check("書く段の機械採点が、お客様の使えない表現を落とす（配信の門まで持ち越さない）", row, (False, "必ず"))


def test_publish_gap_shows_why_delivery_stopped():
    src = (ROOT / "scripts" / "publish_gap.py").read_text(encoding="utf-8")
    check("配信に失敗した記事の理由を出す・配信の門で止まったものは要対応にする",
          ("理由:" in src, "要対応:" in src and "配信の門で止まっています" in src), (True, True))
