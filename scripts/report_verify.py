# -*- coding: utf-8 -*-
"""レポートに載せる数字を、別の方法で測り直して照合する門。

**なぜ要るか**: 1つの測り方の結果をそのまま載せ、実際に誤った。
「60語」は上限で切った数だったし、「CV 0件」は数えるイベントを
間違えていた（リードは4件あった）。どちらも30秒の再確認で防げた。

CLAUDE.md 0.1節の「数字を1つでも出すなら、この4つを必ず通す」を、
人が覚えておく決まりではなく**機械が止める検査**にする。

    python scripts/report_verify.py --month 2026-08
    python scripts/report_verify.py --month 2026-09 --through 2026-09-24

  終了コード 0 … 検査が動いた（結果は VERIFY_OK= で判定する）
  終了コード 1 … 検査そのものが動かなかった
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# リードの傘イベントと、その内訳。**足し算が合うことを毎回確かめる**
LEAD_UMBRELLA = "lead_capture"
LEAD_PARTS = ("lead_form", "lead_diagnosis", "lead_site_audit")
# 指名とみなす語。ここに載っていない社名・人名が増えたら足すこと
NAMED = ("7senses", "セブンセンシズ", "ai集客ラボ", "aiシュウキャク", "原口")


def _gsc(site, start, end, dims=None, limit=1):
    import gcreds
    from googleapiclient.discovery import build
    creds = gcreds.load(ROOT / "indexing-service-account.json",
                        ["https://www.googleapis.com/auth/webmasters.readonly"])
    sc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    body = {"startDate": start, "endDate": end, "rowLimit": limit}
    if dims:
        body["dimensions"] = dims
    return sc.searchanalytics().query(siteUrl=site, body=body).execute()


def _ga_events(prop, start, end):
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Metric,
                                                    RunReportRequest)
    import gcreds
    creds = gcreds.load(ROOT / "indexing-service-account.json",
                        ["https://www.googleapis.com/auth/analytics.readonly"])
    ga = BetaAnalyticsDataClient(credentials=creds)
    rep = ga.run_report(RunReportRequest(
        property=f"properties/{prop}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="eventCount")], limit=300))
    return {r.dimension_values[0].value: int(r.metric_values[0].value) for r in rep.rows}


def check(month, through=None):
    import monthly_report as M

    start = f"{month}-01"
    end = through or M.month_end(month)
    # monthly_report --site と同じサイトを見る。.env の GSC_SITE_URL は AI集客ラボ固定で、
    # 他社のレポートを AI集客ラボの数字で検算していた
    site = f"https://{M.site_cfg()['domain']}/"
    bad, note = [], []

    # ── 1. 合計を2通りで出す（次元なし と query次元）────────────
    tot = (_gsc(site, start, end).get("rows") or [{}])[0]
    t_imp = int(tot.get("impressions", 0))
    t_clicks = int(tot.get("clicks", 0))

    rows = _gsc(site, start, end, ["query"], 5000).get("rows", [])
    q_imp = sum(int(r["impressions"]) for r in rows)
    q_clicks = sum(int(r["clicks"]) for r in rows)
    cover = (q_imp / t_imp * 100) if t_imp else 0

    print(f"■ 検索（{start} 〜 {end}）")
    print(f"   次元なしの合計   : 表示 {t_imp:,} / クリック {t_clicks:,}")
    print(f"   query次元の合計  : 表示 {q_imp:,} / クリック {q_clicks:,}（{len(rows)}語）")
    print(f"   query次元のカバー率: {cover:.0f}%")

    if q_imp > t_imp:
        bad.append("query次元の合計が、次元なしの合計を超えています（数え方の誤り）")
    if cover < 99:
        note.append(f"query次元は全体の{cover:.0f}%しか返しません"
                    f"（検索数の少ない語は返らない仕様）。"
                    f"**語ごとの数を『全体』として書かないこと**")

    # ── 2. 上限で切れていないか ────────────────────────
    if len(rows) >= 5000:
        bad.append("取得が上限5000に達しています。語数を『実数』として書けません")
    print(f"   上限で切れていないか: {'OK' if len(rows) < 5000 else '★切れている'}")

    # ── 3. 指名検索を分けているか ──────────────────────
    named = [r for r in rows if any(n.lower() in r["keys"][0].lower() for n in NAMED)]
    n_clicks = sum(int(r["clicks"]) for r in named)
    share = (n_clicks / q_clicks * 100) if q_clicks else 0
    print(f"   指名検索         : {len(named)}語 / クリック {n_clicks}"
          f"（query次元のクリックの{share:.0f}%）")
    if share >= 20:
        note.append(f"クリックの{share:.0f}%が指名検索です。"
                    f"**記事の力と分けて書くこと**（合計だけで語らない）")

    # ── 4. リードの内訳が合うか ───────────────────────
    # GA4未設定の社は None。そのまま API に渡すと落ちるため、リードの検算だけ飛ばす
    pid = M.ga4_property()
    ev = _ga_events(pid, start, end) if pid else {}
    umb = ev.get(LEAD_UMBRELLA, 0)
    parts = {k: ev.get(k, 0) for k in LEAD_PARTS}
    s_parts = sum(parts.values())
    print()
    print(f"■ リード（{start} 〜 {end}）")
    if not pid:
        print("   GA4未設定のため、リードの検算は飛ばします")
    print(f"   {LEAD_UMBRELLA}（傘）: {umb}")
    for k, v in parts.items():
        print(f"     └ {k}: {v}")
    print(f"   内訳の合計: {s_parts}")
    print(f"   form_submit（フォーム送信のみ）: {ev.get('form_submit', 0)}")

    if umb != s_parts:
        bad.append(f"リードの傘（{umb}）と内訳の合計（{s_parts}）が一致しません。"
                   f"数え漏れか、イベントの追加があります")
    if umb and ev.get("form_submit", 0) == 0:
        note.append(f"フォーム送信は0ですが、リードは{umb}件あります。"
                    f"**『CV 0件』と書かないこと**（診断・監査からの獲得を落とします）")
    if ev.get("form_submit", 0) and umb:
        note.append("form_submit と lead_capture を足さないこと（同時に飛びます）")

    # ── 5. 判定 ──────────────────────────────────
    print()
    for b in bad:
        print(f"   ★ {b}")
    for n in note:
        print(f"   ※ {n}")
    ok = not bad
    print()
    print(f"VERIFY_OK={'yes' if ok else 'no'}")
    print(f"VERIFY_NOTES={len(note)}")
    return ok, bad, note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="YYYY-MM")
    ap.add_argument("--through", help="YYYY-MM-DD（当月の途中まで）")
    a = ap.parse_args()
    try:
        check(a.month, a.through)
    except Exception as e:
        print(f"検査そのものが動きませんでした: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
