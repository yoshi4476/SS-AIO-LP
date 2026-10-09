# -*- coding: utf-8 -*-
"""2026-10-10 GitHub Actions の実行時間を縮めた（品質・動きは変えず、無駄だけを削る）。
直近6日の job の時間（research-refill を除く）1,377分のうち、削れたのは次の無駄だった。
- 配信（deploy.yml）: 147回のうち68回は新しいファイルが0本なのに毎回送っていた。準備も順に待っていた
- 記事の枠の判定（select）: 1日約50回、使わない画像・動画まで 334MB を取っていた（取得に平均12秒）
- 記事の前の確認: ブリーフ（平均35秒）と横断のカニバリ検査（平均39秒）を順に待っていた
- 週次の findings: 検査を1本ずつ待ち、URL検査（約13分）を同じ週次の中で2回繰り返していた（32分）
ここでは、その短縮が「省いてはいけないもの」まで省かないことを守る。
"""
import json
import re
import sys
import tempfile
from pathlib import Path

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
WF = ROOT / ".github" / "workflows"


def _y(name):
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _on(y):
    return y.get("on", y.get(True))


def _step(job, name_part):
    for s in job["steps"]:
        if name_part in str(s.get("name", "")):
            return s
    return None


def test_deploy_skips_only_identical_output():
    print("\n■ 配信: 本番と同じ中身のときだけ送り出しを省く（作り直しと門は省かない）")
    import deploy_marker as M
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "site" / "a").mkdir(parents=True)
        (root / "functions" / "api").mkdir(parents=True)
        (root / "site" / "index.html").write_text("top", encoding="utf-8")
        (root / "site" / "a" / "index.html").write_text("a", encoding="utf-8")
        (root / "functions" / "api" / "x.js").write_text("export const x=1", encoding="utf-8")
        h0 = M.fingerprint(root, "wrangler@1")
        (root / "site" / M.NAME).write_text(h0, encoding="utf-8")
        check("指紋のファイル自身は指紋に数えない", M.fingerprint(root, "wrangler@1"), h0)
        check("wrangler の版が変われば別の指紋（送り直す）", M.fingerprint(root, "wrangler@2") != h0, True)
        (root / "site" / "a" / "index.html").write_text("b", encoding="utf-8")
        check("ページの中身が1文字変われば別の指紋", M.fingerprint(root, "wrangler@1") != h0, True)
        (root / "site" / "a" / "index.html").write_text("a", encoding="utf-8")
        (root / "site" / "a" / "index.html").rename(root / "site" / "a" / "page.html")
        check("ファイル名が変われば別の指紋（消えたページも送り直す）", M.fingerprint(root, "wrangler@1") != h0, True)
        (root / "site" / "a" / "page.html").rename(root / "site" / "a" / "index.html")
        (root / "functions" / "api" / "x.js").write_text("export const x=2", encoding="utf-8")
        check("functions/ が変われば別の指紋", M.fingerprint(root, "wrangler@1") != h0, True)

    import urllib.request

    class Resp:
        def __init__(self, body):
            self.body = body.encode("utf-8")

        def read(self, n=-1):
            return self.body[:n] if n and n > 0 else self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    orig = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda *a, **k: Resp("<!doctype html><html>404</html>")
        check("本番に指紋が無い（404のページ）なら送る", M.live("https://x.example")[0], "")
        urllib.request.urlopen = lambda *a, **k: Resp("a" * 64)
        check("指紋の形なら本番の指紋として読む", M.live("https://x.example")[0], "a" * 64)

        def boom(*a, **k):
            raise OSError("down")
        urllib.request.urlopen = boom
        check("本番を読めなければ送る", M.live("https://x.example")[0], "")
    finally:
        urllib.request.urlopen = orig

    y = _y("deploy.yml")
    job = y["jobs"]["deploy"]
    build = _step(job, "原稿から作り直す")["run"]
    dep = _step(job, "Cloudflare Pagesへデプロイ")["run"]
    check("作り直しは毎回する（省くのは送り出しだけ）",
          ("python scripts/build.py" in build, _step(job, "原稿から作り直す").get("if")), (True, None))
    check("日本語フォントを入れ終えてから作り直す", build.find("wait $apt") < build.find("python scripts/build.py"), True)
    check("先に取った wrangler は工程の中で待ち終える（次の工程と同じ取り置きを同時に書かない）", "wait $wr" in build, True)
    i_gate, i_same = dep.find("seo_audit.py --gate"), dep.find("deploy_marker.py --same")
    i_write, i_deploy = dep.find("deploy_marker.py --write"), dep.find("pages deploy site")
    check("公開前の門は比べる前に通す", 0 <= i_gate < i_same, True)
    check("省くのは SAME=yes のときだけ", "grep -q '^SAME=yes'" in dep, True)
    check("指紋は送り出しの直前に置く", 0 <= i_same < i_write < i_deploy, True)
    check("手で force を付けた回は必ず送る", ("force" in (_on(y)["workflow_dispatch"] or {}).get("inputs", {}),
                                    'inputs.force }}" != "true"' in dep), (True, True))
    check("比べる相手は本番（production）の pages.dev", "--same https://ss-aio-lp.pages.dev --salt wrangler@4.121.0" in dep, True)
    check("鍵の設定は省いた回以外は今までどおり", dep.count("pages secret put") == 1 and "for k in GEMINI_API_KEY" in dep, True)
    check("指紋のファイルはコミットしない", "site/deploy-hash.txt" in (ROOT / ".gitignore").read_text(encoding="utf-8"), True)
    check("最後の push を必ず配る（進行中の古い回を取り消して新しい回が送る）",
          (y["concurrency"]["group"], y["concurrency"]["cancel-in-progress"]), ("cf-pages-deploy", True))
    pm = _y("pipeline-multi.yml")["jobs"]["write"]
    own = _step(pm, "Cloudflare Pagesへデプロイ（自前ビルドのサイトのみ）")["run"]
    check("記事の枠の送り出しも同じ版の指紋を置く（後の deploy.yml が同じ中身なら省ける）",
          0 <= own.find("deploy_marker.py --write --salt wrangler@4.121.0") < own.find("pages deploy site"), True)


