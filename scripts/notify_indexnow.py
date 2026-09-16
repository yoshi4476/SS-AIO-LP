# -*- coding: utf-8 -*-
"""IndexNow即時通知（Phase 7 / 週次リライト後に実行）

使い方: python scripts/notify_indexnow.py <URL> [<URL> ...]
        引数なしの場合は sitemap.xml の全URLを通知
前提: .env に INDEXNOW_KEY を設定し、site/{KEY}.txt を配置していること

処理はすべて main() の中に置く。モジュールの直下に書くと、他のスクリプトが
`import notify_indexnow` した瞬間に外部へ送信が飛ぶ（実際、検査のために
読み込んだだけで136件を送ってしまった）。
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    p = ROOT / ".env"
    if not p.exists():
        return {}
    return dict(l.split("=", 1) for l in p.read_text(encoding="utf-8-sig").splitlines()
                if "=" in l and not l.strip().startswith("#"))


def find_key(env):
    key = env.get("INDEXNOW_KEY", "").strip()
    if key and "YOUR_" not in key:
        return key
    # .envがない環境（GitHub Actions等）ではsite/直下のキーファイル名から自動検出
    # （IndexNowキーは公開URLに置く仕様のため秘匿不要）
    for f in (ROOT / "site").glob("*.txt"):
        if re.fullmatch(r"[0-9a-f]{16,64}", f.stem) and f.read_text().strip() == f.stem:
            return f.stem
    return ""


def sitemap_urls():
    sm = (ROOT / "site" / "sitemap.xml").read_text(encoding="utf-8")
    return re.findall(r"<loc>(.*?)</loc>", sm)


def notify(urls, key, site_url):
    payload = json.dumps({"host": site_url.split("//", 1)[-1].strip("/"), "key": key,
                          "keyLocation": f"{site_url}/{key}.txt",
                          "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        return res.status


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    env = load_env()
    key = find_key(env)
    if not key:
        raise SystemExit("INDEXNOW_KEY が未設定です（.env または site/{KEY}.txt を設置してください）")
    urls = argv or sitemap_urls()
    status = notify(urls, key, env.get("SITE_URL", "https://ai.7senses.co.jp").strip())
    print(f"IndexNow通知: {len(urls)}件 → HTTP {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
