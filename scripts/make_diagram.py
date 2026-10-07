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
import json
import re
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def site_for_slug(slug):
    """記事のカテゴリからサイトの設定を返す（どのサイトでもなければ None）"""
    p = ROOT / "articles" / f"{slug}.md"
    category = None
    if p.exists():
        m = re.match(r"^---\s*\n(.*?)\n---", p.read_text(encoding="utf-8-sig"), re.S)
        if m:
            category = (yaml.safe_load(m.group(1)) or {}).get("category")
    for cfg in sites_mod.load_all().values():
        if category in cfg.get("categories", {}):
            return cfg
    return None


def credit_text(cfg):
    """図の右下の名義。お客様の社はその社の名前だけにする（data/clients/<id>/company.json）。
    以前は「CONFLUX PARTNERS の記事（セブンセンシズ株式会社）」と運用会社の名前まで入っていた（2026-10-08）"""
    if not cfg:
        return "AI集客ラボ（セブンセンシズ株式会社）"
    if sites_mod.is_client(cfg["id"]):
        try:
            name = json.loads((ROOT / "data" / "clients" / cfg["id"] / "company.json").read_text(encoding="utf-8")).get("name")
        except (OSError, ValueError):
            name = ""
        return name or cfg.get("name", "")
    return f"{cfg['name']}（セブンセンシズ株式会社）"


def brand_for_slug(slug):
    """記事のカテゴリからサイトを判定し、画像フッターに出す名義を返す"""
    return credit_text(site_for_slug(slug))


W = 1200
NAVY = (11, 36, 71)
BLUE = (37, 99, 235)
SKY = (234, 242, 254)
LINE = (211, 224, 240)
BG = (245, 248, 252)
RED = (185, 28, 28)
REDBG = (254, 242, 242)
# 色の役割。サイトの設定（sites/<id>.json の diagram_colors に "#RRGGBB"）で替えられる。無い社は AI集客ラボの色のまま
# （お客様の記事の図が AI集客ラボの青になっていた。2026-10-08）
PALETTE = {"ink": NAVY, "accent": BLUE, "soft": SKY, "line": LINE, "bg": BG, "ng": RED,
           "dot": (220, 230, 244), "shadow": (225, 233, 245), "muted": (122, 140, 165)}


def palette_for(cfg):
    pal = dict(PALETTE)
    for k, v in ((cfg or {}).get("diagram_colors") or {}).items():
        if k in pal and isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            pal[k] = tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))
    return pal

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


def flow_lines(d, step, max_width):
    """フロー型の1項目を、箱に収まる行に分ける。

    縮小の下限（16pt）でも収まらない行は、文字単位で折り返す。以前は下限で諦めて
    そのまま描き、隣の箱の文字と重なって読めなかった（2026-08-07 / 08-21）"""
    lines = step.split("|")
    tf = min((fit_font(d, ln, max_width) for ln in lines), key=lambda f: f.size)
    if all(d.textlength(ln, font=tf) <= max_width for ln in lines):
        return lines, tf
    out = []
    for ln in lines:
        cur = ""
        for ch in ln:
            if cur and d.textlength(cur + ch, font=tf) > max_width:
                out.append(cur)
                cur = ch
            else:
                cur += ch
        out.append(cur)
    return out, tf


def save_png(img, slug, name):
    out = ROOT / "site" / "images" / slug / f"{name}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT).save(out, "PNG", optimize=True)
    print(f"saved: {out} ({out.stat().st_size // 1024}KB)")


def canvas(h, title, pal=PALETTE):
    img = Image.new("RGB", (W, h), pal["bg"])
    d = ImageDraw.Draw(img)
    for gy in range(24, h, 40):
        for gx in range(24, W, 40):
            d.ellipse([gx, gy, gx + 2, gy + 2], fill=pal["dot"])
    d.rounded_rectangle([40, 36, 52, 76], radius=6, fill=pal["accent"])
    d.text((68, 56), title, font=fit_font(d, title, W - 148, base=30, minimum=20), fill=pal["ink"], anchor="lm")
    return img, d


def credit(d, h, text="AI集客ラボ（セブンセンシズ株式会社）", pal=PALETTE):
    d.text((W - 40, h - 28), text, font=font(16), fill=pal["muted"], anchor="rm")


