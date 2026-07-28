# -*- coding: utf-8 -*-
"""記事本文用の図解を生成（画像生成API未設定時のPhase 6フォールバック）

日本語はシステムフォント（Windows: 游ゴシック / Linux: Noto Sans CJK）で直接描画するため
文字化けは発生しない。英語テキストは使用しない方針（CLAUDE.md 画像ルール準拠）。
テキストは各ボックス幅に合わせて自動縮小するため、はみ出しは発生しない。

使い方:
    フロー型（従来互換・2〜5ステップ。改行は「|」）:
      python scripts/make_diagram.py <slug> <ファイル名> <タイトル> <ステップ1> <ステップ2> ...
    チェックリスト型（3〜6項目）:
      python scripts/make_diagram.py --type list <slug> <ファイル名> <タイトル> <項目1> <項目2> ...
    比較型（左右2カラム。各引数は「見出し|行1|行2|...」）:
      python scripts/make_diagram.py --type vs <slug> <ファイル名> <タイトル> <左カラム> <右カラム>

出力: site/images/<slug>/<ファイル名>.png
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W = 1200
NAVY = (11, 36, 71)
BLUE = (37, 99, 235)
SKY = (234, 242, 254)
LINE = (211, 224, 240)
BG = (245, 248, 252)
RED = (185, 28, 28)
REDBG = (254, 242, 242)

FONT_PATHS = [
    r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc",
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


def fit_font(d, text, max_width, base=26, minimum=16):
    """max_widthに収まるフォントサイズを返す（はみ出しの構造的防止）"""
    for size in range(base, minimum - 1, -2):
        if d.textlength(text, font=font(size)) <= max_width:
            return font(size)
    return font(minimum)


def save_png(img, slug, name):
    out = ROOT / "site" / "images" / slug / f"{name}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT).save(out, "PNG", optimize=True)
    print(f"saved: {out} ({out.stat().st_size // 1024}KB)")


def canvas(h, title):
    img = Image.new("RGB", (W, h), BG)
    d = ImageDraw.Draw(img)
    for gy in range(24, h, 40):
        for gx in range(24, W, 40):
            d.ellipse([gx, gy, gx + 2, gy + 2], fill=(220, 230, 244))
    d.rounded_rectangle([40, 36, 52, 76], radius=6, fill=BLUE)
    d.text((68, 56), title, font=fit_font(d, title, W - 148, base=30, minimum=20), fill=NAVY, anchor="lm")
    return img, d


def credit(d, h):
    d.text((W - 40, h - 28), "AI集客ラボ（セブンセンシズ株式会社）", font=font(16), fill=(122, 140, 165), anchor="rm")


def draw_flow(slug, name, title, steps):
    n = len(steps)
    if not 2 <= n <= 5:
        raise SystemExit("フロー型のステップは2〜5個で指定してください")
    H = 400
    img, d = canvas(H, title)
    margin, gap, top, bh = 60, 34, 130, 200
    bw = (W - margin * 2 - gap * (n - 1)) // n
    nf = font(22)
    for i, step in enumerate(steps):
        x = margin + i * (bw + gap)
        d.rounded_rectangle([x + 4, top + 8, x + bw + 4, top + bh + 8], radius=16, fill=(225, 233, 245))
        d.rounded_rectangle([x, top, x + bw, top + bh], radius=16, fill=(255, 255, 255), outline=LINE, width=2)
        d.rounded_rectangle([x, top, x + bw, top + 8], radius=4, fill=BLUE)
        d.ellipse([x + bw / 2 - 22, top + 26, x + bw / 2 + 22, top + 70], fill=SKY)
        d.text((x + bw / 2, top + 48), str(i + 1), font=nf, fill=BLUE, anchor="mm")
        lines = step.split("|")
        tf = min((fit_font(d, ln, bw - 28) for ln in lines), key=lambda f: f.size)
        y0 = top + 118 - (len(lines) - 1) * 19
        for j, line in enumerate(lines):
            d.text((x + bw / 2, y0 + j * 38), line, font=tf, fill=NAVY, anchor="mm")
        if i < n - 1:
            ax = x + bw + gap / 2
            d.polygon([(ax - 9, top + bh / 2 - 12), (ax + 9, top + bh / 2), (ax - 9, top + bh / 2 + 12)], fill=BLUE)
    credit(d, H)
    save_png(img, slug, name)


def draw_list(slug, name, title, items):
    n = len(items)
    if not 3 <= n <= 6:
        raise SystemExit("チェックリスト型の項目は3〜6個で指定してください")
    row_h, top = 74, 120
    H = top + n * row_h + 60
    img, d = canvas(H, title)
    for i, item in enumerate(items):
        y = top + i * row_h
        d.rounded_rectangle([60, y, W - 60, y + row_h - 14], radius=12,
                            fill=(255, 255, 255), outline=LINE, width=2)
        d.ellipse([84, y + 14, 84 + 32, y + 46], fill=BLUE)
        d.line([92, y + 30, 99, y + 38], fill=(255, 255, 255), width=4)
        d.line([99, y + 38, 111, y + 22], fill=(255, 255, 255), width=4)
        d.text((140, y + (row_h - 14) / 2), item,
               font=fit_font(d, item, W - 220, base=26), fill=NAVY, anchor="lm")
    credit(d, H)
    save_png(img, slug, name)


def draw_vs(slug, name, title, left, right):
    lparts, rparts = left.split("|"), right.split("|")
    lhead, litems = lparts[0], lparts[1:]
    rhead, ritems = rparts[0], rparts[1:]
    rows = max(len(litems), len(ritems))
    if rows < 1:
        raise SystemExit("比較型は「見出し|行1|行2...」の形式で指定してください")
    row_h, top, head_h = 56, 120, 64
    H = top + head_h + rows * row_h + 70
    img, d = canvas(H, title)
    gap = 24
    cw = (W - 120 - gap) // 2
    for ci, (head, items, accent, bgc) in enumerate(
            [(lhead, litems, RED, REDBG), (rhead, ritems, BLUE, SKY)]):
        x = 60 + ci * (cw + gap)
        d.rounded_rectangle([x, top, x + cw, top + head_h + rows * row_h + 16], radius=14,
                            fill=(255, 255, 255), outline=LINE, width=2)
        d.rounded_rectangle([x, top, x + cw, top + head_h], radius=14, fill=accent)
        d.rectangle([x, top + head_h - 14, x + cw, top + head_h], fill=accent)
        d.text((x + cw / 2, top + head_h / 2), head,
               font=fit_font(d, head, cw - 40, base=26), fill=(255, 255, 255), anchor="mm")
        mark = "×" if ci == 0 else "○"
        for ri, item in enumerate(items):
            y = top + head_h + ri * row_h
            d.text((x + 30, y + row_h / 2 + 4), mark, font=font(22), fill=accent, anchor="lm")
            d.text((x + 64, y + row_h / 2 + 4), item,
                   font=fit_font(d, item, cw - 92, base=22), fill=NAVY, anchor="lm")
    credit(d, H)
    save_png(img, slug, name)


def main():
    args = sys.argv[1:]
    dtype = "flow"
    if args and args[0] == "--type":
        dtype = args[1]
        args = args[2:]
    slug, name, title = args[0], args[1], args[2]
    rest = args[3:]
    if dtype == "flow":
        draw_flow(slug, name, title, rest[:5])
    elif dtype == "list":
        draw_list(slug, name, title, rest[:6])
    elif dtype == "vs":
        draw_vs(slug, name, title, rest[0], rest[1])
    else:
        raise SystemExit(f"未対応のtype: {dtype}（flow / list / vs）")


if __name__ == "__main__":
    main()
