# -*- coding: utf-8 -*-
"""四半期: 業種別の調査（5業種×100問×4つのAI）を調べ直し、数字・質問集・チェックリストを作り直す。

    python scripts/research_refresh.py --estimate   # 見積もりだけ（課金なし）
    python scripts/research_refresh.py              # 見積もりが上限内なら調べ直す

費用（2026-10-03 原口さん了承）: ChatGPT の検索つき回答と Perplexity が従量課金で、1回 約17ドル（約2,500円）。
Gemini は無料枠、Claude はサブスク。見積もりが RESEARCH_USD_CAP（既定25ドル）を超えたら調べない。
出典のドメインの種類は data/research/source_class.json（手で確かめた直しを含む）を使い、
新しく出たドメインだけ claude が分ける。新しいドメインは人が確かめるよう「要対応」で知らせる。
提案書（デスクトップの PDF）は手元でしか作れないため、作り直しを「要対応」で知らせる。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def estimate():
    import industry_ai_sources as IAS
    import question_pages as QP
    n = sum(len(IAS.questions(i)) for i in QP.INDS)
    return n, IAS.estimate(n)


def main():
    import industry_ai_sources as IAS
    import question_pages as QP
    n, usd = estimate()
    cap = float(os.environ.get("RESEARCH_USD_CAP") or 25)
    print(f"RESEARCH_EST_USD={usd:.2f}（{n}問・上限 {cap:.0f}ドル）")
    if "--estimate" in sys.argv:
        return 0
    if usd > cap:
        print(f"要対応: 調査の見積もり {usd:.1f}ドルが上限 {cap:.0f}ドルを超えたため、調べ直しを止めました")
        return 0
    before = set(json.loads(IAS.CLASS_FILE.read_text(encoding="utf-8"))) if IAS.CLASS_FILE.is_file() else set()
    failed = []
    for ind in QP.INDS:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "industry_ai_sources.py"), "--industry", ind],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=7200)
        print(r.stdout[-600:])
        if r.returncode != 0:
            failed.append(ind)
            print(f"  {ind}: 失敗 {r.stderr[-300:]}")
    if failed:
        print(f"要対応: 調査の調べ直しに失敗した業種があります: {', '.join(failed)}（前回の数字のまま）")
    for ind in QP.INDS:
        if ind not in failed:
            QP.build_data(ind)
    try:
        import checklist_make
        checklist_make.main()
    except Exception as e:
        print(f"要対応: チェックリスト（PDF）を作り直せませんでした（{str(e)[:80]}）")
    after = set(json.loads(IAS.CLASS_FILE.read_text(encoding="utf-8"))) if IAS.CLASS_FILE.is_file() else set()
    new = sorted(after - before)
    if new:
        print(f"要対応: 調査に新しく出典として出たドメインが {len(new)} 件あります。種類（claude が分けたもの）を確かめる: "
              + "・".join(new[:10]) + "（data/research/source_class.json）")
    print("要対応: 調査の数字が新しくなりました。提案書（デスクトップの AIO系 の PDF）は手元で "
          "python scripts/proposal_make.py --industry <業種> を走らせて作り直してください")
    print(f"RESEARCH_OK={'no' if failed else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
