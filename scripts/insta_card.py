# -*- coding: utf-8 -*-
"""Instagram のカルーセル画像を作る。1080×1350（縦長）。

**なぜ画像が要るか**: Instagram は文字だけの投稿ができない。
本文にURLを書いても押せないので、リンクは「プロフィールから」に誘導するしかない。
つまり**投稿文だけ渡しても投稿できない**媒体で、他の3媒体とは設計が違う。

**なぜ縦長か**: 1080×1350 は正方形より画面に占める面積が大きく、
スクロール中に目に入る時間が長い。

配色は提案書・動画と同じ紺＋金。媒体をまたいで同じ会社に見えるようにする。

    python scripts/insta_card.py --article <slug>    # 1記事ぶん作る
    python scripts/insta_card.py --data <slug>       # 一次データから作る
"""
import argparse
import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "automation" / "insta"

W, H = 1080, 1350
NAVY = (27, 42, 74)
GOLD = (176, 135, 62)
GOLD_L = (239, 228, 206)
MUTED = (107, 122, 141)
PAPER = (255, 255, 255)
MAX_CARDS = 10          # Instagram のカルーセルの上限


def _v():
    import video_make as V
    return V


def cover(path, title, kicker, brand):
    """1枚目。ここで止まるか流されるかが決まるので、文字は大きく少なく"""
    V = _v()
    im = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 14], fill=GOLD)
    d.text((72, 150), kicker, font=V.font(34), fill=GOLD, anchor="lt")
    f = V.fit(d, title, W - 144, 82, 46)
    y = 240
    for ln in V.wrap(d, title, f, W - 144):
        d.text((72, y), ln, font=f, fill=(255, 255, 255), anchor="lt")
        y += f.size + 26
    d.rectangle([72, y + 30, 72 + 140, y + 36], fill=GOLD)
    d.text((72, H - 120), brand, font=V.font(30), fill=(150, 170, 200), anchor="lt")
    d.text((W - 72, H - 120), "スワイプ →", font=V.font(30), fill=GOLD, anchor="rt")
    im.save(path)


def body(path, n, total, head, text, brand):
    """中身の1枚。1枚1メッセージ。詰め込むと読まれない"""
    V = _v()
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 130], fill=NAVY)
    d.text((72, 65), head[:26], font=V.fit(d, head[:26], W - 250, 40, 26),
           fill=(255, 255, 255), anchor="lm")
    d.text((W - 72, 65), f"{n}/{total}", font=V.font(30), fill=GOLD, anchor="rm")

    d.text((72, 230), f"{n - 1:02d}", font=V.font(96), fill=GOLD_L, anchor="lt")
    f = V.fit(d, text, W - 144, 56, 34)
    y = 400
    for ln in V.wrap(d, text, f, W - 144):
        d.text((72, y), ln, font=f, fill=NAVY, anchor="lt")
        y += f.size + 22
    d.rectangle([0, H - 96, W, H - 92], fill=GOLD_L)
    d.text((72, H - 60), brand, font=V.font(26), fill=MUTED, anchor="lm")
    im.save(path)


def closing(path, url, brand):
    """最後の1枚。Instagram は本文のURLが押せないので、ここで行き先を示す"""
    V = _v()
    im = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(im)
    d.text((W / 2, 400), "続きは記事で", font=V.font(72), fill=(255, 255, 255), anchor="mm")
    d.rectangle([W / 2 - 90, 480, W / 2 + 90, 486], fill=GOLD)
    d.text((W / 2, 580), "プロフィールのリンクから", font=V.font(40), fill=GOLD, anchor="mm")
    f = V.fit(d, url, W - 160, 34, 22)
    d.text((W / 2, 680), url, font=f, fill=(150, 170, 200), anchor="mm")
    d.text((W / 2, H - 140), brand, font=V.font(30), fill=(150, 170, 200), anchor="mm")
    im.save(path)


def from_article(slug):
    import social_post as SP
    a = SP.article(slug)
    if not a:
        raise SystemExit(f"公開済みの記事がありません: {slug}")
    sid, cfg = SP.site_of(a["category"])
    pre = (cfg.get("url_prefix") or f'/{a["category"]}').strip("/")
    url = f'{cfg.get("domain", "")}/{pre}/{slug}/'
    brand = cfg.get("name") or "セブンセンシズ株式会社"
    # 見出し直下の1文結論を、そのままカードにする（本文に無いことを書かない）
    texts = a["leads"][:MAX_CARDS - 2] or [a["desc"]]
    return {"slug": slug, "title": a["title"], "kicker": brand,
            "url": url, "brand": brand, "texts": texts}


def from_data(slug):
    p = ROOT / "data" / "datasets" / f"{slug}.json"
    if not p.is_file():
        raise SystemExit(f"一次データがありません: {slug}")
    ds = json.loads(p.read_text(encoding="utf-8"))
    unit = ds.get("unit", "")
    texts = [ds["sentence"]]
    for r in ds["rows"][:5]:
        naka = f'（{r["den"]}{ds["n_unit"]}中 {r["num"]}）' if r.get("den") else ""
        texts.append(f'{r["label"]}　{r["value"]:g}{unit}{naka}')
    texts.append(f'母数 {ds["n"]:,}{ds["n_unit"]}／対象期間 {ds["period"]}')
    return {"slug": slug, "title": ds["title"], "kicker": "自社で集計した一次データ",
            "url": f'ai.7senses.co.jp/data/{slug}/',
            "brand": "セブンセンシズ株式会社", "texts": texts[:MAX_CARDS - 2]}


def build(spec):
    out = OUT / spec["slug"]
    out.mkdir(parents=True, exist_ok=True)
    total = len(spec["texts"]) + 2
    files = [out / "01_cover.png"]
    cover(files[0], spec["title"], spec["kicker"], spec["brand"])
    for i, t in enumerate(spec["texts"], 2):
        p = out / f"{i:02d}.png"
        body(p, i, total, spec["title"], t, spec["brand"])
        files.append(p)
    last = out / f"{total:02d}_link.png"
    closing(last, spec["url"], spec["brand"])
    files.append(last)
    return files


def caption(spec, tags):
    """キャプション。**URLは書かない**（押せないので、書くと不親切に見える）"""
    head = spec["texts"][0] if spec["texts"] else ""
    body_ = "\n".join(f"・{t}" for t in spec["texts"][1:4])
    tagline = " ".join("#" + t.replace(" ", "") for t in tags[:10])
    return (f'{spec["title"]}\n\n{head}\n\n{body_}\n\n'
            f'▼ 続きは記事で\nプロフィールのリンクからご覧ください。\n\n{tagline}')[:2200]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--article")
    ap.add_argument("--data")
    a = ap.parse_args()
    if not (a.article or a.data):
        ap.print_help()
        return 1
    spec = from_article(a.article) if a.article else from_data(a.data)
    files = build(spec)
    print(f'■ {spec["title"]}')
    for f in files:
        print(f"   {f.name}  {f.stat().st_size // 1024}KB")
    print(f"   {OUT / spec['slug']}")
    print()
    print("--- キャプション ---")
    print(caption(spec, ["AIO対策", "AI検索", "オウンドメディア"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
