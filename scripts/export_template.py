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
COPY_FILES = ["requirements.txt", ".gitignore", ".env.example"]

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
