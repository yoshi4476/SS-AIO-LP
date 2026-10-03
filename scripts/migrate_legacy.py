# -*- coding: utf-8 -*-
"""補助金サイトの旧形式の記事（articles/_legacy/）を、管制塔の形式に直して採点し、管理に乗せる。

旧い自動生成の仕組みで書かれた記事は、カテゴリ（hojo）・狙う語・採点が無く、書き直しや鮮度の更新の
対象外だった（2026-10-03）。採点は書いた工程と別の工程（score_audit.audit_one）が公開ページを読んで付ける。
合格（rubric.judge）なら articles/ へ移し、不合格なら _legacy に残して点数と弱い点だけ記録する。

    python scripts/migrate_legacy.py            # 全部
    python scripts/migrate_legacy.py --dry      # 採点せず、直した頭の情報だけ見る
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEGACY = ROOT / "articles" / "_legacy"
SUBSIDY = ROOT / ".publish-work" / "subsidy"
LOG = ROOT / "data" / "legacy_scores.json"


def split(md):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", md, re.S)
    return (m.group(1), m.group(2)) if m else ("", md)


def field(fm, k):
    m = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
    return m.group(1).strip().strip('"') if m else ""


def convert(p, axes=None):
    fm, body = split(p.read_text(encoding="utf-8"))
    title = field(fm, "title")
    out = [
        "---",
        f"title: {title}",
        f"description: {field(fm, 'description')}",
        f"slug: {p.stem}",
        f"keyword: {re.split(r'[｜|]', title)[0].strip()}",
        "category: hojokin",
        f"date: {field(fm, 'date')}",
        f"modified: {field(fm, 'date')}",
    ]
    if axes:
        out += [f"score: {round(sum(axes.values()) / 3)}",
                "score_breakdown: {" + ", ".join(f"{k}: {v}" for k, v in axes.items()) + "}"]
    return "\n".join(out) + "\n---\n" + body


def main():
    import score_audit as SA
    dry = "--dry" in sys.argv
    log = json.loads(LOG.read_text(encoding="utf-8")) if LOG.is_file() else {}
    for p in sorted(LEGACY.glob("*.md")):
        html = SUBSIDY / "blog" / p.stem / "index.html"
        if dry:
            print(convert(p).split("---")[1])
            continue
        if not html.is_file():
            print(f"× {p.stem}: 公開ページが無い")
            continue
        res, err = SA.audit_one(p.stem, html)
        if not res:
            print(f"× {p.stem}: 採点できず（{err[:80]}）")
            continue
        ok = bool(res.get("ok"))          # audit_one が rubric.judge の結果を含めて返す
        log[p.stem] = {"axes": res["axes"], "pass": ok, "reason": res.get("reason", "")[:600]}
        LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        if ok:
            (ROOT / "articles" / p.name).write_text(convert(p, res["axes"]), encoding="utf-8")
            p.unlink()
        print(f"{'○' if ok else '△'} {p.stem}: {res['axes']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.exit(main())
