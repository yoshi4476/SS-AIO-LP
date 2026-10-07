# -*- coding: utf-8 -*-
"""記事の画像一括生成（Phase 6用オーケストレータ）

1コマンドで、記事フロントマターからアイキャッチ+全図解を生成する:
    python scripts/make_images.py <slug>
全記事の図解だけを描き直す（解像度・見た目を変えたとき。アイキャッチは描かない）:
    python scripts/make_images.py --all [--site <id>]

図解はフロントマターの `diagrams:` で宣言する（なければアイキャッチのみ生成）。
型と書き方は scripts/make_diagram.py の冒頭（flow・steps・list・vs・matrix・cycle・funnel・bars・pyramid・tree）:
---
diagrams:
  - name: steps            # 出力ファイル名（site/images/<slug>/steps.png）
    type: flow             # 見出しの中身に合う型。同じ記事で同じ型を重ねない
    title: ◯◯の5つの手順
    items: ["手順A|2行目", "手順B", "手順C"]
---
本文には <figure><img src="/images/<slug>/steps.png" ...> を通常どおり記述する。
宣言の誤り（項目数・本文に無い数字・枠に収まらない文字）がある図は描かずに止め、理由を出す。
1枚が止まっても残りの図は描く（終了コードは1）。
"""
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
sys.path.insert(0, str(ROOT / "scripts"))


def read(path):
    """(フロントマター, 本文)。読めなければ (None, None)"""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", path.read_text(encoding="utf-8-sig"), re.S)
    if not m:
        return None, None
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError:
        return None, None


def draw_diagrams(slug, meta, body):
    """記事の宣言の図を全部描く。止まった図の [理由] を返す"""
    import make_diagram as MD
    failed = []
    for dg in meta.get("diagrams") or []:
        try:
            MD.render(slug, dg, body=body)
        except SystemExit as e:
            name = dg.get("name", "?") if isinstance(dg, dict) else "?"
            failed.append(f"{name}: {e}")
    return failed


def redraw_all(site=None):
    """全記事の図解だけを描き直す（アイキャッチは触らない）"""
    import make_diagram as MD
    import sites as S
    MD.QUIET = True
    n = arts = 0
    bad = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        meta, body = read(p)
        if not meta or not meta.get("diagrams"):
            continue
        if site and S.find_category_owner(meta.get("category", "")) != site:
            continue
        arts += 1
        n += len(meta["diagrams"])
        bad += [f"{p.stem} / {x}" for x in draw_diagrams(p.stem, meta, body)]
    print(f"描き直し: {arts}本の記事・図{n - len(bad)}/{n}枚（site/images/）")
    for b in bad:
        print(f"  × {b}")
    return 1 if bad else 0


def main():
    args = sys.argv[1:]
    if args[:1] == ["--all"]:
        site = args[args.index("--site") + 1] if "--site" in args else None
        return redraw_all(site)
    slug = args[0]
    p = ROOT / "articles" / f"{slug}.md"
    if not p.exists():
        raise SystemExit(f"articles/{slug}.md が見つかりません")
    meta, body = read(p)
    if meta is None:
        raise SystemExit(f"articles/{slug}.md にフロントマターがありません")

    # 1) アイキャッチ（フロントマターのtitle/categoryから自動）
    subprocess.run([PY, str(ROOT / "scripts" / "make_eyecatch.py"), slug], check=True)

    # 2) 図解（diagrams: 宣言があれば）。同じプロセスで描く（1枚ごとにフォントを読み直さない）
    failed = draw_diagrams(slug, meta, body)
    n = len(meta.get("diagrams") or [])
    for f in failed:
        print(f"  × 図を描けませんでした: {f}")
    print(f"完了: eyecatch + 図解{n - len(failed)}/{n}枚（site/images/{slug}/）")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
