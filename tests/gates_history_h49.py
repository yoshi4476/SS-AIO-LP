# -*- coding: utf-8 -*-
"""コーポレートの相談は「ご相談内容」（service）だけで受け付ける（2026-10-07 判明）。

コーポレートのフォームは「ご相談内容」が必須の選択で、詳細（detail）は任意。受付（contact.hub.gs）は本文が空だと
「必須項目が入力されていません」で弾くため、詳細を書かない相談がすべて失われていた。週次の疎通確認（lead_probe.py）は
いつも本文を入れて送っていたので気づけなかった。
"""
import re

from test_gates import check, ROOT


def test_corporate_contact_without_detail_is_accepted():
    gs = (ROOT / "automation" / "gas" / "contact.hub.gs").read_text(encoding="utf-8")
    form = gs.split("function form_(", 1)[1]
    fallback = form.find("clean_(d.service)")
    has_body = form.find("const hasBody")
    check("受付: 本文が空なら「ご相談内容」を本文の代わりにする", fallback > 0, True)
    check("受付: その代わりは必須の判定（hasBody）より前に置く", 0 < fallback < has_body, True)
    probe = (ROOT / "scripts" / "lead_probe.py").read_text(encoding="utf-8")
    m = re.search(r'results\["corporate"\]\s*=\s*\(probe_direct\("corporate",.*?\)\)', probe, re.S)
    sent = m.group(0) if m else ""
    check("疎通確認: コーポレートはフォームと同じく詳細を空・ご相談内容だけで送る",
          ('"message": ""' in sent, '"detail": ""' in sent, '"service"' in sent), (True, True, True))
