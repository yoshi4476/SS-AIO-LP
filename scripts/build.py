# -*- coding: utf-8 -*-
"""articles/*.md -> site/{cat}/{slug}/index.html 変換 + sitemap.xml 生成。

使い方:
    python scripts/build.py            # 全記事ビルド + sitemap再生成
    python scripts/build.py <slug>     # 指定記事のみビルド + sitemap再生成

記事Markdownの先頭にYAMLフロントマターが必要:
---
title: 記事タイトル（H1・30文字以内目安）
description: メタディスクリプション（120文字以内）
slug: url-slug
category: aio | seo | meo | ai-marketing
date: 2026-07-27
modified: 2026-07-27
eyecatch: /images/url-slug/eyecatch.png   # 省略可
faq:
  - q: 質問文
    a: 回答文（40-60字・本文FAQと完全一致させる）
---
※ ファイル名が _ で始まる記事（例: _sample.md）は下書き扱いでスキップ。
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import markdown
import yaml

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
SITE = ROOT / "site"
TEMPLATE = ROOT / "templates" / "article.html"

# ---- サイト設定（ドメイン取得後に SITE_URL を差し替え） ----
SITE_URL = "https://example.com"
SITE_NAME = "AI集客ラボ"  # TODO: メディア名確定後に変更（PROJECT.md参照）
ORG_NAME = "セブンセンシズ株式会社"
AUTHOR_NAME = "セブンセンシズ編集部"  # TODO: 著者確定後に変更
AUTHOR_ROLE = "AI集客・MEO/SEO運用の実務チーム"  # TODO
AUTHOR_BIO = "G-ranをはじめとする店舗集客支援の実務経験をもとに、AIO・SEO・MEOの実践情報を発信しています。"  # TODO
AUTHOR_URL = f"{SITE_URL}/about/"

CATEGORIES = {
    "aio": ("AIO・LLMO運用", "cat-aio"),
    "seo": ("SEO運用", "cat-seo"),
    "meo": ("MEO運用", "cat-meo"),
    "ai-marketing": ("AI集客・活用全般", "cat-ai"),
}

STATIC_PAGES = ["", "aio/", "seo/", "meo/", "ai-marketing/", "about/", "contact/", "download/", "lp/", "privacy/", "tokushoho/", "blog/", "glossary/"]


def jp_date(iso: str) -> str:
    y, m, d = str(iso).split("-")
    return f"{int(y)}年{int(m)}月{int(d)}日"


def parse_article(path: Path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: フロントマターがありません")
    meta = yaml.safe_load(m.group(1))
    for key in ("title", "description", "slug", "category", "date"):
        if key not in meta:
            raise ValueError(f"{path.name}: フロントマター '{key}' が必須です")
    if meta["category"] not in CATEGORIES:
        raise ValueError(f"{path.name}: category は {list(CATEGORIES)} のいずれか")
    meta.setdefault("modified", meta["date"])
    return meta, m.group(2)


def render_toc(toc_tokens) -> str:
    if not toc_tokens:
        return ""
    items = []
    for t in toc_tokens:  # H2のみ（AIO: Query Fan-Out単位）
        items.append(f'<li><a href="#{t["id"]}">{t["name"]}</a></li>')
    return ('<nav class="toc" aria-label="目次"><span class="toc-title">目次</span>'
            f'<ol>{"".join(items)}</ol></nav>')


def build_json_ld(meta, url):
    cat_name, _ = CATEGORIES[meta["category"]]
    graph = [
        {
            "@type": "BlogPosting",
            "headline": meta["title"],
            "description": meta["description"],
            "mainEntityOfPage": url,
            "image": SITE_URL + meta.get("eyecatch", "/images/ogp-default.png"),
            "datePublished": str(meta["date"]),
            "dateModified": str(meta["modified"]),
            "author": {"@type": "Person", "name": AUTHOR_NAME, "url": AUTHOR_URL},
            "publisher": {"@type": "Organization", "name": ORG_NAME, "url": SITE_URL},
            "inLanguage": "ja",
        },
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "ホーム", "item": SITE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": cat_name,
                 "item": f"{SITE_URL}/{meta['category']}/"},
                {"@type": "ListItem", "position": 3, "name": meta["title"], "item": url},
            ],
        },
    ]
    if meta.get("faq"):
        graph.append({
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in meta["faq"]
            ],
        })
    return json.dumps({"@context": "https://schema.org", "@graph": graph},
                      ensure_ascii=False, indent=1)


def post_tile(meta):
    cat_name, cat_class = CATEGORIES[meta["category"]]
    thumb = ""
    if meta.get("eyecatch"):
        thumb = (f'<span class="thumb"><img src="{meta["eyecatch"]}" '
                 f'alt="{meta["title"]}のアイキャッチ画像" width="1200" height="675" loading="lazy"></span>')
    return (f'    <li class="{cat_class}"><a href="/{meta["category"]}/{meta["slug"]}/">{thumb}'
            f'<time datetime="{meta["date"]}">{str(meta["date"]).replace("-", ".")}</time>'
            f'<h3>{meta["title"]}<span class="tag">{cat_name.replace("・活用全般", "").replace("運用", "")}</span></h3></a></li>')


def related_html(meta, all_metas):
    same = [m for m in all_metas if m["slug"] != meta["slug"] and m["category"] == meta["category"]]
    others = [m for m in all_metas if m["slug"] != meta["slug"] and m["category"] != meta["category"]]
    picks = (same + others)[:3]
    if not picks:
        return ""
    tiles = "\n".join(post_tile(m) for m in picks)
    return ('<section class="related"><h2>あわせて読みたい関連記事</h2>'
            f'<ul class="post-list">\n{tiles}\n  </ul></section>')


def build_article(path: Path, template: str, related: str = ""):
    meta, body = parse_article(path)
    cat_name, cat_class = CATEGORIES[meta["category"]]
    url = f"{SITE_URL}/{meta['category']}/{meta['slug']}/"

    md = markdown.Markdown(extensions=["tables", "extra", "toc", "sane_lists"],
                           extension_configs={"toc": {"toc_depth": "2-2"}})
    content = md.convert(body)
    content = content.replace("<table>", '<div class="table-wrap"><table>').replace(
        "</table>", "</table></div>")
    # 装飾記法: ==テキスト== → <mark>（黄マーカー）。CSSでstrong=黄マーカー等も自動適用
    content = re.sub(r"==([^=<>\n]+?)==", r"<mark>\1</mark>", content)

    eyecatch = ""
    if meta.get("eyecatch"):
        eyecatch = (f'<figure class="article-eyecatch"><img src="{meta["eyecatch"]}" '
                    f'alt="{meta["title"]}" width="1200" height="675"></figure>')

    html = template
    replacements = {
        "{{TITLE}}": meta["title"],
        "{{TITLE_SHORT}}": meta["title"][:22],
        "{{DESCRIPTION}}": meta["description"],
        "{{CANONICAL}}": url,
        "{{OG_IMAGE}}": SITE_URL + meta.get("eyecatch", "/images/ogp-default.png"),
        "{{SITE_NAME}}": SITE_NAME,
        "{{CAT_NAME}}": cat_name,
        "{{CAT_SLUG}}": meta["category"],
        "{{CAT_CLASS}}": cat_class,
        "{{DATE_PUB}}": str(meta["date"]),
        "{{DATE_MOD}}": str(meta["modified"]),
        "{{DATE_PUB_JP}}": jp_date(meta["date"]),
        "{{DATE_MOD_JP}}": jp_date(meta["modified"]),
        "{{AUTHOR_NAME}}": AUTHOR_NAME,
        "{{AUTHOR_ROLE}}": AUTHOR_ROLE,
        "{{AUTHOR_BIO}}": AUTHOR_BIO,
        "{{JSON_LD}}": build_json_ld(meta, url),
        "{{TOC}}": render_toc(md.toc_tokens),
        "{{EYECATCH}}": eyecatch,
        "{{CONTENT}}": content,
        "{{RELATED}}": related,
    }
    for k, v in replacements.items():
        html = html.replace(k, v)

    out = SITE / meta["category"] / meta["slug"] / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return meta, url


def build_feed(article_entries):
    from xml.sax.saxutils import escape
    items = sorted(article_entries, key=lambda e: str(e[0]["modified"]), reverse=True)[:20]
    today = date.today().isoformat()
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<feed xmlns="http://www.w3.org/2005/Atom">',
             f"  <title>{escape(SITE_NAME)}</title>",
             f'  <link href="{SITE_URL}/"/>',
             f'  <link rel="self" href="{SITE_URL}/feed.xml"/>',
             f"  <id>{SITE_URL}/</id>",
             f"  <updated>{today}T00:00:00+09:00</updated>",
             f"  <author><name>{escape(ORG_NAME)}</name></author>"]
    for meta, url in items:
        parts += ["  <entry>",
                  f"    <title>{escape(meta['title'])}</title>",
                  f'    <link href="{url}"/>',
                  f"    <id>{url}</id>",
                  f"    <updated>{meta['modified']}T00:00:00+09:00</updated>",
                  f"    <summary>{escape(meta['description'])}</summary>",
                  "  </entry>"]
    parts.append("</feed>")
    (SITE / "feed.xml").write_text("\n".join(parts) + "\n", encoding="utf-8")


def build_sitemap(article_entries):
    today = date.today().isoformat()
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for p in STATIC_PAGES:
        lines.append(f"  <url><loc>{SITE_URL}/{p}</loc><lastmod>{today}</lastmod></url>")
    for meta, url in article_entries:
        lines.append(f"  <url><loc>{url}</loc><lastmod>{meta['modified']}</lastmod></url>")
    lines.append("</urlset>")
    (SITE / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")


BLOG_PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>記事一覧｜{site}</title>
<meta name="description" content="{site}の全記事一覧。AIO・LLMO・SEO・MEOの実践ノウハウを新着順に掲載しています。">
<link rel="canonical" href="{url}/blog/">
<meta name="theme-color" content="#071a38">
<meta property="og:type" content="website">
<meta property="og:locale" content="ja_JP">
<meta property="og:title" content="記事一覧｜{site}">
<meta property="og:url" content="{url}/blog/">
<meta property="og:site_name" content="{site}">
<link rel="icon" type="image/png" href="/images/icon-192.png">
<link rel="apple-touch-icon" href="/images/icon-180.png">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="alternate" type="application/atom+xml" title="{site} 新着記事" href="/feed.xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=Zen+Kaku+Gothic+New:wght@700;900&family=Outfit:wght@500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/css/style.css">
<script>document.documentElement.classList.add('js');</script>
<script defer src="/js/site.js"></script>
</head>
<body>

<header class="site-header">
  <div class="inner">
    <a class="brand" href="/">
      <img class="brand-logo" src="/images/company/logo.png" alt="Seven Senses" width="371" height="147">
      <span class="mark">{site}<span class="by">by セブンセンシズ株式会社</span></span>
    </a>
    <button class="nav-toggle" aria-label="メニューを開く" aria-expanded="false"><span></span></button>
    <nav class="global-nav" aria-label="グローバルナビゲーション">
      <a href="/aio/">AIO・LLMO</a>
      <a href="/seo/">SEO運用</a>
      <a href="/meo/">MEO運用</a>
      <a href="/ai-marketing/">AI集客</a>
      <a href="/lp/" class="nav-cta">無料相談</a>
    </nav>
  </div>
</header>

<nav class="breadcrumb" aria-label="パンくずリスト">
  <ol>
    <li><a href="/">ホーム</a></li>
    <li aria-current="page">記事一覧</li>
  </ol>
</nav>

<section class="hero">
  <span class="kicker">All Articles</span>
  <h1>記事一覧</h1>
  <p class="lead">AIO・LLMO・SEO・MEOの実践ノウハウを新着順に掲載しています。カテゴリで絞り込む場合はナビゲーションからどうぞ。</p>
</section>

<section class="section" style="padding-top:1rem;">
  <ul class="post-list">
{items}
  </ul>
</section>

<section class="section">
  <div class="cta reveal">
    <p class="cta-copy">読んで終わりにせず、自社の集客改善につなげませんか？</p>
    <a class="btn btn-primary" href="/lp/">AIO・LLMO・SEO・MEO集客支援の無料相談へ <span class="arw">→</span></a>
    <p class="cta-sub">現状分析レポートを無料でお渡ししています</p>
  </div>
</section>

<footer class="site-footer">
  <div class="inner">
    <div>
      <img class="footer-logo" src="/images/company/logo-white.png" alt="Seven Senses セブンセンシズ株式会社" width="371" height="147" loading="lazy">
      <div class="brand-f">{site}</div>
      <p style="font-size:.8rem;color:rgba(255,255,255,.6);margin:.5em 0 0;">AIに選ばれる集客を、実務からつくる。</p>
      <p class="addr">運営: セブンセンシズ株式会社<br>〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902</p>
    </div>
    <nav aria-label="フッターナビゲーション">
      <a href="/blog/">記事一覧</a>
      <a href="/glossary/">用語集</a>
      <a href="/aio/">AIO・LLMO運用</a>
      <a href="/seo/">SEO運用</a>
      <a href="/meo/">MEO運用</a>
      <a href="/ai-marketing/">AI集客・活用</a>
      <a href="/about/">運営者情報</a>
      <a href="/lp/">集客支援サービス</a>
      <a href="/contact/">お問い合わせ</a>
      <a href="/privacy/">プライバシーポリシー</a>
      <a href="/tokushoho/">特定商取引法に基づく表記</a>
    </nav>
    <div class="copyright">© 2026 Seven Senses Inc. All rights reserved.</div>
  </div>
</footer>

</body>
</html>
"""


