# -*- coding: utf-8 -*-
"""2026-10-11 運用者「自動的に直して」。

1. 自動修復の案（鍵の無いコンテナで AI が作った差分）は、検証と機械の検査（patch_policy）に通った1回目のものを人を待たずに
   本体へ取り込む。外へ送る・コマンド・環境変数・書き方を隠す書き方、守る場所、門を弱める変更、多すぎる変更は枝に置いて知らせる
2. 配信先に元からある記事と重複した公開済みの記事は、救済の AI に消させず、実績（同じ検索語に両方が出ている）で決めて
   機械（dup_retract）が取り下げ、既存の記事へ301で送る（retract.py が配信先を直す）
"""
import json
import tempfile
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

import sys
sys.path.insert(0, str(ROOT / "scripts"))


def _patch(path, added, removed=(), new=False, gone=False):
    head = f"diff --git a/{path} b/{path}\n"
    if new:
        head += "new file mode 100644\n"
    if gone:
        head += "deleted file mode 100644\n"
    body = "".join(f"-{x}\n" for x in removed) + "".join(f"+{x}\n" for x in added)
    return head + f"--- a/{path}\n+++ b/{path}\n@@ -1,{len(removed)} +1,{len(added)} @@\n" + body


def test_patch_policy_lets_ordinary_fixes_through():
    print("\n■ 自動修復の案の検査: ふつうの直しは取り込み、危ない書き方・守る場所・門を弱める変更は枝へ")
    import patch_policy as PP
    ok = [_patch("scripts/kw_plan.py", ["    if not rows:", "        return []"], ["    rows = rows or []"]),
          _patch("tests/test_gates.py", ["    check(\"空の台帳でも落ちない\", f([]), [])"]),
          _patch("data/lessons.jsonl", ["{\"rule\": \"x\"}"]),
          _patch("site/sitemap.xml", ["<url/>"]) + _patch("scripts/kw_gate.py", ["    n = len(xs)"]),
          # ふつうの直しに出る書き方（2026-10-12 の点検で、これらまで枝に回り自動で直らなかった）
          _patch("scripts/kw_plan.py", ["RX = re.compile(r'^x')", "    max_tokens = 400", "    v = getattr(args, \"site\", \"\")",
                                        "    tmp.unlink(missing_ok=True)", "ROOT = Path(__file__).resolve().parent",
                                        "    s = s.replace(\"\\u3000\", \" \")", "if __name__ == \"__main__\":"])]
    check("ふつうの直し（コード・門を足す・データ・生成物つき・よく使う書き方）は取り込む",
          [PP.judge(p)[0] for p in ok], [True] * len(ok))
    hunk = lambda path, lines: (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
                                f"@@ -1,0 +1,{len(lines)} @@\n" + "".join(f"+{x}\n" for x in lines))
    bad = {
        "外への通信": _patch("scripts/kw_plan.py", ["import urllib.request"]),
        "コマンド": _patch("scripts/kw_plan.py", ["    subprocess.run(['curl', u])"]),
        "環境変数": _patch("scripts/kw_plan.py", ["    k = os.environ.get('SITE_PUSH_TOKEN')"]),
        "隠す": _patch("scripts/kw_plan.py", ["    getattr(os, 'sys' + 'tem')('id')"]),
        "コメントに見せかけ": _patch("scripts/kw_plan.py", ["x = '#'; __import__('so' + 'cket')"]),
        "鍵の場所": _patch("scripts/kw_plan.py", ["    open('.git/config').read()"]),
        "守る場所": _patch(".github/workflows/x.yml", ["on: push"]),
        "配って動くコード": _patch("functions/api/lead.js", ["fetch(x)"]),
        "依存": _patch("requirements.txt", ["evil-package"]),
        "門を弱める": _patch("tests/test_gates.py", [], ["    check(\"a\", 1, 1)", "    check(\"b\", 2, 2)"]),
        "門を消す": _patch("tests/gates_history_h10.py", [], ["x"], gone=True),
        "見えない変更": "diff --git a/scripts/a.bin b/scripts/a.bin\nGIT binary patch\nliteral 3\n",
        "JS は見ない": _patch("site/js/x.js", ["a()"]) + _patch("tools/x.js", ["a()"]),
        "多すぎる": "".join(_patch(f"scripts/m{i}.py", ["x = 1"]) for i in range(20)),
        "直した中身が無い": _patch("site/index.html", ["<p>"]),
        "検査そのもの": _patch("scripts/patch_policy.py", ["MAX_FILES = 999"]),
        # 記事に入れてよい埋め込みの形を決める所（2026-10-12）。変えると、通してよい iframe の形が人の確認なしに変わる
        "埋め込みの仕組み": _patch("scripts/embeds.py", ["x = 1"]) + _patch("scripts/md2html.py", ["y = 2"]),
        # 2026-10-12 の点検: 判定を素通りして git apply だけが当てる形
        "見出しの無い2つ目のファイル": hunk("scripts/kw_plan.py", ["x = 1"])
            + "--- a/.github/workflows/x.yml\n+++ b/.github/workflows/x.yml\n@@ -1 +1 @@\n-on: push\n+on: workflow_dispatch\n",
        "見出しの前の差分": "--- a/.github/workflows/x.yml\n+++ b/.github/workflows/x.yml\n@@ -1 +1 @@\n-a\n+b\n"
            + hunk("scripts/kw_plan.py", ["x = 1"]),
        "引用符つきの名前": "diff --git \"a/scripts/k w.py\" \"b/scripts/k w.py\"\n@@ -1 +1 @@\n-a\n+b\n",
        "名前の変更": "diff --git a/scripts/a.py b/scripts/b.py\nsimilarity index 90%\nrename from scripts/a.py\nrename to scripts/b.py\n",
        "見出しと名前が違う": "diff --git a/scripts/a.py b/scripts/a.py\n--- a/scripts/a.py\n+++ b/sites/x.json\n@@ -1 +1 @@\n-a\n+b\n",
        "指示書・設定": _patch("CLAUDE.md", ["- 新しい決まり"]) + _patch("sites/corporate.json", ["{}"])
            + _patch("automation/retry_prompt.txt", ["x"]),
        "データの名前で外へ": _patch("data/../sites/x.json", ["{}"]),
        "; の後ろの import": _patch("scripts/kw_plan.py", ["x = 1; import webbrowser"]),
        "ワークフローを書き出す": _patch("scripts/kw_plan.py", ["    Path('.github/workflows/x.yml').write_text(y)"]),
        "隠した文字": _patch("scripts/kw_plan.py", ["    m = '\\x6f\\x73\\x2e\\x73'"]),
    }
    got = {k: PP.judge(v)[0] for k, v in bad.items()}
    check("危ない書き方・守る場所・依存・門を弱める・見えない変更・多すぎる・中身が無い・検査そのものは取り込まない",
          [k for k, v in got.items() if v], [])


