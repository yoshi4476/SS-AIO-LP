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
import md2html
import entities  # noqa: E402
import render_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "articles"
SITE = ROOT / "site"
TEMPLATE = ROOT / "templates" / "article.html"

# ---- ナビゲーション ----
# 別のサイトへ移したとき、ここが直書きだと全ページに存在しないページへの
# リンクが並ぶ。site.config.json に nav / footer_nav があればそれを使い、
# 無ければ下の既定を使う（このサイトの表示は変わらない）。
NAV_DEFAULT = [
    {"label": "AIO・LLMO", "url": "/aio/"},
    {"label": "SEO運用", "url": "/seo/"},
    {"label": "MEO運用", "url": "/meo/"},
    {"label": "AI集客", "url": "/ai-marketing/"},
    {"label": "業種から探す", "url": "/industry/"},
    {"label": "実装ラボ", "url": "/lab/"},
    {"label": "AI導入補助金（独自メディア）", "url": "https://lp.7senses.co.jp/",
     "blank": True},
    {"label": "コーポレートサイト", "url": "https://corp.7senses.co.jp/", "blank": True},
    {"label": "無料相談", "url": "/lp/", "class": "nav-cta", "cta": "nav_consult"},
]
FOOTER_NAV_DEFAULT = [
    {"label": "はじめての方へ", "url": "/start/"},
    {"label": "業種から探す", "url": "/industry/"},
    {"label": "実測データ（一次データ）", "url": "/data/"},
    {"label": "無料資料ダウンロード", "url": "/download/"},
    {"label": "記事一覧", "url": "/blog/"},
    {"label": "用語集", "url": "/glossary/"},
    {"label": "マップ集客の整備度チェック（30秒）", "url": "/diagnosis/meo/"},
    {"label": "AI検索の対応度チェック（30秒）", "url": "/diagnosis/aio/"},
    {"label": "サイトの技術チェック", "url": "/site-audit/"},
    {"label": "AIO・LLMO運用", "url": "/aio/"},
    {"label": "SEO運用", "url": "/seo/"},
    {"label": "MEO運用", "url": "/meo/"},
    {"label": "AI集客・活用", "url": "/ai-marketing/"},
    {"label": "運営者情報", "url": "/about/"},
    {"label": "監修者プロフィール", "url": "/author/haraguchi/"},
    {"label": "AI導入補助金サポート", "url": "https://lp.7senses.co.jp/", "blank": True},
    {"label": "コーポレートサイト", "url": "https://corp.7senses.co.jp/", "blank": True},
    {"label": "集客支援サービス", "url": "/lp/"},
    {"label": "お問い合わせ", "url": "/contact/"},
    {"label": "編集・訂正ポリシー", "url": "/editorial-policy/"},
    {"label": "プライバシーポリシー", "url": "/privacy/"},
    {"label": "特定商取引法に基づく表記", "url": "/tokushoho/"},
]


CTA_DEFAULT = {
    "cta_copy": "読んで終わりにせず、自社の集客改善につなげませんか？",
    "cta_url": "/lp/",
    "cta_label": "AIO・LLMO・SEO・MEO集客支援の無料相談へ",
    "cta_sub": "現状分析レポートを無料でお渡ししています",
}


def _conf():
    p = ROOT / "site.config.json"
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {}


def _cta():
    c = _conf()
    return {k: c.get(k) or v for k, v in CTA_DEFAULT.items()}


def _nav(key, fallback):
    got = _conf().get(key)
    items = got if isinstance(got, list) and got else fallback
    out = []
    for it in items:
        cls = ' class="' + it["class"] + '"' if it.get("class") else ""
        tgt = ' target="_blank" rel="noopener"' if it.get("blank") else ""
        cta = ' data-cta="' + it["cta"] + '"' if it.get("cta") else ""
        out.append('      <a href="' + it["url"] + '"' + tgt + cls + cta + ">"
                   + it["label"] + "</a>")
    return "\n".join(out)

# ---- サイト設定 ----
# 別のサイトへ移したときは site.config.json を置けば切り替わる。
# 無ければ下の値を使う（このサイトの出力は変わらない）。
_C = _conf()
SITE_URL = _C.get("site_url") or (
    "https://" + _C["domain"] if _C.get("domain") else "https://ai.7senses.co.jp")
SITE_NAME = _C.get("site_name") or "AI集客ラボ"
ORG_NAME = _C.get("org_name") or "セブンセンシズ株式会社"
# 同名の別法人（東京都目黒区・法人番号9120001168304）が存在する。社名だけでは
# 機械が区別できないため、法人番号と所在地を必ず添えて出す。
# sameAs には法人番号がURLに含まれるページだけを入れる（名前しか載らないページを
# 入れると、別法人との混同を自分から強めることになる）。
ORG_NUMBER = "3120001227825"
ORG_ADDRESS = {"postal": "537-0003", "region": "大阪府", "city": "大阪市東成区",
               "street": "神路1丁目7-4 コンフォートビル901・902"}
ORG_TEL = "06-4305-7547"
ORG_SAME_AS = [
    f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto.html?selHouzinNo={ORG_NUMBER}",
    f"https://alarmbox.jp/companyinfo/entities/{ORG_NUMBER}",
    "https://corp.7senses.co.jp/",
    "https://lp.7senses.co.jp/",
    # 旧サイト（別業者が運用）。同じ会社のものだと示しておく。
    # 示さないと、社名の検索で「別の組織」として評価が分かれる
    "https://www.7senses.co.jp/",
    # Googleマップの店舗情報。サイトと地図の店舗が同じ会社だと機械に伝える（地図検索・AI検索の NAP の一致）
    "https://www.google.com/maps?cid=815053100031552916",
]
ORG_GEO = {"@type": "GeoCoordinates", "latitude": 34.6791137, "longitude": 135.555196}
ORG_MAP = "https://www.google.com/maps?cid=815053100031552916"


def organization():
    """全ページ共通の発行者情報。法人番号まで出して実在を機械的に確認できるようにする"""
    return {
        "@type": "Organization", "name": ORG_NAME, "alternateName": "SEVEN SENSES Inc.",
        "url": SITE_URL, "telephone": ORG_TEL,
        "identifier": {"@type": "PropertyValue", "name": "法人番号",
                       "propertyID": "https://www.houjin-bangou.nta.go.jp/",
                       "value": ORG_NUMBER},
        "address": {"@type": "PostalAddress", "addressCountry": "JP",
                    "postalCode": ORG_ADDRESS["postal"],
                    "addressRegion": ORG_ADDRESS["region"],
                    "addressLocality": ORG_ADDRESS["city"],
                    "streetAddress": ORG_ADDRESS["street"]},
        "sameAs": ORG_SAME_AS,
        "location": {"@type": "Place", "geo": ORG_GEO, "hasMap": ORG_MAP},
        # 専門領域。実体（about）と合わせて「この会社はこの領域の専門」と機械に伝える
        "knowsAbout": entities.KNOWS_ABOUT,
    }
# 著者は実在の個人にする。「編集部」を Person として出すと、検索エンジンにもAIにも
# 「誰が書いたか」が伝わらず、E-E-A-T の Experience / Expertise を主張できない。
# 経歴・実績・連絡先は /author/haraguchi/ に集約し、Schema からそこへ紐づける。
# site.config.json の byline。author_name は別の用途（移行時の置換元）で
# 使っているため、記事の署名はここに分けて持つ。
_B = _C.get("byline") or {}
AUTHOR_NAME = _B.get("name") or "原口 優"
AUTHOR_ROLE = _B.get("role") or "セブンセンシズ株式会社 代表取締役／MEO・AI検索対策の実務歴6年"
AUTHOR_BIO = _B.get("bio") or "通算3,200店舗以上の運営実績を持つMEO支援「G-ran」をはじめとする集客支援の実務経験をもとに、AIO・LLMO・SEO・MEOの実践情報を発信しています。"
# 経歴・実績の実体があるページへ。無い人を指すと E-E-A-T の主張が空振りする
AUTHOR_URL = _B.get("url") or f"{SITE_URL}/author/haraguchi/"
# 外部の実在プロフィール。サイトの外でも同じ人物だと機械が結び付けられるようにする
AUTHOR_SAME_AS = _B.get("same_as") or ["https://www.linkedin.com/in/yu-haraguchi", "https://note.com/yu_haraguchi", "https://corp.7senses.co.jp/"]
# author_profile.py が台帳（動画・言及・author.json）から束ねた分があれば、それを使う。
# 固定リストのままだと、YouTube や登壇が増えても記事の Person に反映されない
try:
    _AP = json.loads((ROOT / "data" / "author_profile.json").read_text(encoding="utf-8"))
    if _AP.get("same_as"):
        AUTHOR_SAME_AS = list(dict.fromkeys(list(AUTHOR_SAME_AS) + list(_AP["same_as"])))
except Exception:
    pass

CATEGORIES = {
    "aio": ("AIO・LLMO運用", "cat-aio"),
    "seo": ("SEO運用", "cat-seo"),
    "meo": ("MEO運用", "cat-meo"),
    "ai-marketing": ("AI集客・活用全般", "cat-ai"),
}

