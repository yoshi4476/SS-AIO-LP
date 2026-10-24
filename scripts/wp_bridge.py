# -*- coding: utf-8 -*-
"""WordPress の社を、WordPress 本体の機能だけで扱う（管制塔の側）。

先方には何も置かない（2026-10-24 運用者「PHP では作らない一番セキュリティが高いもの」で、PHP のプラグイン
ss-quality-gate.php を廃止し、公開サイトでの配布もやめた）。WordPress のお客様の標準はサブドメインの静的なページで、
WordPress へ直接投稿するのは同じドメインがどうしても要る社だけ。そのときも、記事の投稿の専用ユーザー（投稿者）の
アプリケーションパスワードだけを預かり、管理者・編集者の鍵は受け取らない（role_problems が投稿の前に止める）。

投稿者の権限では固定ページ・転送・設定・<script> を扱えないので、業種のまとめ・用語集・llms.txt・301・
構造化データ・計測は WordPress の社では作らない。公開してよいかは publish.py の門（gate_ok と配信の前の検査）が決める。

  python scripts/wp_bridge.py --check                # WordPress の社の鍵が投稿者の権限だけか（WPBRIDGE_OK=）
"""
import argparse
import html as H
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0)"}
# 投稿者（author）に無い権限。1つでも持つ鍵は、漏れたときにサイトの乗っ取り・ほかの人の記事の改ざんまで届く
TOO_MUCH = ("manage_options", "unfiltered_html", "edit_others_posts", "edit_pages", "edit_theme_options",
            "promote_users", "create_users", "delete_users", "install_plugins", "activate_plugins", "edit_plugins",
            "edit_themes", "update_core")
_ROLE_CHECKED = {}


def is_wp(cfg):
    return (cfg or {}).get("type") == "wordpress"


def _has_auth(cfg):
    try:
        import publish
        publish._wp_auth(cfg)
        return True
    except SystemExit:
        return False


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def _public(url, timeout=30):
    """鍵なしで読む REST の一覧。(中身, 全ページ数)"""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "[]"), int(r.headers.get("X-WP-TotalPages") or 1)


# ---------- 鍵の権限 ----------

def role_problems(cfg):
    """投稿に使う鍵が投稿者の権限だけか。広すぎる・公開できないなら理由の行を返す（空なら投稿してよい）"""
    if cfg["id"] in _ROLE_CHECKED:
        return _ROLE_CHECKED[cfg["id"]]
    import publish
    me = publish._wp_call(cfg, "users/me?context=edit&_fields=roles,capabilities")
    roles = set((me or {}).get("roles") or [])
    caps = {k for k, v in ((me or {}).get("capabilities") or {}).items() if v}
    bad = sorted((roles & {"administrator", "editor"}) | (caps & set(TOO_MUCH)))
    out = []
    if bad:
        out.append(f"{cfg['id']} の投稿に使う鍵の権限が広すぎます（{'・'.join(bad[:4])}）。投稿者（author）の専用ユーザーを作り、"
                   "そのアプリケーションパスワードに替えてください（管理者・編集者の鍵は預かりません）")
    elif "publish_posts" not in caps:
        out.append(f"{cfg['id']} の投稿に使う鍵に記事を公開する権限（publish_posts）がありません。投稿者（author）の権限にしてください")
    _ROLE_CHECKED[cfg["id"]] = out
    return out


# ---------- 公開URL ----------

def sitemap_entries(domain, max_children=60):
    """本番の sitemap の (URL, lastmod)。索引形式（WordPress の /wp-sitemap.xml・Yoast の sitemap_index.xml）なら子を辿る。
    平らな sitemap では従来どおり（<url> を読むだけ）"""
    xml = _get(f"https://{domain}/sitemap.xml")
    if "<sitemapindex" in xml:
        out = []
        for loc in re.findall(r"<sitemap>\s*<loc>\s*(.*?)\s*</loc>", xml, re.S)[:max_children]:
            try:
                out += _entries(_get(H.unescape(loc)))
            except Exception as e:
                print(f"  {domain}: 子の sitemap を読めません（{H.unescape(loc)[:60]}・{type(e).__name__}）")
        return out
    return _entries(xml)


def _entries(xml):
    out = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block, re.S)
        mod = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block, re.S)
        if loc:
            out.append((H.unescape(loc.group(1)), mod.group(1)[:10] if mod else ""))
    return out


