# -*- coding: utf-8 -*-
"""管制塔（スプレッドシート＋Apps Script）を作るところまでを通しで行う

これまで手順書には「スプレッドシートを新規作成し、Apps Script を開き、
6ファイルを貼り、先頭3行を書き換え、setup を実行し、デプロイする」と
書いてあった。8手順あり、貼り忘れ・ファイル名の付け間違いが起きる。
ファイル名を1つ間違えると同じ関数が二重定義になり、プロジェクト全体が
黙って動かなくなるため、原因の特定に時間がかかる。

ここで作るもの:
  1. スプレッドシート「<社名> 自動化管制塔」
  2. そこに紐づいた Apps Script プロジェクト（6ファイル）
  3. ウェブアプリのデプロイ（/exec のURL）
  4. .env への HUB_URL / HUB_SECRET / GAS_SCRIPT_ID_HUB の書き込み

合言葉は自動で作る。人が決めると短くなりがちで、
このURLは誰でも叩ける場所に出るため推測されると台帳を書き換えられる。

使い方:
    python scripts/bootstrap.py --check                 # 権限だけ見る
    python scripts/bootstrap.py --name "株式会社○○" --notify you@example.com

clasp のログインを使う。未ログインなら先に npx @google/clasp login。
"""
import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLASPRC = Path.home() / ".clasprc.json"

# 配置先のファイル名。ここを変えると同じ関数が二重定義になる
FILES = [
    ("automation/gas/hub.gs", "コード"),
    ("automation/gas/kpi.gs", "KPI"),
    ("automation/gas/contact.hub.gs", "contact"),
    ("automation/gas/migrate.gs", "migrate"),
    ("automation/gas/format.gs", "format"),
    ("automation/gas/dashboard.gs", "dashboard"),
]

MANIFEST = {
    "timeZone": "Asia/Tokyo",
    "dependencies": {},
    "exceptionLogging": "STACKDRIVER",
    "runtimeVersion": "V8",
    "webapp": {"executeAs": "USER_DEPLOYING", "access": "ANYONE_ANONYMOUS"},
    "oauthScopes": [
        "https://www.googleapis.com/auth/spreadsheets.currentonly",
        "https://www.googleapis.com/auth/script.send_mail",
        "https://www.googleapis.com/auth/script.scriptapp",
        "https://www.googleapis.com/auth/script.external_request",
    ],
}


