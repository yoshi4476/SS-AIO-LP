# -*- coding: utf-8 -*-
"""無料診断ツールへの内部リンクを、該当カテゴリの記事から張る。

ツールはリード獲得の入口だが、記事から1本もリンクされていなかった。
そのため「meo診断」で診断ツールではなくカテゴリ一覧が出ていた。
アンカーは検索されている言葉そのままにする。
"""
import glob, re
from pathlib import Path

TOOLS = {
    "meo": ("/diagnosis/meo/", "MEO診断（無料・30秒）",
            "自院のマップ集客がいまどの状態かは、"),
    "aio": ("/diagnosis/aio/", "AI検索の対応度チェック（無料・30秒）",
            "自社サイトがAI検索にどこまで対応できているかは、"),
}
MAX_PER_CAT = 6      # 張りすぎるとリンク集になる


def main(write=False):
    for cat, (url, anchor, lead) in TOOLS.items():
        files = [f for f in sorted(glob.glob("articles/*.md"))
                 if re.search(rf"^category:\s*{cat}\s*$",
                              Path(f).read_text(encoding="utf-8-sig"), re.M)]
        done = 0
        for f in files:
            if done >= MAX_PER_CAT:
                break
            p = Path(f)
            t = p.read_text(encoding="utf-8-sig")
            if url in t:
                continue
            # まとめの直前に置く。読み終えて次に動く場所
            m = re.search(r"^## まとめ", t, re.M)
            if not m:
                continue
            line = f"\n{lead}[{anchor}]({url})で確かめられます。登録は不要です。\n\n"
            print(f"   {p.stem[:38]:<40}→ {anchor}")
            if write:
                p.write_text(t[:m.start()] + line + t[m.start():],
                             encoding="utf-8", newline="")
            done += 1
        print(f"  {cat}: {'追加' if write else '候補'} {done}本\n")


if __name__ == "__main__":
    import sys
    main("--write" in sys.argv)
