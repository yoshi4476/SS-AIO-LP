# -*- coding: utf-8 -*-
"""Search Console に権限の無い社の記事を、食い合いの検査が「判定不能」で止め続けない（2026-11-17）。

新しく受けた社は、先方がサービスアカウントをオーナーに足すまで Search Console を読めない（403）。
kw_guard はそれを通信の失敗と同じ「判定不能（3）」にし、配信の門は 2 以上を止めるので「BLOCKED(食い合い)」で止め、
公開前の直しも3回とも「食い合いの検査が動きませんでした」で戻した。追加されるまで、その社の記事は1本も出なかった。
権限なしは待っても直らず、先方へのお願いは別の工程で知らせている。照合は記事と仕組みの外で書いたページで行う
"""
import sys
from unittest import mock

from test_gates import ROOT, check

sys.path.insert(0, str(ROOT / "scripts"))

CFG = {"id": "x", "domain": "example.jp", "client": True,
       "link_pages": [{"url": "/column/a/hand/", "title": "給与計算を外注する費用と相場", "category": "a"}]}
OTHER = {"id": "y", "domain": "example.com", "client": True}


class _Err(Exception):
    def __init__(self, status, body):
        super().__init__(body)
        self.resp = type("R", (), {"status": status})()
        self.content = body.encode()


DENIED = (403, '{"error": {"code": 403, "message": "User does not have sufficient permission for site"}}')
QUOTA = (429, '{"error": {"code": 429, "message": "Quota exceeded"}}')
SERVER = (500, '{"error": {"code": 500, "message": "Backend Error"}}')


def _judge(kw, errors, group=("x",)):
    """errors: {ドメイン: (status, body)}。そのドメインの GSC の照会だけ失敗させる"""
    import googleapiclient.discovery as GD
    import gcreds
    import kw_guard as KG
    import sites

    def query(siteUrl, body):
        dom = siteUrl.split("//")[1].rstrip("/")
        q = mock.Mock()
        if dom in errors:
            q.execute.side_effect = _Err(*errors[dom])
        else:
            q.execute.return_value = {"rows": []}
        return q

    sc = mock.Mock()
    sc.searchanalytics.return_value.query.side_effect = query
    confs = {"x": CFG, "y": OTHER}
    with mock.patch.object(KG, "CRED", ROOT / "tests" / "test_gates.py"), \
            mock.patch.object(KG, "load_articles", return_value=[]), \
            mock.patch.object(gcreds, "load", return_value=None), \
            mock.patch.object(GD, "build", return_value=sc), \
            mock.patch.object(sites, "load_all", return_value={k: confs[k] for k in group}), \
            mock.patch.object(sites, "group_of", return_value=list(group)), \
            mock.patch.object(sites, "find_category_owner", return_value="x"):
        lv, reasons = KG.judge(kw, "x", exclude_slug="self")
        return lv, reasons, KG.gsc_rows.failed, KG.gsc_rows.denied


def test_own_site_without_permission_is_not_unknown():
    print("\n■ kw_guard: 自分のサイトの Search Console に権限が無い（403）ときは判定不能にせず、記事と手書きのページで照合する")
    import kw_guard as KG
    lv, reasons, failed, denied = _judge("経理 代行 料金表", {"example.jp": DENIED})
    check("権限なし: 判定不能（3）にしない", lv, 0)
    check("権限なし: 失敗ではなく権限なしとして残す", (failed, denied), ("", "example.jp"))
    check("権限なし: 照合していないことを理由に出す",
          any(k == "要確認" and "権限がありません" in w for k, w, _ in reasons), True)

    lv, reasons, _f, _d = _judge("給与計算 外注 費用", {"example.jp": DENIED})
    check("権限なし: 手書きのページが同じ語を題にしていれば要差別化（1）", lv, 1)
    check("権限なし: そのページを名指しする", any("/column/a/hand/" in w for _k, w, _ in reasons), True)

    print("\n■ kw_guard: 待てば直る失敗（回数の上限・相手の不具合）と、同じ組のほかのサイトの権限なしは、今までどおり判定不能")
    for name, err in (("回数の上限（429）", QUOTA), ("相手の不具合（500）", SERVER)):
        lv, _r, failed, denied = _judge("経理 代行 料金表", {"example.jp": err})
        check(f"{name}: 判定不能（3）", (lv, bool(failed), denied), (KG.UNKNOWN, True, ""))
    lv, _r, failed, denied = _judge("経理 代行 料金表", {"example.com": DENIED}, group=("x", "y"))
    check("同じ組のほかのサイトの権限なし: 判定不能（3）", (lv, bool(failed), denied), (KG.UNKNOWN, True, ""))
    lv, _r, failed, denied = _judge("経理 代行 料金表", {})
    check("読めたとき: 0・失敗も権限なしも無し", (lv, failed, denied), (0, "", ""))


def test_publish_gate_does_not_call_unknown_a_conflict():
    print("\n■ 配信の門: 判定不能（3）を「BLOCKED(食い合い)」と書かない（記事の中身を疑って直しに行く）")
    src = (ROOT / "scripts" / "publish_flow.py").read_text(encoding="utf-8")
    i3 = src.find("if level == 3:")
    i2 = src.find("if level >= 2:", max(i3, 0))
    check("判定不能を食い合いより先に分ける", 0 <= i3 < i2, True)
    check("判定不能の印", "BLOCKED(食い合いの検査が動かず)" in src[i3:i2], True)
