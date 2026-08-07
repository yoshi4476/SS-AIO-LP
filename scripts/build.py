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
score: 93        # 品質審査スコア(100点満点)。90点未満・未記載はビルド対象外(公開不可)
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
from urllib.parse import quote as urlquote

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import md2html  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
SITE = ROOT / "site"
TEMPLATE = ROOT / "templates" / "article.html"

# ---- サイト設定（ドメイン取得後に SITE_URL を差し替え） ----
SITE_URL = "https://ai.7senses.co.jp"
SITE_NAME = "AI集客ラボ"  # TODO: メディア名確定後に変更（PROJECT.md参照）
ORG_NAME = "セブンセンシズ株式会社"
# 著者は実在の個人にする。「編集部」を Person として出すと、検索エンジンにもAIにも
# 「誰が書いたか」が伝わらず、E-E-A-T の Experience / Expertise を主張できない。
# 経歴・実績・連絡先は /author/haraguchi/ に集約し、Schema からそこへ紐づける。
AUTHOR_NAME = "原口 優"
AUTHOR_ROLE = "セブンセンシズ株式会社 代表取締役／MEO・AI検索対策の実務歴6年"
AUTHOR_BIO = "通算3,200店舗以上の運営実績を持つMEO支援「G-ran」をはじめとする集客支援の実務経験をもとに、AIO・LLMO・SEO・MEOの実践情報を発信しています。"
AUTHOR_URL = f"{SITE_URL}/author/haraguchi/"   # 経歴・実績の実体があるページへ

CATEGORIES = {
    "aio": ("AIO・LLMO運用", "cat-aio"),
    "seo": ("SEO運用", "cat-seo"),
    "meo": ("MEO運用", "cat-meo"),
    "ai-marketing": ("AI集客・活用全般", "cat-ai"),
}

# privacy/tokushoho は noindex のため sitemap から除外（noindex×sitemap掲載の矛盾を防ぐ）
STATIC_PAGES = ["", "aio/", "seo/", "meo/", "ai-marketing/", "about/", "contact/", "download/", "lp/", "blog/", "glossary/", "diagnosis/", "diagnosis/meo/", "diagnosis/aio/", "site-audit/", "author/haraguchi/", "start/", "editorial-policy/"]


def jp_date(iso: str) -> str:
    y, m, d = str(iso).split("-")
    return f"{int(y)}年{int(m)}月{int(d)}日"


def article_site(path: Path):
    """記事のcategoryから、どのサイト向けの記事かを判定する（不明ならNone）"""
    try:
        import sites as sites_mod
        m = re.match(r"^---\s*\n(.*?)\n---", path.read_text(encoding="utf-8-sig"), re.S)
        cat = (yaml.safe_load(m.group(1)) or {}).get("category") if m else None
        return sites_mod.find_category_owner(cat) if cat else None
    except Exception:
        return None


def drop_stale_html(slug: str):
    """当サイトに残っている生成HTMLを消す（他サイトへ移した記事の重複公開を防ぐ）"""
    import shutil
    for cat in CATEGORIES:
        stale = SITE / cat / slug
        if stale.exists():
            shutil.rmtree(stale)
            print(f"REMOVED: 重複公開を解消（当サイトの生成HTMLを削除）: {cat}/{slug}/")


def parse_article(path: Path):
    text = path.read_text(encoding="utf-8-sig")  # BOM付き保存にも耐性
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
            "author": {"@type": "Person", "name": AUTHOR_NAME, "url": AUTHOR_URL,
                       "jobTitle": AUTHOR_ROLE,
                       "worksFor": {"@type": "Organization", "name": ORG_NAME,
                                    "url": SITE_URL}},
            "editor": {"@type": "Person", "name": "原口 優", "jobTitle": "代表取締役",
                       "url": f"{SITE_URL}/author/haraguchi/"},
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


# カテゴリ連動の記事末診断バナー（読者→診断→85点以下は無料相談へ、のリード導線）
DIAG_BANNERS = {
    "meo": ("/diagnosis/meo/", "MEO診断（無料・30秒）", "8つの質問で、Googleマップ集客の整備度を100点満点で採点します。"),
    "aio": ("/diagnosis/aio/", "AIO診断（無料・30秒）", "AI検索に引用される準備ができているかを100点満点で採点します。"),
    "seo": ("/site-audit/", "サイト無料採点（URL入力だけ）", "SEO・AI対応の技術12項目を100点満点で自動チェックします。"),
    "ai-marketing": ("/diagnosis/aio/", "AIO診断（無料・30秒）", "AI検索に引用される準備ができているかを100点満点で採点します。"),
}


