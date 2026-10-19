# -*- coding: utf-8 -*-
"""書き直し・統合・戻しの検算の穴（2026-10-20 の全体点検で確かめたもの）。

  F1 数字の検算が数字だけを比べていた（「3つ」があれば「3倍」、「450万円」があれば「450億円」が通る）。
     漢数字（三割・四百五十万円）を数えず、「約」「以上」を付けて意味を変えても通った。
     鮮度の更新（fresh）は今日の年・月・日の数字をそのまま許し、今日が20日なら「20万円」も通った
  F2 狙う語・題を正規表現で1行目から拾っていた。keyword を2行に書く（build.py は後の行を使う）と検算を素通りした。
     カテゴリの変更も見ていなかった
  F3 出典の URL を足すのを止めるのが compete・serp・aisplit・early だけだった
  F4 題を戻すとき、その後に直した説明文まで直す前へ戻していた。題の判定期間中にも説明文（desc）を直していた
  F5 直す前の原稿が見つからないと「戻さない（KEPT）」と判定済みにし、二度と戻せなかった
  F6 AI に articles/** を丸ごと書かせ（acceptEdits）、1本ずつの書き直しは作業場所そのもので動いていた
  F7 Windows の時間切れで claude.CMD の子の node が残り、止まらなかった
  B4 score_check の FAIL の増加を見ていなかった（WARN が FAIL に変わっても件数は同じ）
架空の記事（zz-post）と一時の場所だけで試す。claude は呼ばない（課金）。記事・台帳には触れない。
"""
import io
import json
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

KW = "zz 経理代行"
ART = ("---\ntitle: zz の経理代行の費用と選び方5つ\nkeyword: zz 経理代行\ncategory: zz-cat\n"
       "description: " + "経理代行の費用の相場と、選ぶときに確かめる点をまとめました。" * 3 + "\n---\n"
       "本文。料金は月3万円から。[出典](https://zz.example/a)\n")


def test_numbers_are_compared_with_their_units():
    import auto_rewrite as AR
    print("\n■ F1 数字は単位・限定とひとまとまりで比べ、漢数字もそろえる")
    base = "本文。3つの手順。上限450万円。採択は3割。\n"
    bad = {
        "「3つ」があっても「3倍」は新しい": "効果は3倍です。",
        "「450万円」があっても「450億円」は新しい": "総額450億円の制度。",
        "漢数字の「三十社」は新しい数として数える": "三十社が使っています。",
        "「約」を付けると新しい事実": "上限は約450万円です。",
        "「以上」を付けると新しい事実": "採択は3割以上。",
        "書いていなかった「五割」": "五割の会社が使います。",
    }
    got = {name: bool(AR.new_fact_numbers(base, base + add)) for name, add in bad.items()}
    check("意味の変わる数字を止める", [n for n, v in got.items() if not v], [])
    good = {
        "同じ金額を漢数字で書く": "上限は四百五十万円。",
        "同じ金額を桁区切りで書く": "上限は4,500,000円。",
        "同じ割合を漢数字で書く": "三割が採択。",
        "記事の組み立ての個数": "5つのポイントの2つ目と、3ステップ。",
        "熟語の漢字（一般・十分・一人ひとり）": "一般に十分です。一人ひとり違います。",
    }
    got = {name: bool(AR.new_fact_numbers(base, base + add)) for name, add in good.items()}
    check("同じ事実の書き方の違い・組み立ての個数は止めない", [n for n, v in got.items() if v], [])
    check("今まで通していた正しい書き換え（1,500円・3つの観点・3,200店舗など）を通す", AR.false_alarms(), [])
    today = AR.date_tokens(2026, 10, 20)
    check("fresh: 今日の「YYYY年M月」「D日」は許す",
          AR.new_fact_numbers(base, base + "2026年10月時点。10月20日に確認。\n", today), {})
    check("fresh: 今日の日と同じ数でも「20万円」「10社」は止める",
          sorted(AR.new_fact_numbers(base, base + "20万円で10社が導入。\n", today)), ["10社", "200000円"])


def _root(td, text=ART):
    r = Path(td)
    (r / "articles").mkdir(parents=True, exist_ok=True)
    (r / "articles" / "zz-post.md").write_text(text, encoding="utf-8", newline="")
    return r


