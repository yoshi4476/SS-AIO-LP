# -*- coding: utf-8 -*-
"""期限のあるトークンを自動更新する（LinkedIn / Threads / Meta）

使い方:
    python scripts/refresh_tokens.py            # 期限を確認し、近いものを更新
    python scripts/refresh_tokens.py --check    # 確認だけ（更新しない）

媒体ごとに事情が違う:
    X（OAuth 1.0a）     … 失効しない。取り消すまで有効
    Facebookページ       … 長期ユーザートークンから発行したページトークンは失効しない
    LINE公式（長期）      … 失効しない
    Threads / Meta       … 60日。期限内に交換すれば延長できる（自動更新の対象）
    LinkedIn            … アクセス60日 / リフレッシュ365日。自動更新の対象

更新した値は .env に書き戻す。CIで動かす場合は GitHub Secrets の更新も要るため、
GH_SECRET_TOKEN（Actions secretsを書ける権限）があれば併せて更新する。
"""
import base64
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
STATE = ROOT / "data" / "token_state.json"
# 期限の何日前から更新するか（当日更新だと失敗したとき打つ手が無い）
MARGIN_DAYS = 14


def read_env():
    """.env と環境変数の両方を見る。CIには .env が無く、手元にはSecretsが無いため"""
    import os
    d = {}
    if ENV.is_file():
        for line in ENV.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                d[k.strip()] = v.strip()
    for k in ("LINKEDIN_TOKEN", "LINKEDIN_REFRESH_TOKEN", "LINKEDIN_CLIENT_ID",
              "LINKEDIN_CLIENT_SECRET", "THREADS_TOKEN", "FB_USER_TOKEN",
              "FB_APP_ID", "FB_APP_SECRET", "GH_SECRET_TOKEN", "SITE_PUSH_TOKEN"):
        v = os.environ.get(k, "")
        if v:
            d[k] = v.strip()
    return d