def diag_banner_html(meta):
    href, title, desc = DIAG_BANNERS[meta["category"]]
    return (f'<aside class="diag-banner"><div class="db-text">'
            f'<span class="db-kicker">この記事のテーマで、自社の現在地を測る</span>'
            f'<span class="db-title">{title}</span>'
            f'<span class="db-desc">{desc}</span></div>'
            f'<a class="btn btn-primary" href="{href}" data-cta="article_diag_{meta["category"]}">'
            f'無料で診断する <span class="arw">→</span></a></aside>')


def prev_next_html(prev_meta, next_meta):
    if not prev_meta and not next_meta:
        return ""
    parts = ['<nav class="prev-next" aria-label="前後の記事">']
    if prev_meta:
        parts.append(f'<a class="pn" href="/{prev_meta["category"]}/{prev_meta["slug"]}/">'
                     f'<span>← 前の記事</span><strong>{prev_meta["title"]}</strong></a>')
    else:
        parts.append('<span class="pn pn-empty" aria-hidden="true"></span>')
    if next_meta:
        parts.append(f'<a class="pn pn-next" href="/{next_meta["category"]}/{next_meta["slug"]}/">'
                     f'<span>次の記事 →</span><strong>{next_meta["title"]}</strong></a>')
    else:
        parts.append('<span class="pn pn-empty" aria-hidden="true"></span>')
    parts.append('</nav>')
    return "".join(parts)


def build_article(path: Path, template: str, related: str = "", unpublished_urls=None, prevnext: str = ""):
    meta, body = parse_article(path)
    cat_name, cat_class = CATEGORIES[meta["category"]]
    url = f"{SITE_URL}/{meta['category']}/{meta['slug']}/"

    # 変換ルールは md2html に集約（publish.py と共通化し、サイト間で装飾がずれないようにする）
    content, toc_tokens = md2html.convert(body)

    # 連鎖隔離の防止: 未公開（BLOCKED）記事への内部リンクはテキスト化して404を出さない。
    # 元のMarkdownは変更しないため、リンク先が公開されれば次回ビルドで自動的にリンクへ戻る。
    if unpublished_urls:
        def _unwrap(m):
            if m.group(1).rstrip("/") + "/" in unpublished_urls:
                print(f"INFO: 未公開記事へのリンクをテキスト化: {meta['slug']} → {m.group(1)}"
                      "（リンク先の公開後、再ビルドで自動復活）")
                return m.group(2)
            return m.group(0)
        content = re.sub(r'<a href="(/[^":]+?)"[^>]*>(.*?)</a>', _unwrap, content)

    # マーカー数チェック（自動生成記事の装飾漏れ検出。基準: 8箇所以上、推奨12-18）
    marker_count = content.count("<strong>") + content.count("<mark>")
    if marker_count < 8:
        print(f"WARN: マーカー不足: {meta['slug']} は強調が{marker_count}箇所"
              f"（基準8箇所以上・推奨12-18箇所。**太字** か ==マーカー== を追加すること）")

    # 文字数チェック（Phase 5基準: 本文5,000字以上。タグ・空白を除いた実文字数で判定）
    plain = re.sub(r"<[^>]+>", "", content)
    plain = re.sub(r"\s", "", plain)
    if len(plain) < 5000:
        print(f"WARN: 文字数不足: {meta['slug']} は本文{len(plain):,}字"
              f"（基準5,000字以上。セクション追加・実務情報の深掘りで増強すること）")

    # 画像実在チェック（生成漏れ・パスtypoの検出。生成: python scripts/make_images.py <slug>）
    if meta.get("eyecatch") and not (SITE / meta["eyecatch"].lstrip("/")).exists():
        print(f"WARN: アイキャッチ未生成: {meta['slug']} → {meta['eyecatch']}")
    for src in sorted(set(re.findall(r'<img src="(/images/[^"]+)"', content))):
        if not (SITE / src.lstrip("/")).exists():
            print(f"WARN: 本文画像が存在しない: {meta['slug']} → {src}")

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
        "{{TOC}}": render_toc(toc_tokens),
        "{{EYECATCH}}": eyecatch,
        "{{CONTENT}}": content,
        "{{RELATED}}": related,
        "{{DIAG_BANNER}}": diag_banner_html(meta),
        "{{PREVNEXT}}": prevnext,
        "{{TITLE_ENC}}": urlquote(meta["title"]),
        "{{URL_ENC}}": urlquote(url, safe=""),
    }
    for k, v in replacements.items():
        html = html.replace(k, v)

    out = SITE / meta["category"] / meta["slug"] / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return meta, url


