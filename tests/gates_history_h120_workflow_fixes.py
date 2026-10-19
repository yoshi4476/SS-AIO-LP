# -*- coding: utf-8 -*-
"""2026-10-20 ワークフローの点検で見つけた不具合の門。

1. 記事のグループ（article-pipeline）で並んで待った回が、起動した時の版で動いて push で衝突した
   （2026-10-19 の週次は待つ間に入ったコミットの親で動き、そのコミットの3ファイルで衝突）。checkout で枝の最新を取る
2. 月次の AI 引用の実測に管制塔の鍵が無く、Gemini の月の残りを読めずに黙って飛ばしていた
3. 記事の枠の「食い合いゲート（執筆後）」に管制塔の鍵が無く、隔離した語を台帳で外せないまま黙っていた
4. 未配信の確認・監修の記録の「公開の後の手順」に SNS の鍵が無く、そこで公開した記事が SNS に出ていなかった
5. 集中モードがお客様の非公開データを戻すだけで残さず、この回の台帳の行が消えていた
6. 月次が Google の鍵と .env を消さず、改善の実行（中で AI を呼ぶ）を鍵を外さずに動かしていた
7. 週次の optimize が、並行の KW 補充の終わりを待たずに AI の語を戻していた
8. 記事の枠の浮いた枠（中で AI を呼ぶ書き直し）が、鍵を外さずに動いていた
"""
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
WF = ROOT / ".github" / "workflows"
SOCIAL = ("FB_PAGE_ID", "FB_PAGE_TOKEN", "IG_USER_ID", "THREADS_TOKEN", "THREADS_USER_ID",
          "LINKEDIN_TOKEN", "LINKEDIN_ORG_ID", "LINKEDIN_PERSON_ID", "SOCIAL_TOKENS_JSON")


def _y(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _steps(job):
    return job.get("steps") or []


def _step(job, name):
    return next(s for s in _steps(job) if s.get("name") == name)


def _idx(job, pred):
    return next(i for i, s in enumerate(_steps(job)) if pred(s))


def test_queued_jobs_check_out_the_branch_tip():
    print("\n■ 記事のグループで並ぶジョブは、起動した時の版ではなく枝の最新を取る（待つ間のコミットと衝突しない）")
    bad, seen = [], []
    for p in sorted(WF.glob("*.yml")):
        wf = yaml.safe_load(p.read_text(encoding="utf-8"))
        wgroup = str((wf.get("concurrency") or {}).get("group", "")) if isinstance(wf.get("concurrency"), dict) else ""
        for jn, job in (wf.get("jobs") or {}).items():
            c = job.get("concurrency")
            group = str(c.get("group", "")) if isinstance(c, dict) else str(c or "") or wgroup
            if group != "article-pipeline":
                continue
            runs = " ".join(str(s.get("run", "")) for s in _steps(job))
            # 正本へ push するか、配信先へ送る（--push）ジョブ。判定だけの guard は起動した時の版でよい
            if "git push" not in runs and "--push" not in runs:
                continue
            seen.append(f"{p.name}:{jn}")
            co = _steps(job)[0]
            if not (str(co.get("uses", "")).startswith("actions/checkout@")
                    and (co.get("with") or {}).get("ref") == "${{ github.ref_name }}"):
                bad.append(f"{p.name}:{jn}")
    check("対象のジョブが見つかる（週次4・記事の枠・救済・集中モード2）", len(seen) >= 8, True)
    check("最初の checkout で ref: ${{ github.ref_name }}（枝の最新）を取る", bad, [])
    pinned = [f"{p.name}" for p in WF.glob("*.yml")
              for ln in p.read_text(encoding="utf-8").splitlines()
              if "uses: actions/checkout@" in ln and not __import__("re").search(r"@[0-9a-f]{40}\b", ln)]
    check("checkout は今までどおり版の指紋（SHA）で固定", pinned, [])


def test_monthly_ai_cite_has_hub_keys():
    print("\n■ 月次の AI 引用の実測は管制塔の鍵を受け取る（Gemini の月の残りを読む）")
    env = _step(_y("monthly-report.yml")["jobs"]["report"], "AI引用の実測").get("env") or {}
    check("HUB_URL と HUB_SECRET", ("HUB_URL" in env, "HUB_SECRET" in env), (True, True))


def test_after_gate_reports_when_retire_fails():
    print("\n■ 食い合いゲート（執筆後）: 管制塔の鍵を受け取り、台帳で外せなかったら要対応で知らせる")
    st = _step(_y("pipeline-multi.yml")["jobs"]["write"], "食い合いゲート（執筆後）")
    env, run = st.get("env") or {}, str(st.get("run", ""))
    check("HUB_URL と HUB_SECRET", ("HUB_URL" in env, "HUB_SECRET" in env), (True, True))
    check("要対応の行を通知の本文へ足す", "grep '^要対応'" in run and "findings.txt" in run, True)

    import kw_gate as KG
    import kw_fit
    import hub_client

    def run_after(retire):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "articles").mkdir()
            (Path(d) / "articles" / "zz-new.md").write_text("---\nkeyword: 架空の語\n---\n", encoding="utf-8")
            out = io.StringIO()
            with mock.patch.object(KG, "ROOT", Path(d)), \
                    mock.patch.object(KG, "written_keyword", return_value=[("zz-new", "架空の語")]), \
                    mock.patch.object(KG, "judge", return_value=(2, "食い合い")), \
                    mock.patch.object(kw_fit, "judge_new", return_value=(0, "")), \
                    mock.patch.object(hub_client, "retire_kw", side_effect=retire), \
                    mock.patch.object(sys, "argv", ["kw_gate.py", "--after", "--site", "client-zz"]), \
                    redirect_stdout(out):
                rc = KG.main()
            moved = (Path(d) / "articles" / "_conflicted" / "zz-new.md").is_file()
        lines = out.getvalue().splitlines()
        warn = [ln for ln in lines if ln.startswith("要対応:")]
        return rc, moved, len(warn), any("架空の語" in w or "zz-new" in w for w in warn)

    def boom(*a, **k):
        raise OSError("down")

    check("管制塔の設定なし（None）→ 隔離して要対応1行（語・slug は書かない）",
          run_after(lambda *a, **k: None), (0, True, 1, False))
    check("管制塔が拒否（ok でない）→ 要対応1行", run_after(lambda *a, **k: {"ok": False, "error": "unauthorized"})[2], 1)
    check("通信の失敗 → 要対応1行", run_after(boom)[2], 1)
    check("外せたら要対応は出さない", run_after(lambda *a, **k: {"ok": True, "retired": 1})[2], 0)


