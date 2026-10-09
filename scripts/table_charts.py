# -*- coding: utf-8 -*-
"""記事の表の数字を、同じ数字の横棒グラフ（インラインの SVG）にして表の直後に添える（4サイト共通の部品）。

表は数字を正確に伝えるが、どれが大きいかは読み比べないと分からない。グラフはその大小をひと目で見せる。
表は消さない（表がデータの正。グラフは同じ数字の見え方を足すだけ）。

使う所（変換の最後に1回だけ呼ぶ）:
  - AI集客ラボ: build.py の記事の変換（add_to_html）
  - コーポレート（nextjs-json）・補助金（external-html）: publish.py の各社の変換（add_to_html）
  - お客様の社（external-md。先方の build-journal.mjs が marked で HTML にする）: publish.py（add_to_markdown）。
    グラフは前後に空行を置いた1行の HTML の塊にする（CommonMark は空行まで HTML の塊として素通しする）

描く表（全部を満たすときだけ。誤ったグラフより、描かない方がよい）:
  - データの行が3〜12。1列目がラベル（文字）
  - 数字の列は、その列の8割以上の行が「同じ単位の1つの数」だけで書かれている（30% / 1,200万円 / 45件）。
    単位が見出しの括弧にある列（「費用（万円）」）は「1,200」も数として読む
  - 範囲（3〜5）・約・以上・〜・年や年度・日付・番号・電話・版・注記の付いた数（上限1,000万円）は数として扱わない。
    単位の混ざる列・符号の付いた数（-5%・▲2件）がある列・全部同じ値の列は描かない
  - 量（円・件など）の列の合計の行は棒にしない（内訳と同じ物差しに並べると、内訳がつぶれる。率の「全体」は残す）
  - 数字の列がちょうど2つで単位が同じなら2本ずつの棒（凡例つき）。それ以外は数の多い列を1つ（同じなら左）
1記事に2つまで。描く棒の多い表を先に選ぶ（同じなら記事の前にある表）。挿す位置はそれぞれの表の直後

数字は表にあるものだけ。四捨五入も単位の変換もしない（棒の端の数字は表の文字そのまま）。
作った SVG を XML として読み戻し、ラベル・数字の文字・棒の長さが表と1つでも合わなければ、その表には描かない。

見た目: 横棒・値は棒の端・薄い目盛り・ラベルは折り返し・最大値の棒が描ける幅いっぱい。
色はサイトの図の色（sites/<id>.json の diagram_colors。無ければ make_diagram の既定 = いまの記事の図の色）。
1本目の棒は図の主色。文字・目盛りは currentColor（本文の文字色）なので、明るい地でも暗い地でも読める。
2本目は本文の文字色（主色と明るさが十分に違う社）か、主色を白に半分混ぜた淡い色（主色も濃紺の社）。
どの社の組も、色覚の型を問わず ΔE 29 以上を dataviz の検算で確かめた（colors_for）。サイトの CSS・外部の
フォント・ライブラリは使わない（色・大きさは SVG の属性に書く。字体だけは本文から受け継ぐ）。
幅は viewBox と width:100% で可変（スマホの本文幅 350px で文字 12px、パソコンは max-width 460px で 16px）。

  python scripts/table_charts.py <slug>...      # 記事の表のうち、どれを描くか・描かない理由を出す
  python scripts/table_charts.py --stats        # サイトごとに、グラフが付く記事の本数と付かない理由を数える
"""
import html as H
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

MAX_CHARTS = 2
MIN_ROWS, MAX_ROWS = 3, 12
SHARE = Decimal("0.8")

# 数として読む単位（長い順に照合する）。年・月・位・号・版は入れない（年や日付・順位・番号は大小を比べる量ではない）
UNITS = ("億円", "万円", "千円", "兆円", "円", "%", "ポイント", "pt", "割", "倍", "点",
         "万件", "件", "社", "者", "万人", "人", "名", "人月", "人日", "日間", "日", "時間", "分間", "分", "秒",
         "週間", "か月", "ヶ月", "カ月", "ケ月", "ヵ月", "万回", "回", "本", "個", "台", "店舗", "店", "院",
         "校", "枚", "冊", "語", "文字", "字", "ページ", "項目", "問", "行", "歳", "ms", "KB", "MB", "GB", "kg", "km")
