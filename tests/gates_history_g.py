# -*- coding: utf-8 -*-
"""Git を使わない配信先（レンタルサーバーの FTP・ZIP 納品）の門（2026-10-04）。

配信方式を足すときに漏れやすいのは、書き出しより周り（形式の一覧・CI に渡す鍵・公開の照合）。
1か所でも抜けると「登録はできるが CI で配信されない」「毎日同じ ZIP を作り直す」になる。
"""
import json
import re
import tempfile
from pathlib import Path

from test_gates import check, ROOT


def test_file_delivery_types_are_wired():
    import client_add
    import deliver_files as DF
    for t in DF.TYPES:
        check(f"配信方式 {t} が形式の一覧にある", t in client_add.TYPES, True)
        check(f"配信方式 {t} をヒアリングシートで選べる",
              t in (ROOT / "scripts" / "client_intake.py").read_text(encoding="utf-8").split("DataValidation(type=\"list\", formula1='\"wordpress")[1].split("'")[0], True)

    # 原稿（.md）と作業用の雛形は相手のサーバーに上げない。記事は接頭辞の場所へ移す
    with tempfile.TemporaryDirectory() as d:
        base = Path(d)
        page = base / "blog" / "x" / "index.html"
        page.parent.mkdir(parents=True)
        page.write_text('<a href="/blog/y/">y</a>', encoding="utf-8")
        (base / "_src").mkdir()
        (base / "_src" / "x.md").write_text("a", encoding="utf-8")
        (base / "_template.html").write_text("t", encoding="utf-8")
        got = DF.files_of([page, base / "_src" / "x.md", base / "_template.html"], base, "/column")
        check("FTP/ZIP は原稿と雛形を上げない", [r for _, r in got], ["column/x/index.html"])
        check("FTP/ZIP は記事内の関連リンクも接頭辞に合わせる", 'href="/column/y/"' in page.read_text(encoding="utf-8"), True)

    # 汎用の雛形は write_external_html が埋める名前と、作業場所で埋める3つだけを使う
    tpl = (ROOT / "templates" / "external_article.html").read_text(encoding="utf-8")
    pub = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    vals = set(re.findall(r'^\s+"([A-Z_]+)": ', pub.split("vals = {", 1)[1].split("\n    }", 1)[0], re.M))
    left = set(re.findall(r"\{\{([A-Z_]+)\}\}", tpl)) - vals - {"SITE_NAME", "ORIGIN", "PREFIX"}
    check("汎用の雛形に埋まらない差し込みが無い", sorted(left), [])

    # 配信する工程（SITE_PUSH_TOKEN を渡す工程）には、FTP・WordPress の接続情報も渡す
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        s = wf.read_text(encoding="utf-8")
        n = s.count("SITE_PUSH_TOKEN: ${{ secrets.SITE_PUSH_TOKEN }}")
        check(f"{wf.name}: 配信の工程に FTP の接続情報を渡している",
              s.count("FTP_CREDENTIALS_JSON: ${{ secrets.FTP_CREDENTIALS_JSON }}") >= n, True)
        check(f"{wf.name}: 配信の工程に WordPress の接続情報を渡している",
              s.count("WP_CREDENTIALS_JSON: ${{ secrets.WP_CREDENTIALS_JSON }}") >= n, True)

    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("FTP の接続情報と ZIP 納品物はコミットしない", "ftp-credentials.json" in gi and "deliveries/" in gi, True)
    check("ZIP 納品は未配信の照合から外す（毎日作り直さない）",
          'c.get("type") == "zip"' in (ROOT / "scripts" / "publish_gap.py").read_text(encoding="utf-8"), True)


def test_site_changes_reach_file_delivery():
    """記事の配信だけでなく、サイト改修（取り下げと301・全記事の描き直し・メニュー・訳のページ）も
    FTP・ZIP・WordPress の社に届く。Git の作業コピー前提の道具は、ここで落ちていた（2026-10-04）"""
    src = lambda n: (ROOT / "scripts" / n).read_text(encoding="utf-8")
    check("取り下げ（統合の301）が FTP・ZIP の社を扱う", "deliver_files.retract" in src("retract.py"), True)
    check("取り下げが WordPress の社を扱う（下書きに戻す）", '"status": "draft"' in src("retract.py"), True)
    check("全記事の描き直しが FTP・ZIP の社を扱う", "DF.deliver_batch" in src("publish_rerender.py"), True)
    check("多言語メニューが FTP・ZIP の社に届く", '("ftp", "zip")' in src("menu_page.py"), True)
    check("訳のページを書いたものとして返す（FTP・ZIP は返したものだけ届ける）",
          'written += [dest / lg / pre / meta["slug"] for lg in extra["langs"]]' in src("publish.py"), True)


