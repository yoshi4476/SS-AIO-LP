# -*- coding: utf-8 -*-
"""記事を、キャラクター2人（ナナ＝解説・聞き手＝その業種の経営者）の掛け合い動画にする。

**なぜこの形か**: 記事の文をそのまま読むスライド動画は、声も構成も機械的に聞こえる。
話し言葉の掛け合いにし、ボードは字幕の繰り返しではなく要点・数字・比較を出し分ける。
（基準は 2026-09 のサンプル v3。これ以降の記事動画はこの形で作る）

**事実は記事の本文だけ**: 台本は claude に書かせるが、通してよいかは機械が決める。
記事に無い数字が1つでもあれば捨てて書き直させる（最大3回）。通らなければ作らない
（呼び出し側がスライド形式に落とす）。読み違いは video_make.say → yomi_guard が聞き直して直す。

    python scripts/duo_video.py --script <slug>          # 台本だけ作る（data/duo_scripts/<slug>.json）
    python scripts/duo_video.py --make <slug> [--out x.mp4]
    python scripts/duo_video.py --selftest
"""
import argparse
import json
import math
import random
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SCRIPTS = ROOT / "data" / "duo_scripts"
CHARS = ROOT / "assets" / "characters"
W, H, FPS = 1920, 1080, 24
NAVY, INK, GOLD, OLIVE = (27, 42, 74), (20, 26, 38), (201, 160, 72), (86, 102, 64)
RED, GREEN, MUTED = (196, 64, 60), (46, 125, 90), (100, 110, 130)
VOICE = {"N": ("ja-JP-NanamiNeural", "+5%", "-1Hz"), "K": ("ja-JP-KeitaNeural", "+7%", "+0Hz")}
COLOR = {"N": NAVY, "K": OLIVE}
BOARD_TYPES = {"cover", "chapter", "points", "number", "compare", "quote", "vs", "step", "end"}

PROMPT = """あなたはYouTubeの解説動画の構成作家です。下の記事だけを材料に、2人の掛け合いの台本をJSONで書いてください。

登場人物:
- N（ナナ）: AI集客ラボの解説役。丁寧語で、要点を短く言い切る。
- K（聞き手）: この記事の読者と同じ立場の経営者。自分の会社の事情として素朴に聞き、驚き、納得する。

守ること:
1. 事実・数字・固有名詞は記事に書いてあるものだけ。記事に無い数字は1つも使わない（例え話の数字も不可）。
2. 記事の文をそのまま読まない。人が話す言葉に言い換える。見出しを読み上げない。
3. 1セリフは70字以内。Nは1セリフ2文まで。Kの相づちは毎回違う言い方にする。
4. 構成: 導入(4〜6セリフ) → 記事の主な見出しごとに章(5〜8章。各章は Kの問い → Nの説明2〜4 → Kの反応) → 今日できる一歩 → 締め。合計36〜56セリフ。
5. 当社の見立て・意見は「私たちの見立てでは」のように意見と分かる言い方にする。
6. 最後のNのセリフは「詳しくは記事にまとめています。概要欄からどうぞ。」

ボード（画面中央の板）: 各セリフに "board" を付けられる。付けたセリフから表示が切り替わる（付けなければ前のまま）。
- {{"type":"cover","kicker":"業種など短く","title":"動画の題（20字以内）"}}  … 最初のセリフに必ず付ける
- {{"type":"chapter","no":1,"head":"章の題（24字以内）"}}               … 各章の最初のセリフに付ける
- {{"type":"points","head":"見出し","items":["18字以内",...最大4],"foot":"任意"}}
- {{"type":"number","head":"見出し","value":"記事にある数字","label":"何の数字か","note":"出典や条件"}}
- {{"type":"compare","head":"見出し","rows":[["ラベル",数値],["ラベル",数値]],"unit":"%","note":"出典"}}
- {{"type":"quote","head":"見出し","text":"大きく見せる一言","sub":"補足"}}
- {{"type":"vs","head":"見出し","ng":["..."],"ok":["..."]}}
- {{"type":"step","head":"今日できる一歩","lines":["1〜3行"]}}  … 締めの前に付ける
- {{"type":"end"}}  … 最後のセリフに付ける
ボードの文字も記事にあることだけ。数字を出すなら number か compare を使う。

出力はJSONだけ（説明文やコードブロックの印を付けない）:
{{"listener_role":"聞き手の肩書き（例: 工務店 経営。8字以内）","lines":[{{"who":"K","text":"...","board":{{...}}}},{{"who":"N","text":"..."}}]}}

--- 記事 ---
{article}
"""


