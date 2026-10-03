# -*- coding: utf-8 -*-
"""デスクトップの「提案資料/記入済みシートを入れる」に置いたヒアリングシートを、システムに取り込む。

営業の現場ではシートをデスクトップで書く。リポジトリの intake/ へ手で移す手間を無くし、
ダブルクリック1回（提案資料/ヒアリングシートを取り込む.cmd）で登録まで終える。

  登録できたシート → 記入済みシートを入れる/取り込み済み/
  不備があったシート → その場に残し、同じ名前の .不備.txt に直す箇所を書く
  登録された設定（sites/<id>.json・data/clients/<id>/・docs/kw-<id>.md）はコミットして公開する。
  シートそのものはコミットしない（会社名・住所・担当者の連絡先が入るため。intake/ は .gitignore 済み）

    python scripts/intake_desktop.py            # 取り込む
    python scripts/intake_desktop.py --setup    # フォルダ・空のシート・起動用の .cmd を作る
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESK = Path.home() / "Desktop" / "提案資料"
INBOX = DESK / "記入済みシートを入れる"
DONE_D = INBOX / "取り込み済み"
INTAKE = ROOT / "intake"


def setup():
    sys.path.insert(0, str(ROOT / "scripts"))
    import client_intake as CI
    INBOX.mkdir(parents=True, exist_ok=True)
    DONE_D.mkdir(exist_ok=True)
    CI.make_sheet(DESK / "ヒアリングシート（共通）.xlsx")
    try:
        CI.make_sheet(DESK / "ヒアリングシート（飲食店）.xlsx", "restaurant")
    except Exception as e:
        print(f"  飲食店向けは作れませんでした: {e}")
    (DESK / "ヒアリングシートを取り込む.cmd").write_text(
        "@echo off\r\n"
        f'cd /d "{ROOT}"\r\n'
        "set PYTHONIOENCODING=utf-8\r\n"
        "python scripts\\intake_desktop.py\r\n"
        "echo.\r\n"
        "pause\r\n", encoding="cp932")
    print(f"用意しました: {DESK}")
    print("  1. ヒアリングシート（共通）.xlsx をコピーして記入する")
    print("  2. 記入したシートを「記入済みシートを入れる」に置く")
    print("  3. 「ヒアリングシートを取り込む.cmd」をダブルクリックする")


def main():
    if "--setup" in sys.argv:
        setup()
        return 0
    sheets = [p for p in INBOX.glob("*.xlsx") if not p.name.startswith("~$")]
    if not sheets:
        print(f"取り込むシートがありません（{INBOX} に記入済みのシートを置いてください）")
        return 0
    INTAKE.mkdir(exist_ok=True)
    for p in sheets:
        shutil.copy2(p, INTAKE / p.name)
    r = subprocess.run([sys.executable, "scripts/intake_watch.py", "--apply"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-3000:])
    ok = []
    for p in sheets:
        bad = INTAKE / "todo" / (p.stem + ".不備.txt")
        if bad.is_file():
            shutil.copy2(bad, INBOX / bad.name)
            print(f"× {p.name}: 不備があります → {bad.name} を見て直し、もう一度実行してください")
        elif (INTAKE / p.name).exists():
            print(f"? {p.name}: 処理されませんでした（上の表示を確認してください）")
        else:
            shutil.move(str(p), str(DONE_D / p.name))
            old = INBOX / (p.stem + ".不備.txt")
            if old.is_file():
                old.unlink()
            ok.append(p.name)
            print(f"○ {p.name}: 登録しました")
    if ok:
        # 登録された設定だけをコミットする（シートは intake/ にあり、コミットされない）
        paths = [x for x in ("sites", "data/clients", "docs") if (ROOT / x).exists()]
        subprocess.run(["git", "add", *paths], cwd=ROOT)
        c = subprocess.run(["git", "commit", "-q", "-m", f"クライアントの登録（ヒアリングシート {len(ok)}件）"], cwd=ROOT)
        if c.returncode == 0:
            for _ in range(3):
                if subprocess.run(["git", "pull", "-q", "--rebase", "--autostash"], cwd=ROOT).returncode == 0 and \
                        subprocess.run(["git", "push", "-q"], cwd=ROOT).returncode == 0:
                    print("公開しました（次の自動実行から、この会社の記事・動画・SNSが回ります）")
                    break
            else:
                print("公開できませんでした。git の状態を確認してください")
        print("動画・SNSは、先方に当社を管理者に追加してもらった後、接続の手続き（youtube_upload.py --auth --site <id> など）が要ります")
    return 0


if __name__ == "__main__":
    sys.exit(main())
