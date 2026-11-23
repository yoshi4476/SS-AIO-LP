# -*- coding: utf-8 -*-
"""2026-11-23 週次の描き直しの記録（data/rerender_state.json。公開リポジトリに commit する）が、お客様の社を
社の id（社名から作る）で書き、公開リポジトリに社名が出た。記録とログは公開の id（sites/<id>.json の印）で書き、
前の書き方の行は公開の id へ移す。本物の描き直しは呼ばない。"""
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_rerender_state_uses_public_id():
    import rerender_watch as R
    import sites as S
    print("\n■ 描き直しの記録とログは、お客様の社を公開の id で書く")
    sites = {"secretco": {"id": "secretco", "public_id": "p0a1b2c3d", "client": True, "type": "nextjs-json",
                          "name": "株式会社ひみつ"},
             "ai-lab": {"id": "ai-lab", "type": "self-static"},
             "corp": {"id": "corp", "type": "nextjs-json"}}
    with tempfile.TemporaryDirectory() as td:
        state = Path(td) / "rerender_state.json"
        # 材料は前の回と同じ。移せていれば「変わっていない」で日付が残り、移せていなければ初めて見る社として今日になる
        old = {"fp": R.fingerprint({"sites": "y"}), "parts": {"sites": "y"}, "at": "2026-11-16"}
        state.write_text(json.dumps({"secretco": old}), encoding="utf-8")
        buf = io.StringIO()
        with mock.patch.object(R, "STATE", state), mock.patch.object(S, "load_all", lambda: sites), \
                mock.patch.object(R, "inputs", lambda cfg, dest=None: {"sites": "y"}), \
                mock.patch.object(R, "rerender", lambda sid: True), \
                mock.patch.object(sys, "argv", ["rerender_watch.py", "--push"]), redirect_stdout(buf):
            R.main()
        st = json.loads(state.read_text(encoding="utf-8"))
        check("記録: お客様の社は公開の id で書き、社の id の行は残さない", sorted(st), ["corp", "p0a1b2c3d"])
        check("記録: 前の書き方の行を公開の id へ移し、前の回の指紋と比べる（初めて見る社に戻さない）",
              st["p0a1b2c3d"]["at"], "2026-11-16")
        out = buf.getvalue()
        check("ログ: 社の id・社名を出さない", ("secretco" in out, "ひみつ" in out, "p0a1b2c3d" in out), (False, False, True))
    # 公開リポジトリの記録そのもの: 自社のサイトと公開の id だけ
    ids = {p.stem for p in (ROOT / "sites").glob("*.json")}
    pub = json.loads((ROOT / "data" / "rerender_state.json").read_text(encoding="utf-8"))
    check("data/rerender_state.json の鍵は sites/ の id（公開の名前）だけ", sorted(k for k in pub if k not in ids), [])
