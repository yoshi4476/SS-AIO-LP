# -*- coding: utf-8 -*-
"""表示速度の週次の実測（cwv_check）が、ラボ値の1回の揺れで「要対応」を出していた（2026-10-12 の週次点検）。

  1. PageSpeed のラボ値（Lighthouse の見積もり）は1回ごとに大きく揺れる。2026-10-12 の AI集客ラボのトップは、
     同じ日に LCP 4.7秒・1.7秒・1.7秒。最初の描画が load より遅れる回に、load の1.2秒後に読む計測タグ（169KB）が
     描画より先に入り、見積もりにその分が足されていた。1回の値で判定せず、基準を割った回だけ測り直して
     3回の中央値で判定する。本当に遅いページ（総合25・LCP 11.7秒と14.9秒）は2回で決まって拾う
  2. 同じURLを続けて頼むと PageSpeed は直前の結果（同じ fetchTime）を返す。それを2回目に数えると、
     1回目の悪い値が2票になり、測り直しの意味が無くなる
  3. 記事を1本測るはずが、sitemap を Python の既定の名乗りで取りに行き Cloudflare に 403 で断られ、
     トップしか測っていなかった（data/cwv.jsonl はトップだけ）
  4. CrUX API が使えない理由（鍵のプロジェクトで API が無効）が通知に届かず「測れませんでした」だけだった
  5. AI集客ラボのトップの計測タグは、load の1.2秒後かつ最初の描画の後に読む

本物の PageSpeed・CrUX・HTTP は使わない。架空の社（client-zz・zz.example）で確かめる
"""
import contextlib
import io
import json
import re
import sys
import tempfile
import urllib.error
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _run(lcp, source="lab", fetched=None):
    return {"url": "u", "strategy": "mobile", "source": source, "LCP": lcp, "CLS": 0, "INP": None,
            "score": 50, "_fetched": fetched or f"t{lcp}"}


class _Clock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def _remeasure(C, first, answers):
    """1回目が first のページを、answers の順に返す偽の計測で測り直す。(runs, 測った回数, 待った秒の list, page)"""
    clock, calls = _Clock(), []

    def fake(url):
        calls.append(url)
        a = answers[len(calls) - 1]
        if isinstance(a, Exception):
            raise a
        return a
    page = {"url": "https://own.zz.example/", "runs": [first], "at": clock.now()}
    C.remeasure([page], measure_fn=fake, clock=clock.now, sleep=clock.sleep)
    return page["runs"], len(calls), clock.slept, page


def test_lab_value_is_judged_by_median_not_one_run():
    import cwv_check as C

    # 良い例（揺れ）: 実例 2026-10-12 の AI集客ラボのトップ。1回目 4.7秒 → 測り直すと 1.7秒・1.7秒 → 基準内
    runs, n, slept, _ = _remeasure(C, _run(4734), [_run(1695), _run(1672)])
    check("速度: 揺れて1回だけ基準を割ったページは、測り直して中央値で基準内（要対応にしない）",
          (len(runs), n, C.lab_verdict(runs)[0]), (3, 2, []))
    check("速度: 同じURLは PSI_GAP 秒あけて測り直す（続けて頼むと直前の結果が返る）",
          all(s >= C.PSI_GAP - 1e-6 for s in slept) and len(slept) == 2, True)

    # 悪い例（本当に遅い）: 実例 2026-10-12 のお客様扱いの社のトップ（総合25）。11.7秒 → 14.9秒 で2回とも割れば決まる
    runs, n, _, _ = _remeasure(C, _run(11706), [_run(14900), _run(13000)])
    over, med = C.lab_verdict(runs)
    check("速度: 本当に遅いページは拾う（2回とも基準を割れば、3回目を待たずに決める）",
          (over, len(runs), n, round(med["LCP"])), (["LCP"], 2, 1, 13303))

    # 3回中2回が遅いページは拾う（揺れでも、遅い回の方が多ければ直す対象）
    runs, _, _, _ = _remeasure(C, _run(4733), [_run(1695), _run(4355)])
    check("速度: 3回中2回が基準を割れば要対応（中央値 4.4秒）", (C.lab_verdict(runs)[0], round(C.lab_verdict(runs)[1]["LCP"])),
          (["LCP"], 4355))

    # 1回目が基準内なら測り直さない（PageSpeed の回数を増やさない）
    runs, n, _, _ = _remeasure(C, _run(1843), [_run(9999)])
    check("速度: 1回目が基準内なら測り直さない", (len(runs), n, C.lab_verdict(runs)[0]), (1, 0, []))

    # 実利用者の値（field）は28日の集計で揺れないので、測り直さずに判定する
    runs, n, _, _ = _remeasure(C, _run(3100, source="field"), [_run(1000)])
    check("速度: 実利用者の値は測り直さない（基準を割れば1回で要対応）", (n, C.lab_verdict(runs)[0]), (0, ["LCP"]))

    # PageSpeed の控え（同じ fetchTime）が返った回は数えない。数えると1回目の悪い値が2票になる
    first = _run(4734, fetched="2026-10-12T03:27:28.642Z")
    runs, n, _, page = _remeasure(C, first, [_run(4734, fetched="2026-10-12T03:27:28.642Z"), _run(1672)])
    check("速度: 直前の控えが返った回は数えず、新しい結果だけを足す",
          (n, len(runs), page.get("cached"), C.settled(runs)), (2, 2, 1, False))

    # 測り直しが失敗しても止まらず、測れた分で判定する（1回だけなら、その値で判定）
    runs, n, _, page = _remeasure(C, _run(4000), [RuntimeError("429"), RuntimeError("429")])
    check("速度: 測り直しが失敗しても止まらず、測れた値で判定する", (len(runs), len(page.get("errors", [])),
                                                    C.lab_verdict(runs)[0]), (1, 2, ["LCP"]))