def _check(AR, root, after, allowed="", warns_after=None):
    """作った記事を after に書き換えて check() を通す（kw_guard・build は通る扱い、警告は増えない扱い）"""
    p = root / "articles" / "zz-post.md"
    before = AR.meta("zz-post")
    snap = AR.snapshot()
    p.write_text(after, encoding="utf-8", newline="")
    ok = subprocess.CompletedProcess([], 0, "", "")
    with mock.patch.object(AR, "sh", lambda *a, **k: ok), \
            mock.patch.object(AR, "warns", lambda slug: list(warns_after or [])):
        got = AR.check("zz-post", before, [], snap, allowed)
    p.write_text(ART, encoding="utf-8", newline="")
    return got


def test_front_matter_category_and_source_urls_are_checked():
    import auto_rewrite as AR
    print("\n■ F2・F3 フロントマターは YAML で読み、同じ項目の2行・カテゴリの変更・出典の URL の追加を止める")
    with tempfile.TemporaryDirectory(prefix="gate_h122_", ignore_cleanup_errors=True) as td:
        root = _root(td)
        with mock.patch.object(AR, "ROOT", root):
            check("直していない記事は通る", _check(AR, root, ART), "")
            dup = ART.replace("keyword: zz 経理代行\n", "keyword: zz 経理代行\nkeyword: 別の語\n")
            check("keyword を2行に書いたら止める", _check(AR, root, dup).startswith("フロントマターが読めません"), True)
            cat = ART.replace("category: zz-cat", "category: zz-other")
            check("カテゴリが変わったら止める", _check(AR, root, cat).startswith("カテゴリが変わりました"), True)
            url = ART.replace("本文。", "本文。[根拠](https://zz.example/made-up)")
            check("どの種類の直しでも、出典の URL を足したら止める",
                  _check(AR, root, url).startswith("出典のURLが増えました"), True)
            check("許可した一次情報にある URL は足してよい",
                  _check(AR, root, url, allowed="- 調べ（https://zz.example/made-up）"), "")
            body_line = ART.replace("本文。", "本文。\ncategory: zz-body\n")
            (root / "articles" / "zz-post.md").write_text(body_line, encoding="utf-8")
            with mock.patch("sites.find_category_owner", lambda c: {"zz-cat": "zz-site"}.get(c)):
                check("site_of は本文の「category:」の行を拾わない", AR.site_of("zz-post"), "zz-site")
    src = (ROOT / "scripts" / "auto_merge.py").read_text(encoding="utf-8")
    chk = src[src.index("def check("):src.index("def _append(")]
    check("統合の検算も カテゴリ・出典の URL の追加（2本のどちらにも無いもの）・FAIL の増加を見る",
          ("カテゴリが変わりました" in chk, "AR.sources(loser_text)" in chk, "AR.worse_warns(" in chk), (True, True, True))


def test_fail_lines_are_compared():
    import auto_rewrite as AR
    print("\n■ B4 score_check の FAIL が増えたら止める（既にある FAIL は止めない）")
    w = lambda name, mark="WARN": f"{mark} | {name} | 明細"
    check("既にある FAIL は止めない", AR.worse_warns([w("文字数", "FAIL")], [w("文字数", "FAIL")]), "")
    check("新しい FAIL は止める",
          AR.worse_warns([w("文字数", "FAIL")], [w("文字数", "FAIL"), w("FAQ", "FAIL")]).startswith("警告が増えました"), True)
    check("WARN が FAIL に変わったら件数が同じでも止める", bool(AR.worse_warns([w("FAQ")], [w("FAQ", "FAIL")])), True)
    check("WARN の件数が増えたら止める（今までどおり）", bool(AR.worse_warns([w("a")], [w("a"), w("b")])), True)
    with tempfile.TemporaryDirectory(prefix="gate_h122_", ignore_cleanup_errors=True) as td:
        root = _root(td)
        with mock.patch.object(AR, "ROOT", root):
            check("check() が FAIL の増加で止める",
                  _check(AR, root, ART, warns_after=[w("FAQ", "FAIL")]).startswith("警告が増えました"), True)


