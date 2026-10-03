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


MERGE = {"ai-hojokin-hitsuyo-shorui-kojin", "ai-hojokin-kourigyou-katsuyou"}   # 点が低すぎるので統合する


def rewrite_all():
    """不合格だった記事を、採点者の指摘に沿って書き直し（検算つき）、原稿を読ませて採点し直す。
    合格したら点数を書いて articles/ に置く（配信は呼び出し側で）。不合格なら _legacy に戻す"""
    import auto_rewrite as AR
    import score_audit as SA
    import subsidy_survey as SV
    log = json.loads(LOG.read_text(encoding="utf-8"))
    only = [a for a in sys.argv[1:] if not a.startswith("--")]
    for p in sorted(LEGACY.glob("*.md")):
        rec = log.get(p.stem)
        if not rec or rec.get("pass") or p.stem in MERGE or (only and p.stem not in only):
            continue
        dst = ROOT / "articles" / p.name
        dst.write_text(convert(p, rec["axes"]), encoding="utf-8")
        # 補助金サイトに書ける自社の数字は、AIへの聞き取り調査（subsidy_survey）だけ
        extra = SV.claims(p.stem)
        why = rec.get("reason", "")
        # 検算に落ちたら、落ちた理由（どの警告か）を伝えてもう1回だけ直させる
        for attempt in range(2):
            ok, msg = AR.run_one({"kind": "quality", "slug": p.stem, "site": "subsidy", "why": why,
                                  "extra_facts": extra}, True)
            if ok:
                break
            why = f"{rec.get('reason', '')}\n\n前回の書き直しは検算で戻されました。次を必ず避けてください: {msg}"
        if not ok:
            dst.unlink()
            print(f"× {p.stem}: 書き直しが検算で止まりました（{str(msg)[:120]}）", flush=True)
            continue
        res, err = SA.audit_one(p.stem, dst)
        if res and res.get("ok"):
            s = dst.read_text(encoding="utf-8")
            s = re.sub(r"^score:.*$", f"score: {round(sum(res['axes'].values()) / 3)}", s, count=1, flags=re.M)
            s = re.sub(r"^score_breakdown:.*$", "score_breakdown: {" + ", ".join(f"{k}: {v}" for k, v in res["axes"].items()) + "}",
                       s, count=1, flags=re.M)
            dst.write_text(s, encoding="utf-8")
            p.unlink()
            log[p.stem] = {"axes": res["axes"], "pass": True, "rewritten": True}
            print(f"○ {p.stem}: {res['axes']}", flush=True)
        else:
            # 書き直した版を _legacy の控えにして、次の回でさらに直せるようにする
            p.write_text(dst.read_text(encoding="utf-8"), encoding="utf-8")
            dst.unlink()
            if res:
                log[p.stem] = {"axes": res["axes"], "pass": False, "reason": res.get("reason", "")[:600], "rewritten": True}
            print(f"△ {p.stem}: 書き直し後も不合格 {res and res['axes']}", flush=True)
        LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    import score_audit as SA
    if "--rewrite" in sys.argv:
        return rewrite_all()
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
