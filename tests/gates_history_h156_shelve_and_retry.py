"""h156: 下書きをしまう記録にお客様の slug を公開側へ書かない・書き直しの回も AI が対象のサイトを読める・書けない語を AI が飛ばせる。

2026-11-03: しまう処理が原稿を移した後で社を調べ、社が空の行としてお客様の slug が data/quality_loop.jsonl（public）に載った。
2026-11-05: 他社名の語を AI が断り、書き直しの回はブリーフが消えていて対象のサイトが分からず、別のサイトの記事を書いて機械に取り消された。
飛ばす道具も無く、次の回も同じ語が出た"""
import json
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT


def test_shelve_decides_the_owner_before_moving():
    sys.path.insert(0, str(ROOT / "scripts"))
    import client_private as CP
    import quality_loop as Q
    print("\n■ 下書きをしまう: 社は原稿を移す前に決め、お客様の行を公開側へ書かない")
    with tempfile.TemporaryDirectory() as d:
        arts = Path(d) / "articles"
        arts.mkdir()
        (arts / "zz-draft.md").write_text("---\ncategory: zz-blog\n---\n本文\n", encoding="utf-8")
        saved = Q.ARTICLES, Q.site_of, Q.unused_materials, Q.rows, Q.record
        got = []
        try:
            Q.ARTICLES = arts
            # 本物と同じく、原稿が置き場に無ければ社は分からない
            Q.site_of = lambda slug: "client-zz" if (arts / f"{slug}.md").is_file() else ""
            Q.unused_materials = lambda slug: []
            Q.rows = lambda path=None: [{"slug": "zz-draft", "action": "hold", "need": "materials"}] * Q.SHELVE_AFTER
            Q.record = got.append
            check("しまえた", Q.shelve("zz-draft"), True)
        finally:
            Q.ARTICLES, Q.site_of, Q.unused_materials, Q.rows, Q.record = saved
        check("記録の社は移す前の社", [r["site"] for r in got], ["client-zz"])
        check("原稿は _held へ移った", (arts / Q.SHELF / "zz-draft.md").is_file(), True)
    print("\n■ 持ち主の判定: しまった下書きの slug も社が分かる")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "articles" / "_held").mkdir(parents=True)
        (root / "articles" / "_held" / "zz-held.md").write_text("---\ncategory: zz-blog\n---\n", encoding="utf-8")
        saved_root, saved_find = CP.ROOT, CP.S.find_category_owner
        try:
            CP.ROOT = root
            CP.S.find_category_owner = lambda c: "client-zz" if c == "zz-blog" else None
            check("_held の原稿から社を読む", CP.owner_of_slug("zz-held"), "client-zz")
            check("どこにも無ければ None", CP.owner_of_slug("zz-none"), None)
        finally:
            CP.ROOT, CP.S.find_category_owner = saved_root, saved_find


def test_retry_rebuilds_the_brief():
    print("\n■ 記事生成の書き直しの回: ブリーフを消したままにしない")
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    at = wf.find('rm -f automation/logs/brief.txt')
    tail = wf[at:at + 500]
    check("消した直後に作り直し、ログには出さない",
          'python scripts/site_brief.py "$SITE_ID" > automation/logs/brief.txt 2>&1' in tail, True)


def test_writer_can_skip_a_keyword_it_cannot_answer():
    import kw_fit
    import hub_client as H
    print("\n■ 書けない語: AI が取り下げて次の語へ進める・同じ種類の語は入口で止める")
    calls = []
    saved = H.enabled, H.retire_kw, sys.argv
    try:
        H.enabled = lambda: True
        H.retire_kw = lambda site, kws, why: calls.append((site, kws, why)) or {"ok": True, "retired": 1}
        sys.argv = ["hub_client.py", "retire", "corporate", "架空社 記帳代行", "他社の", "名前"]
        H.main()
    finally:
        H.enabled, H.retire_kw, sys.argv = saved
    check("retire は1語だけを渡す", calls, [("corporate", ["架空社 記帳代行"], "他社の 名前")])
    prompt = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("指示書に飛ばし方と上限がある",
          ("hub_client.py retire" in prompt, "1回の実行で3語まで" in prompt), (True, True))
    settings = json.loads((ROOT / "automation" / "agent_settings_article.json").read_text(encoding="utf-8"))
    check("AI の許可の一覧で hub_client が通る", "Bash(python scripts/hub_client.py *)" in settings["permissions"]["allow"], True)
    kw_fit._rules.cache_clear()
    bad = ["アーバン 記帳代行", "株式会社ビジョン 記帳代行", "横浜経理専門学校", "2級建設業経理士 過去問", "ドコモ請求書",
           "ハーモス 経費精算", "invox経費精算", "経理の夏谷さんはガマンできない"]
    good = ["記帳代行 費用", "バックオフィス 外注", "月次決算 早期化 メリット", "建設業の経理", "請求書 テンプレート 個人事業主"]
    check("悪い例は止める", [k for k in bad if kw_fit.judge(k, "corporate")[0] < 2], [])
    check("良い例は通す", [k for k in good if kw_fit.judge(k, "corporate")[0] >= 2], [])


def test_local_push_does_not_send_stale_articles():
    import private_store as PS
    print("\n■ 非公開の置き場への送信: 手元の古い写しの原稿を送らない（CI でだけ作業場所の原稿を残す）")
    calls = []
    saved = PS.overlay_out, PS._git, PS.base, PS._token
    env = PS.os.environ.get("GITHUB_ACTIONS")

    class _R:
        returncode = 0
        stdout = stderr = ""

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / ".git").mkdir()
        try:
            PS.overlay_out = lambda unstage=True: calls.append("overlay")
            PS._git = lambda *a, **k: _R()
            PS.base = lambda: Path(d)
            PS._token = lambda: ""
            PS.os.environ.pop("GITHUB_ACTIONS", None)
            PS.push("t")
            check("手元では原稿を重ねない", calls, [])
            PS.os.environ["GITHUB_ACTIONS"] = "true"
            PS.push("t")
            check("CI では今までどおり重ねる", calls, ["overlay"])
        finally:
            PS.overlay_out, PS._git, PS.base, PS._token = saved
            PS.os.environ.pop("GITHUB_ACTIONS", None)
            if env is not None:
                PS.os.environ["GITHUB_ACTIONS"] = env
