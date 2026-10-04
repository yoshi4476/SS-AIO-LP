# -*- coding: utf-8 -*-
"""落ちたCIの再実行と、未登録ページの再送の門（2026-10-04）。

どちらも「やりすぎ」が害になる。再実行は中身の誤りで回すと同じ所で止まり続け、上限が無いと回り続ける。
再送は毎週同じURLを送ると、1日200件の枠を通知では直らないページに使い切る。
見本で「やるべき時にやり、やってはいけない時にやらない」ことを確かめる。
"""
import yaml

from test_gates import check, ROOT

WF = ROOT / ".github" / "workflows"


def test_ci_rerun_only_retries_transient_failures_once():
    import ci_rerun as C
    print("\n■ 落ちたCIの再実行は一時的な失敗だけ・1回まで（2026-10-04）")
    tail = lambda s: C.classify(C.log_tail(s))[0]
    check("検出器: 429 は一時的", tail("HTTP Error 429: Too Many Requests\n##[error]exit 1"), "transient")
    check("検出器: 接続が切れたのは一時的", tail("ConnectionResetError: Connection reset by peer\n##[error]exit 1"), "transient")
    check("検出器: ジョブの上限時間は一時的",
          tail("##[error]The job running on runner X has exceeded the maximum execution time of 100 minutes."), "transient")
    check("検出器: 配信先で「404になる」は中身の誤り（今日の実例）",
          tail("配信先のビルドが止まりました: /blog/x/ が404になる\n##[error]exit 1"), "permanent")
    check("検出器: 門に落ちたのは中身の誤り", tail("::error::門が通らないため公開しません\n##[error]exit 1"), "permanent")
    check("検出器: 管制塔の unauthorized は鍵の誤り（2026-09-25 の実例）",
          tail("→ 台帳から外せませんでした（unauthorized）\n##[error]exit 1"), "permanent")
    check("検出器: 存在しない版の依存は中身の誤り（2026-08-11 のデプロイ）",
          tail("npm error notarget No matching version found for miniflare@5\n##[error]3回ともデプロイ失敗"), "permanent")
    check("検出器: 429 と中身の誤りが並べば再実行しない側",
          tail("HTTP Error 429\nAssertionError\n##[error]exit 1"), "permanent")
    check("検出器: 理由の読めない失敗は再実行しない", tail("なにか\n##[error]exit 2"), "unknown")
    far = "Gemini 429 で飛ばしました\n" + "ok\n" * (C.TAIL + 5) + "なにか\n##[error]exit 1"
    check("検出器: 失敗より前の途中の 429 は理由に数えない", tail(far), "unknown")
    t = [("a", "transient", "")]
    check("1回目の一時的な失敗は再実行する", C.decide(1, False, t)[0], True)
    check("同じ run の2回目は再実行しない（無限に回さない）", C.decide(2, False, t)[0], False)
    check("後に同じワークフローの run があれば再実行しない（古いデプロイで上書きしない）", C.decide(1, True, t)[0], False)
    check("落ちたジョブの1つでも中身の誤りなら再実行しない",
          C.decide(1, False, t + [("b", "permanent", "")])[0], False)
    check("自己診断が通る", C.selftest(), 0)


def test_every_workflow_failure_is_handled():
    import ci_rerun as C
    print("\n■ どのワークフローが落ちても、直すか再実行するかのどちらかが動く")
    heal_src = (WF / "selfheal.yml").read_text(encoding="utf-8")
    y = yaml.safe_load(heal_src)
    trig = (y.get("on") or y.get(True) or {}).get("workflow_run") or {}
    watched = set(trig.get("workflows") or [])
    names = {yaml.safe_load(p.read_text(encoding="utf-8")).get("name")
             for p in WF.glob("*.yml") if p.name != "selfheal.yml"}
    check("selfheal 以外のワークフローを全部待ち受ける", sorted(names - watched), [])
    lists = C.watch_lists(heal_src)
    heal, rerun = set(lists.get("heal") or []), set(lists.get("rerun") or [])
    check("heal と rerun の一覧が起動条件から読める", bool(heal) and bool(rerun), True)
    check("待ち受けた名前は heal か rerun のどちらかが受け持つ", sorted(watched - heal - rerun), [])
    # 再実行すると記事を二重に書く・レポートやニュースレターを二重に送るものは rerun に入れない
    twice = {"Multi-Site Article Pipeline", "Article Pipeline (Rescue)", "Weekly Optimize",
             "Monthly Consulting Report", "Weekly Newsletter Digest"}
    check("二重に書く・送るワークフローは再実行しない", sorted(rerun & twice), [])
    job = y["jobs"]["rerun"]
    cond = " ".join(str(job.get("if")).split())
    check("再実行は失敗のときだけ（取り消しでは回さない）",
          "conclusion == 'failure'" in cond and "cancelled" not in cond, True)
    check("再実行の権限（actions: write）を rerun のジョブだけに付ける",
          (job.get("permissions") or {}).get("actions") == "write"
          and (y.get("permissions") or {}).get("actions") == "read", True)
    check("ワークフロー全体を直列にしない（heal の間に待った判定が取り消される）", "concurrency" in y, False)
    check("rerun は ci_rerun.py を呼ぶ", "scripts/ci_rerun.py" in str(job.get("steps")), True)


