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
    import gcreds
    from googleapiclient.discovery import build
    return build(name, ver, credentials=gcreds.load(SA, scopes))


def sitemap_urls(domain):
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"https://{domain}/sitemap.xml", headers=UA),
                timeout=25) as r:
            return re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"    sitemapを取得できません: {str(e)[:60]}")
        return []


def unindexed(sc, urls, site_url):
    out = []
    for i, u in enumerate(urls, 1):
        try:
            r = sc.urlInspection().index().inspect(
                body={"inspectionUrl": u, "siteUrl": site_url,
                      "languageCode": "ja"}).execute()
            s = r.get("inspectionResult", {}).get("indexStatusResult", {})
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

    for sid, cfg in sites_mod.load_all().items():
        if only and sid != only:
            continue
        d = cfg["domain"]
        site_url = f"https://{d}/"
        urls = sitemap_urls(d)
        if not urls:
            continue
        ng = unindexed(sc, urls, site_url)
        print(f"■ {cfg['name']}  sitemap {len(urls)}件 / 未登録 {len(ng)}件")
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
