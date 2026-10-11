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


def _label(sid):
    """CI のログに出す社の名前。お客様の社は公開の id（社の id・ドメインは伏せる語）"""
    return sites_mod.public_id(sid) if sites_mod.is_client(sid) else sid


def _client_file(sid):
    """お客様の社の一覧の置き場（非公開・CI のキャッシュ）。先方のドメイン・記事の題を public の一覧に書かない"""
    import client_private as CP
    return CP.private_path(sid, "data/external_articles.json")


def _with_clients(d):
    """public の一覧に、お客様の社の一覧（置き場にあるもの）を重ねる"""
    out = {"fetched": d.get("fetched"), "sites": dict(d.get("sites", {}))}
    for sid in sites_mod.load_all():
        if not sites_mod.is_client(sid):
            continue
        p = _client_file(sid)
        try:
            out["sites"].update(json.loads(p.read_text(encoding="utf-8")).get("sites", {}))
        except (OSError, ValueError):
            continue
    return out


def site_articles(cfg):
    """sitemapから記事URLを拾い、各ページのH1をタイトルとして取る"""
    prefix = cfg.get("url_prefix") or ""
    try:
        sm = fetch(f"https://{cfg['domain']}/sitemap.xml")
    except Exception as e:
        print(f"  {_label(cfg.get('id', ''))}: sitemap取得に失敗（{type(e).__name__}）")
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
            return _with_clients(d)
    return build()


def build():
    data = {"fetched": date.today().isoformat(), "sites": {}}
    for sid, cfg in sites_mod.load_all().items():
        if cfg["type"] == "self-static":
            continue  # 自リポジトリの記事は articles/ で把握済み
        client = sites_mod.is_client(sid)
        print(f"  {_label(sid)}" + ("" if client else f"（{cfg['domain']}）") + " を取得中…")
        arts = site_articles(cfg)
        print(f"    {len(arts)}本")
        if client:
            # お客様の社のドメイン・記事の題は public の一覧（data/external_articles.json）に書かず、置き場へ（守秘。2026-10-12）
            p = _client_file(sid)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"fetched": data["fetched"], "sites": {sid: arts}}, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="\n")
            continue
        data["sites"][sid] = arts
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8", newline="\n")
    return _with_clients(data)


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
