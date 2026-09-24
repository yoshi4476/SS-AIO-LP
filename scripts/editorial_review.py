# -*- coding: utf-8 -*-
"""監修の記録。**監修したと表示する記事は、監修した記録がある記事だけにする。**

記事には「監修: 代表取締役 原口 優」と出し、構造化データの editor にも入れている。
記録が無いまま表示すると、確認していない記事にも監修が付いて見える。
大量に公開するサイトほど、表示と実態の食い違いは信頼の問題として見られる
（Google のスパムポリシー「大量生成コンテンツの悪用」は品質の実態を見る）。

記録の無い新しい記事は build.py と publish.py が公開しない（HELD・監修待ち）。
公開済みを後から外すことはしない。

    python scripts/editorial_review.py --pending                 # 監修待ちの一覧（日次・週次が呼ぶ）
    python scripts/editorial_review.py --approve slug1 slug2     # 確認した記事を記録する
    python scripts/editorial_review.py --approve-all-pending     # 監修待ちを全部記録する（全部読んだとき）
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "editorial_reviews.jsonl"
REVIEWER = "原口 優"
JST = timezone(timedelta(hours=9))


def load():
    out = {}
    if LEDGER.is_file():
        for ln in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("slug"):
                out[r["slug"]] = r
    return out


def reviewed(slug, recs=None):
    return slug in (recs if recs is not None else load())


def record(slugs, by=REVIEWER, note=""):
    have = load()
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    new = [s for s in slugs if s not in have]
    if not new:
        return 0
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8", newline="\n") as f:
        for s in new:
            f.write(json.dumps({"slug": s, "by": by, "at": now, **({"note": note} if note else {})},
                               ensure_ascii=False) + "\n")
    return len(new)


def _score(path):
    m = re.search(r"^score:\s*([0-9.]+)", path.read_text(encoding="utf-8-sig")[:3000], re.M)
    return float(m.group(1)) if m else 0.0


def pending():
    """公開の基準（90点）を満たしたのに監修の記録が無い記事"""
    recs = load()
    return [p.stem for p in sorted((ROOT / "articles").glob("*.md"))
            if _score(p) >= 90 and p.stem not in recs]


def main():
    a = sys.argv[1:]
    if "--approve" in a:
        slugs = [x for x in a[a.index("--approve") + 1:] if not x.startswith("--")]
        miss = [s for s in slugs if not (ROOT / "articles" / f"{s}.md").is_file()]
        if miss:
            raise SystemExit("原稿が見つかりません: " + ", ".join(miss))
        print(f"  記録しました: {record(slugs)}本（監修: {REVIEWER}）")
        return 0
    if "--approve-all-pending" in a:
        print(f"  記録しました: {record(pending())}本（監修: {REVIEWER}）")
        return 0
    p = pending()
    print(f"■ 監修待ち: {len(p)}本（記録の無い記事は公開されません）")
    for s in p[:30]:
        print(f"  - {s}")
    if p:
        print(f"要対応: 監修待ちが{len(p)}本あります。確認したら "
              "python scripts/editorial_review.py --approve <slug> で記録すると公開されます")
    print("REVIEW_OK=" + ("no" if p else "yes"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