# ---------- 記事 ----------
def article(slug):
    p = ROOT / "articles" / f"{slug}.md"
    t = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    fm, body = m.group(1), m.group(2)

    def g(k):
        x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
        return x.group(1).strip().strip('"') if x else ""
    faq = re.findall(r"-\s*q:\s*(.+)\n\s*a:\s*(.+)", fm)
    b = re.sub(r"<figure>.*?</figure>", "", body, flags=re.S)
    b = re.sub(r"<[^>]+>", "", b)
    b = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", b)
    b = b.replace("**", "").replace("==", "")
    b = re.sub(r"\n{3,}", "\n\n", b)
    text = f"# {g('title')}\n{g('description')}\n\n{b}\n\n## FAQ\n" + "\n".join(f"Q: {q}\nA: {a}" for q, a in faq)
    return {"slug": slug, "title": g("title"), "category": g("category"), "text": text}


def _nums(s):
    return re.findall(r"\d+(?:\.\d+)?", s.replace(",", ""))


def validate(sc, art):
    """通してよい台本か。問題の一覧を返す（空なら合格）"""
    ng = []
    have = set(_nums(art["text"]))
    lines = sc.get("lines") or []
    if not 30 <= len(lines) <= 64:
        ng.append(f"セリフ数が {len(lines)}（36〜56にする）")
    role = sc.get("listener_role", "")
    if not role or len(role) > 10:
        ng.append("listener_role が無いか長すぎる")
    for i, ln in enumerate(lines):
        who, text, bd = ln.get("who"), ln.get("text", ""), ln.get("board")
        if who not in ("N", "K"):
            ng.append(f"{i}: who が N/K でない")
        if not text or len(text) > 90:
            ng.append(f"{i}: セリフが空か長すぎる（{len(text)}字）")
        shown = {k: v for k, v in (bd or {}).items() if k not in ("no", "show")}
        for n in _nums(text + json.dumps(shown, ensure_ascii=False)):
            if n not in have:
                ng.append(f"{i}: 記事に無い数字「{n}」")
        if bd and not bd.keys() <= {"show"}:   # show だけの指定は、前の表示の続き（棒を1本ずつ出す）
            if bd.get("type") not in BOARD_TYPES:
                ng.append(f"{i}: board.type が不正（{bd.get('type')}）")
            if bd.get("type") == "compare":
                try:
                    [float(v) for _, v in bd["rows"]]
                except Exception:
                    ng.append(f"{i}: compare.rows の形が不正")
    if lines and (lines[0].get("board") or {}).get("type") != "cover":
        ng.append("最初のセリフに cover が無い")
    if lines and (lines[-1].get("board") or {}).get("type") != "end":
        ng.append("最後のセリフに end が無い")
    return ng


def write_script(slug, tries=3):
    """claude に台本を書かせ、検査に通ったものだけ保存する。通らなければ None"""
    import auto_rewrite as AR
    art = article(slug)
    fb = ""
    for k in range(tries):
        prompt = PROMPT.format(article=art["text"][:14000]) + fb
        r = AR.sh([AR.claude_bin(), "-p", "--max-turns", "1", *AR.model_args()], timeout=900, stdin_text=prompt)
        raw = (r.stdout or "").strip()
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            sc = json.loads(m.group(0)) if m else None
        except ValueError:
            sc = None
        if not sc:
            fb = "\n\n前回はJSONとして読めませんでした。JSONだけを出してください。"
            continue
        ng = validate(sc, art)
        if not ng:
            SCRIPTS.mkdir(parents=True, exist_ok=True)
            sc["slug"], sc["title"] = slug, art["title"]
            (SCRIPTS / f"{slug}.json").write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
            return sc
        print(f"   台本 {k + 1}回目 不合格: {' / '.join(ng[:4])}")
        fb = "\n\n前回の台本は次の理由で不合格でした。直して全体を出し直してください:\n- " + "\n- ".join(ng[:12])
    return None


