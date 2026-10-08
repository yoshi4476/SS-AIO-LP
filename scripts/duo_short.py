# -*- coding: utf-8 -*-
"""記事から、縦型ショート（YouTubeショート・TikTok）を作る。キャラクターは横型と同じ2人。

**横型を切り出さない理由**: ショートは最初の2秒で見るかどうかが決まり、答えは1つで足りる。
長い動画の一部を切っても問いも答えも途中から始まる。台本はショート用に別に書かせる。

**置き場所**: TikTok もショートも、右端に「いいね・コメント」、下の2割に説明文が重なる。
文字は左寄りの安全な帯（x 60〜940・y 140〜1500）にだけ置き、キャラクターは下に置く（隠れても困らない）。

**締めは検索**: ショートの説明欄のリンクは押せない前提で考え、「AI集客ラボで検索」で締める。
効いたかは指名検索の推移（brand_search）で見る。社名を声でも字幕でも出すのは、
YouTube での言及が AI の回答に出る要因として被リンクより効いていたため（0.3節）。

**事実は記事の本文だけ**（duo_video と同じ検査。記事に無い数字があれば捨てて書き直させる）。

    python scripts/duo_short.py --script <slug>
    python scripts/duo_short.py --make <slug> [--out x.mp4]
    python scripts/duo_short.py --selftest
"""
import argparse
import json
import math
import random
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import duo_video as DV  # noqa: E402

SCRIPTS = ROOT / "data" / "duo_shorts"
W, H, FPS = 1080, 1920, 30
CX = 500                       # 文字の中心。右端のボタン列を避けて左に寄せる
TXT_W = 860
NAVY, INK, GOLD, OLIVE, MUTED, RED, GREEN = DV.NAVY, DV.INK, DV.GOLD, DV.OLIVE, DV.MUTED, DV.RED, DV.GREEN
BOARDS = {"hook", "points", "number", "quote", "vs", "end"}
MAX_CHARS = 330                # 声にして45秒前後

PROMPT = """あなたはYouTubeショート・TikTok の構成作家です。下の記事だけを材料に、縦型ショート（40秒前後）の2人の掛け合い台本をJSONで書いてください。

登場人物:
- N（ナナ）: {brand}の解説役。丁寧語で、短く言い切る。
- K（聞き手）: この記事の読者と同じ立場の経営者。素朴に聞き、驚き、納得する。

守ること:
1. 事実・数字・固有名詞は記事に書いてあるものだけ。記事に無い数字は1つも使わない。
2. 扱う答えは1つだけ。記事の中で、読者がいちばん知りたい問いを1つ選ぶ。
3. 最初のセリフは K の問い。見た人が「自分のことだ」と思う質問にする（25字以内）。
4. 1セリフ45字以内。合計8〜12セリフ、全セリフの合計で300字以内。
5. 2つ目のセリフは N で、「{brand}のナナです。」で始め、そのまま答えに入る。ほかの所では名乗らない。
6. 最後の N のセリフは「詳しくは『{search}』で検索してください。」
7. 記事の文をそのまま読まない。話し言葉にする。
8. 当社の運用実績・実測の数字（件数・順位・クリック率など）は使わない。母数が小さく、短い動画では条件まで伝えきれないため。
9. 「いちばん」「最も」「必ず」「絶対」のような順位・断定は、記事がそう書いているときだけ使う。
10. 「6つ」「3点」のように数を言うなら、その数の項目をすべてボードに出す。出しきれないなら数を言わず「主な点」と言う。

ボード（画面上の板）: 各セリフに "board" を付けると、そのセリフから切り替わる。
- {{"type":"hook","title":"問い（24字以内）"}}                        … 最初のセリフに必ず付ける
- {{"type":"points","head":"見出し","items":["16字以内",...最大3]}}
- {{"type":"number","head":"見出し","value":"記事にある数字","label":"何の数字か","note":"出典"}}
- {{"type":"quote","head":"見出し","text":"大きく見せる一言（20字以内）"}}
- {{"type":"vs","head":"見出し","ng":["14字以内"],"ok":["14字以内"]}}
- {{"type":"end"}}                                                     … 最後のセリフに付ける

出力はJSONだけ:
{{"title":"ショートの題（30字以内。問いの形）","listener_role":"聞き手の肩書き（8字以内）","lines":[{{"who":"K","text":"...","board":{{...}}}},{{"who":"N","text":"..."}}]}}

--- 記事 ---
{article}
"""


