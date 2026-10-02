# -*- coding: utf-8 -*-
"""無料ツールの一覧（唯一の正）。build.py が毎回これを読み、各ツールのページと /tools/ をそろえる。

そろえるもの:
  - パンくず（ホーム › 無料ツール › ツール名）と、その構造化データ（BreadcrumbList＋WebApplication）
  - ページ末の「ほかの無料ツール」（自分以外を目的別に並べる）
  - /tools/ の目的別の一覧と ItemList

以前はツールごとにURLも名前もばらばらだった（/site-audit/・/diagnosis/aio/・/tools/ai-check/）。
同じツールがページによって「サイトの技術チェック」「サイト無料採点」「URL診断」と呼ばれ、
どれが同じものか分からなかった。名前と行き先はここだけで決める。
"""
import html
import json
import re
from pathlib import Path

SITE_URL = "https://ai.7senses.co.jp"
ORG = {"@type": "Organization", "name": "セブンセンシズ株式会社", "url": "https://corp.7senses.co.jp/"}

# 目的の並びが /tools/ の並び。page=False は資料など、ツールのページを持たないもの
GROUPS = [
    ("site", "サイトを調べる", "AIや検索に読まれる状態かを、URLだけで確かめます。"),
    ("ai", "AIでの見え方を調べる", "AIの答えに御社が出てくるか、引用される準備ができているかを確かめます。"),
    ("prep", "対策の準備に使う", "自社で直すときの手順と、そのまま使える文面を用意しています。"),
    ("map", "地図（Googleマップ）", "Googleビジネスプロフィールの整備度を確かめます。"),
]
TOOLS = [
    {"id": "url-check", "url": "/tools/url-check/", "group": "site", "name": "URL診断",
     "sub": "サイトの14項目を採点", "spec": "URLだけ・約30秒",
     "desc": "URLを入れるだけで、AIのクローラーが入れるか・検索に出るか・内容を読み取れるかを14項目・100点満点で採点し、直す順番と直し方を表示します。"},
    {"id": "ai-check", "url": "/tools/ai-check/", "group": "ai", "name": "AI診断",
     "sub": "AIにどう紹介されているか", "spec": "1回3問・1メールアドレス3回まで",
     "desc": "地域と業種を入れると、AIに「地域名＋業種 おすすめ」など3つの質問をして、答えの出典に御社のサイトが入っているか、回答に社名が出るかを表示します。"},
    {"id": "aio-check", "url": "/tools/aio-check/", "group": "ai", "name": "AI検索の対応度チェック",
     "sub": "8つの質問で採点", "spec": "8問・約30秒",
     "desc": "8つの質問に答えると、AI検索に引用されるために足りないものを100点満点で表示します。"},
    {"id": "checklist", "url": "/download/", "group": "prep", "name": "AI検索対策チェックリスト",
     "sub": "業種別PDF", "spec": "5業種", "page": False,
     "desc": "歯科医院・クリニック・不動産会社・工務店・士業事務所の5業種。印をつけながら、自社で直すところを確かめられます。"},
    {"id": "kuchikomi-henshin", "url": "/tools/kuchikomi-henshin/", "group": "prep", "name": "口コミ返信文の作成ツール",
     "sub": "返信案を3つ作る", "spec": "業種と口コミの種類を選ぶだけ",
     "desc": "業種と口コミの種類を選ぶと、そのまま使える返信案を3つ作ります。医療は医療広告ガイドラインにふれない書き方にそろえます。"},
    {"id": "meo-check", "url": "/tools/meo-check/", "group": "map", "name": "マップ集客の整備度チェック",
     "sub": "8つの質問で採点", "spec": "8問・約30秒",
     "desc": "8つの質問に答えると、Googleビジネスプロフィールの整備度を100点満点で採点します。"},
]
BY_ID = {t["id"]: t for t in TOOLS}
E = html.escape


def label(t):
    return f'{t["name"]}（{t["sub"]}）'


def breadcrumb_html(t):
    return ('<nav class="breadcrumb" aria-label="パンくずリスト">\n  <ol>\n    <li><a href="/">ホーム</a></li>\n'
            '    <li><a href="/tools/">無料ツール</a></li>\n'
            f'    <li aria-current="page">{E(t["name"])}</li>\n  </ol>\n</nav>')


def ld(t):
    graph = [
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "ホーム", "item": SITE_URL + "/"},
            {"@type": "ListItem", "position": 2, "name": "無料ツール", "item": SITE_URL + "/tools/"},
            {"@type": "ListItem", "position": 3, "name": t["name"], "item": SITE_URL + t["url"]}]},
        {"@type": "WebApplication", "name": label(t), "url": SITE_URL + t["url"],
         "applicationCategory": "BusinessApplication", "operatingSystem": "Any", "inLanguage": "ja",
         "isAccessibleForFree": True, "offers": {"@type": "Offer", "price": "0", "priceCurrency": "JPY"},
         "description": t["desc"], "publisher": ORG},
    ]
    return ('<script type="application/ld+json" data-tools-ld>\n'
            + json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, indent=1)
            + "\n</script>")


