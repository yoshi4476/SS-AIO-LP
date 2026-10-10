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
    """日ごと・サイトごとの台帳の行数（照合用。売り込み・テストの行も数える。GA4 の送信にはそれらも入るため）"""
    out = collections.defaultdict(collections.Counter)
    for x in ledger_rows(start):
        out[x["sid"]][x["day"]] += 1
    return out


# ── 問い合わせの件数（台帳で数える）──────────────────────────────────
# 問い合わせの件数は、管制塔の台帳の行のうち温度の列が「営業」（売り込み）・「テスト」（社内の試し送信）でない行で数える。
# 以前は GA4 の送信イベントや台帳の行数をそのまま数え、売り込みもテストも入っていた（2026-10-10 運用者の指示）。
# 見分けは受付（contact.hub.gs の leadKind_）が行い、温度の列に入れる。GA4 の送信は取りこぼしの照合（main）にだけ使う
EXCLUDED = {"営業": "sales", "テスト": "test"}
_LEDGER = {}


def _day(v):
    try:
        return date(1899, 12, 30) + timedelta(days=float(v))
    except (TypeError, ValueError):
        try:
            return date.fromisoformat(str(v)[:10].replace("/", "-"))
        except ValueError:
            return None


def _site_resolver():
    import hub_sheets as H
    import re
    # 台帳の表示名は「コーポレート (corp.7senses.co.jp)」のように、サイト一覧の名前と一致しない
    # ことがある。括弧の中のドメインで引く（名前で引くと全行が「不明」になった）
    by_dom, by_name = {}, {}
    for r in H.rows("サイト一覧", 3):
        if len(r) >= 3:
            by_dom[str(r[2]).strip()] = r[0]
            by_name[str(r[1]).strip()] = r[0]

    def sid_of(label):
        m = re.search(r"\(([^)]+)\)", label or "")
        return by_dom.get(m.group(1).strip()) if m else by_name.get((label or "").strip())
    return sid_of


def ledger_rows(start=None, end=None):
    """台帳の行（日・サイトID・種別・温度・流入経路）。名前・メール・本文は持たない。1回の実行で1回だけ読む"""
    if "rows" not in _LEDGER:
        import hub_sheets as H
        sid_of = _site_resolver()
        rows = []
        for r in H.rows("問い合わせ", 14):
            d = _day(r[0])
            if d:
                rows.append({"day": d.isoformat(), "sid": sid_of(str(r[1])) or "?", "type": str(r[2]).strip(),
                             "temp": str(r[12]).strip(), "route": str(r[11]).strip()})
        _LEDGER["rows"] = rows
    s = start.isoformat() if start else ""
    e = end.isoformat() if end else "9999"
    return [x for x in _LEDGER["rows"] if s <= x["day"] <= e]


def browser_probes(start):
    """本物のブラウザから送った疎通確認（疎通確認のタブ）の、日ごと・サイトごとの数。
    ブラウザからの疎通確認は GA4 の送信イベントも出すが台帳には入らない。照合で GA4 の数から引かないと、
    「台帳に行が無い」と誤って要対応にする。スクリプトの疎通確認（lead_probe.py）は GA4 を出さないので引かない。
    見分け: 送信元がページの URL（2026-10-10 の流入の欄より前）か、流入の欄つき（「流入: 未記録」でない）"""
    import hub_sheets as H
    sid_of = _site_resolver()
    out = collections.defaultdict(collections.Counter)
    for r in H.rows("疎通確認", 4):
        d = _day(r[0])
        src = str(r[3]).strip()
        # 手元の確かめ（127.0.0.1・localhost のページ）は本番の GA4 に入ったか分からないので引かない（引きすぎると本物を隠す）
        local = "://127.0.0.1" in src or "://localhost" in src
        if d and d >= start and not local and (src.startswith(("http://", "https://"))
                                               or (src.startswith("流入: ") and not src.startswith("流入: 未記録"))):
            out[sid_of(str(r[1])) or "?"][d.isoformat()] += 1
    return out


def ledger_counts(rows, sid=None, start=None, end=None):
    """相談（売り込み・テスト以外）・売り込み・テストの件数と、相談の種別ごとの内訳"""
    s = start.isoformat() if start else ""
    e = end.isoformat() if end else "9999"
    c = {"consult": 0, "sales": 0, "test": 0, "by_type": collections.Counter()}
    for x in rows:
        if (sid and x["sid"] != sid) or not (s <= x["day"] <= e):
            continue
        k = EXCLUDED.get(x["temp"])
        if k:
            c[k] += 1
        else:
            c["consult"] += 1
            c["by_type"][x["type"] or "（種別なし）"] += 1
    return c


