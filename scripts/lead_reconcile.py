# -*- coding: utf-8 -*-
"""フォームの送信（GA4）と、管制塔の「問い合わせ」台帳を日ごとに突き合わせる

**なぜ要るか**: AI集客ラボのフォームは管制塔（GAS）に送り、失敗したらメール（Resend）へ落とす。
メールへ落ちた問い合わせは台帳に残らない。2026-09 に、GA4 では 9/4・9/7 に送信があるのに
台帳に行が無く、問い合わせ件数が2つの記録で食い違っていた（GAS が本文なしの送信を弾いていた）。
取りこぼしは、落ちた先のメールを誰かが見るまで気づけない。

GA4 の件数は「その日の form_submit / lead_capture / generate_lead のうち最大」で数える
（同じ送信で両方が飛ぶため足さない。0.1節）。台帳は同じ人の24時間以内の再送信を1行にまとめるので、
GA4 の方が多い日があっても取りこぼしとは限らない。**台帳が0でGA4が1以上の日**だけを要対応にする。

    python scripts/lead_reconcile.py [--days 28]
出す印: LEADS_OK=yes|no（検査が動かなかったときだけ終了コード1）
"""
import argparse
import collections
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
EVENTS = ("form_submit", "lead_capture", "generate_lead")


def ga4_by_day(prop, start, end):
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Filter, FilterExpression,
                                                    Metric, RunReportRequest)
    creds = gcreds.load(ROOT / "indexing-service-account.json", ["https://www.googleapis.com/auth/analytics.readonly"])
    rep = BetaAnalyticsDataClient(credentials=creds).run_report(RunReportRequest(
        property=f"properties/{prop}", date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        dimensions=[Dimension(name="date"), Dimension(name="eventName")], metrics=[Metric(name="eventCount")],
        dimension_filter=FilterExpression(filter=Filter(field_name="eventName",
                                                        in_list_filter=Filter.InListFilter(values=list(EVENTS)))),
        limit=1000))
    per = collections.defaultdict(dict)
    for r in rep.rows:
        d, ev = r.dimension_values[0].value, r.dimension_values[1].value
        per[f"{d[:4]}-{d[4:6]}-{d[6:]}"][ev] = int(r.metric_values[0].value)
    return {d: max(v.values()) for d, v in per.items()}


def ledger_by_site(start):
    import hub_sheets as H
    import re
    # 台帳の表示名は「コーポレート (corp.7senses.co.jp)」のように、サイト一覧の名前と一致しない
    # ことがある。括弧の中のドメインで引く（名前で引くと全行が「不明」になった）
    by_dom, by_name = {}, {}
    for r in H.rows("サイト一覧", 3):
        if len(r) >= 3:
            by_dom[r[2].strip()] = r[0]
            by_name[r[1].strip()] = r[0]

    def sid_of(label):
        m = re.search(r"\(([^)]+)\)", label or "")
        return by_dom.get(m.group(1).strip()) if m else by_name.get((label or "").strip())
    base = date(1899, 12, 30)
    out = collections.defaultdict(collections.Counter)
    for r in H.rows("問い合わせ", 2):
        try:
            d = base + timedelta(days=float(r[0]))
        except (ValueError, IndexError):
            continue
        if d >= start:
            out[sid_of(r[1] if len(r) > 1 else "") or "?"][d.isoformat()] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=28)
    a = ap.parse_args()
    import sites as S
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=a.days - 1)
    try:
        led = ledger_by_site(start)
    except Exception as e:
        print(f"台帳を読めません（{str(e)[:80]}）")
        return 1
    print(f"■ フォーム送信（GA4）と問い合わせ台帳（{start}〜{end}）\n")
    bad = []
    for sid, cfg in S.load_all().items():
        prop = cfg.get("ga4_property_id")
        # 自前の台帳を持つサイト（補助金の form-endpoint.gs など）は管制塔と突き合わせない
        if not prop or cfg.get("lead_hub") is False:
            continue
        try:
            ga = ga4_by_day(str(prop), start, end)
        except Exception as e:
            print(f"  {sid}: GA4 を読めません（{str(e)[:60]}）")
            continue
        miss = [d for d, n in sorted(ga.items()) if n > 0 and led[sid].get(d, 0) == 0]
        print(f"  {cfg.get('name', sid)}: GA4 の送信 {sum(ga.values())}件（{len(ga)}日） / 台帳 {sum(led[sid].values())}行")
        for d in miss:
            bad.append(f"要対応: {cfg.get('name', sid)} — {d} に GA4 では送信{ga[d]}件あるのに台帳に行がありません"
                       "（メールにだけ届いた可能性。info.ai の受信箱を確認し、台帳に書き足す）")
            print("  " + bad[-1])
    if led.get("?"):
        print(f"  サイト名を判定できない行 {sum(led['?'].values())}件")
    print(f"LEADS_OK={'no' if bad else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
