# -*- coding: utf-8 -*-
"""2026-11-22 お客様の社（フォームのメールはその社の受信箱にだけ届く）の、台帳への連携前の送信が「台帳に行が無い」と
毎日知らせられ、知らせの文は「info.ai の受信箱を確認」と、届いていない場所を探させていた。
決着した日の記録（ACK）は公開の data/lead_reconcile_ack.json にしか置けず、お客様の社の日付と理由を書くと社名と結びつく。
お客様の社の決着は非公開の置き場の clients/<id>/lead_reconcile_ack.json から読み、知らせの探す先をその社の受信箱にする。
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_lead_ack_client_private():
    import lead_reconcile as L
    print("\n■ お客様の社の問い合わせの照合: 決着は非公開の置き場から読み、探す先はその社の受信箱")
    with tempfile.TemporaryDirectory() as td:
        cdir = Path(td) / "clients" / "cx"
        cdir.mkdir(parents=True)
        (cdir / "site_private.json").write_text(json.dumps({"id": "cx", "domain": "example.com"}), encoding="utf-8")
        (cdir / "lead_reconcile_ack.json").write_text(json.dumps({"2026-11-18": "営業"}), encoding="utf-8")
        with mock.patch.dict(os.environ, {"SS_PRIVATE_DIR": td}):
            check("お客様の社: 非公開の置き場の決着の日を読む", sorted(L.acked("cx")), ["2026-11-18"])
            check("自社: 非公開の置き場を見ず、公開の記録だけ", L.acked("ai-lab"), dict(L.ACKED.get("ai-lab", {})))
            hint = L.inbox_hint("cx")
            check("お客様の社の知らせ: info.ai を探させず、その社の受信箱と非公開の決着の置き場を示す",
                  ("info.ai" in hint, "その社の受信箱" in hint, "lead_reconcile_ack.json" in hint), (False, True, True))
            check("自社の知らせ: 今までどおり info.ai の受信箱", "info.ai の受信箱" in L.inbox_hint("ai-lab"), True)
            ds = (ROOT / "scripts" / "data_sanity.py").read_text(encoding="utf-8")
            check("data_sanity の食い違いも同じ決着（お客様の社の分を含む）で見る",
                  ("L.acked(sid)" in ds, "L.ACKED.get(" in ds), (True, False))
    # 公開の決着の記録に、お客様の社の id・公開の id を書かない（日付と理由が社名と結びつく）
    own = {p.stem for p in (ROOT / "sites").glob("*.json")
           if not json.loads(p.read_text(encoding="utf-8-sig")).get("client")}
    pub = json.loads((ROOT / "data" / "lead_reconcile_ack.json").read_text(encoding="utf-8"))
    check("公開の決着の記録は自社のサイトだけ", sorted(k for k in pub if k != "_comment" and k not in own), [])
