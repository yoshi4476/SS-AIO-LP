# -*- coding: utf-8 -*-
"""社名・サービス名の表記ゆれを、原稿と公開HTMLの全部で数え、原稿は揃える。

**なぜ要るか**: AI検索は「同じ事実が複数の場所で同じ表記で一致しているか」で
確信度を上げる（nap_check と同じ考え方）。言及として数えられるのは同じ表記だけで、
「セブンセンシズ(株)」「Seven Senses」「AI 集客ラボ」は別の名前に見える。

  python scripts/brand_spelling.py           # 数えるだけ
  python scripts/brand_spelling.py --fix     # 原稿（articles/*.md）だけ正規表記へ揃える
出す印: BRAND_OK=yes/no。HTML側に残っている分は再ビルド・再配信で消える。
URL・メールアドレス・コード内は触らない。
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 正規表記 → ゆれ（正規表現）。順序は長いものから
CANON = {
    # 正規表記そのものに一致する書き方（\s* など）を入れない。実際 `セブン\s*センシズ` で
    # 正規表記まで4,989件「ゆれ」と数えた（0.1節: 検出器は見つかるはずの例で試す）
    "セブンセンシズ株式会社": [r"セブンセンシズ\s*[（(]株[）)]", r"[（(]株[）)]\s*セブンセンシズ",
                            r"セブン\s+センシズ株式会社", r"株式会社セブンセンシズ"],
    "セブンセンシズ": [r"セブン・センシズ", r"セブン\s+センシズ", r"ｾﾌﾞﾝｾﾝｼｽﾞ"],
    "AI集客ラボ": [r"AI\s+集客ラボ", r"ＡＩ集客ラボ", r"AI集客\s*Lab\b", r"AI集客らぼ"],
    "AI導入補助金サポート": [r"AI導入補助金\s+サポート", r"ＡＩ導入補助金サポート"],
}
SKIP = re.compile(r"https?://\S+|[\w.+-]+@[\w-]+\.[\w.]+|`[^`]*`|<code>.*?</code>", re.S)


def scan(text):
    """{正規表記: {ゆれ: 件数}}（URL・メール・コードは除く）"""
    body = SKIP.sub(" ", text)
    out = {}
    for canon, pats in CANON.items():
        for p in pats:
            n = len(re.findall(p, body))
            if n:
                out.setdefault(canon, {})[p] = n
    return out


def fix(text):
    def repl_outside(m):
        return m.group(0)
    parts, last, out = [], 0, []
    for m in SKIP.finditer(text):
        seg = text[last:m.start()]
        for canon, pats in CANON.items():
            for p in pats:
                seg = re.sub(p, canon, seg)
        out.append(seg)
        out.append(m.group(0))
        last = m.end()
    seg = text[last:]
    for canon, pats in CANON.items():
        for p in pats:
            seg = re.sub(p, canon, seg)
    out.append(seg)
    return "".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true")
    a = ap.parse_args()
    total, fixed = 0, 0
    print("■ 原稿（articles/*.md）")
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        got = scan(t)
        n = sum(sum(v.values()) for v in got.values())
        if not n:
            continue
        total += n
        print(f"   {p.stem[:40]:<40} " + " / ".join(f"{c}←{sum(v.values())}" for c, v in got.items()))
        if a.fix:
            t2 = fix(t)
            if t2 != t:
                p.write_text(t2, encoding="utf-8", newline="")
                fixed += 1
    print("■ 公開HTML（site/ と配信先の作業コピー）")
    html_n = 0
    for base in (ROOT / "site", ROOT / ".publish-work"):
        for p in base.rglob("*.html"):
            if "node_modules" in p.parts or ".git" in p.parts:
                continue
            try:
                got = scan(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            html_n += sum(sum(v.values()) for v in got.values())
    print(f"   ゆれ {html_n}件（原稿を直して再ビルド・再配信すると消える）")
    if a.fix:
        print(f"   原稿 {fixed}本を正規表記に揃えました")
    if total or html_n:
        print(f"要対応: 社名・サービス名の表記ゆれ 原稿{total}件・HTML{html_n}件（brand_spelling --fix で原稿は揃う）"
              if not a.fix else f"表記ゆれ: 原稿は揃えました。HTML {html_n}件は次の配信で消えます")
    print(f"BRAND_OK={'yes' if not total and not html_n else 'no'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
