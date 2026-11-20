# -*- coding: utf-8 -*-
"""2026-11-20 品質の直しの後の採点し直しができなかったとき、採点していない直しが記事に残っていた。

お客様の記事で、直し2回目の後の採点が「抽出性の引用が本文にありません（言い換え・作った引用は無効）」で無効になり、
ループを抜けるだけで最後に採点した版へ戻していなかった。85点以上の版から90点を目指して直している途中なら、
採点していない版のまま合格として公開される作りだった。採点できなかった直しは戻す。
本物の claude は呼ばない。一時フォルダの記事と台帳だけで試す。
"""
import contextlib
import io
import json
import sys
import tempfile

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

MARK = "採点していない直しの文。"


def _run(first):
    """1回目の採点は first、直しの後の採点は失敗。直しは記事の末尾に MARK を足す"""
    import gates_history_h128_quality_loop as H
    import gates_history_h196_quality_reach as H196
    import quality_loop as QL
    calls = {"score": 0}

    def score(slug, ask=None):
        calls["score"] += 1
        return (first, "") if calls["score"] == 1 else (None, "抽出性の引用が本文にありません（言い換え・作った引用は無効）")

    def imp(slug, sc):
        QL.write(slug, QL.read(slug) + "\n" + MARK + "\n")
        return True, "直しました（テスト）"
    with tempfile.TemporaryDirectory() as d:
        e = H.Env(d)
        e.put("zz-aio", H._art("score: 92\n"))
        with H196.patched(*e.patches(QL, ["{}"], improve=imp), (QL, "score", score)):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                res = QL.run(["zz-aio"], "rescore", QL.Budget(None))
        text = e.get("zz-aio")
        rows = [json.loads(x) for x in e.log.read_text(encoding="utf-8").splitlines()] if e.log.exists() else []
    return res, buf.getvalue(), text, rows


def test_unscored_fix_is_reverted():
    import gates_history_h196_quality_reach as H196
    print("\n■ 品質の直し: 採点し直しができなかった直しは戻し、最後に採点した版を残す")
    res, out, text, rows = _run(H196._sc(88, 88, 88))
    check("合格点（88）から直して採点できなかった → 採点した版で合格・直しは残さない",
          (res, MARK in text, "要対応" in out), ({"passed": 1}, False, True))
    res, out, text, rows = _run(H196._sc(80, 75, 70))
    check("合格前（75）から直して採点できなかった → 保留・直しは残さない",
          (res, MARK in text), ({"improving": 1}, False))
    check("台帳に採点の失敗と戻しを残す", [r["action"] for r in rows if r.get("action") in ("score", "revert")][-2:],
          ["score", "revert"])
