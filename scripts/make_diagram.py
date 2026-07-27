# -*- coding: utf-8 -*-
"""記事本文用のステップ図解を生成（画像生成API未設定時のPhase 6フォールバック）

日本語はWindowsシステムフォント（游ゴシック/メイリオ）で直接描画するため
文字化けは発生しない。英語テキストは使用しない方針（CLAUDE.md 画像ルール準拠）。

使い方:
    python scripts/make_diagram.py <slug> <ファイル名> <タイトル> <ステップ1> <ステップ2> ...
    ステップ内の改行は「|」で指定。ステップ数は2〜5。
例:
    python scripts/make_diagram.py aio-taisaku-guide steps "AIO対策の5つの手順" "検索10位|以内に入る" "冒頭で|断言する" ...

出力: site/images/<slug>/<ファイル名>.png (1200x400)
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1200, 400
NAVY = (11, 36, 71)
BLUE = (37, 99, 235)
SKY = (234, 242, 254)
LINE = (211, 224, 240)
BG = (245, 248, 252)


FONT_PATHS = [
    # Windows（ローカル実行）
    r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc",
    # Linux/GitHub Actions（fonts-noto-cjk）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]


def font(size):
    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    raise SystemExit("日本語フォントが見つかりません（文字化け防止のため中断）")


def main():
    slug, name, title = sys.argv[1], sys.argv[2], sys.argv[3]
    steps = sys.argv[4:9]
    n = len(steps)
    if n < 2:
        raise SystemExit("ステップは2〜5個で指定してください")

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for gy in range(24, H, 40):
        for gx in range(24, W, 40):
            d.ellipse([gx, gy, gx + 2, gy + 2], fill=(220, 230, 244))

    d.rounded_rectangle([40, 36, 52, 76], radius=6, fill=BLUE)
    d.text((68, 56), title, font=font(30), fill=NAVY, anchor="lm")

    margin, gap, top, bh = 60, 34, 130, 200
    bw = (W - margin * 2 - gap * (n - 1)) // n
    tf = font(26 if bw > 200 else 23)
    nf = font(22)

    for i, step in enumerate(steps):
        x = margin + i * (bw + gap)
        d.rounded_rectangle([x + 4, top + 8, x + bw + 4, top + bh + 8], radius=16, fill=(225, 233, 245))
        d.rounded_rectangle([x, top, x + bw, top + bh], radius=16, fill=(255, 255, 255), outline=LINE, width=2)
        d.rounded_rectangle([x, top, x + bw, top + 8], radius=4, fill=BLUE)
        d.ellipse([x + bw / 2 - 22, top + 26, x + bw / 2 + 22, top + 70], fill=SKY)
        d.text((x + bw / 2, top + 48), str(i + 1), font=nf, fill=BLUE, anchor="mm")
        lines = step.split("|")
        y0 = top + 118 - (len(lines) - 1) * 19
        for j, line in enumerate(lines):
            d.text((x + bw / 2, y0 + j * 38), line, font=tf, fill=NAVY, anchor="mm")
        if i < n - 1:
            ax = x + bw + gap / 2
            d.polygon([(ax - 9, top + bh / 2 - 12), (ax + 9, top + bh / 2), (ax - 9, top + bh / 2 + 12)], fill=BLUE)

    d.text((W - 40, H - 28), "AI集客ラボ（セブンセンシズ株式会社）", font=font(16), fill=(122, 140, 165), anchor="rm")

    out = ROOT / "site" / "images" / slug / f"{name}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print("saved:", out)


if __name__ == "__main__":
    main()
