# -*- coding: utf-8 -*-
"""SNS のアカウントをサイト（社）ごとにつなぐ。鍵は GitHub の SOCIAL_TOKENS_JSON に1つにまとめる。

鍵はチャットにもコマンドにも出さない。この PC に入力欄を出して受け取る。
自社の3サイトは共通のアカウント（_default）、クライアントはその社のアカウントにだけ投稿する
（その社の鍵が無ければ投稿しない。post_social.pick）。

    python scripts/social_connect.py --site _default --facebook          # Facebook ページと Instagram
    python scripts/social_connect.py --site <社のID> --facebook --page "ページ名の一部"
    python scripts/social_connect.py --site <社のID> --threads
    python scripts/social_connect.py --site <社のID> --linkedin
    python scripts/social_connect.py --list                              # つないだ社と期限
    python scripts/social_connect.py --check                             # 期限の近い鍵（週次の findings が呼ぶ）

Facebook・Instagram: クライアントがセブンセンシズの Facebook アカウントにページの管理権限を付けていれば、
こちらの許可だけで、その社のページの鍵（期限なし）と Instagram の ID が取れる。
Threads・LinkedIn: 投稿するのは許可した本人のアカウントなので、その社の担当者が許可のリンクを押す。
鍵は60日で切れる。切れる14日前から要対応で知らせる。
"""
import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
FILE = ROOT / "social-tokens.json"
REPO = "yoshi4476/SS-AIO-LP"
GRAPH = "https://graph.facebook.com/v21.0"


def ask(title, prompt, secret=True):
    """この PC の画面に入力欄を出す（チャットや履歴に鍵を残さない）"""
    import tkinter as tk
    from tkinter import simpledialog
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    v = simpledialog.askstring(title, prompt, show="*" if secret else None, parent=root)
    root.destroy()
    return (v or "").strip()


def load():
    return json.loads(FILE.read_text(encoding="utf-8")) if FILE.is_file() else {}


def save(d):
    FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    # GitHub の Secret も同じ内容にする（CI の投稿はこれを読む）
    r = subprocess.run(["gh", "secret", "set", "SOCIAL_TOKENS_JSON", "--repo", REPO],
                       input=json.dumps(d, ensure_ascii=False), text=True, encoding="utf-8",
                       capture_output=True)
    print("  GitHub に登録しました" if r.returncode == 0 else
          f"  GitHub に登録できませんでした（gh auth login を確認）: {r.stderr.strip()[:120]}")


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def meta_app(d):
    """Meta のアプリ ID とシークレット。一度入れたら控えを使う"""
    app = d.setdefault("_meta_app", {})
    if not app.get("id"):
        app["id"] = ask("Meta のアプリ", "アプリ ID（設定 → ベーシック）", secret=False)
        app["secret"] = ask("Meta のアプリ", "アプリシークレット（設定 → ベーシック）")
    return app


def facebook(site, page_hint):
    d = load()
    app = meta_app(d)
    short = ask("Facebook", "グラフ API エクスプローラで作ったユーザーのトークン")
    if not (app.get("id") and app.get("secret") and short):
        raise SystemExit("入力が空のため中止しました")
    # 短期（1〜2時間）→ 長期（60日）のユーザートークン。そこから取ったページのトークンは期限が無い
    long = get(f"{GRAPH}/oauth/access_token?" + urllib.parse.urlencode({
        "grant_type": "fb_exchange_token", "client_id": app["id"], "client_secret": app["secret"],
        "fb_exchange_token": short}))["access_token"]
    pages = get(f"{GRAPH}/me/accounts?" + urllib.parse.urlencode({
        "fields": "name,id,access_token,instagram_business_account{id,username}",
        "access_token": long, "limit": 100})).get("data", [])
    if not pages:
        raise SystemExit("管理しているページがありません（ページの管理権限と pages_show_list の許可を確認）")
    print("  管理しているページ:")
    for p in pages:
        ig = (p.get("instagram_business_account") or {}).get("username")
        print(f"   - {p['name']}" + (f"（Instagram @{ig}）" if ig else "（Instagram なし）"))
    hit = [p for p in pages if page_hint and page_hint in p["name"]] if page_hint else pages
    if len(hit) != 1:
        raise SystemExit("ページを1つに決められません。--page にページ名の一部を入れて実行し直してください")
    p = hit[0]
    ent = d.setdefault(site, {})
    ent.update({"FB_PAGE_ID": p["id"], "FB_PAGE_TOKEN": p["access_token"], "FB_PAGE_NAME": p["name"]})
    ig = p.get("instagram_business_account") or {}
    if ig.get("id"):
        ent["IG_USER_ID"] = ig["id"]
    save(d)
    print(f"  {site}: Facebook「{p['name']}」" + (f"と Instagram @{ig.get('username')}" if ig else "") + " をつなぎました")


