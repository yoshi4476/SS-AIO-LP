# -*- coding: utf-8 -*-
"""サイト監査（Ahrefs の Site Audit と同じ観点）を、公開前と公開後の両方で機械が回す

**なぜ要るか**: 2026-09-29 の Ahrefs 監査で、OGPの不完全169・説明文が短い174・題が短い31・
被リンク1本149が出た。どれも記事ではなく、ビルドが自動で作るページ（用語集・業種・テーマ）と
固定ページの外枠が原因で、記事ごとの検査（quality_checks）では一度も見ていなかった。
外部の監査で知るのでは遅い。生成したHTMLそのものを、ページの種類を問わず毎回見る。

    python scripts/seo_audit.py                      # 手元の site/（ビルドの後）
    python scripts/seo_audit.py --live --all         # 3サイトの本番を sitemap から巡回（週次）
    python scripts/seo_audit.py --live --site corporate --limit 200

重さ（Ahrefs の区分に合わせる）:
  致命的 … sitemap に載っているのに開けない・noindex・正規URLが別を指す（検索から外れる）
  警告   … 題・説明の欠け／長さ／重複、OGPの欠け、H1の数、alt の無い画像、転送先へのリンク
  お知らせ … 被リンクが1本以下（手元のみ。本番は全ページを読まないので数えない）

出す印: SEO_AUDIT_OK=yes|no（致命的か警告があれば no）。検査が動かなかったときだけ終了コード1。
"""
import argparse
import collections
import html as _h
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SITE = ROOT / "site"
UA = {"User-Agent": "Mozilla/5.0 (compatible; SS-SEO-Audit/1.0)"}

TITLE_MIN, TITLE_MAX = 15, 60          # サイト名込みの字数（日本語）
DESC_MIN, DESC_MAX = 50, 160
OG_NEED = ("og:title", "og:description", "og:image", "og:url")
SHORTENERS = {"goo.gl", "app.goo.gl", "bit.ly", "t.co", "lin.ee", "amzn.to", "youtu.be", "g.page"}


def _get(url, timeout=30):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout)
        return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception:
        return 0, "", url


def page_facts(h):
    t = re.search(r"<title>(.*?)</title>", h, re.S)
    d = re.search(r'<meta name="description" content="([^"]*)"', h)
    c = re.search(r'<link rel="canonical" href="([^"]+)"', h)
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", h, flags=re.S)
    import json as _json
    ld_err = 0
    for blk in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
        try:
            _json.loads(blk)
        except Exception:
            ld_err += 1
    text = re.sub(r"<[^>]+>", "", re.sub(r"<(header|footer|nav)\b.*?</\1>", "", body, flags=re.S))
    return {
        "title": _h.unescape(t.group(1)).strip() if t else None,
        "n_title": len(re.findall(r"<title>", h)),
        "n_desc": len(re.findall(r'<meta name="description"', h)),
        "viewport": 'name="viewport"' in h,
        "lang": bool(re.search(r"<html[^>]*\blang=", h)),
        "ld_err": ld_err,
        "nofollow_int": len(re.findall(r'<a [^>]*href="/[^"]*"[^>]*rel="[^"]*nofollow', body)),
        "http_mixed": len(re.findall(r'(?:src|href)="http://', h)),
        "text_len": len(re.sub(r"\s+", "", _h.unescape(text))),
        "hreflang": re.findall(r'<link rel="alternate" hreflang="[^"]+" href="([^"]+)"', h),
        # 外部リンクは <a> だけ。<link rel="preconnect" href="https://fonts.googleapis.com"> のような
        # 接続の予約まで拾うと、開いても404になる相手を「リンク切れ」と数えた
        "ext": set(re.findall(r'<a\b[^>]*?\bhref="(https?://[^"#]+)"', body)),
        "imgs": set(re.findall(r'<img\b[^>]*?\bsrc="(/[^"?#]+)"', body)),
        "desc": _h.unescape(d.group(1)).strip() if d else None,
        "canonical": c.group(1) if c else None,
        "noindex": bool(re.search(r'<meta name="robots" content="[^"]*noindex', h)),
        "og_missing": [k for k in OG_NEED if f'property="{k}"' not in h],
        "h1": len(re.findall(r"<h1[\s>]", body)),
        "img_noalt": len([m for m in re.findall(r"<img\b[^>]*>", body) if not re.search(r'\balt="[^"]+"', m)]),
        "links": set(re.findall(r'href="(/[^"#?]*)"', body)),
    }


