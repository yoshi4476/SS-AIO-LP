"""CI の AI（claude -p）に読ませる CLAUDE.md を、その仕事に要る章だけに絞る（トークンと時間を減らす）。

claude は起動時に CLAUDE.md（約7.8万字）を文脈に入れ、1手ごとに読み直す。記事を書く AI は1本で100手を超えるので、
受託の導入・納品方式・週次の工程表・スプレッドシートの列といった、書く仕事に使わない章が毎手の大半を占めていた。

  python scripts/agent_memory.py --slim writer   # 0章・Phase 1〜6（在庫の作り方を除く）・6章・付録だけにする
  python scripts/agent_memory.py --slim weekly   # writer に 8章（週次最適化）を足す
  python scripts/agent_memory.py --restore       # HEAD の CLAUDE.md へ戻す
  python scripts/agent_memory.py --show writer   # 絞った版の字数を見る（書き換えない）

--slim / --restore は CI（GITHUB_ACTIONS）でだけ書き換える（手元の CLAUDE.md を消さないため）。
戻し損ねても、agent_guard.protect が CLAUDE.md を守る場所として HEAD へ戻す。
"""
import argparse
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "CLAUDE.md"
MARK = "<!-- agent_memory:slim -->"
KEEP = {"writer": ("0.", "4.", "6.", "付録"), "weekly": ("0.", "4.", "6.", "8.", "付録")}
DROP_SUB = ("Phase 7",)


def _blocks(text, level):
    """見出し（level 個の #）で分ける。コードブロックの中の見出しでは分けない（3章・7章の例に ## がある）"""
    out, cur, fence = [], [], False
    head = "#" * level + " "
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith(head) and cur:
            out.append("".join(cur))
            cur = []
        cur.append(line)
    if cur:
        out.append("".join(cur))
    return out


def _title(block, level):
    first = block.splitlines()[0] if block else ""
    return first[level + 1:].strip() if first.startswith("#" * level + " ") else ""


def slim(text, profile):
    keep = KEEP[profile]
    parts = []
    for b in _blocks(text, 2):
        t = _title(b, 2)
        if not t:
            parts.append(b)
        elif t.startswith(keep):
            if t.startswith("4."):
                b = "".join(s for s in _blocks(b, 3) if not _title(s, 3).startswith(DROP_SUB))
                # Phase 1 の在庫の作り方（ラッコの枠・単価）は機械の工程。書く AI は使わない
                b = re.sub(r"(?ms)^-1\. \*\*在庫の作り方.*?(?=^0\. \*\*)", "", b)
            parts.append(b)
    note = (f"{MARK}\n> CI の AI 用に、この仕事に要る章だけを載せた版（{profile}）。全文は git の CLAUDE.md。"
            "載っていない章（導入・納品方式・週次の工程・守秘の置き場など）は機械の工程が受け持つ。\n\n")
    # 3.0 章は導入の手順なので外すが、「受託運用での分離」（お客様の記事に当社の実績を書かない）だけは書く仕事の決まり。
    # 章ごと外していたので、お客様の社の記事を書く AI に届いていなかった（2026-10-20 の点検）。見出しにせず段落だけ残す
    sep = re.search(r"(?m)^\*\*受託運用での分離\*\*.*$", text)
    if sep:
        note += sep.group(0).strip() + "\n\n"
    return note + "".join(parts)


def _backup(root):
    """絞る前の写しの置き場（.git の中。作業コピーに出ないので commit されない）"""
    g = Path(root) / ".git"
    return (g if g.is_dir() else Path(root)) / "agent_memory_full.md"


def _ci():
    return bool(os.environ.get("GITHUB_ACTIONS"))


def write_slim(profile, root=None):
    doc = Path(root or ROOT) / "CLAUDE.md"
    if not _ci() and root is None:
        print("AGENT_MEMORY=skip（手元では CLAUDE.md を書き換えない）")
        return False
    text = doc.read_text(encoding="utf-8")
    if text.startswith(MARK):
        return False
    s = slim(text, profile)
    _backup(doc.parent).write_text(text, encoding="utf-8")
    doc.write_text(s, encoding="utf-8")
    print(f"AGENT_MEMORY=slim（{profile}: {len(text):,}字 → {len(s):,}字）")
    return True


def restore(root=None):
    root = Path(root or ROOT)
    if not _ci() and root == ROOT:
        return
    doc = root / "CLAUDE.md"
    if not doc.read_text(encoding="utf-8").startswith(MARK):
        return
    # 絞る前の写しを書き戻す（git checkout は作業コピーの未コミットの直しを巻き込むので使わない）。写しが無ければ HEAD の中身
    bk = _backup(root)
    full = bk.read_text(encoding="utf-8") if bk.exists() else subprocess.run(
        ["git", "-C", str(root), "show", "HEAD:CLAUDE.md"], capture_output=True, text=True, encoding="utf-8").stdout
    if full and not full.startswith(MARK):
        doc.write_text(full, encoding="utf-8")
        bk.unlink(missing_ok=True)
        print("AGENT_MEMORY=restored")


@contextmanager
def slimmed(profile="writer"):
    """AI を呼ぶ間だけ絞る（外側で絞ってあれば触らない）"""
    did = write_slim(profile) if _ci() else False
    try:
        yield
    finally:
        if did:
            restore()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slim", choices=sorted(KEEP))
    ap.add_argument("--show", choices=sorted(KEEP))
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()
    if a.show:
        text = DOC.read_text(encoding="utf-8")
        print(f"{a.show}: {len(text):,}字 → {len(slim(text, a.show)):,}字")
    elif a.slim:
        write_slim(a.slim)
    elif a.restore:
        restore()
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
