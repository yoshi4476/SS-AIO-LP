# -*- coding: utf-8 -*-
"""動画のスライドの型。提案書（A4横）と同じ意匠を、1920×1080 に起こす。

**なぜ型を増やすか**: 箇条書きと棒グラフだけでは、12分の動画で画面が変わらない。
「読み上げているだけ」に見えると、最後まで見られない。
資料で使っている型（大きな数字・比較・表・工程図・実際の画面）をそのまま動画に出す。

**運用デモで使う `term` と `gate` は、絵ではなく実態の写し**です。
毎朝5時に走る検査の出力と、公開前の判定の画面を、そのままの形で見せる。
「AIエージェントが喋る」のではなく「システムがこう動いている」を見せるための型。

呼ぶのは video_make.slide() だけ。ここでは中身を描くことだけを持つ。
"""
from PIL import ImageDraw  # noqa: F401  （型の説明のため）

# 追加の色。本体（video_make）の NAVY / ACCENT などと組で使う
PANEL = (17, 28, 49)        # ターミナルの地
PANEL_BAR = (28, 42, 68)    # ターミナルの見出し帯
OK = (58, 150, 100)         # 通った
NG = (201, 74, 66)          # 落ちた
DIM = (126, 142, 165)       # 補助の文字
CREAM = (251, 247, 238)     # 注記の地
GHOST = (233, 237, 243)     # 背景に薄く置く数字


def _v():
    import video_make as V
    return V


def title(im, d, s, top, bot):
    """章の扉。**紺一色にして、話が切り替わったことを体で分からせる。**

    12分の動画は、同じ地色が続くと「まだ同じ話か」と感じられる。
    扉を挟むと、そこまでの話が1つの塊として記憶に残る。
    """
    V = _v()
    W, H = V.W, V.H
    d.rectangle([0, 0, W, H], fill=V.NAVY)
    # 右上の弧。資料の表紙と同じ意匠
    d.arc([W - 620, -340, W + 340, 620], 90, 220, fill=(78, 96, 130), width=3)
    num = s.get("part", "")
    if num:
        d.text((150, 300), "P A R T", font=V.font(34), fill=V.ACCENT, anchor="lt")
        d.text((140, 350), num, font=V.font(230), fill=(58, 76, 112), anchor="lt")
    d.text((150, 640), s.get("eyebrow", ""), font=V.font(34), fill=V.ACCENT, anchor="lt")
    t = s.get("big", "")
    d.text((146, 700), t, font=V.fit(d, t, W - 300, 92, 48),
           fill=(255, 255, 255), anchor="lt")
    y = 850
    for ln in s.get("notes", [])[:3]:
        d.ellipse([150, y + 12, 166, y + 28], fill=V.ACCENT)
        d.text((186, y + 20), ln, font=V.font(34), fill=(186, 200, 222), anchor="lm")
        y += 56


def cards(im, d, s, top, bot):
    """大きな数字の札。**数字は読み上げただけでは残らない。**

    資料の「13.7% / 64.7% / 約30%」と同じ見せ方。
    いま話している札だけを濃くして、音と絵を結び付ける。
    """
    V = _v()
    W = V.W
    items = s.get("cards", [])[:3]
    if not items:
        return
    on = s.get("on", -1)
    gap, side = 46, 90
    cw = (W - side * 2 - gap * (len(items) - 1)) // len(items)
    ch = bot - top - 20          # 空けずに使い切る。下半分が白いと作りかけに見える
    nf = V.font(29)
    for i, (big, label, note) in enumerate(items):
        x = side + i * (cw + gap)
        live = (i == on)
        d.rounded_rectangle([x, top, x + cw, top + ch], 14,
                            fill=(255, 255, 255) if live else (247, 249, 252),
                            outline=V.LINE, width=2)
        d.rectangle([x, top, x + cw, top + 8], fill=V.ACCENT if live else (214, 221, 232))
        bf = V.fit(d, big, cw - 80, 148, 64)
        nl = V.wrap(d, note, nf, cw - 88)[:5]
        # 数字・見出し・説明をひと塊として、札の中央に置く
        block = bf.size + 64 + 44 + 26 + len(nl) * 44
        y = top + max(56, (ch - block) / 2)
        d.text((x + 44, y), big, font=bf,
               fill=V.NAVY if live else (150, 163, 182), anchor="lt")
        y += bf.size + 42
        d.text((x + 44, y), label, font=V.fit(d, label, cw - 80, 38, 24),
               fill=V.NAVY if live else DIM, anchor="lt")
        y += 66
        for ln in nl:
            d.text((x + 44, y), ln, font=nf, fill=DIM, anchor="lt")
            y += 44


