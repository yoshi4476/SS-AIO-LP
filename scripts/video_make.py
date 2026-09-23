# -*- coding: utf-8 -*-
"""台本から解説動画を作る。音声・スライド・合成すべてローカルで、費用はかからない。

**なぜ動画か**: AI検索での可視性と最も強く相関するのは YouTube での言及だった
（AI Overviews 0.712 / ChatGPT 0.737。リンクの無いWeb言及0.656、被リンク0.218）。
このリポジトリは毎日 YouTube の字幕を材料に使っているのに、出る側になっていない。

**ズレを出さない作り**: スライドの切り替えは、字数から推測せず
**合成した音声の実測の長さ**に合わせる。実測では26字が5.40秒、24字が4.87秒で
比例しなかった。1区間ずつ音声を作り、ffprobe で測り、その秒数でスライドを出す。

  台本(JSON) → 区間ごとに音声(edge-tts) → 実測 → スライド(Pillow) → 合成(ffmpeg)

    python scripts/video_make.py <台本.json>            # mp4 を作る
    python scripts/video_make.py --from-data <slug>     # 一次データから台本を作って作る
    python scripts/video_make.py --selftest             # 道具がそろっているか
"""
import argparse
import asyncio
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "automation" / "video"

W, H = 1920, 1080
NAVY = (11, 36, 71)
BG = (245, 248, 252)
ACCENT = (37, 99, 235)
MUTED = (85, 102, 119)
VOICE = "ja-JP-NanamiNeural"
RATE = "+5%"

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


def fit(d, text, max_w, base, minimum):
    for s in range(base, minimum - 1, -2):
        if d.textlength(text, font=font(s)) <= max_w:
            return font(s)
    return font(minimum)


