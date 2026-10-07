# -*- coding: utf-8 -*-
"""記事本文の図解を描く（Pillow。日本語だけ・はみ出さない・サイトの色と名義）

日本語はシステムのフォント（Windows: 游ゴシック / Linux: Noto Sans CJK）で直接描くので文字化けしない。
英語の文字は入れない（CLAUDE.md の画像ルール）。文字は枠に合わせて縮め、日本語の切れ目で折り返す。

■ 型（見出しの中身に合うものを選ぶ。同じ記事で同じ型を重ねない）
  flow     手順（2〜5）               items: ["見出し|補足", ...]
  steps    時系列・段階（2〜6）        items: ["見出し|補足", ...]   labels: ["申請前", "1か月目", ...]（任意。期間）
  list     確かめること（3〜6）        items: ["項目", ...]
  vs       NG と OK の2列             items: ["NG側の見出し|行|行", "OK側の見出し|行|行"]
  matrix   比較の表（2〜4列×3〜6行）    items: ["観点|A|B|C", "費用|○|△|×", ...]（1つ目は見出しの行。○◎△×－ は記号で描く）
  cycle    循環（3〜6）               items: ["見出し|補足", ...]   center: "毎月まわす"（任意。輪の真ん中）
  funnel   絞り込み（3〜5段）          items: ["段の名前|補足", ...]（上が広い）
  bars     数字の横棒（3〜8）          items: ["ラベル|数値", ...]   unit: "%"（任意）  note: "出典：…"（任意）
  pyramid  階層（3〜5段）             items: ["頂点|補足", ..., "土台|補足"]
  tree     分類（2〜4の枝）            root: "分ける対象"   items: ["枝|葉|葉", ...]（葉は1つの枝に4つまで）

■ 描かずに止める決まり（はみ出した絵・事実と違う絵を公開しない）
  - 項目の数が型の範囲を外れたとき（以前は flow の6個目以降を黙って切り、本文の「6ステップ」と図がずれた）
  - bars の数値が、記事の本文・表に同じ値で出ていないとき（図にだけある数字を作らない）
  - 新しい型で、縮めても折り返しても枠に収まらない文字があるとき

■ 解像度と容量
  論理の幅 W=1200 で組み、SCALE 倍（2400px）で書き出す。表示の幅は記事の CSS が決めるので見た目の大きさは
  今と同じで、高精細の画面でも粗く見えない。減色した PNG が MAX_BYTES を超えたら止める（表示速度の方針）。

使い方:
  python scripts/make_images.py <slug>              # 記事の宣言から全部描く（ふつうはこちら）
  python scripts/make_diagram.py [--type T] <slug> <ファイル名> <題> <項目1> <項目2> ...
      [--labels "a|b|c"] [--unit %] [--note "出典：…"] [--center 語] [--root 語]
出力: site/images/<slug>/<ファイル名>.png
"""
import functools
import io
import json
import math
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _split_article(slug):
    """(フロントマター, 本文)。記事が無ければ (None, None)"""
    p = ROOT / "articles" / f"{slug}.md"
    if not p.is_file():
        return None, None
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", p.read_text(encoding="utf-8-sig"), re.S)
    if not m:
        return None, None
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError:
        return None, m.group(2)


def article_body(slug):
    return _split_article(slug)[1]


def site_for_slug(slug):
    """記事のカテゴリからサイトの設定を返す（どのサイトでもなければ None）"""
    fm = _split_article(slug)[0] or {}
    category = fm.get("category")
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


W = 1200            # 論理の幅。座標と文字の大きさはこの幅で考える（表示の幅もこれまでと同じ）
SCALE = 2           # 書き出しの倍率。1200px のままだと高精細の画面で粗く見えた（2026-10-08 の点検）
MAX_BYTES = 200 * 1024   # 1枚の上限。記事は図を3〜4枚載せるので、1枚がこれを超えると表示が遅くなる
M = 60              # 左右の余白
TOP = 120           # 題の下の、中身の始まり
QUIET = False       # まとめて描き直すときは1枚ごとの保存の印字を止める

WHITE = (255, 255, 255)
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


def mix(a, b, t):
    """色 a から b へ t の割合だけ寄せた色"""
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def _lum(c):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def on_color(fill, pal, large=False):
    """塗りの上の文字の色。白で読める（4.5:1 以上。大きい太字は 3:1 以上）なら白、読めなければ濃い色"""
    return WHITE if contrast(WHITE, fill) >= (3.0 if large else 4.5) else pal["ink"]


def sub_ink(pal):
    """補足の文字の色（見出しより一段弱く、読める濃さは残す）"""
    return mix(pal["ink"], pal["muted"], 0.45)


# ── 書き出しの倍率をかけて描く ────────────────────────────────
def _s(v):
    return int(round(v * SCALE))


def _box(b):
    return [_s(v) for v in b]


def _pts(xy):
    if xy and isinstance(xy[0], (tuple, list)):
        return [(_s(x), _s(y)) for x, y in xy]
    return [_s(v) for v in xy]


def _w(width):
    return max(1, int(round(width * SCALE)))


@functools.lru_cache(maxsize=None)
def _load(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)


def _at_scale(f):
    return _load(f.path, int(round(f.size * SCALE)), getattr(f, "index", 0))