def term(im, d, s, top, bot):
    """実際の画面。**毎朝5時に走る検査の出力を、そのまま見せる。**

    「自動で監視しています」と言うより、出力を1行ずつ見せたほうが早い。
    行の色だけで、通ったか塞がれたかが分かる。
    """
    V = _v()
    W = V.W
    x0, x1 = 110, W - 110
    y0 = top
    y1 = min(bot - 10, y0 + 640)
    d.rounded_rectangle([x0, y0, x1, y1], 14, fill=PANEL)
    d.rounded_rectangle([x0, y0, x1, y0 + 62], 14, fill=PANEL_BAR)
    d.rectangle([x0, y0 + 40, x1, y0 + 62], fill=PANEL_BAR)
    for i, c in enumerate([(224, 108, 96), (228, 190, 96), (110, 190, 120)]):
        d.ellipse([x0 + 26 + i * 30, y0 + 24, x0 + 40 + i * 30, y0 + 38], fill=c)
    d.text((x0 + 140, y0 + 31), s.get("term_head", ""), font=V.font(26),
           fill=(168, 186, 212), anchor="lm")
    tag = s.get("term_tag", "")
    if tag:
        tf = V.font(23)
        tw = d.textlength(tag, font=tf) + 34
        d.rounded_rectangle([x1 - 22 - tw, y0 + 16, x1 - 22, y0 + 46], 15, fill=V.ACCENT)
        d.text((x1 - 22 - tw / 2, y0 + 31), tag, font=tf, fill=(30, 26, 14), anchor="mm")

    y = y0 + 92
    colors = {"": (206, 218, 234), "ok": (118, 210, 150), "ng": (240, 130, 120),
              "dim": (120, 137, 160), "hi": V.ACCENT_L, "rule": None}
    for text, style in s.get("term", [])[:14]:
        if y > y1 - 40:
            break
        if style == "rule":
            d.rectangle([x0 + 30, y + 14, x1 - 30, y + 15], fill=(44, 60, 88))
            y += 32
            continue
        f = V.font(31 if style in ("ng", "hi") else 28)
        col = colors.get(style, colors[""])
        # 「名前 … 結果」は列をそろえる。等幅の日本語フォントが無いので、
        # 空白で詰めても そろわない（実測でクローラー名ごとに位置がずれた）
        if "…" in text and style in ("ok", "ng"):
            left, right = text.split("…", 1)
            d.text((x0 + 36, y), left.rstrip(), font=f, fill=col, anchor="lt")
            d.text((x0 + 470, y), "…" + right, font=f, fill=col, anchor="lt")
        else:
            d.text((x0 + 36, y), text, font=f, fill=col, anchor="lt")
        y += 42 if style in ("ng", "hi") else 38


