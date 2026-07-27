# -*- coding: utf-8 -*-
"""IndexNow即時通知（Phase 7 / 週次リライト後に実行）

使い方: python scripts/notify_indexnow.py <URL> [<URL> ...]
        引数なしの場合は sitemap.xml の全URLを通知
前提: .env に INDEXNOW_KEY を設定し、site/{KEY}.txt を配置していること
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
           if "=" in l and not l.strip().startswith("#"))
KEY = env.get("INDEXNOW_KEY", "").strip()
SITE_URL = env.get("SITE_URL", "https://example.com").strip()

if not KEY or "YOUR_" in KEY:
    raise SystemExit("INDEXNOW_KEY が未設定です（.env）。site/{KEY}.txt の設置も必要です")

urls = sys.argv[1:]
if not urls:
    sm = (ROOT / "site" / "sitemap.xml").read_text(encoding="utf-8")
    urls = re.findall(r"<loc>(.*?)</loc>", sm)

host = SITE_URL.split("//", 1)[-1].strip("/")
payload = json.dumps({"host": host, "key": KEY,
                      "keyLocation": f"{SITE_URL}/{KEY}.txt", "urlList": urls}).encode()
req = urllib.request.Request("https://api.indexnow.org/indexnow", data=payload,
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as res:
    print(f"IndexNow通知: {len(urls)}件 → HTTP {res.status}")