class Pen:
    """論理の座標（幅 W）で受け取り、SCALE 倍の画像に描く。文字の幅も描く大きさで測って論理に戻す。
    Pen() は描かずに測るだけの下地（検査が描画と同じ計算で収まりを測るため）"""

    def __init__(self, img=None):
        self.img = img if img is not None else Image.new("RGB", (8, 8))
        self.d = ImageDraw.Draw(self.img)

    def textlength(self, text, font=None):
        return self.d.textlength(text, font=_at_scale(font)) / SCALE

    def text(self, xy, text, font=None, fill=None, anchor=None):
        self.d.text((_s(xy[0]), _s(xy[1])), text, font=_at_scale(font), fill=fill, anchor=anchor)

    def rounded_rectangle(self, box, radius=0, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(_box(box), radius=_s(radius), fill=fill, outline=outline, width=_w(width))

    def rectangle(self, box, fill=None, outline=None, width=1):
        self.d.rectangle(_box(box), fill=fill, outline=outline, width=_w(width))

    def ellipse(self, box, fill=None, outline=None, width=1):
        self.d.ellipse(_box(box), fill=fill, outline=outline, width=_w(width))

    def line(self, xy, fill=None, width=1, joint=None):
        self.d.line(_pts(xy), fill=fill, width=_w(width), joint=joint)

    def polygon(self, xy, fill=None, outline=None, width=1):
        self.d.polygon(_pts(xy), fill=fill, outline=outline, width=_w(width))


# ── 文字 ────────────────────────────────────────────────
FONT_PATHS = [
    r"C:\Windows\Fonts\YuGothB.ttc", r"C:\Windows\Fonts\meiryob.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]
# 補足の文字。太字だけだと見出しと補足の差が色しか無く、読む順が分からなかった
REGULAR_PATHS = [
    r"C:\Windows\Fonts\YuGothM.ttc", r"C:\Windows\Fonts\meiryo.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]


@functools.lru_cache(maxsize=None)
def _font_path(weight):
    for p in (REGULAR_PATHS + FONT_PATHS if weight == "regular" else FONT_PATHS):
        try:
            _load(p, 12)
            return p
        except OSError:
            continue
    return None


def font(size, weight="bold"):
    p = _font_path(weight)
    if not p:
        raise SystemExit("日本語フォントが見つかりません（文字化け防止のため中断）")
    return _load(p, int(size))


def fit_font(d, text, max_width, base=26, minimum=16, weight="bold"):
    """max_widthに収まるフォントサイズを返す（はみ出しの構造的防止）"""
    for size in range(base, minimum - 1, -2):
        if d.textlength(text, font=font(size, weight)) <= max_width:
            return font(size, weight)
    return font(minimum, weight)


# 日本語の折り返し。英数字のかたまり（AI Overview・4.6% など）は割らず、行頭に来てはいけない文字
# （、。」ー ゃ など）は前の行に付け、句読点・助詞の後のような切れ目を選ぶ。文字の途中で機械的に
# 切ると「5つの準／備」のように語が割れた（動画の題で実測）
_WORD = re.compile(r"[A-Za-z0-9\uFF10-\uFF19\uFF21-\uFF3A\uFF41-\uFF5A][A-Za-z0-9\uFF10-\uFF19\uFF21-\uFF3A\uFF41-\uFF5A.,%\uFF05+\-/:&'\u2019]*")
NO_START = set("、。，．・：；？！ー－）」』】〉》〕］｝ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ々〜…‥%％")
NO_END = set("（「『【〈《〔［｛")
GOOD_END = set("、。，．・：；）」』】〉》〕］｝！？ 　")


def _kind(ch):
    o = ord(ch)
    if 0x3041 <= o <= 0x309F:
        return "h"
    if 0x30A0 <= o <= 0x30FF:
        return "k"
    if 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or ch in "々〆ヶ":
        return "c"
    if ch.isascii() and ch.isalnum():
        return "a"
    return "p"


def _tokens(text):
    raw, i = [], 0
    while i < len(text):
        m = _WORD.match(text, i)
        if m:
            raw.append(m.group(0))
            i = m.end()
        else:
            raw.append(text[i])
            i += 1
    out = []
    for t in raw:
        if out and (t[0] in NO_START or out[-1][-1] in NO_END):
            out[-1] += t
        else:
            out.append(t)
    return out


def _score(a, b):
    """a と b の間で折る良さ（高いほどよい）"""
    pa, nb = a[-1], b[0]
    if pa in GOOD_END:
        return 3
    ka, kb = _kind(pa), _kind(nb)
    if pa == "を" or (ka == "h" and kb in "cka"):
        return 2
    if ka != kb and "p" not in (ka, kb):
        return 1
    return 0


def _hard_split(d, tok, f, width):
    out, cur = [], ""
    for ch in tok:
        if cur and d.textlength(cur + ch, font=f) > width:
            out.append(cur)
            cur = ch
        else:
            cur += ch
    return out + ([cur] if cur else [])


def _greedy(d, toks, f, width):
    lines, i, n = [], 0, len(toks)
    while i < n:
        j = i
        while j < n and d.textlength("".join(toks[i:j + 1]), font=f) <= width:
            j += 1
        if j == i:                       # 1つのかたまりだけで幅を超える（長い英単語）→ 文字で割る
            parts = _hard_split(d, toks[i], f, width)
            if len(parts) == 1:          # 1文字でも幅を超える（幅が狭すぎる）。止まらないよう、その字だけで1行
                lines.append(parts[0])
                i += 1
                continue
            lines += parts[:-1]
            toks = toks[:i] + [parts[-1]] + toks[i + 1:]
            n = len(toks)
            continue
        if j == n:
            lines.append("".join(toks[i:j]))
            break
        best_k, best_s = j, _score(toks[j - 1], toks[j])
        for k in range(j - 1, i, -1):    # 行の55%より後ろで、もっと切れ目のよい所があればそこで折る
            if d.textlength("".join(toks[i:k]), font=f) < width * 0.55:
                break
            s = _score(toks[k - 1], toks[k])
            if s > best_s:
                best_k, best_s = k, s
        lines.append("".join(toks[i:best_k]))
        i = best_k
    return lines


def wrap(d, text, f, max_width):
    """text を max_width に収まる行に分ける。行の数は変えずに幅を詰め、最後の行に1〜2字だけ残さない"""
    text = str(text).strip()
    if not text or d.textlength(text, font=f) <= max_width:
        return [text]
    toks = _tokens(text)
    lines = _greedy(d, toks, f, max_width)
    if len(lines) > 1:
        lo, hi, best = max_width * 0.5, max_width, lines
        for _ in range(7):
            mid = (lo + hi) / 2
            trial = _greedy(d, toks, f, mid)
            if len(trial) <= len(lines):
                best, hi = trial, mid
            else:
                lo = mid
        lines = best
    return lines


def fit_block(d, text, width, max_lines, base, minimum, weight="bold"):
    """text を width に max_lines 行以内で収める (行, 文字, 収まったか)。
    まず1行のまま base の85%まで縮め、入らなければ折り返して base から縮める"""
    text = str(text).strip()
    for size in range(base, max(minimum, int(base * 0.85)) - 1, -1):
        f = font(size, weight)
        if d.textlength(text, font=f) <= width:
            return [text], f, True
    for size in range(base, minimum - 1, -1):
        f = font(size, weight)
        lines = wrap(d, text, f, width)
        if len(lines) <= max_lines:
            return lines, f, True
    f = font(minimum, weight)
    return wrap(d, text, f, width), f, False


def fit_multi(d, segs, width, max_lines, base, minimum, weight="regular"):
    """複数の段（「|」で分けた補足）を同じ大きさの文字で、合わせて max_lines 行以内に収める"""
    for size in range(base, minimum - 1, -1):
        f = font(size, weight)
        lines = [ln for s in segs for ln in wrap(d, s, f, width)]
        if len(lines) <= max_lines:
            return lines, f, True
    f = font(minimum, weight)
    return [ln for s in segs for ln in wrap(d, s, f, width)], f, False


def lh(f):
    """行の高さ"""
    return round(f.size * 1.38)


class Block:
    """見出し（太字）と補足（細字）の行のまとまり。高さを先に測ってから置く"""
    GAP = 6

    def __init__(self, head, sub=None):
        self.head, self.sub = head, sub          # (行, 文字)

    @property
    def height(self):
        h = len(self.head[0]) * lh(self.head[1])
        if self.sub:
            h += self.GAP + len(self.sub[0]) * lh(self.sub[1])
        return h

    def draw(self, d, x, top, head_fill, sub_fill, align="center"):
        anchor = "mm" if align == "center" else "lm"
        y = top
        for part, fill in ((self.head, head_fill), (self.sub, sub_fill)):
            if not part:
                continue
            lines, f = part
            for ln in lines:
                d.text((x, y + lh(f) / 2), ln, font=f, fill=fill, anchor=anchor)
                y += lh(f)
            y += self.GAP


class Ctx:
    """1枚の図を描く間の材料（色・名義・収まらなかった文字の記録）"""

    def __init__(self, slug, name, cfg):
        self.slug, self.name, self.cfg = slug, name, cfg
        self.pal = palette_for(cfg)
        self.sub = sub_ink(self.pal)
        self.problems = []

    def problem(self, msg):
        self.problems.append(f"{self.name}: {msg}")


def make_block(ctx, d, text, width, head=(2, 24, 16), sub=(3, 19, 14), what="項目"):
    """「見出し|補足|補足」を見出しと補足の行に収める。収まらなければ ctx に記録する"""
    parts = [s.strip() for s in str(text).split("|")]
    hl, hf, ok = fit_block(d, parts[0], width, *head)
    if not ok:
        ctx.problem(f"{what}「{parts[0][:24]}」が縮めても枠に収まりません（短くしてください）")
    rest = [s for s in parts[1:] if s]
    sb = None
    if rest:
        sl, sf, ok2 = fit_multi(d, rest, width, *sub)
        if not ok2:
            ctx.problem(f"{what}「{parts[0][:16]}」の補足が縮めても枠に収まりません（短くしてください）")
        sb = (sl, sf)
    return Block((hl, hf), sb)


def one_line(ctx, d, text, width, base, minimum, what, weight="bold"):
    """1行で収める文字（期間のラベル・数値など）。入らなければ記録する"""
    f = fit_font(d, text, width, base=base, minimum=minimum, weight=weight)
    if d.textlength(text, font=f) > width:
        ctx.problem(f"{what}「{text[:20]}」が長すぎて収まりません（短くしてください）")
    return f


# ── 下地・名義・保存 ────────────────────────────────────────
def canvas(h, title, pal=PALETTE):
    h = int(math.ceil(h))
    img = Image.new("RGB", (W * SCALE, h * SCALE), pal["bg"])
    d = Pen(img)
    for gy in range(24, h, 40):
        for gx in range(24, W, 40):
            d.ellipse([gx, gy, gx + 2, gy + 2], fill=pal["dot"])
    d.rounded_rectangle([40, 36, 52, 76], radius=6, fill=pal["accent"])
    d.text((68, 56), title, font=fit_font(d, title, W - 148, base=30, minimum=20), fill=pal["ink"], anchor="lm")
    return img, d


def credit(d, h, text="AI集客ラボ（セブンセンシズ株式会社）", pal=PALETTE):
    d.text((W - 40, h - 28), text, font=font(16), fill=pal["muted"], anchor="rm")


def note(ctx, d, h, text):
    """左下の注記（出典など）。名義の1段上に置く"""
    if text:
        f = one_line(ctx, d, text, W - 2 * M, 16, 12, "注記", weight="regular")
        d.text((M, h - 56), text, font=f, fill=ctx.pal["muted"], anchor="lm")


def card(d, box, pal, radius=16, fill=WHITE):
    """白い札（影つき）。どの型も同じ札を使い、見た目をそろえる"""
    x0, y0, x1, y1 = box
    d.rounded_rectangle([x0 + 2, y0 + 5, x1 + 2, y1 + 5], radius=radius, fill=pal["shadow"])
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=pal["line"], width=2)


def badge(d, cx, cy, r, text, pal, solid=True):
    """番号の丸"""
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=pal["accent"] if solid else pal["soft"])
    d.text((cx, cy), text, font=font(max(12, int(r * 0.95))), fill=WHITE if solid else pal["accent"], anchor="mm")


def encode_png(img):
    """減色して軽くした PNG。フラットな図なので256色で見た目は変わらない。
    上限を超えたら色数を減らし、それでも超えたら止める（重い図を記事に載せない）"""
    rgb = img.convert("RGB")
    size = 0
    for colors in (256, 128, 64):
        buf = io.BytesIO()
        rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT,
                     dither=Image.Dither.NONE).save(buf, "PNG", optimize=True)
        size = buf.tell()
        if size <= MAX_BYTES:
            return buf.getvalue()
    raise SystemExit(f"図が重すぎます（{size // 1024}KB・上限 {MAX_BYTES // 1024}KB）。項目を減らすか短くしてください")


