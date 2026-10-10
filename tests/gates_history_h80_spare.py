# -*- coding: utf-8 -*-
"""2026-10-10 補助金の浮いた枠（主力の記事を1本書き直す枠）が「書き直す主力の記事がありません」で何もせずに終わった。
手元では同じ条件で候補が3本出た。候補が尽きた日の無料の調べ（auto_rewrite.free_spare_items → cooccur.cover）は、
上位・AIの出典を Gemini 検索で集めるが、CI のその工程に GEMINI_API_KEY を渡していなかった。出典が0件になると
足す語も0個になり、候補が黙って0本になる（ログには何も出なかった）
"""
import io
import contextlib
import sys
from unittest import mock

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_spare_slot_free_search_has_its_key_and_says_why_when_empty():
    print("\n■ 浮いた枠: 無料の調べに Gemini の鍵を渡し、出典が集まらないときは黙らずに理由を出す")
    y = yaml.safe_load((ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8"))
    steps = [s for j in y["jobs"].values() for s in j.get("steps") or [] if s.get("name") == "浮いた枠：主力の記事を1本書き直す"]
    check("浮いた枠の書き直しの工程に GEMINI_API_KEY を渡す",
          [("GEMINI_API_KEY" in (s.get("env") or {})) for s in steps], [True])

    import auto_rewrite as AR
    import cooccur
    import kw_plan as KP
    arts = {"main-a": "AI導入補助金 対象", "main-b": "AI導入補助金 不採択 理由"}
    out = io.StringIO()
    with mock.patch.object(AR, "page_positions", return_value={"main-a": (6.0, 40), "main-b": (9.0, 30)}), \
            mock.patch.object(KP, "site_articles", return_value=arts), \
            mock.patch.object(AR, "is_main", return_value=True), \
            mock.patch("noindex.drop", side_effect=lambda items: items), \
            mock.patch.object(cooccur, "cover", return_value={"keyword": "x", "sources": [], "covered": [], "missing": []}), \
            mock.patch("pathlib.Path.read_text", return_value="---\ntitle: x\n---\n本文"), \
            contextlib.redirect_stdout(out):
        items = AR.free_spare_items("subsidy")
    check("出典が0件なら候補にしない", items, [])
    check("出典が0件だったことを記事ごとにログへ出す（黙って尽きない）",
          out.getvalue().count("出典を1件も集められませんでした"), 2)
