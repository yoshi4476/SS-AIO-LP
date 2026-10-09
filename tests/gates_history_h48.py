# -*- coding: utf-8 -*-
"""自動化の点検（2026-10-07「全ファイルをチェックして、完璧な自動化ができているか」）で見つけた穴。

  1. お客様の社を足した日、rank_track・ai_kw_research などが全社を回すため、先方の検索語と順位が
     その夜の救済の `git add -A` で public リポジトリに載るところだった（compete・bing_stats・cwv_crux だけ除外していた）
  2. お客様の社の設定の gsc_owner=false・GA4 の閲覧の記録なしが、API で確かめた実態（Search Console は siteOwner・
     GA4 は読める）と食い違い、準備状況が「GA4 に当社を閲覧者で追加（お客様）」と誤って知らせる
  3. history_checks_d は CI に GH_TOKEN が無く、鍵の登録と配信先の検査が1つも動かないまま HISTD_OK=yes と出ていた
     （2026-10-05 の週次のログ: 「gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN environment」）
  4. 書き直しの配信（publish_changed）に落ちた記事は `|| true` で黙って捨てられ、--since のため次の回も送られない
  5. 結果の見張りが月の上限を全社60で数え、月30本の社が上限で止まった日から月末まで「書かれていない」と知らせる
  6. geo_check が sitemap の深さだけで記事を数え、業種ハブ・用語集・調査ページまで数えて ai-lab の llms.txt を
     「74%」と誤って出していた（別の数え方で 146/146 本＝100%。2026-10-07）
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from test_gates import check, ROOT, client_ready

sys.path.insert(0, str(ROOT / "scripts"))

OWN = ("ai-lab", "corporate", "subsidy")
# サイトごとに名前の付く、検索語・順位・AIの出典の記録（書き手 → 置き場）
PER_SITE = ("data/ranks/{}.json", "data/ai_kw/{}.json", "data/win_patterns/{}.md", "docs/ai-kw-{}.md",
            "docs/kw-strong-{}.md", "docs/country-{}.md", "docs/season-{}.md", "docs/kw-plan-{}.md",
            "data/bing_stats/{}.json", "data/cwv_crux/{}.json", "data/compete/{}/2026-10.json")


def _ignored(rel):
    return subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", rel]).returncode == 0


def test_client_search_data_stays_out_of_public_repo():
    import sites as S
    clients = [sid for sid in S.load_all() if S.is_client(sid)] + ["client-zz"]
    leak = [p.format(sid) for sid in clients for p in PER_SITE if not _ignored(p.format(sid))]
    check("お客様の検索語・順位・AIの出典の記録は public に置かない（新しい社も既定で外れる）", leak, [])
    kept = [p.format(sid) for sid in OWN for p in PER_SITE if _ignored(p.format(sid))]
    check("自社3サイトの記録はこれまでどおりコミットできる", kept, [])
    # 書き手が本当に全社を回すこと（回さないなら除外は要らない。回すから除外が要る）
    for name in ("rank_track.py", "ai_kw_research.py", "win_patterns.py"):
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        check(f"{name} は sites/*.json の全社を回す（お客様の分も書く）", "load_all()" in src, True)




def test_histd_does_not_claim_ok_when_github_checks_could_not_run():
    import history_checks_d as HD
    import findings as F
    import gas_deploy as G
    msg = "gh: To use GitHub CLI in a GitHub Actions workflow, set the GH_TOKEN environment variable."
    saved = (HD.shutil.which, HD.subprocess.run, HD._env, G.CLASPRC)
    try:
        HD.shutil.which = lambda name: "/usr/bin/gh"
        HD.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 4, stdout="", stderr=msg)
        HD._env = lambda key: ""
        G.CLASPRC = Path(tempfile.gettempdir()) / "no-such-clasprc.json"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = HD.main()
        out = buf.getvalue()
    finally:
        HD.shutil.which, HD.subprocess.run, HD._env, G.CLASPRC = saved
    check("history_checks_d: GitHub の検査が動かなかったことを印に出す", "HISTD_GH_OK=unknown" in out, True)
    check("history_checks_d: 動かなかった回を findings が「問題なし」と読まない", F.judge(out, rc), "動かせず")


def test_failed_redelivery_reaches_the_notice():
    import types
    import publish_changed as PC
    cfg = {"id": "cx", "name": "テストの社", "type": "external-md", "repo": "o/r"}
    saved = (PC.sites_mod, PC.changed_by_git, PC.subprocess, PC.time, sys.argv)
    buf = io.StringIO()
    try:
        PC.sites_mod = types.SimpleNamespace(load_all=lambda: {"cx": cfg}, load=lambda sid: cfg)
        PC.changed_by_git = lambda sid, since: ["s1", "s2", "s3", "s4"]
        PC.subprocess = types.SimpleNamespace(
            run=lambda *a, **k: types.SimpleNamespace(returncode=1, stdout="", stderr="push に失敗"))
        PC.time = types.SimpleNamespace(sleep=lambda s: None)
        sys.argv = ["publish_changed.py", "--all", "--since", "HEAD", "--push"]
        with contextlib.redirect_stdout(buf):
            rc = PC.main()
    finally:
        PC.sites_mod, PC.changed_by_git, PC.subprocess, PC.time, sys.argv = saved
    got = [l for l in buf.getvalue().splitlines() if l.startswith("要対応:")]
    check("publish_changed: 配信に落ちた記事を「要対応」の1行で出す（ワークフローが findings.txt へ足す）",
          (len(got), "s1" in "".join(got)), (1, True))
    check("publish_changed: 3本続けて落ちて打ち切った残りも「届いていない」に数える", "4本" in "".join(got), True)
    check("publish_changed: 落ちた回は終了コード1（印と別に）", rc, 1)
    # 通知のファイルは書かない（門が実物の findings.txt を汚し、調査の更新が誤って知らせる）
    src = Path(PC.__file__).read_text(encoding="utf-8")
    check("publish_changed: findings.txt を自分で書かない", ('"findings.txt"' in src, "FINDINGS" in src), (False, False))




def test_rescue_waits_for_each_sites_own_slot():
    """救済（daily_audit）が「不足」と言うのは、その社の枠の時刻＋猶予を過ぎてから。
    3社の時刻を手で書いていたため、書いていない社（お客様の社）は時刻に関係なく不足とみなされ、
    夜の救済（実際は翌3時ごろに走る）が先回りで1本書き、枠の1本と合わせて1日1本の決まりを超えるところだった"""
    import daily_audit as D
    import pace
    import site_order
    import sites as S
    ph = getattr(D, "publish_hours", None)
    check("救済: 枠の時刻を pipeline-multi.yml の割り当てから求める（社を足しても手で直さない）", callable(ph), True)
    if not callable(ph):
        return
    saved = pace.quota
    bad = []
    try:
        # お客様の社は1日1本（枠の並びは公開の id、本数は社の id で数える。どちらで聞いても同じ本数）
        pace.quota = lambda sid: 1 if S.is_client(sid) else 2
        for s in site_order.order():
            hs, want = ph(s), min(D.DAILY_TARGET, pace.quota(s))
            if hs is None or len(hs) != want:
                bad.append(f"{s}: 枠 {hs} / 1日 {want}本")
                continue
            before = min(hs) + D.GRACE_HOURS - 1
            if 0 <= before < 24 and D._due_now(s, hour=before) != 0:
                bad.append(f"{s}: 最初の枠（{min(hs)}時）の前から不足とみなす")
            after = max(hs) + D.GRACE_HOURS
            if after < 24 and D._due_now(s, hour=after) != want:
                bad.append(f"{s}: 最後の枠（{max(hs)}時）の後も {D._due_now(s, hour=after)}本しか求めない")
    finally:
        pace.quota = saved
    check("救済: どの社も、自分の枠の時刻が来る前に不足とみなさず、来た後は1日の本数を求める", bad, [])


def test_site_brief_uses_each_sites_cap():
    src = (ROOT / "scripts" / "site_brief.py").read_text(encoding="utf-8")
    body = src[src.index("# 月の上限は publish_flow"):src.index("# 何を売る記事なのか")]
    check("執筆の案内: 月の上限は publish_flow と同じ社ごとの数（site_cap）で知らせる",
          ("site_cap(" in body, "daily_audit.MONTHLY_CAP" in body), (True, False))


def _wf_steps(name, job):
    import yaml
    y = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
    return y["jobs"][job]["steps"]


def test_weekly_findings_reach_the_notice():
    """週次の通知本文（findings.txt）に、見つけたものが本当に届くこと"""
    opt = _wf_steps("weekly-optimize.yml", "optimize")
    fstep = next(s for s in opt if "scripts/findings.py" in str(s.get("run", "")))
    env = fstep.get("env") or {}
    check("週次の検査の工程に配信の鍵を渡す（渡さないと準備状況が「配信用トークンの登録」と誤って知らせる）",
          [k for k in ("SITE_PUSH_TOKEN", "FTP_CREDENTIALS_JSON", "WP_CREDENTIALS_JSON") if k not in env], [])
    rep = _wf_steps("weekly-optimize.yml", "reports")
    runs = {s.get("name"): str(s.get("run", "")) for s in rep}
    for script in ("lead_probe.py", "aicheck_funnel.py", "geo_check.py"):
        body = next((r for r in runs.values() if script in r), "")
        check(f"週次の読むだけの検査: {script} の要対応を findings.txt へ書く",
              ">> automation/logs/findings.txt" in body, True)
    # 成果物（artifact）は public のリポジトリでは誰でも落とせるので、CI のキャッシュで渡す（2026-10-10 守秘義務・h76）
    up = [s for s in rep if "reports-findings" in str((s.get("with") or {}).get("path", ""))
          and "cache/save" in str(s.get("uses", ""))]
    check("週次の読むだけの検査: 要対応を optimize へ渡す（キャッシュ）",
          bool(up) and str(up[0].get("if", "")) == "always()", True)
    names = [str(s.get("name", "")) for s in opt]
    dl = next((i for i, s in enumerate(opt) if "reports-findings" in str((s.get("with") or {}).get("path", ""))
               and "cache/restore" in str(s.get("uses", ""))), None)
    cat = next((i for i, s in enumerate(opt) if "reports-findings/findings.txt" in str(s.get("run", ""))), None)
    fi = next(i for i, s in enumerate(opt) if "scripts/findings.py" in str(s.get("run", "")))
    check("週次: 受け取った要対応を findings.py より前に通知本文へ足す",
          dl is not None and cat is not None and dl < cat < fi, True)
    # 書き直しの配信に落ちた記事（publish_changed が出す「要対応」）を3つのワークフローとも通知本文へ足す
    for wf, job in (("weekly-optimize.yml", "optimize"), ("focus-mode.yml", "focus"), ("monthly-report.yml", "report")):
        body = next(str(s.get("run", "")) for s in _wf_steps(wf, job) if "publish_changed.py" in str(s.get("run", "")))
        check(f"{wf}: publish_changed の要対応を findings.txt へ足す",
              "tee /tmp/publish_changed.txt" in body and "grep '^要対応' /tmp/publish_changed.txt >> automation/logs/findings.txt" in body,
              True)
    check("週次の名前が変わっていない（取り違え防止）", "見つかったものを集めて知らせる" in names, True)


def test_geo_check_counts_only_articles():
    import geo_check as GC
    sm = "".join(f"<url><loc>{u}</loc></url>" for u in (
        "https://x.jp/", "https://x.jp/aio/a1/", "https://x.jp/aio/a2/", "https://x.jp/industry/clinic/",
        "https://x.jp/glossary/abc/", "https://x.jp/research/dental/"))
    llms = "- [A1](https://x.jp/aio/a1/): 説明\n- [A2](https://x.jp/aio/a2): 説明\n- [業種](https://x.jp/industry/clinic/)\n"
    cov = getattr(GC, "article_coverage", None)
    check("geo_check: llms.txt の掲載率は、その社の記事（原稿の slug）だけで数える",
          cov(sm, llms, {"a1", "a2"})[:2] if cov else None, (2, 2))
    src = (ROOT / "scripts" / "geo_check.py").read_text(encoding="utf-8")
    check("geo_check: 掲載率も抽出する記事も、深さ（/ の数）で記事を決めない", "count(\"/\") >= 4" in src, False)


def test_outcome_watch_uses_each_sites_cap():
    """月の上限は社ごと（daily_audit.site_cap）。月30本と決めた社が上限に達した日から月末まで「書かれていない」と
    知らせていた（2026-10-07 の点検）。架空の社で確かめる（お客様の社の設定は非公開の置き場）"""
    import outcome_watch as OW
    import pace
    import sites as S
    day = date(2026, 11, 30)
    arts = [{"slug": f"a{i}", "date": f"2026-11-{i:02d}", "score": "95"} for i in range(1, 30)]
    arts.append({"slug": "a30", "date": "2026-11-29", "score": "95"})
    saved = (pace.quota, S.load)
    try:
        pace.quota = lambda sid: 1
        S.load = lambda sid: {"id": sid, "rules": {"monthly_cap": 30}}
        want = OW.expected_articles("client-zz", arts, day)
    finally:
        pace.quota, S.load = saved
    check("結果の見張り: 月30本の社（rules.monthly_cap）が30本書いた後は、その日の本数を求めない", want, 0)