def validate(sc, art):
    ng = []
    have = set(DV._nums(art["text"]))
    lines = sc.get("lines") or []
    if not 6 <= len(lines) <= 14:
        ng.append(f"セリフ数が {len(lines)}（8〜12にする）")
    total = sum(len(l.get("text", "")) for l in lines)
    if total > MAX_CHARS:
        ng.append(f"合計{total}字（{MAX_CHARS}字以内にする）")
    if not sc.get("title") or len(sc["title"]) > 40:
        ng.append("title が無いか長すぎる")
    if not sc.get("listener_role") or len(sc["listener_role"]) > 10:
        ng.append("listener_role が無いか長すぎる")
    for i, ln in enumerate(lines):
        t, bd = ln.get("text", ""), ln.get("board")
        if ln.get("who") not in ("N", "K"):
            ng.append(f"{i}: who が N/K でない")
        if not t or len(t) > 60:
            ng.append(f"{i}: セリフが空か長すぎる（{len(t)}字）")
        for n in DV._nums(t + json.dumps(bd or {}, ensure_ascii=False)):
            if n not in have:
                ng.append(f"{i}: 記事に無い数字「{n}」")
        if bd and bd.get("type") not in BOARDS:
            ng.append(f"{i}: board.type が不正（{bd.get('type')}）")
    # 数字の検査では拾えない「順位づけ・断定」も、記事に無ければ通さない
    # （実例: 記事は原因を3つ並べただけなのに「いちばん多いのは」と言わせていた）
    said = "".join(l.get("text", "") + json.dumps(l.get("board") or {}, ensure_ascii=False) for l in lines)
    for w in ("いちばん", "一番", "最も", "必ず", "絶対", "確実"):
        if w in said and w not in art["text"]:
            ng.append(f"記事に無い言い切り「{w}」")
    if lines and (lines[0].get("board") or {}).get("type") != "hook":
        ng.append("最初のセリフに hook が無い")
    if lines and (lines[-1].get("board") or {}).get("type") != "end":
        ng.append("最後のセリフに end が無い")
    br = DV.brand(art)
    first_n = next((l.get("text", "") for l in lines if l.get("who") == "N"), "")
    if not first_n.startswith(f"{br['name']}のナナです"):
        ng.append(f"最初の N のセリフが「{br['name']}のナナです。」で始まっていない")
    if lines and f"『{br['search']}』" not in lines[-1].get("text", ""):
        ng.append(f"最後のセリフで『{br['search']}』の検索を案内していない")
    return ng + DV.brand_ng(sc, art) + count_ng(sc)


COUNT = re.compile(r"(\d+)\s*(?:つ|点|個|項目|ステップ)(?!目)")


def count_ng(sc):
    """言った数と、画面に出す項目の数が合っているか。
    実例: 「使う前に6つの点を確かめて」と言い、ボードには5点しか出さずに終わった（2026-10-03）"""
    lines = sc.get("lines") or []
    shown = 0
    for l in lines:
        b = l.get("board") or {}
        # 「6点を確認」のように数を告げるだけの板は項目に数えない
        own = COUNT.search(" ".join(str(b.get(k, "")) for k in ("title", "head", "text")))
        shown += len(b.get("items") or []) if b.get("type") == "points" else int(b.get("type") in ("quote", "vs", "number") and not own)
    ng = []
    for i, l in enumerate(lines):
        b = l.get("board") or {}
        said = l.get("text", "") + " ".join(str(b.get(k, "")) for k in ("title", "head", "text"))
        for m in COUNT.finditer(said):
            if int(m.group(1)) > shown and "うち" not in said:
                ng.append(f"{i}: 「{m.group(0)}」と言うが、画面に出す項目は{shown}つ。数をそろえるか、数を言わない")
    return ng