LISTING_RE = re.compile(
    r'(<!-- (?:新着)?記事リスト:.*?-->\s*<ul class="post-list[^"]*">).*?(</ul>)', re.S)


def sync_listings(all_metas):
    """トップの新着とカテゴリ一覧の記事リストを自動同期（手動追記を廃止し書き忘れをゼロに）"""
    newest = sorted(all_metas, key=lambda m: (str(m["date"]), m["slug"]), reverse=True)

    def replace(page: Path, metas, label):
        if not page.exists():
            return
        html = page.read_text(encoding="utf-8-sig")
        tiles = "\n".join(post_tile(m) for m in metas)
        new_html, n = LISTING_RE.subn(lambda mt: f"{mt.group(1)}\n{tiles}\n  {mt.group(2)}", html)
        if n and new_html != html:
            page.write_text(new_html, encoding="utf-8")
            print(f"SYNC: {label} の記事リストを自動更新（{len(metas)}件）")

    replace(SITE / "index.html", newest[:6], "トップ新着")
    for cat in CATEGORIES:
        cat_metas = [m for m in newest if m["category"] == cat]
        replace(SITE / cat / "index.html", cat_metas, f"カテゴリ {cat}")


def quality_checks(all_metas):
    """第6章 SEO実装詳細の機械検査: メタ品質 + カニバリ(タイトル類似80%)ゲート"""
    import difflib
    warns = []
    for m in all_metas:
        tl = len(m["title"])
        if not 15 <= tl <= 45:
            warns.append(f"タイトル字数NG: {m['slug']} = {tl}字（基準15〜45字）")
        dl = len(m["description"])
        if not 60 <= dl <= 160:
            warns.append(f"メタ記述字数NG: {m['slug']} = {dl}字（基準60〜160字）")
    for i in range(len(all_metas)):
        for j in range(i + 1, len(all_metas)):
            r = difflib.SequenceMatcher(None, all_metas[i]["title"], all_metas[j]["title"]).ratio()
            if r >= 0.8:
                warns.append(f"カニバリ疑い: タイトル類似{r:.0%} {all_metas[i]['slug']} ↔ {all_metas[j]['slug']}"
                             "（80%ゲート。タイトル/切り口を差別化するか統合を検討）")
    return warns


LINK_WHITELIST = {"/api/lead"}


def stamp_assets():
    """CSS/JSのURLに内容ハッシュを付ける（キャッシュ事故の防止）

    _headers で /css/* に7日のキャッシュを指定しているため、URLが同じままだと
    「新しいHTML × 古いCSS」の組み合わせになり、レイアウトが崩れたまま表示される。
    中身が変わったときだけURLが変わるようにして、更新を確実に届ける。
    """
    import hashlib
    ver = {}
    for rel in ("css/style.css", "js/site.js"):
        f = SITE / rel
        if f.exists():
            ver[rel] = hashlib.md5(f.read_bytes()).hexdigest()[:8]
    if not ver:
        return 0
    n = 0
    for p in SITE.rglob("*.html"):
        t = p.read_text(encoding="utf-8")
        new = t
        for rel, h in ver.items():
            new = re.sub(rf'(["\'])/{re.escape(rel)}(\?v=[0-9a-f]+)?(["\'])',
                         rf'\g<1>/{rel}?v={h}\g<3>', new)
        if new != t:
            p.write_text(new, encoding="utf-8", newline="")
            n += 1
    if n:
        print(f"ASSET: CSS/JSのURLにハッシュを付与（{n}ファイル更新 / "
              + " ".join(f"{k}={v}" for k, v in ver.items()) + "）")
    return n


