# -*- coding: utf-8 -*-
"""Bing の検索の成績を週次で積み、月次レポートで Google と並べる（2026-10-07 運用者の依頼）。

外部（Bing）には触れず、_request を偽物に差し替えて確かめる:

  - 日付 "/Date(ms±hhmm)/" を正しい日に直す（公式の例 -0700 と、実測の時差なし）
  - 日別・語・ページを積み、次の回で API の窓から外れた古い日・週を消さない。順位の -1 は「無し」
  - 取るのは送る対象（send_cfgs＝自社と、同意があり所有権を確かめたお客様の社）だけ
  - お客様の社の成績は public に置かない（.gitignore）。自社3サイトはコミットできる
  - 月次レポートの節: Bing と Google の表示・クリック・主な語。表示10回未満はクリック率を出さない。
    成績がまだ無い月は「0回」と書かない。成績を積んでいない社は節を出さない
  - 週次ワークフローが --stats を Bing の工程の近くで呼び、自社の分をコミットし、お客様の分をキャッシュで持ち越す
"""
import contextlib
import json
import subprocess
import tempfile
from pathlib import Path

from test_gates import check, ROOT


def _rows():
    rt = [{"Date": "/Date(1788134400000)/", "Impressions": 12, "Clicks": 1},     # 2026-08-31
          {"Date": "/Date(1788220800000)/", "Impressions": 30, "Clicks": 2},     # 2026-09-01
          {"Date": "/Date(1788307200000)/", "Impressions": 8, "Clicks": 0}]      # 2026-09-02
    qs = [{"Date": "/Date(1788307200000)/", "Query": "ai 集客", "Impressions": 5, "Clicks": 1,
           "AvgImpressionPosition": 6, "AvgClickPosition": -1},
          {"Date": "/Date(1788307200000)/", "Query": "<b>aio</b> 診断", "Impressions": 9, "Clicks": 0,
           "AvgImpressionPosition": -1, "AvgClickPosition": -1}]
    ps = [{"Date": "/Date(1788307200000)/", "Query": "https://x.example/a/", "Impressions": 7, "Clicks": 1,
           "AvgImpressionPosition": 3, "AvgClickPosition": 3}]
    return rt, qs, ps


@contextlib.contextmanager
def fake(B, answers, cfgs):
    """_request と送る対象・置き場を差し替える"""
    old = (B._request, B.send_cfgs, B.STATS_DIR)
    calls = []

    def req(method, name, key, query=None, body=None):
        calls.append((name, (query or {}).get("siteUrl")))
        return {"d": answers.get(name, [])}
    with tempfile.TemporaryDirectory() as d:
        B._request, B.send_cfgs, B.STATS_DIR = req, (lambda key=None: cfgs), Path(d)
        try:
            yield calls
        finally:
            B._request, B.send_cfgs, B.STATS_DIR = old


