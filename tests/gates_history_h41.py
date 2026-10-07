# -*- coding: utf-8 -*-
"""実際の利用者の表示速度（CrUX API）を週次で取る（2026-10-07 運用者の依頼）。

外部（CrUX API）には触れず、_crux_post / urlopen を偽物に差し替えて確かめる:

  - アクセスが少ないURL・サイトの 404（データ無し）を「遅い」と読まない。全部データ無しなら CRUX_OK=unset
  - 履歴（25週）で、基準を割った（bad）・基準内だが悪化が続いている（worse）を見つけ、要対応に出す
  - 欠けた週（null）・CLS の文字列（"0.05"）を正しく読む。最新の週が欠けていれば古い値で判定しない
  - API が使えない（鍵の制限 403）は CRUX_OK=unknown・終了コード1。鍵が無ければ unset・0
  - お客様の社の記録は public に置かない（.gitignore）。自社3サイトはコミットできる
  - 週次の実測の工程が CrUX まで回り、月次レポートに節を差し込み、お客様の分はキャッシュで月次へ渡す
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _period(n):
    return [{"firstDate": {"year": 2026, "month": 4, "day": 1 + i % 28},
             "lastDate": {"year": 2026, "month": 5, "day": 1 + i % 28}} for i in range(n)]


def _record(lcp, inp, cls):
    return {"record": {"key": {"formFactor": "PHONE"}, "metrics": {
        "largest_contentful_paint": {"percentiles": {"p75": lcp}},
        "interaction_to_next_paint": {"percentiles": {"p75": inp}},
        "cumulative_layout_shift": {"percentiles": {"p75": cls}}},
        "collectionPeriod": {"firstDate": {"year": 2026, "month": 9, "day": 8},
                             "lastDate": {"year": 2026, "month": 10, "day": 5}}}}


def _history(lcp, inp, cls):
    n = len(lcp)
    return {"record": {"key": {"formFactor": "PHONE"}, "metrics": {
        "largest_contentful_paint": {"percentilesTimeseries": {"p75s": lcp}},
        "interaction_to_next_paint": {"percentilesTimeseries": {"p75s": inp}},
        "cumulative_layout_shift": {"percentilesTimeseries": {"p75s": cls}}},
        "collectionPeriods": _period(n)}}


@contextlib.contextmanager
def fake(C, answer, key="k", urls=()):
    """_crux_post・鍵・置き場・対象サイト・URL上位を差し替える。answer(method, body) が応答（None=404）"""
    import sites as S
    old = (C._crux_post, C._key, C.CRUX_DIR, C.top_urls, S.load_all, C.CRUX_PAUSE)
    calls = []
    with tempfile.TemporaryDirectory() as td:
        def post(method, body, k):
            calls.append((method, body.get("origin") or body.get("url"), body["formFactor"],
                          body.get("collectionPeriodCount")))
            return answer(method, body)
        C._crux_post = post
        C._key = lambda names=(): key
        C.CRUX_DIR = Path(td)
        C.CRUX_PAUSE = 0
        C.top_urls = lambda sid, cfg, n=5, days=28: list(urls)
        S.load_all = lambda: {"own-x": {"domain": "x.example"}}
        try:
            yield calls, Path(td)
        finally:
            C._crux_post, C._key, C.CRUX_DIR, C.top_urls, S.load_all, C.CRUX_PAUSE = old


def _run(C):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = C.run_crux("")
    return rc, buf.getvalue()


def test_crux_nodata_is_not_slow_and_degradation_is_found():
    import cwv_check as C

    # 判定: 25週ずっと基準内で、最後に割った → bad（何週前は基準内だったかを添える）
    s = [2000.0] * 22 + [2300.0, 2400.0, 3100.0]
    mark, txt = C.judge("LCP", 3100.0, s)
    check("CrUX の判定: 基準（LCP 2.5秒）を割ったら bad", mark, "bad")
    check("CrUX の判定: 何週前は基準内だったかを添える", "1週前は基準内" in txt, True)
    # 基準内だが、それまでの週の中央値の1.2倍以上で、基準の8割を超え、直近4週が続けて上 → worse
    s = [1500.0] * 21 + [2050.0, 2100.0, 2150.0, 2200.0]
    check("CrUX の判定: 基準内でも悪化が続けば worse", C.judge("LCP", 2200.0, s)[0], "worse")
    # 基準のはるか内側の揺れは知らせない
    s = [800.0] * 21 + [1000.0, 1100.0, 1200.0, 1300.0]
    check("CrUX の判定: 基準のはるか内側の揺れは ok", C.judge("LCP", 1300.0, s)[0], "ok")
    # 1週だけ跳ねた（直近4週が続けて上ではない）は worse にしない
    s = [1500.0] * 21 + [1500.0, 1500.0, 1500.0, 2200.0]
    check("CrUX の判定: 1週だけの跳ねは worse にしない", C.judge("LCP", 2200.0, s)[0], "ok")
    # データ無し: 今の値が無く、最新の週も欠け → nodata（古い悪い値で判定しない）
    check("CrUX の判定: 最新の週が欠けていれば古い値で判定しない",
          C.judge("LCP", None, [4000.0, 4000.0, None])[0], "nodata")
    check("CrUX の判定: 値がまったく無ければ nodata", C.judge("INP", None, [])[0], "nodata")
    # 読み取り: CLS は文字列、欠けた週は null、密度の欠けは "NaN"
    h = C.parse_history(_history([2000, None, 2100], [None, None, 150], ["0.05", None, "0.12"]))
    check("CrUX の読み取り: 欠けた週は None・CLS の文字列は数に", (h["LCP"], h["CLS"], len(h["weeks"])),
          ([2000.0, None, 2100.0], [0.05, None, 0.12], 3))
    check("CrUX の読み取り: 今の値（CLS は文字列）", C.parse_current(_record(1800, 120, "0.03"))["CLS"], 0.03)

    # 404 は None（データ無し）、403 は API が使えない（1件ずつの失敗と分ける）
    import urllib.request as U
    old = U.urlopen

    def raiser(code, body):
        def f(*a, **k):
            raise urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(json.dumps(body).encode()))
        return f
    try:
        U.urlopen = raiser(404, {"error": {"code": 404, "message": "chrome ux report data not found",
                                           "status": "NOT_FOUND"}})
        check("CrUX: 404（データ無し）は None", C._crux_post("queryRecord", {"origin": "https://x"}, "k"), None)
        U.urlopen = raiser(403, {"error": {"code": 403, "message": "blocked",
                                           "details": [{"reason": "API_KEY_SERVICE_BLOCKED"}]}})
        try:
            C._crux_post("queryRecord", {"origin": "https://x"}, "k")
            got = "通った"
        except C.CruxUnavailable as e:
            got = "API_KEY_SERVICE_BLOCKED" in str(e)
        check("CrUX: 403（鍵の制限）は API が使えない扱い（理由を残す）", got, True)
    finally:
        U.urlopen = old

    # サイトもURLも全部 404 → データ無し。遅いとは言わず、要対応も出さず、CRUX_OK=unset
    with fake(C, lambda m, b: None, urls=["https://x.example/a/"]) as (calls, td):
        rc, out = _run(C)
        check("CrUX: 全部データ無しは CRUX_OK=unset（no にしない）", ("CRUX_OK=unset" in out, "CRUX_OK=no" in out), (True, False))
        check("CrUX: データ無しを要対応にしない", "要対応" in out, False)
        check("CrUX: データ無しのときは履歴を取りに行かない", [c for c in calls if c[0] == "queryHistoryRecord"], [])
        check("CrUX: origin と URL の PHONE/DESKTOP を聞く", sorted({(c[1], c[2]) for c in calls}),
              [("https://x.example", "DESKTOP"), ("https://x.example", "PHONE"),
               ("https://x.example/a/", "DESKTOP"), ("https://x.example/a/", "PHONE")])
        rec = json.loads((td / "own-x.json").read_text(encoding="utf-8"))
        check("CrUX の記録: データ無しは nodata として残す", {t["status"] for t in rec["targets"]}, {"nodata"})
        check("CrUX の記録: データ無しを0や遅い値で埋めない", any("current" in t for t in rec["targets"]), False)
        import cwv_check as C2
        html = C2.crux_html("own-x")
        check("月次の節: データが無ければ「遅いという意味ではありません」と書き、×を付けない",
              ("遅いという意味ではありません" in html, " ×" in html), (True, False))
        check("CrUX: 終了コードは0", rc, 0)

    # サイト全体の PHONE が悪化（基準を割った）、DESKTOP は良好、URL はデータ無し → 要対応1件・CRUX_OK=no
    def ans(method, body):
        if body.get("url"):
            return None
        bad = body["formFactor"] == "PHONE"
        if method == "queryRecord":
            return _record(3100 if bad else 1200, 150, "0.02")
        lcp = [2000] * 22 + [2300, 2400, 3100] if bad else [1200] * 25
        return _history(lcp, [150] * 25, ["0.02"] * 25)
    with fake(C, ans, urls=["https://x.example/a/"]) as (calls, td):
        rc, out = _run(C)
        req = [ln for ln in out.splitlines() if ln.startswith("要対応")]
        check("CrUX: 悪化を要対応に出す（1件・サイト全体の PHONE の LCP）", (len(req), "PHONE" in req[0] if req else None,
              "LCP" in req[0] if req else None), (1, True, True))
        check("CrUX: 悪化があれば CRUX_OK=no・終了コード0", ("CRUX_OK=no" in out, rc), (True, 0))
        check("CrUX: 履歴は25週を頼む（データのある origin の2件だけ）",
              sorted((c[2], c[3]) for c in calls if c[0] == "queryHistoryRecord"), [("DESKTOP", 25), ("PHONE", 25)])
        html = C.crux_html("own-x")
        check("月次の節: 基準を割った指標に ×、データ無しのページ数を書く",
              (" ×" in html, "1 ページはアクセスが少なくデータがありません" in html), (True, True))

    # 鍵の制限（403）→ unknown・終了コード1。鍵が無い → unset・0
    def blocked(method, body):
        raise C.CruxUnavailable("403 API_KEY_SERVICE_BLOCKED")
    with fake(C, blocked):
        rc, out = _run(C)
        check("CrUX: API が使えなければ CRUX_OK=unknown・終了コード1", ("CRUX_OK=unknown" in out, rc), (True, 1))
    with fake(C, lambda m, b: None, key=""):
        rc, out = _run(C)
        check("CrUX: 鍵が無ければ CRUX_OK=unset・終了コード0", ("CRUX_OK=unset" in out, rc), (True, 0))


def test_crux_privacy_and_wiring():
    def ignored(rel):
        return subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", rel]).returncode == 0
    check("CrUX の記録: お客様の社のファイルは public に置かない", ignored("data/cwv_crux/client-x.json"), True)
    check("CrUX の記録: 自社3サイトはコミットできる",
          [ignored(f"data/cwv_crux/{s}.json") for s in ("ai-lab", "corporate", "subsidy")], [False, False, False])
    src = (ROOT / "scripts" / "cwv_check.py").read_text(encoding="utf-8")
    check("CrUX: 置き場は data/cwv_crux（site/ など公開される所に書かない）",
          'CRUX_DIR = ROOT / "data" / "cwv_crux"' in src and "site/" not in src[src.index("def save_crux"):src.index("def run_crux")], True)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    i = wf.index("python scripts/cwv_check.py")
    line = wf[i:wf.index("\n", i)]
    check("週次: 実測の工程が CrUX まで回り（--no-crux を付けない）、要対応を findings へ流す",
          ("--no-crux" not in line, "/tmp/measure.txt" in line,
           "grep '^要対応' /tmp/measure.txt >> automation/logs/findings.txt" in wf[i:i + 4000]), (True, True, True))
    check("週次: お客様の CrUX の記録をキャッシュに残す（自社3サイトはコミット）",
          "cwv-crux-" in wf and "!data/cwv_crux/ai-lab.json" in wf, True)
    mw = (ROOT / ".github" / "workflows" / "monthly-report.yml").read_text(encoding="utf-8")
    check("月次: お客様の CrUX の記録をキャッシュから戻してからレポートを作る",
          "cwv-crux-" in mw and mw.index("cwv-crux-") < mw.index("月次レポート生成"), True)
    mr = (ROOT / "scripts" / "monthly_report.py").read_text(encoding="utf-8")
    check("月次レポート: 実際の利用者の表示速度の節を差し込む",
          "_cwv.crux_html(SITE_ID)" in mr and "{crux_pages}" in mr, True)