def link_check():
    """内部リンクの存在検証（404ゼロ保証）"""
    warns = []
    for p in SITE.rglob("*.html"):
        t = p.read_text(encoding="utf-8")
        for href in sorted(set(re.findall(r'href="(/[^"#?]*)"', t))):
            if href in LINK_WHITELIST or href == "/":
                continue
            name = href.rstrip("/").rsplit("/", 1)[-1]
            target = SITE / href.lstrip("/") if "." in name else SITE / href.strip("/") / "index.html"
            if not target.exists():
                warns.append(f"リンク切れ: {p.relative_to(SITE)} → {href}")
    return warns


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
<script async src="https://www.googletagmanager.com/gtag/js?id=G-X6KNN36L9J"></script>
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','G-X6KNN36L9J');</script>
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
      <a href="https://lp.7senses.co.jp/" target="_blank" rel="noopener">AI導入補助金（独自メディア）</a>
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
  <p class="lead">AIO・LLMO・SEO・MEOの実践ノウハウを、カテゴリごとに分けて掲載しています。まず新着を見て、気になる領域の見出しから読み進めてください。</p>
</section>

<section class="section" style="padding-top:1rem;">
  <input type="search" id="blogSearch" class="blog-search" placeholder="記事をキーワードで検索（例: 口コミ / AIO / ChatGPT）" aria-label="記事を検索">
  <p id="blogSearchEmpty" class="blog-search-empty">該当する記事が見つかりませんでした。別のキーワードをお試しください。</p>
  <div class="cat-filter" id="catFilter" role="group" aria-label="カテゴリで絞り込む">
    <button type="button" data-target="all" aria-pressed="true">すべて</button>
    <button type="button" data-target="aio" aria-pressed="false">AIO・LLMO運用</button>
    <button type="button" data-target="seo" aria-pressed="false">SEO運用</button>
    <button type="button" data-target="meo" aria-pressed="false">MEO運用</button>
    <button type="button" data-target="ai-marketing" aria-pressed="false">AI集客・活用全般</button>
  </div>
{items}
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
      <a href="/start/">はじめての方へ</a>
      <a href="/blog/">記事一覧</a>
      <a href="/glossary/">用語集</a>
      <a href="/diagnosis/meo/">MEO診断</a>
      <a href="/diagnosis/aio/">AIO診断</a>
      <a href="/site-audit/">サイト診断</a>
      <a href="/aio/">AIO・LLMO運用</a>
      <a href="/seo/">SEO運用</a>
      <a href="/meo/">MEO運用</a>
      <a href="/ai-marketing/">AI集客・活用</a>
      <a href="/about/">運営者情報</a>
      <a href="/author/haraguchi/">監修者プロフィール</a>
      <a href="https://lp.7senses.co.jp/" target="_blank" rel="noopener">AI導入補助金サポート</a>
      <a href="/lp/">集客支援サービス</a>
      <a href="/contact/">お問い合わせ</a>
      <a href="/editorial-policy/">編集・訂正ポリシー</a>
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
    """記事一覧をカテゴリごとに区切って出す。

    全記事を日付順に並べるだけだと、読者が「自分の知りたい領域」にたどり着けない。
    カテゴリごとの塊にして、各見出しからカテゴリページへも入れるようにする。
    """
    newest = sorted(all_metas, key=lambda m: str(m["date"]), reverse=True)
    blocks = [
        '<div class="latest-block" data-cat="new">'
        '<div class="cat-head"><h2>新着</h2>'
        f'<span class="cnt">全{len(newest)}本</span></div>'
        f'<ul class="post-list">\n{chr(10).join(post_tile(m) for m in newest[:6])}\n</ul></div>'
    ]
    for cat, (name, cls) in CATEGORIES.items():
        metas = [m for m in newest if m["category"] == cat]
        if not metas:
            continue
        tiles = "\n".join(post_tile(m) for m in metas)
        blocks.append(
            f'<div class="latest-block {cls}" data-cat="{cat}">'
            f'<div class="cat-head"><h2>{name}</h2>'
            f'<span class="cnt">{len(metas)}本</span>'
            f'<a class="more" href="/{cat}/">このカテゴリを見る →</a></div>'
            f'<ul class="post-list">\n{tiles}\n</ul></div>')
    out = SITE / "blog" / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(BLOG_PAGE.format(site=SITE_NAME, url=SITE_URL, items="\n".join(blocks)),
                   encoding="utf-8")


