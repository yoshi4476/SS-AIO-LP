# -*- coding: utf-8 -*-
"""カニバリゼーション（検索意図の重複）を機械検出する

使い方: python scripts/cannibal_check.py

タイトル・説明文・H2見出しの文字バイグラム類似度で、既存記事どうしの重複を検出する。
形態素解析ライブラリなしで日本語の意図重複を判定するため、文字2-gramのDice係数を使う。
KW選定時の重複回避（kw_status.py）からも本モジュールの関数を利用する。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WARN = 0.50   # これ以上で「要確認」
STRONG = 0.62  # これ以上で「統合を検討」
_NOISE = re.compile(r"[\s　【】\[\]（）()「」『』・、。,.!?！？|｜:：/／〜~\-—+*#\"']")


def bigrams(text):
    t = _NOISE.sub("", str(text)).lower()
    return {t[i:i + 2] for i in range(len(t) - 1)} or {t}


def dice(a, b):
    """2つの文字列の文字バイグラムDice係数（0〜1。1が完全一致）"""
    x, y = bigrams(a), bigrams(b)
    if not x or not y:
        return 0.0
    return 2 * len(x & y) / (len(x) + len(y))


def load_articles():
    arts = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.groups()

        def fv(k):
            mm = re.search(rf"^{k}:\s*(.+?)\s*$", fm, re.M)
            return mm.group(1).strip('"') if mm else ""

        arts.append({
            "slug": p.stem, "title": fv("title"), "desc": fv("description"),
            "cat": fv("category"),
            "h2": [h.strip() for h in re.findall(r"^##\s+(.+?)\s*$", body, re.M)],
        })
    return arts


def h2_overlap(a, b):
    """H2見出しの重なり率（構成レベルの重複度）"""
    if not a["h2"] or not b["h2"]:
        return 0.0
    hits = sum(1 for x in a["h2"] if any(dice(x, y) >= 0.6 for y in b["h2"]))
    return hits / min(len(a["h2"]), len(b["h2"]))


def find_pairs(arts):
    pairs = []
    for i in range(len(arts)):
        for j in range(i + 1, len(arts)):
            a, b = arts[i], arts[j]
            ttl = dice(a["title"], b["title"])
            dsc = dice(a["desc"], b["desc"])
            ov = h2_overlap(a, b)
            score = max(ttl, (ttl + dsc) / 2, ov * 0.9)
            if score >= WARN:
                pairs.append({"a": a, "b": b, "score": round(score, 2),
                              "title_sim": round(ttl, 2), "h2_overlap": round(ov, 2)})
    return sorted(pairs, key=lambda p: -p["score"])


def main():
    arts = load_articles()
    pairs = find_pairs(arts)
    print(f"CANNIBAL_CHECK: {len(arts)}記事を検査 / 重複疑い {len(pairs)}組")
    if not pairs:
        print("CANNIBAL_FOUND=no")
        return
    print("CANNIBAL_FOUND=yes")
    for p in pairs:
        action = "統合を検討（低品質側を削除し301相当の内部リンク集約）" if p["score"] >= STRONG \
            else "差別化（H1・メタ・冒頭結論の切り口を分ける／片方を対象読者で限定する）"
        print(f"\n[{p['score']}] {p['a']['slug']}  ×  {p['b']['slug']}")
        print(f"  A: {p['a']['title']}")
        print(f"  B: {p['b']['title']}")
        print(f"  タイトル類似 {p['title_sim']} / H2構成の重なり {p['h2_overlap']}")
        print(f"  → 推奨対処: {action}")
    sys.exit(0)


if __name__ == "__main__":
    main()
