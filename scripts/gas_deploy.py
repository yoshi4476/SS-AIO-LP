# -*- coding: utf-8 -*-
"""Apps Script のコードを配って、デプロイまで自動で行う

これまでは Apps Script エディタを開いてコードを貼り、デプロイを押す手作業だった。
1か所直すたびに2プロジェクトぶん同じ操作をするため、直し忘れが起きる。

clasp（Apps Script の CLI）で push とデプロイまで通す。
初回だけ、各プロジェクトのスクリプトIDを .env に入れる必要がある。
  GAS_SCRIPT_ID_CORPORATE=...
  GAS_SCRIPT_ID_SUBSIDY=...
スクリプトIDは Apps Script エディタの「プロジェクトの設定」で確認できる。

使い方:
    python scripts/gas_deploy.py --check          # 接続できるかだけ見る
    python scripts/gas_deploy.py corporate        # 1つ配る
    python scripts/gas_deploy.py --all            # 全部配る
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLASPRC = Path.home() / ".clasprc.json"

# 配る対象。どのサイトへ、どのファイルを置くか
TARGETS = {
    "corporate": {
        "name": "コーポレートサイト",
        "env": "GAS_SCRIPT_ID_CORPORATE",
        "files": [("automation/gas/forward-to-hub.gs", "forward-to-hub.gs")],
    },
    "subsidy": {
        "name": "AI導入補助金サポート",
        "env": "GAS_SCRIPT_ID_SUBSIDY",
        "files": [("automation/gas/forward-to-hub.gs", "forward-to-hub.gs")],
    },
    "hub": {
        "name": "管制塔",
        "env": "GAS_SCRIPT_ID_HUB",
        # 配布先のファイル名に合わせる。別名で置くと同じ関数が二重定義になり、
        # プロジェクト全体が動かなくなる。
        "files": [("automation/gas/hub.gs", "コード.gs"),
                  ("automation/gas/kpi.gs", "KPI.gs"),
                  ("automation/gas/contact.hub.gs", "contact.gs"),
                  ("automation/gas/migrate.gs", "migrate.gs"),
                  ("automation/gas/format.gs", "format.gs"),
                  ("automation/gas/dashboard.gs", "dashboard.gs")],
    },
}


def env():
    out = {}
    p = ROOT / ".env"
    if p.is_file():
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def token():
    """clasp のログイン情報を使い回す。期限切れでも refresh_token で更新できる"""
    if not CLASPRC.is_file():
        raise SystemExit("clasp にログインしていません。npx @google/clasp login を先に実行してください")
    t = json.loads(CLASPRC.read_text(encoding="utf-8"))["tokens"]["default"]
    body = urllib.parse.urlencode({
        "client_id": t["client_id"], "client_secret": t["client_secret"],
        "refresh_token": t["refresh_token"], "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=body), timeout=30) as r:
        return json.load(r)["access_token"]


def api(tok, path, method="GET", body=None):
    req = urllib.request.Request(
        f"https://script.googleapis.com/v1/{path}",
        data=json.dumps(body).encode() if body else None, method=method,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def fill(src_text, e):
    """URLと合言葉を埋める。プレースホルダのまま配ると転送が黙って止まる"""
    return (src_text
            .replace("https://script.google.com/macros/s/XXXXXXXXXXXXXXXX/exec",
                     e.get("HUB_URL", ""))
            .replace("'XXXXXXXXXXXXXXXX'", f"'{e.get('HUB_SECRET', '')}'"))


# 既存の doPost に転送の呼び出しを1行足す。ここだけは新規ファイルの追加では済まない。
# 手で入れると片方だけ忘れるので、目印の直前／直後に機械的に差し込む。
HOOKS = {
    "corporate": {
        "call": "    forwardToHub_(payload, 'corporate');",
        # 「return json({ ok: true });」だけだと、送信を破棄する分岐にも同じ行があり
        # そちらに入ってしまう。doPost の最後を指す形にする。
        "anchor": "    return json({ ok: true });\n  } catch (err) {",
        "where": "before",
    },
    "subsidy": {
        "call": "  forwardToHub_(lead, 'subsidy');",
        "anchor": "    try { lock.releaseLock(); } catch (e2) {}\n  }",
        "where": "after",
    },
}


def inject(files, site):
    """転送の呼び出しを差し込む。既に入っていれば何もしない（何度実行しても同じ結果）"""
    h = HOOKS.get(site)
    if not h:
        return False
    for f in files.values():
        src = f.get("source", "")
        if "forwardToHub_(" in src and "function forwardToHub_" not in src:
            print("      呼び出しは既に入っています")
            return False
    for f in files.values():
        src = f.get("source", "")
        if "function doPost" not in src or h["anchor"] not in src:
            continue
        if h["where"] == "before":
            f["source"] = src.replace(h["anchor"], h["call"] + "\n\n" + h["anchor"], 1)
        else:
            f["source"] = src.replace(h["anchor"], h["anchor"] + "\n\n" + h["call"], 1)
        print(f"      {f['name']}.gs に呼び出しを追加")
        return True
    print("      目印が見つからず、呼び出しを追加できませんでした（手順書の位置に手で追加してください）")
    return False


def push(site, e, tok, deploy=True):
    cfg = TARGETS[site]
    sid = e.get(cfg["env"], "")
    if not sid:
        print(f"  {cfg['name']}: {cfg['env']} が未設定のため飛ばします")
        return False

    # いまプロジェクトに入っているファイルを取得し、対象ファイルだけ差し替える。
    # 全置換にすると既存の doPost ごと消えるため、必ずマージする。
    cur = api(tok, f"projects/{sid}/content")
    files = {f["name"]: f for f in cur.get("files", [])}
    for local, remote in cfg["files"]:
        name = remote.rsplit(".", 1)[0]
        src = fill((ROOT / local).read_text(encoding="utf-8"), e)
        files[name] = {"name": name, "type": "SERVER_JS", "source": src}
        print(f"      {local} → {name}")
    if site in HOOKS:
        inject(files, site)
    api(tok, f"projects/{sid}/content", "PUT", {"files": list(files.values())})
    print(f"  {cfg['name']}: コードを更新しました（{len(files)}ファイル）")

    if not deploy:
        return True
    # 既存のデプロイを新しいバージョンに差し替える。
    # 新規に作ると公開URLが変わり、各サイトのフォームが旧URLを向いたままになる。
    ver = api(tok, f"projects/{sid}/versions", "POST",
              {"description": "自動配信"})["versionNumber"]
    deps = api(tok, f"projects/{sid}/deployments").get("deployments", [])
    live = [d for d in deps if d.get("deploymentConfig", {}).get("versionNumber")]
    if not live:
        print("      公開中のデプロイが無いため、バージョン作成のみ")
        return True
    for d in live:
        c = d["deploymentConfig"]
        api(tok, f"projects/{sid}/deployments/{d['deploymentId']}", "PUT",
            {"deploymentConfig": {"scriptId": sid, "versionNumber": ver,
                                  "manifestFileName": c.get("manifestFileName", "appsscript"),
                                  "description": c.get("description", "")}})
        print(f"      デプロイ更新: v{ver}（{d['deploymentId'][:18]}…）")
    return True


def main():
    e = env()
    tok = token()
    if "--check" in sys.argv:
        print("  clasp の認証: 有効")
        for site, cfg in TARGETS.items():
            sid = e.get(cfg["env"], "")
            if not sid:
                print(f"  {cfg['name']:<22} {cfg['env']} 未設定")
                continue
            try:
                c = api(tok, f"projects/{sid}/content")
                names = [f["name"] for f in c.get("files", [])]
                print(f"  {cfg['name']:<22} 接続OK / ファイル {len(names)}件: {', '.join(names[:6])}")
            except Exception as ex:
                print(f"  {cfg['name']:<22} 接続できません: {str(ex)[:70]}")
        return

    sites = list(TARGETS) if "--all" in sys.argv else [a for a in sys.argv[1:] if a in TARGETS]
    if not sites:
        raise SystemExit("対象を指定してください（corporate / subsidy / hub / --all / --check）")
    for s in sites:
        push(s, e, tok, deploy="--no-deploy" not in sys.argv)


if __name__ == "__main__":
    main()
