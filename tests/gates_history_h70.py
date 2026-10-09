# -*- coding: utf-8 -*-
"""2026-10-09 運用者の決定「在庫が1か月分を切った社だけ、月1回ラッコで調べる」から。

それまでの基準は「未着手40本未満」（1日2本で20日分）で、1か月分を切っても組み直さない社があった。
1か月分＝1日の本数×30（月の上限60まで）。量産の兆候で本数を絞った社は絞った本数で数え、1日0本の社は組み直さない。
"""
import sys
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_monthly_plan_runs_only_below_one_month_of_stock():
    import kw_plan as KP
    import pace
    with mock.patch.object(pace, "quota", return_value=2):
        check("1日2本の社の1か月分は60本", KP.month_need("x"), 60)
    with mock.patch.object(pace, "quota", return_value=1):
        check("1日1本に絞った社は30本", KP.month_need("x"), 30)
    with mock.patch.object(pace, "quota", return_value=0):
        check("1日0本の社は0本（組み直さない）", KP.month_need("x"), 0)

    ran = []
    cfg = {"cfg": {"name": "x", "id": "x"}, "industries": [], "sheet": [], "sheet_ng": []}
    with mock.patch.object(KP.KD, "site_config", return_value=cfg), \
            mock.patch.object(KP, "sheet_terms", side_effect=lambda s: ran.append(s) or ([], [])), \
            mock.patch.object(pace, "quota", return_value=2):
        for todo in (59, 60, None):
            ran.clear()
            with mock.patch.object(KP, "todo_count", return_value=todo):
                KP.run("x", False, True, if_needed=True)
            check(f"未着手 {todo} 本: {'組み直す' if todo == 59 else '組み直さない'}", bool(ran), todo == 59)
    src = (ROOT / "scripts" / "kw_plan.py").read_text(encoding="utf-8")
    check("40本の固定の基準が残っていない", "ENOUGH = 40" in src, False)


def test_rakko_key_is_read_from_ci_secrets():
    """2026-10-09: CI で RAKKO_API_KEY を渡しても api_key() が .env だけを見ていて「未設定」と判断し、
    補助金の積み足しがラッコを1回も使えなかった（これまで CI では一度も使えていなかった）"""
    import os
    import rakko
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as td, mock.patch.object(rakko, "ROOT", Path(td)), \
            mock.patch.dict(os.environ, {"RAKKO_API_KEY": "ci-key"}):
        check("CI（.env が無い）でも環境変数の鍵を読む", rakko.api_key(), "ci-key")
    with tempfile.TemporaryDirectory() as td, mock.patch.object(rakko, "ROOT", Path(td)), \
            mock.patch.dict(os.environ, {"RAKKO_API_KEY": "YOUR_KEY"}):
        check("雛形のままの値は鍵とみなさない", rakko.api_key(), "")
    env = {k: v for k, v in os.environ.items() if k != "RAKKO_API_KEY"}
    with tempfile.TemporaryDirectory() as td, mock.patch.object(rakko, "ROOT", Path(td)), \
            mock.patch.dict(os.environ, env, clear=True):
        (Path(td) / ".env").write_text("RAKKO_API_KEY=local-key\n", encoding="utf-8")
        check("手元は .env を読む", rakko.api_key(), "local-key")