def gate(im, d, s, top, bot):
    """公開前の判定の画面。**総合90点でも、1観点が80点を割れば落ちる。**

    「品質を担保します」は誰でも言う。落ちている画面を見せたほうが早い。
    """
    V = _v()
    W = V.W
    mid = 760
    d.rounded_rectangle([90, top, mid - 20, bot - 20], 14,
                        fill=(255, 255, 255), outline=V.LINE, width=2)
    d.text((130, top + 34), s.get("gate_left", "門2｜機械検査"), font=V.font(28),
           fill=DIM, anchor="lt")
    big = s.get("gate_count", "18/18")
    d.text((128, top + 76), big, font=V.font(86), fill=V.NAVY, anchor="lt")
    bw = d.textlength(big, font=V.font(86))
    d.rounded_rectangle([140 + bw, top + 100, 250 + bw, top + 146], 12, fill=(226, 243, 232))
    d.text((195 + bw, top + 123), "PASS", font=V.font(28), fill=OK, anchor="mm")
    y = top + 190
    for ln in s.get("checks", [])[:7]:
        d.text((130, y), "✓", font=V.font(26), fill=OK, anchor="lt")
        d.text((166, y), ln, font=V.font(26), fill=V.NAVY, anchor="lt")
        y += 42

    x0 = mid + 20
    d.rounded_rectangle([x0, top, W - 90, bot - 20], 14,
                        fill=(255, 255, 255), outline=V.LINE, width=2)
    d.text((x0 + 40, top + 34), s.get("gate_right", "門3｜別工程の採点（3観点×100点）"),
           font=V.font(28), fill=DIM, anchor="lt")
    y = top + 92
    bx0, bx1 = x0 + 230, W - 240
    for label, v, bad in s.get("scores", []):
        d.text((x0 + 40, y + 18), label, font=V.font(30),
               fill=NG if bad else V.NAVY, anchor="lm")
        d.rounded_rectangle([bx0, y + 4, bx1, y + 32], 14, fill=(236, 240, 246))
        d.rounded_rectangle([bx0, y + 4, bx0 + (bx1 - bx0) * v / 100, y + 32], 14,
                            fill=NG if bad else V.ACCENT)
        d.text((W - 120, y + 18), str(v), font=V.font(34),
               fill=NG if bad else V.NAVY, anchor="rm")
        y += 58
    # 合格ラインの縦線。基準が見えないと「落ちた」が伝わらない
    lx = bx0 + (bx1 - bx0) * 0.8
    d.rectangle([lx, top + 88, lx + 3, y - 20], fill=V.NAVY)
    d.text((lx + 12, y - 8), "合格ライン 80", font=V.font(22), fill=DIM, anchor="lt")

    vy = y + 26
    ok = s.get("verdict_ok", False)
    note = s.get("verdict_note", "")
    nf = V.font(25)
    nl = V.wrap(d, note, nf, W - 120 - x0 - 86) if note else []
    vh = 92 + len(nl) * 38          # 中身のぶんだけ。余らせると右下が間延びする
    d.rounded_rectangle([x0 + 30, vy, W - 120, min(bot - 30, vy + vh)], 12,
                        fill=(232, 245, 237) if ok else (253, 236, 234))
    d.text((x0 + 56, vy + 24), s.get("verdict", ""), font=V.font(34),
           fill=OK if ok else NG, anchor="lt")
    yy = vy + 78
    for ln in nl:
        d.text((x0 + 56, yy), ln, font=nf, fill=DIM, anchor="lt")
        yy += 38


