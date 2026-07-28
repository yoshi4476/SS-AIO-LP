# -*- coding: utf-8 -*-
"""記事の画像一括生成（Phase 6用オーケストレータ）

1コマンドで、記事フロントマターからアイキャッチ+全図解を生成する:
    python scripts/make_images.py <slug>

図解はフロントマターの `diagrams:` で宣言する（なければアイキャッチのみ生成）:
---
diagrams:
  - name: steps            # 出力ファイル名（site/images/<slug>/steps.png）
    type: flow             # flow（手順2-5） / list（チェックリスト3-6） / vs（比較2カラム）
    title: ◯◯の5つの手順
    items: ["手順A|2行目", "手順B", "手順C"]
    # vs型のみ items は2要素: ["NG側見出し|行1|行2", "OK側見出し|行1|行2"]
---
本文には <figure><img src="/images/<slug>/steps.png" ...> を通常どおり記述する。
"""
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def main():
    slug = sys.argv[1]
    p = ROOT / "articles" / f"{slug}.md"
    if not p.exists():
        raise SystemExit(f"articles/{slug}.md が見つかりません")
    m = re.match(r"^---\s*\n(.*?)\n---", p.read_text(encoding="utf-8-sig"), re.S)
    meta = yaml.safe_load(m.group(1))

    # 1) アイキャッチ（フロントマターのtitle/categoryから自動）
    subprocess.run([PY, str(ROOT / "scripts" / "make_eyecatch.py"), slug], check=True)

    # 2) 図解（diagrams: 宣言があれば）
    for dg in meta.get("diagrams") or []:
        dtype = dg.get("type", "flow")
        cmd = [PY, str(ROOT / "scripts" / "make_diagram.py"), "--type", dtype,
               slug, dg["name"], dg["title"], *[str(x) for x in dg["items"]]]
        subprocess.run(cmd, check=True)

    n = len(meta.get("diagrams") or [])
    print(f"完了: eyecatch + 図解{n}枚（site/images/{slug}/）")


if __name__ == "__main__":
    main()
