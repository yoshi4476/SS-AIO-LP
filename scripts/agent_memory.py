"""CI の AI（claude -p）に読ませる CLAUDE.md を、その仕事に要る章の全文で組み立てる（トークンと時間を減らす）。

CLAUDE.md は芯（要点と索引・約1万字）だけで、全文は docs/pipeline/*.md に章ごとにある（2026-10-25 に文言を変えずに移した。
PARTS の順につなげると、移す前の CLAUDE.md と1字も違わない）。claude は起動時に CLAUDE.md を文脈に入れ、1手ごとに読み直すので、
書く AI には芯の代わりに、書く仕事に要る章（0章・Phase 1〜5（Phase 1 は AI が行う項目だけ）・6章・付録）の全文を渡す。
2026-10-25: AI が行わない節（Phase 6・Phase 1 の Ahrefs とスプレッドシート・8章の機械の工程）も外した（DROP_SUB・DROP_PHASE1）。

  python scripts/agent_memory.py --slim writer   # 0章・Phase 1〜5・6章・付録の全文にする
  python scripts/agent_memory.py --slim weekly   # writer に 8章のうち週次の AI が使う節（8.1・8.2・8.3・8.6）を足す
  python scripts/agent_memory.py --restore       # 芯の CLAUDE.md へ戻す
  python scripts/agent_memory.py --show writer   # 組み立てた版の字数を見る（書き換えない）

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
PIPELINE = "docs/pipeline"
# つなげる順（ファイルを足したら、ここにも足す。門 h107 が docs/pipeline/ の全ファイルと突き合わせる）
PARTS = ("00-principles.md", "01-overview.md", "02-prereq-confidentiality.md", "03-setup-intake-delivery.md",
         "04-phases.md", "05-schedule.md", "06-quality-rules.md", "07-kpi.md", "08-weekly.md", "09-sheets.md",
         "10-troubleshooting.md", "appendix-checklist.md")
MARK = "<!-- agent_memory:slim -->"
KEEP = {"writer": ("0.", "4.", "6.", "付録"), "weekly": ("0.", "4.", "6.", "8.", "付録")}
# 残す章の中で、AI が行わない節（### の見出しの先頭で外す。見出しを足しても既定では載る＝外し漏れより載せ過ぎに倒す）
DROP_SUB = {
    # Phase 6（画像・ビルド・Schema・sitemap・デプロイ）は publish_flow --check と機械の手順が行い、手順書が commit・push を禁じている。
    # 書き方に効く決まり（図の英字禁止・alt・図の中身を本文にも・FAQ と Schema の一致）は 6章と Phase 5 に同じものがある
    "4.": ("Phase 6", "Phase 7"),
    # 8章のうち週次の AI が行わない節（全部スクリプト・月次・人の工程）。週次の AI の手順（weekly_optimize_prompt）が使う
    # 8.1 カニバリ・8.2 書き直しの基準・8.3 内部リンク・8.6 自動修正の決まり（リンクの段落・言い回し・アンカーの長さ）は残す。
    # 「8.1」と「8.10」を取り違えないよう、番号の後ろの空白まで書く
    "8.": ("8.2.5 ", "8.4 ", "8.5 ", "8.7 ", "8.8 ", "8.9 ", "8.10 ", "8.11 ", "8.13 ", "8.14 ", "8.15 ", "8.16 ", "8.17 "),
}
# Phase 1 の中で AI が行わない項目（re.sub。見つからなければ何も外さない）
DROP_PHASE1 = (
    # 在庫の作り方（ラッコの枠・単価）は機械の工程
    r"(?ms)^-1\. \*\*在庫の作り方.*?(?=^0\. \*\*)",
    # 1〜4（記事作成ログのタブ・Ahrefs の競合・KW・AI Overview の取得）と 6（スプレッドシートの更新）。CI の AI には
    # Ahrefs もスプレッドシートも無く、語は site_brief・kw_status が渡す。0（食い合い）・4.5（開く理由）・5（批判3周）は残す
    r"(?ms)^1\. \*\*記事作成ログの確認\*\*.*?(?=^4\.5\. )",
    r"(?ms)^6\. \*\*KW確定・スプレッドシート更新\*\*.*?(?=\n^### |\Z)",
)


def source(root=None):
    """パイプライン定義の全文（docs/pipeline/ を PARTS の順につなげたもの）。無ければ CLAUDE.md（移す前の形）"""
    root = Path(root or ROOT)
    d = root / PIPELINE
    if all((d / p).is_file() for p in PARTS):
        return "".join((d / p).read_text(encoding="utf-8") for p in PARTS)
    return (root / "CLAUDE.md").read_text(encoding="utf-8")


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
    """全文（source()）から、その仕事に要る章だけを残す"""
    keep = KEEP[profile]
    parts = []
    for b in _blocks(text, 2):
        t = _title(b, 2)
        if not t:
            parts.append(b)
        elif t.startswith(keep):
            drop = next((v for k, v in DROP_SUB.items() if t.startswith(k)), ())
            if drop:
                b = "".join(s for s in _blocks(b, 3) if not _title(s, 3).startswith(drop))
            if t.startswith("4."):
                for pat in DROP_PHASE1:
                    b = re.sub(pat, "", b)
            parts.append(b)
    note = (f"{MARK}\n> CI の AI 用に、この仕事に要る章だけを載せた版（{profile}）。全文は docs/pipeline/。"
            "載っていない章（導入・納品方式・公開の工程（Phase 6・7）・週次の機械の工程・守秘の置き場など）は機械の工程が受け持つ。\n\n")
    # 3.0 章は導入の手順なので外すが、「受託運用での分離」（お客様の記事に当社の実績を書かない）だけは書く仕事の決まり。
    # 章ごと外していたので、お客様の社の記事を書く AI に届いていなかった（2026-10-20 の点検）。見出しにせず段落だけ残す
    sep = re.search(r"(?m)^\*\*受託運用での分離\*\*.*$", text)
    if sep:
        note += sep.group(0).strip() + "\n\n"
    return note + "".join(parts)


def _backup(root):
    """組み立てる前の写しの置き場（.git の中。作業コピーに出ないので commit されない）"""
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
    s = slim(source(doc.parent), profile)
    _backup(doc.parent).write_text(text, encoding="utf-8")
    doc.write_text(s, encoding="utf-8")
    print(f"AGENT_MEMORY=slim（{profile}: 芯 {len(text):,}字 → {len(s):,}字）")
    return True


def restore(root=None):
    root = Path(root or ROOT)
    if not _ci() and root == ROOT:
        return
    doc = root / "CLAUDE.md"
    if not doc.read_text(encoding="utf-8").startswith(MARK):
        return
    # 組み立てる前の写しを書き戻す（git checkout は作業コピーの未コミットの直しを巻き込むので使わない）。写しが無ければ HEAD の中身
    bk = _backup(root)
    full = bk.read_text(encoding="utf-8") if bk.exists() else subprocess.run(
        ["git", "-C", str(root), "show", "HEAD:CLAUDE.md"], capture_output=True, text=True, encoding="utf-8").stdout
    if full and not full.startswith(MARK):
        doc.write_text(full, encoding="utf-8")
        bk.unlink(missing_ok=True)
        print("AGENT_MEMORY=restored")


@contextmanager
def slimmed(profile="writer"):
    """AI を呼ぶ間だけ組み立てた版にする（外側で替えてあれば触らない）"""
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
        full = source()
        print(f"{a.show}: 全文 {len(full):,}字・芯 {len(DOC.read_text(encoding='utf-8')):,}字 → {len(slim(full, a.show)):,}字")
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
