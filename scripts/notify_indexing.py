# -*- coding: utf-8 -*-
"""Google Indexing API 即時登録（Phase 7 / 公開直後に実行）

使い方:
    python scripts/notify_indexing.py            # 本日公開・更新の記事URLを通知
    python scripts/notify_indexing.py --all      # sitemap.xml の全URLを通知（初回・障害復旧用）
    python scripts/notify_indexing.py <URL> ...  # 指定URLを通知

前提: indexing-service-account.json（GSCオーナー権限のサービスアカウント）
※未配置なら静かにスキップする（Actionsで未設定でも失敗させない）
"""
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_URL = "https://ai.7senses.co.jp"
SA_PATH = ROOT / "indexing-service-account.json"


def target_urls():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        return args
    sm = (ROOT / "site" / "sitemap.xml").read_text(encoding="utf-8")
    urls = re.findall(r"<loc>(.*?)</loc>", sm)
    if "--all" in sys.argv:
        return urls
    # 本日付の記事だけ（フロントマターの date / dateModified を確認）
    today = str(date.today())
    picked = []
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        if re.search(rf"^(date|dateModified):\s*{today}\s*$", fm, re.M):
            cat = re.search(r"^category:\s*(\S+)", fm, re.M)
            slug = re.search(r"^slug:\s*(\S+)", fm, re.M)
            slug_v = slug.group(1) if slug else p.stem
            if cat:
                picked.append(f"{SITE_URL}/{cat.group(1)}/{slug_v}/")
    return [u for u in picked if u in urls]


def main():
    if not SA_PATH.exists():
        print("indexing-service-account.json 未配置のためスキップ")
        return
    urls = target_urls()
    if not urls:
        print("通知対象URLなし（本日公開・更新の記事なし）")
        return
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    creds = service_account.Credentials.from_service_account_file(
        str(SA_PATH), scopes=["https://www.googleapis.com/auth/indexing"])
    svc = build("indexing", "v3", credentials=creds)
    ok = 0
    for u in urls[:190]:  # 1日200件のAPI上限に対する安全マージン
        try:
            svc.urlNotifications().publish(body={"url": u, "type": "URL_UPDATED"}).execute()
            ok += 1
        except Exception as e:
            print(f"NG {u}: {e}")
    print(f"Indexing API通知: {ok}/{len(urls)}件 成功")


if __name__ == "__main__":
    main()
