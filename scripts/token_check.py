# -*- coding: utf-8 -*-
"""配信用トークン（SITE_PUSH_TOKEN）が生きているかを確かめる

使い方: python scripts/token_check.py

失効に気づかないまま記事を書き、最後のpushで落ちるのが一番もったいない。
執筆前にここで止める。終了コード 0=使える / 1=使えない
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish  # noqa: E402
import sites as sites_mod  # noqa: E402

API = "https://api.github.com"


def _api(path, token):
    r = urllib.request.Request(f"{API}{path}", headers={
        "Authorization": f"Bearer {token}", "User-Agent": "ss-aio-pipeline",
        "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(r, timeout=20) as res:
        return json.loads(res.read().decode("utf-8"))


def main():
    token = publish._push_token()
    if not token:
        print("SITE_PUSH_TOKEN が未設定です（.env か GitHub Secrets に入れてください）")
        print("TOKEN_OK=no")
        sys.exit(1)

    try:
        me = _api("/user", token)
        print(f"トークンの持ち主: {me.get('login')}")
    except urllib.error.HTTPError as e:
        print(f"トークンが無効です（{e.code} {e.reason}）。再発行が必要です")
        print("TOKEN_OK=no")
        sys.exit(1)

    ng = []
    for cfg in sites_mod.load_all().values():
        if cfg["type"] == "self-static":
            continue
        repo = cfg["repo"]
        try:
            r = _api(f"/repos/{repo}", token)
            # 読めても書けるとは限らない。push権限まで確かめる
            can = (r.get("permissions") or {}).get("push")
            if can:
                print(f"  OK       {cfg['id']:10s} {repo}（書き込み可）")
            else:
                print(f"  権限不足 {cfg['id']:10s} {repo}（読めるが書けません）")
                ng.append(repo)
        except urllib.error.HTTPError as e:
            print(f"  届かない {cfg['id']:10s} {repo}（{e.code}）")
            ng.append(repo)

    if ng:
        print("\nTOKEN_OK=no")
        print("対処: 対象リポジトリに書き込めるトークンを発行し直し、")
        print("      .env と GitHub Secrets（SITE_PUSH_TOKEN）の両方を更新してください")
        sys.exit(1)
    print("\nTOKEN_OK=yes（配信先すべてに書き込めます）")


if __name__ == "__main__":
    main()
