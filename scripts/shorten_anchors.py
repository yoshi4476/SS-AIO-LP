# -*- coding: utf-8 -*-
"""内部リンクのアンカーテキストを、読める長さに詰める。

自動で入れるリンク文は、記事タイトルをそのままアンカーにしている。
タイトルは45字まで許されるので、前後の文と合わせると1文が100字を超える。
実測で、公開317本のうち49本にこれが原因の警告が残っていた。

リンク先は変えない。表示される文字だけを、意味の切れ目で詰める。
  「飲食店のAI導入補助金 対象要件｜資本金・従業員数など5つの基準【2026年】」
  → 「飲食店のAI導入補助金 対象要件」

  python scripts/shorten_anchors.py           # どう詰まるか見る
  python scripts/shorten_anchors.py --write   # 実際に詰める
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX = 26          # これを超えるアンカーを詰める
MIN = 10          # 詰めた結果これ未満になるなら、詰めない（何の記事か分からなくなる）


def shorten(a):
    """意味の切れ目で詰める。切る場所が無ければそのまま返す"""
    s = a.strip()
    if len(s) <= MAX:
        return s
    # 1) 【2026年】などの囲みを落とす
    t = re.sub(r"[【\[][^】\]]*[】\]]", "", s).strip()
    if MIN <= len(t) <= MAX:
        return t
    # 2)「｜」「|」の前だけ残す（副題を落とす）
    head = re.split(r"[｜|]", t)[0].strip()
    if MIN <= len(head) <= MAX:
        return head
    # 3) 問いかけで終わるならそこまで
    m = re.match(r"^(.{%d,%d}?[？?])" % (MIN, MAX), head)
    if m:
        return m.group(1)
    # 4) 読点で切れるならそこまで
    m = re.match(r"^(.{%d,%d}?)[、。]" % (MIN, MAX), head)
    if m:
        return m.group(1)
    # 5) それでも長い見出しは、意味が崩れるので触らない
    return head if MIN <= len(head) < len(s) else s


def run(write=False):
    changed = collected = 0
    pat = re.compile(r"\[([^\]\n]{%d,})\]\((/[^)\s]+)\)" % (MAX + 1))
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"^score:\s*(\d+)", t, re.M)
        if not m or int(m.group(1)) < 90:
            continue
        hits = list(pat.finditer(t))
        if not hits:
            continue
        new, n = t, 0
        for h in hits:
            a, url = h.group(1), h.group(2)
            s = shorten(a)
            if s != a and MIN <= len(s):
                new = new.replace(f"[{a}]({url})", f"[{s}]({url})")
                n += 1
        if n and new != t:
            collected += n
            changed += 1
            if write:
                p.write_text(new, encoding="utf-8", newline="")
    return changed, collected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    print(f"■ {MAX}字を超えるアンカーを詰める\n")
    # 先に例を見せる（何が起きるか分からないまま走らせない）
    pat = re.compile(r"\[([^\]\n]{%d,})\]\(/" % (MAX + 1))
    seen = set()
    for p in sorted((ROOT / "articles").glob("*.md")):
        for m in pat.finditer(p.read_text(encoding="utf-8", errors="replace")):
            a0 = m.group(1)
            s = shorten(a0)
            if s != a0 and a0 not in seen and len(seen) < 5:
                seen.add(a0)
                print(f"  {a0[:46]}")
                print(f"    → {s}（{len(a0)}字 → {len(s)}字）")
    n_art, n_link = run(a.write)
    print(f"\n  {n_art}本 / {n_link}箇所" + ("を詰めました" if a.write else "が対象です（--write で実行）"))
    if a.write:
        print("  次: python scripts/build.py でリンク切れが無いか検査してください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
