# -*- coding: utf-8 -*-
"""Search Consoleの権限を確認する（403の原因を切り分ける）

使い方: python scripts/gsc_check.py

「サービスアカウントを追加したのにデータが取れない」ときの原因はほぼ権限レベル。
制限付き（siteRestrictedUser）ではAPIから検索データを読めないため、
追加されていないのか、権限が足りないのかをここで見分ける。
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gcreds  # noqa: E402
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SA = ROOT / "indexing-service-account.json"
# APIで検索データを読める権限。制限付きでは読めない
OK_LEVELS = ("siteOwner", "siteFullUser")
LABEL = {"siteOwner": "所有者", "siteFullUser": "フル", "siteRestrictedUser": "制限付き"}


def main():
    if not SA.is_file():
        raise SystemExit(f"{SA.name} がありません（GCPのサービスアカウント鍵を置いてください）")
    creds = gcreds.load(SA, ["https://www.googleapis.com/auth/webmasters.readonly"])
    from googleapiclient.discovery import build
    sc = build("searchconsole", "v1", credentials=creds)

    print(f"サービスアカウント: {creds.service_account_email}\n")
    granted = {s["siteUrl"]: s["permissionLevel"] for s in sc.sites().list().execute().get("siteEntry", [])}

    ng = []
    for cfg in sites_mod.load_all().values():
        url = f"https://{cfg['domain']}/"
        lv = granted.get(url)
        if lv is None:
            print(f"  未追加   {cfg['id']:10s} {url}")
            ng.append((cfg, url, None))
            continue
        # 権限レベルでは判断しない。制限付き（siteRestrictedUser）でも
        # 検索データを読めることを実測で確認したため、実際に叩いた結果で判定する。
        try:
            r = sc.searchanalytics().query(siteUrl=url, body={
                "startDate": (date.today() - timedelta(days=28)).isoformat(),
                "endDate": date.today().isoformat(),
                "dimensions": ["query"], "rowLimit": 5}).execute()
            print(f"  OK       {cfg['id']:10s} {url}  {LABEL.get(lv, lv)} / "
                  f"直近28日のクエリ {len(r.get('rows', []))}件")
        except Exception as e:
            print(f"  読めない {cfg['id']:10s} {url}  {LABEL.get(lv, lv)} / {str(e)[:90]}")
            ng.append((cfg, url, lv))

    if not ng:
        print("\nGSC_OK=yes（3サイトとも検索データを取得できます）")
        return
    print("\nGSC_OK=no\n対処（Search Consoleの画面で行う作業です）:")
    for cfg, url, lv in ng:
        print(f"\n  ■ {cfg['name']}（{url}）")
        print(f"    1. https://search.google.com/search-console?resource_id={url}")
        print("    2. 左下の［設定］→［ユーザーと権限］")
        if lv is None:
            print(f"    3. ［ユーザーを追加］→ {creds.service_account_email}")
            print("    4. 権限は［フル］を選ぶ")
        else:
            print(f"    3. {creds.service_account_email} は［{LABEL.get(lv, lv)}］で登録済み。"
                  "読めない原因は権限レベル以外にあります（上の実測エラーを参照）")
    print("\n  変更後に python scripts/gsc_check.py を再実行して確認してください")


if __name__ == "__main__":
    main()
