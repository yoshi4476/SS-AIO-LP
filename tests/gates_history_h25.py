# -*- coding: utf-8 -*-
"""Bing への送り切り（--backfill）の門（2026-10-05）。

鍵が無かった間の記事は Bing にほぼ送られていない。本番 sitemap の未送信URLを毎日送るにあたり、
二度送らない・枠を10件残す・新しい順・送り切ったら何もしない・毎日のワークフローに入っている、を固定する。
本物の Bing API と本番 sitemap には触れない（_request を偽物に差し替え、記録は一時ファイルに書く）。
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


class _Fake:
    def __init__(self, quota=100):
        self.quota, self.calls = quota, []

    def __call__(self, method, name, key, query=None, body=None):
        site = (query or {}).get("siteUrl") or (body or {}).get("siteUrl")
        self.calls.append((name, site, list((body or {}).get("urlList") or [])))
        if name == "GetUrlSubmissionQuota":
            return {"d": {"DailyQuota": self.quota, "MonthlyQuota": 2800}}
        return {"d": None}


@contextlib.contextmanager
def _patched(fake, entries):
    import bing_webmaster as BW
    saved = (BW._request, BW.STATE, BW.BACKFILL, BW.api_key, BW.sitemap_entries, BW.client_cfgs)
    with tempfile.TemporaryDirectory() as d:
        BW._request, BW.STATE, BW.BACKFILL = fake, Path(d) / "s.json", Path(d) / "b.json"
        BW.api_key = lambda: "dummy-key"
        BW.sitemap_entries = lambda dom: entries.get(dom, [])
        # 自社だけで確かめる。本物の sites/ に同意済みのお客様の社が増えると GetUserSites を呼び、呼び出しの数が変わる
        BW.client_cfgs = lambda: {}
        try:
            yield BW
        finally:
            BW._request, BW.STATE, BW.BACKFILL, BW.api_key, BW.sitemap_entries, BW.client_cfgs = saved


def _run(BW, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        BW.main(argv)
    return buf.getvalue()


def _sent(fake):
    return [u for n, _, us in fake.calls if n == "SubmitUrlBatch" for u in us]


def test_bing_backfill_quota_order_dedupe_and_workflow():
    print("\n■ Bing の送り切り: 枠を10件残す・新しい順・二度送らない・送り切ったら何もしない")
    import sites as S
    cfgs = S.load_all()
    sid = S.own_ids()[0]
    dom = cfgs[sid]["domain"]
    # lastmod が古い順に並べた sitemap。p0 が最も古い
    entries = {dom: [(f"https://{dom}/p{i}/", f"2026-0{1 + i // 30}-{1 + i % 28:02d}") for i in range(130)]}
    newest = [u for u, _ in sorted(entries[dom], key=lambda e: e[1], reverse=True)]

    fake = _Fake(quota=100)
    with _patched(fake, entries) as BW:
        out = _run(BW, ["--backfill", "--dry-run", "--site", sid])
        check("dry-run は Bing に送らず記録も書かない",
              (_sent(fake), BW.BACKFILL.is_file()), ([], False))
        check("dry-run でも送る予定の件数と残りを出す", "送る予定 90件・残り 40件" in out, True)

        fake.calls.clear()
        out = _run(BW, ["--backfill", "--site", sid])
        first = _sent(fake)
        check("枠100から10件残して90件だけ送る", len(first), 90)
        check("lastmod の新しい順に送る", first, newest[:90])
        check("送り切りまでの残りと見込み日数を出す", "残り 40件（あと1日）" in out and "BING_BACKFILL_LEFT=40" in out, True)
        check("送った記録が送り切りの記録に残る", len(BW.load_backfill()["sent"]), 90)

        fake.calls.clear()
        _run(BW, ["--backfill", "--site", sid])
        check("次の回は送ったURLを二度送らず、残りだけ送る", sorted(_sent(fake)), sorted(newest[90:]))

        fake.calls.clear()
        out = _run(BW, ["--backfill", "--site", sid])
        check("送り切ったら Bing を呼ばず BING_OK=yes とだけ出す", (fake.calls, out.strip()), ([], "BING_OK=yes"))

    fake = _Fake(quota=10)
    with _patched(fake, entries) as BW:
        st = BW.load_state()
        st["sent"][newest[0]] = "2026-10-01"
        BW.save_state(st, "2026-10-05")
        out = _run(BW, ["--backfill", "--site", sid])
        check("枠の残りが10件以下なら送らない（その日の新しい記事のため）", _sent(fake), [])
        check("枠切れは要対応にしない", "要対応" in out, False)
        check("週次・公開直後に送ったURLも送り切りでは送ったものとして扱う",
              BW.load_backfill()["sent"].get(newest[0]), "2026-10-01")

    with _patched(_Fake(), {}) as BW:
        def boom(*a, **k):
            raise BW.BingError(500, 1, "InternalError")
        BW._request = boom
        out = _run(BW, ["--backfill", "--site", sid])
        check("sitemap が空でも Bing を呼ばない（送るものが無い）", "BING_OK=yes" in out, True)
    with _patched(_Fake(), entries) as BW:
        BW._request = boom
        out = _run(BW, ["--backfill", "--site", sid])
        check("枠切れ・鍵の誤り以外のエラーは要対応", ("要対応: Bing への送り切りが失敗しました" in out, "BING_OK=no" in out), (True, True))
        check("出力に鍵を出さない", "dummy-key" in out or "apikey" in out, False)

    import findings as F
    check("BING_OK=no は findings の判定で要対応", F.judge("BING_OK=no", 0), "要対応")

    sh = (ROOT / ".github" / "workflows" / "selfheal.yml").read_text(encoding="utf-8")
    heal = sh.split("\n  heal:")[1].split("\n  rerun:")[0]
    check("毎日の selfheal（heal）で --backfill を回し、鍵を渡す",
          "bing_webmaster.py --backfill" in heal and "BING_WEBMASTER_API_KEY: ${{ secrets.BING_WEBMASTER_API_KEY }}" in heal, True)
    check("送り切りの記録をコミットして push する",
          "git add data/bing_backfill.json" in heal and "git push" in heal.split("bing_webmaster.py --backfill")[1].split("- name:")[0], True)
    check("要対応を通知本文へ足す",
          "grep '^要対応' >> automation/logs/findings.txt" in heal.split("bing_webmaster.py --backfill")[1].split("- name:")[0], True)
    check("送り切りの記録は .gitignore に入れない（二度送らないための記録を残す）",
          "data/bing_backfill.json" in (ROOT / ".gitignore").read_text(encoding="utf-8"), False)
