# -*- coding: utf-8 -*-
"""エリアハブ（/area/<slug>/）。訪日客は業種より先に「エリア」で探す。

業種ハブ（industry_hub）と同じ作り。定義は data/areas.json。
判定は記事の題名と狙う語だけ（本文の住所・会社所在地では判定しない。
実測で「東成」は76回出てくるが、ほぼ全部が運営会社の所在地だった）。
記事が _min_articles 本に満たないエリアはページを作らない（薄い一覧はサイトの評価を下げる）。

build.py が呼ぶ:  pairs = area_hub.live(metas) → [(area, [meta...])]
"""
import html as _h
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "areas.json"
BASE = "/area/"


def load():
    d = json.loads(SRC.read_text(encoding="utf-8"))
    return d.get("areas", []), int(d.get("_min_articles", 5))


def detect(title, keyword, areas=None):
    areas = areas if areas is not None else load()[0]
    key = f"{title} {keyword}".lower()
    for a in areas:
        if any(w.lower() in key for w in a["synonyms"]):
            return a["slug"]
    return None


def live(metas):
    areas, mn = load()
    g = {}
    for m in metas:
        s = detect(m.get("title", ""), m.get("keyword", ""), areas)
        if s:
            g.setdefault(s, []).append(m)
    for v in g.values():
        v.sort(key=lambda m: str(m.get("date", "")), reverse=True)
    return [(a, g[a["slug"]]) for a in areas if len(g.get(a["slug"], [])) >= mn], g


def page_html(area, metas, url_of):
    lis = "".join(f'<li><a href="{url_of(m)}">{_h.escape(m["title"])}</a>'
                  f'<span class="cnt">{str(m.get("date", ""))[:7]}</span></li>' for m in metas)
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": f"{area['name']}の記事",
          "about": {"@type": "Place", "name": area["name"]},
          "mainEntity": {"@type": "ItemList", "numberOfItems": len(metas),
                         "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": url_of(m), "name": m["title"]}
                                             for i, m in enumerate(metas[:30])]}}
    return (f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>{_h.escape(area["name"])}の記事</h2>'
            f'<span class="cnt">全{len(metas)}本</span></div>'
            f'<p class="hub-lead">{_h.escape(area.get("lead", ""))}</p><ul class="hub-list">{lis}</ul>'
            f'<p class="hub-note"><a href="{BASE}">← エリアから探す</a></p></div>'
            '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>")


def index_html(pairs, g):
    areas, mn = load()
    lis = "".join(f'<li><a href="{BASE}{a["slug"]}/"><strong>{_h.escape(a["name"])}</strong>'
                  f'<span class="cnt">{len(v)}本</span></a></li>' for a, v in pairs)
    coming = [a for a in areas if 0 < len(g.get(a["slug"], [])) < mn]
    more = ("" if not coming else
            f'<p class="hub-note">記事が{mn}本たまったエリアからページを作ります。準備中: '
            + "、".join(f'{_h.escape(a["name"])}（{len(g[a["slug"]])}本）' for a in coming) + "</p>")
    return ('<div class="latest-block" data-cat="new"><div class="cat-head"><h2>エリアから探す</h2>'
            f'<span class="cnt">{len(pairs)}エリア</span></div>'
            '<p class="hub-lead">業種や手法ではなく、エリアから記事を探せる入口です。</p>'
            f'<ul class="hub-list">{lis}</ul>{more}</div>')