def test_duplicates_are_retracted_by_the_machine():
    print("\n■ 既存記事と重複した公開済みの記事: 実績で決めて機械が取り下げ、既存の記事へ301で送る")
    import dup_retract as D
    import auto_merge as AM
    h = lambda imp, verdict="conflict", slug="zz-dup-a": {
        "verdict": verdict, "imp": imp, "site": "corporate",
        "mine": {"slug": slug, "kw": "経理代行 費用", "title": "t"},
        "theirs": {"slug": "keiri-daiko", "url": "https://corp.7senses.co.jp/blog/keiri-daiko/", "title": "t"}}
    plan = D.plan([h((40, 30)), h((90, 20), slug="zz-dup-b"), h((0, 50), verdict="clear", slug="zz-dup-c")])
    check("同じ語に両方が出ている組だけを取り下げ、自作側が3倍以上強ければ残す・似ているだけの組は触らない",
          [(x[0]["mine"]["slug"], x[1]) for x in plan], [("zz-dup-a", "retract"), ("zz-dup-b", "keep")])
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "articles").mkdir()
        (root / "articles" / "zz-dup-a.md").write_text("---\ntitle: t\ncategory: keiri-bpo\n---\n本文\n", encoding="utf-8")
        rj = root / "retractions.jsonl"
        with mock.patch.object(AM, "RETRACT", rj), mock.patch.object(AM, "relink", lambda *a: 0):
            fr, to = D.retract(h((40, 30)), root=root, today="2026-10-11")
        row = json.loads(rj.read_text(encoding="utf-8").splitlines()[0])
        moved = (root / "articles" / "_merged" / "zz-dup-a.md")
        check("原稿を _merged へ移し（印つき）、配信先から外して既存の記事へ301で送る行を積む",
              ((root / "articles" / "zz-dup-a.md").exists(), moved.exists() and "retracted_for:" in moved.read_text(encoding="utf-8"),
               (row["site"], row["from"], row["to"], row["survivor"])),
              (False, True, ("corporate", "/blog/zz-dup-a/", "/blog/keiri-daiko/", "keiri-daiko")))
    pl = (ROOT / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    rp = (ROOT / "automation" / "retry_prompt.txt").read_text(encoding="utf-8")
    check("救済の機械の手順が取り下げて配信先を直し、AI は公開済みの記事を要対応にせず機械に任せる",
          (pl.index("dup_retract.py --write") < pl.index("retract.py --pending --push"),
           "機械の手順（dup_retract）" in rp, "「要対応: <slug> の取り下げ」" in rp),
          (True, True, False))