def write_script(slug, tries=3):
    import auto_rewrite as AR
    art = DV.article(slug)
    fb = ""
    for k in range(tries):
        r = AR.sh([AR.claude_bin(), "-p", "--max-turns", "1", *AR.model_args()], timeout=600,
                  stdin_text=PROMPT.format(article=art["text"][:14000], brand=DV.brand(art)["name"], search=DV.brand(art)["search"]) + fb)
        m = re.search(r"\{.*\}", (r.stdout or ""), re.S)
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
            sc["slug"] = slug
            (SCRIPTS / f"{slug}.json").write_text(json.dumps(sc, ensure_ascii=False, indent=1), encoding="utf-8")
            sc["brand"] = DV.brand(art)
            return sc
        print(f"   台本 {k + 1}回目 不合格: {' / '.join(ng[:4])}")
        fb = "\n\n前回の台本は次の理由で不合格でした。直して全体を出し直してください:\n- " + "\n- ".join(ng[:12])
    return None


def load_script(slug):
    p = SCRIPTS / f"{slug}.json"
    if not p.is_file():
        return None
    sc = json.loads(p.read_text(encoding="utf-8"))
    art = DV.article(slug)
    sc["brand"] = DV.brand(art)
    return sc if not validate(sc, art) else None


# ---------- 絵 ----------
def _backdrop():
    import numpy as np
    from PIL import Image, ImageDraw
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.sqrt(((xx - W / 2) / W) ** 2 + ((yy - H * 0.3) / H) ** 2)
    t = np.clip(r * 1.3, 0, 1)[..., None]
    a = np.array([240, 243, 249], np.float32) * (1 - t) + np.array([212, 220, 235], np.float32) * t
    im = Image.fromarray(a.astype("uint8"))
    d = ImageDraw.Draw(im)
    for x in range(-H, W, 64):
        d.line([(x, 0), (x + H, H)], fill=(228, 233, 242), width=2)
    return im


def _lines(d, VM, txt, f, width, maxl):
    """助詞・読点の後で折る（語の途中で割らない）"""
    if d.textlength(txt, font=f) <= width:
        return [txt]
    out, cur = [], ""
    for ch in txt:
        if d.textlength(cur + ch, font=f) > width:
            # 読点で切れるならそこで切る。助詞の「の」でも「その・この」の「の」では切らない
            # （実例: 「テンプレ、その／まま使える？」）
            cut = max((i + 1 for i, c in enumerate(cur[:-1]) if c == "、"), default=0)
            if cut < len(cur) * 0.4:
                cut = max((i + 1 for i, c in enumerate(cur[:-1]) if c in "にてがをはと・："
                           or (c == "の" and not (i and cur[i - 1] in "そこあど"))), default=0)
            if cut < len(cur) * 0.5:
                # 助詞で切れないときは、文字の種類が変わる所で切る（「Google／ビジネスプロフィール」。
                # 幅で切ると「プロフ／ィール」のように語が割れた）
                kind = lambda c: "k" if "ァ" <= c <= "ヶ" or c == "ー" else "a" if c.isascii() else "h" if "ぁ" <= c <= "ん" else "j"
                cut = max((i for i in range(1, len(cur)) if kind(cur[i - 1]) != kind(cur[i])), default=0)
                cut = cut if cut >= len(cur) * 0.4 else 0
            if cut:
                out.append(cur[:cut]); cur = cur[cut:] + ch
            else:
                out.append(cur); cur = ch
        else:
            cur += ch
    out.append(cur)
    # 閉じかっこ・句読点を行頭に置かない（「…か／」のように1文字だけ落ちた）
    for i in range(1, len(out)):
        while out[i] and out[i][0] in "」』）、。！？":
            out[i - 1] += out[i][0]
            out[i] = out[i][1:]
    return [x for x in out if x][:maxl]


