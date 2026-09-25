# -*- coding: utf-8 -*-
"""量産の指紋を見つけて止める（Google スパムポリシー「大量生成コンテンツの悪用」への備え）

Google が見るのは「AIか人か」ではなく「順位のための低品質な量産か」。
1本ずつは合格点でも、サイト全体に次の指紋が並ぶと量産に見える。

  1. 業種や地名を入れ替えただけの同型記事（本文の大半が他の記事と重なる）
  2. 同じ一文を何十本にも貼り回す（定型文）
  3. 全記事の長さが同じ幅に揃う（実測で140本中89%が中央値±10%に集中していた）

新しい記事は build.py / publish.py の門で止め、既にある分は週次で知らせる。
止めるのは新しい記事だけ。公開済みを取り下げると、取れている順位まで失う。

    python scripts/scaled_guard.py              # サイト全体の指紋（週次・findings が呼ぶ）
    python scripts/scaled_guard.py <slug>       # 1本を公開してよいか
    python scripts/scaled_guard.py --selftest   # 検出器が効くか
"""
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"

N_GRAM = 10
# この日以降に書いた記事から、配信の入口（publish.py）で止める。
# それより前の同型の組は週次で知らせ、書き分けか統合で片付ける
SINCE = "2026-09-25"
# 実測（2026-09・公開140本）: 最も近い組の重なりは中央値4.8%・上位5%で20.9%・最大22.6%
# （整骨院と歯科、クリニックと不動産など、業種を入れ替えた同型記事）。
# 新しい記事はこの最大を超えさせない。既存の組は週次で知らせて書き分けさせる
BLOCK_SIM = 0.25
WARN_SIM = 0.18
# 5本以上に出る一文が本文に占める割合。実測は最大6.4%
BOILER_DF = 5
BLOCK_BOILER = 0.08
# 同じ一文を貼ってよい本数。これを超えた文は言い換えさせる（実測で最大60本）
SPREAD_MAX = 30
# 長さが中央値±10%に入る記事の割合。これを超えたら偏りとして知らせる
LEN_BAND_MAX = 0.60
# 手順・定義・単一の疑問は quick（3,000字〜）で足りる。
# standard のまま書くと中央値の帯に張り付く
QUICK_KW = re.compile(r"とは|やり方|手順|方法|書き方|設定|登録|申請方法|始め方|意味|違い$")


def _plain(md):
    md = re.sub(r"```.*?```", " ", md, flags=re.S)
    md = re.sub(r"<[^>]+>", " ", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)
    return re.sub(r"[*=#>|`_]", " ", md)


def load(path):
    # 1本の壊れた原稿でビルド全体を止めない（build.py はその記事だけを止めて続行する）
    try:
        t = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    body = _plain(m.group(2))
    flat = re.sub(r"\s+", "", body)
    return {"slug": path.stem, "meta": meta, "flat": flat,
            "grams": {hash(flat[i:i + N_GRAM]) for i in range(max(0, len(flat) - N_GRAM))},
            "sents": {s for s in (re.sub(r"\s+", "", x) for x in re.split(r"[。！？\n]", body))
                      if len(s) >= 20}}


def corpus(min_score=90):
    """公開の対象になる全記事（3サイト共通）。サイトをまたいだ同型も量産の指紋になる"""
    out = {}
    for p in sorted(ARTICLES.glob("*.md")):
        a = load(p)
        if not a:
            continue
        try:
            sc = float(a["meta"].get("score") or 0)
        except (TypeError, ValueError):
            sc = 0
        if sc >= min_score:
            out[a["slug"]] = a
    return out


def jaccard(a, b):
    return len(a & b) / max(1, len(a | b))


def boiler_share(art, df):
    tot = sum(len(s) for s in art["sents"]) or 1
    return sum(len(s) for s in art["sents"] if df[s] >= BOILER_DF) / tot