@contextlib.contextmanager
def _fake_main(C, answers, urls):
    """main() の計測・対象サイト・記録先・待ちを差し替える。answers[url] は返す値の list"""
    import client_private as CP
    import sites as S
    old = (C.measure, C.sample_urls, S.load_all, S.is_client, S.public_id, C.LOG, C.time.sleep, sys.argv,
           C.PSI_GAP, CP.append_jsonl)
    seen = {}

    def measure(url):
        i = seen.get(url, 0)
        seen[url] = i + 1
        return answers[url][i]
    sites_ = {"own-zz": {"domain": "own.zz.example"}, "client-zz": {"domain": "zz.example", "public_id": "c0000zz00"}}
    with tempfile.TemporaryDirectory() as td:
        log = Path(td) / "cwv.jsonl"

        def append(p, row, sid=None):
            with Path(p).open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        C.measure, C.sample_urls = measure, (lambda cfg: urls[cfg["domain"]])
        S.load_all = lambda: sites_
        S.is_client = lambda sid: sid == "client-zz"
        S.public_id = lambda sid: sites_.get(sid, {}).get("public_id") or sid
        C.LOG, C.time.sleep, sys.argv, C.PSI_GAP, CP.append_jsonl = log, (lambda s: None), ["cwv_check.py", "--no-crux"], 0, append
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = C.main()
            yield rc, buf.getvalue(), log, seen
        finally:
            (C.measure, C.sample_urls, S.load_all, S.is_client, S.public_id, C.LOG, C.time.sleep, sys.argv,
             C.PSI_GAP, CP.append_jsonl) = old