def table(im, d, s, top, bot):
    """表。**行が2つ以上あるものは、箇条書きより表のほうが速い。**"""
    V = _v()
    W = V.W
    head, rows = s.get("table", ([], []))
    if not head:
        return
    x0, x1 = 100, W - 100
    ws = s.get("widths") or [1 / len(head)] * len(head)
    rh = min(84, max(56, (bot - top - 70) // max(1, len(rows))))
    d.rectangle([x0, top, x1, top + 62], fill=V.NAVY)
    x = x0
    for c, w in zip(head, ws):
        d.text((x + 26, top + 31), c, font=V.font(28), fill=(255, 255, 255), anchor="lm")
        x += (x1 - x0) * w
    y = top + 62
    on = s.get("on", -1)
    for i, r in enumerate(rows):
        live = (i == on)
        d.rectangle([x0, y, x1, y + rh],
                    fill=V.ACCENT_L if live else ((250, 251, 253) if i % 2 else (255, 255, 255)))
        x = x0
        for j, (c, w) in enumerate(zip(r, ws)):
            cw = (x1 - x0) * w
            f = V.fit(d, c, cw - 46, 30 if j == 0 else 27, 19)
            lines = V.wrap(d, c, f, cw - 46)[:2]
            yy = y + rh / 2 - (len(lines) - 1) * 18
            for ln in lines:
                d.text((x + 26, yy), ln, font=f,
                       fill=V.NAVY if (j == 0 or live) else (92, 106, 126), anchor="lm")
                yy += 36
            x += cw
        d.rectangle([x0, y + rh - 1, x1, y + rh], fill=V.LINE)
        y += rh


def compare(im, d, s, top, bot):
    """左右の比べ。**「対策していない場合」と「導入後」を並べる。**

    資料の6ページと同じ型。文章で説明するより、並べたほうが1秒で伝わる。
    """
    V = _v()
    W = V.W
    lt, ll, rt, rl = s.get("compare", ("", [], "", []))
    gap = 40
    cw = (W - 180 - gap) // 2
    for i, (ti, lines, good) in enumerate([(lt, ll, False), (rt, rl, True)]):
        x = 90 + i * (cw + gap)
        d.rounded_rectangle([x, top, x + cw, bot - 20], 14,
                            fill=(255, 255, 255) if good else (250, 251, 253),
                            outline=V.ACCENT if good else V.LINE, width=3 if good else 2)
        d.rectangle([x, top, x + cw, top + 58], fill=V.NAVY if good else (222, 228, 238))
        d.text((x + 28, top + 29), ti, font=V.fit(d, ti, cw - 56, 30, 22),
               fill=(255, 255, 255) if good else (92, 106, 126), anchor="lm")
        y = top + 92
        for ln in lines[:6]:
            f = V.fit(d, ln, cw - 96, 30, 21)
            parts = V.wrap(d, ln, f, cw - 96)[:2]
            d.ellipse([x + 32, y + 10, x + 46, y + 24], fill=V.ACCENT if good else (186, 196, 212))
            for k, part in enumerate(parts):
                d.text((x + 62, y + 17 + k * 38), part, font=f,
                       fill=V.NAVY if good else (110, 124, 145), anchor="lm")
            y += 44 + 38 * (len(parts) - 1)


def flow(im, d, s, top, bot):
    """工程図。**いまどこの話かを1段だけ濃くする。**"""
    V = _v()
    W = V.W
    steps = s.get("flow", [])[:6]
    if not steps:
        return
    on = s.get("on", -1)
    n = len(steps)
    aw = 52
    bw = (W - 180 - aw * (n - 1)) // n
    # 箱の高さは中身に合わせる。固定にすると下半分が白く空いて間延びする
    bf = V.font(24)
    rows = max(len(V.wrap(d, b, bf, bw - 52)) for _, b in steps)
    bh = min(bot - top - 30, 104 + rows * 36 + 20)
    top = top + max(0, (bot - top - 30 - bh) // 2)   # 縦の中央へ
    for i, (t, b) in enumerate(steps):
        x = 90 + i * (bw + aw)
        live = (i == on)
        d.rounded_rectangle([x, top, x + bw, top + bh], 12,
                            fill=V.NAVY if live else (255, 255, 255),
                            outline=V.NAVY if live else V.LINE, width=2)
        d.ellipse([x + 24, top + 24, x + 62, top + 62],
                  fill=V.ACCENT if live else (238, 242, 248))
        d.text((x + 43, top + 43), str(i + 1), font=V.font(24),
               fill=(255, 255, 255) if live else DIM, anchor="mm")
        tf = V.fit(d, t, bw - 100, 30, 20)
        d.text((x + 76, top + 43), t, font=tf,
               fill=(255, 255, 255) if live else V.NAVY, anchor="lm")
        y = top + 92
        for ln in V.wrap(d, b, bf, bw - 52)[:5]:
            d.text((x + 26, y), ln, font=bf,
                   fill=(190, 204, 224) if live else DIM, anchor="lt")
            y += 36
        if i < n - 1:
            d.text((x + bw + aw / 2, top + bh / 2), "→", font=V.font(38),
                   fill=(186, 196, 212), anchor="mm")


def note(im, d, s, top, bot):
    """1枚に1文だけ。**大事なところで、あえて何も足さない。**

    情報を詰め続けると、どこが山場か分からなくなる。
    """
    V = _v()
    W = V.W
    t = s.get("big", "")
    # 台本が明示した改行を先に割る。**測る前に割らないと Pillow が落ちる**
    # （ImageDraw.textlength は複数行を測れない）
    # 台本が明示した改行を先に割る。測る前に割らないと Pillow が落ちる
    # （ImageDraw.textlength は複数行を測れない）
    parts = [x for x in t.split(chr(10)) if x.strip()] or [t]
    f = V.fit(d, max(parts, key=len), W - 300, 76, 40)
    lines = [ln for x in parts for ln in V.wrap(d, x, f, W - 300)]
    y = (top + bot) / 2 - len(lines) * (f.size + 24) / 2
    for ln in lines:
        d.text((W / 2, y), ln, font=f, fill=V.NAVY, anchor="mt")
        y += f.size + 24
    sub = s.get("sub", "")
    if sub:
        d.rectangle([W / 2 - 70, y + 20, W / 2 + 70, y + 26], fill=V.ACCENT)
        d.text((W / 2, y + 60), sub, font=V.font(32), fill=DIM, anchor="mt")


DRAW = {"title": title, "cards": cards, "term": term, "gate": gate,
        "table": table, "compare": compare, "flow": flow, "note": note}
