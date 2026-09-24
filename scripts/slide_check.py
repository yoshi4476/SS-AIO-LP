# -*- coding: utf-8 -*-
"""スライドの文字が、重なっていないか・はみ出していないかを機械で調べる。

**なぜ要るか**: 1本の動画に127枚のスライドが入る。目で全部見るのは現実的でない。
実際に「文字の重なりがある」という指摘を受けたが、どの枚かは分からなかった。

見るのは2つ。
  重なり   同じ行に2つの文字列を置く型（ターミナルの「名前 … 結果」）で、
           左の文字列が右の開始位置を越えていないか
  はみ出し 文字列が、置き場（パネル・セル・箱）の右端を越えていないか

    python scripts/slide_check.py            # 3本ぜんぶ
    python scripts/slide_check.py --only demo
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

NAMES = {"pr": "sales_script_pr", "demo": "sales_script_demo", "doc": "sales_script_doc"}


def check(segs, label):
    from PIL import Image, ImageDraw
    import video_make as V

    d = ImageDraw.Draw(Image.new("RGB", (V.W, V.H)))
    bad = []
    for i, s in enumerate(segs, 1):
        kind = s.get("kind")

        if kind == "term":
            x0, x1 = 110, V.W - 110
            rows = s.get("term", [])[:14]
            # 列の位置は video_slides.term と同じ計算で出す。
            # 描く側と違う前提で数えると、直したのに件数が減らず信用できなくなる
            col = 0
            for text, style in rows:
                if "…" in text and style in ("ok", "ng"):
                    f = V.font(31 if style in ("ng", "hi") else 28)
                    col = max(col, d.textlength(text.split("…", 1)[0].rstrip(), font=f))
            col = 36 + col + 28
            fits = col < (x1 - x0) * 0.62
            for text, style in rows:
                if style == "rule":
                    continue
                f = V.font(31 if style in ("ng", "hi") else 28)
                if fits and "…" in text and style in ("ok", "ng"):
                    left, right = text.split("…", 1)
                    if 36 + d.textlength(left.rstrip(), font=f) > col - 12:
                        bad.append((i, "重なり", f"{left.strip()[:26]} … 左が右の列に食い込む"))
                    if x0 + col + d.textlength("…" + right, font=f) > x1 - 20:
                        bad.append((i, "はみ出し", f"{right.strip()[:26]}（右端を越える）"))
                else:
                    # 列をそろえない行は、1行そのままの幅で見る
                    if x0 + 36 + d.textlength(text, font=f) > x1 - 20:
                        bad.append((i, "はみ出し", f"{text[:34]}（パネルの右端を越える）"))

        elif kind == "gate":
            for ln in s.get("checks", []):
                if 166 + d.textlength(ln, font=V.font(26)) > 740 - 20:
                    bad.append((i, "はみ出し", f"検査項目「{ln[:26]}」"))

        elif kind == "table":
            head, rows = s.get("table", ([], []))
            ws = s.get("widths") or ([1 / len(head)] * len(head) if head else [])
            x0, x1 = 100, V.W - 100
            for c, w in zip(head, ws):
                if d.textlength(c, font=V.font(28)) > (x1 - x0) * w - 46:
                    bad.append((i, "はみ出し", f"表の見出し「{c}」"))

        elif kind == "cards":
            items = s.get("cards", [])[:3]
            if items:
                cw = (V.W - 180 - 46 * (len(items) - 1)) // len(items)
                for big, lab, _ in items:
                    if d.textlength(lab, font=V.fit(d, lab, cw - 80, 38, 24)) > cw - 80:
                        bad.append((i, "はみ出し", f"札の見出し「{lab[:22]}」"))

    print(f"■ {label}（{len(segs)}区間）  見つかった問題 {len(bad)}件")
    for i, why, what in bad[:40]:
        print(f"   区間{i:>4} [{why}] {what}")
    return len(bad)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=list(NAMES))
    a = ap.parse_args()
    from sales_common import expand

    total = 0
    for key, mod in NAMES.items():
        if a.only and key != a.only:
            continue
        total += check(expand(__import__(mod).script()["segments"]), key)
    print(f"\n合計 {total}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
