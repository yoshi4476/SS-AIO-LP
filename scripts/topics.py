# -*- coding: utf-8 -*-
"""主題（例: MEO 口コミ）ごとに、ピラー1本＋クラスター記事を自動で束ねる（/topics/）。

**なぜ要るか**: トピカルオーソリティは「面」で決まる。業種ハブはあるが、主題の軸
（口コミ・予約・補助金の申請…）ではまとまっていなかった。狙う語の語を数えて
同じ主題の記事を束ね、最も強い記事をピラーに置き、目次ページと相互リンクを機械で作る。

  主題の決め方: 狙う語（keyword）から手法語（AIO/SEO/MEO/集客…）を除いた名詞を主題語にし、
               同じ主題語を持つ記事が MIN 本以上ある主題だけ作る
  ピラーの決め方: 表示回数（GSC）が最も多い記事。取れなければ本文が最も長い記事

build.py が呼ぶ:
  groups = topics.build(site_id)                  # [{slug, name, pillar, members:[meta...]}]
  topics.box_html(meta, groups)                   # 記事末の「このテーマの記事」
"""
import html as _h
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN = 3          # 4だと主題が2つしか残らない（実測）。3で口コミ・インスタ・集客方法など6主題
MAX_GROUPS = 30
# 主題にしない語（手法・一般語）。主題は「何について」であって「どの手法で」ではない
STOP = {"aio", "llmo", "seo", "meo", "geo", "ai", "対策", "方法", "やり方", "手順", "とは", "比較", "選び方",
        "費用", "料金", "相場", "事例", "ポイント", "コツ", "ガイド", "注意点", "違い", "おすすめ", "一覧", "まとめ",
        "集客", "活用", "導入", "運用", "支援", "サポート", "会社", "企業", "中小企業", "個人事業主", "2026", "2026年",
        "最新", "完全", "解説", "初心者", "向け", "できる", "する", "ない", "無料", "ツール",
        # 題名に入りやすい一般語（施策・ステップ・原因…）は主題ではない。kw+title で試すと
        # 「施策:24本」のような意味の無い束ができた（実測）
        "検索", "施策", "ステップ", "基準", "原因", "要素", "視点", "反響", "google", "ng", "対応", "手法", "効果"}


def _industry_words():
    """業種名は業種ハブ（/industry/）の軸。テーマの軸（口コミ・予約・申請…）と分けるため主題語から外す"""
    try:
        d = json.loads((ROOT / "data" / "industries.json").read_text(encoding="utf-8"))
        return {w.lower() for i in d.get("industries", []) for w in [i.get("name", "")] + list(i.get("synonyms", []))}
    except Exception:
        return set()


_IND = None


def _terms(kw):
    global _IND
    if _IND is None:
        _IND = _industry_words()
    out = []
    for t in re.findall(r"[一-龥ァ-ヶー]{2,}|[A-Za-z][A-Za-z0-9]{1,}", str(kw)):
        t = t.lower()
        if t not in STOP and t not in _IND and len(t) >= 2 and not any(t in w for w in _IND if len(w) > len(t)):
            out.append(t)
    return out


def _slug(term):
    import hashlib
    return re.sub(r"[^a-z0-9]", "", term) or hashlib.md5(term.encode()).hexdigest()[:8]


def _imp(site_id):
    """slug → 表示回数（順位の記録から。無ければ空）"""
    p = ROOT / "data" / "ranks" / f"{site_id}.json"
    out = {}
    if p.is_file():
        try:
            hist = json.loads(p.read_text(encoding="utf-8"))
            for r in hist[sorted(hist)[-1]]:
                s = str(r.get("url", "")).rstrip("/").split("/")[-1]
                if s:
                    out[s] = out.get(s, 0) + int(r.get("imp", 0))
        except Exception:
            pass
    return out