def test_pages_do_not_depend_on_file_order():
    print("\n■ 作り直し: 同じ原稿からは毎回同じページになる（並びをファイルの順に任せない）")
    # 2026-10-10 同じコミットを2回作り直すと /compare/ の2ページだけ違った（同じ日付の表の並びが
    # ランナーごとのファイルの並びで変わる）。同じ中身なら送り出しを省く仕組みが効かず、毎回送り直していた
    for f in ("compare_pages.py", "glossary.py", "season_feature.py"):
        src = (ROOT / "scripts" / f).read_text(encoding="utf-8")
        check(f"{f} は記事を名前順に読む", ('sorted((ROOT / "articles").glob("*.md"))' in src,
                                          'in (ROOT / "articles").glob("*.md"):' in src), (True, False))
    # 集合の並びは実行ごとに変わる（PYTHONHASHSEED）。一部の鍵だけで並べると、同じ値どうしの順が毎回変わる。
    # 2026-10-10 PYTHONHASHSEED を 1・2・3 にして作り直すと /compare/aio/・/compare/meo/ の説明文が毎回違った
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("build.py は集合を一部の鍵だけで並べない（sorted({...}, key=...)）",
          re.findall(r"sorted\(\{[^}]*\}, *key=", src), [])


def test_publish_gap_does_not_redeliver_delivered_noindex():
    print("\n■ 未配信の確認: 検索から外した記事は、配信の指紋が同じなら配信し直さない（違えば配信する）")
    # 2026-10-10 noindex の19本（corporate 10・subsidy 9）は sitemap に載らないため毎回「未配信」になり、
    # 記事の枠のたびに配信し直していた（この工程だけで平均118秒×6日で39回）。どれも配信の指紋は一致していた
    import publish_gap as PG
    hidden = {"hid-same", "hid-diff", "hid-none"}.__contains__
    man = {"hid-same": "aaa", "hid-diff": "old", "open": "bbb"}
    hashes = {"hid-same": "aaa", "hid-diff": "new", "hid-none": "ccc", "open": "zzz"}
    missing = ["hid-same", "hid-diff", "hid-none", "open"]
    check("指紋が今の原稿と同じ noindex の記事だけを届いているとみなす",
          PG.hidden_delivered(missing, man, hashes, hidden), ["hid-same"])
    check("指紋を読めないサイトでは今までどおり全部配信する", PG.hidden_delivered(missing, None, hashes, hidden), [])
    check("検索に出す記事は sitemap に無ければ配信する（指紋が同じでも）",
          PG.hidden_delivered(["open"], {"open": "zzz"}, hashes, hidden), [])
    src = (ROOT / "scripts" / "publish_gap.py").read_text(encoding="utf-8")
    check("配信先の指紋を読んだ後で、未配信から外す",
          0 <= src.find("man = live_manifest_wp(c)") < src.find("hidden_ok = hidden_delivered(missing, man"), True)


