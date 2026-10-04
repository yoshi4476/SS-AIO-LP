# -*- coding: utf-8 -*-
"""地域×業種の語（例: 大阪 歯科医院 集客）を、需要を確かめてから台帳に積む。

地域の検索（「大阪 歯科 集客」）の受け皿が無かった。ただし地域名だけを入れ替えた記事を並べると、
Google のスパムポリシー「大量生成コンテンツの不正使用」の典型になる（scaled_guard が止める形）。
そこで地域は、その社が実際に拠点を置く所だけにする（sites/<id>.json の kw_seeds.regions。書いていない社は動かない）。

1. 優先業種 × 地域 × 集客の語 で Google のサジェスト（無料）を引く
2. 地域名と業種名の両方を含む候補だけを残す（サジェストに出る＝実際に検索されている）
3. kw_guard を通ったもの（終了コード0）だけを、1回の上限まで台帳に積む

    python scripts/region_kw.py --site ai-lab            # 候補を見る
    python scripts/region_kw.py --site ai-lab --append   # 台帳に積む（週次）
"""
import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CORE = ("集客", "ホームページ", "SEO", "AI検索")
DROP = re.compile(r"求人|採用|バイト|転職|副業|資格|口コミ 悪い|ランキング|おすすめ 歯医者|安い")
LIMIT = 6


def candidates(site_id, regions, inds, owns, wait=0.25):
    import kw_discover as KD
    seen, out = set(), []
    for reg in regions:
        for ind in inds:
            for core in CORE:
                for s in KD.suggest(f"{reg} {ind} {core}"):
                    k = re.sub(r"\s+", " ", s).strip()
                    if reg not in k or ind[:2] not in k or DROP.search(k):
                        continue
                    if not any(o.lower() in k.lower() for o in owns):
                        continue       # 売っていない領域（ホームページ制作など）・患者の検索は読者が顧客でない
                    key = k.replace(" ", "")
                    if key not in seen:
                        seen.add(key)
                        out.append(k)
                time.sleep(wait)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="ai-lab")
    ap.add_argument("--append", action="store_true")
    ap.add_argument("--limit", type=int, default=LIMIT)
    a = ap.parse_args()
    import kw_guard as KG
    import sites as S
    seeds = S.load(a.site).get("kw_seeds") or {}
    regions = seeds.get("regions") or []
    if not regions:
        print("REGION_KW_OK=unset（kw_seeds.regions に拠点の地域がありません。拠点の無い地域は狙わない）")
        return 0
    inds = seeds.get("priority") or seeds.get("industries") or []
    if not inds:
        print("REGION_KW_OK=unset（kw_seeds に業種がありません）")
        return 0
    cands = candidates(a.site, regions, inds, S.load(a.site).get("owns") or list(CORE))
    picks, held = [], []
    for k in cands:
        if len(picks) >= a.limit:
            break
        lv, reasons = KG.judge(k, a.site, use_gsc=True)
        if lv == 0:
            picks.append(k)
        else:
            held.append((k, lv))
    print(f"■ {a.site}: 地域 {'・'.join(regions)} × 業種 {len(inds)} → サジェストの候補 {len(cands)}件")
    for k in picks:
        print(f"   積む: {k}")
    for k, lv in held[:10]:
        print(f"   見送り: {k}（kw_guard {lv}）")
    if a.append and picks:
        with (ROOT / "docs" / f"kw-region-{a.site}.md").open("a", encoding="utf-8") as f:
            f.write(f"\n## {date.today().isoformat()}\n" + "".join(f"- {k}\n" for k in picks))
        import hub_client
        if hub_client.enabled():
            r = hub_client.add_kw(a.site, picks) or {}
            print(f"管制塔の台帳へ {r.get('added', 0)}件を追加しました（渡した{len(picks)}件）" if r.get("ok")
                  else f"（管制塔が追加を受け付けませんでした: {r.get('error', '応答なし')}）")
        else:
            print("（管制塔が未接続のため台帳への追加はスキップ）")
    print(f"REGION_KW_OK={'yes' if picks else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