# ---------- 絵 ----------
def _sprites():
    from PIL import Image, ImageEnhance
    sp, dim = {}, {}
    for k, name in (("N", "nana"), ("K", "kenta")):
        sp[k] = {}
        for e in ("open", "half", "closed"):
            for m in ("m0", "m1", "m2", "m3"):
                im = Image.open(CHARS / f"{name}_{e}_{m}.png").convert("RGBA")
                sp[k][(e, m)] = im
                d = ImageEnhance.Brightness(im).enhance(0.9)
                d.putalpha(im.getchannel("A"))
                dim[(k, e, m)] = d
    return sp, dim


def _backdrop():
    import numpy as np
    from PIL import Image, ImageDraw
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H * 0.35) / H) ** 2)
    t = np.clip(r * 1.4, 0, 1)[..., None]
    a = np.array([240, 243, 249], np.float32) * (1 - t) + np.array([214, 222, 236], np.float32) * t
    im = Image.fromarray(a.astype("uint8"))
    d = ImageDraw.Draw(im)
    for x in range(-H, W, 64):
        d.line([(x, 0), (x + H, H)], fill=(228, 233, 242), width=2)
    return im


class Board:
    def __init__(self, title):
        import video_make as VM
        self.VM, self.title = VM, title
        self.base = _backdrop()
        self.cache = {}

    def get(self, st):
        k = json.dumps(st, ensure_ascii=False, sort_keys=True)
        if k not in self.cache:
            self.cache[k] = self.draw(st)
        return self.cache[k], k

    def _card(self, im, box):
        from PIL import Image, ImageDraw, ImageFilter
        x0, y0, x1, y1 = box
        sh = Image.new("L", (W, H), 0)
        ImageDraw.Draw(sh).rounded_rectangle([x0 + 6, y0 + 14, x1 + 6, y1 + 14], 28, fill=70)
        im.paste((20, 30, 60), (0, 0), sh.filter(ImageFilter.GaussianBlur(16)))
        ImageDraw.Draw(im).rounded_rectangle(box, 28, fill=(255, 255, 255))

    def draw(self, st):
        from PIL import ImageDraw
        VM, FB, FR = self.VM, self.VM.font, self.VM.font_regular
        im = self.base.copy()
        d = ImageDraw.Draw(im)
        d.text((W - 40, 36), "AI集客ラボ", font=FB(26), fill=NAVY, anchor="rm")
        t = st.get("type", "cover")
        X0, X1, Y0, Y1 = 470, 1450, 60, 700

        def center_lines(txt, y, base, mn, color, width=860, gap=84, maxl=3):
            # 1行に収まるならそのまま。2行にするときは真ん中に近い助詞・読点の後で切る
            # （幅で機械的に切ると「5つの準／備」のように語の途中で割れる）
            one = VM.fit(d, txt, width, base, max(mn, int(base * 0.75)))
            if d.textlength(txt, font=one) <= width or maxl == 1:
                ls, f = [txt], (one if maxl > 1 else VM.fit(d, txt, width, base, mn))
            else:
                cands = [i + 1 for i, c in enumerate(txt[:-1]) if c in "のにてがをはと、・："]
                ls = None
                for size in range(base, mn - 1, -2):   # 助詞の後で切れる大きさまで下げる
                    f = VM.font(size)
                    cut = [i for i in cands if d.textlength(txt[:i], font=f) <= width
                           and d.textlength(txt[i:], font=f) <= width]
                    if cut:
                        i = min(cut, key=lambda i: abs(i - len(txt) / 2))
                        ls = [txt[:i], txt[i:]]
                        break
                if not ls:
                    f = VM.fit(d, txt, width * 2, base, mn)
                    ls = VM.wrap(d, txt, f, width)[:maxl]
            for i, ln in enumerate(ls):
                d.text((960, y + i * gap - (len(ls) - 1) * gap / 2), ln, font=f, fill=color, anchor="mm")

        if t in ("cover", "end", "step"):
            self._card(im, (X0, Y0 + 40, X1, Y1 - 60))
            d = ImageDraw.Draw(im)
            if t == "cover":
                d.text((960, 190), st.get("kicker", "")[:20], font=FB(42), fill=GOLD, anchor="mm")
                center_lines(st.get("title") or self.title.split("｜")[0], 350, 76, 44, NAVY, gap=100, maxl=2)
                d.line([(760, 480), (1160, 480)], fill=GOLD, width=4)
                d.text((960, 540), "記事をもとに、2人で要点を話します", font=FR(30), fill=MUTED, anchor="mm")
            elif t == "step":
                d.text((960, 200), st.get("head", "今日できる一歩"), font=FB(40), fill=GOLD, anchor="mm")
                for i, ln in enumerate((st.get("lines") or [])[:3]):
                    d.text((960, 300 + i * 84), ln, font=VM.fit(d, ln, 860, 52, 30), fill=NAVY, anchor="mm")
            else:
                d.text((960, 230), "続きは記事で", font=FB(72), fill=NAVY, anchor="mm")
                center_lines(self.title.split("｜")[0], 330, 40, 28, INK, maxl=1)
                d.rounded_rectangle([700, 420, 1220, 500], 40, fill=GOLD)
                d.text((960, 460), "概要欄のリンクから", font=FB(34), fill=(255, 255, 255), anchor="mm")
            return im
        if t == "chapter":
            self._card(im, (X0, 200, X1, 560))
            d = ImageDraw.Draw(im)
            d.text((960, 280), f"CHAPTER {st.get('no', '')}", font=FB(34), fill=GOLD, anchor="mm")
            center_lines(st.get("head", ""), 400, 60, 36, NAVY, gap=76, maxl=2)
            return im
        self._card(im, (X0, Y0, X1, Y1))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([X0, Y0, X1, Y0 + 110], 28, fill=NAVY)
        d.rectangle([X0, Y0 + 70, X1, Y0 + 110], fill=NAVY)
        head = st.get("head", "")
        d.text((X0 + 44, Y0 + 55), head, font=VM.fit(d, head, 900, 44, 26), fill=(255, 255, 255), anchor="lm")
        if t == "points":
            items = (st.get("items") or [])[:4]
            gap = min(118, 420 // max(1, len(items)))
            for i, it in enumerate(items):
                y = Y0 + 170 + i * gap
                d.ellipse([X0 + 50, y - 22, X0 + 94, y + 22], fill=GOLD)
                d.text((X0 + 72, y), str(i + 1), font=FB(26), fill=(255, 255, 255), anchor="mm")
                d.text((X0 + 120, y), it, font=VM.fit(d, it, 800, 44, 26), fill=INK, anchor="lm")
            if st.get("foot"):
                d.text((960, Y1 - 50), st["foot"], font=VM.fit(d, st["foot"], 880, 30, 22), fill=MUTED, anchor="mm")
        elif t == "number":
            v = str(st.get("value", ""))
            d.text((960, 330), v, font=VM.fit(d, v, 880, 150, 60), fill=NAVY, anchor="mm")
            d.line([(760, 440), (1160, 440)], fill=GOLD, width=4)
            lab = st.get("label", "")
            d.text((960, 500), lab, font=VM.fit(d, lab, 880, 38, 24), fill=INK, anchor="mm")
            d.text((960, Y1 - 44), st.get("note", ""), font=VM.fit(d, st.get("note", ""), 900, 24, 18), fill=MUTED, anchor="mm")
        elif t == "compare":
            rows = [(str(a), float(b)) for a, b in (st.get("rows") or [])[:3]]
            mx = max([v for _, v in rows] + [1e-9])
            unit = st.get("unit", "")
            for i, (lab, v) in enumerate(rows[:st.get("show", len(rows))]):
                y = Y0 + 220 + i * (170 if len(rows) <= 2 else 130)
                d.text((X0 + 50, y - 50), lab, font=VM.fit(d, lab, 700, 34, 24), fill=INK, anchor="lm")
                w = 620 * v / mx
                d.rounded_rectangle([X0 + 50, y - 20, X0 + 50 + max(w, 12), y + 40], 12,
                                    fill=GOLD if i == len(rows) - 1 else (150, 165, 190))
                d.text((X0 + 70 + max(w, 12), y + 10), f"{v:g}{unit}", font=FB(58), fill=NAVY, anchor="lm")
            d.text((960, Y1 - 44), st.get("note", ""), font=VM.fit(d, st.get("note", ""), 900, 24, 18), fill=MUTED, anchor="mm")
        elif t == "quote":
            tx = st.get("text", "")
            d.text((960, 340), "「" + tx + "」", font=VM.fit(d, "「" + tx + "」", 880, 64, 32), fill=NAVY, anchor="mm")
            d.text((960, 470), st.get("sub", ""), font=VM.fit(d, st.get("sub", ""), 880, 34, 22), fill=MUTED, anchor="mm")
        elif t == "vs":
            for j, (lab, items, c) in enumerate((("NG", st.get("ng") or [], RED), ("OK", st.get("ok") or [], GREEN))):
                x = X0 + 40 + j * 470
                d.rounded_rectangle([x, Y0 + 140, x + 430, Y1 - 40], 20, outline=c, width=4)
                d.rounded_rectangle([x + 150, Y0 + 120, x + 280, Y0 + 170], 25, fill=c)
                d.text((x + 215, Y0 + 145), lab, font=FB(32), fill=(255, 255, 255), anchor="mm")
                for i, it in enumerate(items[:3]):
                    d.text((x + 30, Y0 + 230 + i * 110), it, font=VM.fit(d, it, 380, 36, 20), fill=INK, anchor="lm")
        return im


def _subtitle(VM, who, name, role, text, pop):
    from PIL import Image, ImageDraw
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    c = COLOR[who]
    d.rounded_rectangle([330, 830, 1590, 1040], 24, fill=(255, 255, 255, 242), outline=c + (255,), width=5)
    fn, fr = VM.font(32), VM.font(22)
    tw = d.textlength(name, font=fn) + d.textlength(role, font=fr) + 70
    tx = 360 if who == "N" else 1560 - tw
    ty = 798 + int(12 * (1 - pop))
    d.rounded_rectangle([tx, ty, tx + tw, ty + 56], 16, fill=c + (255,))
    d.text((tx + 22, ty + 28), name, font=fn, fill=(255, 255, 255), anchor="lm")
    d.text((tx + 34 + d.textlength(name, font=fn), ty + 30), role, font=fr, fill=(230, 222, 190), anchor="lm")
    f = VM.font(48)
    ls = VM.wrap(d, text, f, 1180)[:2]
    y0 = 935 - (len(ls) - 1) * 34
    for i, ln in enumerate(ls):
        d.text((960, y0 + i * 68), ln, font=f, fill=INK, anchor="mm")
    return lay


def chunks(text, limit=44):
    """字幕は短く区切る。かぎ括弧の中では区切らない"""
    sents, buf = [], ""
    for piece in re.split(r"(?<=[。！？])", text):
        buf += piece
        if buf.count("「") > buf.count("」"):
            continue
        sents.append(buf)
        buf = ""
    if buf:
        sents.append(buf)
    out = []
    for s in (x.strip() for x in sents):
        if not s:
            continue
        if len(s) <= limit:
            out.append(s)
            continue
        cur = ""
        for p in re.split(r"(?<=、)", s):
            if cur and len(cur) + len(p) > limit and cur.count("「") == cur.count("」"):
                out.append(cur)
                cur = p
            else:
                cur += p
        if cur:
            out.append(cur)
    return out or [text]


# ---------- 音 ----------
def _read_wav(p):
    import numpy as np
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def _write_wav(p, a, sr):
    import numpy as np
    with wave.open(str(p), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


def _bgm(total, chapter_times, path):
    """自作の和音とアルペジオ（権利の問題が無い）＋章替えのチャイム"""
    import numpy as np
    MSR = 44100
    n = int(total * MSR) + MSR
    tt = np.arange(n) / MSR
    bgm = np.zeros(n, np.float32)
    note = lambda m: 440 * 2 ** ((m - 69) / 12)
    prog = [[48, 55, 64, 67], [45, 52, 60, 64], [41, 48, 57, 60], [43, 50, 59, 62]]
    bar = 3.2
    for k in range(int(total / bar) + 2):
        ch, s0 = prog[k % 4], int(k * bar * MSR)
        if s0 >= n:
            break
        L = int(bar * 1.15 * MSR)
        seg = np.arange(L) / MSR
        env = np.minimum(1, seg / 0.8) * np.minimum(1, (bar * 1.15 - seg) / 0.8)
        pad = sum(np.sin(2 * np.pi * note(m) * seg) + 0.5 * np.sin(2 * np.pi * note(m) * 1.003 * seg) for m in ch)
        e = min(n, s0 + L)
        bgm[s0:e] += (0.05 * env * pad)[:e - s0]
        for j in range(8):
            s1 = s0 + int(j * bar / 8 * MSR)
            if s1 >= n:
                break
            m = ch[[0, 2, 3, 2, 1, 2, 3, 2][j]] + 12
            L2 = int(1.2 * MSR)
            seg2 = np.arange(L2) / MSR
            tone = (np.sin(2 * np.pi * note(m) * seg2) + 0.3 * np.sin(4 * np.pi * note(m) * seg2)) * np.exp(-seg2 * 3.2)
            e2 = min(n, s1 + L2)
            bgm[s1:e2] += (0.045 * tone)[:e2 - s1]
    for _ in range(2):
        bgm = np.convolve(bgm, np.ones(6) / 6, mode="same")
    for t0 in chapter_times:
        s0 = int((t0 - 0.55) * MSR)
        for m, dt in ((79, 0), (84, 0.12)):
            a0 = s0 + int(dt * MSR)
            if a0 < 0 or a0 >= n:
                continue
            L = min(int(1.6 * MSR), n - a0)
            seg = np.arange(L) / MSR
            tone = (np.sin(2 * np.pi * note(m) * seg) + 0.4 * np.sin(2 * np.pi * note(m) * 2.76 * seg) * np.exp(-seg * 6)) * np.exp(-seg * 2.5)
            bgm[a0:a0 + L] += 0.16 * tone
    fade = np.minimum(1, tt / 2) * np.minimum(1, np.maximum(0, (total + 0.5 - tt)) / 2.5)
    _write_wav(path, (bgm * fade).astype(np.float32), MSR)


def make(sc, out_mp4):
    """台本から動画を作る。返り値は秒数"""
    import numpy as np
    from PIL import Image
    import video_make as VM
    lines = sc["lines"]
    names = {"N": "ナナ", "K": "ケンタ"}
    roles = {"N": "AI集客ラボ 解説", "K": sc.get("listener_role") or "経営者"}
    SR = 24000
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        waves = []
        for i, ln in enumerate(lines):
            v, rate, pitch = VOICE[ln["who"]]
            mp3, wav = td / f"v{i:03d}.mp3", td / f"v{i:03d}.wav"
            VM.say(ln["text"], mp3, v, rate, pitch)     # 読み違いは yomi_guard が聞き直して直す
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ar", str(SR), "-ac", "1", str(wav)], check=True)
            a = _read_wav(wav)
            nz = np.where(np.abs(a) > 0.01)[0]
            waves.append(a[max(0, nz[0] - 600):nz[-1] + 1200] if len(nz) else a)
        # 間: 問いの後は短く、同じ人が続くと少し長く、章が変わる前は長く
        gaps = []
        for i, ln in enumerate(lines):
            nx = lines[i + 1] if i + 1 < len(lines) else None
            if nx is None:
                gaps.append(1.2)
            elif (nx.get("board") or {}).get("type") == "chapter":
                gaps.append(0.8)
            elif ln["who"] == "K" and ln["text"].endswith(("？", "?")):
                gaps.append(0.18)
            else:
                gaps.append(0.3 if nx["who"] == ln["who"] else 0.22)
        LEAD = 0.8
        parts, starts, t = [np.zeros(int(LEAD * SR), np.float32)], [], LEAD
        for a, g in zip(waves, gaps):
            starts.append(t)
            parts += [a, np.zeros(int(g * SR), np.float32)]
            t += len(a) / SR + g
        voice = np.concatenate(parts)
        total = len(voice) / SR
        _write_wav(td / "voice.wav", voice, SR)
        chap_t = [starts[i] for i, ln in enumerate(lines) if (ln.get("board") or {}).get("type") == "chapter"]
        _bgm(total, chap_t, td / "bgm.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(td / "voice.wav"), "-i", str(td / "bgm.wav"),
                        "-filter_complex",
                        "[0:a]aresample=44100,highpass=f=75,equalizer=f=250:t=q:w=1:g=-2,equalizer=f=3500:t=q:w=1.2:g=2.5,"
                        "acompressor=threshold=0.08:ratio=2.5:attack=8:release=120:makeup=1.5,"
                        "aecho=0.9:0.6:22|37:0.07|0.04,asplit=2[v][sc];[1:a]volume=0.55[b];"
                        "[b][sc]sidechaincompress=threshold=0.015:ratio=5:attack=30:release=500[bd];"
                        "[v][bd]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=9,alimiter=limit=0.95[a]",
                        "-map", "[a]", "-ar", "44100", str(td / "mix.wav")], check=True)

        # 口の開きは声の大きさで決める（1コマごと）
        def env_of(a):
            hop = SR / FPS
            nf = int(len(a) / hop) + 1
            e = np.array([np.sqrt(np.mean(a[int(i * hop):int((i + 1) * hop)] ** 2)) if int(i * hop) < len(a) else 0
                          for i in range(nf)])
            ref = np.percentile(e[e > 0], 90) if (e > 0).any() else 1
            return np.convolve(np.clip(e / (ref + 1e-6), 0, 1.2), [0.25, 0.5, 0.25], mode="same")
        envs = [env_of(a) for a in waves]
        mouth = lambda v: "m0" if v < 0.12 else "m1" if v < 0.38 else "m2" if v < 0.72 else "m3"
        states, cur = [], {}
        for ln in lines:
            bd = ln.get("board")
            if bd:
                cur = dict(cur, **bd) if bd.keys() <= {"show"} else dict(bd)
            states.append(dict(cur))
        board = Board(sc.get("title", ""))
        sp, dim = _sprites()
        pos = {"N": -60, "K": W - sp["K"][("open", "m0")].width + 90}
        enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(td / "mix.wav"),
                                "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                                "-c:a", "aac", "-b:a", "192k", "-shortest", str(out_mp4)], stdin=subprocess.PIPE)
        rng = random.Random(len(lines))
        blink = {"N": 1.2, "K": 2.0}
        li, prev_key, fade_from, fade_t0, sub_cache = -1, None, None, 0.0, {}
        for f in range(int(total * FPS)):
            t = f / FPS
            while li + 1 < len(lines) and t >= starts[li + 1] - 0.05:
                li += 1
            i = max(li, 0)
            who, text, a = lines[i]["who"], lines[i]["text"], waves[i]
            local = t - starts[i]
            speaking = 0 <= local < len(a) / SR
            v = envs[i][int(local * FPS)] if speaking and int(local * FPS) < len(envs[i]) else 0
            bimg, key = board.get(states[i])
            if key != prev_key:
                fade_from, fade_t0, prev_key = board.cache.get(prev_key) if prev_key else None, t, key
            p = (t - fade_t0) / 0.35
            frame = Image.blend(fade_from, bimg, min(1, p)) if (fade_from is not None and p < 1) else bimg.copy()
            eye = {}
            for k in ("N", "K"):
                dt = t - blink[k]
                if dt < 0 or dt >= 0.15:
                    eye[k] = "open"
                    if dt >= 0.15:
                        blink[k] = t + rng.uniform(2.0, 5.5)
                else:
                    eye[k] = "closed" if 0.05 <= dt < 0.10 else "half"
            for k in ("N", "K"):
                br = math.sin(t * 2 * math.pi / (3.6 if k == "N" else 4.2)) * 3
                if k == who and t >= LEAD:
                    im, dy = sp[k][(eye[k], mouth(v))], br - 5
                else:
                    end = starts[i] + len(a) / SR
                    nod = max(0, 1 - abs(t - (end - 0.25)) / 0.25) if who != k else 0
                    im, dy = dim[(k, eye[k], "m0")], br + 6 + 10 * math.sin(nod * math.pi / 2)
                frame.paste(im, (pos[k], int(H - im.height + 40 + dy)), im)
            z = 1 + 0.022 * min(1, max(0, local) / 6)
            cx = W * (0.42 if who == "N" else 0.58)
            cw, chh = W / z, H / z
            x0 = min(max(0, cx - cw / 2), W - cw)
            y0 = (H - chh) * 0.35
            frame = frame.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + chh))
            if t >= LEAD - 0.1:
                cs = chunks(text)
                wts = [len(VM.read_text(c)) for c in cs]
                pos_ = max(0, local) / max(0.1, len(a) / SR) * sum(wts)
                ci, acc = 0, 0
                for ci, wv in enumerate(wts):
                    acc += wv
                    if pos_ < acc:
                        break
                pop = round(min(1, max(0, local + 0.05) / 0.2), 1)
                sk = (who, cs[ci], pop)
                if sk not in sub_cache:
                    if len(sub_cache) > 60:
                        sub_cache.clear()
                    sub_cache[sk] = _subtitle(VM, who, names[who], roles[who], cs[ci], pop)
                frame.paste(sub_cache[sk], (0, 0), sub_cache[sk])
            enc.stdin.write(frame.tobytes())
        enc.stdin.close()
        enc.wait()
        # YouTube の字幕とチャプター（youtube_upload が読む）
        srt, chaps = [], []
        for i, ln in enumerate(lines):
            s, e = starts[i], starts[i] + len(waves[i]) / SR
            srt.append(f"{i + 1}\n{VM._fmt_srt(s)} --> {VM._fmt_srt(e)}\n{ln['text']}\n")
            bd = ln.get("board") or {}
            if bd.get("type") == "chapter":
                m_, s_ = divmod(int(s), 60)
                chaps.append(f"{m_}:{s_:02d} {bd.get('head', '')[:40]}")
        Path(out_mp4).with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
        Path(out_mp4).with_suffix(".chapters.txt").write_text("\n".join(["0:00 はじめに"] + chaps) + "\n", encoding="utf-8")
    return total


