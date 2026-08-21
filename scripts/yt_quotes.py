# -*- coding: utf-8 -*-
"""YouTubeの字幕から、記事に使える発言を拾う

字幕は12本ぶん溜まっているのに、記事では1本も使われていなかった。
数万字の書き起こしをそのまま渡しても読まれないため、
「引用できそうな一文」だけを抜き出して執筆時に渡す。

拾う基準は3つ。
  ・数字を含む一文（AI検索は数値つきの断定文を引用しやすい）
  ・体験・実感を語っている一文（「実際に」「やってみると」など）
  ・つまずきを語っている一文（失敗例の節に使える）

自動字幕は誤変換がある。数値と固有名詞は動画で確認してから書くこと。

使い方:
    python scripts/yt_quotes.py                 # 全件から拾う
    python scripts/yt_quotes.py "経理 AI"       # キーワードに関係するものだけ
    python scripts/yt_quotes.py --list          # 手元にある動画の一覧
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
YT = ROOT / "data" / "youtube_transcripts"

# 体験・つまずきを語っている合図。一般論との区別に使う
EXP = ("実際に", "やってみ", "使ってみ", "試してみ", "感じ", "思いま", "経験",
       "現場で", "私が", "私は", "うちの", "当社")
TROUBLE = ("失敗", "つまず", "ハマ", "注意", "気をつけ", "落とし穴", "ミス",
           "できません", "難しい", "うまくいか")
# 意味の薄い一文を落とす
NOISE = ("チャンネル登録", "高評価", "コメント欄", "概要欄", "次回", "ご視聴",
         "始まり", "こんにちは", "よろしくお願い")


def clean(t):
    """字幕特有の改行を戻して、文単位に切り直す"""
    body = re.sub(r"^#.*$|^再生.*$|^https?://.*$", "", t, flags=re.M)
    body = re.sub(r"\s*\n\s*", "", body)
    return [s.strip() for s in re.split(r"(?<=[。！？])", body) if s.strip()]


def pick(sentences):
    """引用に使えそうな一文を、種類ごとに分けて返す"""
    num, exp, bad = [], [], []
    for s in sentences:
        if len(s) < 14 or len(s) > 110 or any(n in s for n in NOISE):
            continue
        if re.search(r"[0-9０-９]+\s*(%|％|割|倍|時間|分|円|万|件|人|社|店|日|か月|ヶ月|年)", s):
            num.append(s)
        elif any(k in s for k in TROUBLE):
            bad.append(s)
        elif any(k in s for k in EXP):
            exp.append(s)
    return num, exp, bad


def load(kw=None):
    out = []
    for f in sorted(YT.glob("*.txt")):
        t = f.read_text(encoding="utf-8", errors="ignore")
        head = t.splitlines()
        title = next((x.lstrip("# ").strip() for x in head if x.startswith("# ")), f.stem)
        if kw and not any(w in t for w in kw.split()):
            continue
        out.append({"id": f.stem, "title": title, "sentences": clean(t)})
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    kw = args[0] if args else None
    vids = load(kw)
    if not vids:
        print(f"  該当する文字起こしがありません（{YT.relative_to(ROOT).as_posix()}）")
        return
    if "--list" in sys.argv:
        for v in vids:
            print(f"  {v['id']:<14} {len(v['sentences']):>4}文  {v['title'][:44]}")
        return

    for v in vids:
        num, exp, bad = pick(v["sentences"])
        if not (num or exp or bad):
            continue
        print(f"\n■ {v['title'][:56]}")
        print(f"   https://www.youtube.com/watch?v={v['id']}")
        for label, items in (("数字を含む発言", num), ("体験・実感", exp), ("つまずき", bad)):
            for s in items[:3]:
                print(f"   [{label}] {s}")
    print("\n  ※ 自動字幕は誤変換があります。数値と固有名詞は動画で確認してから引用すること")


if __name__ == "__main__":
    main()
