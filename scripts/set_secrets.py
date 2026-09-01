# -*- coding: utf-8 -*-
"""認証情報を1ファイルから .env と GitHub Secrets の両方へ反映する

片方だけ更新すると、手元では通るのにCIで落ちる（またはその逆）という
食い違いが起きる。実際、SITE_PUSH_TOKEN がそれで長く401のままだった。
1か所に書いて両方へ配る。

使い方:
  1. secrets.local.txt に値を書く（雛形は --init で作る）
  2. python scripts/set_secrets.py           # 中身を確認するだけ（書き込まない）
  3. python scripts/set_secrets.py --apply   # .env と GitHub Secrets を更新
  4. python scripts/set_secrets.py --clean   # 書き終わったら控えを消す

値そのものは画面に出さない。長さと先頭数文字だけを出す。
"""
import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "secrets.local.txt"
ENVF = ROOT / ".env"

# GitHub Secrets にも入れる必要があるもの（ワークフローが使う）
TO_GITHUB = {
    "SITE_PUSH_TOKEN", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID",
    "HUB_URL", "HUB_SECRET", "SLACK_WEBHOOK_URL", "RESEND_API_KEY",
    "RESEND_AUDIENCE_ID", "LEAD_TO_EMAIL", "LEAD_FROM_EMAIL",
    "YOUTUBE_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "GCP_SERVICE_ACCOUNT_JSON",
}

TEMPLATE = """# ここに値を書いて `python scripts/set_secrets.py --apply` を実行します。
# 書いた値は .env と GitHub Secrets の両方へ入ります。
# 行頭に # を付けた行と、値が空の行は「変更しない」の意味です。
# 反映が終わったら `python scripts/set_secrets.py --clean` で消してください。

# ── 配信用（コーポレート・補助金サイトへ記事を届けるのに必須）─────────
# 発行: https://github.com/settings/personal-access-tokens/new
#   Repository access → Only select repositories
#     yoshi4476/SS-CorporateHP
#     yoshi4476/seven-HPunyou
#     yoshi4476/SS-AIO-LP
#   Permissions → Repository permissions → Contents: Read and write
#                                          Workflows: Read and write（任意）
SITE_PUSH_TOKEN=

# ── サイト配信（Cloudflare Pages）───────────────────────────────
# 発行: https://dash.cloudflare.com/profile/api-tokens
#   テンプレート「Edit Cloudflare Workers」または Pages:Edit 権限
CLOUDFLARE_API_TOKEN=
# 確認: https://dash.cloudflare.com/ のURLに含まれる32桁
CLOUDFLARE_ACCOUNT_ID=

# ── 管制塔（スプレッドシート）──────────────────────────────────
# GASの「デプロイを管理」で発行される /exec で終わるURL
HUB_URL=
# automation/gas/hub.gs の SHARED_SECRET と同じ文字列
HUB_SECRET=

# ── 問い合わせ・購読メール ────────────────────────────────────
# 発行: https://resend.com/api-keys
RESEND_API_KEY=
# 確認: https://resend.com/audiences
RESEND_AUDIENCE_ID=
LEAD_TO_EMAIL=
LEAD_FROM_EMAIL=

# ── 通知 ────────────────────────────────────────────────
# 発行: https://api.slack.com/apps → Incoming Webhooks
SLACK_WEBHOOK_URL=

# ── 一次情報の収集 ──────────────────────────────────────────
# 発行: https://console.cloud.google.com/apis/credentials
YOUTUBE_API_KEY=
"""


def mask(v):
    if not v:
        return "（空）"
    return f"{len(v)}文字 / 先頭 {v[:7]}…"


def read_local():
    if not LOCAL.is_file():
        return {}
    out = {}
    for line in LOCAL.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:
            out[k.strip()] = v
    return out


def update_env(vals):
    """.env を書き換える。既存の他の値は残す"""
    lines = ENVF.read_text(encoding="utf-8-sig").splitlines() if ENVF.is_file() else []
    if ENVF.is_file():
        bak = ROOT / f".env.backup-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(ENVF, bak)
        print(f"   控えを作りました: {bak.name}")
    seen = set()
    out = []
    for line in lines:
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=", line)
        if m and m.group(1) in vals:
            out.append(f"{m.group(1)}={vals[m.group(1)]}")
            seen.add(m.group(1))
        else:
            out.append(line)
    for k, v in vals.items():
        if k not in seen:
            out.append(f"{k}={v}")
    ENVF.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="")
    return len(vals)


def gh_ready():
    try:
        r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return r.returncode == 0
    except Exception:
        return False


def set_github(vals):
    ok, ng = [], []
    for k, v in vals.items():
        if k not in TO_GITHUB:
            continue
        r = subprocess.run(["gh", "secret", "set", k, "--body", v],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60, cwd=ROOT)
        (ok if r.returncode == 0 else ng).append(k)
        if r.returncode != 0:
            print(f"   × {k}: {(r.stderr or '').strip()[:80]}")
    return ok, ng


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true", help="雛形を作る")
    ap.add_argument("--apply", action="store_true", help=".env と GitHub Secrets を更新")
    ap.add_argument("--clean", action="store_true", help="控えのファイルを消す")
    a = ap.parse_args()

    if a.init:
        if LOCAL.exists():
            print(f"{LOCAL.name} はすでにあります。上書きしません")
            return 0
        LOCAL.write_text(TEMPLATE, encoding="utf-8", newline="")
        print(f"雛形を作りました: {LOCAL.name}")
        print("値を書いてから `python scripts/set_secrets.py --apply` を実行してください")
        return 0

    if a.clean:
        if LOCAL.exists():
            LOCAL.unlink()
            print(f"{LOCAL.name} を削除しました")
        else:
            print("削除するファイルはありません")
        return 0

    vals = read_local()
    if not vals:
        print(f"{LOCAL.name} に値がありません。"
              f"`python scripts/set_secrets.py --init` で雛形を作ってください")
        return 1

    print(f"■ {LOCAL.name} に書かれている値: {len(vals)}件\n")
    for k, v in vals.items():
        mark = "→ .env と GitHub Secrets" if k in TO_GITHUB else "→ .env のみ"
        print(f"   {k:<28}{mask(v):<26}{mark}")

    if not a.apply:
        print("\n確認だけしました。反映するには --apply を付けてください")
        return 0

    print("\n■ .env を更新")
    print(f"   {update_env(vals)}件を書き込みました")

    print("\n■ GitHub Secrets を更新")
    if not gh_ready():
        print("   gh にログインしていません。先に `gh auth login` を実行してください")
        print("   （.env だけは更新済みです）")
        return 1
    ok, ng = set_github(vals)
    print(f"   反映 {len(ok)}件" + (f" / 失敗 {len(ng)}件" if ng else ""))

    print("\n■ 確認")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "token_check.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    print("\n".join("   " + l for l in (r.stdout or "").strip().splitlines()[-6:]))
    print(f"\n終わったら `python scripts/set_secrets.py --clean` で {LOCAL.name} を消してください")
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
