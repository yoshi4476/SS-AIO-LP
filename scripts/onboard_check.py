# -*- coding: utf-8 -*-
"""最初の接続の点検（onboard check）: 配った後の本番を見て、「先方の作り次第」の項目が本当に動いているかを確かめる。

**なぜ要るか**: 方式×機能の表（data/capabilities.json）の partial には、こちらでは確かめられないものがある。
external-md の先方のビルドが、配ったまとめのページ（pages_dir）やフロントマターの alternates・robots・image を
HTML・head に出すか／Next.js の記事ページが配った alternates や動画を使うか／先方の sitemap・llms.txt・robots.txt・
計測タグ・CSP・WordPress のテーマがフィルターを通すか。配る側のコードを読んでも分からず、本番を見るしかない。
運用者の方針（2026-10-06）は「どの納品方式でも全部動く・人の手間がない」。動いていない所は、先方に頼む1文まで出す。

  python scripts/onboard_check.py --site <id>    # 1社
  python scripts/onboard_check.py --all          # 全社（週次 findings・ヒアリングの登録直後）

守ること:
  - 本番は読むだけ。試験のために記事を出さない（記事が要る項目は公開済みの記事で確かめる。無ければ「確かめる記事がまだ無い」）
  - 1社あたりの要求は BUDGET 回まで（重くしない・ボット扱いされない）
  - 「出ていない」と言う前に逆を探す: sitemap に無い記事は、本番で開ける（200）ものだけを抜けと数える。
    まとめのページが404でも、配った形跡（llms.txt・sitemap・配信の控え）が無ければ「未配信」として要対応にしない
  - 結果は自社は data/onboard/<id>.json（コミットする）、お客様は data/clients/<id>/onboard.json（.gitignore。public に置かない）
  - 先方に頼む文は data/onboard_hints.json（方式ごと・静的サイト生成器ごと）。点検の項目と表の機能は CHECKS で結ぶ

印（CLAUDE.md 8.7）: 見つかったら「要対応: <社> <機能>: <何が出ていない>・<先方に頼むこと>」と ONBOARD_OK=no、
無ければ ONBOARD_OK=yes、お客様も自社も無ければ unset。本番に1回も届かず検査できなければ ONBOARD_OK=unknown・終了コード1。
"""
import argparse
import html as _html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

HINTS = ROOT / "data" / "onboard_hints.json"
CAPS = ROOT / "data" / "capabilities.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 ss-onboard-check/1.0"}
BUDGET = 50
TIMEOUT = 20
ALL = ("self-static", "external-md", "external-html", "nextjs-json", "wordpress", "ftp", "zip")
GIT_FTP = ("external-md", "external-html", "nextjs-json", "ftp", "zip")
# 点検の項目 → (表の機能, 確かめる方式, 確かめる中身)。表の partial のうち、ここに挙がる方式のセルの note に
# 「onboard_check で確かめる（中身）」を書く（tests/gates_history_h35.py が表と食い違わないかを見る）
CHECKS = {
    "agg_compare": (("compare",), ALL, "/compare/ が開けて中身が出る"),
    "agg_topics": (("topics",), ALL, "/topics/ が開けて中身が出る"),
    "agg_area": (("area",), ALL, "/area/ が開けて中身が出る"),
    "agg_season": (("season_feature",), ALL, "季節の特集のページが開けて中身が出る"),
    "agg_industry": (("industry_hub",), ALL, "/industry/ が開けて中身が出る"),
    "agg_glossary": (("glossary",), ALL, "/glossary/ が開けて中身が出る"),
    "agg_i18n": (("i18n",), ALL, "訳のページ（/en/ など）が開けて中身が出る"),
    "hub_nav": (("industry_hub", "glossary"), ("wordpress",), "トップのナビから /industry/・/glossary/ へ辿れる"),
    "ld_blogposting": (("ld_blogposting",), ALL, "記事の head に BlogPosting の JSON-LD"),
    "ld_faqpage": (("ld_faqpage",), ALL, "FAQ のある記事の head に FAQPage の JSON-LD"),
    "robots_meta": (("search_preview",), ALL, "記事の head に robots の meta（max-image-preview 等・noindex でない）"),
    "sitemap_images": (("search_preview",), ALL, "sitemap.xml に記事の画像の行（image:loc）"),
    "og_image": (("thumbnail_photo",), ALL, "記事の og:image が絶対URLで開ける"),
    "hreflang": (("i18n",), ALL, "訳のある記事の head に hreflang"),
    "sitemap": (("sitemap",), ALL, "sitemap.xml が開けて、本番で開ける記事が全部載る"),
    "llms_txt": (("llms_txt",), ALL, "llms.txt が開けて、sitemap の記事が全部載る"),
    "robots_txt": (("robots_txt",), ALL, "robots.txt が AI クローラーを止めていない"),
    "measure_tag": (("measurement",), ALL, "記事に GA4 の測定ID（計測タグ）が出る"),
    "measure_entry": (("measurement",), ALL, "記事内の入口（cta-inline）と、その計測のスクリプトが残る"),
    "indexnow_key": (("indexnow",), ALL, "IndexNow の鍵ファイルが直下で返る"),
    "bing_auth": (("bing",), ALL, "BingSiteAuth.xml が直下で返る（同意の社）"),
    "video_embed": (("video_embed",), ALL, "動画のある記事に埋め込みが出て、CSP が YouTube を止めていない"),
    "merge_301": (("merge_redirect",), ALL, "統合した記事の旧URLが301で残す記事へ飛ぶ"),
    "wp_bridge": (("quality_gate",), ("wordpress",), "橋渡し（mu-plugin）の版と自己更新"),
    # テーマ（PHP）由来の表示速度とサイト構成の変更は、FTP の接続情報がある社だけ自動で直せる
    "wp_ftp": (("speed_fix", "site_change"), ("wordpress",), "FTP の接続情報があり、テーマの速度・構成も自動で直せる"),
}
AGG_CHECK = {"compare": "agg_compare", "topics": "agg_topics", "area": "agg_area", "season": "agg_season",
             "industry": "agg_industry", "glossary": "agg_glossary", "i18n": "agg_i18n", "i18n_index": "agg_i18n"}