# privacy/tokushoho は noindex のため sitemap から除外（noindex×sitemap掲載の矛盾を防ぐ）
# glossary/ は build_sitemap の生成ページのループが出す（ここにも書くと2回載る）
STATIC_PAGES = ["", "aio/", "seo/", "meo/", "ai-marketing/", "about/", "contact/", "download/", "lp/", "blog/", "diagnosis/", "diagnosis/meo/", "diagnosis/aio/", "site-audit/", "author/haraguchi/", "start/", "editorial-policy/", "lab/", "data/"]


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
    _modified_guard(meta, m.group(2))
    return meta, m.group(2)


# 更新日の実体化: 本文が変わっていないのに modified だけ進んだ記事は、前回の
# dateModified のままにする（日付だけ動かしても評価されず、鮮度の信号が薄まる）。
# 本文のハッシュと、そのときの更新日を data/body_hash.json に持つ
_HASH_FILE = ROOT / "data" / "body_hash.json"
try:
    _HASHES = json.loads(_HASH_FILE.read_text(encoding="utf-8")) if _HASH_FILE.is_file() else {}
except Exception:
    _HASHES = {}


def _modified_guard(meta, body):
    import hashlib
    h = hashlib.md5(re.sub(r"\s+", " ", body).encode("utf-8")).hexdigest()
    rec = _HASHES.get(meta["slug"])
    cur = str(meta["modified"])
    if rec and rec.get("hash") == h and rec.get("modified") and str(rec["modified"]) < cur:
        meta["modified"] = rec["modified"]           # 本文が同じなら日付を進めない
        return
    if not rec or rec.get("hash") != h or str(rec.get("modified", "")) < cur:
        _HASHES[meta["slug"]] = {"hash": h, "modified": cur}


_REVIEWS = None


def how_made(slug):
    """この記事の作り方を開示する一文（誰が・どうやって・どう確かめたか）。

    Google は AI を使った制作そのものではなく、読者が知りたい「どう作ったか」を
    隠すことを問題にする。監修日は台帳の記録から出し、記録の無い日付は書かない
    """
    global _REVIEWS
    if _REVIEWS is None:
        import editorial_review
        _REVIEWS = editorial_review.load()
    r = _REVIEWS.get(slug) or {}
    # 一括登録の日付は「記録した日」で、確認した日ではないため出さない
    when = "" if "一括登録" in (r.get("note") or "") else (r.get("at") or "")[:10]
    return ("制作の流れ: 一次情報と出典を集め、AIツールで下書き → 機械検査18項目と3観点の採点"
            "（90点以上のみ公開）→ 監修者が事実と表現を確認"
            + (f"（{when}）" if when else "") + "。"
            '<a href="/editorial-policy/">編集・訂正ポリシー</a>')


