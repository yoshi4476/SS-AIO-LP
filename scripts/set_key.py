# -*- coding: utf-8 -*-
"""APIキーを、貼る場所を探さずに設定する。

    python scripts/set_key.py RAKKO_API_KEY
    → 聞かれたら貼って Enter（画面には出ない）

**入れる先は2か所ある。** 手元の `.env` と GitHub Secrets。同じコードが
自分のPCとGitHubのサーバーの両方で動き、それぞれ別の場所から読むため。
片方だけ更新すると「手元では効くのにCIだけ効かない」が起きる。

入力は getpass で受けるため、画面にもシェルの履歴にも残らない。
GitHub Secrets へも標準入力で渡すので、プロセス一覧にも出ない。

配信用トークン（SITE_PUSH_TOKEN）は書き込み確認が要るため、
専用の set_push_token.py を使うこと。
"""
import argparse
import getpass
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENVF = ROOT / ".env"

# 設定できるキーと、入れたあとに動く確認
KEYS = {
    "RAKKO_API_KEY": ("ラッコキーワード（KW候補の検索ボリューム）",
                      "ラッコキーワード → マイページ → API → キー発行"
                      "（スタンダードプラン以上）",
                      ["scripts/rakko.py", "--check"]),
    "YOUTUBE_API_KEY": ("YouTube Data API（一次情報の収集）",
                        "https://console.cloud.google.com/apis/credentials", None),
    "CLOUDFLARE_API_TOKEN": ("Cloudflare Pages（サイト配信）",
                             "https://dash.cloudflare.com/profile/api-tokens", None),
    "SLACK_WEBHOOK_URL": ("Slack通知（未設定ならメールに届く）",
                          "https://api.slack.com/apps → Incoming Webhooks", None),
    "RESEND_API_KEY": ("メール送信（問い合わせ・通知）",
                       "https://resend.com/api-keys", None),
}


def write_env(key, val):
    lines = ENVF.read_text(encoding="utf-8-sig").splitlines() if ENVF.exists() else []
    if ENVF.exists():
        bak = ROOT / f".env.backup-{datetime.now():%Y%m%d-%H%M%S}"
        bak.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")
        print("   控え: %s" % bak.name)
    out, done = [], False
    for ln in lines:
        if re.match(r"\s*%s\s*=" % re.escape(key), ln):
            out.append("%s=%s" % (key, val))
            done = True
        else:
            out.append(ln)
    if not done:
        out.append("%s=%s" % (key, val))
    ENVF.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="")
    print("   .env を更新しました")


def write_secret(key, val):
    """標準入力で渡す。--body で渡すとプロセス一覧に値が出る"""
    r = subprocess.run(["gh", "secret", "set", key], input=val, text=True,
                       capture_output=True, encoding="utf-8", errors="replace",
                       timeout=60)
    if r.returncode == 0:
        print("   GitHub Secrets を更新しました")
        return True
    print("   GitHub Secrets を更新できません: %s" % (r.stderr or "").strip()[:160])
    print("   （.env だけは更新済みです。gh auth login を確認してください）")
    return False


def main():
    ap = argparse.ArgumentParser(description="APIキーを .env と GitHub Secrets へ入れる")
    ap.add_argument("key", nargs="?", default="", help="キー名（例: RAKKO_API_KEY）")
    a = ap.parse_args()

    if a.key not in KEYS:
        print("設定できるキー:\n")
        for k, (what, where, _) in KEYS.items():
            print("  %-22s %s" % (k, what))
            print("  %-22s 取得: %s" % ("", where))
        print("\n使い方: python scripts/set_key.py <キー名>")
        return 1

    what, where, verify = KEYS[a.key]
    print("■ %s（%s）" % (a.key, what))
    print("   取得: %s" % where)
    print("\n   キーを貼り付けて Enter を押してください。")
    print("   （入力は画面に表示されません。Ctrl+V を押しても何も出ませんが、")
    print("     貼り付けは効いています。そのまま Enter を押してください）")
    try:
        val = getpass.getpass("   キー: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n中止しました。何も変更していません")
        return 1
    if not val:
        print("何も入力されませんでした。何も変更していません")
        return 1
    if len(val) < 8 or " " in val:
        print("値が短すぎるか、空白が混ざっています（%d文字）。何も変更していません" % len(val))
        return 1

    print("\n■ 2か所へ入れます")
    write_env(a.key, val)
    write_secret(a.key, val)

    if verify:
        print("\n■ 動くかの確認")
        subprocess.run([sys.executable] + verify, cwd=str(ROOT))
    print("\n完了しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
