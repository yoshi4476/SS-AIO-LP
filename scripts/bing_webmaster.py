# -*- coding: utf-8 -*-
"""Bing Webmaster Tools の API で、新しい・更新したページと sitemap を Bing に送る

IndexNow（notify_indexnow.py）は「変わった」と知らせるだけで、Bing 側の登録や
送信の枠は見えない。こちらは Bing Webmaster に登録したサイトとして直接送るので、
未登録のサイト・鍵の誤りがエラーとして返り、気づける。

使い方:
    python scripts/bing_webmaster.py --site <id>    # 本日公開・更新のURL＋sitemap（公開直後）
    python scripts/bing_webmaster.py --weekly       # 全サイトの直近7日の更新URL＋sitemap（週次）
    python scripts/bing_webmaster.py <URL> ...      # 指定URL（reindex の再送から呼ぶ）
    python scripts/bing_webmaster.py --backfill [--dry-run] [--site <id>]
                                                    # 本番 sitemap の未送信URLを、その日の枠いっぱい送る（毎日・selfheal）
    python scripts/bing_webmaster.py --stats [--site <id>]
                                                    # 検索の成績を data/bing_stats/<id>.json に積む（週次）

検索の成績（--stats・2026-10-07 運用者の依頼）: Google の Search Console と並べて、Bing（ChatGPT の検索も使う索引）での
表示・クリック・主な語を月次レポートに出すため。API が返すのは日別が約70日・語とページが約9週だけなので、毎週取って
日付ごとに積み増す（前の回の分を消さない）。対象は送信と同じ send_cfgs（自社と、同意があり所有権を確かめたお客様の社）。
お客様の社のファイルは .gitignore で外し、CI のキャッシュで持ち越す（data/compete と同じ方針）。
印: BING_STATS_OK=yes / no（鍵の誤り・未登録）/ unknown（すべて取れなかった）/ unset。

送り切り（--backfill）: 鍵が無かった 2026-10-05 より前の記事は Bing にほぼ送られていない。ChatGPT の検索は
Bing の索引を使うため、自社サイトの本番 sitemap のうち一度も送っていないURLを lastmod の新しい順に送る。
各サイト10件（RESERVE）はその日の新しい記事のために残す。送った記録は data/bing_backfill.json に残して
コミットする（bing_submit.json は7日で消え、CI のキャッシュも消えうるため、送り切りの記録には使えない）。

お客様の社（2026-10-06）: ヒアリングシートで「当社の Bing アカウントで登録することに同意」を「可」にした社
（sites/<id>.json の bing_consent）だけ、当社の Bing アカウントにドメインを足し（AddSite）、確認コード
（GetUserSites の AuthenticationCode）を BingSiteAuth.xml として配信と一緒に置き（search_connect.place・publish.py）、
本番に出たら所有権を確かめる（VerifySite）。確かめられた社から、自社と同じく公開直後・週次・送り切りの対象に入る。
同意の無い社は対象外のまま（先方の Bing アカウントの持ち物）。

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
  サイトの追加・確認  https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi
            （AddSite / GetUserSites / VerifySite。確認コードは Site.AuthenticationCode）
  鍵の発行  https://learn.microsoft.com/en-us/bingwebmaster/getting-access
  検索の成績 https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.getrankandtrafficstats
            （日別の Impressions / Clicks。2023年3月24日以降はウェブ・チャット・ニュース・画像・動画・ナレッジパネルの合計）
            ….getquerystats / ….getpagestats（上位の語・ページ。QueryStats の Query / Impressions / Clicks /
            AvgImpressionPosition / AvgClickPosition / Date。「毎週更新」で、Date は週の始まり。ページは Query にURLが入る）
            日付は "/Date(1316156400000-0700)/" の形（UTC のミリ秒＋任意の時差）。実測（2026-10-07）は時差なし・UTC の0時
"""
import json
import math
import os
import re
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
BACKFILL = ROOT / "data" / "bing_backfill.json"
STATS_DIR = ROOT / "data" / "bing_stats"
MIN_N = 10                # 表示がこれ未満ならクリック率を出さない（割合は母数10以上・0.1節）
TOP_N = 10                # 月次レポートに出す語の数
RESERVE = 10
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


