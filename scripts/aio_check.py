# -*- coding: utf-8 -*-
"""AIO基盤（AIクローラー許可・llms.txt・構造化データ）が3サイトで揃っているかを見る

使い方: python scripts/aio_check.py

サイトごとに手で設定していると必ず差が出る。実際、AIクローラーの明示が
6種のサイトと13種のサイトが混在していた。公開中の実物を突き合わせて差分を出す。
"""
import re
import sys
import urllib.error
import urllib.parse
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
# 記事の下に置かれる一覧ページの区切り。sitemap の先頭が一覧（例: /blog/theme）だと、FAQ も記事型も
# 持たないのが正しいページを「不足」と出していた（2026-10-12 の週次）。一覧に FAQPage を足すのは誤り
LISTING_SEGMENTS = {"category", "categories", "theme", "themes", "tag", "tags", "page", "author",
                    "topics", "industry", "area", "compare", "glossary"}


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def article_urls(locs, paths):
    """sitemap の URL から記事テンプレートのページだけを残す（カテゴリ・テーマ・タグ・ページ送りの一覧は除く）"""
    out = []
    for u in locs:
        segs = [s for s in urllib.parse.urlsplit(u).path.split("/") if s]
        if (any(f"/{p_}/" in u for p_ in paths) and segs and segs[-1] not in paths
                and not set(segs) & LISTING_SEGMENTS):
            out.append(u)
    return out


def main():
    ng = []
    for sid, cfg in sites_mod.load_all().items():
        d = cfg["domain"]
        # CI のログは public。お客様の社は社名・ドメイン・記事の slug を出さず、公開の id で書く
        client = sites_mod.is_client(sid)
        print(f"■ {sites_mod.public_id(sid)}（お客様の社）" if client else f"■ {cfg['name']}（{d}）")

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
        locs = article_urls(re.findall(r"<loc>(.*?)</loc>", sm), paths)
        if locs:
            h = get(locs[0])
            types = set(re.findall(r'"@type":\s*"([A-Za-z]+)"', h))
            lack = (WANT_SCHEMA - types) | ({"記事型"} if not (types & ARTICLE_TYPES) else set())
            print(f"   構造化データ {'OK' if not lack else '不足: ' + ', '.join(sorted(lack))}"
                  f"（{'お客様の記事' if client else locs[0].replace('https://' + d, '')}）")
            if lack:
                ng.append(d)
        else:
            print("   構造化データ sitemapから記事URLを取得できません")
        print()

    # 見つかったことは印で表す（終了コード1は「検査が動かなかった」と区別できない。CLAUDE.md 8.7）
    if ng:
        print("AIO_OK=no（上の不足を埋めてください）")
        return
    print("AIO_OK=yes（3サイトともAIクローラー・llms.txt・構造化データが揃っています）")


if __name__ == "__main__":
    main()
