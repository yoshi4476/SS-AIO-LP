# -*- coding: utf-8 -*-
"""書き直しの長さの警告を機械で直す門と、作業場所（git worktree）の並列を1つの部品にまとめた門（2026-10-04）。"""
import inspect

from test_gates import check, ROOT


def test_rewrite_fixes_only_length_warnings():
    import auto_rewrite as AR
    f = AR.mechanically_fixable
    long_s = "WARN | ［警告］長文が1割強以内・100字超はゼロ（規定50字） | 70字超12文・100字超1文"
    long_p = "WARN | ［警告］段落が200字以内（規定150字＋余裕） | 1段落"
    check("長文の警告は機械で直せる", f([long_s]), True)
    check("長い段落の警告は機械で直せる", f([long_p]), True)
    check("長文と長い段落が同時でも直せる", f([long_s, long_p]), True)
    check("タイトルの警告は直さない", f(["WARN | タイトルが15〜45字 | 50字"]), False)
    check("長さ以外が1つでも混ざれば直さない", f([long_s, "WARN | タイトルが15〜45字 | 50字"]), False)
    check("明細に「長文」が出るだけの別の警告は直さない", f(["WARN | マーカー数 | 長文・100字超・段落が200字以内"]), False)
    check("増えた警告が無ければ直さない", f([]), False)

    src = inspect.getsource(AR.run_one)
    check("書き直しは警告が増えたときだけ機械で直して検算をやり直す",
          'ng.startswith("警告が増えました") and fix_mechanical(' in src and src.count("ng = check(") == 2, True)
    fm = inspect.getsource(AR.fix_mechanical)
    check("機械の直しはその1本だけに当てる", '"--only", slug' in fm and 'split_paragraphs.py", slug' in fm, True)
    ss = (ROOT / "scripts" / "split_sentences.py").read_text(encoding="utf-8")
    check("split_sentences に --only がある", '"--only"' in ss and "only and p.stem != only" in ss, True)


def test_worktree_pool_is_shared():
    import worktree_pool as WP
    check("作業場所に Git 外の鍵を写す", set(WP.KEYS) >= {"indexing-service-account.json", ".env"}, True)
    src = inspect.getsource(WP.run_in_worktrees)
    body = src.split("try:", 1)[1] if "try:" in src else ""
    check("鍵を写すのは作業場所の中", "*KEYS" in body, True)
    check("作業場所は finally で必ず消す", "finally:\n            _remove(w)" in src, True)
    check("同じ名前の古い作業場所を先に消す", src.index("_remove(w)") < src.index('"worktree", "add"'), True)
    ml = (ROOT / "scripts" / "migrate_legacy.py").read_text(encoding="utf-8")
    check("migrate_legacy は worktree_pool を使う",
          "WP.run_in_worktrees(" in ml and '"worktree", "add"' not in ml, True)