def wrap(d, text, f, max_w):
    """日本語は単語で切れないので1文字ずつ詰める"""
    lines, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) > max_w and cur:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def slide(path, head, lines, footer="", n=0, total=0, bars=None, caption="",
          active="", unit=""):
    """1枚のスライド。数字の行は棒でも見せる（読み上げだけでは残らない）"""
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 150], fill=NAVY)
    d.text((90, 75), head, font=fit(d, head, W - 260, 64, 34), fill=(255, 255, 255), anchor="lm")
    if total:
        d.text((W - 90, 75), f"{n}/{total}", font=font(30), fill=(150, 175, 205), anchor="rm")

    # 字幕の帯を下に確保する。ここに本文を重ねると読めなくなる
    body_bottom = H - (210 if caption else 110)
    y = 270
    for ln in lines:
        f = fit(d, ln, W - 300, 52, 30)
        for part in wrap(d, ln, f, W - 300):
            if y > body_bottom - 60:
                break
            d.rectangle([90, y - 6, 104, y + 40], fill=ACCENT)
            d.text((136, y + 17), part, font=f, fill=NAVY, anchor="lm")
            y += 86

    # 棒グラフ。値の大小が目で分かると、聞き流しても記憶に残る。
    # **いま読み上げている行だけを濃くする。** 全部同じ色だと、音声と絵が
    # 結びつかず、どこの話をしているのかが分からない
    if bars:
        mx = max((v for _, v in bars), default=0) or 1
        n_bar = len(bars[:6])
        bh = 58 if n_bar <= 4 else 46
        gap = bh + 26
        # 残りの高さの中央に置く。上に寄せると下half が空いて間延びする
        y = max(y + 20, (y + body_bottom - gap * n_bar) // 2)
        bw_full = W - 700
        for label, v in bars[:6]:
            on = (label == active)
            # ラベルは棒の手前（x=470）までに収める。固定サイズだと長い項目名が
            # 棒に食い込む（実測で「リンクの無いWeb言及」がはみ出した）
            lf = fit(d, label, 470 - 100 - 24, 40 if on else 34, 22)
            d.text((100, y + bh / 2), label, font=lf,
                   fill=NAVY if on else MUTED, anchor="lm")
            d.rectangle([470, y, 470 + bw_full, y + bh], fill=(226, 234, 243))
            d.rectangle([470, y, 470 + max(8, bw_full * v / mx), y + bh],
                        fill=ACCENT if on else (167, 190, 222))
            d.text((W - 100, y + bh / 2), f"{v:g}{unit}", font=font(42 if on else 34),
                   fill=NAVY if on else MUTED, anchor="rm")
            y += gap

    if caption:
        d.rectangle([0, H - 190, W, H - 90], fill=(255, 255, 255))
        d.rectangle([0, H - 192, W, H - 188], fill=ACCENT)
        cf = fit(d, caption, W - 180, 40, 26)
        d.text((W / 2, H - 140), caption, font=cf, fill=NAVY, anchor="mm")
    if footer:
        d.text((90, H - 50), footer, font=font(28), fill=MUTED, anchor="lm")
    im.save(path)


# 読み上げのための置き換え。**画面に出す文はそのままで、音だけを直す。**
# 実測で、記号のままだと1文字ずつ読んで極端に遅くなる
# （通常5.5〜6.5字/秒のところ「2023-10〜2026-08」は3.8字/秒だった）
READ_AS = [
    (r"(\d{4})-0?(\d{1,2})-0?(\d{1,2})", "\\1年\\2月\\3日"),
    (r"(\d{4})-0?(\d{1,2})(?!\d)", "\\1年\\2月"),
    (r"[〜~]", "から"),
    (r"(\d)\s*[%％]", "\\1パーセント"),
    (r"(?<=\d),(?=\d{3})", ""),          # 1,000 の読点は区切って読まれる
    (r"G-?ran", "ジーラン"),
    # 日本語に隣接する英字は \\b が効かない（日本語も単語文字のため境界にならない）。
    # 実測で「AIOとMEO」がそのまま残り、1文字ずつ読まれていた
    (r"(?<![A-Za-z])AIO(?![A-Za-z])", "エーアイオー"),
    (r"(?<![A-Za-z])LLMO(?![A-Za-z])", "エルエルエムオー"),
    (r"(?<![A-Za-z])MEO(?![A-Za-z])", "エムイーオー"),
    (r"(?<![A-Za-z])SEO(?![A-Za-z])", "エスイーオー"),
    (r"(?<![A-Za-z])BPO(?![A-Za-z])", "ビーピーオー"),
    (r"(?<![A-Za-z])CSV(?![A-Za-z])", "シーエスブイ"),
    (r"(?<![A-Za-z])CTA(?![A-Za-z])", "シーティーエー"),
    (r"(?<![A-Za-z])AI(?![A-Za-z])", "エーアイ"),
    (r"(?<![A-Za-z])IT(?![A-Za-z])", "アイティー"),
    (r"(?<![A-Za-z])GA4(?![A-Za-z0-9])", "ジーエーフォー"),
]

URL_RE = re.compile(r"(https?://\S+|[a-z0-9-]+(?:\.[a-z0-9-]+){2,}[/\w.-]*)")


def read_text(s):
    """読み上げ用に直す。URLは読まない（意味が伝わらず、長さだけが伸びる）"""
    s = URL_RE.sub("概要欄のリンク", s)
    for pat, rep in READ_AS:
        s = re.sub(pat, rep, s)
    return re.sub(r"\s+", " ", s).strip()


def say(text, path, voice=None, rate=None):
    """読み上げる。声と速さはサイトごとに変えられる（クライアントの色に合わせる）"""
    import edge_tts

    async def go():
        await edge_tts.Communicate(read_text(text), voice or VOICE,
                                   rate=rate or RATE).save(str(path))

    asyncio.run(go())


def duration(path):
    """音声の実測の長さ。**推測しない**（字数と秒数は比例しない）。

    `text=True` を使ってはいけない。Windows では既定の cp932 で復号され、
    ffprobe が返す JSON にファイル名（日本語）が UTF-8 で入るため
    `UnicodeDecodeError` で読めず、stdout が None になる。
    このリポジトリのパス自体に日本語が入っているので必ず起きる。
    """
    r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                        "-show_format", str(path)], capture_output=True,
                       encoding="utf-8", errors="ignore")
    if not r.stdout:
        raise SystemExit(f"長さを測れません: {path}")
    return float(json.loads(r.stdout)["format"]["duration"])