def test_finish_steps_have_social_keys():
    print("\n■ 公開の後の手順（--finish → post_social）を呼ぶ工程は SNS の鍵を受け取る")
    pm = _y("pipeline-multi.yml")["jobs"]["write"]
    ar = _y("approve-review.yml")["jobs"]["approve"]
    base = set((_step(pm, "書いた記事を配信する（鍵を持つ機械の手順）").get("env") or {}))
    check("基準の工程（書いた記事を配信する）が SNS の鍵を持つ", [k for k in SOCIAL if k not in base], [])
    for name, job, stn in (("記事の枠", pm, "未配信の記事がないかの確認"), ("監修の記録", ar, "公開の後の手順")):
        st = _step(job, stn)
        env = st.get("env") or {}
        check(f"{name}「{stn}」は --finish を呼び、SNS の鍵を全部受け取る",
              ("publish_flow.py --finish" in str(st.get("run", "")), [k for k in SOCIAL if k not in env]), (True, []))


def test_focus_mode_saves_client_private():
    print("\n■ 集中モードはお客様の非公開データを戻したら、終わりに必ず残す")
    job = _y("focus-mode.yml")["jobs"]["focus"]
    cp = [(i, s) for i, s in enumerate(_steps(job)) if str(s.get("uses", "")) == "./.github/actions/client-private"]
    modes = [(s.get("with") or {}).get("mode") for _, s in cp]
    check("restore と save の両方", sorted(modes), ["restore", "save"])
    save = next((i, s) for i, s in cp if (s.get("with") or {}).get("mode") == "save")
    commit = _idx(job, lambda s: s.get("name") == "最終ビルドとコミット")
    check("save は always() でコミットより後", ("always()" in str(save[1].get("if", "")), save[0] > commit), (True, True))


