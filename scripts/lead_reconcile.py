# -*- coding: utf-8 -*-
"""フォームの送信（GA4）と、管制塔の「問い合わせ」台帳を日ごとに突き合わせる

**なぜ要るか**: AI集客ラボのフォームは管制塔（GAS）に送り、失敗したらメール（Resend）へ落とす。
メールへ落ちた問い合わせは台帳に残らない。2026-09 に、GA4 では 9/4・9/7 に送信があるのに
台帳に行が無く、問い合わせ件数が2つの記録で食い違っていた（GAS が本文なしの送信を弾いていた）。
取りこぼしは、落ちた先のメールを誰かが見るまで気づけない。

GA4 の件数は「その日の lead_capture / generate_lead のうち多い方」で数える（コーポレートは同じ送信で
両方が飛ぶため足さない。0.1節）。**form_submit は数えない**: ページを移って送るフォーム（AI集客ラボの
/contact/・/lp/・/download/）では site.js の form_submit と GA4 の拡張計測（フォームの操作）の form_submit が
1回ずつ出て、問い合わせ1回が2件になる。/contact/ の 9/4・9/7・10/7 はどれも form_submit 2・lead_capture 1 で、
以前の数え方（3つのうち最大）は2件と数え、突き合わせも送信数も2倍になっていた（2026-10-07 判明）。
台帳は同じ人の24時間以内の再送信を1行にまとめるので、GA4 の方が多い日があっても取りこぼしとは限らない。
**台帳が0でGA4が1以上の日**だけを要対応にする。

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
EVENTS = ("lead_capture", "generate_lead")
# 2026-09-25 の直し（e2003eabd）より前の診断・サイト診断は、結果を出した時点でも lead_capture を出していた（連絡先は
# 受け取っていない。完了の記録 diagnosis_complete / site_audit_complete と1対1で出る）。その日・そのページの完了の数だけ
# lead_capture から引き、残り（結果の送付を頼んだ＝連絡先を送った分）だけを数える。引かないと、8月の診断の完了4件を
# 「台帳に行が無い送信」と取りこぼし扱いにしていた（2026-10-10 判明）
COMPLETES = ("diagnosis_complete", "site_audit_complete")
COMPLETE_FIXED = "20260925"
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
                                                        in_list_filter=Filter.InListFilter(values=list(EVENTS + COMPLETES)))),
        limit=5000))
    rows = [(r.dimension_values[0].value, r.dimension_values[1].value,
             r.dimension_values[2].value, int(r.metric_values[0].value)) for r in rep.rows]
    ga4_by_day.rows = rows          # 取りこぼした日に「どのページの送信か」を出すため残す
    return count_rows(rows)


def pages_on(rows, day):
    """その日の問い合わせの送信が、どのページから来たか（件数つき）"""
    key = day.replace("-", "")
    c = collections.Counter()
    for d, ev, path, n in rows:
        if d == key and is_lead(ev, path):
            c[path or "(不明)"] += n
    return "・".join(f"{p}（{n}）" for p, n in c.most_common(5))


def is_lead(ev, path=None):
    """問い合わせとして数える送信か。各サイトが送れたときに1回だけ出す lead_capture / generate_lead だけ。
    form_submit は数えない。GA4 の拡張計測がページ上のどのフォームでも出すため、ページを移るフォームでは
    site.js の分と合わせて問い合わせ1回が2件になり（2026-10-07）、「30秒のサイト診断」（URLを入れて
    /lp/ へ移るだけ）も form_submit になる（2026-10-02 に診断の入力2件を問い合わせと誤って報告した）。
    path は呼び出し側との互換のために受けるだけで、判定には使わない"""
    return ev in EVENTS


def count_rows(rows):
    """(date, eventName, pagePath, count) から日ごとの件数。
    コーポレートは同じ送信で generate_lead と lead_capture が両方出るので、足さずに多い方を取る"""
    done = collections.Counter((d, path) for d, ev, path, n in rows for _ in range(n)
                               if ev in COMPLETES and d < COMPLETE_FIXED)
    per = collections.defaultdict(lambda: collections.Counter())
    for d, ev, path, n in rows:
        if not is_lead(ev, path):
            continue
        if ev == "lead_capture" and done[(d, path)]:
            k = min(n, done[(d, path)])
            done[(d, path)] -= k
            n -= k
        if n > 0:
            per[f"{d[:4]}-{d[4:6]}-{d[6:]}"][ev] += n
    return {d: max(v.values()) for d, v in per.items() if v}


def selftest():
    """実際に誤った例で、数え方を確かめる"""
    cases = [
        ([("20260928", "form_submit", "/", 1)], {}),                                        # トップの診断入力
        ([("20260930", "form_submit", "/ai-marketing/fudousan-hankyou-konai/", 1)], {}),    # 記事内の診断入力
        # 問い合わせ1回。form_submit は site.js と GA4 の拡張計測が1回ずつ出す（AI集客ラボ /contact/ の実例）
        ([("20260904", "form_submit", "/contact/", 2), ("20260904", "lead_capture", "/contact/", 1),
          ("20260904", "lead_form", "/contact/", 1)], {"2026-09-04": 1}),
        # コーポレートの問い合わせ1回（generate_lead と lead_capture が両方出る。足さない）
        ([("20261005", "form_submit", "/contact", 1), ("20261005", "generate_lead", "/contact", 1),
          ("20261005", "lead_capture", "/contact", 1)], {"2026-10-05": 1}),
        ([("20260909", "generate_lead", "/contact", 1)], {"2026-09-09": 1}),
        ([("20260918", "lead_capture", "/diagnosis/meo/", 1)], {"2026-09-18": 1}),           # 診断結果の送付依頼
        # 9/25 より前の診断の完了（結果を見ただけ・連絡先なし）。AI集客ラボの 8/21 /diagnosis/aio/ と 8/4 /site-audit/ の実例
        ([("20260821", "diagnosis_complete", "/diagnosis/aio/", 1), ("20260821", "lead_capture", "/diagnosis/aio/", 1),
          ("20260821", "lead_diagnosis", "/diagnosis/aio/", 1)], {}),
        ([("20260804", "site_audit_complete", "/site-audit/", 1), ("20260804", "lead_capture", "/site-audit/", 1)], {}),
        # 完了より lead_capture が多い日は、その差が結果の送付の依頼（連絡先を送った分）
        ([("20260901", "diagnosis_complete", "/diagnosis/meo/", 1), ("20260901", "lead_capture", "/diagnosis/meo/", 2)],
         {"2026-09-01": 1}),
        # 9/25 の直し以降は、完了では lead_capture を出さない。同じ日に完了と送付があれば送付の1件
        ([("20261001", "diagnosis_complete", "/tools/diagnosis/aio/", 1),
          ("20261001", "lead_capture", "/tools/diagnosis/aio/", 1)], {"2026-10-01": 1}),
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
    ap.add_argument("--fix", action="store_true",
                    help="サイト名が（不明）の行に、その日 GA4 で送信があった1社の名前を入れる（1対1で合う日だけ）")
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
    bad, unread = [], []
    fixable = collections.defaultdict(list)       # 日 → その日に台帳に行が無く、（不明）の行がある社
    for sid, cfg in S.load_all().items():
        prop = cfg.get("ga4_property_id")
        # 問い合わせを管制塔へ送らず自前の台帳だけに入れる社（lead_hub: false）は突き合わせない
        if not prop or cfg.get("lead_hub") is False:
            continue
        try:
            ga = ga4_by_day(str(prop), start, end)
        except Exception as e:
            print(f"  {sid}: GA4 を読めません（{str(e)[:60]}）")
            unread.append(sid)
            continue
        # 調べて記録が見つからなかった日（ACK）は毎週くり返し知らせない
        ack = set(ACKED.get(sid, {}))
        miss = [d for d, n in sorted(ga.items()) if n > 0 and led[sid].get(d, 0) == 0 and d not in ack]
        print(f"  {cfg.get('name', sid)}: GA4 の送信 {sum(ga.values())}件（{len(ga)}日） / 台帳 {sum(led[sid].values())}行")
        for d in miss:
            src = pages_on(getattr(ga4_by_day, "rows", []), d)
            where = f"（送信したページ: {src}）" if src else ""
            unknown = led.get("?", {}).get(d, 0)
            if unknown:
                fixable[d].append((sid, cfg.get("name", sid), len(bad)))
                # 行はあるがサイト名が「（不明）」の日。補助金のサービスページのフォームはサイトIDを送っておらず、
                # 10/1 の問い合わせがこの形で残っていた（2026-10-07）。「メールにだけ届いた」と言うと探す先を誤る
                bad.append(f"要対応: {cfg.get('name', sid)} — {d} に GA4 では送信{ga[d]}件。この社の行は無く、"
                           f"同じ日にサイト名を判定できない行が{unknown}行あります{where}"
                           "（その行のサイト名を直す。フォームがサイトIDを送っているかも確かめる）")
            else:
                bad.append(f"要対応: {cfg.get('name', sid)} — {d} に GA4 では送信{ga[d]}件あるのに台帳に行がありません"
                           + where + "（メールにだけ届いた可能性。info.ai の受信箱を確認し、台帳に書き足す）")
            print("  " + bad[-1])
    if a.fix:
        # 根拠が1対1のときだけ直す: その日の（不明）の行がちょうど1行で、行の無い送信がある社もちょうど1社
        import hub_client as HC
        fixed = set()
        for d, who in sorted(fixable.items()):
            if len(who) != 1 or led.get("?", {}).get(d, 0) != 1:
                print(f"  {d}: 直さない（（不明）の行 {led.get('?', {}).get(d, 0)}行・候補 {len(who)}社。1対1ではない）")
                continue
            sid, name, idx = who[0]
            try:
                r = HC._post({"action": "lead_fix_site", "day": d, "site": sid}) or {}
            except Exception as e:                    # 管制塔につながらない回は直さずに知らせるだけ（照合は止めない）
                r = {"error": f"管制塔につながりません（{type(e).__name__}）"}
            print(f"  {d}: サイト名を「{name}」に直しました" if r.get("ok") else f"  {d}: 直せませんでした（{r.get('error', '')}）")
            if r.get("ok"):
                fixed.add(idx)
                led["?"][d] -= 1
        bad = [b for i, b in enumerate(bad) if i not in fixed]
    if led.get("?") and sum(led["?"].values()):
        print(f"  サイト名を判定できない行 {sum(led['?'].values())}件")
    if unread and not bad:
        # 読めなかったサイトを「食い違いなし」に数えない（GA4 が落ちた日も LEADS_OK=yes と出ていた）
        print(f"照合できなかったサイト: {', '.join(unread)}")
        print("LEADS_OK=unknown")
        return 1
    print(f"LEADS_OK={'no' if bad else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