def save_body_hashes():
    try:
        _HASH_FILE.parent.mkdir(exist_ok=True)
        _HASH_FILE.write_text(json.dumps(_HASHES, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8", newline="\n")
    except Exception as e:
        print(f"WARN: 更新日の台帳を書けません（{str(e)[:40]}）")


def render_toc(toc_tokens) -> str:
    if not toc_tokens:
        return ""
    items = []
    for t in toc_tokens:  # H2のみ（AIO: Query Fan-Out単位）
        items.append(f'<li><a href="#{t["id"]}">{t["name"]}</a></li>')
    return ('<nav class="toc" aria-label="目次"><span class="toc-title">目次</span>'
            f'<ol>{"".join(items)}</ol></nav>')


def howto_steps(body_html):
    """本文から手順を取り出す。「ステップN:」「手順N:」の見出しだけを拾う。

    見出しの文言をそのまま名前にし、直後の段落の先頭文を説明にする。
    手順が3つ未満のものは手順記事ではないので出さない（無理に出すと
    「読む記事」まで HowTo になり、構造の意味が薄れる）。
    """
    out = []
    heads = list(re.finditer(
        r"<h[34][^>]*>\s*(?:ステップ|手順|STEP)\s*(\d+)\s*[:：.、]?\s*(.+?)</h[34]>",
        body_html, re.I | re.S))
    for i, m in enumerate(heads):
        name = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        seg = body_html[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(body_html)]
        p = re.search(r"<p[^>]*>(.*?)</p>", seg, re.S)
        text = re.sub(r"<[^>]+>", "", p.group(1)).strip() if p else ""
        text = re.sub(r"\s+", " ", text)[:300]
        if name:
            out.append({"@type": "HowToStep", "position": i + 1,
                        "name": name, **({"text": text} if text else {})})
    return out if len(out) >= 3 else []


def build_json_ld(meta, url, body_text=""):
    cat_name, _ = CATEGORIES[meta["category"]]
    # 記事が扱う実体を公式の場所へ結ぶ（題名・狙う語→about、本文→mentions）
    about, mentions = entities.about_and_mentions(
        f"{meta.get('title', '')} {meta.get('keyword', '')}", re.sub(r"<[^>]+>", " ", body_text or ""))
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
                       "jobTitle": AUTHOR_ROLE, "sameAs": AUTHOR_SAME_AS,
                       "worksFor": organization()},
            "editor": {"@type": "Person", "name": "原口 優", "jobTitle": "代表取締役",
                       "url": f"{SITE_URL}/author/haraguchi/", "sameAs": AUTHOR_SAME_AS},
            "publisher": organization(),
            "inLanguage": "ja",
            **({"about": about} if about else {}),
            **({"mentions": mentions} if mentions else {}),
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
    steps = howto_steps(body_text or "")
    if steps:
        graph.append({
            "@type": "HowTo",
            "name": meta["title"],
            "description": meta["description"],
            "inLanguage": "ja",
            "step": steps,
        })
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


def datasets_box(meta):
    """同じカテゴリの一次データへの枠。AIが引用するのは「そこにしか無い数字」なので、記事から必ず辿れるようにする"""
    try:
        import data_intake
        items = [d for d in data_intake.load_all() if meta["category"] in d.get("categories", [])][:3]
    except Exception:
        return ""
    if not items:
        return ""
    import html as _h
    lis = "".join(f'<li><a href="/data/{d["slug"]}/">{_h.escape(d["title"])}</a>（母数{d["n"]:,}{_h.escape(d["n_unit"])}・{_h.escape(d["period"])}）</li>' for d in items)
    return f'<section class="related datasets"><h2>自社の一次データ</h2><ul>{lis}</ul></section>'


def industry_box(meta, all_metas):
    """同じ業種の記事へつなぐ。手法の軸だけだと、読者は自分の業種の全体像に届かない"""
    try:
        import industry_hub
        return industry_hub.box(meta, all_metas, CATEGORIES)
    except Exception:
        return ""


def related_html(meta, all_metas):
    same = [m for m in all_metas if m["slug"] != meta["slug"] and m["category"] == meta["category"]]
    others = [m for m in all_metas if m["slug"] != meta["slug"] and m["category"] != meta["category"]]
    picks = (same + others)[:3]
    head = industry_box(meta, all_metas) + datasets_box(meta)
    if not picks:
        return head
    tiles = "\n".join(post_tile(m) for m in picks)
    return (head + '<section class="related"><h2>あわせて読みたい関連記事</h2>'
            f'<ul class="post-list">\n{tiles}\n  </ul></section>')


# カテゴリ連動の記事末診断バナー（読者→診断→85点以下は無料相談へ、のリード導線）
DIAG_BANNERS = {
    "meo": ("/diagnosis/meo/", "マップ集客の整備度チェック（無料・30秒）", "8つの質問で、Googleマップ集客の整備度を100点満点で採点します。"),
    "aio": ("/diagnosis/aio/", "AI検索の対応度チェック（無料・30秒）", "AI検索に引用される準備ができているかを100点満点で採点します。"),
    "seo": ("/site-audit/", "サイト無料採点（URL入力だけ）", "SEO・AI対応の技術12項目を100点満点で自動チェックします。"),
    "ai-marketing": ("/diagnosis/aio/", "AI検索の対応度チェック（無料・30秒）", "AI検索に引用される準備ができているかを100点満点で採点します。"),
}


def insert_mid_cta(content, meta):
    """本文の中盤にCTAを1つ差し込む。

    記事末（本文の9割地点）のCTAだけだと、そこまで到達した読者しか見られない。
    実測では、記事67本からのCTA押下が月2回しか発生していなかった。
    読み終える前に離脱する読者のほうが多いので、途中にも置く。

    差し込む位置はH2の切れ目。段落の途中に入れると読みを断ち切る。
    """
    import re as _re
    heads = [m.start() for m in _re.finditer(r"<h2[ >]", content)]
    if len(heads) < 5:
        return content        # 見出しが少ない記事は末尾だけでよい
    pos = heads[len(heads) // 2]
    href, title, _ = DIAG_BANNERS.get(meta["category"], ("/lp/", "無料相談", ""))
    cta = (f'<section class="cta cta-mid">'
           f'<p class="cta-copy">ここまでの内容を、自社に当てはめて確認しませんか。</p>'
           f'<a class="btn btn-primary" href="{href}" '
           f'data-cta="article_mid_{meta["category"]}">{title} '
           f'<span class="arw">→</span></a>'
           f'<p class="cta-sub">読みながらでも1分で終わります</p></section>' + "\n")
    return content[:pos] + cta + content[pos:]


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


def _video_embed(content, meta):
    """YouTube に上がった記事動画があれば、本文の先頭に埋め込む（VideoObject つき）"""
    try:
        import video_embed
        content = video_embed.prepend(content, meta)
    except Exception as e:
        print(f"WARN: 動画の埋め込みを飛ばしました（{str(e)[:40]}）")
    return _topic_box(_glossary_links(content, meta), meta)


_I18N = None


def _html_escape(s):
    import html as _hm
    return _hm.escape(str(s))


def _i18n():
    """訳した要約（data/i18n/<lang>/<slug>.json）。{lang: {slug: {...}}}"""
    global _I18N
    if _I18N is None:
        try:
            import i18n
            import sites as S
            # 指示のある言語だけ。sites/<id>.json に languages が無ければ多言語ページも hreflang も出さない
            langs = i18n.langs_for(S.primary())
            _I18N = {lg: docs for lg, docs in i18n.translated().items() if lg in langs} if langs else {}
        except Exception:
            _I18N = {}
    return _I18N


def _i18n_live():
    """訳のうち、今回公開する記事の分だけ（カテゴリも一致するもの）。

    訳は data/i18n に残り続けるため、止めた記事・カテゴリを移した記事の訳から
    /en/<cat>/<slug>/ を作ると、存在しない日本語ページを指す要約が並ぶ
    """
    if _LIVE is None:
        return _i18n()
    return {lg: {s: d for s, d in docs.items()
                 if s in _LIVE and d.get("category") == _LIVE[s]["category"]}
            for lg, docs in _i18n().items()}


def _hreflang(meta):
    """日本語の記事の head に、訳した要約ページへの hreflang を足す（訳がある言語だけ）"""
    slug, cat = meta.get("slug", ""), meta.get("category", "")
    langs = [lg for lg, d in _i18n_live().items() if slug in d]
    if not langs:
        return ""
    ja = f"{SITE_URL}/{cat}/{slug}/"
    tags = [f'<link rel="alternate" hreflang="ja" href="{ja}">', f'<link rel="alternate" hreflang="x-default" href="{ja}">']
    tags += [f'<link rel="alternate" hreflang="{ {"en": "en", "zh": "zh-Hans", "ko": "ko"}[lg] }" href="{SITE_URL}/{lg}/{cat}/{slug}/">'
             for lg in langs]
    return "\n" + "\n".join(tags)


_TOPIC_GROUPS = None
# 今回の描画で公開する記事 {slug: meta}。テーマの箱・用語集リンク・訳のページは、
# ここに無い記事（観点の足切り・監修待ち・品質NGで止めた記事）を指してはいけない
_LIVE = None


def _set_live(metas):
    """描画する記事の集合を切り替え、それをもとに作ったキャッシュを捨てる。
    止めた記事が出たあとの2回目の描画で、1回目の束ね・用語を使い回さないため"""
    global _LIVE, _TOPIC_GROUPS, _TERMS
    _LIVE = {m["slug"]: m for m in metas}
    _TOPIC_GROUPS = None
    _TERMS = None


def _topic_box(content, meta):
    """記事末に「このテーマの記事」（ピラーへのリンク＋兄弟3本）。相互リンクが機械で揃う"""
    global _TOPIC_GROUPS
    try:
        import topics as TP
        import sites as S
        if _TOPIC_GROUPS is None:
            # /topics/ のページ（build_extra_pages）と同じ記事の集合で束ねる
            _TOPIC_GROUPS = TP.build(S.primary(), list((_LIVE or {}).values()))
        box = TP.box_html(meta, _TOPIC_GROUPS, lambda m: f"/{m['category']}/{m['slug']}/")
        if not box:
            return content
        # FAQ（よくある質問）の直前に置く。無ければ末尾
        i = content.find("<h2")
        j = content.rfind("よくある質問")
        pos = content.rfind("<h2", 0, j) if (j != -1 and i != -1) else -1
        return content[:pos] + box + content[pos:] if pos > 0 else content + box
    except Exception as e:
        print(f"WARN: テーマの箱を飛ばしました（{str(e)[:40]}）")
        return content


_TERMS = None


def _glossary_links(content, meta):
    """定義ブロックの用語を用語集（/glossary/）へリンクする。内部リンクが機械で増える"""
    global _TERMS
    try:
        import glossary as GL
        import sites as S
        if _TERMS is None:
            _TERMS = {r["term"]: r for r in GL.collect(S.primary(), None if _LIVE is None else set(_LIVE))}
        if len(_TERMS) < 10:
            return content
        return GL.link_terms(content, _TERMS, self_slug=meta.get("slug", ""))
    except Exception as e:
        print(f"WARN: 用語集リンクを飛ばしました（{str(e)[:40]}）")
        return content


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

    # 記事のCTAをA/Bテストの対象にする。
    # 記事を見た544件に対しCTAのクリックは38件で、3サイトとも同じ段階で落ちている。
    # どの文言なら押されるかは推測では決まらないため、半々で出し分けて実測する。
    # 文言は記事ごとに書かず、ここで一括して当てる（350箇所を手で直さないため）。
    content = re.sub(
        r'(<a\s+class="cta-button"(?![^>]*data-ab))',
        r'\1 data-ab="article_cta" data-ab-b="自社サイトの現状分析を無料でもらう"',
        content)

    # マーカー数チェック（自動生成記事の装飾漏れ検出。基準: 8箇所以上、推奨12-18）
    marker_count = content.count("<strong>") + content.count("<mark>")
    if marker_count < 8:
        QUALITY_ISSUES.setdefault(meta["slug"], []).append(
            f"マーカー不足（強調{marker_count}箇所・基準8以上）")
        print(f"WARN: マーカー不足: {meta['slug']} は強調が{marker_count}箇所"
              f"（基準8箇所以上・推奨12-18箇所。**太字** か ==マーカー== を追加すること）")

    # リード導線チェック。読んで納得した人の行き先が無いと、記事はそこで終わる。
    # 実際、コーポレートは88本中75本に行き先が無く、記事からの反応がゼロだった。
    # 自己診断・サイト診断・問い合わせのどれか1つは必ず本文に置く。
    if not re.search(r"/diagnosis/|/site-audit/|#diagnosis|/contact|/lp/", content):
        QUALITY_ISSUES.setdefault(meta["slug"], []).append("リード導線なし")
        print(f"WARN: リード導線なし: {meta['slug']} には無料診断・問い合わせのリンクが"
              f"ありません（python scripts/tool_links.py --write で入ります）")

    # CTAの本数。CLAUDE.md は「最低2箇所」と決めているのに検査が無く、
    # 公開136本のうち59本（43%）が2箇所未満だった（2026-09-23 実測）。
    # 別工程の採点でも、デザイン観点が11本中11本で足切りになった主因がこれ。
    # 読み終えた人の行き先が1つしか無い記事は、そこで離脱する
    n_cta = content.count("cta-button")
    if n_cta < 2:
        QUALITY_ISSUES.setdefault(meta["slug"], []).append(
            f"CTAが{n_cta}箇所（基準2箇所以上）")
        print(f"WARN: CTA不足: {meta['slug']} は{n_cta}箇所"
              f"（基準2箇所以上。python scripts/tool_links.py --write で入ります）")

    # 文字数チェック（タグ・空白を除いた実文字数で判定）
    # 基準は depth で変わる。全記事を同じ長さに揃えると、それ自体が量産の指紋になる。
    # 一律5,000字で見ていたため、手順や定義だけの quick 記事を誤って警告していた。
    plain = re.sub(r"<[^>]+>", "", content)
    plain = re.sub(r"\s", "", plain)
    need = {"quick": 3000, "standard": 5000, "deep": 8000}.get(
        str(meta.get("depth") or "standard"), 5000)
    if len(plain) < need:
        QUALITY_ISSUES.setdefault(meta["slug"], []).append(
            f"文字数不足（{len(plain):,}字・基準{need:,}字）")
        print(f"WARN: 文字数不足: {meta['slug']} は本文{len(plain):,}字"
              f"（depth: {meta.get('depth') or 'standard'} の基準{need:,}字以上。"
              f"セクション追加・実務情報の深掘りで増強すること）")

    # タグの対応チェック。数が合っていても入れ子が壊れていれば見つからないため、
    # 開始タグを積んで照合する。生成の作業タグ（</content> など）が原稿の末尾に
    # 残っていたことがあり、そのまま公開HTMLに出ていた。
    _VOID = {"br", "img", "hr", "input", "meta", "link", "source", "col",
             "area", "base", "embed", "wbr", "track", "param"}
    _src = re.sub(r"```.*?```", "", content, flags=re.S)
    _stack, _bad = [], []
    for _m in re.finditer(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*?)(/?)>", _src):
        _close, _name, _self = _m.group(1), _m.group(2).lower(), _m.group(4)
        if _name in _VOID or _self:
            continue
        if not _close:
            _stack.append(_name)
        elif _stack and _stack[-1] == _name:
            _stack.pop()
        elif _name in _stack:
            while _stack and _stack[-1] != _name:
                _bad.append(f"<{_stack.pop()}> が閉じられていない")
            _stack.pop()
        else:
            _bad.append(f"</{_name}> に対応する開始タグが無い")
    _bad += [f"<{t}> が閉じられていない" for t in _stack]
    for _b in _bad[:4]:
        print(f"WARN: タグの対応が取れていない: {meta['slug']} → {_b}")

    # 画像実在チェック（生成漏れ・パスtypoの検出。生成: python scripts/make_images.py <slug>）
    if meta.get("eyecatch") and not (SITE / meta["eyecatch"].lstrip("/")).exists():
        print(f"WARN: アイキャッチ未生成: {meta['slug']} → {meta['eyecatch']}")
    for src in sorted(set(re.findall(r'<img src="(/images/[^"]+)"', content))):
        if not (SITE / src.lstrip("/")).exists():
            print(f"WARN: 本文画像が存在しない: {meta['slug']} → {src}")

    eyecatch = ""
    if meta.get("eyecatch"):
        # アイキャッチは最初に見える最大の要素（LCP）。優先して読む
        eyecatch = (f'<figure class="article-eyecatch"><img src="{meta["eyecatch"]}" '
                    f'alt="{meta["title"]}" width="1200" height="675" fetchpriority="high" decoding="async"></figure>')
    # 本文の画像は画面に入るまで読まない（モバイルで1.5MB超を先に運んでいた）
    content = re.sub(r'<img src="(/images/[^"]+)"(?![^>]*\bloading=)', r'<img src="\1" loading="lazy" decoding="async"', content)

    html = template
    replacements = {
        "{{TITLE}}": meta["title"],
        "{{TITLE_SHORT}}": meta["title"][:22],
        "{{DESCRIPTION}}": meta["description"],
        "{{CANONICAL}}": url,
        "{{OG_IMAGE}}": SITE_URL + meta.get("eyecatch", "/images/ogp-default.png"),
        "{{SITE_NAME}}": SITE_NAME,
        "{{NAV}}": _nav("nav", NAV_DEFAULT),
        "{{FOOTER_NAV}}": _nav("footer_nav", FOOTER_NAV_DEFAULT),
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
        "{{HOW_MADE}}": how_made(meta["slug"]),
        "{{JSON_LD}}": build_json_ld(meta, url, content),
        "{{TOC}}": render_toc(toc_tokens),
        "{{EYECATCH}}": eyecatch,
        "{{CONTENT}}": insert_mid_cta(_video_embed(content, meta), meta),
        "{{RELATED}}": related,
        "{{DIAG_BANNER}}": diag_banner_html(meta),
        "{{PREVNEXT}}": prevnext,
        "{{TITLE_ENC}}": urlquote(meta["title"]),
        "{{URL_ENC}}": urlquote(url, safe=""),
    }
    for k, v in replacements.items():
        html = html.replace(k, v)
    # 訳した要約ページへの hreflang は head の末尾に置く（JSON-LD の中に入れると parse が壊れる。
    # 実測: 1記事の JSON-LD が「Extra data」で壊れた）
    alt = _hreflang(meta)
    if alt:
        html = html.replace("</head>", alt + "\n</head>", 1)

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


# 記事ごとの品質不合格。印字するだけでは公開を止められないため、ここに集める。
# 「まだ公開していない記事」だけを止める（公開済みを取り下げると順位を失う）
QUALITY_ISSUES = {}
PUBLISHED_LEDGER = ROOT / "data" / "published.json"


def published_slugs():
    """これまでに公開した記事。初回は空を返さず、今ある記事で台帳を作る"""
    import json
    if PUBLISHED_LEDGER.is_file():
        try:
            return set(json.loads(PUBLISHED_LEDGER.read_text(encoding="utf-8")))
        except Exception:
            return None
    return None                      # 台帳が無い＝初回。今回は何も止めない


def save_published(slugs):
    import json
    PUBLISHED_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    PUBLISHED_LEDGER.write_text(
        json.dumps(sorted(slugs), ensure_ascii=False, indent=1),
        encoding="utf-8", newline="\n")


def title_has_keyword(title, kw):
    """狙う語がタイトルに入っているか。助詞と記号の違いは同じ語とみなす。

    実測（2026-09-23）で、記事全体が「AIかんたん集客」で書かれているのに
    タイトルだけ「AI集客とは？」の記事があり、表示88回を取りこぼしていた。
    検索結果に出るのはタイトルなので、ここが外れると順位があっても選ばれない。
    """
    if not kw:
        return True
    # 自然文の狙う語（AI検索でそのまま聞かれる形）は、タイトルに丸ごと入れない。
    # 「大阪でmeoとaioの両方を支援してくれる会社を教えてください。」のような語を
    # タイトルに要求すると、読みにくい見出しを強いることになる
    import re as _re
    if (_re.search(r"[？?。]$|教えて|ですか|ください|したい|おすすめの", kw)
            or (len(kw) >= 14 and " " not in kw and "　" not in kw)):
        return True
    drop = "\u3000・･／/（）()｜|【】[]「」、。,.-‐－—ー_ のをにはがともへやかでるな？?！!"
    def norm(s):
        return re.sub(r"\s", "", s.lower().translate({ord(c): None for c in drop}))
    lt, nt, nk = title.lower(), norm(title), norm(kw)
    parts = [w for w in re.split(r"[\s\u3000]+", kw) if len(w) >= 2]
    if any(w.lower() in lt for w in parts):
        return True
    if nk and nk in nt:
        return True
    toks = [x for x in re.split(r"[\s\u3000]+", kw) if len(x) >= 2]
    if not toks:
        return True
    return sum(1 for x in toks if norm(x) in nt) / len(toks) >= 0.7


def quality_checks(all_metas):
    """第6章 SEO実装詳細の機械検査: メタ品質 + カニバリ(タイトル類似80%)ゲート"""
    import difflib
    warns = []
    for m in all_metas:
        # 図解のflow型は描画が5項目までで、6個目以降は黙って切り捨てられる。
        # 本文やタイトルが「6ステップ」と言っているのに図は5つ、というずれが実際に起きた
        for dg in (m.get("diagrams") or []):
            if isinstance(dg, dict) and (dg.get("type") or "flow") == "flow":
                items = dg.get("items") or []
                if len(items) > 5:
                    warns.append(f"図解の項目が多すぎ: {m['slug']} の「{dg.get('title', '')}」は"
                                 f"{len(items)}項目（flow型は5項目まで。6個目以降は画像に出ない）")
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

    # 狙う語の重複。タイトル類似だけでは通り抜ける（実際、タイトルは似ていないのに
    # 同じ語を狙って51語・表示484回・クリック0になった記事があった）。
    # 「aio 診断」と「aio診断」は検索エンジンには同じに見えるので、表記ゆれを吸収して比べる。
    import re as _re
    _n = lambda s: _re.sub(r"[\s　・|｜:：\-—?？!！。、,.／/（）()【】\[\]]", "", str(s)).lower()
    bykw = {}
    for m in all_metas:
        k = _n(m.get("keyword", ""))
        if k:
            bykw.setdefault(k, []).append(m["slug"])
    for k, slugs in bykw.items():
        if len(slugs) > 1:
            warns.append(f"カニバリ: 同じ狙う語を{len(slugs)}記事が持っている「{k}」 → "
                         + " / ".join(slugs) + "（1語1記事。統合するか語をずらす）")
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


def prefix_link_check():
    """他サイト（/blog/<slug>/ で配信する社）の原稿に、カテゴリ形式の内部リンクが無いか。

    上の link_check は当サイトの出力しか見ないため、配信先で404になるリンクが素通りしていた
    （実際に81本が /hojokin/ や /keiri-bpo/ の形で入っていた）
    """
    import sites as sites_mod
    warns = []
    for p in sorted(ARTICLES.glob("*.md")):
        src = article_site(p)
        pre = (sites_mod.load_all().get(src) or {}).get("url_prefix") if src else None
        if not pre:
            continue
        t = p.read_text(encoding="utf-8")
        for seg, slug in re.findall(r"\]\(/([a-z0-9-]+)/([a-z0-9-]+)/?(?:#[^)\s]*)?\)", t):
            if seg != pre.strip("/") and sites_mod.find_category_owner(seg) == src:
                warns.append(f"配信先で404: {p.stem} → /{seg}/{slug}/（{pre}/{slug}/ に直す）")
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
    # 一次データのページ（data_intake.py が作る）。固定の一覧に無くても拾う
    for d in sorted((SITE / "data").glob("*/index.html")):
        lines.append(f"  <url><loc>{SITE_URL}/data/{d.parent.name}/</loc><lastmod>{today}</lastmod></url>")
    # 業種ハブ（industry_hub.py が作る）
    for d in sorted((SITE / "industry").glob("*/index.html")):
        lines.append(f"  <url><loc>{SITE_URL}/industry/{d.parent.name}/</loc><lastmod>{today}</lastmod></url>")
        if (d.parent / "faq" / "index.html").is_file():      # 業種×よくある質問
            lines.append(f"  <url><loc>{SITE_URL}/industry/{d.parent.name}/faq/</loc><lastmod>{today}</lastmod></url>")
    if (SITE / "industry" / "index.html").is_file():
        lines.append(f"  <url><loc>{SITE_URL}/industry/</loc><lastmod>{today}</lastmod></url>")
    # 用語集・比較表（build_extra_pages が作る）
    for top in ("glossary", "compare", "topics", "area"):
        if (SITE / top / "index.html").is_file():
            lines.append(f"  <url><loc>{SITE_URL}/{top}/</loc><lastmod>{today}</lastmod></url>")
        for d in sorted((SITE / top).glob("*/index.html")):
            lines.append(f"  <url><loc>{SITE_URL}/{top}/{d.parent.name}/</loc><lastmod>{today}</lastmod></url>")
    # 多言語の要約ページ（/en/ /zh/ /ko/）
    for lg in ("en", "zh", "ko"):
        if (SITE / lg / "index.html").is_file():
            lines.append(f"  <url><loc>{SITE_URL}/{lg}/</loc><lastmod>{today}</lastmod></url>")
        for d in sorted((SITE / lg).glob("*/*/index.html")):
            lines.append(f"  <url><loc>{SITE_URL}/{lg}/{d.parent.parent.name}/{d.parent.name}/</loc><lastmod>{today}</lastmod></url>")
    for meta, url in article_entries:
        lines.append(f"  <url><loc>{url}</loc><lastmod>{meta['modified']}</lastmod></url>")
    lines.append("</urlset>")
    (SITE / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")


BLOG_PAGE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h1}｜{site}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}/blog/">
<meta name="theme-color" content="#071a38">
<meta property="og:type" content="website">
<meta property="og:locale" content="ja_JP">
<meta property="og:title" content="{h1}｜{site}">
<meta property="og:url" content="{url}/blog/">
<meta property="og:site_name" content="{site}">
<link rel="icon" type="image/png" href="/images/icon-192.png">
<link rel="apple-touch-icon" href="/images/icon-180.png">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="alternate" type="application/atom+xml" title="{site} 新着記事" href="/feed.xml">
<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}gtag('js',new Date());gtag('config','G-X6KNN36L9J');
/* 計測タグ(172KB)は描画の後に読む。先に読むと文字が出るのが遅れる。それまでの出来事は dataLayer に溜まり、読み込み後にまとめて送られる */
window.addEventListener('load',function(){{setTimeout(function(){{var s=document.createElement('script');s.async=true;s.src='https://www.googletagmanager.com/gtag/js?id=G-X6KNN36L9J';document.head.appendChild(s);}},1200);}});</script>
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
{nav}
    </nav>
  </div>
