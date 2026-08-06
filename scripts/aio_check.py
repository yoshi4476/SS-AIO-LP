# -*- coding: utf-8 -*-
"""AIO基盤（AIクローラー許可・llms.txt・構造化データ）が3サイトで揃っているかを見る

使い方: python scripts/aio_check.py

サイトごとに手で設定していると必ず差が出る。実際、AIクローラーの明示が
6種のサイトと13種のサイトが混在していた。公開中の実物を突き合わせて差分を出す。
"""
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126"}
WANT = [l.split("\t")[0] for l in
        (ROOT / "automation/ai-crawlers.txt").read_text(encoding="utf-8").splitlines() if "\t" in l]
# AI検索が引用判断に使う構造化データ。1つでも欠けると抽出されにくくなる
WANT_SCHEMA = {"FAQPage", "BreadcrumbList"}
ARTICLE_TYPES = {"BlogPosting", "Article", "NewsArticle"}


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def main():
    ng = []
    for cfg in sites_mod.load_all().values():
        d = cfg["domain"]
        print(f"■ {cfg['name']}（{d}）")

        rb = get(f"https://{d}/robots.txt")
        have = {a for a in re.findall(r"User-agent:\s*(\S+)", rb, re.I)}
        miss = [b for b in WANT if b not in have]
        if not rb:
            print("   robots.txt   取得できません"); ng.append(d)
        elif miss:
            print(f"   robots.txt   {len(have) - 1}種を明示 / 未記載: {', '.join(miss)}")
            ng.append(d)
        else:
            print(f"   robots.txt   OK（{len(WANT)}種すべて明示）")

        lt = get(f"https://{d}/llms.txt")
        arts = len([l for l in lt.splitlines() if re.search(r"\]\(https?://[^)]+/[^)/]+/?\)", l)])
        print(f"   llms.txt     {'OK' if arts else '記事が載っていません'}（掲載 {arts}件）")
        if not arts:
            ng.append(d)

        # 記事1本を実際に開いて構造化データを見る（テンプレートが壊れていないか）
        sm = get(f"https://{d}/sitemap.xml")
        # 記事ページを選ぶ。サービス紹介などを見ても記事テンプレートの検査にならない
        paths = [cfg["url_prefix"].strip("/")] if cfg.get("url_prefix") else list(cfg.get("categories", {}))
        locs = [u for u in re.findall(r"<loc>(.*?)</loc>", sm)
                if any(f"/{p_}/" in u for p_ in paths)
                and u.rstrip("/").split("/")[-1] not in paths
                and "/category/" not in u]   # 一覧ページは記事テンプレートではない
        if locs:
            h = get(locs[0])
            types = set(re.findall(r'"@type":\s*"([A-Za-z]+)"', h))
            lack = (WANT_SCHEMA - types) | ({"記事型"} if not (types & ARTICLE_TYPES) else set())
            print(f"   構造化データ {'OK' if not lack else '不足: ' + ', '.join(sorted(lack))}"
                  f"（{locs[0].replace('https://' + d, '')}）")
            if lack:
                ng.append(d)
        else:
            print("   構造化データ sitemapから記事URLを取得できません")
        print()

    if ng:
        print("AIO_OK=no（上の不足を埋めてください）")
        sys.exit(1)
    print("AIO_OK=yes（3サイトともAIクローラー・llms.txt・構造化データが揃っています）")


if __name__ == "__main__":
    main()