def token():
    if not CLASPRC.is_file():
        raise SystemExit("clasp にログインしていません。npx @google/clasp login を先に実行してください")
    t = json.loads(CLASPRC.read_text(encoding="utf-8"))["tokens"]["default"]
    body = urllib.parse.urlencode({
        "client_id": t["client_id"], "client_secret": t["client_secret"],
        "refresh_token": t["refresh_token"], "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=body), timeout=30) as r:
        d = json.load(r)
    return d["access_token"], d.get("scope", "").split()


def whoami(tok):
    """どのGoogleアカウントで作るのかを出す。

    clasp のログイン先が意図と違うと、別アカウントの中に管制塔ができる。
    見た目には成功するのに、あとから本人が開けず、原因も分かりにくい。
    """
    try:
        req = urllib.request.Request(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("email", "")
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
        return ""


def call(tok, url, method="GET", body=None):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"APIが断りました（{e.code}）\n  {url}\n  {detail}")


def make_sheet(tok, title):
    """Drive経由で作る。Sheets APIの作成は別の権限が要るため使わない"""
    return call(tok, "https://www.googleapis.com/drive/v3/files", "POST",
                {"name": title, "mimeType": "application/vnd.google-apps.spreadsheet"})["id"]


def fill_head(src, book_id, secret, notify):
    """hub.gs の先頭3行を埋める。空のまま配ると誰でも台帳を書き換えられる"""
    out = []
    for line in src.split("\n"):
        s = line.strip()
        if s.startswith("const BOOK_ID"):
            out.append(f"const BOOK_ID = '{book_id}';")
        elif s.startswith("const SHARED_SECRET"):
            out.append(f"const SHARED_SECRET = '{secret}';")
        elif s.startswith("const NOTIFY_TO"):
            out.append(f"const NOTIFY_TO = '{notify}';")
        else:
            out.append(line)
    return "\n".join(out)


def read_env():
    out = {}
    p = ROOT / ".env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def write_env(pairs):
    p = ROOT / ".env"
    lines = p.read_text(encoding="utf-8-sig").splitlines() if p.is_file() else []
    for k, v in pairs.items():
        for i, line in enumerate(lines):
            if line.split("=", 1)[0].strip() == k:
                lines[i] = f"{k}={v}"
                break
        else:
            lines.append(f"{k}={v}")
    p.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")


def post_exec(url, secret, body, tries=3):
    """デプロイ直後は反映待ちがあるので数回試す"""
    payload = dict(body)
    payload["secret"] = secret
    data = json.dumps(payload).encode()
    for n in range(tries):
        try:
            req = urllib.request.Request(url, data=data, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            if n == tries - 1:
                return {"ok": False, "error": str(e)[:200]}
            time.sleep(6)
    return {"ok": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", help="会社名。スプレッドシートの名前になる")
    ap.add_argument("--notify", default="", help="問い合わせの通知先メール")
    ap.add_argument("--check", action="store_true", help="権限の確認だけ")
    ap.add_argument("--verify", action="store_true",
                    help="画面で「初期設定」を実行したあと、疎通を確かめる")
    a = ap.parse_args()

    if a.verify:
        e = read_env()
        if not e.get("HUB_URL"):
            raise SystemExit("HUB_URL がありません。先に管制塔を作ってください")
        r = post_exec(e["HUB_URL"], e.get("HUB_SECRET", ""),
                      {"action": "admin", "task": "dashboard"})
        if r.get("ok"):
            print("○ 管制塔とつながりました")
            print("  ダッシュボード:", r.get("result", r))
        else:
            print("× まだつながりません:", str(r.get("error", r))[:150])
            print("  スプレッドシート → 拡張機能 → Apps Script で")
            print("  関数「初期設定」を実行し、権限を承認してください")
        return

    tok, scopes = token()
    need = {"https://www.googleapis.com/auth/drive.file": "スプレッドシートの作成",
            "https://www.googleapis.com/auth/script.projects": "コードの配置",
            "https://www.googleapis.com/auth/script.deployments": "デプロイ"}
    who = whoami(tok)
    print(f"■ ログイン中: {who or '（不明）'}")
    print("■ 権限")
    ng = False
    for s, why in need.items():
        ok = s in scopes
        ng = ng or not ok
        print(f"   {'○' if ok else '×'} {why}")
    if ng:
        raise SystemExit("権限が足りません。npx @google/clasp login をやり直してください")
    if a.check:
        return
    if not a.name:
        raise SystemExit("--name に会社名を指定してください")

    e = read_env()
    if e.get("HUB_URL"):
        print(f"\n既に管制塔があります: {e['HUB_URL']}")
        print("  管制塔はクライアントごとに1つです。")
        print("  同じクライアントのサイトを増やすだけなら、作り直さずに")
        print("  setup_from_sheet.py を実行してください（既存の管制塔に足されます）。")
        print("  ここで作ると .env が新しい管制塔に切り替わり、"
              "これまでの台帳を読まなくなります。")
        if input("それでも新しく作りますか（y で続行）: ").strip().lower() != "y":
            return

    secret = secrets.token_urlsafe(24)
    title = f"{a.name} 自動化管制塔"
    if who:
        print(f"\n{who} のドライブに「{title}」を作ります。")
        if input("よろしければ y: ").strip().lower() != "y":
            raise SystemExit("中止しました。別のアカウントで作るなら "
                             "npx @google/clasp login をやり直してください")

    print(f"\n■ スプレッドシートを作る")
    book = make_sheet(tok, title)
    print(f"   https://docs.google.com/spreadsheets/d/{book}/edit")

    print("■ コードを配る")
    files = [{"name": "appsscript", "type": "JSON",
              "source": json.dumps(MANIFEST, ensure_ascii=False, indent=2)}]
    for local, remote in FILES:
        src = (ROOT / local).read_text(encoding="utf-8")
        if remote == "コード":
            src = fill_head(src, book, secret, a.notify)
        files.append({"name": remote, "type": "SERVER_JS", "source": src})
    sid = call(tok, "https://script.googleapis.com/v1/projects", "POST",
               {"title": title, "parentId": book})["scriptId"]
    call(tok, f"https://script.googleapis.com/v1/projects/{sid}/content", "PUT",
         {"files": files})
    print(f"   {len(FILES)}ファイル")

    print("■ デプロイする")
    ver = call(tok, f"https://script.googleapis.com/v1/projects/{sid}/versions", "POST",
               {"description": "初回"})["versionNumber"]
    dep = call(tok, f"https://script.googleapis.com/v1/projects/{sid}/deployments", "POST",
               {"versionNumber": ver, "manifestFileName": "appsscript",
                "description": "web app"})
    url = ""
    for c in dep.get("entryPoints", []):
        if c.get("entryPointType") == "WEB_APP":
            url = c["webApp"]["url"]
    if not url:
        url = f"https://script.google.com/macros/s/{dep['deploymentId']}/exec"
    print(f"   {url}")

    write_env({"HUB_URL": url, "HUB_SECRET": secret, "GAS_SCRIPT_ID_HUB": sid})
    print("■ .env に書きました（HUB_URL / HUB_SECRET / GAS_SCRIPT_ID_HUB）")

    # タブの作成はここでは試さない。作ったばかりのプロジェクトは、
    # 本人が画面で権限を承認するまでWebアプリが403を返す。
    # 試すと「まだ動きません」と出て、失敗したように見えてしまう。

    print("\n" + "=" * 56)
    print(f"管制塔: https://docs.google.com/spreadsheets/d/{book}/edit")
    print("\n【この1回だけ画面での作業が要ります】")
    print("  1. 上のスプレッドシートを開く")
    print("  2. 拡張機能 → Apps Script")
    print("  3. 関数の一覧から「初期設定」を選んで実行 → 権限を承認")
    print("\n  タブの作成・見た目の調整・メール送信の承認・毎朝の集計登録が")
    print("  まとめて終わります。")
    print("  メール送信とトリガー登録は、本人が画面で承認したときにしか")
    print("  許可されないため、ここだけ自動にできません。")
    print(f"\n  終わったら: python scripts/bootstrap.py --verify")


if __name__ == "__main__":
    main()