GENERATORS = (("hugo", "hugo"), ("jekyll", "jekyll"), ("astro", "astro"), ("eleventy", "eleventy"),
              ("gatsby", "gatsby"), ("docusaurus", "docusaurus"), ("wordpress", "wordpress"), ("next.js", "next"),
              ("nuxt", "nuxt"))
FAQ_RX = re.compile(r"^#{2,3}\s*(よくある質問|FAQ|Q&A)", re.M | re.I)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def _http(url, follow=True, head=False):
    """(状態, ヘッダー{小文字}, 本文, 最後のURL)。届かなければ (None, {}, "", url)"""
    op = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    try:
        req = urllib.request.Request(url, headers=UA, method="HEAD" if head else "GET")
        with op.open(req, timeout=TIMEOUT) as r:
            body = "" if head else r.read(1500000).decode("utf-8", "ignore")
            return r.status, {k.lower(): v for k, v in r.headers.items()}, body, r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, "", url
    except Exception:
        return None, {}, "", url


fetch = _http   # 門は偽の HTTP に差し替える


class Ctx:
    """1社分の要求（予算つき・同じURLは1回だけ）"""

    def __init__(self, cfg):
        self.cfg, self.used, self.reached, self.cache = cfg, 0, 0, {}
        self.origin = f"https://{cfg['domain']}"

    def get(self, url, follow=True, head=False):
        if url.startswith("/"):
            url = self.origin + url
        k = (url, follow, head)
        if k in self.cache:
            return self.cache[k]
        if self.used >= BUDGET:
            return None, {}, "", url
        self.used += 1
        r = fetch(url, follow=follow, head=head)
        if r[0] is not None:
            self.reached += 1
        self.cache[k] = r
        return r


def key(u):
    """URL の比べ方（ホストは小文字・末尾スラッシュ・クエリ・断片を無視）"""
    p = urllib.parse.urlsplit(u.strip())
    return p.netloc.lower() + (p.path.rstrip("/") or "/")


def out_path(sid):
    import sites as S
    return (ROOT / "data" / "clients" / sid / "onboard.json") if S.is_client(sid) else (ROOT / "data" / "onboard" / f"{sid}.json")


