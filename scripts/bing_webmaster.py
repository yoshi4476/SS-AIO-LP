# -*- coding: utf-8 -*-
"""Bing Webmaster Tools の API で、新しい・更新したページと sitemap を Bing に送る

IndexNow（notify_indexnow.py）は「変わった」と知らせるだけで、Bing 側の登録や
送信の枠は見えない。こちらは Bing Webmaster に登録したサイトとして直接送るので、
未登録のサイト・鍵の誤りがエラーとして返り、気づける。

使い方:
    python scripts/bing_webmaster.py --site <id>    # 本日公開・更新のURL＋sitemap（公開直後）
    python scripts/bing_webmaster.py --weekly       # 全サイトの直近7日の更新URL＋sitemap（週次）
    python scripts/bing_webmaster.py <URL> ...      # 指定URL（reindex の再送から呼ぶ）

鍵: 環境変数 BING_WEBMASTER_API_KEY（.env と GitHub Secrets）。鍵が無ければ何もせず BING_OK=unset。
印: BING_OK=yes / no（要対応あり）/ unknown（すべて送れなかった）/ unset。終了コードは常に0（8.7節）。

公式の根拠:
  URL送信   https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.submiturlbatch
            （1回500件まで。ただし残りの枠が少なければそちらが上限）
  送信枠    https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.geturlsubmissionquota
            （DailyQuota / MonthlyQuota）
  sitemap   https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.submitfeed
            （SubmitSitemap という名の操作は無く、SubmitFeed が sitemap を受ける）
  エラー    https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.apierrorcode
  鍵の発行  https://learn.microsoft.com/en-us/bingwebmaster/getting-access
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

API = "https://ssl.bing.com/webmaster/api.svc/json/"
STATE = ROOT / "data" / "bing_submit.json"
BATCH_MAX = 500
KEEP_DAYS = 7
WEEK_DAYS = 7

# ApiErrorCode。公式は「サイトが未登録・未確認」のときの番号を明記していないため、
# 権限・未検出の系統（NotFound / NotAllowed / NotAuthorized）をまとめて未登録とみなす
UNREGISTERED = {11, 13, 14}
INVALID_KEY = {3, 10}
THROTTLED = {4, 5}


class BingError(Exception):
    def __init__(self, status, code, message):
        super().__init__(f"HTTP {status} ErrorCode={code} {message}"[:160])
        self.status, self.code, self.message = status, code, message


def api_key():
    key = os.environ.get("BING_WEBMASTER_API_KEY", "").strip()
    if key:
        return key
    import notify_indexnow as NI
    return NI.load_env().get("BING_WEBMASTER_API_KEY", "").strip()


def _request(method, name, key, query=None, body=None):
    """1回の呼び出し。鍵はURLの引数に載るため、URLを例外や出力に含めない"""
    q = dict(query or {}, apikey=key)
    url = API + name + "?" + urllib.parse.urlencode(q)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "ignore")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            j = json.loads(raw)
        except ValueError:
            j = {}
        raise BingError(e.code, j.get("ErrorCode"), str(j.get("Message") or e.reason)[:120]) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise BingError(0, None, type(e).__name__) from None


def classify(err):
    if err.code in UNREGISTERED or "NotAuthorized" in (err.message or ""):
        return "unregistered"
    if err.code in INVALID_KEY:
        return "invalid_key"
    if err.code in THROTTLED:
        return "throttled"
    return "error"


def quota(site_url, key):
    d = _request("GET", "GetUrlSubmissionQuota", key, {"siteUrl": site_url}).get("d") or {}
    vals = [v for v in (d.get("DailyQuota"), d.get("MonthlyQuota")) if isinstance(v, int)]
    return min(vals) if vals else 0


def submit_urls(site_url, urls, key):
    _request("POST", "SubmitUrlBatch", key, body={"siteUrl": site_url, "urlList": urls})


def submit_feed(site_url, feed_url, key):
    _request("POST", "SubmitFeed", key, body={"siteUrl": site_url, "feedUrl": feed_url})


def load_state():
    try:
        s = json.loads(STATE.read_text(encoding="utf-8")) if STATE.is_file() else {}
    except (OSError, ValueError):
        s = {}
    s.setdefault("sent", {})
    s.setdefault("sites", {})
    return s


def save_state(s, today):
    cut = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS)).isoformat()
    s["sent"] = {u: d for u, d in s["sent"].items() if d >= cut}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


def send_site(sid, domain, urls, key, state, today, sitemap=True):
    """1サイト分を送る。同じ日に送ったURL・sitemapは送らず、枠の残りの範囲だけ送る"""
    site_url = f"https://{domain}/"
    feed = f"https://{domain}/sitemap.xml"
    todo = [u for u in dict.fromkeys(urls) if state["sent"].get(u) != today]
    res = {"site": sid, "domain": domain, "sent": 0, "skipped_today": len(set(urls)) - len(todo),
           "over_quota": 0, "feed": False, "state": "ok", "msg": ""}
    try:
        if todo:
            left = quota(site_url, key)
            go = todo[:max(0, min(left, BATCH_MAX))]
            res["over_quota"] = len(todo) - len(go)
            if go:
                submit_urls(site_url, go, key)
                state["sent"].update({u: today for u in go})
                res["sent"] = len(go)
        if sitemap and state["sent"].get(feed) != today:
            submit_feed(site_url, feed, key)
            state["sent"][feed] = today
            res["feed"] = True
    except BingError as e:
        res["state"], res["msg"] = classify(e), str(e)
    state["sites"][sid] = {"state": res["state"], "at": today, "msg": res["msg"]}
    return res


def report(results):
    """印と要対応の行を出す。未登録・鍵の誤りは人が手を動かすまで消えないので要対応にする"""
    bad = []
    for r in results:
        line = (f"  {r['site']}: URL {r['sent']}件を送信・本日送信済み {r['skipped_today']}件は省略"
                f"{'・枠を超えるため ' + str(r['over_quota']) + '件は次回' if r['over_quota'] else ''}"
                f"{'・sitemap 送信' if r['feed'] else ''}")
        print(line if r["state"] == "ok" else f"  {r['site']}: 送れません（{r['state']}・{r['msg']}）")
        if r["state"] == "unregistered":
            bad.append(f"要対応: Bing Webmaster に未登録 — {r['domain']}（サイトを追加して所有権を確認してください）")
        elif r["state"] == "invalid_key":
            bad.append("要対応: Bing Webmaster の API キーが無効です（BING_WEBMASTER_API_KEY を作り直してください）")
    for b in dict.fromkeys(bad):
        print(b)
    if bad:
        print("BING_OK=no")
    elif results and all(r["state"] != "ok" for r in results):
        print("BING_OK=unknown")
    else:
        print("BING_OK=yes")


def sitemap_known(cfg):
    import notify_indexing as NX
    return {u.rstrip("/") + "/" for u in NX.sitemap_of(cfg)}


def recent_urls(cfg, days):
    """直近 days 日に公開・更新した記事のうち、sitemap に載っているもの（まだ配信されていないURLは送らない）"""
    import notify_indexing as NX
    known = sitemap_known(cfg)
    return [u for u in NX.todays_urls(cfg, days) if u.rstrip("/") + "/" in known]


def jobs_for_urls(urls, cfgs):
    """指定URLをサイトごとに束ねる。登録していないドメインのURLは送らない"""
    by_dom = {c["domain"]: sid for sid, c in cfgs.items()}
    out = {}
    for u in urls:
        host = urllib.parse.urlsplit(u.strip()).netloc
        if host in by_dom:
            out.setdefault((by_dom[host], host), []).append(u.strip())
        else:
            print(f"  {host}: sites/*.json に無いドメインのため送りません")
    return out


def send_urls(urls, sitemap=False):
    """他の工程（reindex の再送）から呼ぶ入口。鍵が無ければ何もしない"""
    key = api_key()
    if not key or not urls:
        return []
    import sites as S
    state, today = load_state(), date.today().isoformat()
    res = [send_site(sid, dom, us, key, state, today, sitemap)
           for (sid, dom), us in jobs_for_urls(urls, S.load_all()).items()]
    save_state(state, today)
    return res


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    key = api_key()
    if not key:
        print("BING_WEBMASTER_API_KEY 未設定のため送りません")
        print("BING_OK=unset")
        return 0
    import sites as S
    cfgs = S.load_all()
    state, today = load_state(), date.today().isoformat()
    only = argv[argv.index("--site") + 1] if "--site" in argv and len(argv) > argv.index("--site") + 1 else ""
    urls = [a for a in argv if a.startswith("http")]
    results = []
    if urls:
        for (sid, dom), us in jobs_for_urls(urls, cfgs).items():
            results.append(send_site(sid, dom, us, key, state, today, sitemap=False))
    else:
        days = WEEK_DAYS if "--weekly" in argv else 1
        for sid, cfg in cfgs.items():
            if only and sid != only:
                continue
            results.append(send_site(sid, cfg["domain"], recent_urls(cfg, days), key, state, today))
    save_state(state, today)
    report(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