# ---------- お客様のドメインを当社の Bing アカウントへ足す ----------

SITE_AUTH = "BingSiteAuth.xml"
WAIT_DAYS = 7


def _host(u):
    return urllib.parse.urlsplit(u if "//" in u else "https://" + u).netloc.lower()


def client_cfgs():
    """同意のあるお客様の社（ヒアリングシートで「当社の Bing アカウントで登録することに同意」を可にした社）"""
    import sites as S
    return {sid: c for sid, c in S.load_all().items() if S.is_client(sid) and c.get("bing_consent") is True}


def user_sites(key):
    """当社の Bing アカウントにあるサイト {ドメイン: {"code", "verified"}}"""
    rows = _request("GET", "GetUserSites", key).get("d") or []
    return {_host(r["Url"]): {"code": r.get("AuthenticationCode") or "", "verified": bool(r.get("IsVerified"))}
            for r in rows if isinstance(r, dict) and r.get("Url")}


def add_site(site_url, key):
    _request("POST", "AddSite", key, body={"siteUrl": site_url})


def verify_site(site_url, key):
    return bool(_request("POST", "VerifySite", key, body={"siteUrl": site_url}).get("d"))


def auth_code(cfg, key=None, add=True):
    """お客様のドメインの確認コード（BingSiteAuth.xml に書く）。同意の無い社・鍵が無いときは ""。
    当社のアカウントにまだ無ければ足してから取る（記事の配信と同じ回で確認ファイルを置けるように）"""
    if cfg.get("bing_consent") is not True:
        return ""
    key = api_key() if key is None else key
    if not key:
        return ""
    dom = cfg["domain"].lower()
    try:
        have = user_sites(key)
        if dom not in have and add:
            add_site(f"https://{dom}/", key)
            have = user_sites(key)
    except BingError as e:
        print(f"  {cfg['id']}: Bing の確認コードを取れません（{classify(e)}）")
        return ""
    return (have.get(dom) or {}).get("code", "")


def auth_users(text):
    return re.findall(r"<user>\s*([^<\s]+)\s*</user>", text or "")


def site_auth_xml(codes, current=""):
    """BingSiteAuth.xml の中身。先方が自分の Bing アカウントのために置いた分（current）を消さずに足す"""
    users = list(dict.fromkeys(auth_users(current) + [c for c in codes if c]))
    return '<?xml version="1.0"?>\n<users>\n' + "".join(f"\t<user>{u}</user>\n" for u in users) + "</users>\n"


