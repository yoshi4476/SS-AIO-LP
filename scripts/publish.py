# -*- coding: utf-8 -*-
"""記事を対象サイトへ配信する（多サイト対応の出口）

使い方:
    python scripts/publish.py --site corporate --slug tenpo-saiyou-teichaku
    python scripts/publish.py --site corporate --slug xxx --push   # 対象リポジトリへpushまで行う

記事Markdownは常に本リポジトリの articles/ に置く（品質ゲート・カニバリ検査を1か所で回すため）。
本スクリプトは、そのMarkdownをサイトごとの形式へ変換して対象リポジトリに書き込む。

サイト種別:
  self-static  … 本リポジトリの静的サイト。build.py が担当するため何もしない
  nextjs-json  … Next.jsサイト。src/content/blog/<slug>.json を書き出す
  external-md  … 別リポジトリの静的サイト。Markdownをそのまま置く

対象リポジトリへの書き込みには SITE_PUSH_TOKEN（repo権限のPAT）が必要。
未設定ならローカルのクローンに書き込むだけで止まる（--push は失敗する）。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import md2html  # noqa: E402
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / ".publish-work"  # 対象リポジトリのクローン置き場（.gitignore対象）


def run(args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    if check and r.returncode != 0:
        raise SystemExit(f"コマンド失敗: {' '.join(args)}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def parse_article(path: Path):
    t = path.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
    if not m:
        raise SystemExit(f"フロントマターがありません: {path}")
    return yaml.safe_load(m.group(1)), m.group(2)


def ensure_clone(cfg, token):
    """対象リポジトリをクローン（既にあれば最新化）して作業パスを返す"""
    WORK.mkdir(exist_ok=True)
    dest = WORK / cfg["id"]
    url = f"https://github.com/{cfg['repo']}.git"
    auth_url = f"https://x-access-token:{token}@github.com/{cfg['repo']}.git" if token else url
    if not (dest / ".git").exists():
        shutil.rmtree(dest, ignore_errors=True)
        run(["git", "clone", "--depth", "1", "--branch", cfg["branch"], auth_url, str(dest)])
    else:
        run(["git", "fetch", "--depth", "1", auth_url, cfg["branch"]], cwd=dest)
        run(["git", "reset", "--hard", "FETCH_HEAD"], cwd=dest)
    return dest


def write_nextjs_json(cfg, dest: Path, meta, body):
    """Next.jsサイト用: 本文HTML込みのJSONを書き出す"""
    html, _ = md2html.convert(body)
    faq = md2html.extract_faq(body)
    out = {
        "slug": meta["slug"],
        "title": meta["title"],
        "description": meta["description"],
        "date": str(meta["date"]),
        "dateModified": str(meta.get("modified") or meta.get("dateModified") or meta["date"]),
        "category": meta["category"],
        "categoryName": sites_mod.category_name(cfg, meta["category"]),
        "readingMinutes": md2html.reading_minutes(html),
        "faq": faq,
        "html": html,
    }
    if meta.get("eyecatch"):
        out["eyecatch"] = meta["eyecatch"]
    target = dest / cfg["content_dir"] / f"{meta['slug']}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written = [target]

    # 画像も対象リポジトリへ複製（本文が /images/... を参照するため）
    img_src = ROOT / "site" / "images" / meta["slug"]
    if cfg.get("images_dir") and img_src.exists():
        img_dest = dest / cfg["images_dir"] / meta["slug"]
        shutil.rmtree(img_dest, ignore_errors=True)
        shutil.copytree(img_src, img_dest)
        written.append(img_dest)
    return written, len(md2html.plain_text(html))


def write_external_md(cfg, dest: Path, meta, body, src: Path):
    """別リポジトリの静的サイト用: Markdownをそのまま置く"""
    target = dest / cfg["content_dir"] / f"{meta['slug']}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return [target], len(md2html.plain_text(md2html.convert(body)[0]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--push", action="store_true", help="対象リポジトリへcommit+pushする")
    args = ap.parse_args()

    cfg = sites_mod.load(args.site)
    src = ROOT / "articles" / f"{args.slug}.md"
    if not src.exists():
        raise SystemExit(f"記事が見つかりません: {src}")
    meta, body = parse_article(src)

    score = meta.get("score") or 0
    if score < 90:
        raise SystemExit(f"公開基準未達のため配信しません: score={score}（90点以上が必要）")
    if meta["category"] not in cfg.get("categories", {}):
        raise SystemExit(f"カテゴリ '{meta['category']}' は {cfg['id']} に定義されていません"
                         f"（候補: {', '.join(cfg.get('categories', {}))}）")

    if cfg["type"] == "self-static":
        print(f"{cfg['id']} は本リポジトリのサイトです。scripts/build.py で公開してください。")
        return

    token = os.environ.get("SITE_PUSH_TOKEN", "").strip()
    dest = ensure_clone(cfg, token)

    if cfg["type"] == "nextjs-json":
        written, chars = write_nextjs_json(cfg, dest, meta, body)
    elif cfg["type"] == "external-md":
        written, chars = write_external_md(cfg, dest, meta, body, src)
    else:
        raise SystemExit(f"未対応のサイト種別: {cfg['type']}")

    print(f"配信先: {cfg['name']}（{cfg['repo']} / {cfg['branch']}）")
    for w in written:
        print(f"  書き込み: {w.relative_to(dest)}")
    print(f"  本文: {chars:,}字 / score {score}")
    print(f"  公開URL（予定）: {sites_mod.article_url(cfg, meta)}")

    if not args.push:
        print("\n※ --push を付けると対象リポジトリへcommit+pushします（Cloudflareが自動デプロイ）")
        return
    if not token:
        raise SystemExit("SITE_PUSH_TOKEN が未設定のためpushできません")

    run(["git", "config", "user.name", "AIO Pipeline Bot"], cwd=dest)
    run(["git", "config", "user.email", "noreply@7senses.co.jp"], cwd=dest)
    run(["git", "add", "-A"], cwd=dest)
    if not run(["git", "status", "--porcelain"], cwd=dest):
        print("変更なし — pushをスキップ")
        return
    run(["git", "commit", "-m",
         f"publish: {meta['title']}（score {score} / {date.today().isoformat()}）"], cwd=dest)
    auth_url = f"https://x-access-token:{token}@github.com/{cfg['repo']}.git"
    run(["git", "push", auth_url, f"HEAD:{cfg['branch']}"], cwd=dest)
    print("push完了。対象サイトのビルドが自動で走ります。")


if __name__ == "__main__":
    main()