def test_subsidy_facts_are_on_topic_and_allowed():
    """補助金サイトの記事に渡す一次情報は、主題に合い、方針で載せない数字（支援社数・採択率）を含まない。
    一次データは公開のたびに全サイトへ登録されるため、MEO の店舗数や「のべ50社を支援」が
    補助金の記事に渡り、採点でも主題外と減点されていた（2026-10-04）"""
    import facts as F
    _, fs = F.load_for("subsidy")
    text = " ".join(f.get("claim", "") for f in fs)
    check("補助金サイトの一次情報に支援社数・採択率が無い", re.findall(r"\d+社以上|採択率", text), [])
    check("補助金サイトの一次情報に MEO の店舗数が無い", re.findall(r"[0-9][0-9,]*店舗", text), [])

    import subsidy_survey as SV
    # 調査の文は、母数（回答数）と時期を必ず含む。回答が少なければ書かない
    rec = {"slug": "x", "date": "2026-10-04", "engines": ["A", "B", "C"], "questions": ["q1", "q2", "q3"],
           "answers": {f"q{i}": {e: {"urls": ["https://it-shien.smrj.go.jp/a", "https://example.co.jp/b"], "error": ""}
                                 for e in "ABC"} for i in (1, 2, 3)}}
    t = SV.tally(rec)
    check("調査の集計: 9回答・公的機関を根拠にしたのは9", (t["answers"], t["with_public"]), (9, 9))
    check("調査の分類: smrj.go.jp は公的機関・当社ドメインは当社", (SV.kind("it-shien.smrj.go.jp"), SV.kind("lp.7senses.co.jp")),
          ("public", "own"))


def test_survey_classifier_reads_neighbors_right():
    """分類はドメインの末尾で見る。部分一致だと hojokin-dx.com を SNS（x.com）と数えた（2026-10-04 の実データ）"""
    import subsidy_survey as SV
    check("調査の分類: 紛らわしいドメイン",
          [SV.kind(d) for d in ("hojokin-dx.com", "x.com", "it-shien.example.com", "chusho.meti.go.jp", "j-aix.or.jp")],
          ["private", "media", "private", "public", "private"])
    rec = {"answers": {"q": {"G": {"urls": ["https://vertexaisearch.cloud.google.com/grounding-api-redirect/x"], "error": ""}}}}
    check("調査の集計: 行き先の分からない転送URLだけの回答は数えない", SV.tally(rec)["answers"], 0)


def test_site_change_stays_in_its_own_repo_and_wp_roundtrip():
    """サイト構成の変更（site_change）は作業場所の .git だけを使う。壊れた .git があると git が親の
    管制塔リポジトリまでさかのぼり、本体に無関係なファイルを4,821件コミットした（2026-10-04 の試験。push 前に取り消し）。
    WordPress は取った値を書き戻し、先方が後から変えたものは上書きしない"""
    import subprocess as sp
    import tempfile
    import site_change as C
    with tempfile.TemporaryDirectory() as d:
        parent = Path(d)
        sp.run(["git", "init", "-q", str(parent)], check=True)
        sp.run(["git", "-C", str(parent), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], check=True)
        m = parent / "work" / "x-site"
        (m / ".git").mkdir(parents=True)              # 壊れた .git（HEAD が無い）
        (m / "a.html").write_text("a", encoding="utf-8")
        C.snapshot(m, "取得")
        n = sp.run(["git", "-C", str(parent), "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout.strip()
        check("作業場所の記録が親リポジトリに入らない", n, "1")
        (m / "a.html").write_text("b", encoding="utf-8")
        check("作業場所の変化だけを数える", C.changes(m), [("M", "a.html")])

        # 偽の WordPress（REST API の形だけ真似る）で、取る→直す→反映→先方の変更で止まる を確かめる
        store = {"pages/1": {"id": 1, "title": {"raw": "会社概要"}, "content": {"raw": "旧"}, "slug": "about", "status": "publish"}}
        calls = []

        def fake(cfg, path, data=None, method=None):
            calls.append((path, data, method))
            if path.startswith("pages?"):
                return [store["pages/1"]]
            if path.startswith(("menus?", "menu-items?", "navigation?", "templates?", "template-parts?")):
                return []
            if path == "settings" and data is None:
                return {"title": "テスト社", "description": ""}
            if path.startswith("themes"):
                return []
            if path.startswith("pages/1") and data is None:
                return store["pages/1"]
            if path == "pages/1":
                store["pages/1"]["content"]["raw"] = data["content"]
                return store["pages/1"]
            return {}
        orig, orig_routes = C._wp, C._wp_routes
        C._wp, C._wp_routes = fake, (lambda cfg: set())
        cfg = {"id": "zz-wp", "type": "wordpress"}
        orig_mirror = C.mirror
        C.mirror = lambda c: parent / "work" / "wp-site"
        try:
            C.wp_pull(cfg)
            w = parent / "work" / "wp-site"
            p = w / "pages" / "1.json"
            rec = json.loads(p.read_text(encoding="utf-8"))
            rec["content"] = "新"
            p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            C.wp_push(cfg, C.changes(w))
            check("WordPress: 直した固定ページが反映される", store["pages/1"]["content"]["raw"], "新")
            C.snapshot(w, "反映")
            store["pages/1"]["content"]["raw"] = "先方が管理画面で直した"
            rec["content"] = "さらに新"
            p.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
            try:
                C.wp_push(cfg, C.changes(w))
                stopped = False
            except SystemExit:
                stopped = True
            check("WordPress: 先方が後から変えた固定ページは上書きしない", (stopped, store["pages/1"]["content"]["raw"]),
                  (True, "先方が管理画面で直した"))
        finally:
            C._wp, C._wp_routes, C.mirror = orig, orig_routes, orig_mirror