def main():
    template = TEMPLATE.read_text(encoding="utf-8")
    only = sys.argv[1] if len(sys.argv) > 1 else None
    entries, warns = [], []

    llms = (SITE / "llms.txt").read_text(encoding="utf-8")

    # 品質審査ゲート: score(100点満点) 90点未満・未審査はアップロードしない
    QUALITY_GATE = 90
    paths, all_metas, blocked, blocked_metas = [], [], [], []
    for p in sorted(ARTICLES.glob("*.md")):
        if p.name.startswith("_"):
            continue
        # 他サイト向けの記事は publish.py が配信済み。ここで「不正」と扱うと
        # 救済処理が当サイトのカテゴリへ書き換えてしまい、2ドメインに同じ記事が出る
        owner = article_site(p)
        if owner and owner != "ai-lab":
            print(f"SKIP(他サイト): {p.stem} → {owner} へ配信済み")
            drop_stale_html(p.stem)
            continue
        # 1記事の不正フロントマターで全ビルドを止めない（不正記事はBLOCKED扱いで続行）
        try:
            meta = parse_article(p)[0]
        except Exception as e:
            blocked.append(f"{p.stem}: フロントマター不正（{e}）")
            print(f"BLOCKED(公開不可): {p.stem}: フロントマター不正 → {e}")
            continue
        sc = meta.get("score")
        if not isinstance(sc, (int, float)):
            blocked.append(f"{meta['slug']}: 未審査（score が数値で記載されていない: {sc!r}）")
            blocked_metas.append(meta)
            continue
        if sc < QUALITY_GATE:
            blocked.append(f"{meta['slug']}: {sc}点 < 基準{QUALITY_GATE}点")
            blocked_metas.append(meta)
            continue
        # 足切り: score_breakdown がある場合、1観点でも16/20未満なら不合格（合計点で壊滅観点を隠さない）
        bd = meta.get("score_breakdown") or {}
        weak = {k: v for k, v in bd.items() if isinstance(v, (int, float)) and v < 16}
        if weak:
            blocked.append(f"{meta['slug']}: 観点足切り {weak}（各16/20以上が必要）")
            blocked_metas.append(meta)
            continue
        paths.append(p)
        all_metas.append(meta)
    for b in blocked:
        print(f"BLOCKED(公開不可): {b} → 修正・再審査後に score を更新してください")

    # 隔離記事の生成済みHTMLを物理削除（過去ビルドの残骸が配信されるのを防ぐ）
    unpublished_urls = set()
    for meta in blocked_metas:
        unpublished_urls.add(f"/{meta['category']}/{meta['slug']}/")
        stale = SITE / meta["category"] / meta["slug"]
        if stale.exists():
            import shutil
            shutil.rmtree(stale)
            print(f"REMOVED: 隔離記事の生成HTMLを削除: {stale.relative_to(SITE)}/")

    # 前後ナビ用の時系列順（公開日→slugで安定ソート）
    ordered = sorted(all_metas, key=lambda m: (str(m["date"]), m["slug"]))
    pos = {m["slug"]: i for i, m in enumerate(ordered)}

    for path in paths:
        meta = next(m for m in all_metas if m["slug"] == parse_article(path)[0]["slug"])
        i = pos[meta["slug"]]
        prev_meta = ordered[i - 1] if i > 0 else None
        next_meta = ordered[i + 1] if i < len(ordered) - 1 else None
        meta, url = build_article(path, template, related_html(meta, all_metas),
                                  unpublished_urls=unpublished_urls,
                                  prevnext=prev_next_html(prev_meta, next_meta))
        entries.append((meta, url))
        if url not in llms:
            warns.append(f"llms.txt 未追記: {meta['title']} -> {url}")
        if only and meta["slug"] == only:
            print(f"built: {url}")

    build_blog_index(all_metas)
    build_sitemap(entries)
    build_feed(entries)
    sync_listings(all_metas)
    warns += quality_checks(all_metas)
    stamp_assets()
    warns += link_check()
    print(f"OK: {len(entries)}記事 / blog一覧 + sitemap.xml + feed.xml 更新")
    for w in warns:
        print(f"WARN: {w}")
    if not warns:
        print("品質検査: メタ字数・カニバリ・内部リンク404 すべてクリア")


if __name__ == "__main__":
    main()
