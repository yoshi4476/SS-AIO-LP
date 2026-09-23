# -*- coding: utf-8 -*-
"""ご提案資料のPDFを、サイトに載せるページ画像にする。

**なぜスクリプトにするか**: これまで手作業で作られており、資料を直すたびに
「何枚を、どの大きさで、どこに置いたか」を思い出す必要があった。
実際、動画だけ新しくなって資料が9月2日のまま残っていた。

出力は `site/images/proposal/pNN.jpg`。コーポレートサイトの
`MediaShowcase.tsx` がこのURLを直接読むため、**名前と枚数を変えたら
先方のコンポーネントも直す**こと（枚数は結果に出す）。

    python scripts/proposal_images.py <資料.pdf>            # 何ができるか見る
    python scripts/proposal_images.py <資料.pdf> --write    # 書き出す
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "images" / "proposal"
DPI = 110          # 横1600px前後。これ以上上げても、横スクロールの表示では差が出ない
QUALITY = 82


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf", help="ご提案資料のPDF")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--skip", type=int, nargs="*", default=[],
                    help="載せないページ番号（1始まり。料金のページを外すときなど）")
    a = ap.parse_args()

    src = Path(a.pdf)
    if not src.is_file():
        raise SystemExit(f"見つかりません: {src}")

    import pymupdf
    doc = pymupdf.open(src)
    pages = [i for i in range(doc.page_count) if (i + 1) not in a.skip]
    old = sorted(OUT.glob("p*.jpg"))
    print(f"■ {src.name}（{doc.page_count}ページ）")
    print(f"   いま置いてある画像: {len(old)}枚")
    print(f"   書き出す枚数: {len(pages)}枚"
          + (f"（{a.skip} を除外）" if a.skip else ""))

    if not a.write:
        print("\n  --write を付けると書き出します")
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    for p in old:
        p.unlink()
    for n, i in enumerate(pages, 1):
        pix = doc[i].get_pixmap(dpi=DPI)
        f = OUT / f"p{n:02d}.jpg"
        pix.pil_save(f, format="JPEG", quality=QUALITY, optimize=True)
        if n == 1:
            print(f"   1枚目: {pix.width}×{pix.height}px")
    total = sum(f.stat().st_size for f in OUT.glob("p*.jpg")) / 1048576
    print(f"   → {len(pages)}枚 / 合計 {total:.1f}MB  {OUT}")
    print(f"\n  ※ コーポレートの MediaShowcase.tsx は枚数を直接書いています。"
          f"{len(pages)}枚に合わせて直してください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
