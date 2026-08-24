# -*- coding: utf-8 -*-
"""クライアントに渡せる形でシステム一式を書き出す

このリポジトリには自社の記事・ドメイン・合言葉が混ざっている。
そのまま渡すと事故になるため、仕組みだけを取り出し、
自社固有の値はプレースホルダに置き換える。

出力先には「一度も自社の値が入らない」ことを、書き出したあとに検査する。

使い方:
    python scripts/export_template.py <出力先フォルダ>
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# そのまま持っていくもの（仕組みの本体）
COPY_DIRS = ["scripts", "templates", "automation/gas", ".github/workflows"]
# この道具自身は渡さない。検査用に自社の値を文字列として持っているため。
SKIP_FILES = {"export_template.py"}
COPY_FILES = [
    "requirements.txt", ".gitignore",
    # AIクローラーの一覧。robots.txt との整合を見るのに使う。
    # 自社の値を含まない定義データで、無いと aio_check.py が動かない。
    "automation/ai-crawlers.txt",
]

# 実行時に書き込む場所。空でも作っておく。
# 無いまま走ると、記事を1本書いたあとの保存で落ちる。
KEEP_DIRS = ["articles", "reports", "data/ranks", "data/ai_citations",
             "data/youtube_transcripts", "site/images"]

# .env.example は写さずにここから作る。自社のものは使わない項目が残っていて、
# 手順書に出てくる HUB_URL などが載っていないため、渡す先で埋めようがない。
ENV_TEMPLATE = """\
# 認証情報の雛形。これを .env にコピーして埋める。
# .env は git に入らない（.gitignore 済み）。
#
# GitHub Actions で動かす場合、同じ値をリポジトリの Secrets にも登録する。
# ローカルの .env だけ埋めても、定期実行は動かない。

# ── 管制塔 ───────────────────────────────────────────────
# scripts/bootstrap.py が作り、ここへ自動で書き込む。手で埋めなくてよい。
HUB_URL=
HUB_SECRET=
GAS_SCRIPT_ID_HUB=

# ── 記事の生成 ───────────────────────────────────────────
# どちらか一方でよい。OAuth トークンは claude setup-token で発行する。
ANTHROPIC_API_KEY=
CLAUDE_CODE_OAUTH_TOKEN=

# ── 公開先 ───────────────────────────────────────────────
# GitHub の Fine-grained token（Contents: Read and write）。
# 切れると記事が公開されない。scripts/token_check.py で確認できる。
SITE_PUSH_TOKEN=
SITE_URL=https://example.com

# Cloudflare Pages に置く場合のみ
CLOUDFLARE_ACCOUNT_ID=
CLOUDFLARE_API_TOKEN=

# ── 計測 ─────────────────────────────────────────────────
# GA4 → 管理 → プロパティ設定 に出る数字
GA4_PROPERTY_ID=
# サービスアカウントの鍵。GA4に「閲覧者」、Search Consoleに「オーナー」で追加する。
# オーナーでないとインデックス通知が使えず、検索に載るまで数週間延びる。
INDEXING_SERVICE_ACCOUNT_PATH=./indexing-service-account.json

# ── キーワードの発掘 ─────────────────────────────────────
# 無くても Google/YouTube サジェストで動く。あると検索ボリューム順に採れる。
YOUTUBE_API_KEY=
RAKKO_API_KEY=

# ── 問い合わせの通知 ─────────────────────────────────────
RESEND_API_KEY=
LEAD_FROM_EMAIL=
LEAD_TO_EMAIL=
NOTIFY_TO_EMAIL=
RESEND_AUDIENCE_ID=

# ── 任意 ─────────────────────────────────────────────────
# Bing/Copilot への即時通知。キーファイルをサイトルートに置く
INDEXNOW_KEY=
SLACK_WEBHOOK_URL=
# Actions から別のリポジトリへ push する場合のみ
GH_SECRET_TOKEN=