def save_png(img, slug, name):
    out = ROOT / "site" / "images" / slug / f"{name}.png"
    data = encode_png(img)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 中身が同じなら書かない（描き直しのたびに差分を出さない）
    if not out.is_file() or out.read_bytes() != data:
        out.write_bytes(data)
    if not QUIET:
        print(f"saved: {out} ({len(data) // 1024}KB)")


# ── flow（手順） ─────────────────────────────────────────────
def _flow_layout(d, step, max_width):
    """flow 型の1項目を (行, 文字, 段の番号) に分ける。全部の行で同じ大きさの文字を使う。
    まず大きいまま1行で収め（26→20）、入らなければ段ごとに2行まで折る（26→20）。それでも入らなければ
    下限（16）まで縮め、最後は日本語の切れ目で折る。以前は縮小の下限（16pt）でも収まらない行を
    そのまま描き、隣の箱の文字と重なって読めなかった（2026-08-07 / 08-21）"""
    segs = [s.strip() for s in step.split("|")]

    def flat(f):
        out = []
        for k, s in enumerate(segs):
            out += [(ln, k) for ln in wrap(d, s, f, max_width)]
        return out
    for size in (26, 24, 22, 20):
        f = font(size)
        if all(d.textlength(s, font=f) <= max_width for s in segs):
            return [s for s in segs], f, list(range(len(segs)))
    for size in (26, 24, 22, 20):
        f = font(size)
        out = flat(f)
        if len(out) <= 3 and all(len(wrap(d, s, f, max_width)) <= 2 for s in segs):
            return [x for x, _ in out], f, [k for _, k in out]
    for size in (18, 16):
        f = font(size)
        if all(d.textlength(s, font=f) <= max_width for s in segs):
            return [s for s in segs], f, list(range(len(segs)))
    f = font(16)
    out = flat(f)
    return [x for x, _ in out], f, [k for _, k in out]


def flow_lines(d, step, max_width):
    """flow 型の1項目を、箱に収まる行に分ける（行, 文字）"""
    lines, f, _ = _flow_layout(d, step, max_width)
    return lines, f


def flow_lh(lines, f):
    """flow 型の行の間隔（image_check が同じ式で箱からのはみ出しを測る）"""
    return 38 if len(lines) <= 2 else min(38, int(f.size * 1.45))


def draw_flow(slug, name, title, steps):
    cfg = site_for_slug(slug)
    pal = palette_for(cfg)
    sub = sub_ink(pal)
    n = len(steps)
    if not 2 <= n <= 5:
        raise SystemExit("フロー型のステップは2〜5個で指定してください")
    H = 400
    img, d = canvas(H, title, pal)
    margin, gap, top, bh = 60, 34, 130, 200
    bw = (W - margin * 2 - gap * (n - 1)) // n
    for i, step in enumerate(steps):
        x = margin + i * (bw + gap)
        card(d, [x, top, x + bw, top + bh], pal)
        d.rounded_rectangle([x, top, x + bw, top + 10], radius=5, fill=pal["accent"])
        d.rectangle([x + 2, top + 5, x + bw - 2, top + 10], fill=pal["accent"])
        badge(d, x + bw / 2, top + 48, 22, str(i + 1), pal, solid=False)
        lines, tf, seg = _flow_layout(d, step, bw - 28)
        lh_ = flow_lh(lines, tf)
        y0 = top + 118 - (len(lines) - 1) * lh_ / 2
        for j, line in enumerate(lines):
            d.text((x + bw / 2, y0 + j * lh_), line, font=tf, fill=pal["ink"] if seg[j] == 0 else sub, anchor="mm")
        if i < n - 1:
            ax = x + bw + gap / 2
            d.polygon([(ax - 8, top + bh / 2 - 12), (ax + 9, top + bh / 2), (ax - 8, top + bh / 2 + 12)],
                      fill=pal["accent"])
    credit(d, H, credit_text(cfg), pal)
    save_png(img, slug, name)


# ── list（確かめること） ───────────────────────────────────────
def draw_list(slug, name, title, items):
    cfg = site_for_slug(slug)
    pal = palette_for(cfg)
    sub = sub_ink(pal)
    n = len(items)
    if not 3 <= n <= 6:
        raise SystemExit("チェックリスト型の項目は3〜6個で指定してください")
    row_h, top = 74, 120
    H = top + n * row_h + 60
    img, d = canvas(H, title, pal)
    # 「ラベル|説明」の「|」で段を分けるのは flow・vs だけ。list では「|」がそのまま
    # 描かれていた（2026-09-23 sogyo-shien-hojokin-kojinjigyonushi で4項目すべて）。
    # 「：」でつなぎ、説明は一段弱い色で描く（文字の大きさは1本の文として測る）
    for i, item in enumerate(items):
        label, _, rest = str(item).partition("|")
        text = f"{label}：{rest.replace('|', '：')}" if rest else label
        y = top + i * row_h
        card(d, [60, y, W - 60, y + row_h - 14], pal, radius=12)
        cy = y + (row_h - 14) / 2
        d.ellipse([84, cy - 16, 116, cy + 16], fill=pal["accent"])
        d.line([(92, cy), (99, cy + 8), (111, cy - 8)], fill=WHITE, width=4, joint="curve")
        f = fit_font(d, text, W - 220, base=26)
        if rest:
            head = f"{label}："
            d.text((140, cy), head, font=f, fill=pal["ink"], anchor="lm")
            d.text((140 + d.textlength(head, font=f), cy), rest.replace("|", "："), font=f, fill=sub, anchor="lm")
        else:
            d.text((140, cy), text, font=f, fill=pal["ink"], anchor="lm")
    credit(d, H, credit_text(cfg), pal)
    save_png(img, slug, name)


# ── vs（NG と OK） ─────────────────────────────────────────────
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
        card(d, [x, top, x + cw, top + head_h + rows * row_h + 16], pal, radius=14)
        d.rounded_rectangle([x, top, x + cw, top + head_h], radius=14, fill=accent)
        d.rectangle([x, top + head_h - 14, x + cw, top + head_h], fill=accent)
        d.text((x + cw / 2, top + head_h / 2), head,
               font=fit_font(d, head, cw - 40, base=26), fill=on_color(accent, pal), anchor="mm")
        for ri, item in enumerate(items):
            y = top + head_h + ri * row_h
            if ri:
                d.line([(x + 24, y + 4), (x + cw - 24, y + 4)], fill=mix(pal["line"], WHITE, 0.4), width=1.5)
            cy = y + row_h / 2 + 4
            if ci == 0:
                d.line([(x + 31, cy - 7), (x + 45, cy + 7)], fill=accent, width=3.5)
                d.line([(x + 31, cy + 7), (x + 45, cy - 7)], fill=accent, width=3.5)
            else:
                d.ellipse([x + 30, cy - 8, x + 46, cy + 8], outline=accent, width=3.5)
            d.text((x + 64, cy), item,
                   font=fit_font(d, item, cw - 92, base=22), fill=pal["ink"], anchor="lm")
    credit(d, H, credit_text(cfg), pal)
    save_png(img, slug, name)


