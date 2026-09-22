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


def sitemap_urls(domain=None):
    """公開中の sitemap。他サイトは手元に無いのでHTTPで取る"""
    if domain is None:
        sm = (ROOT / "site" / "sitemap.xml").read_text(encoding="utf-8")
        return re.findall(r"<loc>(.*?)</loc>", sm)
    try:
        import urllib.request as _u
        req = _u.Request(f"https://{domain}/sitemap.xml", headers={"User-Agent": "Mozilla/5.0"})
        with _u.urlopen(req, timeout=30) as r:
            return re.findall(r"<loc>(.*?)</loc>", r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"  {domain}: sitemapを取得できません（{str(e)[:50]}）")
        return []


def key_ok(domain, key):
    """鍵ファイルが置かれているか。無いドメインへの通知は拒否される（実際にそうなっていた）"""
    try:
        import urllib.request as _u
        req = _u.Request(f"https://{domain}/{key}.txt", headers={"User-Agent": "Mozilla/5.0"})
        with _u.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", "ignore").strip() == key
    except Exception:
        return False


def notify(urls, key, site_url):
    payload = json.dumps({"host": site_url.split("//", 1)[-1].strip("/"), "key": key,
                          "keyLocation": f"{site_url}/{key}.txt",
                          "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=payload,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        return res.status


def main(argv=None):
    """3サイトすべてに通知する。以前は AI集客ラボ だけを見ていたため、
    コーポレートと補助金は記事を出しても検索エンジンに知らせていなかった"""
    argv = sys.argv[1:] if argv is None else argv
    env = load_env()
    key = find_key(env)
    if not key:
        raise SystemExit("INDEXNOW_KEY が未設定です（.env または site/{KEY}.txt を設置してください）")
    if argv:
        status = notify(argv, key, env.get("SITE_URL", "https://ai.7senses.co.jp").strip())
        print(f"IndexNow通知: {len(argv)}件 → HTTP {status}")
        return 0
    sys.path.insert(0, str(ROOT / "scripts"))
    import sites as S
    sent = 0
    for sid, cfg in S.load_all().items():
        dom = cfg["domain"]
        if not key_ok(dom, key):
            print(f"  {sid}: 鍵ファイル https://{dom}/{key}.txt がありません（通知は拒否されます）")
            continue
        urls = sitemap_urls(None if sid == S.primary() else dom)
        if not urls:
            continue
        try:
            status = notify(urls, key, f"https://{dom}")
        except Exception as e:
            print(f"  {sid}: 通知に失敗（{str(e)[:60]}）")
            continue
        sent += len(urls)
        print(f"  {sid}: {len(urls)}件 → HTTP {status}")
    print(f"IndexNow通知: 合計{sent}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
