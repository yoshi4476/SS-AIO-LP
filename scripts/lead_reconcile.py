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
ACK_FILE = ROOT / "data" / "lead_reconcile_ack.json"
try:
    import json as _json
    ACKED = _json.loads(ACK_FILE.read_text(encoding="utf-8"))
except Exception:
    ACKED = {}


def ga4_by_day(prop, start, end):
    import gcreds
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (DateRange, Dimension, Filter, FilterExpression,
                                                    Metric, RunReportRequest)
    creds = gcreds.load(ROOT / "indexing-service-account.json", ["https://www.googleapis.com/auth/analytics.readonly"])
    rep = BetaAnalyticsDataClient(credentials=creds).run_report(RunReportRequest(
        property=f"properties/{prop}", date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
        dimensions=[Dimension(name="date"), Dimension(name="eventName"), Dimension(name="pagePath")],
        metrics=[Metric(name="eventCount")],
        dimension_filter=FilterExpression(filter=Filter(field_name="eventName",
                                                        in_list_filter=Filter.InListFilter(values=list(EVENTS)))),
        limit=5000))
    return count_rows([(r.dimension_values[0].value, r.dimension_values[1].value,
                        r.dimension_values[2].value, int(r.metric_values[0].value)) for r in rep.rows])


def is_lead(ev, path):
    """問い合わせとして数える送信か。
    form_submit は GA4 がページ上のどのフォームでも出す。トップや記事の「30秒のサイト診断」
    （URLを入れて /lp/ へ飛ぶだけ）も form_submit になり、2026-10-02 に診断の入力2件を
    「台帳に無い問い合わせ」と誤って報告した。form_submit は問い合わせページのものだけ数える"""
    if ev in ("lead_capture", "generate_lead"):
        return True
    return ev == "form_submit" and "/contact" in (path or "")


def count_rows(rows):
    """(date, eventName, pagePath, count) から日ごとの件数。
    同じ送信で form_submit と lead_capture が両方出るので、足さずに多い方を取る"""
    per = collections.defaultdict(lambda: collections.Counter())
    for d, ev, path, n in rows:
        if is_lead(ev, path):
            per[f"{d[:4]}-{d[4:6]}-{d[6:]}"][ev] += n
    return {d: max(v.values()) for d, v in per.items() if v}


def selftest():
    """実際に誤った例で、数え方を確かめる"""
    cases = [
        ([("20260928", "form_submit", "/", 1)], {}),                                        # トップの診断入力
        ([("20260930", "form_submit", "/ai-marketing/fudousan-hankyou-konai/", 1)], {}),    # 記事内の診断入力
        ([("20260904", "form_submit", "/contact/", 2), ("20260904", "lead_capture", "/contact/", 1)],
         {"2026-09-04": 2}),                                                                # 問い合わせ（足さない）
        ([("20260909", "generate_lead", "/contact", 1)], {"2026-09-09": 1}),
        ([("20260918", "lead_capture", "/diagnosis/meo/", 1)], {"2026-09-18": 1}),           # 診断結果の送付依頼
    ]
    bad = [(rows, want, count_rows(rows)) for rows, want in cases if count_rows(rows) != want]
    for rows, want, got in bad:
        print(f"  NG {rows} → {got}（正しくは {want}）")
    print(f"LEAD_SELFTEST={'ok' if not bad else 'ng'}")
    return 0 if not bad else 1


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
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
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
        # 調べて記録が見つからなかった日（ACK）は毎週くり返し知らせない
        ack = set(ACKED.get(sid, {}))
        miss = [d for d, n in sorted(ga.items()) if n > 0 and led[sid].get(d, 0) == 0 and d not in ack]
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