</header>

<nav class="breadcrumb" aria-label="パンくずリスト">
  <ol>
    <li><a href="/">ホーム</a></li>
    <li aria-current="page">{h1}</li>
  </ol>
</nav>

<section class="hero">
  <span class="kicker">All Articles</span>
  <h1>{h1}</h1>
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
    <p class="cta-copy">{cta_copy}</p>
    <a class="btn btn-primary" href="{cta_url}">{cta_label} <span class="arw">→</span></a>
    <p class="cta-sub">{cta_sub}</p>
  </div>
</section>

<footer class="site-footer">
  <div class="inner">
    <div>
      <img class="footer-logo" src="/images/company/logo-white.png" alt="Seven Senses セブンセンシズ株式会社" width="371" height="147" loading="lazy">
      <div class="brand-f">{site}</div>
      <p style="font-size:.8rem;color:rgba(255,255,255,.6);margin:.5em 0 0;">AIに選ばれる集客を、実務からつくる。</p>
      <p class="addr">運営: セブンセンシズ株式会社<br>〒537-0003 大阪府大阪市東成区神路1丁目7-4 コンフォートビル901・902</p>
      <ul class="social-links" aria-label="外部プロフィール"><li><a href="https://www.linkedin.com/in/yu-haraguchi" target="_blank" rel="noopener me" aria-label="LinkedIn（原口 優）" data-net="linkedin"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false" fill="currentColor"><path d="M20.45 20.45h-3.56v-5.57c0-1.33-.03-3.04-1.85-3.04-1.86 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.47-.9 1.63-1.85 3.36-1.85 3.6 0 4.27 2.37 4.27 5.45v6.29zM5.34 7.43a2.07 2.07 0 1 1 0-4.14 2.07 2.07 0 0 1 0 4.14zM7.12 20.45H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.72V1.72C24 .77 23.2 0 22.22 0z"/></svg></a></li><li><a href="https://note.com/yu_haraguchi" target="_blank" rel="noopener me" aria-label="note（原口 優）" data-net="note"><span>note</span></a></li></ul>
    </div>
    <nav aria-label="フッターナビゲーション">
{footer_nav}
    </nav>
    <div class="copyright">© 2026 Seven Senses Inc. All rights reserved.</div>
  </div>
