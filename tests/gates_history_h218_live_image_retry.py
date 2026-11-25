# -*- coding: utf-8 -*-
"""2026-11-25 公開後の本番巡回（live_check）が、本番で200を返す画像を「画像が表示できない（HTTP 0）」と知らせた。
HTTP 0 は画像が無いのではなく、取りに行く通信が一瞬失敗したときの値。1回だけ取り直し、それでも取れなければ知らせる。
404 などの本当の参照切れは取り直さずに知らせる。"""
import sys
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _run(LC, answers):
    seq = list(answers)
    calls = []

    def fake(u):
        calls.append(u)
        return seq.pop(0) if seq else (200, "", u)
    with mock.patch.object(LC, "fetch", fake):
        probs = LC.check_page("https://x.example/seo/", '<img src="/images/a.webp">', 200,
                              "https://x.example/seo/", {"https://x.example/seo"})
    return any("画像が表示できない" in p for p in probs), len(calls)


def test_live_check_retries_image_once_on_network_error():
    import live_check as LC
    print("\n■ 本番巡回: 画像の通信の一瞬の失敗（HTTP 0）を参照切れと知らせない")
    check("1回目が通信の失敗・2回目が200なら知らせない（取り直しは1回）",
          _run(LC, [(0, "__ERR__TimeoutError", ""), (200, "", "")]), (False, 2))
    check("2回とも通信の失敗なら知らせる", _run(LC, [(0, "", ""), (0, "", "")])[0], True)
    check("404 は取り直さずに知らせる", _run(LC, [(404, "", "")]), (True, 1))
