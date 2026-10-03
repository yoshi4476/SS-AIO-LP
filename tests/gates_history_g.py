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


def test_ai_check_cannot_be_abused():
    """サイトの AI診断は、架空のメールアドレスで何度でも申し込め、台帳に届かないと上限が効かなかった。
    検索つきの Gemini は有料（無料枠では使えない）なので、回線ごとの回数・月の検索回数・ロボットよけを必ず通す（2026-10-04）"""
    js = (ROOT / "functions" / "api" / "ai-check.js").read_text(encoding="utf-8")
    gs = (ROOT / "automation" / "gas" / "contact.hub.gs").read_text(encoding="utf-8")
    check("AI診断: 台帳に届かないときは受け付けない", "if (!quota || !quota.ok)" in js, True)
    check("AI診断: 回線（IP）を台帳に渡す", "CF-Connecting-IP" in js and "ip })" in js, True)
    check("AI診断: 実際の検索回数を数えて残す", "webSearchQueries" in js and "searches," in js, True)
    check("AI診断: ロボットよけの確認がある", "turnstile/v0/siteverify" in js, True)
    check("AI診断: 同じ回線から1日2回・月の検索5,000回", ("AI_CHECK_PER_IP_DAY = 2" in gs, "AI_CHECK_MONTH_SEARCHES = 5000" in gs),
          (True, True))


def test_gemini_is_metered_by_searches():
    """検索つきの Gemini は無料枠で使えない。呼ぶ前に台帳で月の検索回数の残りを確かめ、呼んだら実際の検索回数を残す。
    量の多い業種調査（月約1,700問）が使う「課金しない聞き方」には入れない（2026-10-04: 4日で約1,800問・¥5,000の請求）"""
    src = (ROOT / "scripts" / "ai_cite_check.py").read_text(encoding="utf-8")
    ask = src.split("def ask_gemini(q):", 1)[1].split("\ndef ", 1)[0]
    sub = src.split("def subscription_engines():", 1)[1].split("\ndef ", 1)[0]
    check("Gemini: 呼ぶ前に残りを確かめる", "gemini_budget_ok()" in ask, True)
    check("Gemini: 実際の検索回数を残す", "webSearchQueries" in ask and "gemini_note(" in ask, True)
    check("Gemini: 業種調査の聞き方（subscription_engines）に入れない", "ask_gemini" in sub, False)
    rc = (ROOT / "scripts" / "ai_recheck.py").read_text(encoding="utf-8")
    check("Gemini: 1か月後の測り直しも同じ台帳で数える", "gemini_budget_ok()" in rc and "gemini_note(" in rc, True)


def test_rewrite_targets_measurable_and_parallel_keeps_checks():
    """週次の書き直しは、順位とクリックで効いたかを測れる記事に使う（採点だけを理由にした書き直しは入れない）。
    並列は案を書かせるところだけで、当てて検算するのは1本ずつ（run_one(edited=…)）"""
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    tg = src.split("def targets():", 1)[1].split("\ndef ", 1)[0]
    check("書き直しの対象に採点だけの記事（audit_items）を入れない", "audit_items()" in tg, False)
    ro = src.split("def run_one(item, write, edited=None):", 1)[1].split("\ndef ", 1)[0]
    check("並列の案も、当てた後に同じ検算（check）を通す", "edited" in ro and "check(slug" in ro, True)
    fn = (ROOT / "scripts" / "funnel.py").read_text(encoding="utf-8")
    check("ファネルの送信は問い合わせの数え方（lead_reconcile）に揃える", "LR.ga4_by_day" in fn, True)


def test_ai_check_funnel_is_wired():
    """AI診断のファネル（F1〜F5）: 結果に合わせた次の一歩・出典の上位をメールに・同意した人だけ3日後・
    文字リンクも計測・段階ごとの数を週次で出す（2026-10-04）"""
    js = (ROOT / "site" / "js" / "ai-check.js").read_text(encoding="utf-8")
    fn = (ROOT / "functions" / "api" / "ai-check.js").read_text(encoding="utf-8")
    gs = (ROOT / "automation" / "gas" / "contact.hub.gs").read_text(encoding="utf-8")
    sj = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    page = (ROOT / "site" / "tools" / "ai-check" / "index.html").read_text(encoding="utf-8")
    check("F1: 結果に合わせて次の一歩を変える（0問・1〜2問・3問）", all(x in js for x in ('"fix_order"', '"partial"', '"all"')), True)
    check("F2: 出典の上位を結果メールに載せる", "主な出典" in fn and "主な出典" in gs, True)
    check("F3: 改善のご案内は本人が選んだ人だけ（チェック欄と台帳の列）", 'name="optin"' in page and "ai.optin === false" in gs, True)
    check("F5: data-cta の文字リンクも計測する", "hasAttribute('data-cta')" in sj, True)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("F5: 段階ごとの数を週次で出す", "aicheck_funnel.py" in wf, True)


def test_subsidy_research_page_does_not_judge_answers():
    """補助金サイトの AI 聞き取り調査のページは「AIが何と答えたか」の記録。当社が正誤を判定しない
    （公式の要件と違う判断を当社の見解として広めない）。調べ方・日付・CSV を必ず載せる（2026-10-04）"""
    src = (ROOT / "scripts" / "subsidy" / "research.py").read_text(encoding="utf-8")
    check("調査ページ: 正誤を判定しないと明記する", "正しいかを判定していません" in src, True)
    check("調査ページ: 調べ方と限界・CSV を載せる", "調べ方と限界" in src and "data.csv" in src, True)
    pg = (ROOT / "scripts" / "subsidy" / "pages.py").read_text(encoding="utf-8")
    check("調査ページ: サイトマップと llms.txt に載せる", pg.count("research_done") >= 4, True)


def test_ai_answer_pages_for_three_sites():
    """「AIに聞いた調査」のページは3サイトとも同じ中身の作り（research.data）から出す。
    コーポレートは Next.js なので、中身（JSON）とページの雛形を管制塔から配信する（2026-10-04）"""
    import importlib, sys as _s
    _s.path.insert(0, str(ROOT / "scripts" / "subsidy"))
    RS = importlib.import_module("research")
    check("調査ページ: 3サイトの設定がある", sorted(RS.SITE), ["ai-lab", "corporate", "subsidy"])
    b = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("AI集客ラボ: build.py が調査ページを作る", '_RS.data("ai-lab"' in b, True)
    wf = (ROOT / ".github" / "workflows" / "industry-research.yml").read_text(encoding="utf-8")
    check("毎月: AI集客ラボ・コーポレートを調べ、コーポレートへ配信する",
          ("--site ai-lab" in wf, "--site corporate" in wf, "research_publish.py --site corporate --push" in wf), (True, True, True))
    check("コーポレートのページの雛形がある", (ROOT / "templates" / "corporate_research_page.tsx").is_file(), True)
