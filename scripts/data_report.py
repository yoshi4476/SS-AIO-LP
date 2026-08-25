# -*- coding: utf-8 -*-
"""自社の運用データから調査レポートを組み立てる

被リンクは買えない。集まる理由を作るしかない。そのために一番強いのは、
他社が持っていない自社の運用データを集計して公開することだが、
数字を扱う以上、根拠のない集計は出せない。

この道具は、書き手が数字を作れないようにしてある。
  ・母数と集計期間が無ければ何も出力しない（景品表示法）
  ・件数が少なすぎる区分は「参考値」と明記する
  ・元データの行数と、除外した行数を必ずレポートに書く

使い方:
    python scripts/data_report.py --spec           # 何を出せばいいか表示
    python scripts/data_report.py <CSV>            # 集計だけ見る
    python scripts/data_report.py <CSV> --write    # 記事の下書きを作る
"""
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 集計に必要な列。1つでも欠けたら止める
REQUIRED = {
    "store_id": "店舗を識別する値（社名や住所は入れない）",
    "industry": "業種（飲食／美容／クリニック など）",
    "start_ym": "運用開始の年月（2025-04 の形）",
    "end_ym": "運用終了または集計時点の年月",
}
# あるほど良い列。無ければその切り口の集計を飛ばす
OPTIONAL = {
    "reviews_before": "運用開始時の口コミ件数",
    "reviews_after": "集計時点の口コミ件数",
    "rating_before": "運用開始時の評価（1〜5）",
    "rating_after": "集計時点の評価（1〜5）",
    "reply_rate": "口コミへの返信率（0〜100の数値）",
    "posts_per_month": "最新情報の投稿本数（月平均）",
    "photos_added": "追加した写真の枚数",
}
# この件数を下回る区分は参考値として出す。少数の平均は誤解を生む
MIN_N = 30


def spec():
    print("■ G-ranから出してもらうデータ（CSV・1行1店舗）\n")
    print("  必須の列")
    for k, v in REQUIRED.items():
        print(f"    {k:<18}{v}")
    print("\n  あると集計できる列（無い分は飛ばします）")
    for k, v in OPTIONAL.items():
        print(f"    {k:<18}{v}")
    print(f"""
  条件
    ・店名・住所・担当者名は入れないでください（個人情報・守秘）
    ・集計期間を1行目のコメント、またはファイル名に入れてください
    ・{MIN_N}件未満の業種は「参考値」として扱います

  例:
    store_id,industry,start_ym,end_ym,reviews_before,reviews_after,reply_rate
    A0001,飲食,2025-04,2026-07,12,58,92
    A0002,美容,2025-06,2026-07,31,77,100
""")


def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def load(path):
    rows, skipped, sample = [], 0, 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            # 雛形の記入例。消し忘れたまま集計すると、架空の数字が記事に出る
            if str(r.get("store_id", "")).strip().upper().startswith("SAMPLE"):
                sample += 1
                continue
            if all(str(r.get(k, "")).strip() for k in REQUIRED):
                rows.append(r)
            else:
                skipped += 1
    if sample and not rows:
        raise SystemExit(
            f"記入例が{sample}行あるだけで、実データがありません。\n"
            "  docs/meo-data-template.csv の SAMPLE 行を消して、"
            "実際の店舗データを入れてください")
    if sample:
        print(f"  記入例{sample}行を除外しました（store_idがSAMPLEで始まる行）")
    return rows, skipped


def summarize(rows):
    """業種ごとに、出せる指標だけを集計する"""
    by = defaultdict(list)
    for r in rows:
        by[str(r["industry"]).strip() or "その他"].append(r)

    out = []
    for ind, rs in sorted(by.items(), key=lambda x: -len(x[1])):
        rec = {"industry": ind, "n": len(rs), "reference": len(rs) < MIN_N}
        b = [num(r.get("reviews_before")) for r in rs]
        a = [num(r.get("reviews_after")) for r in rs]
        pair = [(x, y) for x, y in zip(b, a) if x is not None and y is not None]
        if pair:
            rec["reviews_n"] = len(pair)
            rec["reviews_median_before"] = statistics.median(x for x, _ in pair)
            rec["reviews_median_after"] = statistics.median(y for _, y in pair)
        rr = [num(r.get("reply_rate")) for r in rs]
        rr = [x for x in rr if x is not None]
        if rr:
            rec["reply_rate_n"] = len(rr)
            rec["reply_rate_median"] = statistics.median(rr)
        out.append(rec)
    return out


