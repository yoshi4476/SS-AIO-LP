# -*- coding: utf-8 -*-
"""自動更新システムを別サイトへ移行する（サイト固有値の一括置換 + 記事の初期化）

使い方:
    1. site.config.json をコピーして新サイト用の設定を書く（例: new-site.json）
    2. python scripts/init_site.py new-site.json            # 差分を確認するだけ（安全）
    3. python scripts/init_site.py new-site.json --apply    # 実際に書き換える
       python scripts/init_site.py new-site.json --apply --clear-content
                                                            # 記事・画像も消して完全に新規状態にする

前提: このリポジトリを新サイト用に複製（GitHubで Use this template / clone）した上で実行すること。
      元サイトのリポジトリで --apply すると元サイトが壊れるため、必ず複製先で実行する。
"""
import json
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT = ROOT / "site.config.json"

# 置換対象から外すもの（生成物・履歴・バイナリ）
SKIP_DIRS = {".git", "site", "reports", "node_modules", "__pycache__", ".wrangler"}
SKIP_SUFFIX = {".png", ".jpg", ".jpeg", ".webp", ".ico", ".pdf", ".woff", ".woff2"}
# 認証ファイルは新サイト用に作り直すもの。文字列置換で壊さないよう対象外にする
SKIP_FILES = {"indexing-service-account.json", "credentials.json", "sheets-token.json"}
# site/ 配下でも中身がテキスト設定のものは置換する（生成HTMLはビルドで作り直されるため対象外）
SITE_TEXT_FILES = {"site/robots.txt", "site/llms.txt"}


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def _org_short(name):
    """「セブンセンシズ株式会社」→「セブンセンシズ」。法人格を外した呼称を得る"""
    return re.sub(r"(株式会社|有限会社|合同会社|Inc\.?|Co\.,? ?Ltd\.?)", "", str(name or "")).strip()


def _host(url):
    return re.sub(r"^https?://|/$", "", str(url or ""))


def build_map(old, new):
    """置換ペアを作る。長い文字列から順に置換して部分一致の誤爆を防ぐ"""
    pairs = []

    def add(a, b):
        if a and b and a != b:
            pairs.append((str(a), str(b)))

    # ドメインはURL形式とホスト単体の両方
    add(f"https://{old['domain']}", f"https://{new['domain']}")
    add(old["domain"], new["domain"])
    for k in ["site_tagline", "address", "from_email", "notify_email", "corporate_url",
              "author_role", "author_name", "org_name", "site_name", "brand_en",
              "tel", "cf_project", "github_repo", "ga4_measurement_id"]:
        add(old.get(k), new.get(k))
    # 法人格を除いた呼称（「セブンセンシズは〜」のような文中表記を取りこぼさない）
    add(_org_short(old.get("org_name")), _org_short(new.get("org_name")))
    # コーポレートサイトのホスト名（www付き・裸ドメインの両方）
    add(_host(old.get("corporate_url")), _host(new.get("corporate_url")))
    add(re.sub(r"^www\.", "", _host(old.get("corporate_url"))),
        re.sub(r"^www\.", "", _host(new.get("corporate_url"))))
    # 同じ文字列が複数ルールで重複しないよう除去し、長い順に適用する
    seen, uniq = set(), []
    for a, b in pairs:
        if a not in seen:
            seen.add(a)
            uniq.append((a, b))
    uniq.sort(key=lambda p: -len(p[0]))
    return uniq


def target_files():
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.suffix.lower() in SKIP_SUFFIX:
            continue
        rel = p.relative_to(ROOT).as_posix()
        if p.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts[:-1]):
            if rel not in SITE_TEXT_FILES:
                continue
        if rel.startswith("site/") and rel not in SITE_TEXT_FILES:
            continue
        out.append(p)
    return out


def clear_content(old):
    """記事・生成HTML・画像・レポートを削除して新規サイトの状態にする"""
    removed = []
    for p in (ROOT / "articles").glob("*.md"):
        p.unlink()
        removed.append(p.relative_to(ROOT).as_posix())
    for slug in old.get("categories", {}):
        d = ROOT / "site" / slug
        for sub in ([x for x in d.iterdir() if x.is_dir()] if d.exists() else []):
            shutil.rmtree(sub, ignore_errors=True)
            removed.append(sub.relative_to(ROOT).as_posix())
    for d in [ROOT / "reports", ROOT / "data"]:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.relative_to(ROOT).as_posix())
    imgs = ROOT / "site" / "images"
    for sub in (imgs.iterdir() if imgs.exists() else []):
        if sub.is_dir() and sub.name != "company":
            shutil.rmtree(sub, ignore_errors=True)
            removed.append(sub.relative_to(ROOT).as_posix())
    kpi = ROOT / "kpi_feedback.md"
    if kpi.exists():
        kpi.write_text("# KPIフィードバック\n\n（初回のパイプライン実行後に自動生成されます）\n",
                       encoding="utf-8")
        removed.append("kpi_feedback.md（初期化）")
    return removed


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    apply_ = "--apply" in sys.argv
    if not args:
        raise SystemExit("使い方: python scripts/init_site.py <新サイトの設定.json> [--apply] [--clear-content]")

    old, new = load(CURRENT), load(args[0])
    missing = [k for k in ["domain", "site_name", "org_name", "cf_project"] if not new.get(k)]
    if missing:
        raise SystemExit(f"設定に必須項目がありません: {missing}")

    pairs = build_map(old, new)
    print(f"■ 置換ルール {len(pairs)}件")
    for a, b in pairs:
        print(f"   {a}  →  {b}")

    changed, total = [], 0
    for p in target_files():
        try:
            t = p.read_text(encoding="utf-8-sig")
        except (UnicodeDecodeError, OSError):
            continue
        n = 0
        for a, b in pairs:
            t, c = re.subn(re.escape(a), b.replace("\\", "\\\\"), t)
            n += c
        if n:
            changed.append((p.relative_to(ROOT).as_posix(), n))
            total += n
            if apply_:
                p.write_text(t, encoding="utf-8", newline="")

    print(f"\n■ 対象 {len(changed)}ファイル / 計{total}箇所")
    for f, n in sorted(changed, key=lambda x: -x[1]):
        print(f"   {n:4d}  {f}")

    if apply_ and "--clear-content" in sys.argv:
        print("\n■ コンテンツ初期化")
        for r in clear_content(old):
            print(f"   削除: {r}")

    if apply_:
        print("\n■ IndexNowキーの再発行（サイトごとに固有の値が必要）")
        for f in (ROOT / "site").glob("*.txt"):
            if re.fullmatch(r"[0-9a-f]{16,64}", f.stem):
                f.unlink()
                print(f"   旧キーを削除: site/{f.name}")
        key = secrets.token_hex(16)
        (ROOT / "site" / f"{key}.txt").write_text(key, encoding="utf-8")
        print(f"   新キーを設置: site/{key}.txt")

        (ROOT / "site.config.json").write_text(
            json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("\n置換を適用し site.config.json を更新しました。")
        print("次にやること: docs/migration-guide.md の『手作業が必要な設定』を上から実施してください。")
        try:
            out = subprocess.run([sys.executable, str(ROOT / "scripts" / "build.py")],
                                 capture_output=True, text=True, encoding="utf-8", timeout=300)
            print("\n■ ビルド確認\n" + (out.stdout or "")[-800:])
        except Exception as e:
            print(f"ビルド確認をスキップ: {e}")
    else:
        print("\n※ 確認モードです。実際に書き換えるには --apply を付けて再実行してください。")


if __name__ == "__main__":
    main()