def test_weekly_flags_only_pages_that_stay_slow():
    import cwv_check as C
    own, art, cli = "https://own.zz.example/", "https://own.zz.example/blog/a/", "https://zz.example/"
    answers = {own: [_run(4734), _run(1695), _run(1672)], art: [_run(1900)],
               cli: [_run(11706), _run(14900)]}
    with _fake_main(C, answers, {"own.zz.example": [own, art], "zz.example": [cli]}) as (rc, out, log, seen):
        req = [ln for ln in out.splitlines() if ln.startswith("要対応")]
        check("速度（週次）: 揺れたページは要対応にせず、本当に遅いページだけ要対応にする（1件）",
              (len(req), "c0000zz00" in (req[0] if req else ""), "own-zz" in out and any("own-zz" in r for r in req)),
              (1, True, False))
        check("速度（週次）: 要対応に何回の中央値かを添える", "2回の中央値: LCP 13.3秒" in (req[0] if req else ""), True)
        check("速度（週次）: お客様の社は公開の id で出し、ドメインを出さない", "zz.example/" in out.replace("own.zz.example", ""),
              False)
        check("速度（週次）: 印は CWV_OK=no・終了コード0", ("CWV_OK=no" in out, rc), (True, 0))
        check("速度（週次）: 測り直しの回数（揺れたページ3回・記事1回・遅いページ2回）", (seen[own], seen[art], seen[cli]), (3, 1, 2))
        rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
        check("速度（週次）: 測った回はすべて記録し、内部の印（_fetched）は記録の書式に入れない",
              (len(rows), any(k.startswith("_") for r in rows for k in r)), (6, False))
    # 全部基準内 → 要対応なし・CWV_OK=yes
    answers = {own: [_run(1800)], art: [_run(2000)], cli: [_run(2100)]}
    with _fake_main(C, answers, {"own.zz.example": [own, art], "zz.example": [cli]}) as (rc, out, log, seen):
        check("速度（週次）: 全部基準内なら要対応なし・CWV_OK=yes・測り直さない",
              ("要対応" in out, "CWV_OK=yes" in out, sum(seen.values())), (False, True, 3))


def test_sample_urls_reaches_the_sitemap():
    """Python の既定の名乗りは Cloudflare が 403 で断る。名乗りを付けて sitemap を取り、記事を1本足す"""
    import urllib.request as U
    import cwv_check as C
    old = U.urlopen
    sm = ("<urlset><url><loc>https://zz.example/</loc></url><url><loc>https://zz.example/blog/a/</loc></url>"
          "<url><loc>https://zz.example/blog/b/</loc></url></urlset>")

    def fake(req, timeout=None):
        ua = req.get_header("User-agent") if isinstance(req, U.Request) else None
        if not ua or "Python-urllib" in ua:
            raise urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(b""))
        return io.BytesIO(sm.encode("utf-8"))
    try:
        U.urlopen = fake
        check("速度: sitemap を名乗り付きで取り、トップと記事1本を測る", C.sample_urls({"domain": "zz.example"}),
              ["https://zz.example/", "https://zz.example/blog/b/"])
    finally:
        U.urlopen = old


def test_crux_unavailable_tells_what_to_do():
    import cwv_check as C
    import sites as S
    old = (C._crux_post, C._key, S.load_all)
    err = ("403 SERVICE_DISABLED Chrome UX Report API has not been used in project 1 before or it is disabled.")

    def post(method, body, k):
        raise C.CruxUnavailable(err)
    try:
        C._crux_post, C._key, S.load_all = post, (lambda names=(): "k"), (lambda: {"own-zz": {"domain": "own.zz.example"}})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = C.run_crux("")
        out = buf.getvalue()
    finally:
        C._crux_post, C._key, S.load_all = old
    req = [ln for ln in out.splitlines() if ln.startswith("要対応")]
    check("CrUX: API が無効なときは、有効にする作業を要対応で知らせる（印は unknown・終了コード1のまま）",
          (len(req), "Chrome UX Report API を有効" in (req[0] if req else ""), "CRUX_API_KEY" in (req[0] if req else ""),
           "CRUX_OK=unknown" in out, rc), (1, True, True, True, 1))
    check("CrUX: 鍵の制限（API_KEY_SERVICE_BLOCKED）は制限の直し方を書く",
          "APIの制限" in C.crux_fix("403 API_KEY_SERVICE_BLOCKED"), True)


def test_top_page_loads_tag_after_first_paint():
    """AI集客ラボのトップは最初の描画が load より1〜2秒遅れる回がある。計測タグを描画より先に読んだ回だけ
    Lighthouse の LCP が 4.7秒になった（同じ日に描画の後に読んだ回は 1.7秒）"""
    src = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    m = re.search(r"<script>window\.dataLayer=.*?</script>", src, re.S)
    s = m.group(0) if m else ""
    check("速度: トップの計測タグは load の1.2秒後、かつ最初の描画（first-contentful-paint）の後に読む",
          ("},1200);" in s, "first-contentful-paint" in s, "setTimeout(go,5000)" in s,
           re.search(r'<script\b[^>]*\bsrc="https://www\.googletagmanager\.com/gtag/js', src) is None),
          (True, True, True, True))