def write_env(key, value):
    """該当行だけ差し替える（他の設定を壊さないため全書き換えはしない）"""
    if not ENV.is_file():
        return          # CIには .env が無い。GitHub Secrets 側だけ更新する
    text = ENV.read_text(encoding="utf-8-sig")
    if re.search(rf"^{re.escape(key)}=.*$", text, re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={value}", text, count=1, flags=re.M)
    else:
        text = text.rstrip("\n") + f"\n{key}={value}\n"
    ENV.write_text(text, encoding="utf-8", newline="\n")


def is_set(v):
    return bool(v) and not v.upper().startswith("YOUR_")


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.is_file() else {}


def save_state(s):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")


def days_left(state, key):
    exp = state.get(key, {}).get("expires_at")
    if not exp:
        return None
    return (datetime.fromisoformat(exp) - datetime.now(timezone.utc)).days


def stamp(state, key, seconds):
    state[key] = {"expires_at": (datetime.now(timezone.utc)
                                 + timedelta(seconds=int(seconds))).isoformat(timespec="seconds"),
                  "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


# ---------------- LinkedIn ----------------

def refresh_linkedin(e, state):
    rt = e.get("LINKEDIN_REFRESH_TOKEN", "")
    cid, cs = e.get("LINKEDIN_CLIENT_ID", ""), e.get("LINKEDIN_CLIENT_SECRET", "")
    if not all(is_set(v) for v in (rt, cid, cs)):
        return "設定不足（LINKEDIN_REFRESH_TOKEN / CLIENT_ID / CLIENT_SECRET）"
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": rt,
        "client_id": cid, "client_secret": cs}).encode()
    req = urllib.request.Request("https://www.linkedin.com/oauth/v2/accessToken", data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    write_env("LINKEDIN_TOKEN", d["access_token"])
    if d.get("refresh_token"):
        write_env("LINKEDIN_REFRESH_TOKEN", d["refresh_token"])
    stamp(state, "LINKEDIN_TOKEN", d.get("expires_in", 60 * 24 * 3600))
    return f"更新しました（{d.get('expires_in', 0) // 86400}日有効）"


# ---------------- Meta（Threads / Instagram） ----------------

def refresh_threads(e, state):
    t = e.get("THREADS_TOKEN", "")
    if not is_set(t):
        return "設定なし"
    url = ("https://graph.threads.net/refresh_access_token"
           f"?grant_type=th_refresh_token&access_token={urllib.parse.quote(t)}")
    with urllib.request.urlopen(url, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    write_env("THREADS_TOKEN", d["access_token"])
    stamp(state, "THREADS_TOKEN", d.get("expires_in", 60 * 24 * 3600))
    return f"更新しました（{d.get('expires_in', 0) // 86400}日有効）"


def refresh_meta_user(e, state):
    """Metaの長期ユーザートークンを延長する。

    ページトークンはここから発行し直すと失効しないものになるため、
    延長対象はユーザートークンのほうになる。
    """
    t = e.get("FB_USER_TOKEN", "")
    cid, cs = e.get("FB_APP_ID", ""), e.get("FB_APP_SECRET", "")
    if not all(is_set(v) for v in (t, cid, cs)):
        return "設定不足（FB_USER_TOKEN / FB_APP_ID / FB_APP_SECRET）"
    url = ("https://graph.facebook.com/v21.0/oauth/access_token"
           f"?grant_type=fb_exchange_token&client_id={cid}"
           f"&client_secret={cs}&fb_exchange_token={urllib.parse.quote(t)}")
    with urllib.request.urlopen(url, timeout=30) as r:
        d = json.loads(r.read().decode("utf-8"))
    write_env("FB_USER_TOKEN", d["access_token"])
    stamp(state, "FB_USER_TOKEN", d.get("expires_in", 60 * 24 * 3600))
    return f"更新しました（{d.get('expires_in', 0) // 86400}日有効）"


# ---------------- GitHub Secrets への反映 ----------------

def update_secret(name, value, repo, token):
    """CIで使う値も揃える。ここを忘れると手元だけ直って自動運用が止まる"""
    from nacl import encoding, public  # PyNaClが無い環境ではImportErrorで上位に伝える
    api = f"https://api.github.com/repos/{repo}/actions/secrets"
    req = urllib.request.Request(f"{api}/public-key",
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "ss-aio"})
    with urllib.request.urlopen(req, timeout=20) as r:
        k = json.loads(r.read().decode("utf-8"))
    sealed = public.SealedBox(public.PublicKey(k["key"].encode(), encoding.Base64Encoder()))
    enc = base64.b64encode(sealed.encrypt(value.encode())).decode()
    body = json.dumps({"encrypted_value": enc, "key_id": k["key_id"]}).encode()
    req2 = urllib.request.Request(f"{api}/{name}", data=body, method="PUT",
                                  headers={"Authorization": f"Bearer {token}",
                                           "Accept": "application/vnd.github+json",
                                           "User-Agent": "ss-aio"})
    with urllib.request.urlopen(req2, timeout=20) as r:
        return r.status


TASKS = [
    ("LINKEDIN_TOKEN", "LinkedIn", refresh_linkedin),
    ("THREADS_TOKEN", "Threads", refresh_threads),
    ("FB_USER_TOKEN", "Meta（ユーザー）", refresh_meta_user),
]
NEVER_EXPIRE = [
    ("X_ACCESS_TOKEN", "X", "OAuth 1.0a のため失効しません"),
    ("FB_PAGE_TOKEN", "Facebookページ", "長期ユーザートークンから発行すると失効しません"),
    ("LINE_CHANNEL_TOKEN", "LINE公式", "長期トークンは失効しません"),
]


def main():
    check_only = "--check" in sys.argv
    e = read_env()
    state = load_state()

    print("■ 失効しないトークン")
    for key, label, note in NEVER_EXPIRE:
        mark = "設定済み" if is_set(e.get(key, "")) else "未設定"
        print(f"  {label:16s} {mark:8s} {note}")

    print("\n■ 期限があるトークン")
    changed = []
    for key, label, fn in TASKS:
        left = days_left(state, key)
        cur = f"残り{left}日" if left is not None else "期限が未記録"
        if not is_set(e.get(key, "")):
            print(f"  {label:16s} 未設定")
            continue
        if check_only:
            print(f"  {label:16s} {cur}")
            continue
        if left is not None and left > MARGIN_DAYS:
            print(f"  {label:16s} {cur} — まだ更新しません")
            continue
        try:
            msg = fn(e, state)
            print(f"  {label:16s} {msg}")
            if "更新" in msg:
                changed.append(key)
        except urllib.error.HTTPError as ex:
            print(f"  {label:16s} 失敗（{ex.code}）— 手動での再取得が要ります")
        except Exception as ex:
            print(f"  {label:16s} 失敗（{str(ex)[:60]}）")

    if changed:
        save_state(state)
        gh = e.get("GH_SECRET_TOKEN") or e.get("SITE_PUSH_TOKEN", "")
        repo = e.get("HUB_REPO", "yoshi4476/SS-AIO-LP")
        if is_set(gh):
            e2 = read_env()
            for key in changed:
                try:
                    update_secret(key, e2.get(key, ""), repo, gh)
                    print(f"  GitHub Secrets を更新: {key}")
                except ImportError:
                    print("  GitHub Secrets の更新には PyNaCl が要ります"
                          "（python -m pip install pynacl）")
                    break
                except Exception as ex:
                    print(f"  GitHub Secrets の更新に失敗: {key}（{str(ex)[:60]}）")
        else:
            print("  ※ GitHub Secrets は手動で更新してください"
                 "（GH_SECRET_TOKEN を設定すると自動化されます）")

    if not check_only:
        save_state(state)


if __name__ == "__main__":
    main()
