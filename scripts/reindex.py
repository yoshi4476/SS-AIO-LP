# -*- coding: utf-8 -*-
"""登録されていないURLを見つけて、Googleに再通知する

notify_indexing.py は ai-lab 専用（URLが固定）で、コーポレートと
補助金サイトには使えなかった。実測ではコーポレートだけ sitemap 49件中
12件が未登録のまま放置されていた。

やること:
  1. URL検査APIで、sitemapの各URLが登録されているか確認
  2. 未登録のURLを Indexing API で通知
  3. sitemap 自体も再送信（クロールのきっかけを増やす）

使い方:
    python scripts/reindex.py                # 3サイトぶん確認して通知
    python scripts/reindex.py --site corporate
    python scripts/reindex.py --dry          # 通知せず一覧だけ出す
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


def unindexed(sc, urls, site_url, deadline=None, cache=None):
    out = []
    for i, u in enumerate(urls, 1):
        if deadline and time.time() > deadline:
            print(f"    時間の上限に達したため、残り{len(urls) - i + 1}件は次回に回します")
            break
        try:
            r = sc.urlInspection().index().inspect(
                body={"inspectionUrl": u, "siteUrl": site_url,
                      "languageCode": "ja"}).execute()
            s = r.get("inspectionResult", {}).get("indexStatusResult", {})
            if cache is not None:
                cache[u] = {"verdict": s.get("verdict", ""), "state": s.get("coverageState", ""), "at": time.time()}
            if s.get("verdict") != "PASS":
                out.append((u, s.get("coverageState", "—")))
        except Exception as e:
            print(f"    検査に失敗: {u[-40:]} {str(e)[:50]}")
        if i % 20 == 0:
            time.sleep(1)
    return out


def main():
    a = sys.argv
    only = a[a.index("--site") + 1] if "--site" in a else None
    dry = "--dry" in a
    if not SA.is_file():
        raise SystemExit("indexing-service-account.json がありません")

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

        # 旧ドメインが正規ページに選ばれているものは、通知しても直らない。
        # 送り先の設定を変える必要があるため、分けて出す。
        dup = [(u, c) for u, c in ng if "重複" in c]
        todo = [(u, c) for u, c in ng if "重複" not in c]
        for u, c in todo:
            print(f"    {u.replace(f'https://{d}', ''):<46} {c[:30]}")
        if dry:
            for u, c in dup:
                print(f"    [通知しても直りません] {u.replace(f'https://{d}', '')}")
            continue

        ok = fail = 0
        for u, _ in todo:
            try:
                idx.urlNotifications().publish(
                    body={"url": u, "type": "URL_UPDATED"}).execute()
                ok += 1
            except Exception as e:
                fail += 1
                if fail == 1:
                    print(f"    Indexing API が使えません: {str(e)[:110]}")
            time.sleep(0.2)
        print(f"    通知: 成功 {ok}件 / 失敗 {fail}件")

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