def build(script, out_mp4, quiet=False):
    segs = script["segments"]
    total = len(segs)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        durs, pngs, mp3s = [], [], []
        for i, s in enumerate(segs):
            mp3 = td / f"a{i:03d}.mp3"
            png = td / f"s{i:03d}.png"
            say(s["say"], mp3, script.get("voice"), script.get("rate"))
            sec = duration(mp3)
            # 読み終えた直後に切り替わると忙しないので、区間ごとに0.4秒の余白を置く
            durs.append(sec + 0.4)
            # 読み上げている文をそのまま字幕にする。音を出せない場所で見る人が多く、
            # 字幕が無いと最後まで見られない
            slide(png, s.get("head") or script["title"], s.get("lines") or [],
                  script.get("footer", ""), i + 1, total,
                  bars=s.get("bars"), caption=s["say"],
                  active=s.get("active", ""), unit=script.get("unit", ""))
            mp3s.append(mp3)
            pngs.append(png)
            if not quiet:
                print(f"   区間{i + 1}/{total}  {sec:>5.2f}秒  {s['say'][:28]}")

        # 音声をつなぐ。**mp3 のまま -c copy でつながない。**
        # フレーム境界がそろわず「non monotonically increasing dts」が出て、
        # 実際に区間ごとに数十ミリ秒ずつずれていく。いったん wav に開いてから
        # つなげば、ずれは出ない（最後に aac へ落とす）
        alist = td / "a.txt"
        parts = []
        for i, m in enumerate(mp3s):
            wav, sil = td / f"w{i:03d}.wav", td / f"q{i:03d}.wav"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(m),
                            "-ar", "24000", "-ac", "1", str(wav)], check=True)
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", "anullsrc=r=24000:cl=mono", "-t", "0.4",
                            str(sil)], check=True)
            parts += [wav, sil]
        alist.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        audio = td / "all.wav"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(alist), "-c", "copy", str(audio)], check=True)

        # スライドは実測の秒数で切り替える。concat demuxer は最後の1枚を
        # もう一度書かないと、その区間が0秒になって落ちる
        vlist = td / "v.txt"
        body = "".join(f"file '{p.as_posix()}'\nduration {d:.3f}\n"
                       for p, d in zip(pngs, durs))
        vlist.write_text(body + f"file '{pngs[-1].as_posix()}'\n", encoding="utf-8")

        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(vlist), "-i", str(audio),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                        "-c:a", "aac", "-b:a", "128k", "-shortest",
                        str(out_mp4)], check=True)

    got = duration(out_mp4)
    want = sum(durs)
    gap = abs(got - want)
    if not quiet:
        print(f"   台本の合計 {want:.2f}秒 / 出来た動画 {got:.2f}秒（差 {gap:.2f}秒）")
    # 差が1秒を超えるなら、どこかで音声とスライドがずれている
    if gap > 1.0:
        raise SystemExit(f"音声と映像がずれています（差 {gap:.2f}秒）。書き出しを中止しました")
    return got


MAX_SAY = 54   # 1区間で読み上げてよい字数。これを超えるとスライドが動かない時間が長くなる


def split_say(text):
    """長い文を、読み上げの区切りで分ける。

    **1文をそのまま1区間にしてはいけない。** 実測で、引用用の一文をそのまま
    読ませたら19秒、集計方法は25秒になり、その間スライドが1枚も動かなかった。
    句点で切り、それでも長いものは読点で切る。字幕としても1画面に収まる長さになる。
    """
    out = []
    for s in re.split(r"(?<=。)", text):
        s = s.strip()
        if not s:
            continue
        if len(s) <= MAX_SAY:
            out.append(s)
            continue
        cur = ""
        for part in re.split(r"(?<=、)", s):
            if len(cur) + len(part) > MAX_SAY and cur:
                out.append(cur)
                cur = part
            else:
                cur += part
        if cur:
            out.append(cur)
    return out or [text]


def from_dataset(slug):
    """公開済みの一次データから台本を作る。**数字は登録済みのものしか使わない**"""
    p = ROOT / "data" / "datasets" / f"{slug}.json"
    if not p.is_file():
        raise SystemExit(f"一次データがありません: {slug}")
    ds = json.loads(p.read_text(encoding="utf-8"))
    rows, unit = ds["rows"], ds.get("unit", "")
    bars = [(r["label"], float(r["value"])) for r in rows[:6]]
    segs = []

    # 冒頭。結論から言う（AI検索でも読者でも、先に答えがあるほうが残る）
    for i, s in enumerate(split_say(ds["sentence"])):
        segs.append({"say": s, "head": ds["title"],
                     "lines": [f'母数 {ds["n"]:,}{ds["n_unit"]}',
                               f'対象期間 {ds["period"]}'] if i == 0 else []})

    # 数え方。ここを飛ばすと「どこから出した数字か」が分からず引用されない
    for i, s in enumerate(split_say(ds["method"] + "。")):
        segs.append({"say": s, "head": "どう数えたか", "lines": [s]})

    # 結果。棒で見せてから、1行ずつ読む
    segs.append({"say": "結果はこうなりました。", "head": "結果", "lines": [], "bars": bars})
    for r in rows[:6]:
        v = f'{r["value"]:g}{unit}'
        naka = f'（{r["den"]}{ds["n_unit"]}中 {r["num"]}）' if r.get("den") else ""
        segs.append({"say": f'{r["label"]}は{v}{naka}。', "head": "結果",
                     "lines": [], "bars": bars, "active": r["label"]})

    segs.append({"say": "この集計は当社のサイトで公開しています。",
                 "head": "出典", "lines": [f'ai.7senses.co.jp/data/{slug}/']})
    segs.append({"say": "表とCSVもそのまま使えます。概要欄からご覧ください。",
                 "head": "出典", "lines": [f'ai.7senses.co.jp/data/{slug}/',
                                          "表・グラフ・CSV・構造化データ"]})
    return {"title": ds["title"], "slug": slug, "unit": unit,
            "footer": f'セブンセンシズ株式会社 ／ {ds["period"]} ／ 母数 {ds["n"]:,}{ds["n_unit"]}',
            "segments": segs}


