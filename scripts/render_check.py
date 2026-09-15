# -*- coding: utf-8 -*-
"""出来上がったHTMLを読んで、画面の崩れを見つける。

これまでの検査は全部、原稿（Markdown）だけを見ていた。score_check も
build.py の品質検査も原稿しか読まない。そのため「原稿としては正しいが、
変換すると壊れる」種類の崩れが素通りしていた。実際に見逃したもの:

  - 表がパイプ記号のまま本文に出る（62箇所）… 空行が無く前の段落の続き扱い
  - ** が記事にそのまま表示される（282箇所）… 生HTMLの中はMarkdownが効かない
  - [文字](/url/) がそのまま出て押せない（34箇所）… 同上
  - 段落が装飾の内側で分かれ、閉じる ** が次の段落へ残る（19箇所）

どれも記事の点数には出ない。読者の画面にだけ出る。
原稿ではなく**出力**を見る工程を、ビルドの中に置く。

  python scripts/render_check.py          # 検査する
  python scripts/render_check.py --quiet  # 症状がある時だけ出す（build.pyから呼ぶ用）
"""
import argparse
import collections
import html as H
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def readable(page):
    """読者が実際に読む部分だけを取り出す。ヘッダー・スクリプト・コードは外す"""
    m = re.search(r"(?s)<article.*?</article>", page) or \
        re.search(r"(?s)<main.*?</main>", page)
    body = m.group(0) if m else page
    return re.sub(r"(?s)<(script|style|pre|code|textarea).*?</\1>", "", body)


# 症状 → (説明, 見つけ方, 直し方)
SYMPTOMS = [
    ("強調記号がそのまま出ている", lambda t, x: "**" in t,
     "生HTMLブロックの中の ** を <strong> にする（fix_block_breaks.py）"),
    ("Markdownリンクが押せない形で出ている", lambda t, x: "](" in t,
     "生HTMLブロックの中の [文字](url) を <a> にする（fix_block_breaks.py）"),
    ("表の区切り記号が本文に出ている", lambda t, x: "|:--" in t,
     "表の前に空行を入れる（fix_block_breaks.py）"),
    ("見出し記号が本文に出ている", lambda t, x: re.search(r"^\s*#{2,}\s", t, re.M),
     "見出しの前に空行を入れる"),
    ("タグが文字列として出ている", lambda t, x: re.search(r"&lt;(div|p|span|a|strong)\b", x),
     "HTMLがエスケープされている。原稿の記法を確認する"),
    ("押せないリンクがある", lambda t, x: re.search(r"<a[^>]*href=[\"']{2}", x),
     "リンク先が空。原稿のURLを確認する"),
    ("中身の無い見出しがある", lambda t, x: re.search(r"<h[1-6][^>]*>\s*</h[1-6]>", x),
     "見出しだけの行が残っている"),
    ("altの無い画像がある", lambda t, x: re.search(r"<img(?![^>]*\balt=)", x),
     "alt を設定する（AI検索と読み上げが読めない）"),
    ("句点が続いている", lambda t, x: "。。" in t,
     "自動挿入で文が二重になっている"),
]


def scan(pages):
    found = collections.defaultdict(list)
    for f in pages:
        raw = f.read_text(encoding="utf-8", errors="replace")
        x = readable(raw)
        t = H.unescape(re.sub(r"<[^>]+>", "", x))
        for name, test, _ in SYMPTOMS:
            hit = test(t, x)
            if hit:
                s = hit.group(0)[:44] if hasattr(hit, "group") else ""
                found[name].append((f, s))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true", help="症状がある時だけ出す")
    a = ap.parse_args()

    pages = sorted((ROOT / "site").rglob("index.html"))
    if not pages:
        print("  site/ にページがありません。先に build.py を実行してください")
        return 0
    found = scan(pages)
    if not found:
        if not a.quiet:
            print(f"  描画検査: {len(pages)}ページ すべてクリア")
        return 0

    print(f"\n■ 描画の崩れ（{len(pages)}ページを検査）")
    fixes = dict((n, f) for n, _, f in SYMPTOMS)
    for name, hits in sorted(found.items(), key=lambda x: -len(x[1])):
        print(f"\n  {len(hits)}ページ  {name}")
        for f, s in hits[:3]:
            print(f"      {f.parent.name}" + (f"  「{s}」" if s else ""))
        if len(hits) > 3:
            print(f"      ほか{len(hits) - 3}ページ")
        print(f"      → {fixes[name]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
