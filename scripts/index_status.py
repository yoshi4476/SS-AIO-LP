# -*- coding: utf-8 -*-
"""sitemapの各URLがGoogleに登録されているかを1本ずつ確認する

GSCの「インデックスに登録されなかった理由」は件数しか出ないため、
どのページが落ちているかが分からない。URL検査APIで実際の状態を引き、
未登録のURLを理由つきで一覧にする。

APIの上限は1日2,000URL・1分600URL。3サイト合計200URL程度なら収まる。

使い方: python scripts/index_status.py [--site ai-lab]
"""
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sites as sites_mod  # noqa: E402

SA = ROOT / "indexing-service-account.json"
SCOPE = ["https://www.googleapis.com/auth/webmasters.readonly"]
UA = {"User-Agent": "Mozilla/5.0 Chrome/126"}

JP = {
    "PASS": "登録済み",
    "PARTIAL": "一部に問題あり",
    "FAIL": "登録されていない",
    "NEUTRAL": "判定なし",
}


def client():
    import gcreds
    from googleapiclient.discovery import build
    return build("searchconsole", "v1", credentials=gcreds.load(SA, SCOPE))


def sitemap_urls(domain):
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"https://{domain}/sitemap.xml", headers=UA),
                timeout=25) as r:
            return re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"    sitemapを取得できません: {str(e)[:60]}")
        return []


def inspect(sc, url, site_url):
    try:
        res = sc.urlInspection().index().inspect(
            body={"inspectionUrl": url, "siteUrl": site_url,
                  "languageCode": "ja"}).execute()
        return res.get("inspectionResult", {}).get("indexStatusResult", {})
    except Exception as e:
        return {"error": str(e)[:80]}


def main():
    only = sys.argv[sys.argv.index("--site") + 1] if "--site" in sys.argv else None
    sc = client()
    for sid, cfg in sites_mod.load_all().items():
        if only and sid != only:
            continue
        d = cfg["domain"]
        site_url = f"https://{d}/"
        urls = sitemap_urls(d)
        print(f"■ {cfg['name']}（sitemap {len(urls)}件）", flush=True)
        if not urls:
            continue
        tally, ng, err = Counter(), [], 0
        for i, u in enumerate(urls, 1):
            r = inspect(sc, u, site_url)
            if "error" in r:
                err += 1
                if err == 1:
                    print(f"    APIエラー: {r['error']}", flush=True)
                continue
            v = r.get("verdict", "NEUTRAL")
            tally[v] += 1
            if v != "PASS":
                path = u.replace(f"https://{d}", "") or "/"
                ng.append((path, r.get("coverageState", "—"),
                           r.get("robotsTxtState", ""), r.get("googleCanonical", "")))
                # 見つけたその場で出す。1件ずつAPIに問い合わせるため数分かかり、
                # 最後にまとめて出す作りだと、途中で止めたときに何も残らない。
                # 実際、時間切れで打ち切ると出力が丸ごと消えていた。
                print(f"      未登録 {path[:44]:<44} {r.get('coverageState','—')[:30]}",
                      flush=True)
            if i % 20 == 0:
                print(f"    …{i}/{len(urls)}件を確認（登録済み{tally['PASS']}）", flush=True)
                time.sleep(1)      # 1分600件の上限に触れないよう間隔をあける
        got = sum(tally.values())
        if got:
            print("    " + " / ".join(f"{JP.get(k, k)} {v}件" for k, v in tally.most_common()),
                  flush=True)
        for u, cov, rob, can in ng:
            line = f"      {u[:44]:<44} {cov[:34]}"
            if can and can.rstrip("/") != f"https://{d}{u}".rstrip("/"):
                line += f"  正規扱い→ {can.replace(f'https://{d}', '')[:30]}"
            print(line)
        print()


if __name__ == "__main__":
    main()
