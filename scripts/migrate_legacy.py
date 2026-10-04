# -*- coding: utf-8 -*-
"""補助金サイトの旧形式の記事（articles/_legacy/）を、管制塔の形式に直して採点し、管理に乗せる。

旧い自動生成の仕組みで書かれた記事は、カテゴリ（hojo）・狙う語・採点が無く、書き直しや鮮度の更新の
対象外だった（2026-10-03）。採点は書いた工程と別の工程（score_audit.audit_one）が公開ページを読んで付ける。
合格（rubric.judge）なら articles/ へ移し、不合格なら _legacy に残して点数と弱い点だけ記録する。

    python scripts/migrate_legacy.py            # 全部
    python scripts/migrate_legacy.py --dry      # 採点せず、直した頭の情報だけ見る
"""
import json
import os
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


def legacy_keyword(title):
    """題名から狙う語を取る。【2026年最新】などの飾りと、｜・？の後ろ（説明の部分）は外す。
    ｜の無い題では題名まるごとが狙う語になり、食い合いの検査と「題に狙う語が入るか」の検算が崩れた"""
    t = re.sub(r"【[^】]*】", " ", title)
    t = re.split(r"[｜|]", t)[0]
    m = re.match(r"^(.+?[?？])", t)
    t = m.group(1) if m else t
    return re.sub(r"\s+", " ", t).strip(" 　?？\"")[:40]


def convert(p, axes=None):
    fm, body = split(p.read_text(encoding="utf-8"))
    title = field(fm, "title")
    out = [
        "---",
        f"title: {title}",
        f"description: {field(fm, 'description')}",
        f"slug: {p.stem}",
        f"keyword: {legacy_keyword(title)}",
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


def rewrite_parallel(slugs, workers):
    """記事ごとに別の作業場所（git worktree）を作り、書き直しと採点を同時に回す。

    1本の書き直し＋採点は約12分で、ほぼ全部が AI の応答待ち（ビルドは17秒）。検算は
    「その1本以外が変わっていないか」をリポジトリ全体で見るため、同じ作業場所で並べると
    互いの変更を「別の記事まで変わった」と数えて止まる。作業場所を分ければ、検算も採点も
    1本ずつのときと同じものがそのまま通る（精度は変えずに、待ち時間だけを重ねる）"""
    import shutil
    import subprocess
    from concurrent.futures import ThreadPoolExecutor
    work = ROOT / ".publish-work"
    log = json.loads(LOG.read_text(encoding="utf-8"))

    def one(slug):
        w = work / f"wt-{slug}"
        subprocess.run(["git", "worktree", "remove", "--force", str(w)], cwd=ROOT, capture_output=True)
        r = subprocess.run(["git", "worktree", "add", "--detach", str(w), "HEAD"], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        if r.returncode:
            return slug, f"× {slug}: 作業場所を作れません（{r.stderr[-120:]}）"
        try:
            # コミットしていない入力（書き直し途中の控え・採点の台帳）を作業場所へ写す
            for rel in (f"articles/_legacy/{slug}.md", "data/legacy_scores.json", f"data/subsidy_survey/{slug}.json"):
                if (ROOT / rel).is_file():
                    shutil.copy2(ROOT / rel, w / rel)
            # Git で管理していない鍵（Search Console・管制塔）も写す。無いと食い合いの検査（kw_guard）が
            # GSC を読めずに止まり、12本中8本が「食い合う」で戻された（2026-10-04）。作業場所ごと消すので残らない
            for rel in ("indexing-service-account.json", ".env"):
                if (ROOT / rel).is_file():
                    shutil.copy2(ROOT / rel, w / rel)
            r = subprocess.run([sys.executable, "scripts/migrate_legacy.py", "--rewrite", slug], cwd=w,
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=3600)
            got = json.loads((w / "data" / "legacy_scores.json").read_text(encoding="utf-8")).get(slug)
            # 結果だけを本体へ戻す（合格なら articles/ に置き _legacy から外す。不合格なら書き直した控えを残す）
            art, leg = w / "articles" / f"{slug}.md", w / "articles" / "_legacy" / f"{slug}.md"
            if art.is_file():
                shutil.copy2(art, ROOT / "articles" / art.name)
            if leg.is_file():
                shutil.copy2(leg, ROOT / "articles" / "_legacy" / leg.name)
            elif (ROOT / "articles" / "_legacy" / f"{slug}.md").is_file():
                (ROOT / "articles" / "_legacy" / f"{slug}.md").unlink()
            line = (r.stdout.strip().splitlines() or [f"? {slug}: 出力なし {r.stderr[-200:]}"])[-1]
            return slug, (line, got)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(w)], cwd=ROOT, capture_output=True)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for slug, res in ex.map(one, slugs):
            if isinstance(res, str):
                print(res, flush=True)
                continue
            line, got = res
            if got:
                log[slug] = got
                LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
            print(line, flush=True)


def main():
    import score_audit as SA
    if "--rewrite" in sys.argv and "--parallel" in sys.argv:
        i = sys.argv.index("--parallel")
        n = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit() else 4
        slugs = [a for a in sys.argv[1:] if not a.startswith("--") and not a.isdigit()]
        return rewrite_parallel(slugs, n)
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