def test_rollback_keeps_later_description_and_holds_missing_source():
    import rewrite_rollback as RR
    print("\n■ F4・F5 題を戻しても後で直した説明文は残す／直す前の原稿が無ければ判定を保留する")
    with tempfile.TemporaryDirectory(prefix="gate_h122_", ignore_cleanup_errors=True) as td:
        r = Path(td)
        (r / "articles").mkdir()
        p = r / "articles" / "zz-post.md"
        d = {"slug": "zz-post", "kind": "title", "before_title": "zz の経理代行の選び方",
             "after_title": "zz の経理代行の費用", "before_description": "直す前の説明",
             "after_description": "直した後の説明"}
        with mock.patch.object(RR, "ROOT", r):
            p.write_text("---\ntitle: zz の経理代行の費用\ndescription: 手で直した説明\n---\n本文\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()) as o:
                ok = RR.restore("zz-post", d)
            t = p.read_text(encoding="utf-8")
            check("説明文が直した後のものでなければ、題だけ戻して説明文は残し、要対応で知らせる",
                  (ok, "zz の経理代行の選び方" in t, "手で直した説明" in t, "要対応" in o.getvalue()), (True, True, True, True))
            p.write_text("---\ntitle: zz の経理代行の費用\ndescription: 直した後の説明\n---\n本文\n", encoding="utf-8")
            RR.restore("zz-post", d)
            check("説明文が直した後のままなら題と一緒に戻す", "直す前の説明" in p.read_text(encoding="utf-8"), True)

            # F5: 直す前の原稿が見つからない（本文の直し）→ 判定済みにせず保留
            p.write_text("---\ntitle: zz\n---\n本文\n", encoding="utf-8")
            row = {"slug": "zz-post", "kind": "serp", "at": "2026-08-01 10:00", "by": "auto_rewrite", "ok": True,
                   "note": "直しました", "before_path": "data/rewrite_before/zz-post@2026-08-01.md", "after_sha": "x"}
            import effect_ab as EA
            import client_private as CP
            saved = []
            with mock.patch.object(RR, "entries", lambda: [row]), \
                    mock.patch.object(RR, "controls", lambda *a: [1.0] * 12), \
                    mock.patch.object(RR, "min_controls", lambda: 10), \
                    mock.patch.object(RR, "published", lambda: {}), \
                    mock.patch.object(EA, "daily_by_slug", lambda: ({}, None, None)), \
                    mock.patch.object(EA, "change", lambda *a: (0.1, -2)), \
                    mock.patch.object(EA, "rewrites", lambda *a: []), \
                    mock.patch.object(CP, "load_dict", lambda *a, **k: {}), \
                    mock.patch.object(CP, "save_dict", lambda rel, dd, *a, **k: saved.append(dict(dd))), \
                    mock.patch.object(CP, "append_jsonl", lambda *a, **k: saved.append("log")), \
                    mock.patch.object(sys, "argv", ["rewrite_rollback.py", "--write"]):
                with redirect_stdout(io.StringIO()) as o:
                    RR.main()
            out = o.getvalue()
            check("原稿が無ければ HELD に数え、判定済み（KEPT）にしない・要対応で知らせる",
                  ("HELD=1" in out, "KEPT=0" in out, saved, "要対応" in out), (True, True, [{}], True))


def test_agent_writes_only_its_article_in_a_copy():
    import auto_rewrite as AR
    import auto_merge as AM
    print("\n■ F6 AI は一時フォルダの写しで、名指しした1本だけを書ける。作業場所が変わったら全部戻して止める")
    with mock.patch.object(AR, "claude_bin", lambda: "claude"), mock.patch.object(AR, "model_args", lambda: []):
        a = AR.claude_args(["zz-post"])
        perm = json.loads(a[a.index("--settings") + 1])["permissions"]
        check("書けるのはその1本だけ・許可に無いものは断る（dontAsk）",
              (a[a.index("--allowedTools") + 1], perm["allow"], perm["defaultMode"]),
              ("Read,Edit(articles/zz-post.md)", ["Read", "Edit(articles/zz-post.md)"], "dontAsk"))
        check("Bash・Write・WebFetch・WebSearch を拒む",
              [t for t in ("Bash", "Write", "WebFetch", "WebSearch") if t not in perm["deny"]], [])
        check("鍵のファイルの Read の拒否はそのまま", all(x in perm["deny"] for x in AR.READ_DENY), True)
        try:
            AR.claude_args(["../scripts/x"])
            bad = False
        except ValueError:
            bad = True
        check("記事の名前の形でないものは許可に書かない", bad, True)
        seen = []
        with mock.patch.object(AR, "sh", lambda args, **k: seen.append(args) or subprocess.CompletedProcess(args, 0, "", "")):
            AM._claude("p", cwd="x", survivor="zz-s")
        tools = seen[0][seen[0].index("--allowedTools") + 1]
        check("統合で書けるのは残す側（survivor）だけ。消す側は読むだけ", tools, "Read,Edit(articles/zz-s.md)")

    with tempfile.TemporaryDirectory(prefix="gate_h122_", ignore_cleanup_errors=True) as td:
        root = _root(td)
        (root / "scripts").mkdir()
        (root / "scripts" / "tool.py").write_text("x = 1\n", encoding="utf-8")
        where = {}

        def fake_sh(args, timeout=1800, stdin_text=None, cwd=None):
            where["cwd"] = cwd
            (Path(cwd) / "articles" / "zz-post.md").write_text(ART.replace("本文。", "本文を直しました。"), encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "", "")
        with mock.patch.object(AR, "ROOT", root), mock.patch.object(AR, "sh", fake_sh), \
                mock.patch.object(AR, "claude_bin", lambda: "claude"), mock.patch.object(AR, "model_args", lambda: []):
            text, _ = AR.guarded(lambda: AR.draft_one({"slug": "zz-post"}, "p"))
            check("1本ずつの書き直しも写しで書き、作業場所の原稿は変えない（当てるのは呼び出し側）",
                  ("本文を直しました" in text, Path(where["cwd"]) != root,
                   (root / "articles" / "zz-post.md").read_text(encoding="utf-8") == ART), (True, True, True))

            def escape():
                (root / "scripts" / "tool.py").write_text("x = 2\n", encoding="utf-8")
                (root / "articles" / "zz-other.md").write_text("増えた", encoding="utf-8")
            try:
                AR.guarded(escape)
                caught = False
            except AR.Escaped:
                caught = True
            check("作業場所の道具・記事が変わったら全部戻して止める",
                  (caught, (root / "scripts" / "tool.py").read_text(encoding="utf-8"),
                   (root / "articles" / "zz-other.md").exists()), (True, "x = 1\n", False))


def test_windows_timeout_kills_the_process_tree():
    import auto_rewrite as AR
    print("\n■ F7 Windows の時間切れは taskkill /T /F で子プロセスごと止める")
    calls = []

    class FakePopen:
        pid = 4242

        def __init__(self, *a, **k):
            self.n = 0

        def communicate(self, input=None, timeout=None):
            self.n += 1
            if self.n == 1:
                raise subprocess.TimeoutExpired("claude", timeout)
            return "", ""
    with mock.patch.object(AR, "WINDOWS", True), mock.patch.object(AR.subprocess, "Popen", FakePopen), \
            mock.patch.object(AR.subprocess, "run", lambda args, **k: calls.append(list(args))):
        try:
            AR._run(["claude", "-p"], timeout=1, input="x")
            raised = False
        except subprocess.TimeoutExpired:
            raised = True
    check("時間切れを返し、taskkill /T /F /PID で木ごと止める", (raised, calls), (True, [["taskkill", "/T", "/F", "/PID", "4242"]]))
    with mock.patch.object(AR, "WINDOWS", False), \
            mock.patch.object(AR.subprocess, "run", lambda args, **k: calls.append(("run", list(args))) or "r"):
        check("Windows 以外（CI）は subprocess.run のまま", AR._run(["git", "status"]), "r")


def test_desc_waits_while_title_is_judged():
    import auto_rewrite as AR
    print("\n■ F4 題の判定期間中は説明文（desc）も直さない")
    with tempfile.TemporaryDirectory(prefix="gate_h122_", ignore_cleanup_errors=True) as td:
        root = _root(td)
        with mock.patch.object(AR, "ROOT", root), mock.patch.object(AR, "title_locked", lambda slug: "2026-10-10"), \
                mock.patch("shutil.which", lambda name: "claude"):
            ok, why = AR.run_one({"kind": "desc", "slug": "zz-post", "site": "zz", "why": "門"}, True)
    check("desc を見送る", (ok, "判定期間中" in why), (False, True))
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    body = src[src.index("def desc_items("):src.index("def split_items(")]
    check("desc の候補も判定期間中の記事を外す", "title_locked(slug)" in body, True)
