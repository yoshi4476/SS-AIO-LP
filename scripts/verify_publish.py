# -*- coding: utf-8 -*-
"""配信した記事が本当に公開されたかを確認する

使い方:
    python scripts/verify_publish.py --site subsidy --slug ai-hojokin-xxx
    python scripts/verify_publish.py --site corporate --slug xxx --timeout 600

なぜ必要か:
push が成功しても、配信先のビルドが落ちれば記事は公開されない。
実際、カテゴリ表示名の不一致で相手のビルドが KeyError で全停止していたのに、
こちらは「push完了」を成功として扱い、記事が消えていることに気づけなかった。

確認する順番:
  1. 配信先リポジトリのワークフローが成功したか（GitHub API）
  2. 公開URLが実際に 200 を返すか（CDNの伝播を待つためリトライする）

どちらかが駄目なら失敗として返す。呼び出し側はこれを見て再配信や記録の抑止を判断する。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"}
POLL = 20          # 何秒おきに見に行くか
BUILD_TIMEOUT = 480
LIVE_TIMEOUT = 300


def _token():
    for k in ("SITE_PUSH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        v = os.environ.get(k)
        if v:
            return v.strip()
    return None


def _api(path, token):
    req = urllib.request.Request(f"https://api.github.com{path}", headers={
        **UA, "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_build(repo, branch, since_iso, timeout=BUILD_TIMEOUT):
    """配信先リポジトリのビルドが終わるのを待ち、結果を返す。

    戻り値: (ok, 説明文)
    ワークフローが1つも動かない構成のサイトもあるため、
    待っても始まらない場合は「ビルドなし」として成功扱いにする（URL確認で担保する）。
    """
    token = _token()
    limit = time.time() + timeout
    seen = None
    while time.time() < limit:
        try:
            runs = _api(f"/repos/{repo}/actions/runs?branch={branch}&per_page=5", token)["workflow_runs"]
        except Exception as e:
            return True, f"ビルド状況を取得できないため確認をスキップ（{type(e).__name__}）"
        fresh = [r for r in runs if r["created_at"] >= since_iso]
        if not fresh:
            time.sleep(POLL)
            continue
        seen = fresh[0]
        if seen["status"] == "completed":
            ok = seen["conclusion"] == "success"
            return ok, (f"ビルド{'成功' if ok else '失敗'}: {seen['name']}"
                        f"（{seen['conclusion']}）{seen['html_url']}")
        time.sleep(POLL)
    if seen is None:
        return True, "配信先でビルドが動かない構成のため、URLの確認のみで判定します"
    return False, f"ビルドが{timeout}秒たっても終わりません: {seen['html_url']}"


def wait_live(url, timeout=LIVE_TIMEOUT):
    """公開URLが200を返すまで待つ。CDNの伝播に時間がかかるため即断しない"""
    limit = time.time() + timeout
    last = None
    while time.time() < limit:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                if r.status == 200:
                    return True, f"公開を確認: {url}"
                last = r.status
        except urllib.error.HTTPError as e:
            last = e.code
        except Exception as e:
            last = type(e).__name__
        time.sleep(POLL)
    return False, f"公開が確認できません（最後の応答 {last}）: {url}"


def verify(site_id, slug, since_iso=None, build_timeout=BUILD_TIMEOUT, live_timeout=LIVE_TIMEOUT):
    cfg = sites_mod.load(site_id)
    url = sites_mod.article_url(cfg, {"slug": slug, "category": _category_of(slug)})
    since = since_iso or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    msgs = []
    if cfg["type"] != "self-static":
        ok, m = wait_build(cfg["repo"], cfg["branch"], since, build_timeout)
        msgs.append(m)
        if not ok:
            return False, msgs
    ok, m = wait_live(url, live_timeout)
    msgs.append(m)
    return ok, msgs


def _category_of(slug):
    import re
    p = Path(__file__).resolve().parent.parent / "articles" / f"{slug}.md"
    if not p.exists():
        return ""
    m = re.search(r"^category:\s*(\S+)", p.read_text(encoding="utf-8-sig"), re.M)
    return m.group(1) if m else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--since", help="この時刻以降のビルドを見る（ISO8601・省略時は現在）")
    ap.add_argument("--build-timeout", type=int, default=BUILD_TIMEOUT)
    ap.add_argument("--live-timeout", type=int, default=LIVE_TIMEOUT)
    a = ap.parse_args()
    ok, msgs = verify(a.site, a.slug, a.since, a.build_timeout, a.live_timeout)
    for m in msgs:
        print(f"  {m}")
    print("VERIFY_OK=yes" if ok else "VERIFY_OK=no")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