</footer>

</body>
</html>
"""


def page_shell(h1="記事一覧", desc=""):
    """BLOG_PAGE に渡す外枠の値。h1 は title・og:title・パンくずにも入る。

    業種・用語集・テーマなどもこの外枠を使うため、h1 と説明を渡さないと
    どのページも見出しが「記事一覧」になる
    """
    desc = re.sub(r"\s+", " ", str(desc or "")).strip()
    if len(desc) > 120:                  # 文の途中で切らない（120字以内の最後の「。」まで）
        cut = desc[:120].rfind("。")
        desc = desc[:cut + 1] if cut >= 40 else desc[:120]
    desc = desc or (
        f"{SITE_NAME}の全記事一覧。AIO・LLMO・SEO・MEOの実践ノウハウを新着順に掲載しています。")
    return dict(site=SITE_NAME, url=SITE_URL, nav=_nav("nav", NAV_DEFAULT),
                footer_nav=_nav("footer_nav", FOOTER_NAV_DEFAULT),
                h1=_html_escape(h1), desc=_html_escape(desc), **_cta())


def hub_json_ld(name, url, metas, desc=""):
    """業種ハブの構造化データ。何の集まりで、何が入っているかを機械に渡す"""
    items = [{"@type": "ListItem", "position": i + 1,
              "url": f"{SITE_URL}/{m['category']}/{m['slug']}/",
              "name": m["title"]}
             for i, m in enumerate(metas[:30])]
    graph = [
        {"@type": "CollectionPage", "name": name, "url": url,
         "inLanguage": "ja",
         **({"description": desc} if desc else {}),
         "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": SITE_URL},
         "publisher": organization(),
         "mainEntity": {"@type": "ItemList", "numberOfItems": len(metas),
                        "itemListElement": items}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "業種から探す",
             "item": f"{SITE_URL}/industry/"},
            {"@type": "ListItem", "position": 3, "name": name, "item": url}]},
    ]
    return ('<script type="application/ld+json">'
            + json.dumps({"@context": "https://schema.org", "@graph": graph},
                         ensure_ascii=False, indent=1)
            + "</script>")


def build_industry_hubs(all_metas):
    """業種ハブ（/industry/ と /industry/<slug>/）。記事が増えるほど厚くなる"""
    try:
        import industry_hub as IH
    except Exception as e:
        print(f"WARN: 業種ハブを作れません（{str(e)[:50]}）")
        return []
    pairs, g = IH.live(all_metas)
    made = []
    for ind, metas in pairs:
        out = SITE / "industry" / ind["slug"] / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        page = BLOG_PAGE.format(items=IH.hub_body(ind, metas, CATEGORIES, post_tile), **page_shell(
            f'{ind["name"]}の集客', ind.get("lead") or f'{ind["name"]}の集客に役立つ記事をまとめています。'))
        page = page.replace(f"{SITE_URL}/blog/", f'{SITE_URL}/industry/{ind["slug"]}/')
        url = f'{SITE_URL}/industry/{ind["slug"]}/'
        page = page.replace("</head>", hub_json_ld(
            f'{ind["name"]}の集客', url, metas, str(ind.get("lead") or "")[:300]) + "</head>", 1)
        made.append((ind, metas))
        out.write_text(page, encoding="utf-8", newline="\n")
        # 業種×よくある質問（/industry/<slug>/faq/）。記事の FAQ を集めるだけで、
        # 質問形のクエリ（AI Overview 表示率64.7%）に答える面が増える
        fq = IH.faq_body(ind, metas, lambda m: f"{SITE_URL}/{m['category']}/{m['slug']}/")
        if fq:
            import json as _json
            fhtml, fld = fq
            fo = SITE / "industry" / ind["slug"] / "faq" / "index.html"
            fo.parent.mkdir(parents=True, exist_ok=True)
            fpage = BLOG_PAGE.format(items=fhtml, **page_shell(
                f'{ind["name"]}のよくある質問',
                f'{ind["name"]}の集客について、記事で答えたよくある質問をまとめています。'))
            fpage = fpage.replace(f"{SITE_URL}/blog/", f'{SITE_URL}/industry/{ind["slug"]}/faq/')
            fpage = fpage.replace("</head>", '<script type="application/ld+json">'
                                  + _json.dumps(fld, ensure_ascii=False) + "</script></head>", 1)
            fo.write_text(fpage, encoding="utf-8", newline="\n")
    if made:
        out = SITE / "industry" / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        page = BLOG_PAGE.format(items=IH.index_body(pairs, g), **page_shell(
            "業種から探す", "業種ごとに、集客・MEO・AIO・SEOの記事をまとめています。"))
        page = page.replace(f"{SITE_URL}/blog/", f"{SITE_URL}/industry/")
        flat = [m for _, ms in pairs for m in ms]
        page = page.replace("</head>", hub_json_ld(
            "業種から探す", f"{SITE_URL}/industry/", flat,
            "業種ごとに、集客・MEO・AIO・SEOの記事をまとめています。") + "</head>", 1)
        out.write_text(page, encoding="utf-8", newline="\n")
    # llms.txt に業種の目次を出す。AIクローラーはここを読んで全体像を掴む
    lt = SITE / "llms.txt"
    if made and lt.is_file():
        head = "## 業種から探す"
        body = "\n".join(
            f'- [{i["name"]}の集客]({SITE_URL}/industry/{i["slug"]}/): '
            f'{i["lead"].split("。")[0]}。（{len(v)}本）' for i, v in made)
        t = lt.read_text(encoding="utf-8")
        block = f"{head}\n{body}\n"
        if head in t:
            t = re.sub(rf"{head}\n(?:- .*\n)*", block, t, count=1)
        else:
            t = t.replace("## 主要ページ", block + "\n## 主要ページ", 1)
        lt.write_text(t, encoding="utf-8", newline="\n")
    print(f"業種ハブ: {len(made)}件（{'、'.join(i['name'] for i, _ in made)}）")
    return made


def build_extra_pages(all_metas):
    """用語集（/glossary/）・比較表（/compare/）・診断レコメンド（/data/reco.json）。

    どれも記事にあるものを集めるだけで、新しい文は作らない。記事が増えるほど厚くなる。
    """
    import json as _json
    try:
        import glossary as GL
        import compare_pages as CP
        import sites as S
    except Exception as e:
        print(f"WARN: 用語集・比較表を作れません（{str(e)[:50]}）")
        return
    sid = S.primary()
    # 実際に公開する記事だけを出典にする（止めた記事の用語・表を載せると404へリンクする）
    only = {m["slug"] for m in all_metas}

    made_paths = set()

    def page(path, items, title, url, desc=""):
        out = SITE / path / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        p = BLOG_PAGE.format(items=items, **page_shell(title, desc or f"{SITE_NAME}の「{title}」のページです。"))
        p = p.replace(f"{SITE_URL}/blog/", url)
        out.write_text(p, encoding="utf-8", newline="\n")
        made_paths.add(out.parent)

    def sweep():
        """今回作らなかった古いページを消す。残すと sitemap に載り続け、主題が変わった
        テーマページが並ぶ（実測: 5テーマなのに14ページ残った）"""
        import shutil
        for top in ("glossary", "compare", "topics", "area"):
            base = SITE / top
            if not base.is_dir():
                continue
            for d in base.iterdir():
                if d.is_dir() and d not in made_paths and (d / "index.html").is_file():
                    shutil.rmtree(d, ignore_errors=True)
            if base not in made_paths and (base / "index.html").is_file():
                shutil.rmtree(base, ignore_errors=True)
        # 多言語の要約ページは、指示のある言語以外を残さない（指示が外れたら消える）
        for lg in ("en", "zh", "ko"):
            base = SITE / lg
            if base.is_dir() and lg not in _i18n():
                shutil.rmtree(base, ignore_errors=True)
            elif base.is_dir():
                # 指示のある言語でも、公開しなくなった記事の要約（/en/<cat>/<slug>/）は残さない
                for d in base.glob("*/*/index.html"):
                    if d.parent not in made_paths:
                        shutil.rmtree(d.parent, ignore_errors=True)
                if base not in made_paths and (base / "index.html").is_file():
                    (base / "index.html").unlink()

    # 用語集
    terms = GL.collect(sid, only)
    if len(terms) >= 10:
        for r in terms:
            page(f"glossary/{r['id']}", GL.term_html(r, f"{SITE_URL}/{r['category']}/{r['slug']}/"),
                 f"{r['term']}とは", f"{SITE_URL}/glossary/{r['id']}/", f"{r['term']}とは、{r['definition']}")
        page("glossary", GL.index_html(terms), "用語集", f"{SITE_URL}/glossary/",
             f"{SITE_NAME}の記事で定義した用語{len(terms)}語を1か所に集めた用語集です。")
        print(f"用語集: {len(terms)}語")
    # 比較表
    cats = CP.collect(sid, only)
    made = []
    for cat, rows in cats.items():
        if len(rows) < 3 or cat not in CATEGORIES:
            continue
        name = CATEGORIES[cat][0]
        page(f"compare/{cat}", CP.page_html(name, rows, lambda r, c=cat: f"{SITE_URL}/{c}/{r['slug']}/"),
             f"{name}の比較表", f"{SITE_URL}/compare/{cat}/",
             f"{name}の記事にある比較表{len(rows)}表を1か所に集めました。")
        made.append((cat, name, len(rows)))
    if made:
        page("compare", CP.index_html(made), "比較表から探す", f"{SITE_URL}/compare/",
             "記事の比較表をカテゴリごとに集め、違いと費用を見比べられる入口です。")
        print(f"比較表: {', '.join(f'{n}{c}表' for _, n, c in made)}")
    # テーマ（ピラー↔クラスター）。主題ごとに「まず読む1本」と掘り下げる記事を束ねる
    groups = []
    try:
        import topics as TP
        groups = TP.build(sid, all_metas)
        for g in groups:
            page(f"topics/{g['slug']}", TP.page_html(g, lambda m: f"{SITE_URL}/{m['category']}/{m['slug']}/"),
                 f"{g['name']}の記事", f"{SITE_URL}/topics/{g['slug']}/",
                 f"テーマ「{g['name']}」の記事{len(g['members'])}本。まず読む1本は「{g['pillar']['title']}」です。")
        if groups:
            page("topics", TP.index_html(groups), "テーマから探す", f"{SITE_URL}/topics/",
                 "同じ主題の記事を束ね、まず読む1本と掘り下げる記事に分けたテーマの一覧です。")
            print(f"テーマ: {len(groups)}件（{', '.join(g['name'] for g in groups[:6])}…）")
    except Exception as e:
        print(f"WARN: テーマの束ねを飛ばしました（{str(e)[:50]}）")
    # エリアハブ（/area/<slug>/）。訪日客は業種より先にエリアで探す。5本たまったエリアだけ
    area_pairs = []
    try:
        import area_hub as AH
        area_pairs, area_g = AH.live(all_metas)
        for a, ms in area_pairs:
            page(f"area/{a['slug']}", AH.page_html(a, ms, lambda m: f"{SITE_URL}/{m['category']}/{m['slug']}/"),
                 f"{a['name']}の記事", f"{SITE_URL}/area/{a['slug']}/",
                 f"{a['name']}に関する記事{len(ms)}本をまとめています。")
        if area_pairs:
            page("area", AH.index_html(area_pairs, area_g), "エリアから探す", f"{SITE_URL}/area/",
                 "エリアごとに記事をまとめています。")
            print(f"エリアハブ: {len(area_pairs)}件（{'、'.join(a['name'] for a, _ in area_pairs)}）")
    except Exception as e:
        print(f"WARN: エリアハブを飛ばしました（{str(e)[:50]}）")
    # 多言語の要約ページ（/en/ /zh/ /ko/）。訳は i18n.py が週次で作る（ここでは置くだけ）
    n_i18n = 0
    try:
        import i18n as I18N
        lang_attr = {"en": "en", "zh": "zh-Hans", "ko": "ko"}
        live_i18n = _i18n_live()
        for lg, docs in live_i18n.items():
            if not docs:
                continue
            for slug, d in docs.items():
                cat = d.get("category", "")
                if cat not in CATEGORIES:
                    continue
                ja = f"{SITE_URL}/{cat}/{slug}/"
                path = f"{lg}/{cat}/{slug}"
                page(path, I18N.page_html(d, ja, lg), d["title"], f"{SITE_URL}/{path}/", d.get("description"))
                out = SITE / path / "index.html"
                t = out.read_text(encoding="utf-8")
                alts = [f'<link rel="alternate" hreflang="ja" href="{ja}">',
                        f'<link rel="alternate" hreflang="x-default" href="{ja}">'] + [
                    f'<link rel="alternate" hreflang="{lang_attr[o]}" href="{SITE_URL}/{o}/{cat}/{slug}/">'
                    for o in live_i18n if slug in live_i18n[o]]
                t = t.replace('<html lang="ja">', f'<html lang="{lang_attr[lg]}">', 1)
                t = t.replace("</head>", "\n".join(alts) + "\n</head>", 1)
                out.write_text(t, encoding="utf-8", newline="\n")
                n_i18n += 1
            names = {"en": "Articles in English", "zh": "中文文章", "ko": "한국어 기사"}
            lis = "".join(f'<li><a href="/{lg}/{d["category"]}/{s}/"><strong>{_html_escape(d["title"])}</strong>'
                          f'<span class="cnt">{str(d.get("date", ""))[:7]}</span></a></li>'
                          for s, d in sorted(docs.items(), key=lambda kv: str(kv[1].get("date", "")), reverse=True)
                          if d.get("category") in CATEGORIES)
            page(lg, f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>{names[lg]}</h2>'
                     f'<span class="cnt">{len(docs)}</span></div><ul class="hub-list">{lis}</ul></div>',
                 names[lg], f"{SITE_URL}/{lg}/")
            t = (SITE / lg / "index.html").read_text(encoding="utf-8").replace('<html lang="ja">', f'<html lang="{lang_attr[lg]}">', 1)
            (SITE / lg / "index.html").write_text(t, encoding="utf-8", newline="\n")
        if n_i18n:
            print(f"多言語の要約: {n_i18n}ページ")
    except Exception as e:
        print(f"WARN: 多言語ページを飛ばしました（{str(e)[:60]}）")
    sweep()
    # 入口が孤立しないように、業種の入口（/industry/・ナビから届く）から用語集・比較表・テーマへリンクする
    idx = SITE / "industry" / "index.html"
    if idx.is_file():
        links = "".join(f'<li><a href="/{top}/"><strong>{name}</strong><span class="cnt">{n}</span></a></li>'
                        for top, name, n in (("glossary", "用語集", f"{len(terms)}語" if len(terms) >= 10 else ""),
                                             ("compare", "比較表から探す", f"{len(made)}カテゴリ" if made else ""),
                                             ("topics", "テーマから探す", f"{len(groups)}テーマ" if groups else ""),
                                             ("area", "エリアから探す", f"{len(area_pairs)}エリア" if area_pairs else ""),
                                             ("en", "English", f"{len(_i18n_live().get('en', {}))}" if _i18n_live().get("en") else ""),
                                             ("zh", "中文", f"{len(_i18n_live().get('zh', {}))}" if _i18n_live().get("zh") else ""),
                                             ("ko", "한국어", f"{len(_i18n_live().get('ko', {}))}" if _i18n_live().get("ko") else ""))
                        if n)
        if links:
            t = idx.read_text(encoding="utf-8")
            block = ('<div class="latest-block" data-cat="new"><div class="cat-head"><h2>ほかの探し方</h2></div>'
                     f'<ul class="hub-list">{links}</ul></div>')
            if "ほかの探し方" not in t and '<footer class="site-footer">' in t:
                t = t.replace('<footer class="site-footer">', f'<section class="wrap">{block}</section>\n<footer class="site-footer">', 1)
                idx.write_text(t, encoding="utf-8", newline="\n")
    # 診断の自動返信が読む「弱い項目 → まず読む記事」（管制塔の GAS が UrlFetch で取る）
    reco = {}
    for kind, cat in (("meo", "meo"), ("ai", "ai-marketing"), ("aio", "aio"), ("seo", "seo")):
        ms = sorted([m for m in all_metas if m.get("category") == cat],
                    key=lambda m: str(m.get("date", "")), reverse=True)[:3]
        reco[kind] = [{"title": m["title"], "url": f"{SITE_URL}/{cat}/{m['slug']}/"} for m in ms]
    reco["hojokin"] = [{"title": "AI導入補助金の記事一覧", "url": "https://lp.7senses.co.jp/blog/"}]
    (SITE / "data").mkdir(exist_ok=True)
    (SITE / "data" / "reco.json").write_text(_json.dumps(reco, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


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
    out.write_text(BLOG_PAGE.format(items="\n".join(blocks), **page_shell()),
                   encoding="utf-8")


def sync_llms(entries):
    """llms.txt の記事の行を、今回公開する記事に合わせる。記事以外の行（業種・主要ページ・一次データ）は触らない。

    記事の行は公開時に足すだけで、止めた記事・原稿の無くなった記事の行が残り、
    AIクローラーに404を案内していた。タイトルを直した記事も古い題名のままだった
    """
    lt = SITE / "llms.txt"
    if not entries or not lt.is_file():
        return
    live = {url: meta for meta, url in entries}
    art = re.compile(r"^- \[(.*?)\]\((" + re.escape(SITE_URL) + r"/(?:"
                     + "|".join(re.escape(c) for c in CATEGORIES) + r")/[^/()\s]+/)\)(.*)$")
    t = lt.read_text(encoding="utf-8")
    out, dropped, renamed, have = [], [], 0, set()
    for ln in t.split("\n"):
        m = art.match(ln)
        if m and m.group(2) not in live:
            dropped.append(m.group(2))
            continue
        if m:
            have.add(m.group(2))
        if m and m.group(1) != live[m.group(2)]["title"]:
            ln = f'- [{live[m.group(2)]["title"]}]({m.group(2)}){m.group(3)}'
            renamed += 1
        out.append(ln)
    # 公開する記事で行が無いものを「## 主要コンテンツ」の末尾に足す。
    # 消すだけだと、監修待ち（HELD）で一度消えた行が承認の後も戻らない
    added = [f'- [{meta["title"]}]({url}): {meta.get("description", "")}'
             for url, meta in live.items() if url not in have]
    if added:
        head = next((i for i, ln in enumerate(out) if ln.strip() == "## 主要コンテンツ"), None)
        if head is None:
            out += ["", "## 主要コンテンツ"] + added
        else:
            end = next((i for i in range(head + 1, len(out)) if out[i].startswith("## ")), len(out))
            while end > head + 1 and not out[end - 1].strip():
                end -= 1          # 節の間の空行は残す
            out[end:end] = added
    if dropped or renamed or added:
        lt.write_text("\n".join(out), encoding="utf-8", newline="\n")
        print(f"SYNC: llms.txt の記事の行を整理（公開しない記事 {len(dropped)}行を削除・題名の差し替え {renamed}行"
              f"・行の無い記事 {len(added)}行を追加）")
        for u in dropped[:10]:
            print(f"   削除: {u}")


def prune_orphan_articles(entries, unparsable):
    """原稿の無くなった記事の生成HTML（site/<cat>/<slug>/）を消す。

    カテゴリ変更・_conflicted への隔離・削除をすると、原稿は無いのに古いHTMLが
    配信され続ける（sitemap からは消えるため、誰も気づかない）。
    消すのは「かつて記事として生成したフォルダ」だけ: index.html 1枚だけを持ち、
    その中身が記事テンプレート（<main class="article" と BlogPosting）であるもの。
    カテゴリ一覧・固定ページ・画像は条件に合わないので消えない。
    カテゴリを移した記事は、旧URLから新URLへ 301 を _redirects に足す
    """
    import shutil
    if not entries:
        return []
    live = {(m["category"], m["slug"]) for m, _ in entries}
    moved_to = {m["slug"]: m["category"] for m, _ in entries}
    victims = []
    for cat in CATEGORIES:
        base = SITE / cat
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            # フロントマターが一時的に壊れただけの記事は、直れば戻るので消さない
            if not d.is_dir() or (cat, d.name) in live or d.name in unparsable:
                continue
            files = [f for f in d.rglob("*") if f.is_file()]
            if [f.name for f in files] != ["index.html"]:
                continue
            t = files[0].read_text(encoding="utf-8", errors="replace")
            if '<main class="article ' not in t or '"BlogPosting"' not in t:
                continue
            victims.append((cat, d))
    if not victims:
        return []
    # 一度に大量に消えるのは、判定か原稿の置き場のほうが壊れている。消さずに知らせる
    if len(victims) > max(10, len(entries) // 5):
        print(f"WARN: 原稿の無い記事フォルダが{len(victims)}件あります。多すぎるため消しません"
              "（articles/ の置き場やビルドの判定を確かめてください）: "
              + ", ".join(f"{c}/{d.name}" for c, d in victims[:5]))
        return []
    print(f"REMOVED: 原稿の無くなった記事の生成HTMLを削除（{len(victims)}件）")
    for cat, d in victims:
        print(f"   {cat}/{d.name}/"
              + (f" → /{moved_to[d.name]}/{d.name}/ へ301" if d.name in moved_to else ""))
    rd = SITE / "_redirects"
    have = rd.read_text(encoding="utf-8") if rd.is_file() else ""
    srcs = {ln.split()[0] for ln in have.splitlines() if ln.strip() and not ln.startswith("#")}
    add = [f"/{cat}/{d.name}/  /{moved_to[d.name]}/{d.name}/  301" for cat, d in victims
           if d.name in moved_to and f"/{cat}/{d.name}/" not in srcs]
    if add:
        head = "" if "# build.py: カテゴリを移した記事" in have else (
            "# build.py: カテゴリを移した記事。旧URLの評価を新URLへ引き継ぐ（自動で追記）\n")
        rd.write_text(have.rstrip("\n") + "\n" + head + "\n".join(add) + "\n",
                      encoding="utf-8", newline="\n")
    for _, d in victims:
        shutil.rmtree(d)
    return [f"{c}/{d.name}" for c, d in victims]


def main():
    template = TEMPLATE.read_text(encoding="utf-8")
    only = sys.argv[1] if len(sys.argv) > 1 else None
    entries, warns = [], []

    # 隔離フォルダに公開済みの記事が入っていたら知らせる。
    # 公開してランクインしていた10本が、2度にわたり誤って隔離された。
    # 気づかないとサイトから静かに消えるため、ビルドのたびに見る。
    conflicted = ARTICLES / "_conflicted"
    if conflicted.is_dir():
        live = [f.stem for f in conflicted.glob("*.md")
                if (SITE / "sitemap.xml").read_text(encoding="utf-8").find(f"/{f.stem}/") >= 0]
        if live:
            print(f"!! 公開済みの記事が隔離されています（{len(live)}本）: "
                  + ", ".join(live[:5]) + ("…" if len(live) > 5 else ""))
            print("   articles/ へ戻してください。隔離は新規記事にだけ使います")

    llms = (SITE / "llms.txt").read_text(encoding="utf-8")

    # 品質審査ゲート: score(100点満点) 90点未満・未審査はアップロードしない
    QUALITY_GATE = 90
    paths, all_metas, blocked, blocked_metas = [], [], [], []
    unparsable = set()             # フロントマターが読めなかった記事。生成済みHTMLは消さない
    for p in sorted(ARTICLES.glob("*.md")):
        if p.name.startswith("_"):
            continue
        # 他サイト向けの記事は publish.py が配信済み。ここで「不正」と扱うと
        # 救済処理が当サイトのカテゴリへ書き換えてしまい、2ドメインに同じ記事が出る
        import sites as sites_mod
        owner = article_site(p)
        if owner and owner != sites_mod.primary():
            print(f"SKIP(他サイト): {p.stem} → {owner} へ配信済み")
            drop_stale_html(p.stem)
            continue
        # 1記事の不正フロントマターで全ビルドを止めない（不正記事はBLOCKED扱いで続行）
        try:
            meta = parse_article(p)[0]
        except Exception as e:
            blocked.append(f"{p.stem}: フロントマター不正（{e}）")
            unparsable.add(p.stem)
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
        # 足切り: score_breakdown がある場合、1観点でも下限未満なら不合格（合計点で壊滅観点を隠さない）。
        # 規則は rubric に1か所だけ置く（配信側も rubric.gate_ok で同じ判定をする）
        import rubric
        weak = rubric.weak_axes(meta)
        if weak:
            th, full = rubric.cutoff(meta.get("score_breakdown") or {})
            blocked.append(f"{meta['slug']}: 観点足切り {weak}（各{th}/{full}以上が必要）")
            blocked_metas.append(meta)
            continue
        if not title_has_keyword(str(meta.get("title") or ""),
                                 str(meta.get("keyword") or "")):
            QUALITY_ISSUES.setdefault(meta["slug"], []).append(
                f"狙う語がタイトルに無い（{meta.get('keyword')}）")
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

    # これまでに公開した記事。台帳が無い初回は何も止めず、台帳だけ作る
    _known = published_slugs()
    late_blocked = set()          # 品質検査で止めた記事。一覧からも外す

    # 前後ナビ用の時系列順（公開日→slugで安定ソート）
    ordered = sorted(all_metas, key=lambda m: (str(m["date"]), m["slug"]))
    pos = {m["slug"]: i for i, m in enumerate(ordered)}

    def render_all(metas, skip):
        """記事を描画して (meta, url) を集める。skip の記事は描かない。

        前後ナビの並びは、渡された metas から作り直す。止めた記事を含んだ並びを
        使い回すと、隣の記事から「次の記事」として404へリンクが残る
        """
        seq = sorted(metas, key=lambda m: (str(m["date"]), m["slug"]))
        idx = {m["slug"]: i for i, m in enumerate(seq)}
        _set_live(metas)
        out = []
        for path in paths:
            slug = parse_article(path)[0]["slug"]
            if slug in skip or slug not in idx:
                continue
            meta = next(m for m in metas if m["slug"] == slug)
            i = idx[meta["slug"]]
            prev_meta = seq[i - 1] if i > 0 else None
            next_meta = seq[i + 1] if i < len(seq) - 1 else None
            meta, url = build_article(path, template, related_html(meta, metas),
                                      unpublished_urls=unpublished_urls,
                                      prevnext=prev_next_html(prev_meta, next_meta))
            out.append((meta, url))
        return out

    rendered = render_all(all_metas, set())
    # 新しい記事だけに当てる門: 量産の指紋（scaled_guard）と監修の記録（editorial_review）
    import editorial_review as _ER
    _reviews = _ER.load()
    _new = [m["slug"] for m, _ in rendered if _known is not None and m["slug"] not in _known]
    _corpus = None
    if _new:
        import scaled_guard as _SG
        _corpus = _SG.corpus()
    for meta, url in rendered:
        # 「警告ゼロが公開条件」を実際に守らせる。ただし止めるのは未公開の記事だけ。
        # 公開済みを後から取り下げると、取れている順位まで失う
        issues = list(QUALITY_ISSUES.get(meta["slug"]) or [])
        is_new = _known is not None and meta["slug"] not in _known
        if is_new:
            issues += _SG.check(meta["slug"], _corpus)
        if is_new and not issues and not _ER.reviewed(meta["slug"], _reviews):
            # 品質の門は通ったが、監修の記録が無い。BLOCKED と分けるのは、救済の工程が
            # BLOCKED を「書き直す対象」として拾うため（監修待ちは書き直しても解けない）
            print(f"HELD(監修待ち): {meta['slug']} → 確認したら "
                  f"python scripts/editorial_review.py --approve {meta['slug']}")
            stale = SITE / meta["category"] / meta["slug"]
            if stale.exists():
                import shutil
                shutil.rmtree(stale)
            unpublished_urls.add(f"/{meta['category']}/{meta['slug']}/")
            late_blocked.add(meta["slug"])
            continue
        if issues and is_new:
            blocked.append(f"{meta['slug']}: " + " / ".join(issues))
            print(f"BLOCKED(公開不可): {meta['slug']}: " + " / ".join(issues)
                  + " → 直してから再度ビルドしてください")
            stale = SITE / meta["category"] / meta["slug"]
            if stale.exists():
                import shutil
                shutil.rmtree(stale)
            unpublished_urls.add(f"/{meta['category']}/{meta['slug']}/")
            late_blocked.add(meta["slug"])
            continue
        entries.append((meta, url))
        if url not in llms:
            warns.append(f"llms.txt 未追記: {meta['title']} -> {url}")
        if only and meta["slug"] == only:
            print(f"built: {url}")

    # 止めた記事を一覧・関連・業種ハブから外す。残すと内部リンクが404になる。
    # 先に描いた記事は、止めた記事への関連リンクを持ったままなので描き直す
    if late_blocked:
        all_metas = [m for m in all_metas if m["slug"] not in late_blocked]
        print(f"再描画: {len(late_blocked)}本を止めたため、関連リンクを作り直します")
        entries = render_all(all_metas, late_blocked)
    sync_llms(entries)
    prune_orphan_articles(entries, unparsable)
    build_blog_index(all_metas)
    build_industry_hubs(all_metas)
    build_extra_pages(all_metas)
    build_sitemap(entries)
    save_body_hashes()
    build_feed(entries)
    sync_listings(all_metas)
    warns += quality_checks(all_metas)
    stamp_assets()
    warns += link_check()
    warns += prefix_link_check()
    print(f"OK: {len(entries)}記事 / blog一覧 + sitemap.xml + feed.xml 更新")
    for w in warns:
        print(f"WARN: {w}")
    if not warns:
        print("品質検査: メタ字数・カニバリ・内部リンク404 すべてクリア")
    # ここまでの検査は全部、原稿（Markdown）だけを見ている。
    # 「原稿は正しいが変換すると壊れる」崩れは、出力を見ないと分からない。
    # 実際、表がパイプ記号のまま出る・** がそのまま表示される崩れを長く見逃した
    render_warns = render_check.scan(sorted((ROOT / "site").rglob("index.html")))
    if render_warns:
        fixes = {n: f for n, _, f in render_check.SYMPTOMS}
        for name, hits in sorted(render_warns.items(), key=lambda x: -len(x[1])):
            print(f"WARN: 描画 — {name}（{len(hits)}ページ / 例: "
                  f"{hits[0][0].parent.name}）→ {fixes[name]}")
    else:
        print("描画検査: 生成HTMLに崩れなし")
    # 症状を並べる検査は「こちらが知っている壊れ方」しか見つけられない。
    # ここでは中身を見ず、原稿と出力で塊の数だけを突き合わせる。
    # 知らない壊れ方でも、変換に失敗すれば数は合わなくなる
    gaps = 0
    for md in sorted((ROOT / "articles").glob("*.md")):
        t = md.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"^score:\s*(9[0-9]|100)\s*$", t, re.M):
            continue
        out = list((ROOT / "site").glob(f"*/{md.stem}/index.html"))
        if not out:
            continue
        body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", t, flags=re.S)
        g = render_check.structure_gap(
            body, out[0].read_text(encoding="utf-8", errors="replace"))
        if g:
            gaps += 1
            print(f"WARN: 取りこぼし — {md.stem}: "
                  + " / ".join(f"{n} 原稿{a}→出力{b}" for n, a, b in g))
    if not gaps:
        print("取りこぼし検査: 原稿に書いたものは全て出力に出ています")

    # 公開できた記事を台帳に残す。次回からは、ここに無い記事が不合格なら止まる
    # 前回の台帳との和集合で残す。今回たまたま外れた記事（隔離・フロントマターの一時的な誤り）を
    # 台帳から落とすと、戻ったときに新規扱いになり、警告1つで HTML ごと取り下げられる。
    # 原稿が無くなった slug（統合で _merged/ へ移したもの等）だけは外す
    alive = {f.stem for f in ARTICLES.rglob("*.md") if "_merged" not in f.parts}
    save_published({s for s in (_known or set()) if s in alive}
                   | {m["slug"] for m, _ in entries})
    if _known is None:
        print(f"公開台帳を作りました（{len(entries)}本）。"
              "次のビルドからは、品質検査に落ちた新規記事は公開されません")
    still = {s: v for s, v in QUALITY_ISSUES.items()
             if _known and s in _known}
    if still:
        print(f"要対応: 公開済みで品質検査に落ちている記事 {len(still)}本"
              "（取り下げず、直す対象として扱います）")
        for s, v in list(still.items())[:6]:
            print(f"   {s}: " + " / ".join(v))


if __name__ == "__main__":
    main()