def test_select_skips_only_big_unused_dirs():
    print("\n■ 記事の枠の判定: 使わない大きな置き場だけ取らない（判定が読むものは取る）")
    sel = _y("pipeline-multi.yml")["jobs"]["select"]
    co = sel["steps"][0]
    w = co.get("with") or {}
    pats = [l.strip() for l in str(w.get("sparse-checkout") or "").splitlines() if l.strip()]
    check("最初の工程が checkout", co.get("uses"), "actions/checkout@v4")
    check("除外の書き方（全部を取ってから外す）", (w.get("sparse-checkout-cone-mode"), pats[:1]), (False, ["/*"]))
    check("外すのは画像・動画・資料・レポート・写真の原本だけ",
          sorted(pats[1:]), sorted(["!/site/images/", "!/site/videos/", "!/assets/", "!/reports/", "!/写真素材/"]))
    needed = ["scripts", "sites", "data", "articles", ".github"]
    check("判定が読む置き場は外さない", [n for n in needed if any(p.startswith(f"!/{n}") for p in pats)], [])
    src = "\n".join((ROOT / "scripts" / f).read_text(encoding="utf-8") for f in
                    ("sched_guard.py", "site_order.py", "daily_audit.py", "pace.py", "schedule_guard.py",
                     "scheduler_build.py", "sites.py"))
    check("判定の道具が外した置き場を読まない",
          [d for d in ("site/images", "site/videos", "写真素材", "\"assets\"", "'reports'", "\"reports\"") if d in src], [])
    write = _y("pipeline-multi.yml")["jobs"]["write"]
    check("記事を書く job は全部を取る（画像の検査・配信に要る）",
          (write["steps"][0].get("uses"), (write["steps"][0].get("with") or {}).get("sparse-checkout")),
          ("actions/checkout@v4", None))


def test_brief_and_cross_check_run_together_but_log_in_order():
    print("\n■ 記事の前の確認: ブリーフと横断の検査を同時に始め、brief.txt には今までの順で書く")
    write = _y("pipeline-multi.yml")["jobs"]["write"]
    brief = _step(write, "執筆ブリーフの表示")["run"]
    cross = _step(write, "全サイト横断のカニバリ・領域チェック")["run"]
    check("横断の検査をブリーフより先に裏で始める",
          0 <= brief.find("cannibal_check.py --cross > /tmp/cannibal.txt") < brief.find("site_brief.py"), True)
    check("裏の検査は工程の出力をつかまない（工程の終わりを待たせない）", "< /dev/null > /dev/null 2>&1 &" in brief, True)
    check("ブリーフは brief.txt を作り直す（tee）", "| tee automation/logs/brief.txt" in brief, True)
    check("横断の結果は見出しの後に書き足す",
          0 <= cross.find('echo "■ python scripts/cannibal_check.py --cross の結果"') < cross.find("tee -a automation/logs/brief.txt"), True)
    check("終わるまで待つ（印のファイル）", "/tmp/cannibal.rc" in cross, True)
    check("始まっていなければその場で動かす（取りこぼさない）", "python scripts/cannibal_check.py --cross 2>&1 | tee -a" in cross, True)
    check("同じ条件で動く（片方だけ動くことが無い）", _step(write, "執筆ブリーフの表示")["if"], _step(write, "全サイト横断のカニバリ・領域チェック")["if"])
    names = [s.get("name", "") for s in write["steps"]]
    check("食い合いゲートは横断の検査の後（台帳を書き換えうるので並べない）",
          names.index("全サイト横断のカニバリ・領域チェック") < names.index("食い合いゲート（執筆前）")
          < names.index("一次情報の収集（YouTube文字起こし）"), True)