def test_monthly_locks_ai_and_cleans_keys():
    print("\n■ 月次: 改善の実行（中で AI を呼ぶ）は鍵を外して動かし、配信の鍵は外した後の機械の手順だけが持つ")
    job = _y("monthly-report.yml")["jobs"]["report"]
    names = [s.get("name") for s in _steps(job)]
    i_lock = names.index("改善の実行の前に作業場から鍵を外す")
    i_act = names.index("レポートの改善点を実行し、残りを人へ知らせる")
    i_prot = names.index("改善の実行で触ってはいけない場所を戻す")
    i_unl = names.index("改善の実行の後に作業場へ鍵を戻す")
    i_pub = names.index("改善の実行で直した記事をコミットし配信先へ届ける")
    check("順番: 外す → 実行 → 戻す場所 → 鍵を戻す → 配信", i_lock < i_act < i_prot < i_unl < i_pub, True)
    lock, act, prot, unl, pub = (_steps(job)[i] for i in (i_lock, i_act, i_prot, i_unl, i_pub))
    check("外す工程は agent_guard --lock と許可証の作り直し",
          ("agent_guard.py --lock" in lock["run"], "agent_guard.py --refresh" in lock["run"]), (True, True))
    check("実行の工程は report_actions --apply を動かし、配信・Google の鍵を持たない",
          ("report_actions.py --apply" in act["run"],
           sorted(k for k in (act.get("env") or {}) if k in ("SITE_PUSH_TOKEN", "FTP_CREDENTIALS_JSON",
                                                             "WP_CREDENTIALS_JSON", "GCP_SERVICE_ACCOUNT_JSON"))),
          (True, []))
    check("戻す工程は always() で、--protect と --unlock",
          ("always()" in str(prot.get("if")), "--protect" in prot["run"], "always()" in str(unl.get("if")),
           "agent_guard.py --unlock" in unl["run"], "GCP_SERVICE_ACCOUNT_JSON" in (unl.get("env") or {})),
          (True, True, True, True, True))
    check("配信の工程が publish_changed を動かし、配信の鍵を持つ",
          ("publish_changed.py" in pub["run"], "SITE_PUSH_TOKEN" in (pub.get("env") or {})), (True, True))
    put = _idx(job, lambda s: "printf '%s' \"$SA_JSON\" > indexing-service-account.json" in str(s.get("run", "")))
    clean = [(i, s) for i, s in enumerate(_steps(job))
             if "rm -f indexing-service-account.json .env" in str(s.get("run", "")) and "always()" in str(s.get("if", ""))]
    check("鍵のファイルと .env を always() で消す（置いた後）", bool(clean) and clean[0][0] > put, True)


def test_weekly_optimize_waits_for_kw_refill():
    print("\n■ 週次: optimize は並行の KW 補充が終わるのを待ってから、pull と AI の語の戻しをする")
    wf = _y("weekly-optimize.yml")
    job = wf["jobs"]["optimize"]
    check("needs に kw-refill を入れない（始まりを遅らせない）", "kw-refill" in str(job.get("needs")), False)
    i_wait = _idx(job, lambda s: s.get("name") == "並行のKW補充が終わるのを待つ")
    i_save = _idx(job, lambda s: s.get("name") == "途中までの直しを正本へ保存")
    i_rest = _idx(job, lambda s: (s.get("with") or {}).get("family") == "ai-kw")
    run = str(_steps(job)[i_wait].get("run", ""))
    check("待つ工程は pull（途中の保存）と ai-kw の戻しより前", i_wait < i_save < i_rest, True)
    check("待つのは kw-refill の終わり・上限つき・読めなければ進む",
          ('select(.name == "kw-refill")' in run, "completed" in run, "seq 1 80" in run, '[ -z "$st" ]' in run),
          (True, True, True, True))
    check("ジョブの名前が kw-refill のまま（API の名前と一致）", "name" in wf["jobs"]["kw-refill"], False)
    check("ジョブの一覧を読む権限", (wf.get("permissions") or {}).get("actions"), "read")


def test_spare_slot_runs_with_keys_removed():
    print("\n■ 浮いた枠: 書き直し（中で AI を呼ぶ）は鍵を外して動かし、終わったら（失敗しても）戻す")
    job = _y("pipeline-multi.yml")["jobs"]["write"]
    names = [s.get("name") for s in _steps(job)]
    i_lock = names.index("浮いた枠：作業場から鍵を外す")
    i_rw = names.index("浮いた枠：主力の記事を1本書き直す")
    i_prot = names.index("浮いた枠：触ってはいけない場所を戻す")
    i_unl = names.index("浮いた枠：作業場へ鍵を戻す")
    check("順番: 外す → 書き直す → 戻す場所 → 鍵を戻す", i_lock < i_rw < i_prot < i_unl, True)
    lock, rw, prot, unl = (_steps(job)[i] for i in (i_lock, i_rw, i_prot, i_unl))
    check("外す工程は id spare_lock で agent_guard --lock（Google の鍵から読むだけの許可証を作る）",
          (lock.get("id"), "agent_guard.py --lock" in lock["run"], "GCP_SERVICE_ACCOUNT_JSON" in (lock.get("env") or {})),
          ("spare_lock", True, True))
    check("書き直しの工程は Google の鍵を持たず、鍵のファイルを書かない",
          ("GCP_SERVICE_ACCOUNT_JSON" in (rw.get("env") or {}), "> indexing-service-account.json" in rw["run"],
           "auto_rewrite.py --write --kind spare" in rw["run"]),
          (False, False, True))
    check("戻す工程は always() かつ外す工程が動いた回",
          [("always()" in str(s.get("if")) and "steps.spare_lock.outcome != 'skipped'" in str(s.get("if"))) for s in (prot, unl)],
          [True, True])
    check("鍵を戻す前に範囲を全部へ戻す",
          0 <= unl["run"].find("private_store.py --scope all") < unl["run"].find("agent_guard.py --unlock"), True)