def check(pages, sitemap, redirects=(), inbound=None):
    """pages: {path: facts}（path は /x/ の形）。sitemap: sitemap に載る path の集合。
    返り値: [(重さ, 検査名, path, 詳細)]"""
    out = []
    for p in sorted(sitemap):
        f = pages.get(p)
        if f is None:
            out.append(("致命的", "sitemap のページが開けない", p, ""))
            continue
        if f["noindex"]:
            out.append(("致命的", "sitemap に noindex のページ", p, ""))
        if f["canonical"] and urlparse(f["canonical"]).path.rstrip("/") + "/" != p:
            out.append(("致命的", "正規URLが別のページを指す", p, f["canonical"]))
    titles, descs = collections.defaultdict(list), collections.defaultdict(list)
    for p, f in pages.items():
        if f["noindex"]:
            continue
        t, d = f["title"], f["desc"]
        if not t:
            out.append(("警告", "題が無い", p, ""))
        elif not TITLE_MIN <= len(t) <= TITLE_MAX:
            out.append(("警告", "題が短すぎる" if len(t) < TITLE_MIN else "題が長すぎる", p, f"{len(t)}字"))
        if not d:
            out.append(("警告", "説明文が無い", p, ""))
        elif not DESC_MIN <= len(d) <= DESC_MAX:
            out.append(("警告", "説明文が短すぎる" if len(d) < DESC_MIN else "説明文が長すぎる", p, f"{len(d)}字"))
        if t:
            titles[t].append(p)
        if d:
            descs[d].append(p)
        if f["og_missing"]:
            out.append(("警告", "OGPが不完全", p, ",".join(f["og_missing"])))
        if f["h1"] != 1:
            out.append(("警告", "H1が1つでない", p, f"{f['h1']}個"))
        if f["img_noalt"]:
            out.append(("警告", "alt の無い画像", p, f"{f['img_noalt']}枚"))
        red = [l for l in f["links"] if (l if l.endswith("/") else l + "/") in redirects]
        if red:
            out.append(("警告", "転送されるURLへの内部リンク", p, red[0]))
        if f.get("n_title", 1) > 1 or f.get("n_desc", 1) > 1:
            out.append(("警告", "題か説明文のタグが複数", p, f"title{f['n_title']}・description{f['n_desc']}"))
        if not f.get("viewport", True) or not f.get("lang", True):
            out.append(("警告", "viewport か lang の指定が無い", p, ""))
        if f.get("ld_err"):
            out.append(("警告", "構造化データが壊れている", p, f"{f['ld_err']}件"))
        if f.get("http_mixed"):
            out.append(("警告", "http:// の読み込み・リンク", p, f"{f['http_mixed']}件"))
        if f.get("nofollow_int"):
            out.append(("お知らせ", "nofollow の内部リンク", p, f"{f['nofollow_int']}件"))
        if not f["links"]:
            out.append(("お知らせ", "内部リンクが1本も無いページ", p, ""))
        if p in sitemap and f.get("text_len", 999) < 400:
            out.append(("お知らせ", "本文が薄い（400字未満）", p, f"{f['text_len']}字"))
        for hl in f.get("hreflang") or []:
            hp = urlparse(hl).path.rstrip("/") + "/"
            if hp not in pages:
                out.append(("警告", "hreflang の行き先が無い", p, hl))
        if inbound is not None and p in sitemap and p != "/":
            n = inbound.get(p, 0)
            if n == 0:
                out.append(("警告", "孤立ページ（被リンク0）", p, ""))
            elif n <= 1:
                out.append(("お知らせ", "被リンクが1本以下", p, f"{n}本"))
    for t, ps in titles.items():
        if len(ps) > 1:
            out.append(("警告", "題が重複", ps[0], f"{len(ps)}ページ: {t[:30]}"))
    for d, ps in descs.items():
        if len(ps) > 1:
            out.append(("警告", "説明文が重複", ps[0], f"{len(ps)}ページ"))
    return out