# ── steps（時系列・段階） ───────────────────────────────────────
def _steps(ctx, dg, title, items):
    probe, n = Pen(), len(items)
    labels = [str(x).strip() for x in (dg.get("labels") or [])]
    if n <= 5:                               # 横に並べられるなら横（時間が左から右へ流れる）
        trial = Ctx(ctx.slug, ctx.name, ctx.cfg)
        cw = (W - 2 * M) / n
        blocks = [make_block(trial, probe, it, cw - 40, head=(3, 24, 16), sub=(3, 19, 14)) for it in items]
        if not trial.problems and max(b.height for b in blocks) <= 210:
            return _steps_row(ctx, title, items, labels, blocks, cw)
    return _steps_column(ctx, title, items, labels)


def _label_pill(ctx, d, text, cx, cy, max_w, align="center"):
    f = one_line(ctx, d, text, max_w - 28, 17, 13, "期間のラベル")
    tw = min(d.textlength(text, font=f), max_w - 28)
    x0 = cx - tw / 2 - 14 if align == "center" else cx - tw - 28
    d.rounded_rectangle([x0, cy - 17, x0 + tw + 28, cy + 17], radius=17, fill=ctx.pal["soft"])
    d.text((x0 + 14 + tw / 2, cy), text, font=f, fill=ctx.pal["accent"], anchor="mm")


def _steps_row(ctx, title, items, labels, blocks, cw):
    pal, n = ctx.pal, len(items)
    y_line = TOP + (78 if labels else 34)
    r = 24
    box_top = y_line + r + 22
    box_h = max(b.height for b in blocks) + 36
    H = box_top + box_h + 64
    img, d = canvas(H, title, pal)
    xs = [M + cw * (i + 0.5) for i in range(n)]
    d.line([(xs[0], y_line), (xs[-1], y_line)], fill=mix(pal["accent"], WHITE, 0.55), width=4)
    for i, x in enumerate(xs):
        if labels:
            _label_pill(ctx, d, labels[i], x, TOP + 22, cw - 12)
            d.line([(x, TOP + 39), (x, y_line - r)], fill=mix(pal["accent"], WHITE, 0.55), width=2)
        card(d, [x - cw / 2 + 10, box_top, x + cw / 2 - 10, box_top + box_h], pal, radius=14)
        d.ellipse([x - r - 5, y_line - r - 5, x + r + 5, y_line + r + 5], fill=pal["bg"])
        badge(d, x, y_line, r, str(i + 1), pal)
        b = blocks[i]
        b.draw(d, x, box_top + (box_h - b.height) / 2, pal["ink"], ctx.sub, align="center")
    credit(d, H, credit_text(ctx.cfg), pal)
    return img


def _steps_column(ctx, title, items, labels):
    pal, probe, n = ctx.pal, Pen(), len(items)
    lab_w = 0
    if labels:
        f = font(17)
        lab_w = min(220, max(probe.textlength(x, font=f) for x in labels) + 30)
    r = 22
    cx = M + (lab_w + 38 if labels else 26)
    x0, x1 = cx + r + 22, W - M
    inner = x1 - x0 - 44
    parts = [[s.strip() for s in it.split("|")] for it in items]
    # 札は横に広いので、見出しを左・補足を右に並べる（縦に積むと6段で縦長になりすぎた）
    hw = min(330, inner * 0.42) if any(len(p) > 1 for p in parts) else inner
    heads, subs = [], []
    for p in parts:
        hl, hf, ok = fit_block(probe, p[0], hw, 2, 24, 16)
        if not ok:
            ctx.problem(f"項目「{p[0][:24]}」が縮めても枠に収まりません（短くしてください）")
        heads.append((hl, hf))
        rest = [s for s in p[1:] if s]
        sb = None
        if rest:
            sl, sf, ok2 = fit_multi(probe, rest, inner - hw - 28, 3, 19, 14)
            if not ok2:
                ctx.problem(f"項目「{p[0][:16]}」の補足が縮めても枠に収まりません（短くしてください）")
            sb = (sl, sf)
        subs.append(sb)
    rows = [max(64, max(len(h[0]) * lh(h[1]), len(s[0]) * lh(s[1]) if s else 0) + 26) for h, s in zip(heads, subs)]
    gap = 14
    H = TOP + 8 + sum(rows) + gap * (n - 1) + 62
    img, d = canvas(H, title, pal)
    tops, y = [], TOP + 8
    for h in rows:
        tops.append(y)
        y += h + gap
    mids = [t + h / 2 for t, h in zip(tops, rows)]
    d.line([(cx, mids[0]), (cx, mids[-1])], fill=mix(pal["accent"], WHITE, 0.55), width=4)
    for i, (t, h) in enumerate(zip(tops, rows)):
        card(d, [x0, t, x1, t + h], pal, radius=14)
        cols = [(heads[i], x0 + 22, pal["ink"])]
        if subs[i]:
            cols.append((subs[i], x0 + 22 + hw + 28, ctx.sub))
        for (lines, f), x, fill in cols:
            top = mids[i] - len(lines) * lh(f) / 2
            for k, ln in enumerate(lines):
                d.text((x, top + lh(f) * (k + 0.5)), ln, font=f, fill=fill, anchor="lm")
        if subs[i]:
            d.line([(x0 + 22 + hw + 13, t + 14), (x0 + 22 + hw + 13, t + h - 14)], fill=pal["line"], width=1.5)
        d.ellipse([cx - r - 5, mids[i] - r - 5, cx + r + 5, mids[i] + r + 5], fill=pal["bg"])
        badge(d, cx, mids[i], r, str(i + 1), pal)
        if labels:
            _label_pill(ctx, d, labels[i], cx - r - 12, mids[i], lab_w, align="right")
    credit(d, H, credit_text(ctx.cfg), pal)
    return img


# ── matrix（比較の表） ─────────────────────────────────────────
MARKS = {"◎": "double", "○": "circle", "◯": "circle", "〇": "circle", "△": "tri", "▲": "tri",
         "×": "cross", "✕": "cross", "✗": "cross", "－": "dash", "-": "dash", "―": "dash", "—": "dash", "ー": "dash"}


def draw_mark(d, kind, cx, cy, pal):
    if kind == "double":
        d.ellipse([cx - 15, cy - 15, cx + 15, cy + 15], outline=pal["accent"], width=4)
        d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], outline=pal["accent"], width=4)
    elif kind == "circle":
        d.ellipse([cx - 13, cy - 13, cx + 13, cy + 13], outline=pal["accent"], width=4.5)
    elif kind == "tri":
        c = mix(pal["ink"], pal["muted"], 0.55)
        d.polygon([(cx, cy - 14), (cx + 15, cy + 11), (cx - 15, cy + 11)], outline=c, width=4)
    elif kind == "cross":
        d.line([(cx - 11, cy - 11), (cx + 11, cy + 11)], fill=pal["ng"], width=4.5)
        d.line([(cx - 11, cy + 11), (cx + 11, cy - 11)], fill=pal["ng"], width=4.5)
    else:
        d.line([(cx - 12, cy), (cx + 12, cy)], fill=pal["muted"], width=4)


