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
env = {}
env_path = ROOT / ".env"
if env_path.exists():
    env = dict(l.split("=", 1) for l in env_path.read_text(encoding="utf-8-sig").splitlines()
               if "=" in l and not l.strip().startswith("#"))
KEY = env.get("INDEXNOW_KEY", "").strip()
SITE_URL = env.get("SITE_URL", "https://ai.7senses.co.jp").strip()

if not KEY or "YOUR_" in KEY:
    # .envがない環境（GitHub Actions等）ではsite/直下のキーファイル名から自動検出
    # （IndexNowキーは公開URLに置く仕様のため秘匿不要）
    for f in (ROOT / "site").glob("*.txt"):
        if re.fullmatch(r"[0-9a-f]{16,64}", f.stem) and f.read_text().strip() == f.stem:
            KEY = f.stem
            break
if not KEY:
    raise SystemExit("INDEXNOW_KEY が未設定です（.env または site/{KEY}.txt を設置してください）")

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
