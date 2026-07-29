# -*- coding: utf-8 -*-
"""管制塔（GASスプレッドシート）との通信

記事工場（GitHub Actions）から、キーワードの取得・着手記録・公開記録を行う。
HUB_URL が未設定の場合はローカルのKWリスト（docs/*.md）にフォールバックするため、
管制塔が未設置でもパイプラインは止まらない。

使い方（単体確認）:
    python scripts/hub_client.py status
    python scripts/hub_client.py next corporate
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"}
TIMEOUT = 30


def _env():
    env = dict(os.environ)
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                env.setdefault(k.strip(), v.strip())
    return env


ENV = _env()
HUB_URL = ENV.get("HUB_URL", "").strip()
HUB_SECRET = ENV.get("HUB_SECRET", "").strip()


def enabled():
    return bool(HUB_URL)


def _get(params):
    url = HUB_URL + ("&" if "?" in HUB_URL else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def _post(body):
    body = dict(body)
    body["secret"] = HUB_SECRET
    req = urllib.request.Request(
        HUB_URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def next_kw(site):
    """次に書くKWを取得。管制塔が使えなければ None を返す（呼び出し側でローカルにフォールバック）"""
    if not enabled():
        return None
    try:
        return _get({"action": "next_kw", "site": site})
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"管制塔に接続できません（ローカルのKWリストを使います）: {e}")
        return None


def all_kw():
    if not enabled():
        return []
    try:
        return _get({"action": "all_kw"}).get("keywords", [])
    except Exception:
        return []


def status(site=""):
    if not enabled():
        return {"ok": False, "error": "HUB_URL 未設定"}
    return _get({"action": "kw_status", "site": site})


def claim_kw(site, keyword):
    return _post({"action": "claim_kw", "site": site, "keyword": keyword}) if enabled() else None


def add_kw(site, keywords):
    return _post({"action": "add_kw", "site": site, "keywords": keywords}) if enabled() else None


def publish_log(**kw):
    """公開結果を記録。失敗してもパイプラインは止めない"""
    if not enabled():
        return None
    try:
        return _post({"action": "publish_log", **kw})
    except Exception as e:
        print(f"管制塔への公開記録に失敗（記事の公開は完了しています）: {e}")
        return None


def error_log(site, phase, message):
    if not enabled():
        return None
    try:
        return _post({"action": "error_log", "site": site, "phase": phase, "message": message})
    except Exception:
        return None


def main():
    if not enabled():
        raise SystemExit("HUB_URL が未設定です（.env または環境変数に設定してください）")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    site = sys.argv[2] if len(sys.argv) > 2 else ""
    if cmd == "status":
        for s in ([site] if site else ["ai-lab", "subsidy", "corporate"]):
            r = status(s)
            print(f"{s:10s} 全{r.get('total', 0):3d}件  未着手{r.get('todo', 0):3d}  "
                  f"執筆中{r.get('doing', 0):2d}  公開済み{r.get('done', 0):3d}")
    elif cmd == "next":
        print(json.dumps(next_kw(site), ensure_ascii=False, indent=2))
    elif cmd == "all":
        for k in all_kw():
            print(f"{k['site']:10s} {k['status']:6s} {k['keyword']}")
    else:
        raise SystemExit("使い方: python scripts/hub_client.py [status|next|all] [site]")


if __name__ == "__main__":
    main()