def test_selfheal_starts_runners_only_when_needed():
    print("\n■ 自動修復: 成功した回のあとは runner を立てない（失敗の見張りは残す）")
    y = _y("selfheal.yml")
    heal, rerun = str(y["jobs"]["heal"]["if"]), str(y["jobs"]["rerun"]["if"])
    check("heal は失敗・取り消しのときだけ（定時と手動は別）",
          all(s in heal for s in ("workflow_run.conclusion == 'failure'", "workflow_run.conclusion == 'cancelled'",
                                   "github.event.schedule == '0 15 * * *'", "workflow_dispatch")), True)
    check("rerun は失敗のときだけ", "github.event.workflow_run.conclusion == 'failure'" in rerun, True)
    check("見張りの役目（取りこぼしの起動）は定時に残る", "schedule" in str(y["jobs"]["schedule-guard"]["if"]), True)


def test_weekly_inspection_is_not_repeated():
    print("\n■ 週次: URL検査を同じ週次の中で2回しない・遅い検査は同時に始める（順と判定は同じ）")
    import pace as P
    import index_status as IX
    calls = []

    class Req:
        def __init__(self, url):
            self.url = url

        def execute(self):
            calls.append(self.url)
            if self.url.endswith("/bad/"):
                raise RuntimeError("quota")
            return {"inspectionResult": {"indexStatusResult": {"coverageState": "Submitted and indexed"}}}

    class Client:
        def urlInspection(self):
            return self

        def index(self):
            return self

        def inspect(self, body):
            return Req(body["inspectionUrl"])

    with tempfile.TemporaryDirectory() as d:
        cache = Path(d) / "c.json"
        o_client, o_sm, o_path = IX.client, P._sitemap, P._inspect_cache_path
        try:
            IX.client = lambda: Client()
            P._sitemap = lambda dom: {}
            P._inspect_cache_path = lambda: cache
            cfg = {"domain": "x.example"}
            paths = [f"/p{i}/" for i in range(10)] + ["/bad/"]
            r1 = P.coverage(cfg, paths, now=1000.0)
            check("結果は渡した順（同時に投げても）", list(r1), paths)
            check("1回目は全部を検査する", len(calls), 11)
            check("失敗は失敗として返す", r1["/bad/"].startswith("ERROR"), True)
            calls.clear()
            r2 = P.coverage(cfg, paths, now=1000.0 + 3600)
            check("6時間以内の2回目は検査し直さない（失敗したものだけ聞き直す）", calls, ["https://x.example/bad/"])
            check("2回目も同じ結果", {k: v for k, v in r2.items() if k != "/bad/"},
                  {k: v for k, v in r1.items() if k != "/bad/"})
            calls.clear()
            P.coverage(cfg, paths, now=1000.0 + P.INSPECT_TTL + 1)
            check("6時間を過ぎたら検査し直す", len(calls), 11)

            def no_key():
                raise FileNotFoundError("indexing-service-account.json")
            IX.client = no_key
            try:
                P.coverage(cfg, ["/z/"], now=1.0)
                got = "通った"
            except FileNotFoundError:
                got = "止まる"
            check("鍵が無いときは今までどおり止まる（呼び出し側が『測れません』にする）", got, "止まる")
        finally:
            IX.client, P._sitemap, P._inspect_cache_path = o_client, o_sm, o_path
    check("控えは一時フォルダ（お客様の URL を public のリポジトリに置かない）",
          str(P._inspect_cache_path()).startswith(tempfile.gettempdir()), True)

    import findings as F
    scripts = [s for _, s, _ in F.CHECKS]
    check("同時に始める検査はどれも一覧にある", sorted(F.PARALLEL - set(scripts)), [])
    writers = re.compile(r"write_text\(|json\.dump\(|\.open\([^)]*['\"][wa]")
    bad = [s for s in F.PARALLEL if writers.search((ROOT / "scripts" / s.split()[0]).read_text(encoding="utf-8"))
           and s.split()[0] != "pace.py"]
    check("同時に始める検査はファイルを書かない（pace は --write の時だけ書く）", bad, [])
    pace_src = (ROOT / "scripts" / "pace.py").read_text(encoding="utf-8")
    check("pace は --write の時だけ判定を残す", "if a.write:\n        # お客様の社の兆候" in pace_src, True)
