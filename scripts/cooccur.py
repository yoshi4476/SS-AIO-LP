# -*- coding: utf-8 -*-
"""上位・引用元の記事が扱う小見出しの語のうち、自記事に無いものを出す（共起語のカバー率）。

**なぜ要るか**: 11〜30位で止まる記事の主因は「需要のある語に答えていない」（rank_rescue）。
いまは GSC に出た語しか材料が無い。AIの回答が出典に選んだページ（ai_kw_research が
記録する sources）と、Gemini の検索が返す上位ページの見出しを読めば、
「上位が扱っていて自分が扱っていない観点」が機械で分かる。

材料: data/ai_kw/<site>.json の items[].ai.sources（ドメイン）と、必要なら Gemini 検索で
      狙う語の上位URLを取り、各ページの H2/H3 を抜き出す。自社ドメインは除く。
出力: data/cooccur/<slug>.json … {"missing": [...], "sources": [...]}
      auto_rewrite --kind stuck が「足りない観点」に加えて読む

  python scripts/cooccur.py --site ai-lab --limit 5
出す印: COOCCUR_OK=yes / COVERED=<記事数>
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "data" / "cooccur"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0; +https://ai.7senses.co.jp/)"}
STOP = {"まとめ", "よくある質問", "はじめに", "目次", "関連記事", "この記事", "監修", "注意", "こちら"}


def headings(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            html = r.read(400_000).decode("utf-8", "ignore")
    except Exception:
        return []
    hs = re.findall(r"<h[23][^>]*>(.*?)</h[23]>", html, re.S | re.I)
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", h)).strip() for h in hs][:40]


def terms(texts):
    out = set()
    for t in texts:
        for w in re.findall(r"[一-龥ァ-ヶー]{2,}|[A-Za-z][A-Za-z0-9]{2,}", t):
            if w not in STOP and len(w) <= 12:
                out.add(w.lower())
    return out


def source_urls(site_id, keyword, limit=6):
    """ai_kw の記録にある出典と、あれば Gemini 検索の上位URL"""
    urls = []
    p = ROOT / "data" / "ai_kw" / f"{site_id}.json"
    if p.is_file():
        for r in json.loads(p.read_text(encoding="utf-8")).get("items", []):
            if r["kw"] == keyword and (r.get("ai") or {}).get("sources"):
                urls += [f"https://{d}/" for d in r["ai"]["sources"]]
    try:
        import ai_cite_check as AC
        eng = AC.engines_available()          # 30日キャッシュつき（同じ語を何度も課金しない）
        if "Gemini" in eng:
            urls += eng["Gemini"](keyword) or []
    except Exception:
        pass
    seen, out = set(), []
    for u in urls:
        d = re.sub(r"^https?://([^/]+).*", r"\1", u)
        if "7senses" in d or d in seen:
            continue
        seen.add(d)
        out.append(u)
    return out[:limit]


def cover(site_id, slug, keyword, body):
    urls = source_urls(site_id, keyword)
    if not urls:
        return None
    theirs = terms([h for u in urls for h in headings(u)])
    mine = terms(re.findall(r"^#{2,3}\s+(.+)$", body, re.M)) | terms([body[:20000]])
    missing = sorted(theirs - mine, key=lambda w: -len(w))[:12]
    OUT.mkdir(parents=True, exist_ok=True)
    rec = {"keyword": keyword, "sources": urls, "missing": missing, "covered": round(1 - len(theirs - mine) / max(len(theirs), 1), 2)}
    (OUT / f"{slug}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--limit", type=int, default=5)
    a = ap.parse_args()
    import rank_rescue as RR
    try:
        items = [x for x in RR.items() if not a.site or x["site"] == a.site][:a.limit]
    except Exception as e:
        print(f"   止まっている記事を読めません（{str(e)[:60]}）")
        print("COOCCUR_OK=yes\nCOVERED=0")
        return 0
    n = 0
    for it in items:
        p = ROOT / "articles" / f"{it['slug']}.md"
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        kw = re.search(r"^keyword:\s*(.+)$", m.group(1), re.M)
        if not kw:
            continue
        rec = cover(it["site"], it["slug"], kw.group(1).strip(), m.group(2))
        if rec:
            n += 1
            print(f"   {it['slug'][:36]:<36} カバー率 {rec['covered']:.0%} / 無い語: {'・'.join(rec['missing'][:6])}")
        else:
            print(f"   {it['slug'][:36]:<36} 出典が取れません（AIの記録なし・鍵なし）")
    print(f"COOCCUR_OK=yes\nCOVERED={n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