def absolute_roots(src):
    """ROOT をドライブ名からの絶対パスで書いた行。別の作業コピーから読み込むと、本体の scripts/ が
    sys.path の先頭に入り、それ以降の import が全部本体の古いモジュールになる"""
    import re
    return [l.strip() for l in src.splitlines() if re.match(r"\s*ROOT\s*=\s*Path\(r?[\"'][A-Za-z]:", l)]


def test_scripts_do_not_pin_the_repo_path():
    print("\n■ スクリプトの ROOT を手元の絶対パスで書かない（2026-10-04: worktree の門が本体のモジュールを読んだ）")
    check("検出器: ドライブ名からの ROOT を拾う",
          bool(absolute_roots('ROOT = Path(r"C:\\Users\\x\\repo")\n')), True)
    check("検出器: __file__ からの ROOT は拾わない",
          absolute_roots("ROOT = Path(__file__).resolve().parent.parent\n"), [])
    check("検出器: 出力先の絶対パス（ROOT 以外）は拾わない", absolute_roots('OUT = Path(r"C:\\Users\\x")\n'), [])
    bad = [f"{p.name}: {l}" for p in sorted((ROOT / "scripts").glob("*.py"))
           for l in absolute_roots(p.read_text(encoding="utf-8", errors="replace"))]
    check("scripts/ の ROOT はすべて __file__ から決める", bad, [])


def test_unindexed_pages_are_resent_without_repeating():
    import reindex as RX
    print("\n■ 未登録ページの再送: 直る見込みのある状態だけ・14日は送り直さない（2026-10-04）")
    ng = [("https://a.jp/x/", "検出 - インデックス未登録"),
          ("https://a.jp/y/", "Crawled - currently not indexed"),
          ("https://a.jp/z/", "URL が Google に認識されていません"),
          ("https://a.jp/d/", "重複しています。ユーザーにより、正規ページとして選択されていません"),
          ("https://a.jp/n/", "noindex タグによって除外されました"),
          ("https://a.jp/r/", "検出 - インデックス未登録")]
    go, recent, other = RX.resend_plan(ng, {"https://a.jp/r/": "2026-09-28"}, "2026-10-04")
    check("検出・クロール済みの未登録と、未認識を送る", [u for u, _ in go],
          ["https://a.jp/x/", "https://a.jp/y/", "https://a.jp/z/"])
    check("14日以内に送ったURLは送らない", [u for u, _ in recent], ["https://a.jp/r/"])
    check("重複・noindex は通知では直らないので送らない", [u for u, _ in other], ["https://a.jp/d/", "https://a.jp/n/"])
    go, recent, _ = RX.resend_plan(ng, {"https://a.jp/r/": "2026-09-19"}, "2026-10-04")
    check("15日たてば送り直す", "https://a.jp/r/" in [u for u, _ in go], True)
    check("1回の上限で切る（1日200件の枠を使い切らない）", len(RX.resend_plan(ng, {}, "2026-10-04", 2)[0]), 2)
    check("上限は Indexing API の1日200件の半分以下", RX.RESEND_MAX <= 100, True)
    import inspect
    src = inspect.getsource(RX._publish)
    check("Indexing API と IndexNow の両方へ送る", "urlNotifications" in src and "_indexnow(" in src, True)
    check("送れたURLだけ日付を残す", "sent.update({u: today for u in done})" in src, True)
    wk = (WF / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次が送った日の記録を残す（残さないと毎週同じURLを送る）", "data/index_resend.json" in wk, True)
    check("週次は検査の結果から再送する", "reindex.py --from-cache" in wk, True)
