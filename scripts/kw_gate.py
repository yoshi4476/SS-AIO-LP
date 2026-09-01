# -*- coding: utf-8 -*-
"""食い合いのゲート。ワークフローから機械的に呼ぶ

手順書に「必ず実行すること」と書いても、それは関門ではない。
実行を忘れれば素通りする。実際、タイトル類似だけのゲートを通り抜けて、
狙う範囲が8記事と重なり51語・表示484回でクリック0の記事ができた。

2箇所で止める。
  --before  執筆前。次に書くKWを管制塔から取り、着手可否を判定する
  --after   執筆後。実際に書かれた記事の keyword を判定する
            （書き手が別のKWを選んでも、ここで捕まる）

使い方:
    python scripts/kw_gate.py --before --site ai-lab
    python scripts/kw_gate.py --after  --site ai-lab

終了コード: 0=通過 / 1=着手禁止（食い合う）
"""
import argparse
import glob
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def judge(kw, site):
    """kw_guard を呼んで着手可否を返す。(レベル, 出力)"""
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "kw_guard.py"), kw, "--site", site],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def next_keyword(site):
    """次に書くKWを管制塔から取る。取れなければローカルの計画から"""
    try:
        import hub_client
        n = hub_client.next_kw(site)
        if isinstance(n, dict) and n.get("keyword"):
            return n["keyword"], "管制塔"
    except Exception as e:
        print(f"   （管制塔から取得できません: {type(e).__name__}）")
    try:
        import kw_status
        from cannibal_check import kw_conflicts, load_articles
        arts = load_articles()
        for _g, k in kw_status.plan_keywords():
            if not kw_conflicts(k, arts):
                return k, "ローカルの計画"
    except Exception:
        pass
    return "", ""


def written_keyword(site):
    """直近に書かれた記事の keyword を、gitの差分から拾う"""
    r = subprocess.run(["git", "status", "--short", "articles/"],
                       capture_output=True, text=True, cwd=ROOT)
    files = [l.split()[-1] for l in r.stdout.splitlines() if l.strip().endswith(".md")]
    if not files:
        # 直前のコミットで追加された記事を見る
        r = subprocess.run(["git", "show", "--name-only", "--pretty=", "HEAD"],
                           capture_output=True, text=True, cwd=ROOT)
        files = [l for l in r.stdout.splitlines()
                 if l.startswith("articles/") and l.endswith(".md")]
    out = []
    for f in files:
        p = ROOT / f
        if not p.is_file():
            continue
        fm = p.read_text(encoding="utf-8-sig").split("---", 2)[1]
        kw = (re.search(r"^keyword:\s*(.+)$", fm, re.M) or [0, ""])[1].strip()
        if kw:
            out.append((p.stem, kw))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--before", action="store_true")
    ap.add_argument("--after", action="store_true")
    a = ap.parse_args()

    if a.before:
        kw, src = next_keyword(a.site)
        if not kw:
            print("次のKWを取得できませんでした。KW台帳の補充が必要です")
            print("KW_GATE=skip")
            return 0
        print(f"次に書くKW: 「{kw}」（{src}）")
        level, out = judge(kw, a.site)
        print(out.rstrip())
        if level >= 2:
            print("\nKW_GATE=block")
            print("このKWは既存ページと食い合います。台帳の状態を直すまで着手しません")
            return 1
        print("\nKW_GATE=ok")
        return 0

    if a.after:
        # 書き手が別のKWを選ぶことがある。実際に書かれたものを見る
        pairs = written_keyword(a.site)
        if not pairs:
            print("この実行で追加された記事はありません")
            print("KW_GATE=skip")
            return 0
        ng = []
        for slug, kw in pairs:
            level, out = judge(kw, a.site)
            print(f"■ {slug}（狙う語「{kw}」）")
            print("\n".join("   " + l for l in out.strip().splitlines()[-4:]))
            if level >= 2:
                ng.append((slug, kw))
        if ng:
            print("\nKW_GATE=block")
            for slug, kw in ng:
                print(f"  {slug}: 「{kw}」は既存ページと食い合います")
            return 1
        print("\nKW_GATE=ok")
        return 0

    ap.error("--before か --after のどちらかを指定してください")


if __name__ == "__main__":
    sys.exit(main())