def _card(t, cta):
    return (f'<a href="{t["url"]}" data-cta="{cta}_{t["id"]}"><b>{E(t["name"])}<small>{E(t["sub"])}</small></b>'
            f'<span>{E(t["desc"])}</span><em>{E(t["spec"])}</em></a>')


def others_html(t):
    """ツールのページの末尾。自分以外を目的別に並べ、一覧へ戻れるようにする"""
    rows = []
    for gid, gname, _ in GROUPS:
        items = [x for x in TOOLS if x["group"] == gid and x["id"] != t["id"]]
        if items:
            rows.append(f'<div class="tools-grp"><h3>{E(gname)}</h3><div class="tools-sub">'
                        + "".join(_card(x, "tools_other") for x in items) + "</div></div>")
    return ('<!-- tools:others -->\n<section class="tools-more tools-others" aria-label="ほかの無料ツール">\n'
            '  <h2>ほかの無料ツール</h2>\n  ' + "\n  ".join(rows)
            + '\n  <p class="tools-consult"><a href="/tools/" data-cta="tools_other_all">無料ツールの一覧へ</a>'
            ' ／ 結果の読み方や、何から直すかのご相談は <a href="/lp/#form" data-cta="tools_other_consult">無料相談</a></p>\n'
            '</section>\n<!-- /tools:others -->')


def index_html():
    """/tools/ の目的別一覧"""
    out = []
    for gid, gname, gdesc in GROUPS:
        items = [x for x in TOOLS if x["group"] == gid]
        out.append(f'<div class="tools-grp" id="{gid}"><h3>{E(gname)}</h3><p>{E(gdesc)}</p><div class="tools-sub">'
                   + "".join(_card(x, "tools_index") for x in items) + "</div></div>")
    return ('<!-- tools:catalog -->\n<section class="tools-more" aria-label="目的から選ぶ">\n  <h2>目的から選ぶ</h2>\n  '
            + "\n  ".join(out)
            + '\n  <p class="tools-consult">結果の読み方や、何から直すかのご相談は無料です。'
            '<a href="/lp/#form" data-cta="tools_consult">無料相談を申し込む</a></p>\n</section>\n<!-- /tools:catalog -->')


def index_ld():
    items = [{"@type": "ListItem", "position": i, "name": label(t), "url": SITE_URL + t["url"]}
             for i, t in enumerate(TOOLS, 1)]
    return ('<script type="application/ld+json" data-tools-ld>\n'
            + json.dumps({"@context": "https://schema.org", "@type": "ItemList", "name": "AI集客ラボの無料ツール",
                          "itemListElement": items}, ensure_ascii=False, indent=1) + "\n</script>")


LD_BLOCK = re.compile(r'<script type="application/ld\+json"[^>]*>(?:(?!</script>).)*?(?:BreadcrumbList|ItemList)(?:(?!</script>).)*</script>', re.S)
CRUMB = re.compile(r'<nav class="breadcrumb".*?</nav>', re.S)


def _sub(rx, new, s, where):
    s2, n = rx.subn(lambda m: new, s, count=1)
    if n != 1:
        raise ValueError(f"{where}: 置き換え先が見つかりません（{rx.pattern[:40]}）")
    return s2


def apply(site: Path):
    """各ツールのページと /tools/ を一覧にそろえる。変えたファイルの数を返す"""
    n = 0
    for t in TOOLS:
        if t.get("page") is False:
            continue
        p = site / t["url"].strip("/") / "index.html"
        s = p.read_text(encoding="utf-8")
        new = _sub(CRUMB, breadcrumb_html(t), s, p.name)
        new = _sub(LD_BLOCK, ld(t), new, t["id"])
        block = others_html(t)
        if "<!-- tools:others -->" in new:
            new = re.sub(r"<!-- tools:others -->.*?<!-- /tools:others -->", lambda m: block, new, flags=re.S)
        else:
            new = new.replace('<footer class="site-footer">', block + '\n\n<footer class="site-footer">', 1)
        if new != s:
            p.write_text(new, encoding="utf-8", newline="")
            n += 1
    p = site / "tools" / "index.html"
    s = p.read_text(encoding="utf-8")
    new = re.sub(r"<!-- tools:catalog -->.*?<!-- /tools:catalog -->", lambda m: index_html(), s, flags=re.S)
    ld_blocks = [m for m in LD_BLOCK.finditer(new) if "ItemList" in m.group(0) and "BreadcrumbList" not in m.group(0)]
    if len(ld_blocks) != 1:
        raise ValueError("/tools/: ItemList の構造化データが1つではありません")
    new = new[:ld_blocks[0].start()] + index_ld() + new[ld_blocks[0].end():]
    if new != s:
        p.write_text(new, encoding="utf-8", newline="")
        n += 1
    return n
