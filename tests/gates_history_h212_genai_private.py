# -*- coding: utf-8 -*-
"""2026-11-23 生成AIの表示回数（genai_import）が、お客様の社の分も公開の data/genai_impressions.json に社の id とページの URL で
書く作りで、未取込の知らせも社の id を CI のログ（public）に出していた。また 11/17 に始めた社の10月分を「未取込」と出していた。
お客様の社の分は非公開の置き場へ書き、知らせは公開の id で出し、始める前の月は数えない。"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_genai_client_rows_stay_private():
    import genai_import as G
    import sites as S
    print("\n■ 生成AIの表示回数: お客様の社の分は非公開の置き場に書き、公開の記録・知らせに社の id を出さない")
    fake = {"ai-lab": {"id": "ai-lab"}, "secretco": {"id": "secretco", "public_id": "p0a1", "start_date": "2026-11-17"},
            "oldco": {"id": "oldco", "public_id": "p0b2", "start_date": "2026-09-01"}}
    client = lambda s: s in ("secretco", "oldco")
    with tempfile.TemporaryDirectory() as td:
        pub = Path(td) / "genai.json"
        with mock.patch.object(S, "load_all", lambda: fake), mock.patch.object(S, "is_client", client), \
                mock.patch.object(S, "public_id", lambda s: (fake.get(s) or {}).get("public_id") or s), \
                mock.patch.object(G, "STORE", pub), mock.patch.dict(os.environ, {"SS_PRIVATE_DIR": td}):
            rec = lambda n, pages=None: {"total": n, "pages": pages or {}, "imported": "2026-11-23", "source": "x.csv"}
            G._save({"2026-10": {"ai-lab": rec(5), "oldco": rec(3, {"https://old.example/a/": 1})}})
            text = pub.read_text(encoding="utf-8")
            check("公開の記録にお客様の社の id もページの URL も書かない", ("oldco" in text, "old.example" in text), (False, False))
            check("お客様の社の分は非公開の置き場に入り、読み戻せる", sorted(G.load()["2026-10"]), ["ai-lab", "oldco"])
            check("始める前の月（10月に11/17開始の社）は数えない", sorted(G.site_ids("2026-10")), ["ai-lab", "oldco"])
        with tempfile.TemporaryDirectory() as td2:
            pub2 = Path(td2) / "genai.json"
            pub2.write_text(json.dumps({"2026-10": {"ai-lab": rec(5)}}), encoding="utf-8")
            buf = io.StringIO()
            with mock.patch.object(S, "load_all", lambda: fake), mock.patch.object(S, "is_client", client), \
                    mock.patch.object(S, "public_id", lambda s: (fake.get(s) or {}).get("public_id") or s), \
                    mock.patch.object(G, "STORE", pub2), mock.patch.dict(os.environ, {"SS_PRIVATE_DIR": td2}), \
                    mock.patch.object(G, "date", type("D", (), {"today": staticmethod(lambda: __import__("datetime").date(2026, 11, 23))})), \
                    redirect_stdout(buf), mock.patch.object(sys, "argv", ["genai_import.py"]):
                G.main()
            out = buf.getvalue()
            check("未取込の知らせは公開の id で出す（社の id を出さない）・始める前の社は出さない",
                  ("oldco" in out, "p0b2" in out, "p0a1" in out), (False, True, False))
