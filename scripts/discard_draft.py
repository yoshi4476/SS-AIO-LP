# -*- coding: utf-8 -*-
"""その回に書いた原稿（git でまだ追跡していないもの）を1本だけ消す。記事を書く AI に渡す唯一の「消す」道具。

**なぜ要るか**: 記事の AI の許可に `Bash(rm articles/*)` があり、`rm articles/*` でも一致して全記事を消せた。
AI は外の文章（字幕・検索上位の見出し）を読むので、仕込まれた指示に従う可能性がある。消した分は後の
`git add -A` でコミットされ、お客様の原稿は非公開の置き場へ「削除」として push される（2026-10-11 の点検）。
そこで、消せるのを「その回に作った、git で追跡していない原稿」に限る。

消さないもの（理由を出して何もしない）:
  - slug が英小文字・数字・ハイフン以外を含む（../ やパスの区切りで articles/ の外を指せないように）
  - git で追跡している記事（公開済み・コミット済み。取り下げは 301 つきの機械の手順が行う）
  - git から外している原稿（お客様の社の原稿。非公開の置き場から重ねて置いたもの）
  - 非公開の置き場に同じ原稿がある

  python scripts/discard_draft.py <slug>
出す印: DISCARD_OK=yes（消した）/ DISCARD_OK=no（消していない。理由つき）。消していなければ終了コード 1
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,150}")


def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _private_base(root):
    import private_store
    return private_store.base(root)


def discard(slug, root=ROOT):
    """消せたら (True, 説明)、消さなければ (False, 理由)"""
    root = Path(root)
    if not SLUG.fullmatch(slug or ""):
        return False, "slug は英小文字・数字・ハイフンだけで書いてください（パスや .. は使えません）"
    rel = f"articles/{slug}.md"
    p = root / "articles" / f"{slug}.md"
    if p.is_symlink() or not p.is_file():
        return False, f"{rel} がありません"
    if p.resolve().parent != (root / "articles").resolve():
        return False, f"{rel} が articles/ の外を指しています"
    # 壊れた .git から親のリポジトリへさかのぼって判定しない（その場所が git の根であることを確かめる）
    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode or Path(top.stdout.strip()).resolve() != root.resolve():
        return False, "git の作業場所の根で動いていないため、追跡しているか確かめられません"
    tracked = _git(root, "ls-files", "--", rel)
    if tracked.returncode or tracked.stdout.strip():
        return False, f"{rel} は git で追跡している記事（公開済み・コミット済み）なので消しません"
    others = _git(root, "ls-files", "--others", "--exclude-standard", "--", rel)
    if others.returncode or others.stdout.strip() != rel:
        return False, f"{rel} は git から外している原稿（お客様の社の原稿など）なので消しません"
    if (_private_base(root) / "articles" / f"{slug}.md").exists():
        return False, f"{rel} は非公開の置き場にも同じ原稿があるので消しません"
    p.unlink()
    return True, f"{rel} を消しました（この回に書いた、まだ追跡していない原稿）"


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("使い方: python scripts/discard_draft.py <slug>（1本ずつ。slug は英小文字・数字・ハイフン）")
        print("DISCARD_OK=no")
        return 1
    ok, msg = discard(args[0])
    print(msg)
    print(f"DISCARD_OK={'yes' if ok else 'no'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
