# -*- coding: utf-8 -*-
"""配信用トークン（SITE_PUSH_TOKEN）を、貼る場所を探さずに入れ替える。

使い方: python scripts/set_push_token.py
       → トークンを聞かれるので、貼って Enter（画面には出ない）

**入れる先は2か所ある。** 手元の `.env` と GitHub Secrets。同じコードが
自分のPCとGitHubのサーバーの両方で動き、それぞれ別の場所からトークンを
読むため。片方だけ更新すると食い違う（実際そうなっていた。CI側だけ生きて、
手元は2リポジトリに書けないままだった）。ここは必ず両方へ入れる。

**書き込む前に、実際に書けるかを確かめる。** 確かめずに入れ替えると、
動いていたCIまで一緒に壊れる。1つでも書けなければ何も変更せずに終わる。

入力は getpass で受けるため、画面にもシェルの履歴にも残らない。
GitHub Secrets へも標準入力で渡すので、プロセス一覧にも出ない。
"""
import getpass
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sites as sites_mod          # noqa: E402
from token_check import _probe_write   # noqa: E402

ENVF = ROOT / ".env"
LOCAL = ROOT / "secrets.local.txt"
KEY = "SITE_PUSH_TOKEN"
WRITABLE = (201, 422)   # 422=権限はある（内容が不正なだけ）/ 403=権限が無い


def ask():
    print("新しい配信用トークンを貼り付けて Enter を押してください。")
    print("（入力は画面に表示されません。github_pat_ で始まる文字列です）")
    try:
        t = getpass.getpass("トークン: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n中止しました。何も変更していません")
        return ""
    if not t:
        print("何も入力されませんでした。何も変更していません")
        return ""
    if not re.fullmatch(r"(?:github_pat_|ghp_)[A-Za-z0-9_]{20,}", t):
        print("形式が違います。github_pat_ か ghp_ で始まる文字列を貼ってください")
        print("  （前後の空白や改行が混ざっていないか確認してください）")
        return ""
    return t


def targets():
    """配信先と、このリポジトリ自身。自分自身はCIでは別のトークンで
    push するため必須ではないが、手元から直すときに要る"""
    out, seen = [], set()
    for cfg in sites_mod.load_all().values():
        repo = cfg.get("repo")
        if not repo or repo in seen:
            continue
        seen.add(repo)
        out.append((repo, cfg["type"] != "self-static"))   # 2つ目=配信に必須か
    return out


def check(token):
    print("\n■ 書き込めるかを確かめます（何も作りません）")
    must_fail, want_fail = [], []
    for repo, required in targets():
        code = _probe_write(repo, token)
        ok = code in WRITABLE
        note = "" if required else "（配信には必須ではない）"
        print("   %-8s %-28s %s" % ("書き込み可" if ok else "権限不足", repo, note))
        if ok:
            continue
        (must_fail if required else want_fail).append(repo)
    if must_fail:
        print("\n何も変更していません。トークンの Permissions を見直してください")
        print("  Repository permissions → Contents: Read and write")
        print("  対象: " + " / ".join(must_fail))
        return False
    if want_fail:
        print("\n注意: 上の「必須ではない」リポジトリに書けません。")
        print("      記事の配信は動きますが、手元からの修正ができません")
    return True


def write_env(token):
    lines = ENVF.read_text(encoding="utf-8-sig").splitlines() if ENVF.exists() else []
    if ENVF.exists():
        bak = ROOT / f".env.backup-{datetime.now():%Y%m%d-%H%M%S}"
        bak.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
        print("   控え: %s" % bak.name)
    out, done = [], False
    for ln in lines:
        if re.match(r"\s*%s\s*=" % KEY, ln):
            out.append("%s=%s" % (KEY, token))
            done = True
        else:
            out.append(ln)
    if not done:
        out.append("%s=%s" % (KEY, token))
    ENVF.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="")
    print("   .env を更新しました（%s行目あたり）" % (out.index("%s=%s" % (KEY, token)) + 1))


def write_secret(token):
    """標準入力で渡す。--body で渡すとプロセス一覧に値が出る"""
    r = subprocess.run(["gh", "secret", "set", KEY], input=token, text=True,
                       capture_output=True, encoding="utf-8", errors="replace",
                       timeout=60)
    if r.returncode == 0:
        print("   GitHub Secrets を更新しました")
        return True
    print("   GitHub Secrets を更新できません: %s" % (r.stderr or "").strip()[:200])
    print("   （.env だけは更新済みです。gh auth login を確認してください）")
    return False


def scrub_local():
    """控えのファイルに残った古い値を消す。ファイルが残る限り読まれる余地がある"""
    if not LOCAL.exists():
        return
    src = LOCAL.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^(\s*%s\s*=).*$" % KEY, r"\1", src)
    if new != src:
        LOCAL.write_text(new, encoding="utf-8", newline="")
        print("   secrets.local.txt に残っていた古い値を消しました")


def main():
    token = ask()
    if not token:
        return 1
    if not check(token):
        return 1

    print("\n■ 2か所へ入れます")
    write_env(token)
    ok = write_secret(token)
    scrub_local()

    print("\n■ 入れ替えたあとの状態")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "token_check.py")],
                       cwd=str(ROOT), env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if r.returncode == 0 and ok:
        print("\n完了しました。ここで初めて古いトークンを削除してください")
        print("  https://github.com/settings/personal-access-tokens")
        return 0
    print("\n古いトークンはまだ削除しないでください")
    return 1


if __name__ == "__main__":
    sys.exit(main())
