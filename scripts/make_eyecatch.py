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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
W, H = 1200, 675

# 背景のグラデーション（濃→淡）。カテゴリごとに変える。
# これまで全記事が同じ紺→青だったため、82枚が文字違いの同一デザインになっていた。
# 一覧で並んだときに区別がつかず、SNSでも同じ画像が流れ続ける状態だった。
CAT_BG = {
    "AIO・LLMO運用": ((13, 53, 133), (59, 130, 246)),      # 紺 → 青
    "SEO運用": ((49, 32, 120), (124, 92, 245)),            # 紫紺 → 紫
    "MEO運用": ((6, 78, 74), (20, 184, 166)),              # 深緑 → 青緑
    "AI集客・活用全般": ((7, 62, 96), (14, 165, 233)),      # 藍 → 水色
    "経理BPO・経理代行": ((24, 60, 92), (56, 132, 176)),    # 落ち着いた青
    "経理実務・法対応": ((30, 50, 80), (82, 118, 160)),      # 灰青
    "バックオフィス効率化": ((17, 70, 78), (44, 150, 154)),  # 青緑
    "店舗経営・人材": ((92, 42, 18), (198, 106, 44)),        # 茶 → 橙
    "補助金・助成金": ((94, 20, 60), (214, 62, 122)),        # 臙脂 → 桃
    "補助金": ((94, 20, 60), (214, 62, 122)),
}

CAT_COLORS = {
    "AIO・LLMO運用": (37, 99, 235),
    "SEO運用": (79, 70, 229),
    "MEO運用": (13, 148, 136),
    "AI集客・活用全般": (2, 132, 199),
    "店舗経営": (8, 145, 178),
    "採用・人材育成": (194, 65, 12),
    "オペレーション改善": (21, 128, 61),
    "店舗DX・AI活用": (67, 56, 202),
    "導入事例": (161, 98, 7),
    "補助金・助成金": (190, 24, 93),
}


def site_for_category(category):
    """カテゴリを所有するサイト設定を返す（記事がどのサイト向けかを判定する）"""
    for cfg in sites_mod.load_all().values():
        if category in cfg.get("categories", {}):
            return cfg
    return None

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
    cfg = site_for_category(meta["category"])
    cat_name = cfg["categories"][meta["category"]] if cfg else meta["category"]
    brand = cfg["name"] if cfg else "AI集客ラボ"
    return meta["title"], cat_name, brand


def render(slug, cat, lines_or_title, brand="AI集客ラボ"):
    accent = CAT_COLORS.get(cat, (37, 99, 235))

    img = Image.new("RGB", (W, H))
    px = img.load()
    c1, c2 = CAT_BG.get(cat, ((13, 53, 133), (59, 130, 246)))
    for y in range(H):
        for x in range(0, W, 4):
            t = (x / W + y / H) / 2
            col = tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))
            for dx in range(4):
                if x + dx < W:
                    px[x + dx, y] = col

    d = ImageDraw.Draw(img)

    # 記事ごとに幾何の型を変える。同じカテゴリでも並べたときに区別がつくようにする。
    # slugから決めるので、同じ記事なら何度生成しても同じ絵になる（再現性を保つ）。
    import hashlib
    seed = int(hashlib.md5(slug.encode()).hexdigest()[:8], 16)
    shape = seed % 4
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)

    if shape == 0:      # 点描（従来の型）
        for gy in range(30, H, 44):
            for gx in range(30, W, 44):
                od.ellipse([gx, gy, gx + 2, gy + 2], fill=(255, 255, 255, 60))
    elif shape == 1:    # 右上から差す斜線
        for i in range(-H, W, 78):
            od.line([(i, H), (i + H, 0)], fill=(255, 255, 255, 22), width=3)
    elif shape == 2:    # 右側の同心円
        cx, cy = W - 240, H // 2 - 40
        for r in range(90, 460, 76):
            od.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 30), width=3)
    else:               # 右下の階段状ブロック
        for i in range(7):
            x = W - 120 - i * 96
            y = H - 150 - i * 44
            od.rectangle([x, y, x + 70, y + 70], fill=(255, 255, 255, 16))

    img.paste(Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB"), (0, 0))
    d = ImageDraw.Draw(img)

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
    d.text((tx, H - 46), brand, font=font(30), fill=(255, 255, 255), anchor="lm")
    d.text((W - 80, H - 46), "セブンセンシズ株式会社", font=font(22), fill=(163, 196, 243), anchor="rm")

    save_png(img, ROOT / "site" / "images" / slug / "eyecatch.png")


def main():
    if len(sys.argv) == 2:  # slugのみ → フロントマターから自動
        slug = sys.argv[1]
        title, cat, brand = parse_frontmatter(slug)
        render(slug, cat, title, brand)
    else:  # 従来互換
        slug, cat = sys.argv[1], sys.argv[2]
        lines = [x for x in sys.argv[3:5] if x]
        render(slug, cat, lines)


if __name__ == "__main__":
    main()