def build_blog_index(all_metas):
    items = "\n".join(post_tile(m) for m in sorted(all_metas, key=lambda m: str(m["date"]), reverse=True))
    out = SITE / "blog" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(BLOG_PAGE.format(site=SITE_NAME, url=SITE_URL, items=items), encoding="utf-8")


def main():
    template = TEMPLATE.read_text(encoding="utf-8")
    only = sys.argv[1] if len(sys.argv) > 1 else None
    entries, warns = [], []

    llms = (SITE / "llms.txt").read_text(encoding="utf-8")

    paths = [p for p in sorted(ARTICLES.glob("*.md")) if not p.name.startswith("_")]
    all_metas = [parse_article(p)[0] for p in paths]

    for path in paths:
        meta = next(m for m in all_metas if m["slug"] == parse_article(path)[0]["slug"])
        meta, url = build_article(path, template, related_html(meta, all_metas))
        entries.append((meta, url))
        if url not in llms:
            warns.append(f"llms.txt 未追記: {meta['title']} -> {url}")
        if only and meta["slug"] == only:
            print(f"built: {url}")

    build_blog_index(all_metas)
    build_sitemap(entries)
    build_feed(entries)
    print(f"OK: {len(entries)}記事 / blog一覧 + sitemap.xml + feed.xml 更新")
    for w in warns:
        print(f"WARN: {w}")


if __name__ == "__main__":
    main()
