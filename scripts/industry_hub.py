# -*- coding: utf-8 -*-
"""業種別のハブページ。サイトに2本目の軸を作る。

いまの構成は「手法（AIO・SEO・MEO・AI集客）→ 記事」の1軸しかない。
しかし読者が探しているのは「クリニックの集客」であって、手法ごとの分類ではない。
実測では、クリニック関連の21本が4カテゴリに散っていて、まとめて見る場所が無かった。

手法×業種の2軸にすると、
  - 読者は自分の業種の全体像に1ページでたどり着ける
  - 記事どうしがカテゴリをまたいで結ばれ、主題のまとまり（トピカルオーソリティ）ができる
  - 記事が増えるほどハブが厚くなる。運用の手間は増えない（自動で組み直す）

定義は data/industries.json。記事が `_min_articles` 本に満たない業種はページを作らない
（中身の薄いページを増やすと、サイト全体の評価を下げる）。

  python scripts/industry_hub.py          # どの業種に何本あるか
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "industries.json"
SITE = ROOT / "site"
BASE = "/industry/"


def load():
    d = json.loads(SRC.read_text(encoding="utf-8"))
    return d.get("industries", []), int(d.get("_min_articles", 5))


def detect(title, keyword, industries=None):
    """記事がどの業種のものか。定義の順に見る（具体的なものが先）"""
    inds = industries if industries is not None else load()[0]
    key = f"{title} {keyword}".lower()
    for ind in inds:
        if any(w.lower() in key for w in ind["synonyms"]):
            return ind["slug"]
    return None


def group(metas, industries=None):
    """{slug: [meta]}。新しい順"""
    inds = industries if industries is not None else load()[0]
    out = {}
    for m in metas:
        s = detect(m.get("title", ""), m.get("keyword", ""), inds)
        if s:
            out.setdefault(s, []).append(m)
    for v in out.values():
        v.sort(key=lambda m: str(m.get("date", "")), reverse=True)
    return out


def live(metas):
    """ページを作る業種だけ（本数が足りているもの）"""
    inds, mn = load()
    g = group(metas, inds)
    return [(i, g[i["slug"]]) for i in inds if len(g.get(i["slug"], [])) >= mn], g


def box(meta, metas, categories):
    """記事に出す「同じ業種の記事」枠。カテゴリをまたいで結ぶのが目的"""
    import html as _h
    inds, mn = load()
    slug = detect(meta.get("title", ""), meta.get("keyword", ""), inds)
    if not slug:
        return ""
    ind = next(i for i in inds if i["slug"] == slug)
    same = [m for m in group(metas, inds).get(slug, []) if m["slug"] != meta["slug"]]
    if len(same) + 1 < mn:
        return ""
    picks = same[:3]
    lis = "".join(
        f'<li><a href="/{m["category"]}/{m["slug"]}/">{_h.escape(m["title"])}</a>'
        f'<span class="tag">{_h.escape(categories[m["category"]][0].replace("・活用全般", "").replace("運用", ""))}</span></li>'
        for m in picks)
    return (f'<section class="related industry-box"><h2>{_h.escape(ind["name"])}の集客をまとめて見る</h2>'
            f'<ul>{lis}</ul>'
            f'<p><a class="more" href="{BASE}{slug}/">{_h.escape(ind["name"])}の記事を全部見る（{len(same) + 1}本）→</a></p>'
            f'</section>')


def _tiles(metas, post_tile):
    return "\n".join(post_tile(m) for m in metas)


def faq_pairs(metas):
    """業種の記事が持つ FAQ（フロントマター）を、記事つきで平らに並べる"""
    out = []
    for m in metas:
        for f in (m.get("faq") or []):
            q, a = str(f.get("q", "")).strip(), str(f.get("a", "")).strip()
            if q and a:
                out.append((q, a, m))
    return out


def faq_body(ind, metas, url_of, limit=60):
    """業種×よくある質問のページ。質問形のクエリは AI Overview 表示率が64.7%で、
    記事を1本も書かずに質問の面を増やせる。答えは各記事の FAQ そのまま
    （新しい文を機械が作らない）。返すのは (HTML, FAQPage の JSON-LD) か None"""
    import html as _h
    pairs = faq_pairs(metas)[:limit]
    if len(pairs) < 5:
        return None
    items = "\n".join(
        f'<details class="faq-item"><summary>{_h.escape(q)}</summary>'
        f'<div class="a"><p>{_h.escape(a)}</p>'
        f'<p class="src"><a href="{url_of(m)}">→ {_h.escape(str(m.get("title", ""))[:48])}</a></p></div></details>'
        for q, a, m in pairs)
    html = (f'<div class="latest-block" data-cat="new"><div class="cat-head">'
            f'<h2>{_h.escape(ind["name"])}のよくある質問</h2><span class="cnt">{len(pairs)}問</span></div>'
            f'<p class="hub-lead">{_h.escape(ind["name"])}の記事{len(metas)}本から、よくある質問と答えを1か所に集めました。'
            f'答えは各記事に書いたものと同じです。詳しい根拠は記事本文をご覧ください。</p>'
            f'<div class="faq-list">{items}</div>'
            f'<p class="hub-note"><a href="{BASE}{ind["slug"]}/">← {_h.escape(ind["name"])}の記事一覧へ</a></p></div>')
    ld = {"@context": "https://schema.org", "@type": "FAQPage",
          "mainEntity": [{"@type": "Question", "name": q,
                          "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a, _ in pairs]}
    return html, ld


def hub_body(ind, metas, categories, post_tile):
    """業種ハブの中身。手法ごとに区切る（読者は自分に必要な手法から入る）"""
    import html as _h
    nq = len(faq_pairs(metas))
    faq_link = (f'<p class="hub-note"><a href="{BASE}{ind["slug"]}/faq/">'
                f'{_h.escape(ind["name"])}のよくある質問をまとめて見る（{nq}問）</a></p>' if nq >= 5 else "")
    blocks = [f'<div class="latest-block" data-cat="new">'
              f'<div class="cat-head"><h2>{_h.escape(ind["name"])}の記事</h2>'
              f'<span class="cnt">全{len(metas)}本</span></div>'
              f'<p class="hub-lead">{_h.escape(ind["lead"])}</p>{faq_link}</div>']
    for cat, (name, cls) in categories.items():
        part = [m for m in metas if m["category"] == cat]
        if not part:
            continue
        blocks.append(f'<div class="latest-block {cls}" data-cat="{cat}">'
                      f'<div class="cat-head"><h2>{_h.escape(ind["name"])}の{_h.escape(name)}</h2>'
                      f'<span class="cnt">{len(part)}本</span>'
                      f'<a class="more" href="/{cat}/">このカテゴリを見る →</a></div>'
                      f'<ul class="post-list">\n{_tiles(part, post_tile)}\n</ul></div>')
    return "\n".join(blocks)


def index_body(pairs, g):
    """/industry/ の一覧。どの業種に何本あるかを先に見せる"""
    import html as _h
    inds, mn = load()
    lis = "".join(
        f'<li><a href="{BASE}{i["slug"]}/"><strong>{_h.escape(i["name"])}</strong>'
        f'<span class="cnt">{len(v)}本</span></a>'
        f'<span class="hub-lead">{_h.escape(i["lead"][:70])}…</span></li>' for i, v in pairs)
    coming = [i for i in inds if 0 < len(g.get(i["slug"], [])) < mn]
    more = ""
    if coming:
        names = "、".join(f'{_h.escape(i["name"])}（{len(g[i["slug"]])}本）' for i in coming)
        more = (f'<p class="hub-note">記事が{mn}本たまった業種からページを作ります。'
                f'いま準備中: {names}</p>')
    return ('<div class="latest-block" data-cat="new"><div class="cat-head"><h2>業種から探す</h2>'
            f'<span class="cnt">{len(pairs)}業種</span></div>'
            '<p class="hub-lead">手法（AIO・SEO・MEO）ではなく、業種から探せる入口です。'
            '同じ業種の記事を、手法をまたいでまとめています。</p>'
            f'<ul class="hub-list">{lis}</ul>{more}</div>')


def main():
    from collections import Counter
    inds, mn = load()
    metas = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        g_ = lambda k: (re.search(rf"^{k}:\s*(.+)$", fm, re.M) or [0, ""])[1].strip().strip('"')
        metas.append({"title": g_("title"), "keyword": g_("keyword"),
                      "category": g_("category"), "slug": p.stem, "date": g_("date")})
    metas = [m for m in metas if m["category"] in ("aio", "seo", "meo", "ai-marketing")]
    g = group(metas, inds)
    print(f"■ 業種別の記事数（{len(metas)}本中／ページを作るのは{mn}本以上）")
    for i in inds:
        v = g.get(i["slug"], [])
        mark = "○" if len(v) >= mn else "－"
        cats = Counter(m["category"] for m in v)
        print(f"  {mark} {i['name']:<18} {len(v):>3}本  {dict(cats)}")
    print(f"  業種なし {len(metas) - sum(len(v) for v in g.values())}本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
