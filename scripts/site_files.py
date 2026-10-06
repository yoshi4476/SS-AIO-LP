# -*- coding: utf-8 -*-
"""配信先の直下のファイル（robots.txt・llms.txt・sitemap.xml）と統合の転送を、方式とホストに合わせて置く・直す。

**なぜ要るか**: publish.py は「既にある」sitemap.xml・llms.txt に記事を足すだけで、先方に無ければ作らなかった。
robots.txt は本番を読んで知らせるだけで、AI のクローラーが塞がれていても直す工程が無かった。
統合の301は Cloudflare Pages の _redirects にしか書かず、Vercel・Netlify・Apache の配信先では転送が効かなかった。
どれも「人が気づいて site_change で直す」前提で、お客様の社では誰も気づかないまま残る。

  ensure(cfg, dest, pages)   … 配信のたびに publish.py が書き出しの前に呼ぶ（無ければ作る・塞がれていれば直す）
  add_redirect(cfg, dest, …) … retract.py が統合した記事の旧URLを、配信先のホストが読む形で書く

直さないもの（知らせるだけ）:
  - 生成コード（app/robots.ts・sitemap.ts・Hugo の layouts/robots.txt など）で作る社。ファイルを置くと二重になる
  - 先方が名前を挙げて塞いだ AI クローラー（先方の判断。名指しの組には触らない）
  - Googlebot まで塞いだ robots.txt（公開前のサイトの可能性がある）
  - CDN（Cloudflare 等）の遮断。ファイルの手前で落ちるので、ファイルでは直らない（ai_crawler_check が知らせる）
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 許可を確かめる AI のクローラー（回答用・学習用）。Googlebot は検索の前提なので別に見る
AI_AGENTS = ("OAI-SearchBot", "ChatGPT-User", "GPTBot", "ClaudeBot", "Claude-SearchBot",
             "PerplexityBot", "Google-Extended", "Bingbot")
# sitemap.xml を作ってよい方式（ページを管制塔が書き出す方式）。Next.js・Markdown の社は先方のビルドが作る
SITEMAP_TYPES = ("external-html", "ftp", "zip")
HOSTS = ("cloudflare", "netlify", "vercel", "apache", "meta")
MARK = "管制塔"
SKIP_DIRS = {".git", "node_modules", ".next", "out", "dist", "build", "public", "static", "site", ".publish-work"}


def public_root(cfg, dest: Path):
    """ドメインの直下として公開されるフォルダ（search_connect と同じ見分け方）。公開ファイルの目印が1つも無い
    Hugo の社は static/ が公開の元（public/ はビルドの出力なので、置いても次のビルドで消える）"""
    import search_connect
    dest = Path(dest)
    if (cfg.get("public_dir") is None and (dest / "static").is_dir()
            and not any((dest / r / m).is_file() for r in search_connect.ROOTS for m in search_connect.MARKERS)):
        return dest / "static"
    return search_connect.public_root(cfg, dest)


def find_public(dest: Path, name):
    import publish
    return publish._public_file(Path(dest), name)


def generated(dest: Path, stem):
    """そのファイルをコードで作っている配信先か（Next.js の app/robots.ts、Astro の robots.txt.ts、Hugo の layouts/robots.txt）"""
    dest = Path(dest)
    if stem == "sitemap" and any((dest / n).is_file() for n in ("hugo.toml", "hugo.yaml", "config.toml")):
        return True
    rx = re.compile(rf"^{stem}(\.txt|\.xml)?\.(ts|tsx|js|jsx|mjs)$|^{stem}\.(txt|xml)$")
    for top, dirs, files in os.walk(dest):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if Path(top) == dest:
            continue                      # 直下の robots.txt は公開ファイルそのもの（生成ではない）
        if any(rx.match(f) for f in files):
            return True
    return False


# ---------------------------------------------------------------- robots.txt

def fix_robots(text, paths=("/",)):
    """(直した本文, 足した AI クローラー, 先方が名指しで塞いだもの, 触らなかった理由)。

    「User-agent: *」の組で塞がれている AI クローラーにだけ、名前の組を足す。名前の組は * の組の規則を
    写し、記事の場所を塞ぐ行だけ外す（* の組の他の制限は同じまま）。名指しで塞がれたものは先方の判断として触らない。
    Googlebot まで塞がれていれば、公開前のサイトかもしれないので何もしない"""
    import ai_crawler_check as AC
    if not all(AC.robots_allows(text, "Googlebot", p) for p in paths):
        return text, [], [], "Googlebot も塞いでいる（公開前の可能性があるので触らない）"
    groups = AC._groups(text)
    named = {a for ags, _ in groups for a in ags}
    blocked = [a for a in AI_AGENTS if not all(AC.robots_allows(text, a, p) for p in paths)]
    by_name = [a for a in blocked if a.lower() in named]
    need = [a for a in blocked if a.lower() not in named]
    if not need:
        return text, [], by_name, ""
    star = [r for ags, rs in groups if "*" in ags for r in rs]
    keep = [(allow, pat) for allow, pat in star
            if allow or not any(AC._match_len(pat, p) >= 0 for p in paths)]
    lines = [f"# AI 検索のクローラーを許可（{MARK}。* の組と同じ制限から、記事の場所を塞ぐ行だけ外す）"]
    lines += [f"User-agent: {a}" for a in need] + ["Allow: /"]
    lines += [f"{'Allow' if allow else 'Disallow'}: {pat}" for allow, pat in keep if pat != "/"]
    new = text.rstrip("\n") + "\n\n" + "\n".join(lines) + "\n"
    if not all(AC.robots_allows(new, a, p) for a in need for p in paths):
        return text, [], by_name, "足しても許可にならない（書き方が読めない）"
    return new, need, by_name, ""


def new_robots(cfg, has_sitemap, has_llms):
    origin = f"https://{cfg['domain']}"
    out = ["User-agent: *", "Allow: /", ""]
    if has_sitemap:
        out.append(f"Sitemap: {origin}/sitemap.xml")
    if has_llms:
        out.append(f"# AI向けのサイト案内: {origin}/llms.txt")
    return "\n".join(out).rstrip("\n") + "\n"


def article_paths(cfg):
    pre = (cfg.get("url_prefix") or "").rstrip("/")
    return ("/", f"{pre}/x/") if pre else ("/",)


# ---------------------------------------------------------------- llms.txt・sitemap.xml

def new_llms(cfg):
    return f"# {cfg.get('name') or cfg['domain']}\n> {cfg.get('name') or cfg['domain']}の記事の一覧（AI向けのサイト案内）\n\n## 記事\n"


def new_sitemap(cfg, pages: Path = None):
    """空の sitemap.xml。配信済みの記事（pages/<slug>/index.html）があれば載せておく（作った回に既存の記事が漏れない）"""
    import sites as S
    rows = [f"  <url>\n    <loc>https://{cfg['domain']}/</loc>\n  </url>\n"]
    if pages and Path(pages).is_dir() and cfg.get("url_prefix"):
        for f in sorted(Path(pages).glob("*/index.html")):
            slug = f.parent.name
            t = f.read_text(encoding="utf-8", errors="replace")
            d = re.search(r'"datePublished":\s*"(\d{4}-\d{2}-\d{2})', t)
            url = S.article_url(cfg, {"slug": slug, "category": ""})
            rows.append(f"  <url>\n    <loc>{url}</loc>\n" + (f"    <lastmod>{d.group(1)}</lastmod>\n" if d else "") + "  </url>\n")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(rows) + "</urlset>\n")


def valid(name, data: bytes):
    """取ってきた中身がそのファイルとして読めるか。HTTPS の取得では、無いページ（200 で返る HTML）が混ざる"""
    t = data.decode("utf-8", "replace").lstrip("﻿").lstrip()
    if name == "sitemap.xml":
        return "<urlset" in t[:2000] or "<sitemapindex" in t[:2000]
    if name == "article-manifest.json":
        try:
            return isinstance(json.loads(t), dict)
        except ValueError:
            return False
    return not t[:200].lower().startswith(("<!doctype", "<html", "<?xml", "<head"))


def ensure(cfg, dest, pages=None, write=True):
    """配信のたびに、書き出しの前に呼ぶ。作った・直したファイルを返す（FTP の社は上げる一覧へ足す）。
    pages は記事のページを置くフォルダ（sitemap.xml を作る回に、配信済みの記事を載せるため）"""
    dest = Path(dest)
    t = cfg.get("type")
    if t not in ("external-md", "external-html", "nextjs-json", "ftp", "zip"):
        return []
    root = public_root(cfg, dest)
    touched = []

    def put(p: Path, text, why):
        if write:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="\n")
        touched.append(p)
        print(f"  {why}: {p.relative_to(dest).as_posix()}")

    lt = find_public(dest, "llms.txt")
    if lt is None and not generated(dest, "llms"):
        put(root / "llms.txt", new_llms(cfg), "llms.txt が無いので作りました")
    sm = find_public(dest, "sitemap.xml")
    if sm is None and t in SITEMAP_TYPES and not generated(dest, "sitemap"):
        put(root / "sitemap.xml", new_sitemap(cfg, pages), "sitemap.xml が無いので作りました")
    # FTP の社で、サーバーに robots.txt のファイルが無いのに本番が返す（CMS・CDN が作る）なら触らない
    if (dest / "_robots_dynamic").is_file():
        return touched
    rb = find_public(dest, "robots.txt")
    if rb is None:
        if not generated(dest, "robots"):
            has_sm = find_public(dest, "sitemap.xml") is not None or any(p.name == "sitemap.xml" for p in touched)
            has_lt = find_public(dest, "llms.txt") is not None or any(p.name == "llms.txt" for p in touched)
            put(root / "robots.txt", new_robots(cfg, has_sm, has_lt), "robots.txt が無いので作りました")
        return touched
    cur = rb.read_text(encoding="utf-8", errors="replace")
    new, added, by_name, why = fix_robots(cur, article_paths(cfg))
    if added:
        put(rb, new, f"robots.txt で塞がれていた AI クローラー（{'・'.join(added)}）を許可しました")
    if by_name:
        print(f"要対応: {cfg.get('name', cfg['id'])} の robots.txt が {'・'.join(by_name)} を名前を挙げて塞いでいます"
              "（先方の判断なので直していません。AI 検索に出したいなら先方に確かめてください）")
    if why:
        print(f"  robots.txt は直していません: {why}")
    return touched


# ---------------------------------------------------------------- 統合の転送

def redirect_host(cfg, dest: Path):
    """転送をどの形で書くか。sites/<id>.json の redirect_host が最優先、無ければ配信先のファイルで見分ける"""
    h = str(cfg.get("redirect_host") or "").lower()
    if h in HOSTS:
        return h
    dest = Path(dest)
    if find_public(dest, "_redirects"):
        return "cloudflare"
    if (dest / "vercel.json").is_file():
        return "vercel"
    if (dest / "netlify.toml").is_file():
        return "netlify"
    if any((dest / n).is_file() for n in ("wrangler.toml", "wrangler.json", "wrangler.jsonc")):
        return "cloudflare"
    if find_public(dest, ".htaccess"):
        return "apache"
    return "cloudflare"


def redirects_file(cfg, dest: Path):
    """_redirects の置き場。既にあればそこ、無ければ公開フォルダ（Next.js の静的書き出しは public/）"""
    f = find_public(dest, "_redirects")
    if f:
        return f
    if (cfg.get("images_dir") or "").startswith("public/"):
        return Path(dest) / "public" / "_redirects"
    # 公開ファイル（index.html・robots.txt など）が見つかったフォルダ。見つからなければ直下（public/ はビルドの出力のことがある）
    import search_connect
    root = public_root(cfg, dest)
    if any((root / m).is_file() for m in search_connect.MARKERS):
        return root / "_redirects"
    return Path(dest) / "_redirects"


def add_redirect(cfg, dest, src, dst, note, write=True):
    """src（同じサイトのパス）を dst へ 301 で送る行を、配信先のホストが読む形で足す。触ったファイルを返す（無ければ None）"""
    dest = Path(dest)
    host = redirect_host(cfg, dest)
    if host == "vercel":
        f = dest / "vercel.json"
        data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        rows = data.setdefault("redirects", [])
        have = {r.get("source") for r in rows if isinstance(r, dict)}
        add = [s for s in dict.fromkeys((src, src.rstrip("/") or "/")) if s not in have]
        if not add:
            return None
        rows += [{"source": s, "destination": dst, "statusCode": 301} for s in add]
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    elif host == "netlify":
        f = dest / "netlify.toml"
        cur = f.read_text(encoding="utf-8") if f.is_file() else ""
        if f'from = "{src}"' in cur:
            return None
        text = (cur.rstrip("\n") + "\n\n" if cur else "") + (
            f'# {note}（{MARK}）\n[[redirects]]\n  from = "{src}"\n  to = "{dst}"\n  status = 301\n  force = true\n')
    elif host == "apache":
        f = find_public(dest, ".htaccess") or public_root(cfg, dest) / ".htaccess"
        cur = f.read_text(encoding="utf-8") if f.is_file() else ""
        line = f"Redirect 301 {src} https://{cfg['domain']}{dst}"
        if line in cur:
            return None
        text = (cur.rstrip("\n") + "\n" if cur else "") + f"# {note}（{MARK}）\n{line}\n"
    elif host == "meta":
        # 転送の仕組みを持たないホスト（GitHub Pages 等）: 旧URLに、新しいURLを指す正規URL＋即時の移動だけのページを置く
        import publish
        if cfg.get("type") != "external-html":
            print(f"要対応: {cfg.get('name', cfg['id'])} は転送を書けません（redirect_host=meta は external-html だけ）: {src} → {dst}")
            return None
        slug = src.rstrip("/").rsplit("/", 1)[-1]
        f = dest / publish.page_dir(cfg) / slug / "index.html"
        to = f"https://{cfg['domain']}{dst}"
        text = ('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
                f'<title>移動しました</title><link rel="canonical" href="{to}">'
                f'<meta name="robots" content="noindex"><meta http-equiv="refresh" content="0; url={to}">'
                f'</head><body><p><a href="{to}">{to}</a> へ移動しました。</p></body></html>\n')
        if f.is_file() and f.read_text(encoding="utf-8") == text:
            return None
    else:
        f = redirects_file(cfg, dest)
        cur = f.read_text(encoding="utf-8") if f.is_file() else "# Cloudflare Pages のリダイレクト定義\n"
        line = f"{src} {dst} 301"
        if line in cur:
            return None
        text = cur.rstrip("\n") + f"\n# {note}\n{line}\n"
    if write:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline="\n")
    return f
