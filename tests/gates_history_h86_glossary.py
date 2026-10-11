# -*- coding: utf-8 -*-
"""2026-10-11 用語集の AIO の定義が、新しい記事「aio 文字数」のもの（根拠として使われるよう整える取り組み）に入れ替わり、
トップ・LP の図の説明（出典として引用されるよう整える）と食い違った（門 gates_history_h59 が止めた）。

用語集は「同じ用語は新しい記事の定義を採る」作りだったため、中心の用語の定義が記事の増えるたびに入れ替わる。
その用語を説明する記事（狙う語が「<用語>とは」）の定義を優先し、無いときだけ新しい記事の定義を採る
"""
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

ART = """---
title: {title}
keyword: {kw}
category: aio
date: {date}
score: 95
---
<div class="definition-box"><span class="term">AIO（AI Overview Optimization）とは</span>、{d}</div>
"""


def test_glossary_prefers_the_article_that_explains_the_term():
    print("\n■ 用語集: 中心の用語は、その用語を説明する記事（「<用語>とは」）の定義を採る（新しい記事で入れ替えない）")
    import glossary as G
    check("「aioとは」は AIO（AI Overview Optimization）を説明する記事・「aio 文字数」は違う",
          (G._explains("aioとは", "AIO（AI Overview Optimization）"), G._explains("aio 文字数", "AIO（AI Overview Optimization）"),
           G._explains("AIO とは", "AIO")), (True, False, True))
    old = "AIの回答で自社ページが出典として引用されるように内容と構造を整える施策です。"
    new = "AIが回答を作るときに自社サイトの情報が根拠として使われるよう整える取り組みです。"
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "articles").mkdir()
        (root / "articles" / "aio-towa.md").write_text(ART.format(title="AIOとは", kw="aioとは", date="2026-09-01", d=old),
                                                        encoding="utf-8")
        (root / "articles" / "aio-mojisuu.md").write_text(ART.format(title="AIOの文字数", kw="aio 文字数", date="2026-10-11",
                                                                     d=new), encoding="utf-8")
        with mock.patch.object(G, "ROOT", root), mock.patch("sites.find_category_owner", return_value="ai-lab"), \
                mock.patch("noindex.hidden_fm", return_value=False):
            terms = {r["term"]: r for r in G.collect("ai-lab")}
            got = terms["AIO（AI Overview Optimization）"]["slug"]
            (root / "articles" / "aio-towa.md").unlink()
            fallback = {r["term"]: r for r in G.collect("ai-lab")}["AIO（AI Overview Optimization）"]["slug"]
    check("説明の記事がある用語は、新しい記事があってもその定義を採る", got, "aio-towa")
    check("説明の記事が無い用語は、今までどおり新しい記事の定義を採る", fallback, "aio-mojisuu")