def load_hints():
    try:
        return json.loads(HINTS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def generator(html):
    """ページを作った道具（meta generator・Next.js の印）。分からなければ ""。先方に頼む文を道具に合わせる"""
    m = re.search(r"<meta\b[^>]*name=[\"']generator[\"'][^>]*content=[\"']([^\"']+)", html or "", re.I) \
        or re.search(r"<meta\b[^>]*content=[\"']([^\"']+)[\"'][^>]*name=[\"']generator[\"']", html or "", re.I)
    g = (m.group(1) if m else "").lower()
    for word, name in GENERATORS:
        if word in g:
            return name
    if "/_next/" in (html or "") or "__NEXT_DATA__" in (html or ""):
        return "next"
    return ""


def ask(hints, check_id, method, gen="", **fmt):
    """先方に頼む1文（方式ごと・道具ごと）"""
    h = hints.get(check_id) or {}
    v = h.get(method, h.get("_", ""))
    if isinstance(v, dict):
        v = v.get(gen) or v.get("_", "")
    try:
        return str(v).format(**fmt)
    except (KeyError, IndexError):
        return str(v)


# ---------- ページの中身を読む ----------

def ld_types(html):
    """JSON-LD の @type（@graph・入れ子も）"""
    out = set()

    def walk(x):
        if isinstance(x, dict):
            t = x.get("@type")
            for v in (t if isinstance(t, list) else [t]):
                if isinstance(v, str):
                    out.add(v)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for m in re.finditer(r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", html or "", re.S | re.I):
        try:
            walk(json.loads(m.group(1).strip()))
        except ValueError:
            continue
    return out


def _attrs(tag):
    return {k.lower(): _html.unescape(v) for k, v in re.findall(r"([\w:-]+)\s*=\s*[\"']([^\"']*)[\"']", tag)}


def metas(html):
    """[{属性}]（meta タグ）"""
    return [_attrs(t) for t in re.findall(r"<meta\b[^>]*>", html or "", re.I)]


def robots_meta(html):
    vals = [m.get("content", "") for m in metas(html) if m.get("name", "").lower() == "robots"]
    return ", ".join(vals) if vals else None


def og_image(html):
    for m in metas(html):
        if m.get("property", "").lower() == "og:image" or m.get("name", "").lower() == "og:image":
            return m.get("content", "")
    return None


def hreflangs(html):
    out = set()
    for t in re.findall(r"<link\b[^>]*>", html or "", re.I):
        a = _attrs(t)
        if a.get("rel", "").lower() == "alternate" and a.get("hreflang"):
            out.add(a["hreflang"].lower())
    return out


def csp_of(headers, html):
    """CSP（ヘッダー、無ければ meta http-equiv）。無ければ ""。"""
    v = headers.get("content-security-policy", "")
    if not v:
        for m in metas(html):
            if m.get("http-equiv", "").lower() == "content-security-policy":
                v = m.get("content", "")
                break
    return v


def csp_blocks_youtube(policy):
    if not policy:
        return False
    pol = {p.strip().split(" ", 1)[0].lower(): p.strip().split()[1:] for p in policy.split(";") if p.strip()}
    rule = pol.get("frame-src") or pol.get("child-src") or pol.get("default-src")
    if rule is None:
        return False
    return not any(s in ("*", "https:") or "youtube-nocookie.com" in s or s.endswith("youtube.com") for s in rule)


def sitemap_locs(ctx, wp=False):
    """(状態, [loc], 本文の束)。sitemap の索引なら子を辿る（記事の子を先に・6本まで）"""
    st, _, body, _ = ctx.get("/sitemap.xml")
    if st != 200 and wp:
        st, _, body, _ = ctx.get("/wp-sitemap.xml")
    if st != 200:
        return st, [], ""
    bodies = [body]
    if "<sitemapindex" in body:
        kids = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
        kids.sort(key=lambda u: (not re.search(r"post|blog|article|page", u), u))
        bodies = [ctx.get(_html.unescape(u))[2] for u in kids[:6]]
    text = "\n".join(bodies)
    return st, [_html.unescape(u) for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)], text


# ---------- 社ごとの材料 ----------

def articles(cfg, ctx):
    """公開の基準を満たすその社の記事 [{slug, url, date, faq, title}]（新しい順）。WordPress は橋渡しのパーマリンク"""
    import sites as S
    import wp_bridge
    rows = []
    wp_urls = {}
    if cfg.get("type") == "wordpress":
        st, _, body, _ = ctx.get("/wp-json/ss/v1/urls")
        try:
            data = json.loads(body) if st == 200 else {}
        except ValueError:
            data = {}
        wp_urls = {r.get("slug"): r.get("url") for r in (data.get("urls") or []) if isinstance(r, dict) and r.get("type") == "post"}
    for meta, body, _p in wp_bridge._site_articles(cfg):
        slug = meta.get("slug") or Path(_p).stem
        m = dict(meta, slug=slug)
        if cfg.get("type") == "wordpress":
            url = wp_urls.get(slug)
            if not url:
                continue
        else:
            url = S.article_url(cfg, m)
        rows.append({"slug": slug, "url": url, "date": str(meta.get("date") or ""), "title": str(meta.get("title") or ""),
                     "faq": bool(FAQ_RX.search(body or ""))})
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def expected_pages(cfg, live):
    """管制塔が作るまとめのページ（aggregate_pages.collect。build.py と同じ関数）"""
    import aggregate_pages as AP
    return AP.collect(cfg, live=live)


def delivered_paths(cfg):
    """配った控え（ftp・zip の data/aggregate/<id>.json）"""
    import aggregate_pages as AP
    return set(AP.load_state(cfg["id"]).get("paths") or [])


def videos(cfg):
    import client_private as CP           # お客様の社の記事の行は非公開のリポジトリ
    d = CP.load_videos()
    return {k: v["youtube"] for k, v in d.items() if isinstance(v, dict) and v.get("site") == cfg["id"] and v.get("youtube")}


def translations(cfg):
    """訳のある記事 {slug: [言語]}（sites/<id>.json の languages を指示した社だけ）"""
    langs = cfg.get("languages") or []
    if not langs:
        return {}
    import i18n
    out = {}
    for lg, rows in i18n.translated().items():
        if lg in langs:
            for slug in rows:
                out.setdefault(slug, []).append(lg)
    return out


def merges(cfg):
    """統合した記事の (旧パス, 残す記事のパス)。新しい順に2組"""
    out = []
    if cfg.get("type") == "self-static":
        f = ROOT / "site" / "_redirects"
        cats = "|".join(map(re.escape, cfg.get("categories") or {})) or "x^"
        for ln in (f.read_text(encoding="utf-8").splitlines() if f.is_file() else []):
            m = re.match(rf"^(/(?:{cats})/[a-z0-9-]+/)\s+(/(?:{cats})/[a-z0-9-]+/)\s+30[18]\s*$", ln.strip())
            if m:
                out.append((m.group(1), m.group(2)))
        return out[::-1][:2]
    f = ROOT / "data" / "retractions.jsonl"
    for ln in (f.read_text(encoding="utf-8").splitlines() if f.is_file() else []):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("site") == cfg["id"] and r.get("done_at") and r.get("from") and r.get("to"):
            out.append((r["from"], r["to"]))
    return out[::-1][:2]


def indexnow_key():
    import notify_indexnow as NI
    return NI.find_key(NI.load_env())


# ---------- 点検 ----------

def run_site(cfg, hints=None, today=None):
    """1社を点検して {"site", "checks": [...], "reached"} を返す"""
    import sites as S
    import ai_crawler_check as AC
    hints = load_hints() if hints is None else hints
    today = today or date.today()
    t = cfg.get("type", "")
    ctx = Ctx(cfg)
    res = []
    gen = [""]

    def add(cid, status, detail="", feature=None, hint=None):
        feats = CHECKS[cid][0]
        res.append({"id": cid, "feature": feature or feats[0], "status": status, "detail": detail,
                    "ask": ask(hints, hint or cid, t, gen[0], domain=cfg["domain"], site=cfg["id"]) if status == "ng" else ""})

    no_art = "公開済みの記事がまだありません（記事を配った後の点検で確かめる）"

    # 入口: トップ・robots.txt・sitemap・llms.txt
    st_home, _, home, _ = ctx.get("/")
    gen[0] = generator(home)
    st_rb, _, robots, _ = ctx.get("/robots.txt")
    st_sm, locs, sm_text = sitemap_locs(ctx, wp=t == "wordpress")
    st_ll, _, llms, _ = ctx.get("/llms.txt")
    if not ctx.reached:
        return {"site": cfg["id"], "checks": [], "reached": 0, "requests": ctx.used}
    sm_keys = {key(u) for u in locs}
    llms_keys = {key(u) for u in re.findall(r"https?://[^\s)\]>\"']+", llms or "")} if st_ll == 200 else set()

    arts = articles(cfg, ctx)
    live = [a for a in arts if key(a["url"]) in sm_keys] if sm_keys else []
    if t == "wordpress":
        live = arts                                    # 橋渡しの一覧に載った＝公開済み
    old = [a for a in arts if a["date"][:10] <= (today - timedelta(days=2)).isoformat()]

    # robots.txt
    if st_rb == 200:
        path = urllib.parse.urlsplit(live[0]["url"]).path if live else "/"
        blocked = sorted({ag for ag in AC.ROBOTS_AGENTS for p in ("/", path) if not AC.robots_allows(robots, ag, p)})
        add("robots_txt", "ng" if blocked else "ok",
            f"robots.txt が {', '.join(blocked)} を止めています" if blocked else "AI クローラーを止めていない")
    elif st_rb == 404:
        add("robots_txt", "ok", "robots.txt が無い（全部許可と同じ）")
    else:
        add("robots_txt", "unknown", f"robots.txt を読めません（HTTP {st_rb}）")

    # sitemap.xml: 本番で開けるのに載っていない記事だけを抜けと数える（未配信の記事を抜けと言わない）
    if st_sm != 200:
        add("sitemap", "ng", f"sitemap.xml が開けません（HTTP {st_sm}）")
    elif not arts:
        add("sitemap", "skip", no_art)
    elif t != "wordpress":
        gaps = []
        for a in [a for a in old if key(a["url"]) not in sm_keys][:3]:
            if ctx.get(a["url"])[0] == 200:
                gaps.append(a["slug"])
        add("sitemap", "ng" if gaps else "ok",
            f"本番で開ける記事が sitemap.xml に載っていません（{', '.join(gaps)}）" if gaps else f"記事 {len(live)}本が載る")
    else:
        add("sitemap", "ok" if locs else "ng", f"記事 {len(locs)}行" if locs else "sitemap.xml に URL がありません")

    # llms.txt
    if st_ll != 200:
        add("llms_txt", "ng", f"llms.txt が開けません（HTTP {st_ll}）")
    elif not live:
        add("llms_txt", "skip", no_art)
    else:
        miss = [a["slug"] for a in live if key(a["url"]) not in llms_keys]
        add("llms_txt", "ng" if miss else "ok",
            f"sitemap の記事 {len(miss)}本が llms.txt に載っていません（{', '.join(miss[:3])}）" if miss
            else f"記事 {len(live)}本が載る")

    # 記事の head（新しい記事と、FAQ のある新しい記事）
    samples = []
    for a in ([live[0]] if live else []) + [a for a in live if a["faq"]][:1]:
        if a not in samples:
            samples.append(a)
    pages = []
    for a in samples:
        st, hd, body, _ = ctx.get(a["url"])
        if st == 200:
            pages.append((a, hd, body))
    if not pages:
        for cid in ("ld_blogposting", "ld_faqpage", "robots_meta", "og_image", "measure_tag"):
            add(cid, "skip", no_art if not live else "記事のページを開けません")
    else:
        if not gen[0]:
            gen[0] = generator(pages[0][2])
        nob = [a["slug"] for a, _, b in pages if not ({"BlogPosting", "Article", "NewsArticle"} & ld_types(b))]
        add("ld_blogposting", "ng" if nob else "ok",
            f"記事の head に BlogPosting の JSON-LD がありません（{', '.join(nob)}）" if nob else "出ている")
        faq = [(a, b) for a, _, b in pages if a["faq"]]
        nofaq = [a["slug"] for a, b in faq if "FAQPage" not in ld_types(b)]
        add("ld_faqpage", "skip" if not faq else ("ng" if nofaq else "ok"),
            "FAQ のある記事がまだありません" if not faq else
            (f"FAQ のある記事に FAQPage の JSON-LD がありません（{', '.join(nofaq)}）" if nofaq else "出ている"))
        a0, _, b0 = pages[0]
        rm = robots_meta(b0)
        if rm and re.search(r"\b(noindex|none)\b", rm, re.I):
            add("robots_meta", "ng", f"記事が noindex です（{a0['slug']}: {rm}）")
        elif not rm or "max-image-preview" not in rm.lower():
            add("robots_meta", "ng", f"記事の head に robots の meta（max-image-preview 等）がありません（{a0['slug']}）")
        else:
            add("robots_meta", "ok", rm)
        og = og_image(b0)
        if not og:
            add("og_image", "ng", f"記事の head に og:image がありません（{a0['slug']}）")
        elif not og.startswith("http"):
            add("og_image", "ng", f"og:image が絶対URLではありません（{og[:60]}）")
        else:
            st = ctx.get(og, head=True)[0]
            if st == 405:
                st = ctx.get(og)[0]
            add("og_image", "ok" if st == 200 else ("unknown" if st is None else "ng"),
                f"og:image が開けません（HTTP {st}・{og[:60]}）" if st not in (200, None) else og[:80])
        gid = str(cfg.get("ga4_measurement_id") or "").strip()
        bodies = "\n".join(b for _, _, b in pages)
        tag = (gid in bodies) if gid else bool(re.search(r"\bG-[A-Z0-9]{6,}\b|\bGTM-[A-Z0-9]{4,}\b|googletagmanager\.com", bodies))
        need_ss = bool(gid) and t in ("wordpress", "ftp", "zip")
        if not tag:
            add("measure_tag", "ng", f"記事に GA4 の計測タグ{'（' + gid + '）' if gid else ''}がありません")
        elif need_ss and 'id="ss-measure"' not in bodies:
            add("measure_tag", "ng", "記事に計測のスクリプト（ss-measure）がありません（テーマがフッターのフックを呼んでいない）")
        else:
            add("measure_tag", "ok", gid or "計測タグあり")
        if (cfg.get("cta_inline") or {}).get("url"):
            have = [b for _, _, b in pages if "cta-inline" in b]
            if not have:
                add("measure_entry", "ng", "記事に入口（cta-inline）が出ていません（先方の雛形が本文の HTML を落としている）")
            elif not any("inline_tool_view" in b for b in have):
                add("measure_entry", "ng", "入口はあるが計測のスクリプトが消えています（本文の <script> を落としている）")
            else:
                add("measure_entry", "ok", "入口と計測のスクリプトが残る")

    # 画像のサイトマップ（search_preview）
    if st_sm == 200 and live:
        add("sitemap_images", "ok" if "<image:loc>" in sm_text else "ng",
            "画像の行あり" if "<image:loc>" in sm_text else "sitemap.xml に画像の行（image:loc）がありません")

    # hreflang（訳のある記事）
    tr = translations(cfg)
    if cfg.get("languages"):
        cand = [a for a in live if a["slug"] in tr]
        if not cand:
            add("hreflang", "skip", "訳のある公開済みの記事がまだありません")
        else:
            a = cand[0]
            st, _, b, _ = ctx.get(a["url"])
            miss = sorted(set(tr[a["slug"]]) - hreflangs(b)) if st == 200 else []
            add("hreflang", "unknown" if st != 200 else ("ng" if miss else "ok"),
                f"記事の head に hreflang（{', '.join(miss)}）がありません（{a['slug']}）" if miss else a["slug"])

    # 動画
    vids = videos(cfg)
    vlive = [a for a in live if a["slug"] in vids]
    if vlive:
        a = vlive[0]
        st, hd, b, _ = ctx.get(a["url"])
        pol = csp_of(hd, b)
        if st != 200:
            add("video_embed", "unknown", f"動画のある記事を開けません（HTTP {st}）")
        elif csp_blocks_youtube(pol):
            add("video_embed", "ng", f"CSP の frame-src が YouTube を止めています（{a['slug']}）")
        elif vids[a["slug"]] not in b:
            # CSP は許している。配った中身に動画が無い（CSP が止めていた頃に配った）か、先方の記事ページが描かないか
            add("video_embed", "ng", f"動画のある記事に埋め込みが出ていません（{a['slug']}・CSP は YouTube を許している）",
                hint="video_missing")
        else:
            add("video_embed", "ok", a["slug"])

    # 統合の301
    for old_p, new_p in merges(cfg):
        st, hd, _, _ = ctx.get(old_p, follow=False)
        loc = urllib.parse.urlsplit(urllib.parse.urljoin(ctx.origin + old_p, hd.get("location", ""))).path
        if st is None:
            add("merge_301", "unknown", f"旧URLに届きません（{old_p}）")
        elif st in (301, 308) and loc.rstrip("/") == new_p.rstrip("/"):
            add("merge_301", "ok", f"{old_p} → {new_p}")
        elif st in (301, 302, 307, 308):
            add("merge_301", "ng", f"旧URL {old_p} の転送先が違います（HTTP {st} → {loc or '?'}・正しくは {new_p}）")
        else:
            add("merge_301", "ng", f"統合した記事の旧URL {old_p} が転送されません（HTTP {st}）")

    # IndexNow・Bing
    k = cfg.get("indexnow_key") or indexnow_key()
    if k:
        st, _, b, _ = ctx.get(f"/{k}.txt")
        add("indexnow_key", "ok" if st == 200 and b.strip() == k else ("unknown" if st is None else "ng"),
            "鍵ファイルが返る" if st == 200 and b.strip() == k else f"IndexNow の鍵ファイルが直下で返りません（HTTP {st}）")
    if cfg.get("bing_consent") is True or (t == "self-static" and (ROOT / "site" / "BingSiteAuth.xml").is_file()):
        st, _, b, _ = ctx.get("/BingSiteAuth.xml")
        good = st == 200 and "<user>" in b
        add("bing_auth", "ok" if good else ("unknown" if st is None else "ng"),
            "確認ファイルが返る" if good else f"BingSiteAuth.xml が直下で返りません（HTTP {st}）")

    # まとめのページ: 種類ごとに入口の1ページ。404 でも配った形跡が無ければ「未配信」
    try:
        exp = expected_pages(cfg, {a["slug"] for a in live} if live else None)
    except Exception as e:
        exp = []
        print(f"  {cfg['id']}: まとめのページを組めません（{type(e).__name__}: {str(e)[:60]}）")
    by_kind = {}
    for p in exp:
        cid = AGG_CHECK.get(p.get("kind"))
        if cid and (cid not in by_kind or len(p["path"]) < len(by_kind[cid]["path"])):
            by_kind[cid] = p
    sent = delivered_paths(cfg)
    for cid, p in sorted(by_kind.items()):
        st, _, b, _ = ctx.get(p["path"])
        title = p.get("title") or ""
        feat = {"i18n": "i18n", "i18n_index": "i18n"}.get(p["kind"])
        shown = st == 200 and (title and title in _html.unescape(b) or "ss-aggregate" in b)
        if shown:
            add(cid, "ok", p["path"], feat)
        elif st is None:
            add(cid, "unknown", f"{p['path']} に届きません", feat)
        else:
            url_k = key(ctx.origin + p["path"])
            evidence = url_k in llms_keys or url_k in sm_keys or p["path"] in sent
            if evidence or st == 200:
                add(cid, "ng", f"{p['path']} が" + ("開けますが中身が出ていません" if st == 200 else f"開けません（HTTP {st}）"), feat)
            else:
                add(cid, "skip", f"{p['path']} はまだ配っていません（次の配信で置く）", feat)
    if t == "wordpress" and st_home == 200:
        miss = [x for x in ("industry", "glossary") if any(p.get("kind") == x for p in exp) and f"/{x}/" not in home]
        add("hub_nav", "ng" if miss else "ok",
            f"トップのナビから {', '.join('/' + x + '/' for x in miss)} へ辿れません" if miss else "辿れる")

    # WordPress の橋渡し
    if t == "wordpress":
        import contextlib
        import io
        import wp_bridge
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                bad = wp_bridge.check({cfg["id"]: cfg})
            except Exception as e:
                bad = [f"要対応: 橋渡しを確かめられません（{type(e).__name__}）"]
        add("wp_bridge", "ng" if bad else "ok", "；".join(re.sub(r"^要対応:\s*", "", b) for b in bad)[:200] or "最新")
        import speed_fix
        has = speed_fix.has_ftp(cfg)
        add("wp_ftp", "ok" if has else "ng",
            "FTP の接続情報あり" if has else "FTP の接続情報が無く、テーマ由来の速度・構成は自動で直せません")
    return {"site": cfg["id"], "checks": res, "reached": ctx.reached, "requests": ctx.used, "generator": gen[0]}


NOTE_HEAD = "onboard_check で確かめる"


def caps_notes(caps):
    """表の partial のうち点検で確かめるセル {(機能, 方式): "onboard_check で確かめる（中身・中身）"}"""
    out = {}
    for cid, (feats, methods, what) in CHECKS.items():
        for f in feats:
            for m in methods:
                c = ((caps.get("features") or {}).get(f) or {}).get("cells", {}).get(m)
                if c and c.get("status") == "partial":
                    out.setdefault((f, m), [])
                    if what not in out[(f, m)]:
                        out[(f, m)].append(what)
    return {k: f"{NOTE_HEAD}（{'・'.join(v)}）" for k, v in out.items()}


def write_caps_notes():
    """表のセルの note に点検の中身を書く（前に書いた分は置き換える）。書いたセルの数"""
    caps = json.loads(CAPS.read_text(encoding="utf-8"))
    want, n = caps_notes(caps), 0
    for fid, f in caps["features"].items():
        for m, c in f["cells"].items():
            note = str(c.get("note") or "")
            # 点検の中身はいつも末尾に書く（中身に括弧が入れ子になるので、括弧ではなく印の位置で切る）
            base = (note[:note.index(NOTE_HEAD)] if NOTE_HEAD in note else note).rstrip()
            base = base[:-1] if base.endswith("。") and NOTE_HEAD in note else base
            new = base + ("。" if base and not base.endswith("。") else "") + want[(fid, m)] if (fid, m) in want else base
            if new != note:
                c["note"] = new
                n += 1
    CAPS.write_text(json.dumps(caps, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return n


def labels():
    try:
        caps = json.loads(CAPS.read_text(encoding="utf-8"))
        return {k: f.get("label", k) for k, f in caps["features"].items()}
    except (OSError, ValueError, KeyError):
        return {}


def todo_lines(cfg, result, labs=None):
    labs = labels() if labs is None else labs
    name = cfg.get("name") or cfg["id"]
    return [f"要対応: {name} {labs.get(c['feature'], c['feature'])}: {c['detail']}・{c['ask']}"
            for c in result["checks"] if c["status"] == "ng"]


def save(cfg, result):
    p = out_path(cfg["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {"site": cfg["id"], "type": cfg.get("type"), "domain": cfg.get("domain"),
            "at": datetime.now().strftime("%Y-%m-%d %H:%M"), "generator": result.get("generator", ""),
            "ok": not any(c["status"] == "ng" for c in result["checks"]), "requests": result.get("requests", 0),
            "checks": result["checks"]}
    p.write_text(json.dumps(body, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return p


def main(argv=None, cfgs=None):
    import sites as S
    ap = argparse.ArgumentParser(description="配った後の本番で、先方の作り次第の項目が動いているかを確かめる")
    ap.add_argument("--site", action="append", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-save", action="store_true", help="結果のファイルを書かない")
    ap.add_argument("--caps", action="store_true", help="表（data/capabilities.json）の note に点検の中身を書く")
    a = ap.parse_args(argv)
    if a.caps:
        print(f"表の note を書きました: {write_caps_notes()}セル")
        return 0
    cfgs = S.load_all() if cfgs is None else cfgs
    ids = [s for s in cfgs if s != "sample"] if a.all else a.site
    if not ids:
        ap.print_help()
        return 0
    unknown = [s for s in ids if s not in cfgs]
    if unknown:
        print(f"サイト設定が見つかりません: {', '.join(unknown)}")
        return 1
    hints, labs = load_hints(), labels()
    todo, dead = [], []
    for sid in ids:
        cfg = cfgs[sid]
        r = run_site(cfg, hints)
        print(f"■ {cfg.get('name', sid)}（{cfg.get('type')} / {cfg['domain']}・要求 {r['requests']}回"
              + (f"・{r['generator']}" if r.get("generator") else "") + "）")
        if not r["reached"]:
            print("  本番に1回も届きませんでした（検査できず）")
            dead.append(sid)
            continue
        for c in r["checks"]:
            mark = {"ok": "OK  ", "ng": "NG  ", "skip": "—   ", "unknown": "？  "}[c["status"]]
            print(f"  {mark}{c['id']:15s} {c['detail'][:110]}")
        if not a.no_save:
            save(cfg, r)
        todo += todo_lines(cfg, r, labs)
    for ln in todo:
        print(ln)
    if todo:
        print("ONBOARD_OK=no")
    elif dead:
        print("ONBOARD_OK=unknown")
    else:
        print("ONBOARD_OK=yes")
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