def threads(site):
    d = load()
    app = meta_app(d)
    short = ask("Threads", "Threads のユーザートークン（アプリの「Threads API の利用」→ トークン生成）")
    if not short:
        raise SystemExit("入力が空のため中止しました")
    tok = get("https://graph.threads.net/access_token?" + urllib.parse.urlencode({
        "grant_type": "th_exchange_token", "client_secret": app["secret"], "access_token": short}))
    me = get("https://graph.threads.net/v1.0/me?" + urllib.parse.urlencode({
        "fields": "id,username", "access_token": tok["access_token"]}))
    ent = d.setdefault(site, {})
    ent.update({"THREADS_TOKEN": tok["access_token"], "THREADS_USER_ID": me["id"],
                "THREADS_EXPIRES": (date.today() + timedelta(seconds=int(tok.get("expires_in", 5184000)))).isoformat()})
    save(d)
    print(f"  {site}: Threads @{me.get('username')} をつなぎました（期限 {ent['THREADS_EXPIRES']}）")


def linkedin(site):
    """個人として投稿する許可（Share on LinkedIn・審査なし）。ブラウザで許可すると戻ってくる"""
    import http.server
    import secrets as _s
    import webbrowser
    d = load()
    app = d.setdefault("_linkedin_app", {})
    if not app.get("id"):
        app["id"] = ask("LinkedIn のアプリ", "Client ID（Auth タブ）", secret=False)
        app["secret"] = ask("LinkedIn のアプリ", "Client Secret（Auth タブ）")
    redirect, state, got = "http://localhost:8765/callback", _s.token_urlsafe(16), {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("許可を受け取りました。この画面は閉じてかまいません。".encode("utf-8"))

        def log_message(self, *a):
            pass

    url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": app["id"], "redirect_uri": redirect, "state": state,
        "scope": "openid profile w_member_social"})
    print("  このURLをブラウザで開いて許可してください（自動で開きます）:\n  " + url)
    webbrowser.open(url)
    http.server.HTTPServer(("localhost", 8765), H).handle_request()
    if got.get("state") != state or not got.get("code"):
        raise SystemExit(f"許可を受け取れませんでした（{got.get('error_description') or got.get('error') or '不明'}）")
    req = urllib.request.Request("https://www.linkedin.com/oauth/v2/accessToken", data=urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": got["code"], "redirect_uri": redirect,
        "client_id": app["id"], "client_secret": app["secret"]}).encode())
    with urllib.request.urlopen(req, timeout=60) as r:
        tok = json.loads(r.read().decode("utf-8"))
    ui = urllib.request.Request("https://api.linkedin.com/v2/userinfo",
                                headers={"Authorization": f"Bearer {tok['access_token']}"})
    with urllib.request.urlopen(ui, timeout=30) as r:
        me = json.loads(r.read().decode("utf-8"))
    ent = d.setdefault(site, {})
    ent.update({"LINKEDIN_TOKEN": tok["access_token"], "LINKEDIN_PERSON_ID": me["sub"],
                "LINKEDIN_EXPIRES": (date.today() + timedelta(seconds=int(tok.get("expires_in", 5184000)))).isoformat()})
    save(d)
    print(f"  {site}: LinkedIn（{me.get('name', '')}）をつなぎました（期限 {ent['LINKEDIN_EXPIRES']}）")


def listing():
    d = load()
    for site, ent in d.items():
        if site.startswith("_") and site != "_default":
            continue
        have = [k for k, on in (("Facebook", "FB_PAGE_TOKEN"), ("Instagram", "IG_USER_ID"),
                                ("Threads", "THREADS_TOKEN"), ("LinkedIn", "LINKEDIN_TOKEN")) if ent.get(on)]
        exp = " / ".join(f"{k} {ent[k]}" for k in ("THREADS_EXPIRES", "LINKEDIN_EXPIRES") if ent.get(k))
        print(f"  {site:<12} {' ・ '.join(have) or '（なし）'}" + (f"  期限: {exp}" if exp else ""))
    return 0


def check():
    """期限が14日以内の鍵を要対応で知らせる。CI では SOCIAL_TOKENS_JSON を読む"""
    import os
    raw = os.environ.get("SOCIAL_TOKENS_JSON") or (FILE.read_text(encoding="utf-8") if FILE.is_file() else "{}")
    d = json.loads(raw or "{}")
    soon, today = [], date.today()
    for site, ent in d.items():
        for k, name, flag in (("THREADS_EXPIRES", "Threads", "--threads"), ("LINKEDIN_EXPIRES", "LinkedIn", "--linkedin")):
            if ent.get(k) and date.fromisoformat(ent[k]) - today <= timedelta(days=14):
                soon.append(f"{site} の {name}（期限 {ent[k]}）→ python scripts/social_connect.py --site {site} {flag}")
    print(f"■ SNS の鍵: {len([s for s in d if not s.startswith('_') or s == '_default'])}社")
    for s in soon:
        print("要対応: SNS の鍵の期限が近い: " + s)
    print("SOCIAL_OK=" + ("no" if soon else "yes"))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--facebook", action="store_true")
    ap.add_argument("--threads", action="store_true")
    ap.add_argument("--linkedin", action="store_true")
    ap.add_argument("--page", default="", help="Facebook ページ名の一部（複数ページを管理しているとき）")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.list:
        return listing()
    if a.check:
        return check()
    if not a.site:
        raise SystemExit("--site に社のID（自社3サイト共通は _default）を入れてください")
    if a.facebook:
        facebook(a.site, a.page)
    if a.threads:
        threads(a.site)
    if a.linkedin:
        linkedin(a.site)
    return 0


if __name__ == "__main__":
    sys.exit(main())