def check(slug, arts=None):
    """1本を公開してよいか。止める理由のリストを返す（空なら通す）"""
    arts = arts if arts is not None else corpus()
    me = arts.get(slug) or load(ARTICLES / f"{slug}.md")
    if not me:
        return []
    others = {s: a for s, a in arts.items() if s != slug}
    issues = []
    near = max(((jaccard(me["grams"], a["grams"]), s) for s, a in others.items()),
               default=(0.0, ""))
    if near[0] >= BLOCK_SIM:
        issues.append(f"量産の指紋: 本文の{near[0]:.0%}が {near[1]} と重なる"
                      f"（上限{BLOCK_SIM:.0%}。業種を入れ替えただけの同型にしない。"
                      "その業種・地域にしか無い事情と数字で書き分ける）")
    df = Counter()
    for a in others.values():
        df.update(a["sents"])
    bs = boiler_share(me, df)
    if bs >= BLOCK_BOILER:
        issues.append(f"量産の指紋: {BOILER_DF}本以上に出る定型文が本文の{bs:.0%}"
                      f"（上限{BLOCK_BOILER:.0%}。同じ一文を貼らず、この記事の文脈で書く）")
    depth = str(me["meta"].get("depth") or "standard")
    kw = str(me["meta"].get("keyword") or "")
    if depth == "standard" and QUICK_KW.search(kw):
        lens = [len(a["flat"]) for a in others.values()]
        med = statistics.median(lens) if lens else 0
        if med and abs(len(me["flat"]) - med) <= 0.1 * med:
            issues.append(f"量産の指紋: 「{kw}」は手順・定義を答える語なのに depth: standard で、"
                          f"長さが全記事の中央値（{med:,.0f}字）の±10%に入る"
                          "（depth: quick にして、答えに要る分だけ書く）")
    return issues


def report():
    arts = corpus()
    keys = sorted(arts)
    print(f"■ 量産の指紋（公開対象 {len(keys)}本・3サイト合算）\n")
    if len(keys) < 10:
        print("  記事が10本未満のため判定しません\nSCALED_OK=yes")
        return 0
    bad = []
    pairs = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            j = jaccard(arts[a]["grams"], arts[b]["grams"])
            if j >= WARN_SIM:
                pairs.append((j, a, b))
    pairs.sort(reverse=True)
    print(f"  同型の組（本文の重なり{WARN_SIM:.0%}以上）: {len(pairs)}組")
    for j, a, b in pairs[:10]:
        print(f"    {j:.0%} {a} ～ {b}")
    if pairs:
        bad.append(f"要対応: 業種・地名を入れ替えただけの同型記事が{len(pairs)}組"
                   f"（最大{pairs[0][0]:.0%}: {pairs[0][1]} ～ {pairs[0][2]}）。"
                   "片方をその業種にしか無い事情と数字で書き分けるか統合する")

    df = Counter()
    for a in arts.values():
        df.update(a["sents"])
    spread = [(c, s) for s, c in df.items() if c > SPREAD_MAX]
    spread.sort(reverse=True)
    print(f"\n  {SPREAD_MAX}本を超えて貼られている一文: {len(spread)}文")
    for c, s in spread[:8]:
        print(f"    {c}本: {s[:50]}")
    if spread:
        bad.append(f"要対応: 同じ一文が{SPREAD_MAX}本を超えて貼られている（{len(spread)}文・"
                   f"最多{spread[0][0]}本「{spread[0][1][:30]}」）。記事ごとに言い換える")

    lens = [len(a["flat"]) for a in arts.values()]
    med = statistics.median(lens)
    band = sum(1 for L in lens if abs(L - med) <= 0.1 * med) / len(lens)
    depths = Counter(str(a["meta"].get("depth") or "standard") for a in arts.values())
    print(f"\n  長さ: 中央値{med:,.0f}字・±10%に入る記事 {band:.0%}（上限{LEN_BAND_MAX:.0%}）")
    print("  depth の内訳: " + " / ".join(f"{k} {v}本" for k, v in depths.most_common()))
    if band > LEN_BAND_MAX:
        bad.append(f"要対応: 記事の{band:.0%}が同じ長さの帯（{med:,.0f}字±10%）に揃っている。"
                   "手順・定義の語は depth: quick で短く、網羅の語は deep で書き分ける")

    print()
    for b in bad:
        print(b)
    print("SCALED_OK=" + ("no" if bad else "yes"))
    return 0


def selftest():
    """検出器が効くかを、作った同型記事で確かめる（本番の記事は触らない）"""
    arts = corpus()
    if len(arts) < 2:
        print("SELFTEST_OK=yes（記事が足りないため省略）")
        return 0
    src = next(iter(arts.values()))
    clone = dict(src, slug="__clone__")
    arts2 = dict(arts, __clone__=clone)
    got = check("__clone__", arts2)
    ok = any("重なる" in x for x in got)
    print("  同型（丸写し）を止める:", "OK" if ok else "NG")
    print("SELFTEST_OK=" + ("yes" if ok else "no"))
    return 0 if ok else 1


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--selftest" in sys.argv:
        return selftest()
    if args:
        issues = check(args[0])
        for x in issues:
            print("NG " + x)
        print("SCALED_OK=" + ("no" if issues else "yes"))
        return 0
    return report()


if __name__ == "__main__":
    sys.exit(main())
