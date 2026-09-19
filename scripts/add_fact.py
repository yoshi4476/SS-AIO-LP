# -*- coding: utf-8 -*-
"""一次情報を登録する（数値を入れるだけで、記事に使える形にする）

記事に書ける自社数値は data/first_party_facts.json にあるものだけ。
ここに無い数値を書くと、確認できない主張になり、記事全体の信頼が落ちる。

いま未確定のまま止まっているもの:
  - 支援社数・継続率
  - 補助金の採択率
  - 経理BPOの削減時間

**割合を書くときは母数と集計期間が要る**（景品表示法・根拠の明示）。
「採択率90%」だけでは、何社中何社か、いつからいつまでかが分からない。
優良誤認と見なされる。ここで機械的に止める。

  python scripts/add_fact.py --list                    # いま何が登録されているか
  python scripts/add_fact.py --pending                 # 何を入れれば記事が書けるか
  python scripts/add_fact.py --template saitaku        # 記入用の雛形を出す
  python scripts/add_fact.py --check <file.json>       # 書いた内容を検査する
  python scripts/add_fact.py --add <file.json>         # 検査を通れば登録する
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "first_party_facts.json"

# 記入の雛形。何を埋めればよいかを、埋める人が迷わない形で示す
TEMPLATES = {
    "saitaku": {
        "id": "subsidy-saitaku",
        "sites": ["subsidy", "corporate"],
        "topic": ["補助金", "採択率", "申請支援"],
        "claim": "＜例＞2025年4月〜2026年3月に支援した42社のうち38社が採択されました（採択率90.5%）",
        "source": "自社の申請支援実績",
        "as_of": date.today().strftime("%Y-%m"),
        "denominator": 42,
        "period": "2025-04〜2026-03",
        "verifiable": True,
    },
    "shien": {
        "id": "shien-count",
        "sites": ["corporate", "subsidy", "ai-lab"],
        "topic": ["支援実績", "導入支援"],
        "claim": "＜例＞2020年3月の創業から2026年9月までに、のべ◯◯社の導入を支援しました",
        "source": "自社実績",
        "as_of": date.today().strftime("%Y-%m"),
        "denominator": None,
        "period": "2020-03〜2026-09",
        "verifiable": True,
    },
    "bpo": {
        "id": "keiri-bpo-jisseki",
        "sites": ["corporate"],
        "topic": ["経理BPO", "バックオフィス", "業務効率化"],
        "claim": "＜例＞経理BPOを導入した12社では、月次決算の締めが平均◯営業日短くなりました",
        "source": "自社の支援実績",
        "as_of": date.today().strftime("%Y-%m"),
        "denominator": 12,
        "period": "2025-01〜2026-08",
        "verifiable": True,
    },
}

RATE = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|割|パーセント)")
NUM = re.compile(r"\d")


def load():
    d = json.loads(SRC.read_text(encoding="utf-8"))
    d.setdefault("facts", [])
    d.setdefault("pending", [])
    return d


def problems(f, existing_ids):
    """登録してよいかを見る。返した理由が空なら合格"""
    out = []
    for k in ("id", "sites", "topic", "claim", "source", "as_of"):
        if not f.get(k):
            out.append(f"{k} が空です")
    if f.get("id") in existing_ids:
        out.append(f"id「{f.get('id')}」は既に登録されています")
    claim = str(f.get("claim") or "")
    if "＜例＞" in claim or "◯" in claim or "〇" in claim:
        out.append("雛形の例文のままです。実際の数値に置き換えてください")
    if not NUM.search(claim):
        out.append("数値が入っていません。一次情報は数値で書きます")

    # 割合を書くなら、母数と集計期間が要る（景品表示法・根拠の明示）
    if RATE.search(claim):
        if not f.get("denominator"):
            out.append("割合を書くなら denominator（母数）が要ります"
                       "。「何社中何社か」が分からない数字は優良誤認になります")
        if not f.get("period"):
            out.append("割合を書くなら period（集計期間）が要ります"
                       "。いつからいつまでかを示さない数字は根拠になりません")
        d_ = f.get("denominator")
        if isinstance(d_, int) and d_ < 10:
            out.append(f"母数が{d_}件では割合として意味を持ちません"
                       "（実数で書いてください）")
        if f.get("denominator") and str(f["denominator"]) not in claim:
            out.append("claim の中に母数が書かれていません。"
                       "読者が本文だけで根拠を確認できる形にしてください")
        if f.get("period") and not any(x in claim for x in ("年", "月", "〜", "から")):
            out.append("claim の中に集計期間が書かれていません")

    sites = f.get("sites") or []
    known = {p.stem for p in (ROOT / "sites").glob("*.json")}
    for s in sites:
        if s not in known:
            out.append(f"sites の「{s}」は存在しません（候補: {', '.join(sorted(known))}）")
    if not str(f.get("as_of", "")).count("-") == 1:
        out.append("as_of は YYYY-MM の形で書いてください")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pending", action="store_true")
    ap.add_argument("--template", metavar="種類")
    ap.add_argument("--check", metavar="FILE")
    ap.add_argument("--add", metavar="FILE")
    a = ap.parse_args()
    d = load()

    if a.template:
        t = TEMPLATES.get(a.template)
        if not t:
            raise SystemExit(f"種類は {', '.join(TEMPLATES)} のいずれかです")
        print(json.dumps(t, ensure_ascii=False, indent=2))
        print("\n// これをファイルに保存し、＜例＞と◯を実際の数値に置き換えてから", file=sys.stderr)
        print("//   python scripts/add_fact.py --check <ファイル>", file=sys.stderr)
        return 0

    if a.pending:
        print("■ これを入れれば、記事に書けるようになります\n")
        for i, p in enumerate(d["pending"], 1):
            print(f"  [{i}] {p['note']}")
        print("\n  雛形:")
        for k, t in TEMPLATES.items():
            print(f"    python scripts/add_fact.py --template {k}"
                  f"    （{t['claim'][:34]}…）")
        return 0

    if a.list:
        print(f"■ 登録済みの一次情報 {len(d['facts'])}件\n")
        for f in d["facts"]:
            print(f"  [{f['id']}] {', '.join(f.get('sites', []))}")
            print(f"      {f.get('claim', '')[:78]}")
        return 0

    path = a.check or a.add
    if not path:
        raise SystemExit(__doc__.strip())
    try:
        new = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SystemExit(f"読めません: {e}")
    items = new if isinstance(new, list) else [new]

    ids = {f["id"] for f in d["facts"]}
    ng = 0
    for f in items:
        errs = problems(f, ids)
        head = f.get("id") or "(idなし)"
        if errs:
            ng += 1
            print(f"  × {head}")
            for e in errs:
                print(f"      - {e}")
        else:
            print(f"  ○ {head}  {str(f.get('claim'))[:56]}")
    if ng:
        print(f"\n  {ng}件が条件を満たしていません。登録しません")
        return 1
    if not a.add:
        print("\n  すべて条件を満たしています。--add で登録できます")
        return 0

    d["facts"].extend(items)
    SRC.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n  {len(items)}件を登録しました → {SRC.relative_to(ROOT).as_posix()}")
    print("  次に書かれる記事から使われます（site_brief.py が執筆時に渡します）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