_UNIT = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
# 3桁区切りは正しい位置だけ（1,200 / 12,000）。先頭の0は 0 と 0.5 だけ（05 は番号）
_NUM = r"(?:0|[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d*)(?:\.\d+)?"
NUM_RE = re.compile(rf"(?P<num>{_NUM})(?P<unit>{_UNIT})?")
SIGNED = re.compile(r"^[\-−－‐▲△+＋±]\s*\d")
# 見出しがこれで終わるなら、数に見えても大小の量ではない（年・日付・期限・番号・連絡先・版・順位）。
# 終わりだけを見る（「2次締切の採択率」は率の列）
HEADER_SKIP = re.compile(r"(?:年度|年月|年月日|日付|期日|期限|締切|締め切り|締切日|開始日|終了日|時期|時点|番号|電話|TEL|FAX|"
                         r"郵便|バージョン|順位|ランク)$|^(?:年|月|日|No\.?|#|ID|Ver\.?)$", re.I)
# 合計の行。内訳と同じ物差しに並べると内訳がつぶれるので、量（円・件など）の列では棒にしない。率（%・割・倍）の列の「全体」は
# 同じ物差しの値なので残す
TOTAL_ROW = re.compile(r"(?:合計|総計|小計|総額|合算|全体)(?:（[^）]*）|\([^)]*\))?$|^(?:計|総数|トータル)$")
RATIO_UNITS = {"%", "割", "倍", "ポイント", "pt"}
HEADER_UNIT = re.compile(rf"[（(［\[【]\s*(?:単位\s*[:：]?\s*)?(?P<unit>{_UNIT})\s*[）)］\]】]")

# 見た目の寸法（viewBox の単位）。スマホの本文幅 340〜350px では 0.86 倍前後で文字が 12px、
# パソコンでは max-width で 1.15 倍（文字 16px・本文と同じ大きさ）までにとどめる
W = 400
MAX_PX = 460
PAD = 8
FS = 14              # ラベル・値の文字
FS_LEG = 13          # 凡例の文字
FS_VAL2 = 13         # 2本ずつの棒の値（上下の値が重ならない大きさ）
LH = 18              # ラベルの行の高さ
BAR1, BAR2, INNER = 15, 12, 3   # 棒の太さ（1本 / 2本ずつ）と、2本の間の地の隙間
ROW_GAP = 12
GAP_LB, GAP_BV = 8, 6           # ラベル→棒、棒の端→値
LEG_H = 22
RADIUS = 4
NS = "{http://www.w3.org/2000/svg}"
# 2本目を本文の文字色にしてよい、主色と文字色（ink）の輝度比の下限。AI集客ラボ 3.0・お客様の社 3.7 は文字色、
# コーポレート 1.8・補助金 1.7 は主色の淡い色にする
S2_INK_MIN = 2.5


