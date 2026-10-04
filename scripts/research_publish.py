# -*- coding: utf-8 -*-
"""「AIに聞いた調査」のページをコーポレート（Next.js）へ届ける。

補助金サイトは pages.py、AI集客ラボは build.py が自分で作る。コーポレートは別リポジトリの Next.js なので、
中身（JSON）と表（CSV）と、それを描くページ（templates/corporate_research_page.tsx）を配信先に置いて push する。

    python scripts/research_publish.py --site corporate          # 何を置くかを見る
    python scripts/research_publish.py --site corporate --push   # 置いて push する（先方のビルドが動く）
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "subsidy"))
SITEMAP_LINE = ('    { url: `${site.url}/research/ai-answers`, lastModified: now, changeFrequency: "monthly", priority: 0.6 },\n')


def main():
    import importlib.util
    import publish
    import sites as S
    # scripts/research.py（Phase 2 の収集）と同じ名前。publish が先に読むと取り違えるので、場所を指定して読む
    spec = importlib.util.spec_from_file_location("subsidy_research", ROOT / "scripts" / "subsidy" / "research.py")
    RS = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(RS)
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="corporate")
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()
    cfg = S.load(a.site)
    if cfg["type"] != "nextjs-json":
        raise SystemExit(f"{a.site} は {cfg['type']}。この道具は Next.js のサイトだけを扱います")
    d = RS.data(a.site, f"https://{cfg['domain']}")
    if not d:
        print("RESEARCH_PUBLISH=skip（調査の材料が足りないので、ページを作りません）")
        return 0
    dest = publish.ensure_clone(cfg, publish._push_token())
    payload = {k: d[k] for k in ("title", "description", "h1", "lead", "period", "engines", "rows",
                                 "split", "answers", "public_pct", "readout_html")}
    payload["dataset"] = RS.dataset_ld(d)
    payload["dataset"]["distribution"]["contentUrl"] = f"https://{cfg['domain']}/research/ai-answers/data.csv"
    files = {
        dest / "src" / "content" / "research" / "ai-answers.json": json.dumps(payload, ensure_ascii=False, indent=1),
        dest / "public" / "research" / "ai-answers" / "data.csv": RS.csv_text(d),
    }
    page = dest / "src" / "app" / "research" / "ai-answers" / "page.tsx"
    for p, text in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    page.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "templates" / "corporate_research_page.tsx", page)
    sm = dest / "src" / "app" / "sitemap.ts"
    s = sm.read_text(encoding="utf-8")
    if "/research/ai-answers" not in s:
        anchor = '    { url: `${site.url}/blog/theme`,'
        if anchor not in s:
            raise SystemExit("sitemap.ts の書式が変わっています（/blog/theme の行が見つかりません）")
        sm.write_text(s.replace(anchor, SITEMAP_LINE + anchor, 1), encoding="utf-8", newline="\n")
    print(f"置きました: {len(d['rows'])}問・{'・'.join(d['engines'])}（{d['period']}）")
    if not a.push:
        print("※ --push で配信先へ commit + push します")
        return 0
    publish.run(["git", "add", "-A"], cwd=dest)
    if not publish.run(["git", "status", "--porcelain"], cwd=dest):
        print("変更なし")
        return 0
    publish.run(["git", "-c", "user.name=AIO Pipeline Bot", "-c", "user.email=noreply@7senses.co.jp",
                 "commit", "-q", "-m", f"AIへの聞き取り調査のページを更新（{len(d['rows'])}問・{d['period']}）"], cwd=dest)
    token = publish._push_token()
    ok = publish.try_run(["git", "push", f"https://x-access-token@github.com/{cfg['repo']}.git", f"HEAD:{cfg['branch']}"],
                         cwd=dest, env=publish.git_auth(token))
    print("push完了（先方のビルドが動きます）" if ok else "push できませんでした（python scripts/token_check.py を確認）")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
