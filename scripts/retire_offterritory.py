# -*- coding: utf-8 -*-
"""担当領域の違うKWを台帳から取り下げる

使い方:
    python scripts/retire_offterritory.py           # 対象を表示するだけ
    python scripts/retire_offterritory.py --apply   # 台帳の状態を「対象外」に変更

cannibal_check の領域チェックで検出されたKWを、記事にされる前に止める。
公開済みのKWは対象外（既に評価を得ているものを消さない）。
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hub_client  # noqa: E402
from cannibal_check import territory_check  # noqa: E402


def main():
    apply_ = "--apply" in sys.argv
    bad = territory_check()
    if not bad:
        return

    by_site = defaultdict(list)
    for b in bad:
        by_site[b["site"]].append(b)

    print()
    for site, items in by_site.items():
        owner = items[0]["owner"]
        print(f"■ {site}: {len(items)}件を取り下げ（担当は {owner} ほか）")
        if not apply_:
            continue
        r = hub_client._post({
            "action": "retire_kw", "site": site,
            "keywords": [i["keyword"] for i in items],
            "reason": f"担当領域が異なるため取り下げ（{owner} の領域）",
        })
        print(f"   結果: {r.get('retired', 0)}件を「対象外」に変更しました")

    if not apply_:
        print("\n※ 確認モードです。実行するには --apply を付けてください。")


if __name__ == "__main__":
    main()
