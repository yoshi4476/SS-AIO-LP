# -*- coding: utf-8 -*-
"""登録されていないURLを見つけて、Googleに再通知する

notify_indexing.py は ai-lab 専用（URLが固定）で、コーポレートと
補助金サイトには使えなかった。実測ではコーポレートだけ sitemap 49件中
12件が未登録のまま放置されていた。

やること:
  1. URL検査APIで、sitemapの各URLが登録されているか確認
  2. 未登録（検出/クロール済み - インデックス未登録・Google に未認識）のURLを
     Indexing API と IndexNow で通知。送った日を data/index_resend.json に残し、14日は送り直さない
  3. sitemap 自体も再送信（クロールのきっかけを増やす）

使い方:
    python scripts/reindex.py                # 3サイトぶん確認して通知
    python scripts/reindex.py --site corporate
    python scripts/reindex.py --dry          # 通知せず一覧だけ出す（検査の結果は data/index_cache.json に残る）
    python scripts/reindex.py --from-cache   # 検査せず、直近の --dry の結果から未登録だけを通知する
"""
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sites as sites_mod  # noqa: E402

SA = ROOT / "indexing-service-account.json"
READ = ["https://www.googleapis.com/auth/webmasters.readonly"]
WRITE = ["https://www.googleapis.com/auth/webmasters"]
PUBLISH = ["https://www.googleapis.com/auth/indexing"]
UA = {"User-Agent": "Mozilla/5.0 Chrome/126"}


def svc(name, ver, scopes):
    """1回の呼び出しに30秒の上限を付ける。無いと止まった呼び出しを待ち続け、
    週次が60分の上限に当たって打ち切られた（2026-09-21・この工程だけで32分）"""
    import gcreds
    import httplib2
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build
    http = AuthorizedHttp(gcreds.load(SA, scopes), http=httplib2.Http(timeout=30))
    return build(name, ver, http=http, cache_discovery=False)


# 登録済みと確かめたURLは30日間もう一度は検査しない（毎週全部を検査していたのが時間の大半）。
# 未登録・失敗したURLは毎回検査する
CACHE = ROOT / "data" / "index_cache.json"
FRESH_DAYS = 30


def _cache():
    import json
    try:
        return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.is_file() else {}
    except Exception:
        return {}


def _save(c):
    import json
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(c, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


def needs_check(u, c):
    rec = c.get(u)
    if not rec or rec.get("verdict") != "PASS":
        return True
    return (time.time() - rec.get("at", 0)) > FRESH_DAYS * 86400


def sitemap_urls(domain):
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"https://{domain}/sitemap.xml", headers=UA),
                timeout=25) as r:
            return re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"    sitemapを取得できません: {str(e)[:60]}")
        return []


BUDGET_MIN = 15      # 1回の上限。全URLを毎週見ると30分を超え、週次の通知工程まで道連れに止まった
PER_SITE = 120       # 1サイト1回に検査する上限。週ごとに起点をずらして全体を回す