class Board:
    def __init__(self, sc):
        import video_make as VM
        self.VM, self.sc, self.base, self.cache = VM, sc, _backdrop(), {}
        self.br = sc.get("brand") or DV.BRANDS["ai-lab"]
        self.hook = next((l["board"].get("title", "") for l in sc["lines"] if (l.get("board") or {}).get("type") == "hook"), sc.get("title", ""))

    def get(self, st):
        k = json.dumps(st, ensure_ascii=False, sort_keys=True)
        if k not in self.cache:
            self.cache[k] = self.draw(st)
        return self.cache[k], k

    def draw(self, st):
        from PIL import ImageDraw, ImageFilter, Image
        VM, FB, FR = self.VM, self.VM.font, self.VM.font_regular
        im = self.base.copy()
        d = ImageDraw.Draw(im)
        # 上: 問いを出し続ける（途中から見た人にも何の話か分かる）
        d.text((60, 150), self.br["name"], font=FB(34), fill=NAVY, anchor="lm")
        d.line([(60, 190), (200, 190)], fill=GOLD, width=5)
        f = VM.fit(d, self.hook, TXT_W, 78, 50)
        ls = _lines(d, VM, self.hook, f, TXT_W, 3)
        for i, ln in enumerate(ls):
            d.text((60, 250 + i * (f.size + 18)), ln, font=f, fill=INK, anchor="la")
        t = st.get("type", "hook")
        if t == "hook":
            # 最初の2秒で「自分のことだ」と分かるよう、問いを板いっぱいに出す
            d.rounded_rectangle([60, 560, 940, 1120], 30, fill=NAVY)
            d.text((CX, 660), "Q.", font=FB(90), fill=GOLD, anchor="mm")
            f2 = VM.fit(d, self.hook, 1560, 96, 60)
            ls2 = _lines(d, VM, self.hook, f2, 780, 3)
            for i, ln in enumerate(ls2):
                d.text((CX, 860 + (i - (len(ls2) - 1) / 2) * (f2.size + 26)), ln, font=f2, fill=(255, 255, 255), anchor="mm")
            d.text((CX, 1060), "40秒で答えます", font=FR(34), fill=(200, 210, 230), anchor="mm")
            return im
        # 中: 板
        x0, y0, x1, y1 = 60, 560, 940, 1120
        sh = Image.new("L", (W, H), 0)
        ImageDraw.Draw(sh).rounded_rectangle([x0 + 6, y0 + 14, x1 + 6, y1 + 14], 30, fill=70)
        im.paste((20, 30, 60), (0, 0), sh.filter(ImageFilter.GaussianBlur(16)))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([x0, y0, x1, y1], 30, fill=(255, 255, 255))
        if t == "end":
            d.text((CX, y0 + 150), "続きは記事で", font=FB(84), fill=NAVY, anchor="mm")
            d.rounded_rectangle([x0 + 80, y0 + 270, x1 - 80, y0 + 400], 60, fill=GOLD)
            q = f"「{self.br['search']}」で検索"
            d.text((CX, y0 + 335), q, font=VM.fit(d, q, 660, 56, 36), fill=(255, 255, 255), anchor="mm")
            d.text((CX, y0 + 470), self.br["url"], font=FR(40), fill=MUTED, anchor="mm")
            return im
        d.rounded_rectangle([x0, y0, x1, y0 + 120], 30, fill=NAVY)
        d.rectangle([x0, y0 + 80, x1, y0 + 120], fill=NAVY)
        head = st.get("head", "")
        d.text((x0 + 44, y0 + 60), head, font=VM.fit(d, head, 790, 48, 30), fill=(255, 255, 255), anchor="lm")
        if t == "points":
            items = (st.get("items") or [])[:3]
            for i, it in enumerate(items):
                y = y0 + 210 + i * 125
                d.ellipse([x0 + 44, y - 28, x0 + 100, y + 28], fill=GOLD)
                d.text((x0 + 72, y), str(i + 1), font=FB(32), fill=(255, 255, 255), anchor="mm")
                d.text((x0 + 128, y), it, font=VM.fit(d, it, 690, 52, 30), fill=INK, anchor="lm")
        elif t == "number":
            v = str(st.get("value", ""))
            d.text((CX, y0 + 260), v, font=VM.fit(d, v, 780, 170, 70), fill=NAVY, anchor="mm")
            d.line([(CX - 180, y0 + 370), (CX + 180, y0 + 370)], fill=GOLD, width=5)
            lab = st.get("label", "")
            for i, ln in enumerate(_lines(d, VM, lab, VM.font(42), 780, 2)):
                d.text((CX, y0 + 420 + i * 54), ln, font=VM.font(42), fill=INK, anchor="mm")
            d.text((CX, y1 - 36), st.get("note", ""), font=VM.fit(d, st.get("note", ""), 800, 26, 18), fill=MUTED, anchor="mm")
        elif t == "quote":
            tx = "「" + st.get("text", "") + "」"
            f = VM.fit(d, tx, 1500, 70, 44)
            ls = _lines(d, VM, tx, f, 780, 3)
            for i, ln in enumerate(ls):
                d.text((CX, y0 + 330 + (i - (len(ls) - 1) / 2) * (f.size + 20)), ln, font=f, fill=NAVY, anchor="mm")
        elif t == "vs":
            for j, (lab, items, c) in enumerate((("NG", st.get("ng") or [], RED), ("OK", st.get("ok") or [], GREEN))):
                y = y0 + 170 + j * 190
                d.rounded_rectangle([x0 + 40, y - 40, x0 + 170, y + 40], 24, fill=c)
                d.text((x0 + 105, y), lab, font=FB(40), fill=(255, 255, 255), anchor="mm")
                it = (items or [""])[0]
                d.text((x0 + 200, y), it, font=VM.fit(d, it, 640, 50, 28), fill=INK, anchor="lm")
        return im


