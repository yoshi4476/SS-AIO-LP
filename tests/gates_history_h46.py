# -*- coding: utf-8 -*-
"""Dataset の構造化データには license を必ず付ける（2026-10-07 Search Console が corp の /research/ai-answers で
「項目 license がありません」と知らせた）。調査ページの license は引用の条件の枠（#cite）を指し、条件を広げない。
"""
import json
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _datasets(node):
    if isinstance(node, dict):
        if node.get("@type") == "Dataset":
            yield node
        for v in node.values():
            yield from _datasets(v)
    elif isinstance(node, list):
        for v in node:
            yield from _datasets(v)


def test_dataset_has_license():
    import research_cite as RC
    import importlib.util
    # 名前が research の別のモジュールと取り違えないよう、build.py と同じくファイルから読む
    spec = importlib.util.spec_from_file_location("subsidy_research_h46", ROOT / "scripts" / "subsidy" / "research.py")
    RS = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(RS)
    url = "https://ai.7senses.co.jp/research/dental-ai-sources/"
    check("Dataset: 調査ページの license は引用の条件の枠を指す", RC.license_url(url), url + "#cite")
    d = {"title": "t", "description": "d", "domain": "https://corp.7senses.co.jp", "url": "/research/ai-answers",
         "period": "2026-10-04"}
    check("Dataset: 3サイト共通の調査（コーポレートの JSON も同じ関数）に license",
          RS.dataset_ld(d).get("license"), "https://corp.7senses.co.jp/research/ai-answers#cite")
    missing, seen = [], 0
    for p in (ROOT / "site").rglob("*.html"):
        t = p.read_text(encoding="utf-8", errors="ignore")
        if '"Dataset"' not in t:
            continue
        for block in LD.findall(t):
            try:
                node = json.loads(block)
            except ValueError:
                continue
            for ds in _datasets(node):
                seen += 1
                if not ds.get("license"):
                    missing.append(str(p.relative_to(ROOT)))
    check("Dataset: 公開しているページの Dataset はすべて license を持つ", missing, [])
    check("Dataset: 検査した Dataset が1つ以上ある（検出器が空振りしていない）", seen > 0, True)
