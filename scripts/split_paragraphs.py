# -*- coding: utf-8 -*-
"""長すぎる段落を、文の切れ目で分ける。

CLAUDE.md の文章ルールは「段落3行 or 150字以内」。実測すると、
91〜92点で止まっている記事はほぼ全部これを外していた。読みにくいだけでなく、
AI検索も長い塊からは一文を切り出しにくい。

文の途中では絶対に切らない。「。」の直後だけで分け、分けたあとに
文字が1字でも増減していたらその記事は書き換えない。

  python scripts/split_paragraphs.py <slug>          # どう分かれるか見る
  python scripts/split_paragraphs.py <slug> --write  # 実際に分ける
  python scripts/split_paragraphs.py --all --write   # 公開記事すべて
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 200          # これを超える段落を対象にする（規定150字＋余裕）
KEEP = 90            # 分けたあと、片側がこれ未満になるなら分けない


def plain(s):
    return re.sub(r"<[^>]+>|\s", "", s)


def splittable(p):
    """その段落を触ってよいか。表・リスト・HTMLの塊は触らない"""
    if p.lstrip().startswith(("|", "-", "*", ">", "#", "<")):
        return False
    if "|:--" in p or "<div" in p or "<figure" in p or "<details" in p:
        return False
    return len(plain(p)) > LIMIT


def split_one(p):
    """真ん中に近い「。」で2つに分ける。文の途中では切らない"""
    # 「。」の位置（閉じ括弧が続くときはその後ろまで含める）
    ends = [m.end() for m in re.finditer(r"。(?:[」』）\)]+)?", p)]
    ends = [e for e in ends if e < len(p)]      # 末尾の「。」では分けられない
    if not ends:
        return None
    # 装飾の内側では切らない。「**失敗1: 〜。」で切ると、閉じる ** が次の段落へ
    # 残り、記事に ** がそのまま表示される（実測32箇所）
    ends = [e for e in ends if p[:e].count("**") % 2 == 0
            and p[:e].count("==") % 2 == 0 and p[:e].count("`") % 2 == 0]
    if not ends:
        return None
    mid = len(p) / 2
    best = min(ends, key=lambda e: abs(e - mid))
    a, b = p[:best].strip(), p[best:].strip()
    if len(plain(a)) < KEEP or len(plain(b)) < KEEP:
        return None                              # 片方が短すぎる。分けない
    return a, b


def _pass(body):
    """1周ぶん。分けられるものを分けて、(本文, 分けた数) を返す"""
    parts = re.split(r"(\n\n+)", body)
    out, n = [], 0
    for x in parts:
        if x.startswith("\n") or not splittable(x):
            out.append(x)
            continue
        r = split_one(x)
        if r:
            out.append(r[0] + "\n\n" + r[1])
            n += 1
        else:
            out.append(x)
    return "".join(out), n


def process(text, rounds=4):
    """本文を受け取り、(新しい本文, 分けた数) を返す。

    1回分けても長いままの段落が残る（400字なら2回、600字なら3回要る）。
    分けられなくなるまで繰り返す。
    """
    m = re.match(r"^(---\s*\n.*?\n---\s*\n)(.*)$", text, re.S)
    if not m:
        return text, 0
    fm, body = m.groups()
    total = 0
    for _ in range(rounds):
        body, n = _pass(body)
        total += n
        if not n:
            break
    return fm + body, total


def run(slug, write):
    p = ROOT / "articles" / f"{slug}.md"
    if not p.is_file():
        print(f"  ! {slug} が見つかりません")
        return 0
    before = p.read_text(encoding="utf-8")
    after, n = process(before)
    if not n:
        return 0
    # 文字が1字でも増減したら触らない。分けるだけなので、地の文は変わらないはず
    if plain(before.partition("---\n")[2]) != plain(after.partition("---\n")[2]):
        print(f"  × {slug}: 分ける前後で本文が変わりました。書き換えません")
        return 0
    def count_long(s):
        b = re.match(r"^---\s*\n.*?\n---\s*\n(.*)$", s, re.S)
        return sum(1 for x in re.split(r"\n\n+", b.group(1) if b else s)
                   if len(plain(x)) > LIMIT)

    long_before, long_after = count_long(before), count_long(after)
    print(f"  {slug[:40]:<40} 長い段落 {long_before} → {long_after}（{n}箇所で分割）")
    if write:
        p.write_text(after, encoding="utf-8", newline="")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", default="")
    ap.add_argument("--all", action="store_true", help="公開記事すべてを対象にする")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    if a.all:
        targets = []
        for p in sorted((ROOT / "articles").glob("*.md")):
            t = p.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"^score:\s*(\d+)", t, re.M)
            if m and int(m.group(1)) >= 90:
                targets.append(p.stem)
    elif a.slug:
        targets = [a.slug]
    else:
        raise SystemExit(__doc__.strip())

    print(f"■ 長い段落を分ける（{LIMIT}字超が対象）\n")
    total = sum(run(s, a.write) for s in targets)
    print(f"\n  {total}箇所を分けました" if a.write else
          f"\n  {total}箇所が対象です（--write で実行）")
    if a.write and total:
        print("  次: python scripts/build.py で検査してください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
