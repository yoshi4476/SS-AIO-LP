# -*- coding: utf-8 -*-
"""AI検索に引用されているかを、GSCの実データから推定する

使い方: python scripts/ai_citation_check.py

AI Overviewでの引用有無を直接返すAPIは無い（GSCの生成AIレポートも
インプレッションのみ）。有料ツールも使わない前提なので、実データの
「順位は高いのにクリックされない」という歪みから推定する。

判定の考え方:
  順位ごとのCTRには経験的な相場がある（1位で約28%、3位で約11%）。
  順位に対して実測CTRが極端に低いページは、答えがAI回答に取られて
  クリックまで到達していない可能性が高い。逆に想定通りのCTRなら、
  引用の有無にかかわらず流入は確保できている。

これは推定であって観測ではない。断定はしない（結果に「推定」と明記する）。
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RANKS = ROOT / "data" / "ranks"
OUT = ROOT / "data" / "ai_citations"

# 順位別のCTRの目安（各種公開調査の中央値。厳密な値ではなく歪みの検出に使う）
CTR_BASE = {1: 28.0, 2: 15.0, 3: 11.0, 4: 8.0, 5: 7.0,
            6: 5.0, 7: 4.0, 8: 3.5, 9: 3.0, 10: 2.5}
MIN_IMP = 10          # これ未満は偶然に振られるので判定しない
LOW_RATIO = 0.35      # 目安CTRの35%未満なら「取られている」疑い


def expected_ctr(pos):
    return CTR_BASE.get(int(round(pos)), 2.0)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"date": date.today().isoformat(), "method": "GSCのCTR歪みからの推定", "sites": {}}

    for cfg in sites_mod.load_all().values():
        sid = cfg["id"]
        f = RANKS / f"{sid}.json"
        if not f.is_file():
            print(f"■ {cfg['name']}: 順位の記録がありません"
                  "（先に python scripts/rank_track.py を実行してください）")
            continue
        hist = json.loads(f.read_text(encoding="utf-8"))
        rows = hist[sorted(hist)[-1]]

        judged, taken, ok, thin = [], [], [], 0
        for r in rows:
            if r["pos"] > 10:
                continue
            if r["imp"] < MIN_IMP:
                thin += 1
                continue
            exp = expected_ctr(r["pos"])
            ratio = (r["ctr"] / exp) if exp else 1
            item = {**r, "expected_ctr": exp, "ratio": round(ratio, 2)}
            judged.append(item)
            (taken if ratio < LOW_RATIO else ok).append(item)

        print(f"\n■ {cfg['name']}")
        if not judged:
            print(f"   判定できるKWがありません（10位以内かつ表示{MIN_IMP}回以上が0件"
                  f"／表示不足で除外 {thin}件）")
            print("   → まず順位を上げる段階です。AI引用の判定はその後になります")
        else:
            print(f"   判定対象 {len(judged)}件 ／ 引用に取られている疑い {len(taken)}件")
            for r in sorted(taken, key=lambda r: -r["imp"])[:5]:
                print(f"     {r['pos']:4.1f}位 CTR{r['ctr']:5.2f}%（目安{r['expected_ctr']:.1f}%）"
                      f" 表示{r['imp']:4d}  {r['kw'][:26]}")
        result["sites"][sid] = {"judged": len(judged), "suspect_taken": len(taken),
                                "healthy": len(ok), "too_thin": thin,
                                "items": taken[:20]}

    p = OUT / f"{date.today():%Y-%m}.json"
    p.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n記録: {p.relative_to(ROOT).as_posix()}")
    print("※ AI引用の有無を直接観測する手段は無いため、CTRの歪みからの推定です")


if __name__ == "__main__":
    main()