def url_rows(cfg, fallback=True):
    """WordPress の公開済みの記事（[{url, slug, type, modified}]）。

    WordPress 本体の REST（/wp/v2/posts。公開済みの一覧なので鍵は要らない）でパーマリンクを読む。
    読めなければ sitemap 索引から拾う（fallback=False なら空）"""
    import publish
    rows, page = [], 1
    try:
        while page <= 20:
            got, pages = _public(f"{publish._wp_api(cfg)}/posts?status=publish&per_page=100&page={page}"
                                 "&_fields=link,slug,modified")
            rows += [{"url": p["link"], "slug": p.get("slug", ""), "type": "post", "modified": p.get("modified", "")}
                     for p in got if isinstance(p, dict) and p.get("link")]
            if page >= pages:
                break
            page += 1
        return rows
    except Exception as e:
        if not fallback:
            print(f"  {cfg['id']}: 公開済みの記事の一覧を読めません（{type(e).__name__}）")
            return []
    try:
        return [{"url": u, "slug": urllib.parse.urlsplit(u).path.rstrip("/").rsplit("/", 1)[-1],
                 "type": "post", "modified": m} for u, m in sitemap_entries(cfg["domain"])]
    except Exception as e:
        print(f"  {cfg['id']}: 公開URLを取得できません（{type(e).__name__}）")
        return []


def site_urls(cfg):
    """通知・巡回に使う公開URLの一覧。WordPress は本体の REST、ほかは sitemap（索引形式なら子まで辿る）"""
    if is_wp(cfg):
        return [r["url"] for r in url_rows(cfg)]
    return [u for u, _ in sitemap_entries(cfg["domain"])]


def url_map(cfg, rows=None):
    """記事の slug → 公開URL"""
    rows = url_rows(cfg) if rows is None else rows
    return {r["slug"]: r["url"] for r in rows if r.get("type") == "post" and r.get("slug")}


def post_link(cfg, slug):
    """公開済みの記事のパーマリンク（WordPress の REST から。無ければ空）"""
    import publish
    try:
        found = publish._wp_call(cfg, f"posts?slug={slug}&status=publish&per_page=1&_fields=link")
    except SystemExit:
        found = None
    if isinstance(found, list) and found and found[0].get("link"):
        return found[0]["link"]
    return url_map(cfg).get(slug, "")


def article_url(cfg, meta):
    """記事の公開URL。WordPress はパーマリンク設定が決めるので、組み立てずに先方へ聞く"""
    import sites as S
    if is_wp(cfg):
        return post_link(cfg, meta["slug"]) or S.article_url(cfg, meta)
    return S.article_url(cfg, meta)


def rewrite_links(html, rows, skip=("/industry/", "/glossary/")):
    """本文の内部リンク（/<カテゴリ>/<slug>/ や /blog/<slug>/）を、WordPress の実際のパーマリンクへ置き換える。
    原稿は静的サイトの組み方で書かれており、そのままでは /%postname%/ の社で404になる"""
    by_slug = url_map(None, rows)

    def repl(m):
        path, slug, frag = m.group(1), m.group(2), m.group(3) or ""
        if slug not in by_slug or any(path.startswith(s) for s in skip):
            return m.group(0)
        return f'href="{by_slug[slug]}{frag}"'
    return re.sub(r'href="(/(?:[A-Za-z0-9_-]+/)*?([A-Za-z0-9_-]+)/)(#[^"]*)?"', repl, html)


def _site_articles(cfg):
    """その社の記事で、公開の基準を満たすもの（[(meta, body, path)]）"""
    import publish
    import sites as S
    out = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        if p.name.startswith("_"):
            continue
        try:
            meta, body = publish.parse_article(p)
        except Exception:
            continue
        if not isinstance(meta, dict) or S.find_category_owner(meta.get("category", "")) != cfg["id"]:
            continue
        if publish.gate_ok(meta):
            out.append((meta, body, p))
    return out


def _split_ld(html):
    """本文の <script type="application/ld+json"> を外し、JSON として読めたものを返す。
    本文に <script> を残すと、unfiltered_html の無い投稿者では WordPress が消す"""
    lds = []

    def take(m):
        try:
            lds.append(json.loads(m.group(1)))
        except ValueError:
            pass
        return ""
    body = re.sub(r'<script type="application/ld\+json">(.*?)</script>', take, html, flags=re.S)
    return body, lds


def ga4_id(cfg):
    v = str(cfg.get("ga4_measurement_id") or "").strip()
    return v if re.fullmatch(r"G-[A-Z0-9]{4,20}", v) else ""


def check(cfgs):
    """WordPress の社の鍵が投稿者の権限だけか。広すぎる・届かないなら要対応"""
    wps = [c for c in cfgs.values() if is_wp(c)]
    if not wps:
        print("WPBRIDGE_OK=unset")
        return []
    bad = []
    for c in wps:
        try:
            bad += [f"要対応: {b}" for b in role_problems(c)]
        except SystemExit as e:
            bad.append(f"要対応: {c['id']} の WordPress に鍵で入れません（鍵が無い・違う・接続できない）: {str(e)[:80]}")
    for b in bad:
        print(b)
    print("WPBRIDGE_OK=" + ("no" if bad else "yes"))
    return bad


def main():
    import sites as S
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        check({k: v for k, v in S.load_all().items() if not a.site or k == a.site})
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