def _subtitle(VM, who, name, role, text):
    from PIL import Image, ImageDraw
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    c = DV.COLOR[who]
    x0, y0, x1, y1 = 60, 1170, 940, 1400
    d.rounded_rectangle([x0, y0, x1, y1], 26, fill=(255, 255, 255, 245), outline=c + (255,), width=5)
    fn, fr = VM.font(34), VM.font(24)
    tw = d.textlength(name, font=fn) + d.textlength(role, font=fr) + 70
    tx = x0 + 24 if who == "N" else x1 - 24 - tw
    d.rounded_rectangle([tx, y0 - 34, tx + tw, y0 + 26], 16, fill=c + (255,))
    d.text((tx + 22, y0 - 4), name, font=fn, fill=(255, 255, 255), anchor="lm")
    d.text((tx + 34 + d.textlength(name, font=fn), y0 - 2), role, font=fr, fill=(230, 222, 190), anchor="lm")
    f = VM.font(52)
    ls = DV.balanced_lines(d, text, f, 800)
    for i, ln in enumerate(ls):
        d.text((CX, (y0 + y1) / 2 + 8 + (i - (len(ls) - 1) / 2) * 72), ln, font=f, fill=INK, anchor="mm")
    return lay


def make(sc, out_mp4):
    import numpy as np
    from PIL import Image
    import video_make as VM
    lines = sc["lines"]
    names = {"N": "ナナ", "K": "ケンタ"}
    roles = {"N": (sc.get("brand") or DV.BRANDS["ai-lab"])["name"], "K": sc.get("listener_role") or "経営者"}
    SR = 24000
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        td = Path(td)
        waves = DV.voices(VM, lines, td, SR, "short")
        t_audio = time.perf_counter()
        # ショートは間を詰める（長い間で指が離れる）
        gaps = [0.12 if (ln["who"] == "K" and ln["text"].endswith(("？", "?"))) else 0.18 for ln in lines]
        gaps[-1] = 1.0
        LEAD = 0.25
        parts, starts, t = [np.zeros(int(LEAD * SR), np.float32)], [], LEAD
        for a, g in zip(waves, gaps):
            starts.append(t)
            parts += [a, np.zeros(int(g * SR), np.float32)]
            t += len(a) / SR + g
        voice = np.concatenate(parts)
        total = len(voice) / SR
        DV._write_wav(td / "voice.wav", voice, SR)
        DV._bgm(total, [], td / "bgm.wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(td / "voice.wav"), "-i", str(td / "bgm.wav"),
                        "-filter_complex",
                        "[0:a]aresample=44100,highpass=f=75,equalizer=f=3500:t=q:w=1.2:g=2.5,"
                        "acompressor=threshold=0.08:ratio=2.5:attack=8:release=120:makeup=1.5,asplit=2[v][sc];"
                        "[1:a]volume=0.5[b];[b][sc]sidechaincompress=threshold=0.015:ratio=5:attack=30:release=500[bd];"
                        "[v][bd]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=9,alimiter=limit=0.95[a]",
                        "-map", "[a]", "-ar", "44100", str(td / "mix.wav")], check=True)
        VM.note_time("short.audio", time.perf_counter() - t_audio)
        t_render, t_draw, t_write = time.perf_counter(), 0.0, 0.0

        def env_of(a):
            hop = SR / FPS
            e = np.array([np.sqrt(np.mean(a[int(i * hop):int((i + 1) * hop)] ** 2)) if int(i * hop) < len(a) else 0
                          for i in range(int(len(a) / hop) + 1)])
            ref = np.percentile(e[e > 0], 90) if (e > 0).any() else 1
            return np.convolve(np.clip(e / (ref + 1e-6), 0, 1.2), [0.25, 0.5, 0.25], mode="same")
        envs = [env_of(a) for a in waves]
        mouth = lambda v: "m0" if v < 0.12 else "m1" if v < 0.38 else "m2" if v < 0.72 else "m3"
        states, cur = [], {}
        for ln in lines:
            if ln.get("board"):
                cur = dict(ln["board"])
            states.append(dict(cur))
        board = Board(sc)
        sp0, dim0 = DV._sprites()
        # 1200px の素材を 640px に一度だけ縮める（毎コマは縮めない）
        CH = 640
        rs = lambda im: im.resize((round(im.width * CH / im.height), CH), Image.LANCZOS)
        sp = {k: {kk: rs(v) for kk, v in d.items()} for k, d in sp0.items()}
        dim = {k: rs(v) for k, v in dim0.items()}
        # 毎コマ貼るものは透明な余白を落としておく（字幕は画面全体の大きさの透明な板だった。貼った結果は同じ）
        sp_c = {k: {kk: DV.crop_layer(im) for kk, im in d.items()} for k, d in sp.items()}
        dim_c = {kk: DV.crop_layer(im) for kk, im in dim.items()}
        line_cs = {}     # 字幕の区切りと読みの重みはセリフごとに1回だけ求める
        pos = {"N": 10, "K": 470}
        enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(td / "mix.wav"),
                                "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "medium", "-tune", "animation", "-crf", "18",
                                "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(out_mp4)],
                               stdin=subprocess.PIPE, stderr=open(td / "enc.log", "w", encoding="utf-8", errors="ignore"))
        rng = random.Random(len(lines))
        blink = {"N": 1.0, "K": 1.8}
        li, prev_key, fade_from, fade_t0, sub_cache = -1, None, None, 0.0, {}
        for f in range(int(total * FPS)):
            t0f = time.perf_counter()
            t = f / FPS
            while li + 1 < len(lines) and t >= starts[li + 1] - 0.04:
                li += 1
            i = max(li, 0)
            who, a = lines[i]["who"], waves[i]
            local = t - starts[i]
            speaking = 0 <= local < len(a) / SR
            v = envs[i][int(local * FPS)] if speaking and int(local * FPS) < len(envs[i]) else 0
            bimg, key = board.get(states[i])
            if key != prev_key:
                fade_from, fade_t0, prev_key = board.cache.get(prev_key) if prev_key else None, t, key
            p = (t - fade_t0) / 0.25
            frame = Image.blend(fade_from, bimg, min(1, p)) if (fade_from is not None and p < 1) else bimg.copy()
            for k in ("N", "K"):
                dt = t - blink[k]
                if dt < 0 or dt >= 0.15:
                    eye = "open"
                    if dt >= 0.15:
                        blink[k] = t + rng.uniform(2.0, 5.0)
                else:
                    eye = "closed" if 0.05 <= dt < 0.10 else "half"
                br = math.sin(t * 2 * math.pi / (3.6 if k == "N" else 4.2)) * 3
                if k == who:
                    im, dy = sp[k][(eye, mouth(v))], br - 6
                    cim, cx, cy = sp_c[k][(eye, mouth(v))]
                else:
                    im, dy = dim[(k, eye, "m0")], br + 6
                    cim, cx, cy = dim_c[(k, eye, "m0")]
                frame.paste(cim, (pos[k] + cx, int(H - im.height + 30 + dy) + cy), cim)
            if i not in line_cs:
                cs0 = DV.chunks(lines[i]["text"], limit=30)
                line_cs[i] = (cs0, [len(VM.read_text(c)) for c in cs0])
            cs, wts = line_cs[i]
            pos_ = max(0, local) / max(0.1, len(a) / SR) * sum(wts)
            ci, acc = 0, 0
            for ci, wv in enumerate(wts):
                acc += wv
                if pos_ < acc:
                    break
            sk = (who, cs[ci])
            if sk not in sub_cache:
                sub_cache[sk] = DV.crop_layer(_subtitle(VM, who, names[who], roles[who], cs[ci]))
            sim, sx, sy = sub_cache[sk]
            frame.paste(sim, (sx, sy), sim)
            t1f = time.perf_counter()
            t_draw += t1f - t0f
            try:
                enc.stdin.write(frame.tobytes())
            except BrokenPipeError:
                # ffmpeg が先に落ちると「Broken pipe」しか残らず、原因が分からなかった（2026-10-03）
                enc.wait()
                raise RuntimeError("ffmpeg が止まりました: " + (td / "enc.log").read_text(encoding="utf-8", errors="ignore")[-400:])
            t_write += time.perf_counter() - t1f
        t1f = time.perf_counter()
        enc.stdin.close()
        enc.wait()
        t_write += time.perf_counter() - t1f
        VM.note_time("short.render", time.perf_counter() - t_render, f"frames={int(total * FPS)} {W}x{H}")
        VM.note_time("short.render.draw", t_draw)
        VM.note_time("short.render.encode_wait", t_write)
        # 字幕（youtube_upload が <動画>.srt を上げる）。無いと YouTube の自動字幕が出て、
        # 「[音楽]」や聞き違い（請求書テンプレ→請求書店）がそのまま表示されていた（2026-10-03）
        srt = [f"{i + 1}\n{VM._fmt_srt(s)} --> {VM._fmt_srt(s + len(a) / SR)}\n{ln['text']}\n"
               for i, (ln, s, a) in enumerate(zip(lines, starts, waves))]
        Path(out_mp4).with_suffix(".srt").write_text("\n".join(srt), encoding="utf-8")
    return total