def _matrix(ctx, dg, title, items):
    pal, probe = ctx.pal, Pen()
    rows = [[c.strip() for c in it.split("|")] for it in items]
    head, body = rows[0], rows[1:]
    ncol = len(head) - 1
    x0, x1 = M, W - M
    rw = {2: 320, 3: 280}.get(ncol, 250)
    cw = (x1 - x0 - rw) / ncol

    def cell(text, width, base, minimum, what):
        if text in MARKS:
            return ("mark", MARKS[text], 30)
        lines, f, ok = fit_block(probe, text, width, 2, base, minimum)
        if not ok:
            ctx.problem(f"{what}「{text[:20]}」が縮めても枠に収まりません（短くしてください）")
        return ("text", (lines, f), len(lines) * lh(f))
    corner = cell(head[0], rw - 36, 19, 14, "表の見出し") if head[0] else None
    hcells = [cell(c, cw - 20, 21, 14, "表の見出し") for c in head[1:]]
    hh = max(58, max([c[2] for c in hcells] + [corner[2] if corner else 0]) + 24)
    grid = []
    for r in body:
        rh = cell(r[0], rw - 36, 21, 14, "行の見出し")
        cs = [cell(c, cw - 22, 20, 14, "表の値") for c in r[1:]]
        grid.append((rh, cs, max(56, max([rh[2]] + [c[2] for c in cs]) + 22)))
    y0 = TOP + 6
    total = hh + sum(g[2] for g in grid)
    H = y0 + total + (88 if dg.get("note") else 64)
    img, d = canvas(H, title, pal)
    card(d, [x0, y0, x1, y0 + total], pal, radius=16)
    d.rounded_rectangle([x0, y0, x1, y0 + hh], radius=16, fill=pal["accent"])
    d.rectangle([x0, y0 + hh - 16, x1, y0 + hh], fill=pal["accent"])
    head_ink = on_color(pal["accent"], pal)

    def put(c, cx, cy, fill, align="center", left=0):
        if c[0] == "mark":
            draw_mark(d, c[1], cx, cy, pal)
            return
        lines, f = c[1]
        top = cy - len(lines) * lh(f) / 2
        for k, ln in enumerate(lines):
            if align == "center":
                d.text((cx, top + lh(f) * (k + 0.5)), ln, font=f, fill=fill, anchor="mm")
            else:
                d.text((left, top + lh(f) * (k + 0.5)), ln, font=f, fill=fill, anchor="lm")
    if corner:
        put(corner, 0, y0 + hh / 2, mix(head_ink, pal["accent"], 0.2), align="left", left=x0 + 22)
    for j, c in enumerate(hcells):
        put(c, x0 + rw + cw * (j + 0.5), y0 + hh / 2, head_ink)
    y = y0 + hh
    zebra = mix(pal["soft"], WHITE, 0.45)
    for i, (rh, cs, h) in enumerate(grid):
        last = i == len(grid) - 1
        if i % 2 == 1:
            if last:
                d.rounded_rectangle([x0 + 2, y, x1 - 2, y + h - 2], radius=14, fill=zebra)
                d.rectangle([x0 + 2, y, x1 - 2, y + 16], fill=zebra)
            else:
                d.rectangle([x0 + 2, y, x1 - 2, y + h], fill=zebra)
        if i:
            d.line([(x0 + 2, y), (x1 - 2, y)], fill=pal["line"], width=1.5)
        put(rh, 0, y + h / 2, pal["ink"], align="left", left=x0 + 22)
        for j, c in enumerate(cs):
            put(c, x0 + rw + cw * (j + 0.5), y + h / 2, pal["ink"])
        y += h
    for j in range(ncol):
        x = x0 + rw + cw * j
        d.line([(x, y0 + 10), (x, y0 + hh - 10)], fill=mix(pal["accent"], WHITE, 0.35), width=1.5)
        d.line([(x, y0 + hh), (x, y0 + total - 2)], fill=pal["line"], width=1.5)
    note(ctx, d, H, str(dg.get("note") or ""))
    credit(d, H, credit_text(ctx.cfg), pal)
    return img


# ── cycle（循環） ────────────────────────────────────────────
def _cycle(ctx, dg, title, items):
    pal, probe, n = ctx.pal, Pen(), len(items)
    nw = 300 if n <= 4 else 272
    blocks = [make_block(ctx, probe, it, nw - 70, head=(2, 22, 15), sub=(2, 17, 13)) for it in items]
    nh = max(72, max(b.height for b in blocks) + 26)
    rx, ry = {3: (300, 165), 4: (330, 160), 5: (345, 178), 6: (360, 190)}[n]
    cx = W / 2
    cy = TOP + 12 + nh / 2 + ry
    H = cy + ry + nh / 2 + 64
    center = str(dg.get("center") or "").strip()
    cblock = None
    if center:
        cl, cf, ok = fit_block(probe, center, 150, 3, 24, 15)
        if not ok:
            ctx.problem(f"真ん中の語「{center[:20]}」が縮めても収まりません（短くしてください）")
        cblock = (cl, cf)
    angles = [-math.pi / 2 + 2 * math.pi * i / n for i in range(n)]
    pos = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in angles]
    rects = [(x - nw / 2, y - nh / 2, x + nw / 2, y + nh / 2) for x, y in pos]
    img, d = canvas(H, title, pal)
    # 輪の帯は線の内側に描かれるので、半分の太さだけ外へ広げて矢印の通り道の真ん中に帯を置く
    d.ellipse([cx - rx - 6, cy - ry - 6, cx + rx + 6, cy + ry + 6], outline=mix(pal["accent"], pal["bg"], 0.8), width=12)

    def free(p):
        return not any(r[0] - 12 <= p[0] <= r[2] + 12 and r[1] - 12 <= p[1] <= r[3] + 12 for r in rects)
    for i in range(n):
        a0, a1 = angles[i], angles[i] + 2 * math.pi / n
        ts = [a0 + (a1 - a0) * k / 160 for k in range(161)]
        runs, cur = [], []
        for t in ts:
            p = (cx + rx * math.cos(t), cy + ry * math.sin(t))
            if free(p):
                cur.append((t, p))
            elif cur:
                runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        if not runs:
            continue
        run = max(runs, key=len)
        if len(run) > 3:
            d.line([p for _, p in run[:-2]], fill=pal["accent"], width=5, joint="curve")
        t, (px, py) = run[-1]
        tx, ty = -rx * math.sin(t), ry * math.cos(t)
        k = math.hypot(tx, ty) or 1
        ux, uy = tx / k, ty / k
        d.polygon([(px + ux * 6, py + uy * 6), (px - ux * 14 - uy * 10, py - uy * 14 + ux * 10),
                   (px - ux * 14 + uy * 10, py - uy * 14 - ux * 10)], fill=pal["accent"])
    if cblock:
        d.ellipse([cx - 88, cy - 88, cx + 88, cy + 88], fill=pal["soft"])
        lines, f = cblock
        top = cy - len(lines) * lh(f) / 2
        for k, ln in enumerate(lines):
            d.text((cx, top + lh(f) * (k + 0.5)), ln, font=f, fill=pal["accent"], anchor="mm")
    for i, ((x, y), b) in enumerate(zip(pos, blocks)):
        card(d, [x - nw / 2, y - nh / 2, x + nw / 2, y + nh / 2], pal, radius=14)
        badge(d, x - nw / 2 + 30, y, 17, str(i + 1), pal)
        b.draw(d, x - nw / 2 + 58, y - b.height / 2, pal["ink"], ctx.sub, align="left")
    credit(d, H, credit_text(ctx.cfg), pal)
    return img


# ── funnel（絞り込み） ─────────────────────────────────────────
def _funnel(ctx, dg, title, items):
    pal, probe, n = ctx.pal, Pen(), len(items)
    heads = [it.split("|")[0].strip() for it in items]
    subs = [[s.strip() for s in it.split("|")[1:] if s.strip()] for it in items]
    has_sub = any(subs)
    fw = 600 if has_sub else 760
    fx = M + 10 if has_sub else (W - fw) / 2
    cx = fx + fw / 2
    widths = [fw * (1 - 0.5 * i / (n - 1)) for i in range(n)]
    tx = fx + fw + 48
    sh, gap = 74, 10
    hb = []
    for h, w in zip(heads, widths):
        lines, f, ok = fit_block(probe, h, w - 48, 2, 24, 15)
        if not ok:
            ctx.problem(f"段「{h[:20]}」が縮めても収まりません（短くしてください）")
        hb.append((lines, f))
    sb = []
    for s in subs:
        if not s:
            sb.append(None)
            continue
        lines, f, ok = fit_multi(probe, s, W - M - tx, 3, 20, 14)
        if not ok:
            ctx.problem(f"段の補足「{s[0][:20]}」が縮めても収まりません（短くしてください）")
        sb.append((lines, f))
    sh = max([sh] + [len(b[0]) * lh(b[1]) + 22 for b in hb] + [len(b[0]) * lh(b[1]) + 10 for b in sb if b])
    y0 = TOP + 10
    H = y0 + n * sh + (n - 1) * gap + 64
    img, d = canvas(H, title, pal)
    for i in range(n):
        y = y0 + i * (sh + gap)
        w = widths[i]
        fill = mix(pal["accent"], WHITE, 0.5 * i / (n - 1))
        if i:
            pw = widths[i - 1]
            d.polygon([(cx - pw / 2 + 14, y - gap), (cx + pw / 2 - 14, y - gap),
                       (cx + w / 2 - 6, y + 4), (cx - w / 2 + 6, y + 4)], fill=mix(fill, pal["bg"], 0.55))
        d.rounded_rectangle([cx - w / 2, y, cx + w / 2, y + sh], radius=14, fill=fill)
        lines, f = hb[i]
        top = y + (sh - len(lines) * lh(f)) / 2
        for k, ln in enumerate(lines):
            d.text((cx, top + lh(f) * (k + 0.5)), ln, font=f, fill=on_color(fill, pal, large=f.size >= 19), anchor="mm")
        if sb[i]:
            ym = y + sh / 2
            d.line([(cx + w / 2 + 8, ym), (tx - 16, ym)], fill=mix(pal["line"], pal["muted"], 0.3), width=2)
            d.ellipse([tx - 20, ym - 4, tx - 12, ym + 4], fill=pal["accent"])
            sl, sf = sb[i]
            top = ym - len(sl) * lh(sf) / 2
            for k, ln in enumerate(sl):
                d.text((tx, top + lh(sf) * (k + 0.5)), ln, font=sf, fill=pal["ink"], anchor="lm")
    credit(d, H, credit_text(ctx.cfg), pal)
    return img


