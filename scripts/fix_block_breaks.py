# -*- coding: utf-8 -*-
"""段落の切れ目が壊れている箇所を直す。

自動でリンク文を挿し込む工程と、長い段落を分ける工程が、それぞれ別の壊し方を
していた。どちらも画面に出て初めて分かる崩れで、記事の点数には出ない。

1. 空行なしで表・箇条書き・番号リストが続く（実測62箇所）
   Markdownは前の段落の続きとして扱う。表がパイプ記号のまま本文に出る。
2. 段落が「**」の内側で分かれている（実測32箇所）
   閉じる「**」が次の段落へ残り、記事に ** がそのまま表示される。

どちらも地の文は変えない。空行を足すか、分かれた段落を戻すだけ。

  python scripts/fix_block_breaks.py           # どこが崩れているか見る
  python scripts/fix_block_breaks.py --write   # 直す
"""
import argparse
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 前に空行が要るもの。行頭が表・箇条書き・番号リスト・引用・見出し
BLOCK = re.compile(r"[ 　]*(?:[0-9０-９]+[.．][ 　]|[-*+][ 　]|\||>[ 　]|#{2,6}[ 　])")
MARKS = ("**", "==", "`")


def add_blank_lines(body):
    """空行なしで続くブロックの前に、空行を1つ入れる"""
    lines = body.split("\n")
    out, fence, n = [], False, 0
    for i, cur in enumerate(lines):
        if cur.lstrip().startswith("```"):
            fence = not fence
        prev = lines[i - 1] if i else ""
        if (not fence and i and prev.strip() and cur.strip()
                and not BLOCK.match(prev) and not prev.lstrip().startswith("<")
                and BLOCK.match(cur)):
            out.append("")
            n += 1
        out.append(cur)
    return "\n".join(out), n


def rejoin_marks(body):
    """装飾の途中で分かれた段落を、元の1段落に戻す"""
    parts = re.split(r"(\n\s*\n)", body)
    out, n, i = [], 0, 0
    while i < len(parts):
        cur = parts[i]
        # 奇数個の装飾で終わっていて、次の段落も奇数個なら、分かれている
        if (i + 2 < len(parts) and parts[i + 1].strip() == ""
                and any(cur.count(m) % 2 for m in MARKS)
                and any(parts[i + 2].count(m) % 2 for m in MARKS)
                and not BLOCK.match(parts[i + 2])):
            out.append(cur.rstrip() + "\n" + parts[i + 2].lstrip())
            n += 1
            i += 3
            continue
        out.append(cur)
        i += 1
    return "".join(out), n


def strong_in_html(body):
    """生HTMLブロックの中の「**」を <strong> に直す

    Markdownは raw HTML ブロックの中身を処理しない。注意ボックスの中に
    「**罰金**」と書くと、記事に ** がそのまま出る（実測8本）。
    """
    n = 0

    def one(line):
        nonlocal n
        if not line.lstrip().startswith("<") or "**" not in line:
            return line
        new, k = re.subn(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", line)
        n += k
        return new

    return "\n".join(one(x) for x in body.split("\n")), n


def plain(s):
    """読者が読む文字だけを残す。装飾記法とタグの差は見ない"""
    return re.sub(r"<[^>]+>|[*=`]|\s", "", s)


def run(write):
    blanks = joins = strongs = touched = 0
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = io.open(p, encoding="utf-8-sig").read()
        m = re.match(r"^(---\s*\n.*?\n---\s*\n)(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.groups()
        if not re.search(r"^score:\s*(9[0-9]|100)\s*$", fm, re.M):
            continue
        nb, a = add_blank_lines(body)
        nb, b = rejoin_marks(nb)
        nb, c = strong_in_html(nb)
        if not (a or b or c):
            continue
        # 地の文が1字でも変わったら触らない。空行の増減と結合しかしていないはず
        if plain(body) != plain(nb):
            print(f"  × {p.stem}: 前後で本文が変わりました。書き換えません")
            continue
        blanks += a
        joins += b
        strongs += c
        touched += 1
        print(f"  {p.stem[:44]:<44} 空行{a:>2}  結合{b:>2}  強調{c:>2}")
        if write:
            io.open(p, "w", encoding="utf-8", newline="").write(fm + nb)
    return touched, blanks, joins, strongs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    print("■ 段落の切れ目が壊れている箇所\n")
    n, b, j, s = run(a.write)
    print(f"\n  {n}本 / 空行{b}箇所・結合{j}箇所・強調{s}箇所"
          + ("を直しました" if a.write else "が対象です（--write で実行）"))
    if a.write and n:
        print("  次: python scripts/build.py で検査してください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
