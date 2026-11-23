# -*- coding: utf-8 -*-
"""2026-11-23 対照群と比べて効きが出ない施策（link_rescue・link_decay・title）を、週次は知らせるだけで当て続けていた。
運用者の決定「自動で休む仕組みにする」: effect_ab が効かないと判定した種類を4週休ませ、終われば自動で戻し、
戻ってから測り直す（すぐまた休ませない）。stock（出どころの無い体験談の決まり文句を直す）は事実のための直しなので休ませない。"""
import io
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_strategy_pause_cycle():
    import strategy_pause as SP
    print("\n■ 効きが出ない施策を4週休ませ、自動で戻し、戻ってから測り直す")
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(SP, "FILE", Path(td) / "pause.json"):
            d0 = date(2026, 11, 23)
            check("休ませるのは測れる施策だけ（stock は休ませない）",
                  SP.note(["link_rescue", "title", "stock"], today=d0), ["link_rescue", "title"])
            check("休止中は当てない", (SP.paused("link_rescue", date(2026, 12, 1)), SP.paused("stock", date(2026, 12, 1))),
                  (True, False))
            check("4週たてば自動で戻る", SP.paused("link_rescue", date(2026, 12, 21)), False)
            check("戻ってすぐは、古い記録で休ませ直さない", SP.note(["link_rescue"], today=date(2026, 12, 28)), [])
            check("戻って8週たてば、また判定で休ませられる", SP.note(["link_rescue"], today=date(2027, 2, 16)), ["link_rescue"])
            import auto_rewrite as A
            buf = io.StringIO()
            with mock.patch.object(SP, "paused", lambda k, today=None: k == "title"), redirect_stdout(buf):
                got = A.pick_items(type("A", (), {"slugs": ""})(), "title", 3)
            check("auto_rewrite: 休止中の種類は候補を出さない", (got, "休止中" in buf.getvalue()), ([], True))
    lb = (ROOT / "scripts" / "link_boost.py").read_text(encoding="utf-8")
    check("link_boost: link_rescue・link_decay の休止を見る",
          ('SP.paused("link_rescue")' in lb, 'SP.paused("link_decay")' in lb), (True, True))
    ab = (ROOT / "scripts" / "effect_ab.py").read_text(encoding="utf-8")
    check("effect_ab: 2つの判定（施策・書き直しの種類）の両方で休止を書く", ab.count('_pause(weak, "'), 2)
