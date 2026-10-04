# -*- coding: utf-8 -*-
"""Bing Webmaster への送信の門（2026-10-05）。

IndexNow は送りっぱなしで、Bing 側の登録や枠が見えない。Bing Webmaster API で直接送るにあたり、
鍵が無ければ何もしない・枠を超えない・同じURLを同じ日に二度送らない・未登録のサイトを要対応にする、を固定する。
本物の Bing API は呼ばない（_request を偽物に差し替え、記録は一時ファイルに書く）。
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


class _Fake:
    """Bing の偽物。呼ばれた操作を残し、枠と未登録のサイトを決められる"""

    def __init__(self, quota=10, unregistered=()):
        self.quota, self.unregistered, self.calls = quota, set(unregistered), []

    def __call__(self, method, name, key, query=None, body=None):
        import bing_webmaster as BW
        site = (query or {}).get("siteUrl") or (body or {}).get("siteUrl")
        self.calls.append((name, site, list((body or {}).get("urlList") or [])))
        if site in self.unregistered:
            raise BW.BingError(400, 14, "ERROR!!! NotAuthorized")
        if name == "GetUrlSubmissionQuota":
            return {"d": {"DailyQuota": self.quota, "MonthlyQuota": 100}}
        return {"d": None}


@contextlib.contextmanager
def _patched(fake, key="dummy-key"):
    import bing_webmaster as BW
    saved = (BW._request, BW.STATE, BW.api_key)
    with tempfile.TemporaryDirectory() as d:
        BW._request, BW.STATE = fake, Path(d) / "bing_submit.json"
        BW.api_key = lambda: key
        try:
            yield BW
        finally:
            BW._request, BW.STATE, BW.api_key = saved


def _out(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a, **k)
    return buf.getvalue()


def test_bing_webmaster_unset_quota_dedupe_and_unregistered():
    print("\n■ Bing Webmaster: 鍵が無ければ何もしない・枠を超えない・同じ日に二度送らない・未登録は要対応")
    today = "2026-10-05"

    fake = _Fake()
    with _patched(fake, key="") as BW:
        out = _out(BW.main, ["--weekly"])
        check("鍵が無いと BING_OK=unset", "BING_OK=unset" in out, True)
        check("鍵が無いと Bing を1回も呼ばない", fake.calls, [])
        check("鍵が無いと他の工程からの呼び出しも何もしない", BW.send_urls(["https://ai.7senses.co.jp/a/"]), [])

    urls = [f"https://ex.example/p{i}/" for i in range(8)]
    fake = _Fake(quota=3)
    with _patched(fake) as BW:
        st = BW.load_state()
        r = BW.send_site("cl-x", "ex.example", urls, "k", st, today)
        sent = [u for n, _, us in fake.calls if n == "SubmitUrlBatch" for u in us]
        check("枠（DailyQuota 3）を超えて送らない", (len(sent), r["over_quota"]), (3, 5))
        check("sitemap は SubmitFeed で送る", [n for n, _, _ in fake.calls if n == "SubmitFeed"], ["SubmitFeed"])

        fake.calls.clear()
        r2 = BW.send_site("cl-x", "ex.example", urls[:3], "k", st, today)
        check("同じ日に送ったURLと sitemap は二度送らない",
              ([n for n, _, _ in fake.calls], r2["skipped_today"]), ([], 3))
        BW.save_state(st, today)
        st2 = BW.load_state()
        check("送った記録が data/ の記録に残り、次の回でも効く", all(st2["sent"].get(u) == today for u in urls[:3]), True)
        r3 = BW.send_site("cl-x", "ex.example", urls[:3], "k", st2, "2026-10-06")
        check("翌日は同じURLをまた送れる", r3["sent"], 3)

    fake = _Fake(unregistered={"https://cl-new.example/"})
    with _patched(fake) as BW:
        st = BW.load_state()
        res = [BW.send_site("cl-new", "cl-new.example", ["https://cl-new.example/a/"], "k", st, today),
               BW.send_site("ai-lab", "ai.7senses.co.jp", ["https://ai.7senses.co.jp/a/"], "k", st, today)]
        out = _out(BW.report, res)
        check("未登録のサイトは unregistered に分ける", res[0]["state"], "unregistered")
        check("未登録は要対応の行を出す（findings.txt へ足す形）",
              "要対応: Bing Webmaster に未登録 — cl-new.example" in out, True)
        check("要対応があれば BING_OK=no", "BING_OK=no" in out, True)
        check("未登録のサイトがあっても他のサイトは送る", res[1]["sent"], 1)
        check("出力に鍵を出さない", "dummy-key" in out or "apikey" in out, False)

    import findings as F
    check("BING_OK=no は findings の判定で要対応", F.judge("BING_OK=no", 0), "要対応")
    check("BING_OK=unset は要対応にしない", F.judge("BING_OK=unset", 0), "問題なし")

    wf = ROOT / ".github" / "workflows"
    pm = (wf / "pipeline-multi.yml").read_text(encoding="utf-8")
    wk = (wf / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("記事CI: 公開直後の通知の所で Bing に送り、鍵を渡す",
          "bing_webmaster.py --site" in pm and "secrets.BING_WEBMASTER_API_KEY" in pm, True)
    check("週次CI: findings より前に --weekly を回し、要対応を通知本文へ足す",
          0 < wk.find("bing_webmaster.py --weekly") < wk.find("python scripts/findings.py"), True)
    check("週次CI: reindex の再送の工程にも鍵を渡す",
          wk.count("BING_WEBMASTER_API_KEY: ${{ secrets.BING_WEBMASTER_API_KEY }}") >= 2, True)
    check("reindex の再送が Bing にも送る",
          "_bing([u for u, _ in todo])" in (ROOT / "scripts" / "reindex.py").read_text(encoding="utf-8"), True)
    check("送信記録はコミットしない（.gitignore）",
          "data/bing_submit.json" in (ROOT / ".gitignore").read_text(encoding="utf-8"), True)
