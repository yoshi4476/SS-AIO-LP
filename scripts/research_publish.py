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


LAB = "https://ai.7senses.co.jp"
AIO_PAGE_IMPORT = 'import AioResearchData from "@/components/AioResearchData";\n'
AIO_PAGE_SLOT = '      {service.slug === "aio" && <AioDetail />}\n'


def place_aio_data(dest):
    """AIO運用代行のページ（/services/aio）に、AI集客ラボの業種別調査（AIは何を出典に答えるか）の表を置く。
    数字は industry_ai_sources.headline（ラボの調査ページと同じ集計）だけ。手で書き写さないので、
    3か月ごとの調査のたびに同じ数字に揃う"""
    import industry_ai_sources as IAS
    rows = []
    for p in sorted((ROOT / "data" / "research").glob("*-summary.json")):
        try:
            h = IAS.headline(p.name[:-len("-summary.json")])
        except Exception:
            continue
        if h and h.get("questions"):
            rows.append({"name": h["name"], "questions": int(h["questions"]), "lp": float(h["lp"]),
                         "lc": float(h["lc"]), "oa": float(h["oa"]), "url": h["url"], "date": h["date"]})
    if len(rows) < 5:
        return 0
    rows.sort(key=lambda r: (-r["questions"], r["name"]))
    dates = sorted(r.pop("date") for r in rows)
    payload = {"n_industries": len(rows), "total_questions": sum(r["questions"] for r in rows),
               "period": f"{dates[0][:7].replace('-', '年', 1)}月" if dates[0][:7] == dates[-1][:7]
               else f"{dates[0]}〜{dates[-1]}",
               "index_url": f"{LAB}/research/", "ranking_url": f"{LAB}/research/ranking/", "rows": rows}
    (dest / "src" / "content" / "research").mkdir(parents=True, exist_ok=True)
    (dest / "src" / "content" / "research" / "aio-industries.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    shutil.copy2(ROOT / "templates" / "corporate_aio_data.tsx", dest / "src" / "components" / "AioResearchData.tsx")
    sp = dest / "src" / "app" / "services" / "[slug]" / "page.tsx"
    s = sp.read_text(encoding="utf-8")
    if "<AioResearchData />" not in s:
        if AIO_PAGE_SLOT not in s or 'import AioDetail from "@/components/AioDetail";\n' not in s:
            raise SystemExit("services/[slug]/page.tsx の書式が変わっています（AioDetail の行が見つかりません）")
        s = s.replace('import AioDetail from "@/components/AioDetail";\n',
                      'import AioDetail from "@/components/AioDetail";\n' + AIO_PAGE_IMPORT, 1)
        s = s.replace(AIO_PAGE_SLOT, AIO_PAGE_SLOT + '      {service.slug === "aio" && <AioResearchData />}\n', 1)
        sp.write_text(s, encoding="utf-8", newline="\n")
    return len(rows)


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
    aio = place_aio_data(dest)
    print(f"置きました: {len(d['rows'])}問・{'・'.join(d['engines'])}（{d['period']}）"
          + (f"／AIO運用代行のページに業種別調査 {aio}業種" if aio else ""))
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
