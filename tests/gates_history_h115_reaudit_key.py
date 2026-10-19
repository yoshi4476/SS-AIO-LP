# -*- coding: utf-8 -*-
"""2026-10-20 救済後の再監査に Search Console の鍵が渡っておらず、食い合い・指名検索・未登録の確認が毎晩
「取得できません」で終わっていた。そのうえ再監査は「今回出なかった TODO」を管制塔で「解消」にするため、
見えなかっただけの課題を毎晩消していた。再監査にも鍵を渡し、動かなかった検査がある回は解消の同期をしない。
"""
import io
import sys
from contextlib import redirect_stdout

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_audit_marks_checks_that_could_not_run():
    import daily_audit as D
    print("\n■ 動かなかった検査は AUDIT_SKIPPED= で知らせる（TODO が出ないのは「無い」ではなく「分からない」）")
    import cannibal_check
    orig = cannibal_check.serp_overlap
    D.SKIPPED.clear()
    try:
        cannibal_check.serp_overlap = lambda: (_ for _ in ()).throw(FileNotFoundError("indexing-service-account.json"))
        with redirect_stdout(io.StringIO()):
            D.check_serp_overlap([])
    finally:
        cannibal_check.serp_overlap = orig
    check("取得できなかった検査を SKIPPED に残す", D.SKIPPED, ["食い合い"])
    D.SKIPPED.clear()
    src = (ROOT / "scripts" / "daily_audit.py").read_text(encoding="utf-8")
    check("結果の前に AUDIT_SKIPPED= を出す", 'print(f"AUDIT_SKIPPED=' in src, True)


def test_reaudit_has_the_key_and_does_not_resolve_unseen_todos():
    import yaml
    print("\n■ 救済後の再監査は鍵を受け取り、動かなかった検査がある回は「解消」を同期しない")
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8"))
    steps = [s for j in wf["jobs"].values() for s in j.get("steps", [])]
    st = next(s for s in steps if "救済後の再監査" in str(s.get("name")))
    run = str(st.get("run", ""))
    check("再監査の env に GCP_SERVICE_ACCOUNT_JSON", "GCP_SERVICE_ACCOUNT_JSON" in (st.get("env") or {}), True)
    check("監査の前に鍵のファイルを置き、後で消す",
          (run.find("indexing-service-account.json") < run.find("daily_audit.py"), "rm -f indexing-service-account.json" in run),
          (True, True))
    i_skip, i_sync = run.find("AUDIT_SKIPPED="), run.find("error_sync")
    check("AUDIT_SKIPPED= の回は error_sync の前で分岐する", 0 <= i_skip < i_sync, True)