def consult_text(c):
    """レポート・検査に出す1行。「相談 N件（ほかに売り込み x件・テスト y件を除いた）」"""
    return f"相談 {c['consult']}件（ほかに売り込み {c['sales']}件・テスト {c['test']}件を除いた）"


def leads(sid, start, end, prop=None, ga4_n=None):
    """その社のその期間の問い合わせの件数（**レポートに出す数はこれだけ**）。
    台帳に行のある社は台帳の相談の数。台帳に1行も無い社（問い合わせを管制塔へ送らない社）と、その社の最初の行より前の期間は、
    GA4 の送信（ga4_n があればそれ、無ければ prop から lead_capture / generate_lead を数える）で数え、
    相談か見分けていないことを source='ga4' で返す。返す: {"n", "source": "ledger"|"ga4"|None, "counts"（台帳のときだけ）, "text"}"""
    try:
        rows = ledger_rows()
    except Exception:
        rows = None
    mine = [x for x in rows or [] if x["sid"] == sid]
    if mine and start.isoformat() >= min(x["day"] for x in mine)[:7] + "-01":
        c = ledger_counts(mine, start=start, end=end)
        return {"n": c["consult"], "source": "ledger", "counts": c, "text": consult_text(c)}
    n = ga4_n
    if n is None and prop:
        try:
            n = sum(ga4_by_day(str(prop), start, end).values())
        except Exception:
            n = None
    if n is None:
        return {"n": None, "source": None, "counts": None, "text": "台帳にも GA4 にも問い合わせの記録がありません"}
    why = ("台帳を読めなかった" if rows is None else
           "台帳に記録が始まる前の期間の" if mine else "この社の問い合わせは台帳に入っていない")
    return {"n": n, "source": "ga4", "counts": None,
            "text": f"送信 {n}件（GA4 の送信イベント。{why}ため、売り込み・テストを見分けていません）"}


def month_fields(sid, start, end, ga4_n):
    """月次の集計（monthly_report・group_report）の1か月に入れる問い合わせの欄。cv は台帳の相談の数
    （台帳に無い社・期間は GA4 の送信 ga4_n）。cv_ga4 は照合のために残す GA4 の送信の数"""
    r = leads(sid, start, end, ga4_n=ga4_n)
    out = {"cv": r["n"] if r["n"] is not None else ga4_n, "cv_source": r["source"] or "ga4", "cv_text": r["text"],
           "cv_ga4": ga4_n}
    if r["counts"]:
        c = r["counts"]
        out["cv_counts"] = {"consult": c["consult"], "sales": c["sales"], "test": c["test"], "by_type": dict(c["by_type"])}
    return out


# ── 流入経路の名前（受付の contact.hub.gs の leadSource_ と同じ分類）─────────────
# AI は daily_kpi.AI_DOMAINS を正とする（受付側は同じ中身を写して持つ。門 gates_history_h82_leads が一致を確かめる）
REF_LABELS = [
    ("mail.google.com", "Gmail（メール）"), ("outlook.live.com", "Outlook（メール）"), ("outlook.office.com", "Outlook（メール）"),
    ("mail.yahoo.co.jp", "Yahoo!メール"), ("googleadservices.com", "Google広告"), ("doubleclick.net", "Google広告"),
    ("google.", "Google検索"), ("bing.com", "Bing検索"), ("search.yahoo.co.jp", "Yahoo!検索"), ("yahoo.co.jp", "Yahoo! JAPAN"),
    ("duckduckgo.com", "DuckDuckGo"),
    ("ecosia.org", "Ecosia"), ("naver.com", "NAVER"), ("baidu.com", "Baidu"), ("yandex.", "Yandex"),
    ("facebook.com", "Facebook"), ("fb.com", "Facebook"), ("instagram.com", "Instagram"), ("t.co", "X"), ("x.com", "X"),
    ("twitter.com", "X"), ("linkedin.com", "LinkedIn"), ("lnkd.in", "LinkedIn"), ("youtube.com", "YouTube"), ("youtu.be", "YouTube"),
    ("threads.net", "Threads"), ("threads.com", "Threads"), ("note.com", "note"), ("tiktok.com", "TikTok"), ("line.me", "LINE"),
]
DIRECT = "直接（ブックマーク・URLの入力・アプリなど）"