# ── SNS自動投稿（任意。未設定でも記事の公開は止まらない）──
X_API_KEY=
X_API_SECRET=
X_ACCESS_TOKEN=
X_ACCESS_SECRET=
FB_PAGE_ID=
FB_PAGE_TOKEN=
FB_APP_ID=
FB_APP_SECRET=
FB_USER_TOKEN=
IG_USER_ID=
THREADS_TOKEN=
THREADS_USER_ID=
LINKEDIN_TOKEN=
LINKEDIN_ORG_ID=
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_REFRESH_TOKEN=
"""

# サイトの骨格。記事と画像は持っていかない（クライアントごとに作る）
SITE_KEEP = ["css", "js", "robots.txt"]

# 置き換える値。左が自社の値、右が渡す先で埋めてもらう印
REPLACE = [
    ("ai.7senses.co.jp", "{{MEDIA_DOMAIN}}"),
    ("corp.7senses.co.jp", "{{CORP_DOMAIN}}"),
    ("lp.7senses.co.jp", "{{LP_DOMAIN}}"),
    ("www.7senses.co.jp", "{{MAIN_DOMAIN}}"),
    ("7senses.co.jp", "{{DOMAIN}}"),
    ("セブンセンシズ株式会社", "{{COMPANY_NAME}}"),
    ("セブンセンシズ", "{{COMPANY_SHORT}}"),
    ("SEVEN SENSES", "{{COMPANY_EN}}"),
    ("3120001227825", "{{CORPORATE_NUMBER}}"),
    ("原口 優", "{{REPRESENTATIVE}}"),
    ("原口優", "{{REPRESENTATIVE}}"),
    ("G-ran", "{{OWN_SERVICE}}"),
    ("info.ai@7senses.co.jp", "{{NOTIFY_EMAIL}}"),
    ("06-4305-7547", "{{TEL}}"),
    ("06-4305-7548", "{{FAX}}"),
    ("〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902", "{{ADDRESS}}"),
    ("大阪市東成区神路1丁目7-4 コンフォートビル901・902", "{{ADDRESS_SHORT}}"),
    ("大阪市東成区", "{{CITY}}"),
    ("yoshi4476/SS-AIO-LP", "{{HUB_REPO}}"),
    ("yoshi4476/SS-CorporateHP", "{{SITE_REPO_1}}"),
    ("yoshi4476/seven-HPunyou", "{{SITE_REPO_2}}"),
    ("yoshi4476", "{{GITHUB_OWNER}}"),
    ("ss-aio-lp", "{{PAGES_PROJECT}}"),
    ("aio-report@ss-aio-media.iam.gserviceaccount.com", "{{SERVICE_ACCOUNT}}"),
    ("ss-aio-media", "{{GCP_PROJECT}}"),
    # 指名検索を除外するための表記ゆれ。ここも自社名なので置き換える
    ("セブンセンシス", "{{COMPANY_KANA}}"),
    ("sevensenses", "{{COMPANY_SLUG}}"),
    ("7senses", "{{COMPANY_SLUG}}"),
    # 通信するときの名乗り（User-Agent）。秘密ではないが、渡した先の
    # アクセスログに当社の内部の呼び名が出るため、一般名に替える。
    # ss-aio-lp / ss-aio-media を先に処理してから、残りをまとめて替える
    ("ss-aio-pipeline", "media-pipeline"),
    ("ss-aio", "media-pipeline"),
]

# 合言葉やIDは、値そのものを渡してはいけない。空にして埋めてもらう。
# 検査だけだと「見つけたが直せない」ため、置換の段で確実に消す。
Q = chr(34)          # ダブルクォート。正規表現に直接書くと囲み文字とぶつかる
SECRET_LINES = [
    (r"(?m)^(const SHARED_SECRET\s*=\s*)'[^']*'", r"\1'{{SHARED_SECRET}}'"),
    (r"(?m)^(const BOOK_ID\s*=\s*)'[^']*'", r"\1''"),
    (r"(?m)^(const MIGRATE_TO\s*=\s*)'[^']*'", r"\1''"),
    (r"(?m)^(HUB_SHEET\s*=\s*)" + Q + '[^' + Q + ']*' + Q,
     r"\1" + Q + Q),
    (r"(?m)^(SRC|DST)(\s*=\s*)" + Q + '[^' + Q + ']*' + Q,
     r"\1\2" + Q + Q),
]

# 見つかったら書き出しを止めるもの。渡してはいけない値
FORBIDDEN = [
    (r"vPwJAYW\w*", "GASの合言葉"),
    (r"AKfycb[\w-]{20,}", "GASのデプロイURL"),
    (r"ghp_\w{20,}", "GitHubトークン"),
    (r"AIza[\w-]{30,}", "GoogleのAPIキー"),
    (r"re_\w{20,}", "Resendのキー"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY", "秘密鍵"),
    (r"\b1[A-Za-z0-9_-]{40,}\b", "スプレッドシート/スクリプトID"),
    # 置換の網から漏れた自社の名前。値そのものより気づきにくく、
    # 「検査は通ったのに社名が入ったまま渡した」が起きるため最後の砦にする
    (r"7senses|セブンセンシ[スズ]|ss-aio|3120001227825|aio-report@", "自社の名前"),
]

TEXT_EXT = {".py", ".gs", ".yml", ".yaml", ".json", ".md", ".txt", ".html",
            ".css", ".js", ".example"}


def scrub(text):
    for a, b in REPLACE:
        text = text.replace(a, b)
    for pat, rep in SECRET_LINES:
        text = re.sub(pat, rep, text)
    return text


def copy_file(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in TEXT_EXT:
        try:
            t = src.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            shutil.copy2(src, dst)
            return
        dst.write_text(scrub(t), encoding="utf-8", newline="")
    else:
        shutil.copy2(src, dst)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("使い方: python scripts/export_template.py <出力先>")
    out = Path(sys.argv[1])
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    n = 0
    for d in COPY_DIRS:
        src = ROOT / d
        if not src.is_dir():
            continue
        for f in src.rglob("*"):
            if not f.is_file() or "__pycache__" in f.parts:
                continue
            if f.name in SKIP_FILES:
                continue
            copy_file(f, out / d / f.relative_to(src))
            n += 1
    for f in COPY_FILES:
        if (ROOT / f).is_file():
            copy_file(ROOT / f, out / f)
            n += 1
    (out / ".env.example").write_text(ENV_TEMPLATE, encoding="utf-8")
    n += 1
    for d in KEEP_DIRS:
        (out / d).mkdir(parents=True, exist_ok=True)
        (out / d / ".gitkeep").write_text("", encoding="utf-8")
        n += 1
    # 手順書。書き出し先は毎回作り直すので、原本はリポジトリ側に置いてある
    readme = ROOT / "docs" / "client-readme.md"
    if readme.is_file():
        copy_file(readme, out / "README.md")
        n += 1

    # サイトの骨格だけ。記事と画像はクライアントごとに作る
    for k in SITE_KEEP:
        src = ROOT / "site" / k
        if src.is_dir():
            for f in src.rglob("*"):
                if f.is_file():
                    copy_file(f, out / "site" / k / f.relative_to(src))
                    n += 1
        elif src.is_file():
            copy_file(src, out / "site" / k)
            n += 1

    # 設定はサンプルを1つだけ。自社の3サイトぶんは持っていかない
    tmpl = ROOT / "sites" / "ai-lab.json"
    if tmpl.is_file():
        cfg = json.loads(tmpl.read_text(encoding="utf-8-sig"))
        cfg = json.loads(scrub(json.dumps(cfg, ensure_ascii=False)))
        cfg["id"] = "sample"
        cfg["name"] = "{{MEDIA_NAME}}"
        (out / "sites").mkdir(exist_ok=True)
        (out / "sites" / "sample.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        n += 1

    # 書き出したものに、渡してはいけない値が残っていないか検査する
    hits = []
    for f in out.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in TEXT_EXT:
            continue
        try:
            t = f.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        for pat, label in FORBIDDEN:
            for m in re.finditer(pat, t):
                hits.append((f.relative_to(out).as_posix(), label, m.group(0)[:24]))
    left = []
    for f in out.rglob("*"):
        if not f.is_file() or f.suffix.lower() not in TEXT_EXT:
            continue
        try:
            t = f.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        for a, _ in REPLACE:
            if a in t:
                left.append((f.relative_to(out).as_posix(), a))

    print(f"  書き出し: {n}ファイル → {out}")
    if hits:
        print(f"\n  ★ 渡してはいけない値が {len(hits)}件 残っています")
        for p, label, s in hits[:12]:
            print(f"      {p}  [{label}] {s}…")
    if left:
        print(f"\n  ! 置き換え漏れ {len(left)}件")
        for p, a in left[:10]:
            print(f"      {p}  「{a}」")
    if not hits and not left:
        print("  検査: 自社固有の値は残っていません")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
