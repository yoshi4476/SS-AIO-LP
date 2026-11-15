# -*- coding: utf-8 -*-
"""ラボの組み立て（build.py）が section に付ける名前は、style.css に定義があるものだけにする
（2026-11-15 運用者「ほかの探し方 これ横長になりすぎてちぎれている」）。業種の入口に足した「ほかの探し方」が
定義の無い名前（wrap）だったため、幅の上限と左右の余白がかからず、画面の端から端まで伸びていた"""
import re
from pathlib import Path

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent


def undefined_section_classes(src: str, css: str) -> set[str]:
    """フッターの直前（ページの一番下）に差し込む section だけを見る。記事の本文の中の section（関連記事など）は
    本文の枠が幅を決めるので対象にしない"""
    names = set()
    for line in src.splitlines():
        if "site-footer" in line:
            for cls in re.findall(r'<section class=\\?"([^"\\{]+)', line):
                names.update(cls.split())
    return {n for n in names if not re.search(rf"\.{re.escape(n)}(?![\w-])", css)}


def test_section_classes_exist_in_css():
    print("\n■ ラボの section の名前が見た目の定義にあるか")
    css = (ROOT / "site" / "css" / "style.css").read_text(encoding="utf-8")
    bad = 't.replace(\'<footer class="site-footer">\', f\'<section class="wrap">{block}</section>\')'
    check("悪い例（定義の無い wrap）を拾う", undefined_section_classes(bad, css), {"wrap"})
    check("良い例（section）は拾わない", undefined_section_classes(bad.replace('"wrap"', '"section"'), css), set())
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("ページの一番下に差し込む section の名前は style.css にある", undefined_section_classes(src, css), set())
