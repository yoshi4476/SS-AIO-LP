# -*- coding: utf-8 -*-
"""週次の検査が見つけたものを、1か所に集めて知らせる。

個々の検査は `|| true` を付けて呼んでいる。1つ止まっても週次全体を
止めたくないためだが、その結果として終了コードが捨てられ、何を見つけても
実行ログの奥に埋もれて誰にも届いていなかった。実際、会社表記のゆれと
AIO基盤の欠けは毎週検出されうるのに、Slackには「週次最適化: success」
としか出ていない。

ここは検査をまとめて回し、出力から「見つかったもの」だけを抜き出して、
GitHubの注釈と通知本文に載る形にする。**ここ自体は決して止まらない**
（常に0で終わる）。知らせるのが仕事であって、止めるのは各検査の仕事。
"""
import argparse
import io
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "automation" / "logs" / "findings.txt"
MAX_LINES = 6        # 1検査あたりの明細。多すぎると通知が読まれなくなる
TIMEOUT = 900

# 読むだけの検査だけを入れる。書き換える工程を入れると週次で二重に走る。
# 明細の書き方が検査ごとに違うため、拾う形をここで明示する
CHECKS = [
    ("AIO基盤（robots・llms.txt・構造化データ）", "aio_check.py",
     re.compile(r"未記載:|不足:|取得できません|記事が載っていません")),
    ("会社表記のゆれ（NAP）", "nap_check.py",
     re.compile(r"^\s{2}-\s")),
    ("内部リンクの積み上がり", "auto_review.py",
     re.compile(r"上限\+\d+本|同じ言い回し\d+本")),
    ("数字の信頼性", "data_sanity.py",
     re.compile(r"^\s*注意\s+(?!\d+件)\S")),
    ("ラッコキーワードの消費", "rakko.py",
     re.compile(r"今月の消費")),
    # 面の欠け。1本ずつ選んでいると、同じマスに重なり、空いたマスが残る。
    # 検索エンジンとAIが「この分野を扱うサイト」と見るのは面の広さによる
    ("盤面の空き（業種×手法）", "coverage.py",
     re.compile(r"空いているマス")),
    # 順位は保証できないが、順位を決める要因のうちこちら側にあるものは
    # 100%満たせる。その達成率を毎週出す
    ("こちら側で決まる要因の達成率", "guarantee.py",
     re.compile(r"^  [×] |^  合計 ")),
]

# 「問題あり」を表す印。検査ごとに語尾が違うため、値の側で見る
BAD = re.compile(r"(?:[A-Z_]+_OK=no|LIVE_CHECK=ng|KW_GATE=block|RAKKO_MONTH=over)")
GOOD = re.compile(r"(?:[A-Z_]+_OK=yes|LIVE_CHECK=ok|KW_GATE=ok|RAKKO_MONTH=ok)")


def run(script):
    """検査を1本動かして、出力と終了コードを返す。落ちても例外にしない。"""
    try:
        args = ["--check"] if script == "rakko.py" else []
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / script)] + args,
                           cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT)
        return (r.stdout or "") + (r.stderr or ""), r.returncode
    except subprocess.TimeoutExpired:
        return "（%d秒で応答がありませんでした）" % TIMEOUT, 124
    except Exception as e:
        return "（起動できません: %s）" % e, 127


def judge(text, rc):
    """印を最優先で見る。印が無い検査だけ終了コードに頼る。

    印を先に見るのは、終了コードが「見つかった」と「壊れた」を
    区別できないため。実際それで一度、正常な検出を不具合と読み違えた。
    """
    if BAD.search(text):
        return "要対応"
    if GOOD.search(text):
        return "問題なし"
    if rc in (124, 127):
        return "動かせず"
    return "問題なし" if rc == 0 else "要対応"


def details(text, pat):
    seen, out = set(), []
    for ln in text.splitlines():
        s = ln.rstrip()
        if not s.strip() or not pat.search(s):
            continue
        # 表の桁揃えがそのまま通知に出ると読めない
        t = re.sub(r"[ 　]{2,}", " ", s.strip())
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def annotate(level, msg):
    """GitHub Actions の注釈。ローカルではただの1行として出る"""
    print("::%s::%s" % (level, msg.replace("\n", " ")))


def main():
    ap = argparse.ArgumentParser(
        description="週次の検査をまとめて回し、見つかったものを集める")
    ap.add_argument("--quiet", action="store_true",
                    help="各検査の生の出力を表示しない")
    a = ap.parse_args()

    rows, lines = [], []
    for label, script, pat in CHECKS:
        if not (ROOT / "scripts" / script).exists():
            rows.append((label, "動かせず", ["%s がありません" % script]))
            continue
        print("\n===== %s（%s） =====" % (label, script), flush=True)
        text, rc = run(script)
        if not a.quiet:
            print(text.rstrip())
        state = judge(text, rc)
        rows.append((label, state, details(text, pat) if state == "要対応" else []))

    print("\n" + "=" * 60)
    print("■ 週次で見つかったもの\n")
    bad = [r for r in rows if r[1] != "問題なし"]
    for label, state, det in rows:
        mark = {"問題なし": "OK  ", "要対応": "要対応", "動かせず": "動かせず"}[state]
        print("  %s %s%s" % (mark, label,
                             "（%d件）" % len(det) if det else ""))
        for d in det[:MAX_LINES]:
            print("       " + d[:100])
        if len(det) > MAX_LINES:
            print("       …ほか%d件" % (len(det) - MAX_LINES))

    # 通知に載せる本文。Slackが読める長さに収める
    for label, state, det in bad:
        lines.append("%s: %s" % (state, label))
        for d in det[:3]:
            lines.append("   " + d[:80])
    if not bad:
        lines.append("検査%d件すべて問題なし" % len(rows))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("\n  通知用に書き出しました: %s" % OUT.relative_to(ROOT))

    for label, state, det in bad:
        if state == "動かせず":
            annotate("error", "検査が動きません: %s" % label)
        else:
            annotate("warning", "%s — %s" % (
                label, " / ".join(d[:60] for d in det[:2]) or "詳細は実行ログ"))

    print("FINDINGS=%d" % len(bad))
    return 0   # 知らせるのが仕事。ここで止めない


if __name__ == "__main__":
    sys.exit(main())
