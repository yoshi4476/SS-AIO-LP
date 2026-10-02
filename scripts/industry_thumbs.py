# -*- coding: utf-8 -*-
"""業種別のサムネイル（「◯◯のAIO対策」の画像）を、ファイル名で引いて記事に当てる。

    site/images/thumbs/aio-<鍵>.jpg   … 鍵は業種ページの slug（shika / clinic / fudosan …）＋細かい区分

記事の frontmatter は書き換えない。build.py が読み込むたびに、次の条件の記事だけ差し替える。
  - アイキャッチが自動生成のもの（/images/<slug>/eyecatch.png）か未設定。手で選んだ画像は触らない
  - 記事の主題が AI検索の対策（カテゴリ aio、または題・狙う語に AIO／AI検索／LLMO など）。
    画像に「◯◯のAIO対策」と書いてあるため、インスタ集客など別の主題の記事に付けると内容と食い違う
  - 業種が分かり、その業種の画像がある
画像を差し替えたいときは、同じ名前で上書きするだけでよい。業種が増えたら、ファイルを置いて KEYS に足す。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "site" / "images" / "thumbs"

# 鍵 → 画像の題（デスクトップのファイル名・一覧にも使う）
KEYS = {
    "shika": "歯科医院のAIO対策",
    "clinic": "クリニック・医療機関のAIO対策",
    "clinic-biyou": "美容外科・美容クリニックのAIO対策",
    "seikotsuin": "整骨院・接骨院のAIO対策",
    "fudosan": "不動産のAIO対策",
    "koumuten": "工務店・注文住宅のAIO対策",
    "btob": "BtoBのAIO対策",
    "btob-system": "システム開発のAIO対策",
    "btob-consulting": "経営戦略・コンサルティングのAIO対策",
    "inshoku": "飲食店のAIO対策",
}
AIO_THEME = re.compile(r"AIO|AI検索|LLMO|AI ?Overview|AIに(選|引用|紹介|出)", re.I)
_DEFS = None


def _hub(title, keyword):
    global _DEFS
    try:
        import industry_hub as IH
        if _DEFS is None:
            _DEFS = IH.load()[0]
        return IH.detect(title, keyword, _DEFS) or ""
    except Exception:
        return ""


def key_for(meta):
    """その記事に当てる鍵（当てないときは空）"""
    title, kw = str(meta.get("title", "")), str(meta.get("keyword", ""))
    if meta.get("category") != "aio" and not AIO_THEME.search(title + " " + kw):
        return ""
    if "飲食" in title or "飲食" in kw:
        return "inshoku"
    hub = _hub(title, kw)
    if hub == "clinic" and "美容" in title:
        return "clinic-biyou"
    if hub == "btob":
        if re.search(r"システム開発|SaaS|IT企業|ソフトウェア", title):
            return "btob-system"
        if "コンサル" in title:
            return "btob-consulting"
    return hub if hub in KEYS else ""


def apply(meta):
    """自動生成のアイキャッチの記事だけ、業種の画像に差し替えた eyecatch を返す"""
    cur = meta.get("eyecatch") or ""
    if cur and cur != f"/images/{meta.get('slug')}/eyecatch.png":
        return cur                                   # 手で選んだ画像はそのまま
    k = key_for(meta)
    if k and (DIR / f"aio-{k}.jpg").is_file():
        return f"/images/thumbs/aio-{k}.jpg"
    return cur