def rotated(urls, per_site):
    """毎週同じ先頭だけを見ないよう、週番号で起点をずらす"""
    if len(urls) <= per_site:
        return urls
    k = (time.gmtime().tm_yday // 7 * per_site) % len(urls)
    return (urls[k:] + urls[:k])[:per_site]


WORKERS = 5   # 1件ずつ順に聞くと週次で15分かかっていた。URL検査APIの枠は1分600件なので5本並べても余裕がある


def unindexed(sc, urls, site_url, deadline=None, cache=None):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    local = threading.local()

    def one(u):
        if deadline and time.time() > deadline:
            return u, None, "skip"
        # API の client はスレッドをまたいで使えないので、スレッドごとに作る
        if not hasattr(local, "sc"):
            local.sc = svc("searchconsole", "v1", READ)
        try:
            r = local.sc.urlInspection().index().inspect(
                body={"inspectionUrl": u, "siteUrl": site_url, "languageCode": "ja"}).execute()
            return u, r.get("inspectionResult", {}).get("indexStatusResult", {}), ""
        except Exception as e:
            return u, None, str(e)[:50]

    out, skipped = [], 0
    with ThreadPoolExecutor(WORKERS) as ex:
        for u, s, err in ex.map(one, urls):
            if err == "skip":
                skipped += 1
                continue
            if err:
                print(f"    検査に失敗: {u[-40:]} {err}")
                continue
            if cache is not None:
                cache[u] = {"verdict": s.get("verdict", ""), "state": s.get("coverageState", ""), "at": time.time()}
            if s.get("verdict") != "PASS":
                out.append((u, s.get("coverageState", "—")))
    if skipped:
        print(f"    時間の上限に達したため、残り{skipped}件は次回に回します")
    return out


def main():
    a = sys.argv
    only = a[a.index("--site") + 1] if "--site" in a else None
    dry = "--dry" in a
    if not SA.is_file():
        raise SystemExit("indexing-service-account.json がありません")

    if "--from-cache" in a:
        _from_cache(svc("indexing", "v3", PUBLISH), only)
        return

    sc = svc("searchconsole", "v1", READ)
    idx = None if dry else svc("indexing", "v3", PUBLISH)
    budget = float(a[a.index("--budget-min") + 1]) if "--budget-min" in a else BUDGET_MIN
    deadline = time.time() + budget * 60
    cache = _cache()

    try:
        _loop(sc, idx, only, dry, deadline, cache)
    finally:
        _save(cache)                       # 途中で打ち切られても、確かめた分は残す


def _loop(sc, idx, only, dry, deadline, cache):
    for sid, cfg in sites_mod.load_all().items():
        if only and sid != only:
            continue
        d = cfg["domain"]
        site_url = f"https://{d}/"
        urls = sitemap_urls(d)
        if not urls:
            continue
        if time.time() > deadline:
            print(f"■ {cfg['name']}  時間の上限のため今回は見送り（次回）")
            continue
        need = [u for u in urls if needs_check(u, cache)]
        picked = rotated(need, PER_SITE)
        ng = unindexed(sc, picked, site_url, deadline, cache)
        print(f"■ {cfg['name']}  sitemap {len(urls)}件（登録済みの確認済み {len(urls) - len(need)}件は省略・"
              f"今回 {len(picked)}件を検査）/ 未登録 {len(ng)}件")
        if not ng:
            print("    すべて登録済み")
            continue
        _publish(idx, d, ng, dry)


# 週次は検査（--dry）を並行ジョブで先に済ませ、通知だけを最後に行う。
# 通知を先に送ると、Indexing API の1日200件をこの再通知が使い切り、
# その日に直した記事の通知（notify_indexing）が落ちるため、通知の順番は変えない
FROM_CACHE_HOURS = 6


def _from_cache(idx, only):
    cache, cutoff = _cache(), time.time() - FROM_CACHE_HOURS * 3600
    for sid, cfg in sites_mod.load_all().items():
        if only and sid != only:
            continue
        d = cfg["domain"]
        ng = [(u, r.get("state") or "—") for u, r in sorted(cache.items())
              if u.startswith(f"https://{d}/") and r.get("at", 0) >= cutoff and r.get("verdict") != "PASS"]
        print(f"■ {cfg['name']}  直近{FROM_CACHE_HOURS}時間の検査結果から / 未登録 {len(ng)}件")
        if ng:
            _publish(idx, d, ng, False)


# 再送するのは「見つけたが登録していない（検出/クロール済み - インデックス未登録）」と
# 「Google に知られていない」だけ。重複・noindex・404・転送は通知しても直らず、1日200件の枠を食うだけ。
# 状態名は検査の言語（ja / en-US）で変わるので両方で見る
RESEND_STATES = ("インデックス未登録", "currently not indexed",
                 "Google に認識されていません", "unknown to Google")
RESEND_DAYS = 14     # 毎週同じURLを送り続けない。送っても登録されないURLは中身の問題で、通知では直らない
RESEND_MAX = 100     # 1回の上限。同じ日の notify_indexing（本日更新分）と合わせて Indexing API の1日200件に収める
SENT = ROOT / "data" / "index_resend.json"


def resend_plan(ng, sent, today, left=RESEND_MAX):
    """[(url, 状態)] を「送る / 最近送った / 通知では直らない」に分ける。sent は {url: 'YYYY-MM-DD'}"""
    from datetime import date, timedelta
    cut = (date.fromisoformat(today) - timedelta(days=RESEND_DAYS)).isoformat()
    go, recent, other = [], [], []
    for u, c in ng:
        if not any(s in c for s in RESEND_STATES):
            other.append((u, c))
        elif sent.get(u, "") > cut:
            recent.append((u, c))
        elif len(go) < left:
            go.append((u, c))
    return go, recent, other


def _sent():
    import json
    try:
        return json.loads(SENT.read_text(encoding="utf-8")) if SENT.is_file() else {}
    except Exception:
        return {}


def _indexnow(urls):
    """IndexNow（Bing・Copilot 系）にも同じURLを送る。鍵が配信されていないドメインは拒否されるので先に確かめる"""
    import notify_indexnow as NI
    key = NI.find_key(NI.load_env())
    if not key or not urls:
        return set()
    ok = set()
    for host, us in NI.by_host(urls).items():
        if not NI.key_ok(host.split("//", 1)[-1], key):
            print(f"    IndexNow: {host} に鍵ファイルが無いため送りません")
            continue
        try:
            print(f"    IndexNow: {len(us)}件 → HTTP {NI.notify(us, key, host)}")
            ok.update(us)
        except Exception as e:
            print(f"    IndexNow に失敗: {str(e)[:80]}")
    return ok


_left = [RESEND_MAX]


def _publish(idx, d, ng, dry):
    import json
    from datetime import date
    site_url = f"https://{d}/"
    sent, today = _sent(), date.today().isoformat()
    todo, recent, other = resend_plan(ng, sent, today, _left[0])
    # 旧ドメインが正規ページに選ばれているものは、通知しても直らない。
    # 送り先の設定を変える必要があるため、分けて出す。
    dup = [(u, c) for u, c in other if "重複" in c or "Duplicate" in c]
    for u, c in todo:
        print(f"    {u.replace(f'https://{d}', ''):<46} {c[:30]}")
    if recent:
        print(f"    {RESEND_DAYS}日以内に送ったため見送り: {len(recent)}件")
    for u, c in other:
        if (u, c) not in dup:
            print(f"    [通知では直りません] {u.replace(f'https://{d}', ''):<40} {c[:30]}")
    if dry:
        for u, c in dup:
            print(f"    [通知しても直りません] {u.replace(f'https://{d}', '')}")
        return
    if not todo:
        return

    ok = fail = 0
    done = set()
    for u, _ in todo:
        try:
            idx.urlNotifications().publish(
                body={"url": u, "type": "URL_UPDATED"}).execute()
            ok += 1
            done.add(u)
        except Exception as e:
            fail += 1
            if fail == 1:
                print(f"    Indexing API が使えません: {str(e)[:110]}")
        time.sleep(0.2)
    print(f"    通知: 成功 {ok}件 / 失敗 {fail}件")
    _indexnow([u for u, _ in todo])
    _left[0] -= len(todo)
    # Indexing API に送れたURLだけ日付を残す。IndexNow だけ通ったURLまで残すと、
    # Google への再送が見送り期間のあいだ止まる（失敗したものは次の週にもう一度送る）
    sent.update({u: today for u in done})
    SENT.parent.mkdir(exist_ok=True)
    SENT.write_text(json.dumps(sent, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")

    # sitemap 再送信（クロールのきっかけを作る）
    try:
        svc("searchconsole", "v1", WRITE).sitemaps().submit(
            siteUrl=site_url, feedpath=f"https://{d}/sitemap.xml").execute()
        print("    sitemap を再送信しました")
    except Exception as e:
        print(f"    sitemap 再送信に失敗: {str(e)[:90]}")
    for u, c in dup:
        print(f"    [別ドメインが正規に選ばれています] {u.replace(f'https://{d}', '')}")


if __name__ == "__main__":
    main()