def local():
    pages, inbound = {}, collections.Counter()
    for f in SITE.rglob("index.html"):
        p = "/" + str(f.parent.relative_to(SITE)).replace("\\", "/") + "/"
        p = "/" if p == "/./" else p
        pages[p] = page_facts(f.read_text(encoding="utf-8", errors="replace"))
    for p, f in pages.items():
        for l in f["links"]:
            l = l if l.endswith("/") else l + "/"
            if l != p:
                inbound[l] += 1
    sm = (SITE / "sitemap.xml").read_text(encoding="utf-8") if (SITE / "sitemap.xml").is_file() else ""
    sitemap = {urlparse(u).path.rstrip("/") + "/" for u in re.findall(r"<loc>(.*?)</loc>", sm)}
    red = set()
    rf = SITE / "_redirects"
    if rf.is_file():
        for line in rf.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                src = line.split()[0]
                red.add(src if src.endswith("/") else src + "/")
    rows = check(pages, sitemap, red, inbound)
    # 重い画像（Ahrefs の「画像のファイルサイズが大きい」）。表示速度とLCPを落とす
    # ページが実際に表示している画像だけを見る（置いてあるだけの控えは読み込まれない）
    for src in sorted({s for f in pages.values() for s in f.get("imgs", ())}):
        f = SITE / src.lstrip("/")
        if f.is_file() and f.stat().st_size > 300_000:
            rows.append(("警告", "重い画像（300KB超）", src, f"{f.stat().st_size // 1024}KB"))
    return rows, pages


def external(pages, cap=400):
    """外部リンク切れ（4xx/5xx）。同じURLは1回だけ見る。HEADを断るサイトはGETで確かめる"""
    import concurrent.futures as cf
    urls = sorted({u for f in pages.values() for u in f.get("ext", ())})[:cap]
    where = {}
    for p, f in pages.items():
        for u in f.get("ext", ()):
            where.setdefault(u, p)

    def st(u):
        for method in ("HEAD", "GET"):
            try:
                r = urllib.request.urlopen(urllib.request.Request(u, headers=UA, method=method), timeout=20)
                return u, r.status, r.geturl()
            except urllib.error.HTTPError as e:
                if method == "HEAD" and e.code in (403, 405, 400, 501):
                    continue
                return u, e.code, u
            except Exception:
                if method == "HEAD":
                    continue
                return u, 0, u
        return u, 0, u

    def base(host):
        # www. を外し、末尾2つ（co.jp などは3つ）で比べる
        # twitter.com → x.com は同じ運営の名称変更。別サイトへの転送ではない
        host = {"twitter.com": "x.com", "mobile.twitter.com": "x.com"}.get((host or "").lower().removeprefix("www."), host)
        parts = (host or "").lower().removeprefix("www.").split(".")
        return ".".join(parts[-3:] if len(parts) >= 3 and parts[-2] in ("co", "or", "go", "ne", "ac", "lg") else parts[-2:])
    out = []
    with cf.ThreadPoolExecutor(8) as ex:
        res = list(ex.map(st, urls))
    # 404 はブラウザと同じ名乗りで1回だけ聞き直す。Google のヘルプは機械の名乗りに404を返し、
    # 生きているページ18本を「リンク切れ」と数えた（2026-09-29）
    BUA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/126.0 Safari/537.36", "Accept-Language": "ja"}
    for i, (u, s, final) in enumerate(res):
        if s in (404, 410):
            try:
                r = urllib.request.urlopen(urllib.request.Request(u, headers=BUA), timeout=20)
                res[i] = (u, r.status, r.geturl())
            except urllib.error.HTTPError as e:
                res[i] = (u, e.code, u)
            except Exception:
                pass
    for u, s, final in res:
        # 403/429 は相手が機械のアクセスを断っているだけのことが多い（人が開けば見られる）。切れとは数えない
        # 999 は LinkedIn が機械のアクセスを断るときの独自の値（人が開けば見られる）
        if s in (404, 410) or (500 <= s < 999):
            out.append(("警告", "外部リンク切れ", where[u], f"{s} {u[:80]}"))
        # 別のドメインへ転送されるリンクは、ドメインが手放され第三者に取られていることがある。
        # 実例: 医療機関ネットパトロールの旧ドメインがFXのサイトへ転送されていた（2026-09-29）
        # 短縮URL（地図・SNSの共有リンク）は別ドメインへ転送するのが正しい動きなので外す
        elif (s == 200 and base(urlparse(final).hostname) != base(urlparse(u).hostname)
              and base(urlparse(u).hostname) not in SHORTENERS):
            out.append(("警告", "外部リンクが別のドメインへ転送", where[u], f"{u[:60]} → {final[:60]}"))
    return out


