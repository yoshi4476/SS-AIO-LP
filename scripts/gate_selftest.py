# -*- coding: utf-8 -*-
"""検査の検査: わざと壊した例を入れ、門（tests/test_gates.py）がちゃんと止めるかを確かめる（週次）。

2026-10-03 に、自動テストを pytest で走らせると失敗を「passed」と出していたこと、
検出器の数え方の誤りが何度もあったことが分かった。門が黙って壊れていても、普段は誰も気づかない。
既知の壊れ方を1つずつ入れて、その門が落ちることを確かめ、落ちなければ「その門は壊れている」と知らせる。
入れた変更は必ず元に戻す（try/finally）。

    python scripts/gate_selftest.py
出す印: GATE_SELFTEST_OK=yes|no と「要対応: …」の行（検査が動かなかったときだけ終了コード1）
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (壊すファイル, 元の文字列, 壊した文字列, 止めるはずの門, 何を壊したか)
PLANTS = [
    ("site/tools/index.html", "<h1>無料ツール</h1>", '<h1>無料ツール</h1><a href="/site-audit/">x</a>',
     "test_free_tools_live_under_one_roof", "古いツールURLへのリンク"),
    ("site/faq/index.html", "<p>最低契約期間は6か月です。", "<p>最低契約期間は3か月です。",
     "test_question_and_faq_pages", "よくある質問の画面と構造化データの食い違い"),
    ("scripts/daily_audit.py", "    sys.exit(main())", "    main()",
     "test_monthly_cap_check_exit_code", "月の上限の判定が終了コードを捨てる"),
    ("data/research/dental-questions.json", '"answered": 3,', '"answered": 4,',
     "test_question_and_faq_pages", "質問集の数字が調査の要約とずれる"),
    ("data/season_calendar.json", '"windows": [["10-01", "11-30"]]', '"windows": [["13-40", "11-30"]]',
     "test_season_features", "特集の暦にありえない日付"),
]


def run_gate(fn):
    """その門だけを走らせ、落ちたら True"""
    code = ("import sys; sys.path.insert(0, 'tests'); sys.path.insert(0, 'scripts'); import test_gates as T\n"
            f"try:\n    T.{fn}()\nexcept Exception as e:\n    T.FAIL.append(str(e))\n"
            "sys.exit(1 if T.FAIL else 0)")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    return r.returncode != 0


def main():
    bad = []
    base = {fn for _, _, _, fn, _ in PLANTS}
    broken_before = [fn for fn in sorted(base) if run_gate(fn)]
    if broken_before:
        # 「要対応」の行にしないと、週次の通知に載らない（Codex の点検で指摘）
        print(f"要対応: 壊す前から落ちている門があります: {', '.join(broken_before)}（先にそちらを直す）")
        print("GATE_SELFTEST_OK=no")
        return 0
    for rel, old, new, fn, what in PLANTS:
        p = ROOT / rel
        orig = p.read_bytes()
        s = orig.decode("utf-8")
        if old not in s:
            bad.append(f"要対応: 検査の検査を当てられません（{rel} に「{old[:30]}」が無い）。gate_selftest.py の例を今の形に直す")
            continue
        try:
            # 1か所だけ壊す（JSON の数字などは最初の1つで足りる）
            p.write_bytes(s.replace(old, new, 1).encode("utf-8"))
            caught = run_gate(fn)
        finally:
            p.write_bytes(orig)
            if p.read_bytes() != orig:
                bad.append(f"要対応: 検査の検査が {rel} を元に戻せていません（手で戻す）")
        print(f"  {'止めた' if caught else '素通り'}  {what} → {fn}")
        if not caught:
            bad.append(f"要対応: 門 {fn} が「{what}」を止めませんでした（門が壊れている）")
    for b in bad:
        print(b)
    print(f"GATE_SELFTEST_OK={'no' if bad else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
