# -*- coding: utf-8 -*-
"""2026-10-20 データ集めの点検で見つけた、取れなかった回を「0」や「問題なし」と書いていた箇所。

  1. 日次KPI: GA4 が落ちた社の行を0で送り、その日を送り済みにして二度と取り直さなかった
  2. 引用の実測: AI が全部 429 で落ちた回も「引用0/20語」と記録した
  3. 月の途中のレポート: 検索の数字（確定は3日遅れ）を GA4 と同じ日数で割っていた。サイトをまたぐ平均順位が単純平均
  4. 順位の記録: rowLimit 1000 で切れていた（AI集客ラボは987行）
  5. 施策の効き: GSC が取れなくても EFFECT_AB_OK=yes
  6. 結果から学ぶ: 信号が読めなかった週に、その学びを退役させた。「型なし」の書き置きを型として学んだ
  7. 数字の信頼性: 台帳を今日まで、GA4 を前日まで数え、今日の相談で毎回「GA4 に送信が無い」と出た
  8. 再通知: URL検査が全部失敗しても「すべて登録済み」
  9. 表示速度: 測れなかったサイトがあっても CWV_OK=yes

本物の GA4・Search Console・AI・PageSpeed は使わない。架空の社（client-zz・zz.example）で確かめる
"""
import contextlib
import io
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


# ── 1. 日次KPI ────────────────────────────────────────────────

