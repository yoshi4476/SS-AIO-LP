# -*- coding: utf-8 -*-
"""記事アイキャッチ生成（画像生成API未設定時のフォールバック / Phase 6用）

使い方:
    python scripts/make_eyecatch.py <slug> <カテゴリ名> <タイトル1行目> [タイトル2行目]
例:
    python scripts/make_eyecatch.py aio-taisaku-guide "AIO・LLMO運用" "AIO対策とは？" "AI検索に引用される5つの手順"

出力: site/images/<slug>/eyecatch.png (1200x675)
記事フロントマターに eyecatch: /images/<slug>/eyecatch.png を追記して使用する。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1200, 675

CAT_COLORS = {
    "AIO・LLMO運用": (37, 99, 235),
    "SEO運用": (79, 70, 229),
    "MEO運用": (13, 148, 136),
    "AI集客・活用全般": (2, 132, 199),
}


FONT_PATHS = [
    # Windows（ローカル実行）
    r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc",
    # Linux/GitHub Actions（fonts-noto-cjk。ディストリによって配置が異なる）
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
    raise SystemExit("日本語フォントが見つかりません（Linuxは fonts-noto-cjk を、"
                     "Windowsは游ゴシック/メイリオを確認）。文字化け画像の生成を防ぐため中断します")


def main():
    slug, cat = sys.argv[1], sys.argv[2]
    lines = [x for x in sys.argv[3:5] if x]
    accent = CAT_COLORS.get(cat, (37, 99, 235))

    img = Image.new("RGB", (W, H))
    px = img.load()
    c1, c2 = (13, 53, 133), (59, 130, 246)
    for y in range(H):
        for x in range(0, W, 4):
            t = (x / W + y / H) / 2
            col = tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))
            for dx in range(4):
                if x + dx < W:
                    px[x + dx, y] = col

    d = ImageDraw.Draw(img)
    for gy in range(30, H, 44):
        for gx in range(30, W, 44):
            d.ellipse([gx, gy, gx + 2, gy + 2], fill=(255, 255, 255))

    # カテゴリバッジ
    bf = font(26)
    tw = d.textlength(cat, font=bf)
    d.rounded_rectangle([80, 88, 80 + tw + 56, 140], radius=26, fill=accent)
    d.text((80 + 28 + tw / 2, 114), cat, font=bf, fill=(255, 255, 255), anchor="mm")

    # タイトル（1〜2行）
    tf = font(64)
    y0 = 260 if len(lines) > 1 else 300
    for i, line in enumerate(lines):
        d.text((80, y0 + i * 90), line, font=tf, fill=(255, 255, 255), anchor="lm")

    # フッター帯（公式ロゴ白版）
    d.rectangle([0, H - 92, W, H], fill=(11, 36, 71))
    logo_path = ROOT / "site" / "images" / "company" / "logo-white.png"
    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        lh = 52
        lw = int(logo.width * lh / logo.height)
        logo = logo.resize((lw, lh), Image.LANCZOS)
        img.paste(logo, (80, H - 46 - lh // 2), logo)
        tx = 80 + lw + 28
    else:
        tx = 80
    d.text((tx, H - 46), "AI集客ラボ", font=font(30), fill=(255, 255, 255), anchor="lm")
    d.text((W - 80, H - 46), "セブンセンシズ株式会社", font=font(22), fill=(163, 196, 243), anchor="rm")

    out = ROOT / "site" / "images" / slug / "eyecatch.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print("saved:", out)


if __name__ == "__main__":
    main()