# ── bars（数字の横棒） ─────────────────────────────────────────
_Z2H = str.maketrans("０１２３４５６７８９，．％－", "0123456789,.%-")
_VAL = re.compile(r"^\s*(\d[\d,]*(?:\.\d+)?)\s*(.*)$")


def parse_bar(item, unit=""):
    """「ラベル|数値」→ (ラベル, 値, 数値の書き方, 単位)。形が違えば None"""
    parts = [s.strip() for s in str(item).split("|")]
    if len(parts) != 2 or not parts[0]:
        return None
    m = _VAL.match(parts[1].translate(_Z2H))
    if not m:
        return None
    try:
        v = Decimal(m.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    return parts[0], v, m.group(1), (m.group(2).strip() or str(unit or "").strip())


def _bars(ctx, dg, title, items):
    pal, probe, n = ctx.pal, Pen(), len(items)
    unit = str(dg.get("unit") or "")
    rows = [parse_bar(it, unit) for it in items]
    lw, vw = 300, 176
    labels = []
    for label, *_ in rows:
        lines, f, ok = fit_block(probe, label, lw - 20, 2, 22, 14)
        if not ok:
            ctx.problem(f"ラベル「{label[:20]}」が縮めても収まりません（短くしてください）")
        labels.append((lines, f))
    vals = []
    for _, _, raw, u in rows:
        nf = one_line(ctx, probe, raw + u, vw - 20, 26, 16, "数値")
        uf = font(max(13, int(nf.size * 0.66)))
        vals.append((raw, u, nf, uf))
    row_h = max([58] + [len(lb[0]) * lh(lb[1]) + 18 for lb in labels])
    x0, x1 = M + lw + 10, W - M - vw
    vmax = max(r[1] for r in rows) or Decimal(1)
    y0 = TOP + 12
    H = y0 + n * row_h + (90 if dg.get("note") else 64)
    img, d = canvas(H, title, pal)
    d.rounded_rectangle([M - 10, y0 - 6, W - M + 10, y0 + n * row_h + 6], radius=16, fill=WHITE,
                        outline=pal["line"], width=2)
    track = mix(pal["soft"], WHITE, 0.35)
    for i, ((label, v, raw, u), (lines, f), (_, _, nf, uf)) in enumerate(zip(rows, labels, vals)):
        yc = y0 + row_h * (i + 0.5)
        top = yc - len(lines) * lh(f) / 2
        for k, ln in enumerate(lines):
            d.text((M + 14, top + lh(f) * (k + 0.5)), ln, font=f, fill=pal["ink"], anchor="lm")
        d.rounded_rectangle([x0, yc - 13, x1, yc + 13], radius=13, fill=track)
        bw = max(14, float((x1 - x0) * float(v / vmax)))
        d.rounded_rectangle([x0, yc - 13, x0 + bw, yc + 13], radius=13, fill=pal["accent"])
        vx = x0 + bw + 12
        d.text((vx, yc), raw, font=nf, fill=pal["ink"], anchor="lm")
        if u:
            d.text((vx + d.textlength(raw, font=nf) + 3, yc + nf.size * 0.12), u, font=uf, fill=ctx.sub, anchor="lm")
    d.line([(x0, y0 + 4), (x0, y0 + n * row_h - 4)], fill=pal["line"], width=2)
    note(ctx, d, H, str(dg.get("note") or ""))
    credit(d, H, credit_text(ctx.cfg), pal)
    return img


# ── pyramid（階層） ───────────────────────────────────────────
def _pyramid(ctx, dg, title, items):
    pal, probe, n = ctx.pal, Pen(), len(items)
    pw = 520
    px = M + 10
    cx = px + pw / 2
    tx = px + pw + 60
    blocks = [make_block(ctx, probe, it, W - M - tx, head=(2, 23, 15), sub=(2, 18, 13)) for it in items]
    lv = max(86, max(b.height for b in blocks) + 18)
    gap = 7
    y0 = TOP + 12
    ph = n * lv
    H = y0 + ph + 64
    img, d = canvas(H, title, pal)

    def half(y):
        return pw / 2 * (y - y0) / ph
    for i, b in enumerate(blocks):
        yt = y0 + i * lv + (gap / 2 if i else 0)
        yb = y0 + (i + 1) * lv - gap / 2
        fill = mix(pal["accent"], WHITE, 0.08 + 0.5 * i / (n - 1))
        d.polygon([(cx - half(yt), yt), (cx + half(yt), yt), (cx + half(yb), yb), (cx - half(yb), yb)], fill=fill)
        ym = (yt + yb) / 2 + (lv * 0.16 if i == 0 else 0)
        d.text((cx, ym), str(i + 1), font=font(22), fill=on_color(fill, pal, large=True), anchor="mm")
        yc = y0 + (i + 0.5) * lv
        d.line([(cx + half(yc) + 10, yc), (tx - 18, yc)], fill=mix(pal["line"], pal["muted"], 0.3), width=2)
        d.ellipse([tx - 22, yc - 4, tx - 14, yc + 4], fill=pal["accent"])
        b.draw(d, tx, yc - b.height / 2, pal["ink"], ctx.sub, align="left")
    credit(d, H, credit_text(ctx.cfg), pal)
    return img


# ── tree（分類） ──────────────────────────────────────────────
def _tree(ctx, dg, title, items):
    pal, probe = ctx.pal, Pen()
    root = str(dg.get("root") or "").strip()
    branches = [[s.strip() for s in it.split("|") if s.strip()] for it in items]
    n = len(branches)
    gap = 24
    bw = (W - 2 * M - gap * (n - 1)) / n
    rl, rf, ok = fit_block(probe, root, 440, 2, 26, 17)
    if not ok:
        ctx.problem(f"分ける対象「{root[:20]}」が縮めても収まりません（短くしてください）")
    root_h = len(rl) * lh(rf) + 28
    root_w = min(520, max(280, max(probe.textlength(x, font=rf) for x in rl) + 80))
    heads, leaves = [], []
    for b in branches:
        hl, hf, ok = fit_block(probe, b[0], bw - 32, 2, 22, 15)
        if not ok:
            ctx.problem(f"枝「{b[0][:20]}」が縮めても収まりません（短くしてください）")
        heads.append((hl, hf))
        ls = []
        for leaf in b[1:]:
            ll, lf, ok = fit_block(probe, leaf, bw - 56, 2, 19, 13, weight="regular")
            if not ok:
                ctx.problem(f"葉「{leaf[:20]}」が縮めても収まりません（短くしてください）")
            ls.append((ll, lf))
        leaves.append(ls)
    head_h = max(len(h[0]) * lh(h[1]) for h in heads) + 26
    leaf_h = [sum(len(x[0]) * lh(x[1]) + 12 for x in ls) for ls in leaves]
    box_h = head_h + (max(leaf_h) + 22 if any(leaf_h) else 0)
    y_root = TOP + 6
    bus = y_root + root_h + 30
    box_top = bus + 26
    H = box_top + box_h + 64
    img, d = canvas(H, title, pal)
    con = mix(pal["accent"], WHITE, 0.45)
    xs = [M + (bw + gap) * i + bw / 2 for i in range(n)]
    d.line([(W / 2, y_root + root_h), (W / 2, bus)], fill=con, width=3)
    d.line([(xs[0], bus), (xs[-1], bus)], fill=con, width=3)
    d.rounded_rectangle([W / 2 - root_w / 2, y_root, W / 2 + root_w / 2, y_root + root_h], radius=16, fill=pal["accent"])
    top = y_root + 14
    for k, ln in enumerate(rl):
        d.text((W / 2, top + lh(rf) * (k + 0.5)), ln, font=rf, fill=on_color(pal["accent"], pal), anchor="mm")
    for i, x in enumerate(xs):
        d.line([(x, bus), (x, box_top)], fill=con, width=3)
        bx0 = x - bw / 2
        card(d, [bx0, box_top, bx0 + bw, box_top + box_h], pal, radius=14)
        d.rounded_rectangle([bx0 + 1, box_top + 1, bx0 + bw - 1, box_top + head_h], radius=13, fill=pal["soft"])
        d.rectangle([bx0 + 1, box_top + head_h - 13, bx0 + bw - 1, box_top + head_h], fill=pal["soft"])
        hl, hf = heads[i]
        top = box_top + (head_h - len(hl) * lh(hf)) / 2
        for k, ln in enumerate(hl):
            d.text((x, top + lh(hf) * (k + 0.5)), ln, font=hf, fill=pal["accent"], anchor="mm")
        y = box_top + head_h + 16
        for ll, lf in leaves[i]:
            d.ellipse([bx0 + 20, y + lh(lf) / 2 - 4, bx0 + 28, y + lh(lf) / 2 + 4], fill=pal["accent"])
            for k, ln in enumerate(ll):
                d.text((bx0 + 38, y + lh(lf) * (k + 0.5)), ln, font=lf, fill=pal["ink"], anchor="lm")
            y += len(ll) * lh(lf) + 12
    credit(d, H, credit_text(ctx.cfg), pal)
    return img


# ── 宣言の検査 ─────────────────────────────────────────────
# 型 → (最小, 最大, 数える単位, 中身の目安)。書き手への案内（brief）と検査の両方がここを読む
TYPES = {
    "flow":    (2, 5, "項目", "手順（順番に進むもの）"),
    "steps":   (2, 6, "項目", "時系列・段階（期間のラベルを付けられる）"),
    "list":    (3, 6, "項目", "確かめること・満たす条件"),
    "vs":      (2, 2, "列", "NG と OK・よくある誤解と正しい理解"),
    "matrix":  (3, 6, "行", "比較（2〜4つの選択肢を同じ観点で見比べる）"),
    "cycle":   (3, 6, "項目", "繰り返し回すもの（PDCA・毎月の運用）"),
    "funnel":  (3, 5, "段", "段階的に絞られるもの（表示→クリック→問い合わせ）"),
    "bars":    (3, 8, "項目", "数字の大小（本文・表にある数字だけ）"),
    "pyramid": (3, 5, "段", "土台から積み上がる階層・優先度"),
    "tree":    (2, 4, "枝", "分類（1つの対象を種類に分ける）"),
}
OLD_TYPES = ("flow", "list", "vs")


def span(dtype):
    """型の数の範囲の書き方（「2〜5項目」「2列」）"""
    lo, hi, unit, _ = TYPES[dtype]
    return f"{lo}{unit}" if lo == hi else f"{lo}〜{hi}{unit}"


def all_texts(dg):
    """図に描く文字（英語の混入の検査に使う）"""
    out = [str(dg.get("title") or "")] + [str(x) for x in dg.get("items") or []]
    out += [str(x) for x in dg.get("labels") or []]
    out += [str(dg.get(k)) for k in ("root", "center", "unit", "note") if dg.get(k)]
    return out


def visible_text(body):
    """数字の検算に使う本文。図の画像タグ・図の説明・リンク先・コメントは除く
    （図の宣言を写しただけの alt の数字を「本文にある」と数えない）"""
    t = re.sub(r"<!--.*?-->", " ", str(body or ""), flags=re.S)
    t = re.sub(r"<figure\b.*?</figure>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<img\b[^>]*>", " ", t, flags=re.I)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\]\([^)]*\)", "]", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return t.translate(_Z2H)