def load_script(slug):
    p = SCRIPTS / f"{slug}.json"
    if not p.is_file():
        return None
    sc = json.loads(p.read_text(encoding="utf-8"))
    return sc if not validate(sc, article(slug)) else None


def ready():
    """この形式で作れる環境か（素材がそろっているか）"""
    return all((CHARS / f"{n}_{e}_{m}.png").is_file() for n in ("nana", "kenta")
               for e in ("open", "half", "closed") for m in ("m0", "m1", "m2", "m3"))


def selftest():
    art = {"text": "延床32坪で断熱等級6。10件すべてが3か月以内。"}
    good = {"listener_role": "工務店 経営", "lines": [{"who": "K", "text": "はじめまして。", "board": {"type": "cover"}}]
            + [{"who": "N", "text": "延床32坪、断熱等級6です。"}] * 34
            + [{"who": "N", "text": "詳しくは記事にまとめています。", "board": {"type": "end"}}]}
    bad = json.loads(json.dumps(good))
    bad["lines"][3]["text"] = "導入企業の85%で成果が出ました。"
    ok = not validate(good, art) and any("85" in x for x in validate(bad, art))
    ok = ok and chunks("「断熱等級はいくつ必要？」みたいに、施主さんは聞きますよね。")[0].startswith("「断熱")
    print("DUO_SELFTEST=" + ("ok" if ok else "ng"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="記事を2人の掛け合い動画にする")
    ap.add_argument("--script", metavar="SLUG")
    ap.add_argument("--make", metavar="SLUG")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.script:
        sc = write_script(a.script)
        print("DUO_SCRIPT=" + ("ok" if sc else "ng"))
        return 0 if sc else 1
    if a.make:
        sc = load_script(a.make) or write_script(a.make)
        if not sc:
            print("DUO_SCRIPT=ng")
            return 1
        import video_make as VM
        out = Path(a.out) if a.out else VM.OUT / f"{a.make}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"{make(sc, out):.0f}秒 → {out}")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