def _host_is(host, d):
    if "/" in d:
        return False
    if d.endswith("."):
        return host.startswith(d) or ("." + d) in host
    return host == d or host.endswith("." + d)


def _ref_name(h):
    import daily_kpi as DK
    if not h:
        return ""
    for k, doms in DK.AI_DOMAINS.items():
        if any((d in h) if "." not in d else _host_is(h, d) for d in doms):
            return DK.AI_LABELS.get(k, k)
    return next((label for d, label in REF_LABELS if _host_is(h, d)), "")


def source_label(ref, utm="", ad="", own_host="", sites=None):
    """参照元のドメイン（と utm「source|medium|campaign」・広告のクリック）から流入の名前。sites は {ドメイン: 名前}"""
    host = str(ref or "").strip().lower().removeprefix("www.")
    u = str(utm or "").split("|")
    src, med = u[0].strip().lower(), (u[1].strip().lower() if len(u) > 1 else "")
    if src:
        tag = "（utm: " + " / ".join(x.strip() for x in u if x.strip()) + "）"
        paid = med in ("cpc", "ppc", "paid", "paidsearch", "display", "cpm")
        mail = med in ("email", "e-mail", "newsletter") or "newsletter" in src or "mail" in src
        return (_ref_name(src) or ("メール" if mail else src)) + ("（広告）" if paid else "") + tag
    if ad:
        return "Google広告"
    if not host:
        return DIRECT
    own = str(own_host or "").lower().removeprefix("www.")
    if own and host == own:
        return "未記録（記録を始める前の来訪）"
    name = _ref_name(host)
    if name:
        return name
    for dom, nm in (sites or {}).items():
        if host == str(dom).lower().removeprefix("www."):
            return f"自社サイト（{nm}）"
    return f"他サイト（{host}）"


def ga4_source_label(source, medium):
    """GA4 のセッションの参照元・メディア（sessionSource / sessionMedium）から、受付と同じ流入の名前（推定に使う）"""
    s, m = str(source or "").strip().lower(), str(medium or "").strip().lower()
    if s in ("(direct)", "") and m in ("(none)", "(not set)", ""):
        return DIRECT
    ai = _ref_name(s) if "." in s or s == "openai" else ""
    if ai and ai not in dict(REF_LABELS).values():
        return ai
    engines = {"google": "Google検索", "bing": "Bing検索", "yahoo": "Yahoo!検索", "duckduckgo": "DuckDuckGo",
               "ecosia.org": "Ecosia", "naver": "NAVER", "baidu": "Baidu", "yandex": "Yandex"}
    if m == "organic":
        return engines.get(s) or ai or f"{s}（自然検索）"
    if m in ("cpc", "ppc", "paid"):
        return (engines.get(s, s).replace("検索", "")) + "（広告）"
    return ai or (f"他サイト（{s}）" if "." in s else s)


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
    # ブラウザからの疎通確認は GA4 の送信を出すが台帳に入らない。照合の前に GA4 の数から引く（台帳を読めた回だけ）
    probes = {}
    if "rows" in _LEDGER:
        try:
            probes = browser_probes(start)
        except Exception as e:
            print(f"  疎通確認のタブを読めず、ブラウザからの疎通確認を引いていません（{str(e)[:60]}）")
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
        pr = probes.get(sid, {})
        for d, n in pr.items():
            if d in ga:
                ga[d] = max(0, ga[d] - n)
        if pr:
            print(f"  （{cfg.get('name', sid)}: ブラウザからの疎通確認 {sum(pr.values())}件を GA4 の送信から引きました）")
        # 調べて記録が見つからなかった日（ACK）は毎週くり返し知らせない
        ack = set(ACKED.get(sid, {}))
        miss = [d for d, n in sorted(ga.items()) if n > 0 and led[sid].get(d, 0) == 0 and d not in ack]
        # 照合は台帳の全行と比べる（GA4 の送信には売り込み・テストも入る）。件数として出すのは相談だけ
        print(f"  {cfg.get('name', sid)}: GA4 の送信 {sum(ga.values())}件（{len(ga)}日） / 台帳 {sum(led[sid].values())}行"
              + (f"（{consult_text(ledger_counts(ledger_rows(start), sid=sid))}）"
                 if led[sid] and "rows" in _LEDGER else ""))
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