def test_daily_kpi_retries_failed_sites_and_sends_blanks():
    import daily_kpi as K
    print("\n■ 日次KPI: GA4 が落ちた社は送らずに取り直し、期限切れなら空欄で送る（0にしない）")
    keep, wait = K.split_rows([{"site": "own-zz", "date": "d", "sessions": 3},
                               {"site": "client-zz", "date": "d", "note": "n", "_retry": ["GA4"]}], final=False)
    check("取れなかった社は送らず取り直しに回す", ([r["site"] for r in keep], wait), (["own-zz"], {"client-zz"}))
    keep, wait = K.split_rows([{"site": "client-zz", "date": "d", "note": "n", "_retry": ["GA4"]}], final=True)
    check("期限切れの回は空欄のまま送り、0を入れず、0でないと書き添える",
          (wait, "sessions" in keep[0], "_retry" in keep[0], "0ではありません" in keep[0]["note"]),
          (set(), False, False, True))

    import lead_reconcile as LR

    def ga4(prop, day):
        raise RuntimeError("HTTP 500 backend" if prop == "1" else "403 PERMISSION_DENIED")
    sites_ = {"own-zz": {"domain": "own.zz.example", "ga4_property_id": "1"},
              "client-zz": {"domain": "zz.example", "ga4_property_id": "2"}}
    with mock.patch.object(K, "ga4", ga4), mock.patch.object(K, "gsc", lambda u, d: {"impressions": 9, "clicks": 1}), \
            mock.patch.object(K, "aio_estimate", lambda s: {}), \
            mock.patch.object(LR, "leads", lambda *a, **k: {"n": None, "source": "ga4"}), \
            mock.patch.object(K.sites_mod, "load_all", lambda: sites_), \
            mock.patch.object(K.sites_mod, "is_client", lambda s: s == "client-zz"):
        rows, _ = _quiet(K.collect, "2026-10-19")
    got = {r["site"]: (r.get("_retry"), "sessions" in r) for r in rows}
    check("一時的な失敗は取り直し、権限が無い（取り直しても直らない）社は空欄で送る",
          got, {"own-zz": (["GA4"], False), "client-zz": (None, False)})

    y = (date.today() - timedelta(days=1)).isoformat()
    state = {"fail": True}
    posted = []

    def collect(day, only=None):
        rows = []
        for sid in ("own-zz", "client-zz"):
            if only is not None and sid not in only:
                continue
            r = {"site": sid, "date": day, "note": "n"}
            if sid == "client-zz" and state["fail"]:
                r["_retry"] = ["GA4"]
            else:
                r["sessions"] = 5
            rows.append(r)
        return rows

    with tempfile.TemporaryDirectory() as td:
        sa = Path(td) / "sa.json"
        sa.write_text("{}", encoding="utf-8")
        with mock.patch.object(K, "SA", sa), mock.patch.object(K, "SENT", Path(td) / "kpi_sent.json"), \
                mock.patch.object(K, "collect", collect), \
                mock.patch.object(K.hub_client, "enabled", lambda: True), \
                mock.patch.object(K.hub_client, "_post", lambda b: posted.append(b) or {"ok": True, "rows": len(b["rows"])}), \
                mock.patch.object(sys, "argv", ["daily_kpi.py", "--send", "--once"]):
            _quiet(K.main)
            first = ([r["site"] for r in posted[0]["rows"]], K.sent_days(), K.retry_sites())
            state["fail"] = False
            _quiet(K.main)
            second = ([r["site"] for r in posted[1]["rows"]], posted[1].get("partial"), K.retry_sites())
            _quiet(K.main)
            third = len(posted)
            # 窓から外れる日（今日−CATCH_UP 日）の取り直しは、取れなくても空欄で送って終える
            old = (date.today() - timedelta(days=K.CATCH_UP)).isoformat()
            K.mark_sent(old, {"client-zz"})
            state["fail"] = True
            _quiet(K.main)
            last = (posted[-1]["rows"][0]["site"], "sessions" in posted[-1]["rows"][0], K.retry_sites())
    check("1回目: 取れた社だけ送り、日は送り済み・取れなかった社は取り直しに残す",
          first, (["own-zz"], {y}, {y: {"client-zz"}}))
    check("2回目: 取り直した社だけを送り（ダッシュボードは書き換えない印つき）、取り直しを消す",
          second, (["client-zz"], True, {}))
    check("3回目: 送り済みの日も取り直しも無ければ何も送らない", third, 2)
    check("期限の日は取れなくても空欄で送り、取り直しをやめる", last, ("client-zz", False, {}))

    hub = (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")
    body = hub.split("function kpiLog_", 1)[1].split("\nfunction ", 1)[0]
    check("管制塔: セッション・PV・CV は無ければ空欄（|| 0 で0にしない）",
          ("sc(r.sessions)" in body and "sc(r.pv)" in body and "sc(r.cv)" in body, "r.sessions || 0" in body),
          (True, False))
    check("管制塔: 取り直した社だけの行ではダッシュボード（全社の合計）を書き換えない",
          "if (!b.partial) writeDashboard_" in body, True)


def test_daily_kpi_shows_unknown_when_ai_did_not_answer():
    import daily_kpi as K
    import client_private as CP
    print("\n■ 日次KPI: 引用の実測が1語も答えを得られなかった月は「0/20」ではなく不明と書く")
    d = {"date": "2026-10-01", "sites": {"own-zz": {"suspect_taken": 2, "judged": 9}},
         "measured": {"engines": ["Gemini"], "sites": {"own-zz": {"queries": 0, "asked": 20, "cited": 0}}}}
    with mock.patch.object(CP, "citation_months", lambda: ["2026-10.json"]), \
            mock.patch.object(CP, "load_citations", lambda m: d):
        note = K.aio_estimate("own-zz")["aio_note"]
        d["measured"]["sites"]["own-zz"] = {"queries": 12, "asked": 20, "cited": 3}
        note2 = K.aio_estimate("own-zz")["aio_note"]
    check("答えが無い月は不明（0/20 と書かない）", ("不明" in note, "0/20" in note), (True, False))
    check("答えた語だけを母数にする（3/12語）", "引用3/12語" in note2, True)


# ── 2. 引用の実測 ─────────────────────────────────────────────

def test_cite_check_counts_only_answered_queries():
    import ai_cite_check as A
    print("\n■ 引用の実測: 数えるのは AI が答えた語だけ。1語も答えが無ければ不明")

    def boom(q):
        raise RuntimeError("HTTP 429: quota")
    rec, _ = _quiet(A.measure_site, ["a", "b", "c"], {"Gemini": boom, "Perplexity": lambda q: None}, "zz.example", True)
    check("全部落ちた回は queries=0・asked=3・note つき", (rec["queries"], rec["asked"], rec["cited"], bool(rec.get("note"))),
          (0, 3, 0, True))

    def some(q):
        if q == "c":
            raise RuntimeError("HTTP 429")
        return ["https://zz.example/x/"] if q == "a" else ["https://other.example/"]
    rec, _ = _quiet(A.measure_site, ["a", "b", "c"], {"Gemini": some}, "zz.example", True)
    check("答えた2語のうち引用1語（落ちた1語は母数に入れない）", (rec["queries"], rec["asked"], rec["cited"]), (2, 3, 1))


# ── 3. 月の途中のレポート ──────────────────────────────────────

def test_mid_month_gsc_per_day_uses_covered_days():
    import report_context as RC
    print("\n■ 月の途中: 検索の数字は確定している日（今日−3日）までの日数で1日あたりに直す")
    through = date(2026, 10, 15)
    with mock.patch.object(RC, "_today", lambda: date(2026, 10, 15)):
        imp = RC.compare({"impressions": 1200}, {"impressions": 3000}, "impressions", "2026-10", "2026-09", through)
        ses = RC.compare({"sessions": 1500}, {"sessions": 3000}, "sessions", "2026-10", "2026-09", through)
        warn = RC.partial_warning("2026-10", through)
        full = RC.compare({"impressions": 3000}, {"impressions": 3100}, "impressions", "2026-09", "2026-08")
    with mock.patch.object(RC, "_today", lambda: date(2026, 10, 2)):
        early = RC.compare({"clicks": 5}, {"clicks": 300}, "clicks", "2026-10", "2026-09", date(2026, 10, 2))
    check("表示は12日（10/12まで）で割る: 1日100回同士で横ばい（15日で割ると-20%に見えた）",
          (imp["dir"], round(imp["pct"]), "10月12日まで" in imp["text"]), ("flat", 0, True))
    check("GA4 のセッションは15日で割る（1日100 → 1日100）", (ses["dir"], round(ses["pct"])), ("flat", 0))
    check("途中経過の但し書きに、検索の数字が何日までかを書く", "10月12日まで（12日分）" in warn, True)
    check("確定した日がまだ無い月初は比べない", (early["dir"], "まだ無い" in early["text"]), ("flat", True))
    check("済んだ月はこれまでどおり（31日と30日）", ("2026-08は31日、2026-09は30日）" in full["text"]), True)

    import group_report as G
    sites = [{"months": [{"pos": 3.0, "impressions": 100}]}, {"months": [{"pos": 30.0, "impressions": 9900}]}]
    check("サイトをまたぐ平均順位は表示回数で重み付け（単純平均16.5位ではなく29.7位）", G.avg_position(sites), 29.7)
    check("表示回数が無ければ単純平均", G.avg_position([{"months": [{"pos": 4.0}]}, {"months": [{"pos": 6.0}]}]), 5.0)


# ── 4. 順位の記録 ─────────────────────────────────────────────

def test_rank_track_paginates():
    import rank_track as R
    print("\n■ 順位の記録: 25,000行ずつページ送りし、1000行で切らない")
    seen = []

    class Q:
        def searchanalytics(self):
            return self

        def query(self, siteUrl, body):
            seen.append((body["rowLimit"], body["startRow"]))
            n = R.PAGE if body["startRow"] == 0 else 7
            rows = [{"keys": [f"q{body['startRow'] + i}", "https://zz.example/a/"], "position": 5.0,
                     "impressions": 1, "clicks": 0, "ctr": 0.0} for i in range(n)]
            return mock.Mock(execute=lambda: {"rows": rows})
    out = R.fetch("https://zz.example/", sc=Q())
    check("2ページ取り、全行を記録する", (len(out), seen), (R.PAGE + 7, [(R.PAGE, 0), (R.PAGE, R.PAGE)]))


# ── 5. 施策の効き ─────────────────────────────────────────────

def test_effect_ab_does_not_say_yes_when_gsc_failed():
    import effect_ab as EA
    import gsc_detail as G
    import sites as S
    print("\n■ 施策の効き: GSC が取れなかった回を EFFECT_AB_OK=yes と出さない")

    def q(sc, domain, start, end, dims=None, limit=1000, raise_errors=False):
        if not raise_errors:
            return []
        raise RuntimeError("HTTP 500")
    sites = {"own-zz": {"id": "own-zz", "domain": "own.zz.example"},
             "client-zz": {"id": "client-zz", "domain": "zz.example"}}
    with mock.patch.object(G, "client", lambda: None), mock.patch.object(G, "q", q), \
            mock.patch.object(S, "load_all", lambda: sites), mock.patch.object(S, "is_client", lambda s: s == "client-zz"), \
            mock.patch.object(S, "public_id", lambda s: "c0000zz00"), \
            mock.patch.object(EA, "interventions", lambda: [{"slug": "a", "at": "2026-09-01", "kind": "x"}]), \
            mock.patch.object(sys, "argv", ["effect_ab.py"]):
        raised = False
        try:
            _quiet(EA.daily_by_slug)
        except RuntimeError:
            raised = True
        _, out = _quiet(EA.main)
    check("全サイト落ちたら例外（空の日次を返さない）", raised, True)
    check("印は EFFECT_AB_OK=unknown", ("EFFECT_AB_OK=unknown" in out, "EFFECT_AB_OK=yes" in out), (True, False))
    check("お客様の社の id はログに出さない", "client-zz" in out, False)


# ── 6. 結果から学ぶ ───────────────────────────────────────────

def test_learn_keeps_lessons_when_signal_breaks_and_skips_placeholders():
    import learn as LN
    import lessons as L
    print("\n■ 結果から学ぶ: 信号が読めない週は学びを残す。「型なし」「なし」は型として学ばない")
    head = "全体: CTR 1.48%（表示14,166回・310ページ）\n\n"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "title_patterns.md"
        with mock.patch.object(LN, "DATA", Path(td)):
            p.write_text(head + "寄せる型: （全体比1.15倍以上の型なし。型より語の性質を優先）\n避ける型: なし\n", encoding="utf-8")
            none = LN.title_signal()
            p.write_text(head + "寄せる型: （全体比1.15倍以上の型なし。型より語の性質を優先）\n避ける型: 年号入り\n", encoding="utf-8")
            only_bad = LN.title_signal()
    check("寄せる型も避ける型も無い週は学びにしない", none, [])
    rule = only_bad[0][4] if only_bad else ""
    check("避ける型だけの週は、避ける型だけの文にする（書き置きを入れない）",
          ("型なし" in rule, "「年号入り」の型は避ける" in rule, "は、" in rule), (False, True, False))

    rows = [{"id": 1, "source": "learn:yield:own-zz", "status": "active", "rule": "r", "detail": "d"},
            {"id": 2, "source": "learn:rollback", "status": "active", "rule": "r", "detail": "d"}]
    saved = []

    def broken():
        raise ValueError("yield_state.json が読めない")
    with mock.patch.object(LN, "SIGNALS", (broken, lambda: [])), mock.patch.object(LN, "SOURCES", {broken: "learn:yield"}), \
            mock.patch.object(L, "load", lambda: rows), mock.patch.object(L, "save", lambda r: saved.append(r)), \
            mock.patch.object(sys, "argv", ["learn.py", "--write"]):
        _, out = _quiet(LN.main)
    check("読めなかった信号の学びは残し、根拠の消えた学びだけ退役させる",
          [r["status"] for r in rows], ["active", "retired"])


# ── 7. 数字の信頼性 ───────────────────────────────────────────

def test_sanity_ledger_ends_where_ga4_ends():
    import data_sanity as D
    import lead_reconcile as L
    print("\n■ 数字の信頼性: 台帳も GA4 と同じ前日で切る（今日の相談で「GA4 に無い」と出さない）")
    today, y = date.today().isoformat(), (date.today() - timedelta(days=1)).isoformat()
    out = []
    with mock.patch.object(L, "ga4_by_day", lambda prop, s, e: {y: 1}), \
            mock.patch.object(L, "ACKED", {}), mock.patch.object(L, "ledger_rows", lambda s=None, e=None: []):
        got = D.check_leads("own-zz", {}, "1", 28, {"own-zz": {today: 2, y: 1}}, out)
    check("今日の台帳の行は照合に入れない（注意0件・台帳1行）", (out, got[1]), ([], 1))


# ── 8. 再通知 ─────────────────────────────────────────────────

def test_reindex_does_not_claim_all_indexed_when_inspection_failed():
    import reindex as RX
    print("\n■ 再通知: URL検査が全部失敗・時間切れのとき「すべて登録済み」と言わない")

    class Fail:
        def urlInspection(self):
            raise RuntimeError("HTTP 429 quota")
    stats = {}
    with mock.patch.object(RX, "svc", lambda *a: Fail()):
        ng, _ = _quiet(RX.unindexed, None, ["https://zz.example/a/", "https://zz.example/b/"], "https://zz.example/",
                       None, {}, stats)
    check("失敗は数え、未登録は空", (ng, stats), ([], {"checked": 0, "failed": 2, "skipped": 0}))
    msg = RX.summary(ng, stats)
    check("一言は「不明」で、すべて登録済みと言わない", ("不明" in msg, "すべて登録済み" in msg), (True, False))
    stats = {}
    ng, _ = _quiet(RX.unindexed, None, ["https://zz.example/a/"], "https://zz.example/", 1.0, {}, stats)
    check("時間切れで見送った分も数える", (stats["skipped"], "不明" in RX.summary(ng, stats)), (1, True))
    check("全部確かめて未登録が無いときだけ「すべて登録済み」", RX.summary([], {"checked": 3, "failed": 0, "skipped": 0}),
          "すべて登録済み")


# ── 9. 表示速度 ───────────────────────────────────────────────

def test_cwv_unknown_when_a_site_could_not_be_measured():
    import cwv_check as C
    import client_private as CP
    import sites as S
    print("\n■ 表示速度: 測れなかったサイトがあれば CWV_OK=yes と出さない")
    own, cli = "https://own.zz.example/", "https://zz.example/"

    def measure(url):
        if url == cli:
            raise RuntimeError("HTTP 429")
        return {"url": url, "strategy": "mobile", "source": "lab", "LCP": 1800, "CLS": 0, "INP": None,
                "score": 95, "_fetched": "t"}
    sites_ = {"own-zz": {"domain": "own.zz.example"}, "client-zz": {"domain": "zz.example"}}
    with tempfile.TemporaryDirectory() as td:
        with mock.patch.object(C, "measure", measure), \
                mock.patch.object(C, "sample_urls", lambda cfg: [f"https://{cfg['domain']}/"]), \
                mock.patch.object(S, "load_all", lambda: sites_), mock.patch.object(S, "is_client", lambda s: s == "client-zz"), \
                mock.patch.object(S, "public_id", lambda s: "c0000zz00" if s == "client-zz" else s), \
                mock.patch.object(C, "LOG", Path(td) / "cwv.jsonl"), mock.patch.object(C.time, "sleep", lambda s: None), \
                mock.patch.object(C, "PSI_GAP", 0), mock.patch.object(CP, "append_jsonl", lambda p, row, sid=None: None), \
                mock.patch.object(sys, "argv", ["cwv_check.py", "--no-crux"]):
            rc, out = _quiet(C.main)
    line = [ln for ln in out.splitlines() if ln.startswith("CWV_OK=")]
    check("印は unknown で、測れなかったサイトを公開の id で挙げる",
          (line[0].startswith("CWV_OK=unknown") if line else False, "c0000zz00" in (line[0] if line else ""),
           "client-zz" in out, rc), (True, True, False, 0))