def draft(rows, skipped, stats, period):
    """記事の下書き。数字はここで作らず、集計結果だけを流し込む"""
    tot = len(rows)
    lines = [
        "---",
        "title: 【調査】MEO運用データから見た口コミの増え方",
        "description: 自社で運用した店舗のデータを業種別に集計しました。"
        "口コミ件数の中央値と返信率の実態を、母数と集計期間つきで公開します。",
        "slug: meo-unyou-data-chosa",
        "keyword: MEO 口コミ 増え方 データ",
        "category: meo",
        f"date: {period['today']}",
        f"modified: {period['today']}",
        "depth: standard",
        "score: 0   # 採点前。90点未満はビルド対象外",
        "---",
        "",
        f"**自社で運用した{tot:,}店舗のデータを集計しました。**"
        f"集計期間は{period['label']}です。",
        "",
        f'<p class="freshness">※ {period["today"]}時点の集計です。</p>',
        "",
        "## この調査の前提",
        "",
        f"**対象は{tot:,}店舗、集計期間は{period['label']}です。**",
        "",
        f"- 元データ: {tot + skipped:,}行のうち、必須項目が揃った{tot:,}行を対象",
        f"- 除外: {skipped:,}行（項目の欠けがあるもの）",
        "- 店名・住所・担当者名は含まれていません",
        f"- {MIN_N}件未満の業種は参考値として扱っています",
        "",
        "## 業種別の集計",
        "",
        "| 業種 | 店舗数 | 口コミ中央値（開始時→集計時） | 返信率の中央値 |",
        "|:--|--:|:--|--:|",
    ]
    for s in stats:
        name = s["industry"] + ("（参考値）" if s["reference"] else "")
        if "reviews_median_before" in s:
            rev = (f"{s['reviews_median_before']:.0f}件 → "
                   f"{s['reviews_median_after']:.0f}件")
        else:
            rev = "—"
        rr = f"{s['reply_rate_median']:.0f}%" if "reply_rate_median" in s else "—"
        lines.append(f"| {name} | {s['n']:,} | {rev} | {rr} |")
    lines += [
        "",
        "**平均ではなく中央値を出しています。** 平均は極端に多い店舗に引きずられ、"
        "実態から離れるためです。",
        "",
        "## この数字の読み方",
        "",
        "（ここに、現場で何が起きていたかの説明を書く。"
        "数字だけでは引用されても意味が伝わらない）",
        "",
        "## 調査の限界",
        "",
        "**この集計は自社が運用した店舗に限られます。** "
        "運用を依頼する時点で一定の意欲がある事業者に偏っているため、"
        "全業界の平均としては読めません。",
        "",
    ]
    return "\n".join(lines) + "\n"


def main():
    if "--spec" in sys.argv or len(sys.argv) < 2:
        spec()
        return
    path = Path(sys.argv[1])
    if not path.is_file():
        raise SystemExit(f"{path} がありません")

    rows, skipped = load(path)
    if not rows:
        raise SystemExit("必須項目が揃った行がありません。--spec で必要な列を確認してください")

    ym = sorted({str(r["start_ym"]).strip() for r in rows} |
                {str(r["end_ym"]).strip() for r in rows})
    period = {"label": f"{ym[0]}〜{ym[-1]}", "today": __import__("datetime").date.today().isoformat()}

    stats = summarize(rows)
    print(f"■ 対象 {len(rows):,}店舗（除外 {skipped:,}行）/ 集計期間 {period['label']}\n")
    print(f"  {'業種':<12}{'件数':>7}  {'口コミ中央値':<20}{'返信率':>8}")
    for s in stats:
        rev = (f"{s.get('reviews_median_before', 0):.0f}→{s.get('reviews_median_after', 0):.0f}件"
               if "reviews_median_before" in s else "—")
        rr = f"{s['reply_rate_median']:.0f}%" if "reply_rate_median" in s else "—"
        mark = "（参考値）" if s["reference"] else ""
        print(f"  {s['industry'][:10]:<12}{s['n']:>7,}  {rev:<20}{rr:>8}  {mark}")

    if "--write" not in sys.argv:
        print("\n  記事の下書きを作るには --write を付けてください")
        return
    out = ROOT / "articles" / "meo-unyou-data-chosa.md"
    if out.exists():
        raise SystemExit(f"{out} が既にあります。消すか、別名にしてください")
    out.write_text(draft(rows, skipped, stats, period), encoding="utf-8", newline="")
    print(f"\n  作成: {out}")
    print("  「この数字の読み方」を書いてから、機械採点と品質採点にかけてください")


if __name__ == "__main__":
    main()