def selftest():
    art = {"text": "延床32坪で断熱等級6。AI集客ラボ。"}
    good = {"title": "工務店はAIに何と聞かれる？", "listener_role": "工務店 経営",
            "lines": [{"who": "K", "text": "AIに聞かれる？", "board": {"type": "hook", "title": "問い"}}]
            + [{"who": "N", "text": "AI集客ラボのナナです。延床32坪です。"}] * 7
            + [{"who": "N", "text": "詳しくは『AI集客ラボ』で検索してください。", "board": {"type": "end"}}]}
    bad = json.loads(json.dumps(good))
    bad["lines"][2]["text"] = "問い合わせが3倍になりました。"
    many = json.loads(json.dumps(good))
    many["lines"][2]["text"] = "確かめる点は6つあります。"
    other = json.loads(json.dumps(good))
    other["lines"][1]["text"] = "セブンセンシズのナナです。"
    ok = (not validate(good, art) and any("「3」" in x for x in validate(bad, art))
          and any("6つ" in x for x in validate(many, art)) and any("ナナです" in x for x in validate(other, art)))
    print("SHORT_SELFTEST=" + ("ok" if ok else "ng"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="記事から縦型ショートを作る")
    ap.add_argument("--script", metavar="SLUG")
    ap.add_argument("--make", metavar="SLUG")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    slug = a.script or a.make
    if not slug:
        ap.print_help()
        return 0
    sc = (load_script(slug) if a.make else None) or write_script(slug)
    if not sc:
        print("SHORT_SCRIPT=ng")
        return 1
    if a.script:
        print("SHORT_SCRIPT=ok")
        return 0
    import video_make as VM
    out = Path(a.out) if a.out else VM.OUT / f"{slug}.short.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"{make(sc, out):.0f}秒 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