def _plain(s):
    """読み上げ用に、装飾と印を落とす。数字と語は1文字も変えない"""
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)     # リンクは表示文字だけ残す
    s = s.replace("**", "").replace("==", "").replace("*", "")
    s = re.sub(r"[#`|]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def from_article(slug):
    """記事から台本を作る。**本文に書かれていることしか読み上げない。**

    記事はH2の直下に必ず1文結論（40〜60字・単体で意味が通る）を置く決まりなので、
    見出しと1文結論を並べるだけで台本になる。要約をAIに書き直させると、
    本文に無い話が混ざって事実と違う動画になるため、抜き出しに徹する。
    """
    p = ROOT / "articles" / f"{slug}.md"
    if not p.is_file():
        raise SystemExit(f"記事がありません: {slug}")
    t = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    if not m:
        raise SystemExit(f"フロントマターがありません: {slug}")
    fm, body = m.group(1), m.group(2)

    def g(k):
        x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
        return x.group(1).strip().strip('"') if x else ""

    title, desc, cat = g("title"), g("description"), g("category")
    segs = []
    for s in split_say(_plain(desc)):
        segs.append({"say": s, "head": title, "lines": []})

    heads = [(mm.group(1).strip(), mm.end()) for mm in re.finditer(r"^##\s+(.+)$", body, re.M)]
    for i, (h, pos) in enumerate(heads[:8]):
        # 見出し直下の、最初の本文の段落（1文結論）だけを取る
        rest = body[pos:heads[i + 1][1] - len(heads[i + 1][0]) - 3] if i + 1 < len(heads) \
            else body[pos:pos + 900]
        lead = ""
        for ln in rest.split("\n"):
            ln = ln.strip()
            if not ln or ln.startswith(("<", "|", "#", "!", "[")):
                continue
            # 箇条書きの印は「- 」「* 」のように空白が続く。空白で判定しないと、
            # **太字** で始まる1文結論を箇条書きと誤判定して飛ばしてしまう。
            # 実際、この記事の1文結論が全部落ちて、内部リンクの案内文を読み上げていた
            if re.match(r"^[-*+]\s|^\d+\.\s", ln):
                continue
            # 関連記事への案内は本文の主張ではないので読み上げない
            if re.match(r"^(関連|あわせて|近い論点|前提となる|つまずき|費用の目安|選ぶときの)", _plain(ln)):
                continue
            lead = _plain(ln)
            break
        if not lead:
            continue
        head = _plain(h)
        for j, s in enumerate(split_say(lead)):
            segs.append({"say": s, "head": head, "lines": [head] if j == 0 else []})

    url = f"ai.7senses.co.jp/{cat}/{slug}/"
    segs.append({"say": "続きは記事にまとめています。概要欄からご覧ください。",
                 "head": "記事はこちら", "lines": [url]})
    return {"title": title, "slug": slug,
            "footer": "セブンセンシズ株式会社 ／ " + url, "segments": segs}


def selftest():
    ok = True
    for c in ("ffmpeg", "ffprobe"):
        r = subprocess.run([c, "-version"], capture_output=True)
        print(f"  {c}: {'あり' if r.returncode == 0 else 'なし'}")
        ok &= r.returncode == 0
    try:
        import edge_tts  # noqa: F401
        print("  edge-tts: あり")
    except ImportError:
        print("  edge-tts: なし（pip install edge-tts）")
        ok = False
    try:
        font(40)
        print("  日本語フォント: あり")
    except SystemExit:
        print("  日本語フォント: なし")
        ok = False
    print("VIDEO_OK=" + ("yes" if ok else "no"))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script", nargs="?", help="台本のJSON")
    ap.add_argument("--from-data", help="一次データのslugから台本を作る")
    ap.add_argument("--from-article", help="記事のslugから台本を作る")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()
    if a.from_data:
        script = from_dataset(a.from_data)
    elif a.from_article:
        script = from_article(a.from_article)
    elif a.script:
        script = json.loads(Path(a.script).read_text(encoding="utf-8"))
    else:
        ap.print_help()
        return 1

    out = OUT / f'{script["slug"]}.mp4'
    print(f'■ 「{script["title"]}」')
    sec = build(script, out)
    mb = out.stat().st_size / 1024 / 1024
    print(f"  {out}（{sec:.0f}秒 / {mb:.1f}MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
