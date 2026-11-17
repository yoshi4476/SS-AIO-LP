# -*- coding: utf-8 -*-
"""Instagram の ID が未登録でも、Facebook ページにつながった Instagram へ投稿する（2026-11-18）。

自社の Facebook ページは自動投稿が動いていたが、Instagram の ID（IG_USER_ID）が無く、Instagram は毎回スキップしていた。
ページの鍵には Instagram の投稿の権限が入っている。ページに Instagram をつないだ後も、つなぎ直しの作業を
しなければ ID が入らないままだった。投稿のたびにページから引けば、つないだ次の投稿から出る
"""
import inspect
import io
import json
from unittest import mock

from test_gates import check


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_instagram_id_is_read_from_the_facebook_page():
    print("\n■ Instagram: ID が未登録なら、Facebook ページにつながった Instagram を引いて投稿する")
    import post_social as PS
    seen = []

    def opener(body):
        def urlopen(url, timeout=0):
            seen.append(url.split("?")[0])
            return _Resp(json.dumps(body).encode())
        return urlopen

    with mock.patch.object(PS.urllib.request, "urlopen", opener({"instagram_business_account": {"id": "1784"}, "id": "p"})):
        check("つながっている: Instagram の ID を返す", PS.ig_from_page("p", "t"), "1784")
    check("ページの項目を読みに行く（投稿はしない）", seen, [f"{PS.GRAPH}/p"])
    with mock.patch.object(PS.urllib.request, "urlopen", opener({"id": "p"})):
        check("つながっていない: 空", PS.ig_from_page("p", "t"), "")
    with mock.patch.object(PS.urllib.request, "urlopen", side_effect=OSError("x")):
        check("読めない: 空（Facebook の投稿は止めない）", PS.ig_from_page("p", "t"), "")

    src = inspect.getsource(PS.deliver)
    i = src.find('pick(e, "IG_USER_ID", site_id)')
    check("投稿の前に、未登録ならページから引く",
          0 <= i < src.find("ig_from_page(fbp, fbt)") < src.find("ig_post("), True)
    check("つながっていないときは理由を出す", "Instagram のプロアカウントがつながっていません" in src, True)
