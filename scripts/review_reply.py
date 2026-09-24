# -*- coding: utf-8 -*-
"""Googleマップの口コミに、口コミと同じ言語で返信案を作る（投稿は人が承認してから）。

**なぜ要るか**: 英語・中国語・韓国語の口コミに母語で返すと、次の訪日客の判断材料になる。
返信の有無と新しさは地図での見え方にも効く。ただし返信は店の公式発言なので、
機械は「案」まで。承認したものだけを投稿する。

検査（1つでも外れた案は捨てる）:
  - 口コミに無い数字を書かない（価格・割引・日数の約束をしない）
  - 誇大・保証の語を書かない（必ず・絶対・No.1・治る・効果を保証 など。サイト設定の ng_words も）
  - 症状・施術・個人が特定できる内容に触れない（医療・美容で守秘の違反になる）
  - 長さ 20〜600字

  python scripts/review_reply.py --site <id>              # 返信の無い口コミに案を作る（data/reviews/<id>.jsonl）
  python scripts/review_reply.py --site <id> --list        # 承認待ちの案
  python scripts/review_reply.py --site <id> --approve <n> # n番の案を投稿する
出す印: REVIEW_OK=yes/unset / DRAFTS=<件>。承認待ちがあれば「要対応」を出す（週次の通知に載る）
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DIR = ROOT / "data" / "reviews"
NG = ["必ず", "絶対", "No.1", "ナンバーワン", "日本一", "最高の", "治る", "治ります", "完治", "効果を保証", "保証します",
      "guarantee", "best in", "cure", "100%", "保证", "最好", "治愈", "보장", "최고", "완치"]
MEDICAL = re.compile(r"(症状|治療|施術|診断|処方|手術|薬|symptom|treatment|diagnos|surgery|症状|治疗|诊断|증상|치료|진단)", re.I)


def lang_of(text):
    t = str(text or "")
    if re.search(r"[가-힣]", t):
        return "ko"
    if re.search(r"[぀-ヿ]", t):
        return "ja"
    if re.search(r"[一-鿿]", t):
        return "zh"
    return "en" if re.search(r"[A-Za-z]", t) else "ja"


def check(draft, review, extra_ng=()):
    if not (20 <= len(draft) <= 600):
        return f"長さが{len(draft)}字"
    nums_r = set(re.findall(r"\d+", review.get("comment", "")))
    extra = set(re.findall(r"\d+", draft)) - nums_r
    if extra:
        return f"口コミに無い数字 {sorted(extra)[:3]}"
    for w in list(NG) + list(extra_ng):
        if w and w.lower() in draft.lower():
            return f"使わない語「{w}」"
    if MEDICAL.search(draft) and not MEDICAL.search(review.get("comment", "")):
        return "症状・施術に触れている（口コミ側に無い）"
    if re.search(r"https?://", draft):
        return "URLを入れない"
    return ""


PROMPT = """You are replying, on behalf of the business "{shop}", to a Google Maps review. Write the reply in {lang} only.
Rules: thank the reviewer; respond to what they actually wrote; if negative, apologise briefly and invite them to contact the shop, without excuses.
Do NOT mention prices, discounts, numbers, dates or promises. Do NOT mention symptoms, treatments or anything that identifies the person.
Do NOT use superlatives or guarantees. 2-4 sentences. Output only the reply text.
Review ({rating}): {comment}"""


def draft(shop, review, lg):
    import auto_rewrite as AR
    name = {"ja": "Japanese (polite です/ます)", "en": "English", "zh": "Simplified Chinese", "ko": "Korean"}[lg]
    r = AR.sh([AR.claude_bin(), "-p", "--max-turns", "1", *AR.model_args(), "--allowedTools", ""], timeout=300,
              stdin_text=PROMPT.format(shop=shop, lang=name, rating=review.get("rating", ""), comment=review.get("comment", "")))
    return (r.stdout or "").strip().strip('"')


def load(site):
    p = DIR / f"{site}.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.is_file() else []


def save(site, rows):
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / f"{site}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def main():
    import gbp
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--approve", type=int, default=0)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--check", action="store_true", help="未返信の件数だけ数えて知らせる（週次CI用・案は作らない）")
    a = ap.parse_args()
    cfg = S.load(a.site)
    if a.check:
        got = gbp.reviews(a.site)
        if got is None:
            print("REVIEW_OK=unset")
            return 0
        n = sum(1 for r in got if not r["reply"] and r["comment"])
        if n:
            print(f"要対応: 未返信の口コミが{n}件あります（{cfg.get('name', a.site)}。手元で python scripts/review_reply.py --site {a.site} → --list → --approve <番号>）")
        print(f"REVIEW_OK=yes\nUNREPLIED={n}")
        return 0
    rows = load(a.site)
    pending = [r for r in rows if r.get("status") == "draft"]
    if a.list:
        for i, r in enumerate(pending, 1):
            print(f"[{i}] ★{r['rating']} {r['lang']} {r['comment'][:60]}\n    → {r['draft']}")
        print(f"DRAFTS={len(pending)}")
        return 0
    if a.approve:
        r = pending[a.approve - 1]
        gbp.reply(a.site, r["name"], r["draft"])
        r["status"], r["posted"] = "posted", time.strftime("%Y-%m-%d %H:%M")
        save(a.site, rows)
        print(f"投稿しました: {r['draft'][:60]}")
        return 0
    got = gbp.reviews(a.site)
    if got is None:
        print("  GBP の鍵か gbp.location/account が無いため、口コミを取れません（gbp.py --auth / --check）")
        print("REVIEW_OK=unset\nDRAFTS=0")
        return 0
    seen = {r["name"] for r in rows}
    ng_words = [w for w in re.split(r"[\s、,]+", str(cfg.get("ng_words", ""))) if w]
    made = 0
    for rv in got:
        if rv["reply"] or rv["name"] in seen or not rv["comment"] or made >= a.limit:
            continue
        lg = lang_of(rv["comment"])
        text = draft(cfg.get("name", ""), rv, lg)
        why = check(text, rv, ng_words)
        rows.append({**rv, "lang": lg, "draft": text, "status": "draft" if not why else "rejected", "why": why,
                     "made": time.strftime("%Y-%m-%d")})
        print(f"   {'○' if not why else '×'} {lg} ★{rv['rating']} {rv['comment'][:40]} {why}")
        made += not why
    save(a.site, rows)
    pending = [r for r in rows if r.get("status") == "draft"]
    if pending:
        print(f"要対応: 口コミの返信案が{len(pending)}件あります（{a.site}。確認して python scripts/review_reply.py --site {a.site} --approve <番号>）")
    print(f"REVIEW_OK=yes\nDRAFTS={len(pending)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