_NUM = re.compile(r"(?<![0-9.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")


def numbers_in(text):
    """文に出る数。「1.2万」「3億」は万・億を掛けた値も数える"""
    out = set()
    for m in _NUM.finditer(text):
        v = Decimal(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))
        out.add(v)
        tail = text[m.end():m.end() + 1]
        if tail == "万":
            out.add(v * 10000)
        elif tail == "億":
            out.add(v * 100000000)
    return out


def label_keys(label):
    """ラベルを本文の行で探すときの手がかり（2文字以上の漢字・カタカナ・英数字。漢字は2字ずつでも探す）"""
    s = str(label).translate(_Z2H).lower()
    keys = set()
    for t in re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff\u3005\u3006\u30f6]{2,}|[\u30a1-\u30fa\u30fc]{2,}", s):
        keys.add(t)
        if not t.isascii() and len(t) > 2:
            keys.update(t[i:i + 2] for i in range(len(t) - 1))
    return keys


def bar_number_problems(name, items, unit, body):
    """bars の数値が本文・表に同じ値で、同じ段落・表の行のラベルと一緒に出ているか"""
    lines = [ln.lower() for ln in visible_text(body).splitlines()]
    out = []
    for it in items:
        p = parse_bar(it, unit)
        if not p:
            continue
        label, v, raw, u = p
        hits = [ln for ln in lines if v in numbers_in(ln)]
        if not hits:
            out.append(f"{name}: 「{label}」の値 {raw}{u} が本文・表にありません"
                       "（図の数字は本文に出ている数字だけ。描きません）")
            continue
        keys = label_keys(label)
        if keys and not any(k in ln for ln in hits for k in keys):
            out.append(f"{name}: 「{label}」の値 {raw} は本文にありますが、「{label}」と同じ段落・表の行にありません"
                       "（取り違えを防ぐため描きません。本文と同じ言葉のラベルにする）")
    return out


def declaration_problems(dg, body=None, need_body=False):
    """宣言1つの形の誤り（型・数・書き方・本文に無い数字）。描かずに分かるものだけを返す。
    body が無いとき、bars の数字は need_body なら「確かめられない」として止め、そうでなければ見ない"""
    if not isinstance(dg, dict):
        return ["diagrams の書き方が壊れています"]
    name = str(dg.get("name") or "?")
    dtype = str(dg.get("type") or "flow")
    if dtype not in TYPES:
        return [f"{name}: 未対応の型 {dtype}（{' / '.join(TYPES)}）"]
    out = []
    if not str(dg.get("name") or "").strip():
        out.append("name（ファイル名）がありません")
    if not str(dg.get("title") or "").strip():
        out.append(f"{name}: title（図の題）がありません")
    items = [str(x) for x in dg.get("items") or []]
    lo, hi, unit, _ = TYPES[dtype]
    count = len(items) - (1 if dtype == "matrix" else 0)
    if not lo <= count <= hi:
        out.append(f"{name}: {dtype} 型は{span(dtype)}です（{count}{unit}。この数では描きません）")
        return out
    parts = [[s.strip() for s in it.split("|")] for it in items]
    if dtype == "vs":
        if any(len(p) < 2 for p in parts):
            out.append(f"{name}: vs 型は「見出し|行1|行2」の形です")
    elif dtype == "matrix":
        ncol = len(parts[0]) - 1
        if not 2 <= ncol <= 4:
            out.append(f"{name}: matrix 型の1つ目（見出しの行）は「観点|A|B」の形で、列は2〜4です（{ncol}列）")
        elif any(len(p) != ncol + 1 for p in parts[1:]):
            out.append(f"{name}: matrix 型の行は見出しの行と同じ数（{ncol + 1}つ）に「|」で分けます")
        elif any(not c for p in parts[1:] for c in p) or any(not c for c in parts[0][1:]):
            out.append(f"{name}: matrix 型に空のマスがあります（無いなら「－」）")
    elif dtype == "steps":
        labels = dg.get("labels")
        if labels is not None and (not isinstance(labels, list) or len(labels) != len(items)):
            out.append(f"{name}: steps 型の labels は items と同じ数にします（{len(items)}つ）")
    elif dtype == "tree":
        if not str(dg.get("root") or "").strip():
            out.append(f"{name}: tree 型は root（分ける対象）が要ります")
        for p in parts:
            if len([s for s in p[1:] if s]) > 4:
                out.append(f"{name}: tree 型の葉は1つの枝に4つまでです（「{p[0][:16]}」は{len(p) - 1}つ）")
    elif dtype == "bars":
        unit_ = dg.get("unit") or ""
        bad = [it for it in items if parse_bar(it, unit_) is None]
        if bad:
            out.append(f"{name}: bars 型は「ラベル|数値」の形です（数値は数字で書く）… {bad[0][:30]}")
        elif body is None:
            if need_body:
                out.append(f"{name}: 記事の本文が無いので、bars の数字を確かめられません（描きません）")
        else:
            out += bar_number_problems(name, items, unit_, body)
    if dtype not in ("matrix", "bars") and any(not p[0] for p in parts):
        out.append(f"{name}: 見出しの空いた項目があります")
    return out


# この日以降の記事にだけ当てる決まり。既存の記事の宣言は書き換えない（本文と図の対応が崩れる）
DIAGRAM_RULES_FROM = "2026-10-09"