def live(domain, limit):
    st, sm, _ = _get(f"https://{domain}/sitemap.xml")
    if st != 200:
        raise RuntimeError(f"sitemap を読めません（{st}）")
    urls = re.findall(r"<loc>(.*?)</loc>", sm)[:limit]
    import concurrent.futures as cf
    pages = {}

    def one(u):
        s, body, final = _get(u)
        return u, s, body, final
    moved = []
    with cf.ThreadPoolExecutor(6) as ex:
        for u, s, body, final in ex.map(one, urls):
            p = urlparse(u).path.rstrip("/") + "/"
            if s == 200 and urlparse(final).path.rstrip("/") != urlparse(u).path.rstrip("/"):
                moved.append(("致命的", "sitemap に転送されるURL", p, final))
            # 転送された（統合で301）ページや開けないページは、開けないものとして数える
            if s == 200 and urlparse(final).path.rstrip("/") == urlparse(u).path.rstrip("/"):
                pages[p] = page_facts(body)
    sm_paths = {urlparse(u).path.rstrip("/") + "/" for u in urls}
    rows = check(pages, sm_paths - {r[2] for r in moved}) + moved
    return rows, pages


def report(name, rows, show=4):
    by = collections.defaultdict(list)
    for sev, kind, p, det in rows:
        by[(sev, kind)].append((p, det))
    order = {"致命的": 0, "警告": 1, "お知らせ": 2}
    print(f"■ {name}")
    if not rows:
        print("   問題なし")
    for (sev, kind), items in sorted(by.items(), key=lambda x: (order[x[0][0]], -len(x[1]))):
        ex = " / ".join(f"{p}{'（' + d + '）' if d else ''}" for p, d in items[:show])
        line = f"{sev}: {name} — {kind} {len(items)}件（例: {ex}）"
        print(("要対応: " if sev != "お知らせ" else "   ") + line if sev != "お知らせ" else "   " + line)
    return sum(1 for r in rows if r[0] != "お知らせ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--site", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--external", action="store_true", help="外部リンク切れも見る（時間がかかる）")
    a = ap.parse_args()
    bad = 0
    if not a.live:
        if not SITE.is_dir():
            print("site/ がありません")
            return 1
        rows, pages = local()
        if a.external:
            rows += external(pages)
        bad += report("AI集客ラボ（手元の site/）", rows)
    else:
        import sites as S
        cfgs = S.load_all()
        ids = list(cfgs) if a.all or not a.site else [a.site]
        ran = 0
        for sid in ids:
            dom = (cfgs.get(sid) or {}).get("domain")
            if not dom:
                continue
            try:
                rows, pages = live(dom, a.limit)
                if a.external:
                    rows += external(pages)
                bad += report(f"{cfgs[sid].get('name', sid)}（本番）", rows)
                ran += 1
            except Exception as e:
                print(f"■ {sid}: 巡回できません（{str(e)[:60]}）")
        if not ran:
            return 1
    print(f"SEO_AUDIT_OK={'no' if bad else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