def live_auth(domain):
    """本番の BingSiteAuth.xml の中身（無ければ ""）"""
    try:
        req = urllib.request.Request(f"https://{domain}/{SITE_AUTH}", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def connect(cfgs, key, ledger=None, today=None):
    """同意のあるお客様の社を当社の Bing アカウントへ足し、確認ファイルが本番に出ていれば所有権を確かめる。
    state: verified / waiting（ファイル待ち）/ stuck（WAIT_DAYS を過ぎても出ない）/ failed（出ているのに確認できない）/ error。
    ledger（送り切りの記録・selfheal がコミットする）があれば、待ち始めた日を残して stuck を判定する"""
    today = today or date.today().isoformat()
    waits = ledger.setdefault("connect", {}) if ledger is not None else {}
    try:
        have = user_sites(key) if cfgs else {}
    except BingError as e:
        return [{"site": sid, "domain": c["domain"], "state": "error", "msg": str(e)} for sid, c in cfgs.items()]
    out = []
    for sid, cfg in cfgs.items():
        dom = cfg["domain"].lower()
        r = {"site": sid, "domain": dom, "state": "verified", "msg": ""}
        out.append(r)
        try:
            if dom not in have:
                add_site(f"https://{dom}/", key)
                have = user_sites(key)
            info = have.get(dom) or {}
            if info.get("verified"):
                waits.pop(sid, None)
                continue
            code = info.get("code", "")
            if not code:
                r["state"], r["msg"] = "error", "確認コードが返りません"
                continue
            if cfg.get("type") == "wordpress":
                # WordPress は直下にファイルを置けない。橋渡しへ確認コードを渡す（返す窓口はプラグインの版による）
                import wp_bridge
                try:
                    wp_bridge.push_settings(cfg)
                except SystemExit as e:
                    r["msg"] = f"橋渡しへ確認コードを渡せません（{str(e)[:60]}）"
            if code not in auth_users(live_auth(dom)):
                since = waits.setdefault(sid, today)
                late = (date.fromisoformat(today) - date.fromisoformat(since)).days > WAIT_DAYS
                r["state"] = "stuck" if late else "waiting"
                continue
            if verify_site(f"https://{dom}/", key):
                waits.pop(sid, None)
            else:
                r["state"], r["msg"] = "failed", "VerifySite が確認できないと返しました"
        except BingError as e:
            r["state"], r["msg"] = "error", str(e)
    return out


def connect_report(results):
    """つなぐ工程の行。人が動くまで消えないもの（失敗・長く出ない）だけ要対応にする"""
    bad = []
    for r in results:
        url = f"https://{r['domain']}/{SITE_AUTH}"
        if r["state"] == "verified":
            print(f"  {r['site']}: Bing の所有権を確認済み（送信の対象）")
        elif r["state"] == "waiting":
            print(f"確認中: {r['domain']} の Bing の確認ファイル {url} が本番に出るのを待っています（記事の配信と一緒に置きます）")
        elif r["state"] == "stuck":
            bad.append(f"要対応: {r['domain']} の Bing の確認ファイル {url} が{WAIT_DAYS}日たっても本番に出ていません"
                       "（配信先の公開フォルダの直下に置かれているか確かめてください）")
        elif r["state"] == "failed":
            bad.append(f"要対応: {r['domain']} を Bing で所有権を確認できません（{url} の中身を確かめてください）")
        else:
            bad.append(f"要対応: {r['domain']} を当社の Bing アカウントへ足せません（{r['msg']}）")
    for b in dict.fromkeys(bad):
        print(b)
    return bad


def send_cfgs(key=None):
    """送ってよい社＝自社と、同意があり当社の Bing アカウントで所有権を確かめたお客様の社"""
    out = dict(own_cfgs())
    cl = client_cfgs()
    if not cl:
        return out
    key = api_key() if key is None else key
    try:
        have = user_sites(key) if key else {}
    except BingError:
        have = {}
    out.update({sid: c for sid, c in cl.items() if (have.get(c["domain"].lower()) or {}).get("verified")})
    return out


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


def report(results, bad=None):
    """印と要対応の行を出す。未登録・鍵の誤りは人が手を動かすまで消えないので要対応にする
    （bad: つなぐ工程で出た要対応。行は connect_report が出し済み）"""
    shown = list(bad or [])
    bad = list(shown)
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
        if b not in shown:
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


def own_cfgs():
    """自社の社。お客様の社は、同意を取り所有権を確かめた社だけ send_cfgs が足す"""
    import sites as S
    cfgs = S.load_all()
    return {sid: cfgs[sid] for sid in S.own_ids() if sid in cfgs}


def jobs_for_urls(urls, cfgs):
    """指定URLをサイトごとに束ねる。登録していないドメインのURLは送らない"""
    by_dom = {c["domain"]: sid for sid, c in cfgs.items()}
    out = {}
    for u in urls:
        host = urllib.parse.urlsplit(u.strip()).netloc
        if host in by_dom:
            out.setdefault((by_dom[host], host), []).append(u.strip())
        else:
            print(f"  {host}: 送り先にない（sites/*.json に無い・同意が無い・Bing で所有権を確かめていない）ため送りません")
    return out


def send_urls(urls, sitemap=False):
    """他の工程（reindex の再送）から呼ぶ入口。鍵が無ければ何もしない"""
    key = api_key()
    if not key or not urls:
        return []
    state, today = load_state(), date.today().isoformat()
    res = [send_site(sid, dom, us, key, state, today, sitemap)
           for (sid, dom), us in jobs_for_urls(urls, send_cfgs(key)).items()]
    save_state(state, today)
    return res


def sitemap_entries(domain):
    """本番の sitemap の (URL, lastmod)。手元の site/ ではなく本番を読むのは、Bing が取りに行くのも本番だから。
    索引形式（WordPress の /wp-sitemap.xml 等）は子まで辿る（平らに読むと子の sitemap のURLを記事として送っていた）"""
    import wp_bridge
    return wp_bridge.sitemap_entries(domain)


def load_backfill():
    try:
        b = json.loads(BACKFILL.read_text(encoding="utf-8")) if BACKFILL.is_file() else {}
    except (OSError, ValueError):
        b = {}
    b.setdefault("sent", {})
    return b


def save_backfill(b):
    BACKFILL.parent.mkdir(exist_ok=True)
    BACKFILL.write_text(json.dumps(b, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


def backfill_site(sid, domain, entries, key, state, ledger, today, dry=False):
    """1サイト分の送り切り。送ったことのあるURLは送らず、lastmod の新しい順に、枠から RESERVE を残して送る"""
    site_url = f"https://{domain}/"
    urls = list(dict.fromkeys(u for u, _ in sorted(entries, key=lambda e: e[1], reverse=True)))
    # 週次・公開直後に送った分（bing_submit.json は7日で消える）も送り切りの記録へ移し、二度送らない
    for u in urls:
        if u not in ledger["sent"] and u in state["sent"]:
            ledger["sent"][u] = state["sent"][u]
    todo = [u for u in urls if u not in ledger["sent"]]
    res = {"site": sid, "domain": domain, "total": len(urls), "sent": 0, "left": len(todo),
           "per_day": 0, "state": "ok", "msg": ""}
    if not todo:
        return res
    try:
        q = quota(site_url, key)
        res["per_day"] = max(0, min(q - RESERVE, BATCH_MAX))
        go = todo[:res["per_day"]]
        if go and not dry:
            submit_urls(site_url, go, key)
            ledger["sent"].update({u: today for u in go})
            state["sent"].update({u: today for u in go})
        res["sent"] = len(go)
        res["left"] = len(todo) - len(go)
    except BingError as e:
        res["state"], res["msg"] = classify(e), str(e)
    return res


def backfill_report(results, dry=False, pre_bad=()):
    """送り切りの印。枠切れ（throttled）は翌日に持ち越すだけなので要対応にしない
    （pre_bad: つなぐ工程の要対応。行は connect_report が出し済み）"""
    if not pre_bad and results and all(r["state"] == "ok" and r["left"] == 0 and r["sent"] == 0 for r in results):
        print("BING_OK=yes")
        return
    bad = list(pre_bad)
    for r in results:
        if r["state"] == "ok":
            days = math.ceil(r["left"] / r["per_day"]) if r["left"] and r["per_day"] else 0
            print(f"  {r['site']}: sitemap {r['total']}件・{'送る予定' if dry else '今回送信'} {r['sent']}件・"
                  f"残り {r['left']}件" + (f"（あと{days}日）" if days else "")
                  + ("（枠の残りが少ないため今日は送りません）" if r["left"] and not r["per_day"] else ""))
            continue
        print(f"  {r['site']}: 送れません（{r['state']}・{r['msg']}）")
        if r["state"] == "unregistered":
            bad.append(f"要対応: Bing Webmaster に未登録 — {r['domain']}（サイトを追加して所有権を確認してください）")
        elif r["state"] == "invalid_key":
            bad.append("要対応: Bing Webmaster の API キーが無効です（BING_WEBMASTER_API_KEY を作り直してください）")
        elif r["state"] != "throttled":
            bad.append(f"要対応: Bing への送り切りが失敗しました — {r['domain']}（{r['msg']}）")
    for b in dict.fromkeys(bad):
        if b not in pre_bad:
            print(b)
    print(f"BING_BACKFILL_LEFT={sum(r['left'] for r in results)}")
    if bad:
        print("BING_OK=no")
    elif results and all(r["state"] != "ok" for r in results):
        print("BING_OK=unknown")
    else:
        print("BING_OK=yes")


def backfill(argv, key):
    only = argv[argv.index("--site") + 1] if "--site" in argv and len(argv) > argv.index("--site") + 1 else ""
    dry = "--dry-run" in argv
    state, ledger, today = load_state(), load_backfill(), date.today().isoformat()
    results = []
    # 同意のあるお客様の社は、毎日ここでつなぐ（足す→確認ファイルが出ていれば所有権を確かめる）。待ち始めた日は ledger に残る
    cl = {sid: c for sid, c in client_cfgs().items() if not only or sid == only}
    pre_bad = connect_report(connect(cl, key, ledger, today)) if cl and not dry else []
    # 同意の無いお客様の社は先方の Bing アカウントの持ち物のため送らない
    for sid, cfg in send_cfgs(key).items():
        if only and sid != only:
            continue
        dom = cfg["domain"]
        try:
            entries = sitemap_entries(dom)
        except Exception as e:
            results.append({"site": sid, "domain": dom, "total": 0, "sent": 0, "left": 0, "per_day": 0,
                            "state": "error", "msg": f"sitemapを取得できません（{type(e).__name__}）"})
            continue
        results.append(backfill_site(sid, dom, entries, key, state, ledger, today, dry))
    if not dry:
        save_state(state, today)
        save_backfill(ledger)
    backfill_report(results, dry, pre_bad)
    return 0


# ---------- 検索の成績（週次で積み、月次レポートが読む） ----------

def bing_day(v):
    """Bing の日付 "/Date(ms[±hhmm])/" → YYYY-MM-DD。ms は UTC の時刻で、時差があればその土地の日付にする
    （公式の例 "/Date(1316156400000-0700)/" は XML の 2011-09-16T00:00:00-07:00 と同じ日）"""
    m = re.match(r"/Date\((-?\d+)([+-]\d{4})?\)/", str(v or ""))
    if not m:
        return ""
    ms = int(m.group(1))
    if m.group(2):
        off = (int(m.group(2)[1:3]) * 60 + int(m.group(2)[3:5])) * 60000
        ms += off if m.group(2)[0] == "+" else -off
    return (date(1970, 1, 1) + timedelta(milliseconds=ms)).isoformat()


def _pos(v):
    """平均順位。Bing はデータの無いとき -1 を返す（実測: クリック1回でも AvgClickPosition が -1）"""
    return v if isinstance(v, (int, float)) and v > 0 else None


def fetch_stats(site_url, key):
    """(日別, 語, ページ) の生の行。どれか1つでも失敗すれば BingError（半端に積まない）"""
    return tuple(_request("GET", op, key, {"siteUrl": site_url}).get("d") or []
                 for op in ("GetRankAndTrafficStats", "GetQueryStats", "GetPageStats"))


def merge_stats(old, rt, qs, ps, today):
    """前の回の分に積み増す。日別は日付ごとに今回の値で上書き、語・ページは今回返った週だけを丸ごと差し替える
    （古い週・古い日は API の窓から外れても残す）"""
    s = dict(old or {})
    daily = dict(s.get("daily") or {})
    for r in rt:
        d = bing_day(r.get("Date"))
        if d:
            daily[d] = {"imp": int(r.get("Impressions") or 0), "clicks": int(r.get("Clicks") or 0)}
    fresh = {}
    for kind, rows in (("queries", qs), ("pages", ps)):
        for r in rows:
            d, k = bing_day(r.get("Date")), str(r.get("Query") or "").strip()
            if d and k:
                fresh.setdefault(d, {"queries": [], "pages": []})[kind].append(
                    {"key": k, "imp": int(r.get("Impressions") or 0), "clicks": int(r.get("Clicks") or 0),
                     "pos": _pos(r.get("AvgImpressionPosition"))})
    weeks = dict(s.get("weeks") or {})
    for d, w in fresh.items():
        weeks[d] = {kind: sorted(v, key=lambda x: (-x["imp"], -x["clicks"], x["key"])) for kind, v in w.items()}
    s.update(daily=dict(sorted(daily.items())), weeks=dict(sorted(weeks.items())), updated=today)
    return s


def stats_path(sid):
    return STATS_DIR / f"{sid}.json"


def load_stats(sid):
    p = stats_path(sid)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, ValueError):
        return None


def collect_stats(argv, key):
    """送る対象と同じ社（send_cfgs）の成績を取って積む。同意の無いお客様の社は取らない"""
    only = argv[argv.index("--site") + 1] if "--site" in argv and len(argv) > argv.index("--site") + 1 else ""
    today = date.today().isoformat()
    results, bad = [], []
    for sid, cfg in send_cfgs(key).items():
        if only and sid != only:
            continue
        dom = cfg["domain"]
        try:
            rt, qs, ps = fetch_stats(f"https://{dom}/", key)
        except BingError as e:
            st = classify(e)
            results.append(st)
            print(f"  {sid}: 成績を取れません（{st}・{e}）")
            if st == "unregistered":
                bad.append(f"要対応: Bing Webmaster に未登録 — {dom}（成績を取れません）")
            elif st == "invalid_key":
                bad.append("要対応: Bing Webmaster の API キーが無効です（BING_WEBMASTER_API_KEY を作り直してください）")
            continue
        s = merge_stats(load_stats(sid), rt, qs, ps, today)
        s.update(site=sid, domain=dom)
        STATS_DIR.mkdir(parents=True, exist_ok=True)
        stats_path(sid).write_text(json.dumps(s, ensure_ascii=False, indent=0), encoding="utf-8")
        results.append("ok")
        days = [d for d in s["daily"]]
        if not (rt or qs or ps):
            print(f"  {sid}: Bing から成績がまだ返っていません（所有権の確認から日が浅い・表示が無い。積んだ日別 {len(days)}日）")
            continue
        print(f"  {sid}: 今回 日別 {len(rt)}日・語 {len(qs)}行・ページ {len(ps)}行 → 積んだ日別 {len(days)}日"
              f"（{days[0]}〜{days[-1]}）・週 {len(s['weeks'])}週")
    for b in dict.fromkeys(bad):
        print(b)
    if bad:
        print("BING_STATS_OK=no")
    elif results and all(r != "ok" for r in results):
        print("BING_STATS_OK=unknown")
    else:
        print("BING_STATS_OK=yes")
    return 0


def month_totals(s, start, end):
    """[start, end] の日別の合計。(表示, クリック, 日数, 最初の日, 最後の日)"""
    days = [(d, v) for d, v in (s.get("daily") or {}).items() if start <= d <= end]
    if not days:
        return 0, 0, 0, "", ""
    return (sum(v["imp"] for _, v in days), sum(v["clicks"] for _, v in days), len(days), days[0][0], days[-1][0])


def top_queries(s, start, end, n=TOP_N):
    """週の始まりが [start, end] の週の語を足し合わせる。順位は表示回数で重みをつけた平均"""
    agg = {}
    for wk, w in (s.get("weeks") or {}).items():
        if not start <= wk <= end:
            continue
        for r in w.get("queries", []):
            a = agg.setdefault(r["key"], {"key": r["key"], "imp": 0, "clicks": 0, "pw": 0.0, "pi": 0})
            a["imp"] += r["imp"]
            a["clicks"] += r["clicks"]
            if r.get("pos") and r["imp"]:
                a["pw"] += r["pos"] * r["imp"]
                a["pi"] += r["imp"]
    rows = sorted(agg.values(), key=lambda a: (-a["imp"], -a["clicks"], a["key"]))[:n]
    for a in rows:
        a["pos"] = round(a["pw"] / a["pi"], 1) if a["pi"] else None
    return rows


def _ctr(clicks, imp):
    if imp is None or clicks is None:
        return "—"
    if imp < MIN_N:
        return f"—（表示{MIN_N}回未満）"
    return f"{clicks / imp * 100:.1f}%"


def report_html(sid, ym, through=None, google=None):
    """月次レポートの「Bing での表示・クリック・主な語」の中身（節の見出しは呼び出し側）。
    成績を取っていない社（Bing の対象外）は ""。取っていてもまだ返っていなければ、0 と書かずにそう書く"""
    import html as H
    s = load_stats(sid)
    if s is None:
        return ""
    y, mo = map(int, ym.split("-"))
    start = f"{ym}-01"
    end = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)).isoformat()
    if through:
        end = min(end, str(through)[:10])
    imp, clk, n_days, d0, d1 = month_totals(s, start, end)
    out = ['<p style="font-size:9.5pt">ChatGPT の検索は Bing の索引も使います。Bing に載って表示されているかは、'
           'ChatGPT の回答に出る前提の1つです。Google（Search Console）と同じ月で並べます。</p>']
    if not n_days:
        last = max((s.get("daily") or {}), default="")
        out.append('<div class="callout"><b>この月の Bing の成績はまだ返っていません。</b>'
                   + (f'手元にある最後の日は {H.escape(last)} です。' if last else
                      'Bing Webmaster で所有権を確かめた直後は、成績が出るまで日数がかかります。')
                   + '表示が0回だったという意味ではありません。</div>')
        return "\n".join(out)
    g = google or {}
    gi, gc = g.get("imp"), g.get("clicks")
    fmt = (lambda v: f"{v:,}" if isinstance(v, int) else "—")
    out.append('<table><tr><th>指標</th><th>Bing</th><th>Google（Search Console）</th></tr>'
               f'<tr><td>表示回数</td><td class="num">{imp:,}</td><td class="num">{fmt(gi)}</td></tr>'
               f'<tr><td>クリック</td><td class="num">{clk:,}</td><td class="num">{fmt(gc)}</td></tr>'
               f'<tr><td>クリック率</td><td class="num">{_ctr(clk, imp)}</td>'
               f'<td class="num">{_ctr(gc, gi) if isinstance(gi, int) else "—"}</td></tr>'
               f'<tr><td>期間</td><td>{d0}〜{d1}（{n_days}日分）</td><td>{start}〜{end}</td></tr></table>')
    rows = top_queries(s, start, end)
    if rows:
        tr = "".join(f'<tr><td>{H.escape(r["key"])}</td><td class="num">{r["imp"]:,}</td>'
                     f'<td class="num">{r["clicks"]:,}</td>'
                     f'<td class="num">{r["pos"] if r["pos"] is not None else "—"}</td></tr>' for r in rows)
        out.append('<h3>Bing の主な検索語（表示回数順）</h3>'
                   '<table><tr><th>検索語</th><th>表示回数</th><th>クリック</th><th>平均順位</th></tr>' + tr + '</table>')
    else:
        out.append('<p class="note">この月に始まる週の検索語は、まだ返っていません。</p>')
    out.append('<p class="note">Bing の表示・クリックは、ウェブ・チャット（Copilot）・ニュース・画像・動画などの面の合計です'
               '（2023年3月24日以降の Bing の仕様）。検索語は週ごと（週の始まりがこの月の週）で上位の語だけが返るため、'
               '語の合計は日別の合計より少なくなります。'
               f'表示が{MIN_N}回に満たないときはクリック率を出さず、回数だけを示します。</p>')
    return "\n".join(out)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    key = api_key()
    if not key:
        print("BING_WEBMASTER_API_KEY 未設定のため送りません")
        print("BING_STATS_OK=unset" if "--stats" in argv else "BING_OK=unset")
        return 0
    if "--stats" in argv:
        return collect_stats(argv, key)
    if "--backfill" in argv:
        return backfill(argv, key)
    state, today = load_state(), date.today().isoformat()
    only = argv[argv.index("--site") + 1] if "--site" in argv and len(argv) > argv.index("--site") + 1 else ""
    # 同意のあるお客様の社は、送る前につなぐ（記事CIでは、配信と一緒に置いた確認ファイルがこの時点で本番に出ている）
    cl = {sid: c for sid, c in client_cfgs().items() if (sid == only if only else "--weekly" in argv)}
    bad = connect_report(connect(cl, key)) if cl else []
    cfgs = send_cfgs(key)
    if only and only not in cfgs:
        # 記事CI（pipeline-multi）はお客様の社でも呼ぶ。同意の無い社は先方の Bing アカウントの持ち物で送らない
        print(f"{only}: " + ("Bing の所有権の確認がまだのため、今回は送りません" if only in cl else
                             "Bing への登録に同意の無いお客様のサイト（先方の Bing アカウントの持ち物）のため送りません"))
        print("BING_OK=" + ("no" if bad else "unset"))
        return 0
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
    report(results, bad)
    return 0


if __name__ == "__main__":
    sys.exit(main())
