# -*- coding: utf-8 -*-
"""各サイトに実際に公開されている記事の一覧を取得してキャッシュする

使い方: python scripts/external_index.py [--refresh]

なぜ必要か:
コーポレートと補助金は別リポジトリのサイトで、移管前から独自に記事を持っている。
こちらの管制塔の台帳にはそれが載っていないため、同じテーマの記事を書いてしまう
（実際、補助金サイトには既に SECURITY ACTION の記事があった）。
sitemapとページタイトルを取り込んでキャッシュし、カニバリ検査の突合対象に加える。

キャッシュ: data/external_articles.json（--refresh で再取得。既定は7日で失効）
"""
import json
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sites as sites_mod  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "external_articles.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"}
MAX_AGE_DAYS = 7


def fetch(url, timeout=25):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def site_articles(cfg):
    """sitemapから記事URLを拾い、各ページのH1をタイトルとして取る"""
    prefix = cfg.get("url_prefix") or ""
    try:
        sm = fetch(f"https://{cfg['domain']}/sitemap.xml")
    except Exception as e:
        print(f"  {cfg['id']}: sitemap取得に失敗（{type(e).__name__}）")
        return []
    urls = [u for u in re.findall(r"<loc>(.*?)</loc>", sm)
            if prefix and f"{prefix}/" in u and not u.rstrip("/").endswith(prefix)]
    out = []
    for u in urls:
        try:
            h = fetch(u)
        except Exception:
            continue
        m = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""
        if title:
            out.append({"url": u, "slug": u.rstrip("/").rsplit("/", 1)[-1], "title": title})
    return out


def load(refresh=False):
    """キャッシュを返す。古い/無い場合だけ取りに行く"""
    if CACHE.exists() and not refresh:
        d = json.loads(CACHE.read_text(encoding="utf-8"))
        fetched = date.fromisoformat(d.get("fetched", "1970-01-01"))
        if date.today() - fetched <= timedelta(days=MAX_AGE_DAYS):
            return d
    return build()


def build():
    data = {"fetched": date.today().isoformat(), "sites": {}}
    for sid, cfg in sites_mod.load_all().items():
        if cfg["type"] == "self-static":
            continue  # 自リポジトリの記事は articles/ で把握済み
        print(f"  {sid}（{cfg['domain']}）を取得中…")
        arts = site_articles(cfg)
        data["sites"][sid] = arts
        print(f"    {len(arts)}本")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8", newline="\n")
    return data


def all_titles():
    """(site_id, title, url) の一覧。カニバリ検査が使う"""
    d = load()
    return [(sid, a["title"], a["url"]) for sid, arts in d.get("sites", {}).items() for a in arts]


if __name__ == "__main__":
    print("外部サイトの公開記事を取得します")
    d = build() if "--refresh" in sys.argv else load()
    for sid, arts in d.get("sites", {}).items():
        print(f"\n[{sid}] {len(arts)}本（取得日 {d['fetched']}）")
        for a in arts[:5]:
            print(f"  - {a['title'][:44]}")
        if len(arts) > 5:
            print(f"  … 他{len(arts) - 5}本")