def test_bing_stats_are_collected_and_merged():
    import bing_webmaster as B
    check("Bing の日付: 公式の例（-0700）はその土地の日", B.bing_day("/Date(1316156400000-0700)/"), "2011-09-16")
    check("Bing の日付: 時差なしは UTC の日", B.bing_day("/Date(1788220800000)/"), "2026-09-01")
    check("Bing の日付: 形が違えば空", B.bing_day("2026-09-01"), "")
    rt, qs, ps = _rows()
    cfgs = {"own": {"id": "own", "domain": "own.example"}}
    with fake(B, {"GetRankAndTrafficStats": rt, "GetQueryStats": qs, "GetPageStats": ps}, cfgs) as calls:
        B.collect_stats(["--stats"], "k")
        s = B.load_stats("own")
        check("Bing の成績: 取るのは日別・語・ページの3つで、送る対象のドメインだけ",
              sorted(calls), sorted([("GetPageStats", "https://own.example/"), ("GetQueryStats", "https://own.example/"),
                                     ("GetRankAndTrafficStats", "https://own.example/")]))
        check("Bing の成績: 日別が日付ごとに積まれる", s["daily"]["2026-09-01"], {"imp": 30, "clicks": 2})
        wk = s["weeks"]["2026-09-02"]
        check("Bing の成績: 語は表示回数の多い順・順位の -1 は無し", [(r["key"], r["pos"]) for r in wk["queries"]],
              [("<b>aio</b> 診断", None), ("ai 集客", 6)])
        check("Bing の成績: ページも週ごとに残る", wk["pages"][0]["key"], "https://x.example/a/")
        # 次の回: API の窓から外れた古い日・週は返らないが、手元からは消さない
        new_rt = [{"Date": "/Date(1788307200000)/", "Impressions": 9, "Clicks": 1}]
        new_q = [{"Date": "/Date(1788912000000)/", "Query": "meo", "Impressions": 2, "Clicks": 0,
                  "AvgImpressionPosition": 4}]
        B._request = lambda m, n, k, query=None, body=None: {"d": {"GetRankAndTrafficStats": new_rt,
                                                                     "GetQueryStats": new_q}.get(n, [])}
        B.collect_stats(["--stats"], "k")
        s2 = B.load_stats("own")
        check("Bing の成績: 古い日を消さず、同じ日は新しい値で上書き",
              (s2["daily"]["2026-08-31"]["imp"], s2["daily"]["2026-09-02"]["imp"]), (12, 9))
        check("Bing の成績: 古い週を消さず、新しい週を足す", sorted(s2["weeks"]), ["2026-09-02", "2026-09-09"])

        # 月次レポートの節
        h = B.report_html("own", "2026-09", None, {"imp": 1234, "clicks": 56})
        check("月次の Bing の節: Bing の9月の表示・クリックを Google と並べる",
              all(x in h for x in ('<td class="num">39</td>', '<td class="num">3</td>', '<td class="num">1,234</td>',
                                   '<td class="num">56</td>', "Search Console")), True)
        check("月次の Bing の節: 8月31日を9月に入れない", '<td class="num">51</td>' in h, False)
        check("月次の Bing の節: 主な語を出し、語はエスケープする",
              "&lt;b&gt;aio&lt;/b&gt; 診断" in h and "<b>aio</b>" not in h and "ai 集客" in h, True)
        check("月次の Bing の節: 表示10回以上ならクリック率", "7.7%" in h, True)
        h_small = B.report_html("own", "2026-09", "2026-09-02", {"imp": 5, "clicks": 1})
        check("月次の Bing の節: 表示10回未満はクリック率を出さない（Google 側も）",
              h_small.count("表示10回未満") >= 1 and "20.0%" not in h_small, True)
        h_none = B.report_html("own", "2026-11", None, {"imp": 10, "clicks": 1})
        check("月次の Bing の節: 成績がまだ無い月は0と書かず、まだと書く",
              "まだ返っていません" in h_none and '<td class="num">0</td>' not in h_none, True)
        check("月次の Bing の節: 成績を積んでいない社は節を出さない", B.report_html("nobody", "2026-09"), "")

    # 送る対象が空なら（同意の無いお客様だけの状態）、1つも取らない
    with fake(B, {"GetRankAndTrafficStats": rt}, {}) as calls:
        B.collect_stats(["--stats"], "k")
        check("Bing の成績: 送る対象に無い社（同意の無いお客様）は取らない", calls, [])
    src = (ROOT / "scripts" / "bing_webmaster.py").read_text(encoding="utf-8")
    check("Bing の成績: 対象は送信と同じ send_cfgs", "for sid, cfg in send_cfgs(key).items():" in
          src[src.index("def collect_stats"):src.index("def month_totals")], True)


def test_bing_stats_privacy_and_wiring():
    def ignored(rel):
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", rel])
        return r.returncode == 0
    check("Bing の成績: お客様の社のファイルは public に置かない", ignored("data/bing_stats/client-x.json"), True)
    check("Bing の成績: 自社3サイトはコミットできる",
          [ignored(f"data/bing_stats/{s}.json") for s in ("ai-lab", "corporate", "subsidy")], [False, False, False])
    mr = (ROOT / "scripts" / "monthly_report.py").read_text(encoding="utf-8")
    check("月次レポート: Bing の節を Google の月の表示・クリックと並べて差し込む",
          "_bw.report_html(SITE_ID, ym, THROUGH" in mr and 'cur.get("impressions")' in mr and "{bing_pages}" in mr, True)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    i = wf.index("python scripts/bing_webmaster.py --weekly")
    check("週次: 検索の成績を Bing の送信の工程の近くで取る", "bing_webmaster.py --stats" in wf[i:i + 600], True)
    check("週次: 自社の成績をコミットし、お客様の分をキャッシュで持ち越す",
          "data/bing_stats" in wf[wf.index("data/yield_state.json"):][:400]
          and "bing-stats-" in wf and "!data/bing_stats/ai-lab.json" in wf, True)
    mw = (ROOT / ".github" / "workflows" / "monthly-report.yml").read_text(encoding="utf-8")
    check("月次: お客様の Bing の成績をキャッシュから戻してからレポートを作る",
          "bing-stats-" in mw and mw.index("bing-stats-") < mw.index("月次レポート生成"), True)
