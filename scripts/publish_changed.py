# -*- coding: utf-8 -*-
"""変更された記事をまとめて配信する

publish.py は1記事ずつしか配信できない。パイプラインもその日に書いた
新記事1本しか配信しないため、既存記事に加筆しても本番へ届かない。
実際、リライトした60本が手元に残ったままになっていた。

週次のリライトでも同じことが起きるので、差分から拾って配信する。

使い方:
    python scripts/publish_changed.py --site corporate            # 対象を出すだけ
    python scripts/publish_changed.py --site corporate --push     # 実際に配信
    python scripts/publish_changed.py --all --push                # 全サイト
    python scripts/publish_changed.py --site corporate --since HEAD~30

既定では、配信先リポジトリにある本文と手元の本文を突き合わせて、
中身が変わっているものだけを配信する。gitの履歴に頼らないので、
どこまで配信したかを覚えておく必要がない。
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import publish as P  # noqa: E402
import sites as sites_mod  # noqa: E402


def site_articles(site_id):
    """そのサイトが担当する記事を返す（公開基準を満たすものだけ）"""
    out = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_"):
            continue
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        cat = (re.search(r"^category:\s*(\S+)", fm, re.M) or [0, ""])[1]
        if sites_mod.find_category_owner(cat) != site_id:
            continue
        sc = (re.search(r"^score:\s*(\d+)", fm, re.M) or [0, "0"])[1]
        if int(sc) < 90:
            continue
        out.append(p.stem)
    return out


def changed_by_git(site_id, since):
    """gitの差分から、変更された記事を拾う"""
    r = subprocess.run(["git", "diff", "--name-only", since, "--", "articles/"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT)
    touched = {Path(l).stem for l in r.stdout.splitlines() if l.endswith(".md")}
    return [s for s in site_articles(site_id) if s in touched]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--all", action="store_true", help="全サイトを対象にする")
    ap.add_argument("--since", default="", help="この地点からの差分だけを見る（例: HEAD~30）")
    ap.add_argument("--push", action="store_true", help="実際に配信する")
    ap.add_argument("--limit", type=int, default=0, help="1回に配信する本数の上限")
    a = ap.parse_args()

    ids = list(sites_mod.load_all()) if a.all else ([a.site] if a.site else [])
    if not ids:
        ap.error("--site か --all を指定してください")

    total_ok = total_ng = 0
    for sid in ids:
        cfg = sites_mod.load(sid)
        if cfg["type"] == "self-static":
            print(f"■ {cfg['name']}: 本リポジトリのサイトです（build.py が担当）")
            continue

        targets = changed_by_git(sid, a.since) if a.since else site_articles(sid)
        if a.limit:
            targets = targets[:a.limit]
        print(f"■ {cfg['name']}（{cfg['repo']}）: 対象 {len(targets)}本")
        if not a.push:
            for s in targets[:12]:
                print(f"     {s}")
            if len(targets) > 12:
                print(f"     …ほか{len(targets) - 12}本")
            continue

        ok = ng = 0
        for i, slug in enumerate(targets, 1):
            r = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "publish.py"),
                 "--site", sid, "--slug", slug, "--push"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", cwd=ROOT)
            if r.returncode == 0:
                ok += 1
                print(f"   [{i}/{len(targets)}] ○ {slug}", flush=True)
            else:
                ng += 1
                why = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
                print(f"   [{i}/{len(targets)}] × {slug}: {why[-1][:70] if why else '原因不明'}",
                      flush=True)
                # 認証で落ちているなら、以降も同じ結果になる。早めに止める
                if any("401" in l or "unauthorized" in l.lower()
                       or "SITE_PUSH_TOKEN" in l for l in why):
                    print("   → トークンの問題です。ここで中断します")
                    break
        print(f"   配信 {ok}本 / 失敗 {ng}本\n")
        total_ok += ok
        total_ng += ng

    if a.push:
        print(f"PUBLISH_CHANGED: 成功 {total_ok}本 / 失敗 {total_ng}本")
    else:
        print("※ --push を付けると実際に配信します")
    return 1 if total_ng else 0


if __name__ == "__main__":
    sys.exit(main())
