# -*- coding: utf-8 -*-
"""配信用トークン（SITE_PUSH_TOKEN）が生きているかを確かめる

使い方: python scripts/token_check.py

失効に気づかないまま記事を書き、最後のpushで落ちるのが一番もったいない。
執筆前にここで止める。終了コード 0=使える / 1=使えない

原因を取り違えないこと。以前はHTTPエラーをすべて「トークンが無効」と報じており、
GitHub側の500でも「再発行が必要です」と出していた。無効でないトークンを
作り直させると、原因が残ったまま時間だけが消える。
401/403（認証）・5xx（GitHub側）・通信不能を分けて報告する。
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish  # noqa: E402
import sites as sites_mod  # noqa: E402

API = "https://api.github.com"
RETRY = 3          # GitHub側の一時的な失敗は数秒で戻ることが多い
BACKOFF = 4        # 秒


class AuthError(Exception):
    """トークンそのものが通らない（401/403）"""


class UpstreamError(Exception):
    """GitHub側の問題。トークンの状態は判定できない"""


def _api(path, token):
    """GitHub APIを叩く。5xxは数回やり直す"""
    last = None
    for i in range(RETRY):
        req = urllib.request.Request(f"{API}{path}", headers={
            "Authorization": f"Bearer {token}", "User-Agent": "ss-aio-pipeline",
            "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                return json.loads(res.read().decode("utf-8")), res.headers
        except urllib.error.HTTPError as e:
            rid = e.headers.get("x-github-request-id", "-")
            if e.code in (401, 403):
                try:
                    msg = json.loads(e.read().decode("utf-8")).get("message", "")
                except Exception:
                    msg = ""
                # 403はレート超過のこともある。文言で分ける
                if e.code == 403 and "rate limit" in msg.lower():
                    raise UpstreamError(f"レート制限（403 {msg}） request-id={rid}")
                raise AuthError(f"{e.code} {msg or e.reason} request-id={rid}")
            if 500 <= e.code < 600:
                last = UpstreamError(f"GitHub側のエラー（{e.code} {e.reason}） request-id={rid}")
                if i < RETRY - 1:
                    print(f"   {e.code} が返りました。{BACKOFF}秒待って再試行します"
                          f"（{i + 2}/{RETRY}）")
                    time.sleep(BACKOFF)
                    continue
                raise last
            raise UpstreamError(f"{e.code} {e.reason} request-id={rid}")
        except (urllib.error.URLError, ssl.SSLError, TimeoutError) as e:
            last = UpstreamError(f"GitHubに接続できません（{type(e).__name__}: {e}）")
            if i < RETRY - 1:
                print(f"   接続に失敗しました。{BACKOFF}秒待って再試行します"
                      f"（{i + 2}/{RETRY}）")
                time.sleep(BACKOFF)
                continue
            raise last
    raise last or UpstreamError("原因不明")


def fail(kind, detail):
    print(f"\n{detail}")
    print("TOKEN_OK=no")
    if kind == "auth":
        print("対処: トークンを再発行し、.env と GitHub Secrets（SITE_PUSH_TOKEN）の")
        print("      両方を更新してください。片方だけだと手元とCIで結果が食い違います")
    elif kind == "upstream":
        print("対処: トークンの問題ではありません。GitHubの障害情報を確認し、")
        print("      https://www.githubstatus.com/ が正常なら時間をおいて再実行してください")
        print("      （再発行しても直りません）")
    sys.exit(1)


def _probe_write(repo, token):
    """書き込めるかを実際に試す。存在しないSHAで参照を作ろうとすると、
    権限があれば422（内容が不正）、無ければ403（権限が無い）が返る。
    参照は作られないので、リポジトリには何も残らない"""
    import json as _json
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/git/refs",
        data=_json.dumps({"ref": "refs/heads/_perm_probe", "sha": "0" * 40}).encode(),
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=20)
        return 201
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def main():
    token = publish._push_token()
    if not token:
        print("SITE_PUSH_TOKEN が未設定です（.env か GitHub Secrets に入れてください）")
        print("TOKEN_OK=no")
        sys.exit(1)
    # 値そのものは出さない。長さと先頭だけで取り違えに気づける
    print(f"トークン: {len(token)}文字 / 先頭 {token[:7]}…")

    try:
        me, hdr = _api("/user", token)
    except AuthError as e:
        fail("auth", f"トークンが通りません（{e}）。失効か、値の取り違えです")
    except UpstreamError as e:
        fail("upstream", f"確認できませんでした（{e}）。トークンの有効・無効は判定できていません")
    print(f"トークンの持ち主: {me.get('login')}")
    scopes = hdr.get("x-oauth-scopes")
    if scopes is not None:
        print(f"権限（scope）: {scopes or '（なし）'}")

    ng, unknown = [], []
    for cfg in sites_mod.load_all().values():
        if cfg["type"] == "self-static":
            continue
        repo = cfg["repo"]
        try:
            _api(f"/repos/{repo}", token)      # まず届くかを見る
            # permissions.push は「利用者の権限」で、トークンの権限ではない。
            # 細粒度PATが Contents:write を持たなくても True が返るため、
            # これを見ていた検査は通ってしまい、配信で403になった。
            # 書き込みを実際に試す。権限があれば422（内容が不正なだけ）が返る。
            code = _probe_write(repo, token)
            if code == 422:
                print(f"  OK       {cfg['id']:10s} {repo}（書き込み可）")
            elif code == 403:
                print(f"  権限不足 {cfg['id']:10s} {repo}"
                      f"（Contents: Read and write を付けてください）")
                ng.append(repo)
            else:
                print(f"  確認不可 {cfg['id']:10s} {repo}（HTTP {code}）")
                unknown.append(repo)
        except AuthError as e:
            print(f"  届かない {cfg['id']:10s} {repo}（{e}）")
            ng.append(repo)
        except UpstreamError as e:
            print(f"  確認不可 {cfg['id']:10s} {repo}（{e}）")
            unknown.append(repo)

    if ng:
        fail("auth", f"書き込めないリポジトリがあります: {' / '.join(ng)}")
    if unknown:
        fail("upstream", f"確認できなかったリポジトリがあります: {' / '.join(unknown)}")
    print("\nTOKEN_OK=yes（配信先すべてに書き込めます）")


if __name__ == "__main__":
    main()
