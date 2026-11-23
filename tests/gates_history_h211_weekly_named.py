# -*- coding: utf-8 -*-
"""2026-11-23 週次の要対応が、何をすればよいかを名指しせずに毎週くり返していた3件。
- 鍵の配布の確認: Secrets を読む鍵が 401 で失効していても「動かせず」だけ（7週目）
- CrUX: 鍵の「APIの制限」で断られた ACCESS_DENIED を見分けず「鍵か API の設定を確かめて」だけ
- KW重複: 運用者が「重なってよい」と決めた社（kw_overlap_ok）を含む組も「未確認」と出し続けた"""
import io
import subprocess
import sys
from contextlib import redirect_stdout
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_weekly_items_name_the_action():
    print("\n■ 週次の要対応: 失効した鍵・CrUX の鍵の制限を名指しし、重なってよいと決めた社の KW 重複は要対応にしない")
    import history_checks_d as D
    bad = subprocess.CompletedProcess([], 1, "", "HTTP 401: Bad credentials (https://api.github.com/...)")
    buf = io.StringIO()
    with mock.patch.object(D.shutil, "which", lambda n: "gh"), mock.patch.object(D.subprocess, "run", lambda *a, **k: bad), \
            redirect_stdout(buf):
        D.check_secrets([])
    check("鍵の配布: 401 なら GH_SECRET_TOKEN の失効を要対応で名指しする",
          any(l.startswith("要対応:") and "GH_SECRET_TOKEN" in l for l in buf.getvalue().splitlines()), True)
    other = subprocess.CompletedProcess([], 1, "", "network unreachable")
    buf = io.StringIO()
    with mock.patch.object(D.shutil, "which", lambda n: "gh"), mock.patch.object(D.subprocess, "run", lambda *a, **k: other), \
            redirect_stdout(buf):
        D.check_secrets([])
    check("鍵の配布: 401 でない失敗は鍵の失効と言わない", "GH_SECRET_TOKEN が失効" in buf.getvalue(), False)

    import cwv_check as C
    msg = C.crux_fix('403 {"error":{"status":"PERMISSION_DENIED","details":[{"reason":"ACCESS_DENIED"}]}}')
    check("CrUX: ACCESS_DENIED は鍵の「APIの制限」と CRUX_API_KEY を名指しする",
          ("APIの制限" in msg, "CRUX_API_KEY" in msg), (True, True))

    import hub_client as H
    import sites as S
    rows = [{"keyword": "x", "site_a": "corporate", "site_b": "p0ok", "status": "未確認"},
            {"keyword": "y", "site_a": "corporate", "site_b": "ai-lab", "status": "未確認"}]
    fake = {"okco": {"id": "okco", "public_id": "p0ok", "kw_overlap_ok": True, "client": True},
            "corporate": {"id": "corporate"}, "ai-lab": {"id": "ai-lab"}}
    buf = io.StringIO()
    with mock.patch.object(H, "enabled", lambda: True), mock.patch.object(H, "kw_overlaps", lambda: rows), \
            mock.patch.object(S, "load_all", lambda: fake), mock.patch.object(S, "is_client", lambda s: s in ("okco", "p0ok")), \
            redirect_stdout(buf):
        H.overlaps_report()
    out = buf.getvalue()
    check("KW重複: 重なってよいと決めた社を含む組は数えず、ほかの組は今までどおり要対応",
          ("未確認1件" in out, "KW_OVERLAP_OK=no" in out), (True, True))
    buf = io.StringIO()
    with mock.patch.object(H, "enabled", lambda: True), mock.patch.object(H, "kw_overlaps", lambda: rows[:1]), \
            mock.patch.object(S, "load_all", lambda: fake), mock.patch.object(S, "is_client", lambda s: s in ("okco", "p0ok")), \
            redirect_stdout(buf):
        H.overlaps_report()
    check("KW重複: 重なってよい組だけなら要対応にしない", "KW_OVERLAP_OK=yes" in buf.getvalue(), True)