def draw_flow(slug, name, title, steps):
    cfg = site_for_slug(slug)
    pal = palette_for(cfg)
    n = len(steps)
    if not 2 <= n <= 5:
        raise SystemExit("フロー型のステップは2〜5個で指定してください")
    H = 400
    img, d = canvas(H, title, pal)
    margin, gap, top, bh = 60, 34, 130, 200
    bw = (W - margin * 2 - gap * (n - 1)) // n
    nf = font(22)
    for i, step in enumerate(steps):
        x = margin + i * (bw + gap)
        d.rounded_rectangle([x + 4, top + 8, x + bw + 4, top + bh + 8], radius=16, fill=pal["shadow"])
        d.rounded_rectangle([x, top, x + bw, top + bh], radius=16, fill=(255, 255, 255), outline=pal["line"], width=2)
        d.rounded_rectangle([x, top, x + bw, top + 8], radius=4, fill=pal["accent"])
        d.ellipse([x + bw / 2 - 22, top + 26, x + bw / 2 + 22, top + 70], fill=pal["soft"])
        d.text((x + bw / 2, top + 48), str(i + 1), font=nf, fill=pal["accent"], anchor="mm")
        lines, tf = flow_lines(d, step, bw - 28)
        lh = 38 if len(lines) <= 2 else min(38, int(tf.size * 1.45))   # 折り返した分だけ詰める
        y0 = top + 118 - (len(lines) - 1) * lh / 2
        for j, line in enumerate(lines):
            d.text((x + bw / 2, y0 + j * lh), line, font=tf, fill=pal["ink"], anchor="mm")
        if i < n - 1:
            ax = x + bw + gap / 2
            d.polygon([(ax - 9, top + bh / 2 - 12), (ax + 9, top + bh / 2), (ax - 9, top + bh / 2 + 12)],
                      fill=pal["accent"])
    credit(d, H, credit_text(cfg), pal)
    save_png(img, slug, name)


def draw_list(slug, name, title, items):
    cfg = site_for_slug(slug)
    pal = palette_for(cfg)
    n = len(items)
    if not 3 <= n <= 6:
        raise SystemExit("チェックリスト型の項目は3〜6個で指定してください")
    row_h, top = 74, 120
    H = top + n * row_h + 60
    img, d = canvas(H, title, pal)
    # 「ラベル|説明」の「|」で段を分けるのは flow・vs だけ。list では「|」がそのまま
    # 描かれていた（2026-09-23 sogyo-shien-hojokin-kojinjigyonushi で4項目すべて）
    items = [str(it).replace("|", "：") for it in items]
    for i, item in enumerate(items):
        y = top + i * row_h
        d.rounded_rectangle([60, y, W - 60, y + row_h - 14], radius=12,
                            fill=(255, 255, 255), outline=pal["line"], width=2)
        d.ellipse([84, y + 14, 84 + 32, y + 46], fill=pal["accent"])
        d.line([92, y + 30, 99, y + 38], fill=(255, 255, 255), width=4)
        d.line([99, y + 38, 111, y + 22], fill=(255, 255, 255), width=4)
        d.text((140, y + (row_h - 14) / 2), item,
               font=fit_font(d, item, W - 220, base=26), fill=pal["ink"], anchor="lm")
    credit(d, H, credit_text(cfg), pal)
    save_png(img, slug, name)


def draw_vs(slug, name, title, left, right):
    cfg = site_for_slug(slug)
    pal = palette_for(cfg)
    lparts, rparts = left.split("|"), right.split("|")
    lhead, litems = lparts[0], lparts[1:]
    rhead, ritems = rparts[0], rparts[1:]
    rows = max(len(litems), len(ritems))
    if rows < 1:
        raise SystemExit("比較型は「見出し|行1|行2...」の形式で指定してください")
    row_h, top, head_h = 56, 120, 64
    H = top + head_h + rows * row_h + 70
    img, d = canvas(H, title, pal)
    gap = 24
    cw = (W - 120 - gap) // 2
    for ci, (head, items, accent) in enumerate([(lhead, litems, pal["ng"]), (rhead, ritems, pal["accent"])]):
        x = 60 + ci * (cw + gap)
        d.rounded_rectangle([x, top, x + cw, top + head_h + rows * row_h + 16], radius=14,
                            fill=(255, 255, 255), outline=pal["line"], width=2)
        d.rounded_rectangle([x, top, x + cw, top + head_h], radius=14, fill=accent)
        d.rectangle([x, top + head_h - 14, x + cw, top + head_h], fill=accent)
        d.text((x + cw / 2, top + head_h / 2), head,
               font=fit_font(d, head, cw - 40, base=26), fill=(255, 255, 255), anchor="mm")
        mark = "×" if ci == 0 else "○"
        for ri, item in enumerate(items):
            y = top + head_h + ri * row_h
            d.text((x + 30, y + row_h / 2 + 4), mark, font=font(22), fill=accent, anchor="lm")
            d.text((x + 64, y + row_h / 2 + 4), item,
                   font=fit_font(d, item, cw - 92, base=22), fill=pal["ink"], anchor="lm")
    credit(d, H, credit_text(cfg), pal)
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
        if len(rest) > 5:
            print(f"WARN: flow型は5項目までです（{len(rest)}項目が渡され、6個目以降は描きません）")
        draw_flow(slug, name, title, rest[:5])
    elif dtype == "list":
        draw_list(slug, name, title, rest[:6])
    elif dtype == "vs":
        draw_vs(slug, name, title, rest[0], rest[1])
    else:
        raise SystemExit(f"未対応のtype: {dtype}（flow / list / vs）")


if __name__ == "__main__":
    main()