# ============================================================
# 表を読む
# ============================================================
def _cell_text(cell_html):
    """表のセル（HTML）→ 読者に見える文字。改行（<br>）は改行のまま残す（2つの数が並ぶセルを1つの数と読まない）"""
    s = re.sub(r"<br\s*/?>", "\n", cell_html, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return H.unescape(s).replace("\xa0", " ").strip()


def html_table_cells(table_html):
    """<table>…</table> → (見出しの列, データの行)。行は <tr> の順、セルは <th>/<td> の順"""
    rows = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table_html, re.S | re.I):
        rows.append([_cell_text(c) for c in re.findall(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", tr, re.S | re.I)])
    if not rows:
        return [], []
    return rows[0], rows[1:]


def number(cell, unit_hint=None):
    """セルが「1つの数（と単位）」だけなら (値, 表の文字, 単位)。範囲・約・注記・年・番号などは None。
    表の文字（shown）は四捨五入も変換もしない。単位が見出しにしか無いときは、表の文字の後に足して見せる"""
    if not cell or "\n" in cell:
        return None
    t = re.sub(r"\s+", "", unicodedata.normalize("NFKC", cell))
    m = NUM_RE.fullmatch(t)
    if not m:
        return None
    unit = m.group("unit") or unit_hint
    if not unit:
        return None
    shown = cell.strip() if m.group("unit") else cell.strip() + unit
    return Decimal(m.group("num").replace(",", "")), shown, unit


def _label_ok(label):
    """1列目がラベル（文字）か。数だけ（100人・30%・2）はラベルではない"""
    t = re.sub(r"\s+", "", unicodedata.normalize("NFKC", label or ""))
    if not t:
        return False
    if NUM_RE.fullmatch(t) or re.fullmatch(r"[\d.,%]+", t):
        return False
    return True


def _column(head, cells):
    """数字の列なら {'head', 'nums', 'unit'}、そうでなければ描かない理由"""
    bare = re.sub(r"[（(][^）)]*[）)]$", "", re.sub(r"\s+", "", unicodedata.normalize("NFKC", head or "")))
    if HEADER_SKIP.search(bare):
        return "見出しが年・日付・期限・番号・順位"
    if any(SIGNED.match(unicodedata.normalize("NFKC", c or "").strip()) for c in cells):
        return "符号の付いた数（増減・マイナス）がある"
    m = HEADER_UNIT.search(unicodedata.normalize("NFKC", head or ""))
    hint = m.group("unit") if m else None
    nums = [number(c, hint) for c in cells]
    got = [n for n in nums if n]
    if not got or Decimal(len(got)) < SHARE * len(cells):
        return "数だけの行が8割に届かない（範囲・約・注記・文章）"
    if len({n[2] for n in got}) > 1:
        return "単位が混ざる"
    vals = [n[0] for n in got]
    if max(vals) <= 0:
        return "全部が0"
    if len(set(vals)) == 1:
        return "全部同じ値"
    return {"head": (head or "").strip(), "nums": nums, "unit": got[0][2]}


def _one_line(s):
    return re.sub(r"\s+", " ", s or "").strip()


def analyze(header, rows):
    """表 → 描く内容（dict）か、描かない理由（str）"""
    header = [_one_line(h) for h in header]
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if not (MIN_ROWS <= len(rows) <= MAX_ROWS):
        return f"行が{MIN_ROWS}〜{MAX_ROWS}でない"
    if len(header) < 2:
        return "列が足りない"
    if not all(_label_ok(r[0] if r else "") for r in rows):
        return "1列目がラベル（文字）でない"
    cols, why = [], []
    for k in range(1, len(header)):
        c = _column(header[k], [(r[k] if k < len(r) else "") for r in rows])
        (cols if isinstance(c, dict) else why).append(c)
    if not cols:
        # いちばん多かった理由を返す（数を数えるときに、何が足りないのかが分かるように）
        return max(set(why), key=why.count) if why else "数字の列が無い"
    if len(cols) == 2 and cols[0]["unit"] == cols[1]["unit"]:
        use = cols
    else:
        use = [max(cols, key=lambda c: sum(1 for n in c["nums"] if n))]   # 同じ数なら左（max は最初を返す）
    unit = use[0]["unit"]
    out_rows, totals, skipped = [], [], 0
    for i, r in enumerate(rows):
        label = _one_line(r[0])
        vals = [c["nums"][i] for c in use]
        if unit not in RATIO_UNITS and TOTAL_ROW.search(re.sub(r"\s+", "", label)):
            totals.append(label)
        elif any(vals):
            out_rows.append((label, vals))
        else:
            skipped += 1
    if len(out_rows) < MIN_ROWS:
        return f"合計・数の無い行を除くと{MIN_ROWS}行に届かない"
    vals = [v[0] for _, vs in out_rows for v in vs if v]
    if len(set(vals)) == 1:
        return "全部同じ値"
    return {"label_head": (header[0] or "").strip(), "series": [c["head"] for c in use], "unit": unit,
            "rows": out_rows, "skipped": skipped, "totals": totals}


def bars_of(spec):
    return sum(1 for _, vals in spec["rows"] for v in vals if v)


# ============================================================
# 文字の幅（折り返しと、値のはみ出し防止に使う。少し広めに見積もる）
# ============================================================
def _cw(ch):
    o = ord(ch)
    if 0xFF61 <= o <= 0xFF9F:
        return 0.5
    if o >= 0x2E80 or unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.0
    if ch.isdigit():
        return 0.62
    if ch.isupper():
        return 0.72
    if ch.islower():
        return 0.58
    return {" ": 0.33, ".": 0.32, ",": 0.32, ":": 0.32, ";": 0.32, "'": 0.3, "%": 0.92, "(": 0.4, ")": 0.4,
            "[": 0.4, "]": 0.4, "-": 0.42, "/": 0.45, "+": 0.62, "~": 0.62}.get(ch, 0.66)


def text_width(s, size=FS, bold=False):
    return sum(_cw(c) for c in s) * size * (1.06 if bold else 1.0)


NO_START = set("、。，．・：；）」』】〕〉》！？ー…‥ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ%")
NO_END = set("（「『【〔〈《")
GOOD_AFTER = set("、。・）」』】〕〉》／/")


def _script(ch):
    o = ord(ch)
    if 0x3040 <= o <= 0x309F:
        return "hira"
    if 0x30A0 <= o <= 0x30FF:
        return "kata"
    if 0x4E00 <= o <= 0x9FFF or ch in "々〆ヶ":
        return "kanji"
    return "other"


def _break_cost(a, b):
    """a と b の間で行を分ける損（None は分けない）。句読点・中黒・括弧の切れ目 → ひらがなの後 → 字の種類の変わり目 → 語の途中"""
    if b[0] in NO_START or a[-1] in NO_END:
        return None
    if a[-1] in GOOD_AFTER or b[0] in NO_END or a.isspace() or b.isspace():
        return 0
    sa, sb = _script(a[-1]), _script(b[0])
    if sa == "hira" and sb != "hira":
        return 1
    if sa != sb:
        return 2
    return 4


def wrap(label, width, size=FS, max_lines=3):
    """ラベルを width に収まる行に分ける。いちばん少ない行数で、切れ目のよい所（句読点・中黒・括弧・助詞の後）を選び、
    行の長さをそろえる（「ロケーション（地域）ペー／ジ」のような1文字だけの行を作らない）。英数字の並びは切らない。
    max_lines に収まらなければ最後の行を「…」で終える"""
    toks = re.findall(r"[A-Za-z0-9.,%+\-/:]+|\s+|.", label.strip())
    if not toks:
        return [""]
    if text_width("".join(toks), size) <= width:
        return ["".join(toks)]
    # 1語が1行より長いときだけ、その語を文字に分ける
    toks = [c for t in toks for c in (list(t) if text_width(t, size) > width else [t])]
    n = len(toks)
    widths = [text_width(t, size) for t in toks]

    def line_w(i, j):
        return sum(widths[i:j])

    best = None
    for k in range(2, max_lines + 1):
        # 分け目の組 (b1 < b2 …) を全部試す（ラベルは短いので数は少ない）
        def rec(start, left, cuts):
            nonlocal best
            if left == 1:
                if line_w(start, n) > width:
                    return
                segs = list(zip([0] + cuts, cuts + [n]))
                ws = [line_w(a, b) for a, b in segs]
                cost = 4 * sum(_break_cost(toks[c - 1], toks[c]) for c in cuts) + (max(ws) - min(ws)) / size
                if best is None or cost < best[0]:
                    best = (cost, segs)
                return
            for c in range(start + 1, n):
                if line_w(start, c) > width:
                    break
                if _break_cost(toks[c - 1], toks[c]) is None:
                    continue
                rec(c, left - 1, cuts + [c])
        rec(0, k, [])
        if best:
            return ["".join(toks[a:b]).strip() for a, b in best[1]]
    # 切れ目が見つからない・行数に収まらない: 前から詰める。収まらない分は最後の行を「…」で終える
    lines, cur = [], ""
    for t in toks:
        if cur and text_width(cur + t, size) > width:
            lines.append(cur.strip())
            cur = t.lstrip()
        else:
            cur += t
    lines.append(cur.strip())
    if len(lines) <= max_lines:
        return lines
    last = "".join(lines[max_lines - 1:])
    while last and text_width(last + "…", size) > width:
        last = last[:-1]
    return lines[:max_lines - 1] + [last + "…"]


# ============================================================
# 色（サイトの図の色）
# ============================================================
def _lum(hexc):
    """WCAG の相対輝度"""
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _tint(hexc, t=0.5):
    """主色を白に t だけ混ぜた淡い色（同じ色みの濃淡。新しい色を足さない）"""
    return "#" + "".join("%02X" % round(int(hexc[i:i + 2], 16) * (1 - t) + 255 * t) for i in (1, 3, 5))


def colors_for(cfg=None):
    """1本目の棒 = 図の主色（accent）。2本目は、主色と本文の文字色（ink）の明るさが十分に違えば本文の文字色
    （currentColor。地が暗くても明るくても見える）、近ければ主色を白に半分混ぜた淡い色。
    コーポレート（主色 #1C3F7C）・補助金（#2A4A8A）は主色も文字も濃紺で、文字色では見分けがつかない
    （dataviz の検算で ΔE 13.5・15.3。15 未満は色覚が典型でも見分けにくい）。淡い色なら ΔE 30 前後になる"""
    import make_diagram
    pal = make_diagram.palette_for(cfg)
    hexs = {k: "#%02X%02X%02X" % tuple(v) for k, v in pal.items()}
    accent = hexs["accent"]
    s2 = "currentColor" if contrast(accent, hexs["ink"]) >= S2_INK_MIN else _tint(accent)
    return {"s1": accent, "s2": s2, "ink": hexs["ink"]}


# ============================================================
# SVG を作る
# ============================================================
_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        # Markdown の後処理（お客様の社 の ** と == の読み替え・表の | ）に記号として拾われないように
        "*": "&#42;", "_": "&#95;", "=": "&#61;", "|": "&#124;", "`": "&#96;", "[": "&#91;", "]": "&#93;", "~": "&#126;"}


def esc(s):
    """SVG の文字と属性に入れる文字。改行は空白にする（図は1行の HTML の塊として置くため）"""
    return "".join(_ESC.get(c, c) for c in re.sub(r"\s+", " ", str(s)))


def _f(x):
    """座標の数字（小数2桁まで・末尾の0は落とす）"""
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def _bar_path(x0, y, length, h):
    """棒の形: 端（値の側）だけ角を丸め、根元は四角（ひとつの基線から伸びて見えるように）"""
    if length <= 0:
        return f"M{_f(x0)},{_f(y)}H{_f(x0)}V{_f(y + h)}H{_f(x0)}Z"
    r = min(RADIUS, h / 2, length)
    x1 = x0 + length
    return (f"M{_f(x0)},{_f(y)}H{_f(x1 - r)}A{_f(r)},{_f(r)} 0 0 1 {_f(x1)},{_f(y + r)}"
            f"V{_f(y + h - r)}A{_f(r)},{_f(r)} 0 0 1 {_f(x1 - r)},{_f(y + h)}H{_f(x0)}Z")


def caption(spec):
    names = "』と『".join(spec["series"])
    notes = []
    if spec["skipped"]:
        notes.append("数字で書かれていない行は除く")
    if spec["totals"]:
        notes.append("「" + "」「".join(spec["totals"]) + "」の行は除く")
    return f"上の表の『{names}』をグラフにしたもの" + (f"（{'。'.join(notes)}）" if notes else "")


def summary(spec):
    """aria-label（読み上げの要約）。最大と最小を表の文字のまま"""
    parts = []
    for k, name in enumerate(spec["series"]):
        pts = [(lab, vals[k]) for lab, vals in spec["rows"] if vals[k]]
        hi = max(pts, key=lambda p: p[1][0])
        lo = min(pts, key=lambda p: p[1][0])
        parts.append(f"『{name}』は{hi[0]}が最も大きく{hi[1][1]}、{lo[0]}が最も小さく{lo[1][1]}")
    return f"上の表の横棒グラフ（{len(spec['rows'])}項目）。" + "。".join(parts) + "。"


def svg(spec, colors):
    """描く内容 → SVG の文字列（1行）。

    ラベルが棒の左に2行までで収まるなら左（右寄せ）に、収まらなければ棒の上に置く（長い文のラベルで棒が細くならないように）。
    最大の値の棒が、値の文字を置いた残りの幅いっぱいになる。目盛りは最大値の 1/4 ごとの薄い縦線と、濃いめの基線"""
    two = len(spec["series"]) == 2
    fills = [colors["s1"], colors["s2"]]
    fs_val = FS_VAL2 if two else FS
    inner = W - 2 * PAD
    vw = max(text_width(v[1], fs_val, bold=True) for _, vals in spec["rows"] for v in vals if v) + GAP_BV
    side_max = min(inner * 0.4, inner - GAP_LB - vw - inner * 0.42)
    labels = [wrap(lab, side_max, FS, max_lines=2) for lab, _ in spec["rows"]]
    side = not any(ln[-1].endswith("…") for ln in labels)
    if side:
        lw = max(2 * FS, max(text_width(t, FS) for ln in labels for t in ln))
        x0 = PAD + lw + GAP_LB
    else:
        lw = inner
        labels = [wrap(lab, lw, FS, max_lines=2) for lab, _ in spec["rows"]]
        x0 = PAD
    pw = W - PAD - x0 - vw
    maxv = max(v[0] for _, vals in spec["rows"] for v in vals if v)
    block = (2 * BAR2 + INNER) if two else BAR1
    out, rows_svg = [], []
    y = PAD
    if two:
        names = [wrap(name, inner * 0.42, FS_LEG, max_lines=1)[0] for name in spec["series"]]
        need = sum(15 + text_width(nm, FS_LEG) for nm in names) + 18
        lx = x0 if x0 + need <= W - PAD else PAD      # 凡例は棒の書き出しにそろえる（入らなければ左端）
        for k, nm in enumerate(names):
            rows_svg.append(f'<rect x="{_f(lx)}" y="{_f(y + 3)}" width="10" height="10" rx="2" fill="{fills[k]}"/>'
                            f'<text x="{_f(lx + 15)}" y="{_f(y + 12.5)}" font-size="{FS_LEG}" fill="currentColor">{esc(nm)}</text>')
            lx += 15 + text_width(nm, FS_LEG) + 18
        y += LEG_H
    top = y
    grid = []
    for (lab, vals), lines in zip(spec["rows"], labels):
        if side:
            ch = max(len(lines) * LH, block)
            by = y + (ch - block) / 2
            ty = y + (ch - len(lines) * LH) / 2
            anchor, tx = "end", PAD + lw
        else:
            ch = len(lines) * LH + 4 + block
            by = y + len(lines) * LH + 4
            ty = y
            anchor, tx = "start", PAD
        # 行の箱（LH）の中で、上下の余白を等しくした位置に字の基線を置く（和文の字面は 0.88em が基線より上）
        tsp = "".join(f'<tspan x="{_f(tx)}" y="{_f(ty + LH * i + (LH - FS) / 2 + FS * 0.88)}">{esc(t)}</tspan>'
                      for i, t in enumerate(lines))
        g = [f'<g class="tc-row"><text class="tc-lab" font-size="{FS}" fill="currentColor" text-anchor="{anchor}">{tsp}</text>']
        for k, v in enumerate(vals):
            if not v:
                continue
            bh = BAR2 if two else BAR1
            yy = by + k * (BAR2 + INNER) if two else by
            length = float(v[0] / maxv) * pw
            g.append(f'<path class="tc-bar tc-s{k + 1}" d="{_bar_path(x0, yy, length, bh)}" fill="{fills[k]}"/>'
                     f'<text class="tc-val tc-s{k + 1}" x="{_f(x0 + length + GAP_BV)}" y="{_f(yy + bh / 2 + fs_val * 0.36)}" '
                     f'font-size="{fs_val}" font-weight="700" fill="currentColor">{esc(v[1])}</text>')
        g.append("</g>")
        rows_svg.append("".join(g))
        if not side:
            grid.append((by - 3, by + block + 3))
        y += ch + ROW_GAP
    bottom = y - ROW_GAP
    if side:
        grid = [(top - 4, bottom + 4)]
    for a, b in grid:
        for f in (0.25, 0.5, 0.75, 1.0):
            out.append(f'<line x1="{_f(x0 + pw * f)}" y1="{_f(a)}" x2="{_f(x0 + pw * f)}" y2="{_f(b)}" '
                       f'stroke="currentColor" stroke-opacity="0.12" stroke-width="1"/>')
        out.append(f'<line x1="{_f(x0)}" y1="{_f(a)}" x2="{_f(x0)}" y2="{_f(b)}" '
                   f'stroke="currentColor" stroke-opacity="0.4" stroke-width="1"/>')
    h = bottom + PAD
    # 字体は本文から受け継ぐ（表と同じ字で描く。お客様の社 の欧文は BIZ UDP ゴシック、AI集客ラボは游ゴシック Medium など）。
    # 字間・太さ・斜体は受け継がない（本文の字間 0.04em などが乗ると、見積もった幅より広がって値が枠からはみ出す）
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {_f(h)}" width="100%" role="img" '
            f'aria-label="{esc(summary(spec))}" letter-spacing="0" word-spacing="0" font-weight="400" font-style="normal" '
            f'style="display:block;width:100%;max-width:{MAX_PX}px;height:auto;margin:0 auto">'
            f"<title>{esc(caption(spec))}</title>" + "".join(out) + "".join(rows_svg) + "</svg>")


# ============================================================
# 読み戻して検算する
# ============================================================
def _path_extent(d):
    """棒の path → (根元の x, 端の x)。M・H・V・A・Z だけを読む（このモジュールが書く形）"""
    toks = re.findall(r"[MHVAZ]|-?\d+(?:\.\d+)?", d)
    i, x, xs, x0 = 0, 0.0, [], None
    while i < len(toks):
        c = toks[i]
        if c == "M":
            x = float(toks[i + 1])
            x0 = x
            i += 3
        elif c == "H":
            x = float(toks[i + 1])
            i += 2
        elif c == "V":
            i += 2
        elif c == "A":
            x = float(toks[i + 6])
            i += 8
        else:
            i += 1
        xs.append(x)
    return x0, max(xs)


def read_back(svg_text):
    """SVG → [(ラベル, [(系列, 値の文字, 棒の根元, 棒の端)…])…]。XML として読めなければ例外"""
    root = ET.fromstring(svg_text)
    out = []
    for g in root.iter(f"{NS}g"):
        if g.get("class") != "tc-row":
            continue
        lab = "".join("".join(t.itertext()) for t in g.iter(f"{NS}text") if t.get("class") == "tc-lab")
        bars = {}
        for p in g.iter(f"{NS}path"):
            k = p.get("class", "").split("tc-s")[-1]
            bars[k] = _path_extent(p.get("d", ""))
        items = []
        for t in g.iter(f"{NS}text"):
            cls = t.get("class", "")
            if cls.startswith("tc-val"):
                k = cls.split("tc-s")[-1]
                x0, x1 = bars.get(k, (None, None))
                items.append((int(k), "".join(t.itertext()), x0, x1))
        out.append((lab, items))
    return out


def verify(spec, svg_text):
    """描いたものが表と同じか。ラベル・値の文字・値の数・棒の長さ（最大の棒に対する割合）を、SVG から読み戻して比べる"""
    try:
        got = read_back(svg_text)
    except ET.ParseError:
        return False
    if len(got) != len(spec["rows"]):
        return False
    lengths, vals = [], []
    for (lab, want), (glab, items) in zip(spec["rows"], got):
        # 折り返しの位置の空白は行の端で落とすので、空白を除いて比べる。長すぎて「…」で終えたラベルは頭だけ比べる
        exp, glab = re.sub(r"\s", "", lab), re.sub(r"\s", "", glab)
        if not (glab == exp or (glab.endswith("…") and exp.startswith(glab[:-1]))):
            return False
        want_items = [(k + 1, v) for k, v in enumerate(want) if v]
        if [k for k, _ in want_items] != [k for k, *_ in items]:
            return False
        for (k, v), (_, text, x0, x1) in zip(want_items, items):
            n = number(text)
            if text != v[1] or not n or n[0] != v[0] or x0 is None:
                return False
            lengths.append(x1 - x0)
            vals.append(n[0])
    top = max(vals)
    longest = max(lengths)
    if top <= 0 or longest <= 0:
        return False
    return all(abs(length - float(v / top) * longest) <= 0.02 for length, v in zip(lengths, vals))


def figure(spec, colors):
    """検算を通った図（1行の HTML）。通らなければ空"""
    s = svg(spec, colors)
    if not verify(spec, s):
        return ""
    return (f'<figure class="table-chart" style="margin:1.5em 0">{s}'
            f'<figcaption style="margin-top:.5em;font-size:.85em;line-height:1.6;text-align:center">'
            f"{esc(caption(spec))}</figcaption></figure>")


# ============================================================
# 記事に挿す
# ============================================================
TABLE_HTML = re.compile(r"<table\b(?:(?!</table>).)*</table>", re.S | re.I)
ROW_MD = re.compile(r"\s*\|.*\|\s*$")
SEP_MD = re.compile(r"\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-*:?\s*\|?\s*$")


def pick(specs):
    """描ける表から2つまで選ぶ。描く棒の多い表を先に（同じなら記事の前にある表）。返すのは記事の順の番号"""
    ok = [(i, s) for i, s in enumerate(specs) if isinstance(s, dict)]
    ok.sort(key=lambda p: (-bars_of(p[1]), p[0]))
    return sorted(i for i, _ in ok[:MAX_CHARTS])


def html_tables(html):
    """本文 HTML の表 → [(図を挿す位置, 描く内容 or 理由)]。横スクロールの枠（table-wrap）に入った表は枠の後ろ"""
    out = []
    for m in TABLE_HTML.finditer(html):
        end = m.end()
        wrapped = re.match(r"\s*</div>", html[end:])
        if wrapped and re.search(r'<div class="table-wrap">\s*$', html[:m.start()]):
            end += wrapped.end()
        head, rows = html_table_cells(m.group(0))
        out.append((end, analyze(head, rows)))
    return out


def md_tables(md):
    """原稿 Markdown の表 → [(表の最後の行の番号, 描く内容 or 理由)]。

    どの表を描くかは、本文全体を md2html で HTML にしてから読む（add_to_html と同じ文字・同じ選び方になる）。
    Markdown の表の塊（| で始まる行の並び。コードの中は見ない）と HTML の表が同じ数でなければ、
    どれがどれか決まらないので空を返す（段落の続きになって表にならない塊・生の HTML の表があるとき）"""
    import md2html
    lines = md.split("\n")
    blocks, fence, i = [], False, 0
    while i < len(lines):
        if lines[i].lstrip().startswith("```"):
            fence = not fence
        elif not fence and ROW_MD.match(lines[i]):
            j = i
            while j < len(lines) and ROW_MD.match(lines[j]):
                j += 1
            if j - i >= 2 and SEP_MD.match(lines[i + 1]):     # 区切りの行（|:--|）が無い塊は、どちらの変換でも表にならない
                blocks.append(j - 1)
            i = j
            continue
        i += 1
    found = html_tables(md2html.convert(md)[0])
    if len(found) != len(blocks):
        return []
    return [(last, spec) for last, (_, spec) in zip(blocks, found)]


def add_to_html(html, cfg=None):
    """本文 HTML の表のうち選んだもの（2つまで）の直後にグラフを挿す。既に挿してあれば何もしない"""
    if 'class="table-chart"' in html:
        return html
    found = html_tables(html)
    use = pick([s for _, s in found])
    if not use:
        return html
    colors = colors_for(cfg)
    for i in sorted(use, reverse=True):
        end, spec = found[i]
        fig = figure(spec, colors)
        if fig:
            html = html[:end] + fig + html[end:]
    return html


def add_to_markdown(md, cfg=None):
    """原稿 Markdown の表のうち選んだもの（2つまで）の直後に、前後を空行で挟んだ1行の HTML としてグラフを挿す
    （CommonMark・Python-Markdown とも、空行で終わる HTML の塊は中身を Markdown として読まずに素通しする）"""
    if 'class="table-chart"' in md:
        return md
    found = md_tables(md)
    use = pick([s for _, s in found])
    if not use:
        return md
    colors = colors_for(cfg)
    lines = md.split("\n")
    for i in sorted(use, reverse=True):
        last, spec = found[i]
        fig = figure(spec, colors)
        if fig:
            after = [] if last + 1 < len(lines) and not lines[last + 1].strip() else [""]
            lines[last + 1:last + 1] = ["", fig] + after
    return "\n".join(lines)


def count(html):
    return html.count('class="table-chart"')


# ============================================================
# 手元で確かめる
# ============================================================
def _articles():
    import yaml
    import sites as sites_mod
    owner = {}
    for sid, cfg in sites_mod.load_all().items():
        for c in cfg.get("categories", {}):
            owner.setdefault(c, sid)
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", t, re.S)
        if not m:
            continue
        meta = yaml.safe_load(m.group(1)) or {}
        yield owner.get(meta.get("category")), p.stem, t[m.end():]


def survey(body):
    """1記事の表の見立て: [(数字を含む表か, 描くか, 描く内容 or 理由)]（本文 HTML の順）"""
    import md2html
    html = md2html.convert(body)[0]
    found = html_tables(html)
    specs = [s for _, s in found]
    use = set(pick(specs))
    out = []
    for i, m in enumerate(TABLE_HTML.finditer(html)):
        _, rows = html_table_cells(m.group(0))
        digits = any(re.search(r"\d", unicodedata.normalize("NFKC", c)) for r in rows for c in r)
        s = specs[i]
        if isinstance(s, dict) and i not in use:
            s = "1記事2つまでの枠の外（棒の多い表を先に選ぶ）"
        out.append((digits, i in use, s))
    return out


def stats():
    import collections
    per = collections.defaultdict(lambda: collections.Counter())
    why = collections.defaultdict(collections.Counter)
    for sid, slug, body in _articles():
        sid = sid or "?"
        got = survey(body)
        s = per[sid]
        s["記事"] += 1
        s["数字の入った表がある記事"] += any(d for d, _, _ in got)
        s["グラフが付く記事"] += any(u for _, u, _ in got)
        s["グラフ"] += sum(1 for _, u, _ in got if u)
        s["数字の入った表"] += sum(1 for d, _, _ in got if d)
        if any(u for _, u, _ in got) and not md_tables(body):
            s["原稿と表の数が合わず Markdown では挿せない記事"] += 1
        for d, u, x in got:
            if d and not u:
                why[sid][x if isinstance(x, str) else "?"] += 1
    for sid, s in per.items():
        print(f"{sid}: " + "・".join(f"{k} {v}" for k, v in s.items()))
        for r, n in why[sid].most_common(10):
            print(f"    描かない数字の表 {n:4d}  {r}")


def main(argv):
    if not argv or argv[0] == "--stats":
        stats()
        return 0
    for slug in argv:
        p = ROOT / "articles" / f"{slug}.md"
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", p.read_text(encoding="utf-8-sig"), count=1, flags=re.S)
        for i, (digits, used, s) in enumerate(survey(body)):
            mark = "描く" if used else "－"
            print(f"{slug} 表{i + 1} {mark}: "
                  + (f"{'・'.join(s['series'])}（{len(s['rows'])}行・{s['unit']}）" if isinstance(s, dict) else s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
