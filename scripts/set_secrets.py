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
    "RAKKO_API_KEY",
    # AI検索の語の調査（ai_kw_research / ai_cite_check）と記事動画の投稿（article_videos）
    "GEMINI_API_KEY", "YOUTUBE_CLIENT_JSON", "YOUTUBE_TOKEN_JSON", "YOUTUBE_TOKENS_JSON",
    # Googleビジネスプロフィール（訪日客向けの地図の整備・口コミの返信案）。
    # GBP_TOKENS_JSON は {"<サイトID>": <gbp-token-<id>.json の中身>} の1つのJSON
    "GBP_CLIENT_JSON", "GBP_TOKENS_JSON",
    # 表示速度の実測（cwv_check）。YOUTUBE_API_KEY のプロジェクトでは PageSpeed API が使えず、週次で測れなかった
    "PAGESPEED_API_KEY",
    # AI検索の引用の実測（ai_cite_check）。鍵のあるAIだけに聞く
    "OPENAI_API_KEY", "PERPLEXITY_API_KEY", "XAI_API_KEY", "CLAUDE_CITE_API_KEY",
    # ワークフローが使うのにここに無かった鍵。.env だけにあり CI で空のまま動いていた（2026-10-03 門で照合）
    "ANTHROPIC_API_KEY", "CODEX_AUTH_JSON", "GA4_PROPERTY_ID", "SPREADSHEET_ID", "GH_SECRET_TOKEN",
    "X_BEARER_TOKEN", "FB_PAGE_ID", "FB_PAGE_TOKEN", "IG_USER_ID", "THREADS_TOKEN", "THREADS_USER_ID",
    "LINKEDIN_TOKEN", "LINKEDIN_REFRESH_TOKEN", "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET",
    "LINKEDIN_ORG_ID", "LINKEDIN_PERSON_ID",
    # Git を使わない配信先（レンタルサーバーの FTP・WordPress）の接続情報。全社分を1つの JSON で持つ
    "FTP_CREDENTIALS_JSON", "WP_CREDENTIALS_JSON",
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

# ── KW候補の検索ボリューム（無くても無料のサジェストだけで動きます）──
# 発行: ラッコキーワード → マイページ → API → キー発行
#   スタンダードプラン（月2,475円〜）以上でのみ発行できます
#   消費の目安: 1社あたり約168クレジット/月（10社で1,680／枠3,000）
RAKKO_API_KEY=

# ── AI検索に引用されているかの実測（月1回・1サイト20語。あるものだけ使う）──
# 発行: https://platform.openai.com/api-keys
OPENAI_API_KEY=
# 発行: https://www.perplexity.ai/settings/api
PERPLEXITY_API_KEY=

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
        # 値は標準入力で渡す。--body で渡すと、実行中はプロセス一覧から誰でも読める
        r = subprocess.run(["gh", "secret", "set", k], input=v,
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
    ap.add_argument("--sync-github", nargs="*", metavar="KEY",
                    help="すでに .env にある値を GitHub Secrets へ写す（KEY を省くと GitHub 用の全部）")
    a = ap.parse_args()

    if a.sync_github is not None:
        # 値は .env にあるのに GitHub 側だけ無い、というときに secrets.local.txt へ書き直させない。
        # 実例: PAGESPEED_API_KEY が .env にあるのに Secrets に無く、週次の速度計測が測れなかった
        env = {}
        for line in (ENVF.read_text(encoding="utf-8") if ENVF.is_file() else "").splitlines():
            m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$", line)
            if m and not line.lstrip().startswith("#"):
                env[m.group(1)] = m.group(2).strip().strip('"').strip("'")
        keys = a.sync_github or sorted(TO_GITHUB)
        vals = {k: env[k] for k in keys if env.get(k)}
        missing = [k for k in keys if not env.get(k)]
        if missing and a.sync_github:
            print(f"   .env に値がありません: {', '.join(missing)}")
        if not vals:
            print(".env に写せる値がありません")
            return 1
        if not gh_ready():
            print("gh にログインしていません。先に `gh auth login` を実行してください")
            return 1
        print(f"■ .env から GitHub Secrets へ写します: {len(vals)}件")
        for k, v in vals.items():
            print(f"   {k:<28}{mask(v)}")
        ok, ng = set_github({k: v for k, v in vals.items() if k in TO_GITHUB})
        print(f"\n   反映 {len(ok)}件" + (f" / 失敗 {len(ng)}件" if ng else ""))
        return 0 if not ng else 1

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
    # 確認（token_check）は配信用トークンしか見ない。他の値の反映失敗も終了コードに出す
    return 0 if r.returncode == 0 and not ng else 1


if __name__ == "__main__":
    sys.exit(main())