def build(site_id, metas):
    """metas: build.py の all_metas（title, slug, keyword, category, date, chars?）"""
    by = {}
    for m in metas:
        for t in set(_terms(m.get("keyword") or m.get("title", ""))):
            by.setdefault(t, []).append(m)
    imp = _imp(site_id)
    groups = []
    used = set()
    for t, ms in sorted(by.items(), key=lambda kv: -len(kv[1])):
        ms = [m for m in ms if m["slug"] not in used]
        if len(ms) < MIN:
            continue
        pillar = max(ms, key=lambda m: (imp.get(m["slug"], 0), len(str(m.get("body", "")))))
        groups.append({"slug": _slug(t), "name": t, "pillar": pillar,
                       "members": sorted(ms, key=lambda m: str(m.get("date", "")), reverse=True)})
        used.update(m["slug"] for m in ms)
        if len(groups) >= MAX_GROUPS:
            break
    return groups


def page_html(g, url_of):
    p = g["pillar"]
    items = "".join(f'<li><a href="{url_of(m)}">{_h.escape(m["title"])}</a>'
                    f'<span class="cnt">{str(m.get("date", ""))[:7]}</span></li>' for m in g["members"] if m is not p)
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": f"{g['name']}の記事",
          "mainEntity": {"@type": "ItemList", "numberOfItems": len(g["members"]),
                         "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": url_of(m), "name": m["title"]}
                                             for i, m in enumerate(g["members"])]}}
    return (f'<div class="latest-block" data-cat="new"><div class="cat-head"><h2>{_h.escape(g["name"])}の記事</h2>'
            f'<span class="cnt">全{len(g["members"])}本</span></div>'
            f'<p class="hub-lead">まず読む1本: <a href="{url_of(p)}"><strong>{_h.escape(p["title"])}</strong></a></p>'
            f'<ul class="hub-list">{items}</ul>'
            f'<p class="hub-note"><a href="/topics/">← テーマ一覧へ</a></p></div>'
            '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>")


def index_html(groups):
    lis = "".join(f'<li><a href="/topics/{g["slug"]}/"><strong>{_h.escape(g["name"])}</strong>'
                  f'<span class="cnt">{len(g["members"])}本</span></a>'
                  f'<span class="hub-lead">まず読む1本: {_h.escape(g["pillar"]["title"][:40])}</span></li>' for g in groups)
    return ('<div class="latest-block" data-cat="new"><div class="cat-head"><h2>テーマから探す</h2>'
            f'<span class="cnt">{len(groups)}テーマ</span></div>'
            '<p class="hub-lead">同じ主題の記事を束ね、まず読む1本（ピラー）と、掘り下げる記事（クラスター）に分けています。</p>'
            f'<ul class="hub-list">{lis}</ul></div>')


def box_html(meta, groups, url_of):
    """記事末に置く「このテーマの記事」。ピラーへ必ずリンクし、兄弟記事を3本まで"""
    for g in groups:
        if any(m["slug"] == meta["slug"] for m in g["members"]):
            p = g["pillar"]
            sib = [m for m in g["members"] if m["slug"] not in (meta["slug"], p["slug"])][:3]
            lis = "".join(f'<li><a href="{url_of(m)}">{_h.escape(m["title"])}</a></li>' for m in sib)
            head = (f'<p>このテーマの全体像は <a href="{url_of(p)}"><strong>{_h.escape(p["title"])}</strong></a> にまとめています。</p>'
                    if p["slug"] != meta["slug"] else "<p>この記事がテーマの全体像です。掘り下げる記事:</p>")
            return (f'<section class="topic-box" style="margin:32px 0;padding:18px 20px;border:1px solid #dbe4f0;border-radius:12px">'
                    f'<p style="margin:0 0 8px;font-weight:700">テーマ「{_h.escape(g["name"])}」の記事（全{len(g["members"])}本）</p>'
                    f'{head}<ul>{lis}</ul><p style="margin:8px 0 0"><a href="/topics/{g["slug"]}/">テーマの一覧へ →</a></p></section>')
    return ""