def article_problems(meta, body, site_root=None, slug=None):
    """1記事の図解の問題（build.py と image_check が使う）:
    宣言の誤り・描いた画像の欠け・（新しい記事だけ）同じ型の重なりと本文への置き忘れ"""
    slug = slug or meta.get("slug", "")
    site_root = Path(site_root) if site_root else ROOT / "site"
    out = []
    dgs = meta.get("diagrams") or []
    if not isinstance(dgs, list):
        return ["diagrams の書き方が壊れています（一覧で書く）"]
    for dg in dgs:
        probs = declaration_problems(dg, body)
        out += probs
        if isinstance(dg, dict) and not probs and not (site_root / "images" / slug / f"{dg.get('name')}.png").is_file():
            out.append(f"画像がありません: /images/{slug}/{dg.get('name')}.png")
    if str(meta.get("date") or "") >= DIAGRAM_RULES_FROM:
        types = [str(dg.get("type") or "flow") for dg in dgs if isinstance(dg, dict)]
        dup = sorted({t for t in types if types.count(t) > 1})
        if dup:
            out.append(f"同じ型の図が重なっています（{'・'.join(dup)}）。見出しの中身に合う別の型にしてください")
        for dg in dgs:
            if isinstance(dg, dict) and body is not None and f"/images/{slug}/{dg.get('name')}.png" not in body:
                out.append(f"宣言した図を本文に置いていません: {dg.get('name')}（その見出しの直下に figure で置く）")
    return out


# ── 描く ────────────────────────────────────────────────
NEW_TYPES = {"steps": _steps, "matrix": _matrix, "cycle": _cycle, "funnel": _funnel,
             "bars": _bars, "pyramid": _pyramid, "tree": _tree}


def render(slug, dg, body=None, save=True):
    """記事の宣言1つ（dict）を描いて site/images/<slug>/<name>.png に書く。
    宣言の誤りと、新しい型の収まらない文字があれば描かずに止める（SystemExit）。
    save=False は検査用: 保存せず、止めずに、問題の一覧を返す"""
    dtype = str((dg or {}).get("type") or "flow") if isinstance(dg, dict) else ""
    if save and body is None and dtype == "bars":
        body = article_body(slug)
    probs = declaration_problems(dg, body, need_body=save)
    if probs:
        if save:
            raise SystemExit("\n".join(probs))
        return probs
    items = [str(x) for x in dg.get("items") or []]
    name, title = str(dg["name"]), str(dg["title"])
    if dtype in OLD_TYPES:
        if save:
            if dtype == "flow":
                draw_flow(slug, name, title, items)
            elif dtype == "list":
                draw_list(slug, name, title, items)
            else:
                draw_vs(slug, name, title, items[0], items[1])
        return []        # 旧い型の収まりは image_check が同じ計算で測る（描いて止めることはしない）
    ctx = Ctx(slug, name, site_for_slug(slug))
    if Pen().textlength(title, font=font(20)) > W - 68 - 20:
        ctx.problem(f"題が長すぎて、縮めても1行に収まりません（{len(title)}字）")
    img = NEW_TYPES[dtype](ctx, dg, title, items)
    if ctx.problems:
        if save:
            raise SystemExit("\n".join(ctx.problems))
        return ctx.problems
    if save:
        save_png(img, slug, name)
    return []


def fit_problems(dg, slug="zz-check"):
    """新しい型の宣言を描いてみて、収まらない文字を返す（保存しない）。旧い型は []"""
    return render(slug, dg, body=None, save=False)


# ── 書き手への案内（site_brief が出す） ─────────────────────────────
EXAMPLES = [
    "  - name: nagare\n    type: steps\n    title: 申請から入金までの流れ\n"
    "    items: [\"GビズIDを取る|2〜3週間かかる\", \"計画を書く\", \"申請する\", \"実績を報告する\"]\n"
    "    labels: [\"申請前\", \"1か月目\", \"2か月目\", \"採択後\"]",
    "  - name: hikaku\n    type: matrix\n    title: 依頼先ごとにできること\n"
    "    items: [\"業務|税理士|経理代行|派遣\", \"記帳|○|○|△\", \"給与計算|△|○|○\", \"決算申告|○|×|×\"]",
    "  - name: share\n    type: bars\n    title: AIの出典に選ばれた回数\n"
    "    items: [\"ChatGPT|42\", \"Gemini|31\", \"Perplexity|18\"]\n    unit: 回\n"
    "    note: 出典：当サイトの計測（2026年9月）   # 数字は本文・表と同じ値・同じ段落か行",
    "  - name: wakekata\n    type: tree\n    title: 補助金の分け方\n    root: 国の主な補助金\n"
    "    items: [\"設備|ものづくり補助金\", \"IT|デジタル化・AI導入補助金\", \"販路|持続化補助金\"]",
]


def recent_combos(site_id, n=12):
    """そのサイトの直近の記事の図の型の組み合わせ（新しい順）"""
    rows = []
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    owner = {}
    for sid, cfg in sites_mod.load_all().items():      # find_category_owner と同じく、先に定義した社が持ち主
        for c in cfg.get("categories", {}):
            owner.setdefault(c, sid)
    for p in (ROOT / "articles").glob("*.md"):
        m = re.match(r"^---\s*\n(.*?)\n---", p.read_text(encoding="utf-8-sig"), re.S)
        cat = re.search(r"^category:\s*(\S+)", m.group(1), re.M) if m else None
        # 他サイトの記事は YAML を読まない（全記事を読むと案内だけで4秒かかった）
        if not cat or owner.get(cat.group(1)) != site_id:
            continue
        try:
            fm = yaml.load(m.group(1), Loader=loader) or {}
        except yaml.YAMLError:
            continue
        if not fm.get("diagrams"):
            continue
        types = [str(dg.get("type") or "flow") for dg in fm["diagrams"] if isinstance(dg, dict)]
        rows.append((str(fm.get("date") or ""), p.stem, types))
    rows.sort(reverse=True)
    return rows[:n]


def brief(site_id):
    """記事を書く前に読ませる図解の案内（型の選び方・書き方・直近の組み合わせ）"""
    from collections import Counter
    out = ["■ 図解（フロントマターの diagrams。見出しの中身に合う型を選ぶ）"]
    for t, (_, _, _, use) in TYPES.items():
        out.append(f"  {t:8s} {use}（{span(t)}）")
    out += ["  決まり:",
            "   - 1つの見出しに1枚。その見出しの直下に <figure><img src=\"/images/<slug>/<name>.png\" alt=\"…\"></figure> で置く",
            "   - 同じ記事で同じ型を重ねない（list を2枚にしない）。flow+list+vs の3点セットを毎回使わない",
            "   - 手順なら steps/flow、比較なら matrix/vs、数字の大小なら bars、繰り返しなら cycle、"
            "絞り込みなら funnel、階層なら pyramid、分類なら tree",
            "   - bars の数字は本文・表に同じ値で書いたものだけ（ラベルと同じ段落・表の行）。無ければ描かれない",
            "   - 図の文字は日本語だけ。図に描いた大事な情報は本文にも書く（AIは画像を引用できない）"]
    rows = recent_combos(site_id)
    if rows:
        combos = Counter("+".join(sorted(t)) for _, _, t in rows)
        used = Counter(t for _, _, ts in rows for t in ts)
        out.append(f"  直近{len(rows)}本の組み合わせ: " + " / ".join(f"{k} {v}本" for k, v in combos.most_common(4)))
        rare = [t for t in TYPES if used[t] == 0]
        if rare:
            out.append("  直近で使っていない型（中身に合うなら優先する）: " + "・".join(rare))
        top = combos.most_common(1)[0]
        if len(rows) >= 4 and top[1] * 2 >= len(rows):
            out.append(f"  ※ {top[0]} が半分以上を占めています。今回は別の組み合わせにする")
    out.append("  書き方の例:")
    out += EXAMPLES
    return out


def main():
    args = sys.argv[1:]
    dtype = "flow"
    if args[:1] == ["--type"]:
        dtype, args = args[1], args[2:]
    opts, rest, i = {}, [], 0
    while i < len(args):
        if args[i] in ("--labels", "--unit", "--note", "--center", "--root") and i + 1 < len(args):
            opts[args[i][2:]] = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1
    if len(rest) < 3:
        raise SystemExit(__doc__)
    dg = {"name": rest[1], "type": dtype, "title": rest[2], "items": rest[3:], **opts}
    if "labels" in dg:
        dg["labels"] = dg["labels"].split("|")
    render(rest[0], dg)


if __name__ == "__main__":
    main()
