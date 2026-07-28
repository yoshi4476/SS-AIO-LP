# -*- coding: utf-8 -*-
"""記事アイキャッチ生成（画像生成API未設定時のフォールバック / Phase 6用）

使い方:
    python scripts/make_eyecatch.py <slug>                      # 記事フロントマターから自動生成（推奨）
    python scripts/make_eyecatch.py <slug> <カテゴリ名> <1行目> [2行目]   # 手動指定（従来互換）

出力: site/images/<slug>/eyecatch.png (1200x675)
- タイトルは自動で折り返し・自動縮小するため、はみ出しは構造的に発生しない
- PNGはパレット化で自動軽量化（フラットデザインのため画質劣化なし）
"""
import re
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
CAT_NAMES = {"aio": "AIO・LLMO運用", "seo": "SEO運用", "meo": "MEO運用",
             "ai-marketing": "AI集客・活用全般"}

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
    raise SystemExit("日本語フォントが見つかりません（Linuxは fonts-noto-cjk を、"
                     "Windowsは游ゴシック/メイリオを確認）。文字化け画像の生成を防ぐため中断します")


def save_png(img, out: Path):
    """フラットイラスト向けのパレット化保存（サイズ約1/3〜1/5・画質劣化なし）"""
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT).save(out, "PNG", optimize=True)
    print(f"saved: {out} ({out.stat().st_size // 1024}KB)")


def wrap_title(d, title, max_width, base_size=64, min_size=40):
    """タイトルを最大2行に折り返し、収まるまでフォントを自動縮小する"""
    # 区切り優先: ｜/｜?、読点・中黒・スペースの位置で自然に分割
    for size in range(base_size, min_size - 1, -4):
        f = font(size)
        if d.textlength(title, font=f) <= max_width:
            return [title], f
        # 2行分割: 中央に最も近い区切り文字で割る
        seps = [m.start() for m in re.finditer(r"[、。・｜|？! ？!／/」』）)]", title)]
        cut = min(seps, key=lambda i: abs(i - len(title) // 2)) + 1 if seps else len(title) // 2
        lines = [title[:cut].strip(), title[cut:].strip()]
        if all(d.textlength(x, font=f) <= max_width for x in lines if x):
            return [x for x in lines if x], f
    # 最終手段: 最小サイズで強制2分割
    f = font(min_size)
    cut = len(title) // 2
    return [title[:cut], title[cut:]], f


def parse_frontmatter(slug):
    p = ROOT / "articles" / f"{slug}.md"
    if not p.exists():
        raise SystemExit(f"articles/{slug}.md が見つかりません（手動指定モードを使うか、slugを確認）")
    import yaml
    m = re.match(r"^---\s*\n(.*?)\n---", p.read_text(encoding="utf-8-sig"), re.S)
    if not m:
        raise SystemExit(f"articles/{slug}.md にフロントマターがありません")
    meta = yaml.safe_load(m.group(1))
    return meta["title"], CAT_NAMES.get(meta["category"], "AI集客・活用全般")


def render(slug, cat, lines_or_title):
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

    # タイトル（自動折り返し+自動縮小）
    if isinstance(lines_or_title, str):
        lines, tf = wrap_title(d, lines_or_title, W - 160)
    else:
        lines, tf = lines_or_title, font(64)
        # 手動指定でもはみ出しは縮小で防ぐ
        while any(d.textlength(x, font=tf) > W - 160 for x in lines) and tf.size > 40:
            tf = font(tf.size - 4)
    line_h = int(tf.size * 1.42)
    y0 = 300 - (len(lines) - 1) * line_h // 2
    for i, line in enumerate(lines):
        d.text((80, y0 + i * line_h), line, font=tf, fill=(255, 255, 255), anchor="lm")

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

    save_png(img, ROOT / "site" / "images" / slug / "eyecatch.png")


def main():
    if len(sys.argv) == 2:  # slugのみ → フロントマターから自動
        slug = sys.argv[1]
        title, cat = parse_frontmatter(slug)
        render(slug, cat, title)
    else:  # 従来互換
        slug, cat = sys.argv[1], sys.argv[2]
        lines = [x for x in sys.argv[3:5] if x]
        render(slug, cat, lines)


if __name__ == "__main__":
    main()
