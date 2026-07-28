# -*- coding: utf-8 -*-
"""KWキューの残数を機械判定する（Phase 1のKW選定で最初に実行）

使い方: python scripts/kw_status.py

docs/industry-pillar-plan.md のクラスターKWリストと articles/*.md を突合し、
未執筆KWの残数・次の候補・補充が必要かを出力する。
LLMの目視判断に頼らず、残数を決定的な数値として得るためのスクリプト。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "docs" / "industry-pillar-plan.md"
REPLENISH_THRESHOLD = 5  # 残りがこの数以下になったらKWリストの補充を促す


def plan_keywords():
    """計画ファイルの「**〜（N本）**: KW / KW / …」行からKWを抽出"""
    if not PLAN.exists():
        return []
    out = []
    for line in PLAN.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"^\*\*(.+?)\*\*\s*[:：]\s*(.+)$", line.strip())
        if not m:
            continue
        group = re.sub(r"（.*?）", "", m.group(1)).strip()
        for kw in m.group(2).split("/"):
            kw = kw.strip()
            if kw:
                out.append((group, kw))
    return out


def written_corpus():
    """既存記事のtitle+description+slugを1本ずつ連結して返す"""
    corpus = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        fm = m.group(1) if m else ""
        fields = re.findall(r"^(?:title|description|slug):\s*(.+)$", fm, re.M)
        corpus.append(p.stem + " " + " ".join(fields))
    return corpus


def is_written(kw, corpus):
    """KWを空白で分解し、全トークンを含む記事が1本でもあれば執筆済みとみなす"""
    tokens = [t for t in re.split(r"[\s　]+", kw) if t]
    return any(all(tok in doc for tok in tokens) for doc in corpus)


def main():
    kws = plan_keywords()
    if not kws:
        print("KW_TOTAL=0")
        print("警告: docs/industry-pillar-plan.md からKWリストを読み取れません。補充が必要です。")
        print("NEED_REPLENISH=yes")
        return

    corpus = written_corpus()
    remaining = [(g, k) for g, k in kws if not is_written(k, corpus)]
    print(f"KW_TOTAL={len(kws)}  KW_WRITTEN={len(kws) - len(remaining)}  KW_REMAINING={len(remaining)}")
    print("次のKW候補（上から順に採用する）:")
    for g, k in remaining[:5]:
        print(f"  - {k}  ［{g}］")
    if len(remaining) <= REPLENISH_THRESHOLD:
        print(f"NEED_REPLENISH=yes  （残り{len(remaining)}本 ≤ 閾値{REPLENISH_THRESHOLD}本）")
        print("→ 記事作成の前に docs/industry-pillar-plan.md へ次の30KWを設計・追記すること")
    else:
        print("NEED_REPLENISH=no")


if __name__ == "__main__":
    main()
