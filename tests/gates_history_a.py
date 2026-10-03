# -*- coding: utf-8 -*-
"""過去の誤りの棚卸し（サイト・HTML・CSS・配信の領域）から作った門。

どの門も「検出器が壊れた例を拾うこと」「正しい例を拾わないこと」を先に確かめてから、
いまのファイルに当てる（CLAUDE.md 0.1: 0件と言う前に、見つかるはずの例で検出器を試す）。
別リポジトリ（.publish-work/）の作業コピーは古いことがあるため、そこでの検出は WARN にとどめる。
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from test_gates import check, ROOT

SITE = ROOT / "site"
SUB = ROOT / ".publish-work" / "subsidy"
CORP = ROOT / ".publish-work" / "corporate"
HOSTS = {"ai.7senses.co.jp": SITE, "lp.7senses.co.jp": SUB, "corp.7senses.co.jp": CORP / "out"}
SKIP_DIRS = {"node_modules", "dist", ".git", "_next", ".next"}


def warn(label, items):
    if items:
        print(f"  WARN  {label}: {len(items)}件  " + " / ".join(map(str, sorted(items)[:8])))


def html_files(root, sub=""):
    base = root / sub if sub else root
    if not base.is_dir():
        return []
    return [p for p in base.rglob("*.html") if not (SKIP_DIRS & set(p.relative_to(root).parts))]


def read(p):
    return p.read_text(encoding="utf-8", errors="ignore")


def strip_code(html):
    """script・style・コメントを除く。表やリンクを文字列で数えると、style の中の CSS まで拾う
    （2026-10-02: 「包まれていない表は0本」と誤報した原因）"""
    return re.sub(r"<(script|style)\b.*?</\1>|<!--.*?-->", " ", html, flags=re.S | re.I)


def exists_at(root, path):
    p = path.split("#")[0].split("?")[0].strip("/")
    if not p:
        return (root / "index.html").is_file()
    return any(c.is_file() for c in (root / p / "index.html", root / p, root / (p + ".html")))


def local_target(url, own_root):
    """URL を (配信ルート, パス) に。自社3ドメイン以外・相対でないものは None"""
    m = re.match(r"https?://([^/]+)(/.*)?$", url)
    if m:
        root = HOSTS.get(m.group(1).lower())
        return (root, m.group(2) or "/") if root else None
    return (own_root, url) if url.startswith("/") and not url.startswith("//") else None


# ── 2. _redirects の転送先が実在し、連鎖していない（2026-08-04 / 08-17）─────────
def parse_redirects(text):
    out = []
    for ln in text.splitlines():
        ln = ln.split("#")[0].strip() if not ln.lstrip().startswith("#") else ""
        parts = ln.split()
        if len(parts) >= 2:
            out.append((parts[0], parts[1], parts[2] if len(parts) > 2 else "301"))
    return out


def _norm(s):
    return s.split("#")[0].split("?")[0].rstrip("/") or "/"


def redirect_sources():
    """自社3ドメインそれぞれの転送元（別ドメインへ送った先がさらに転送される連鎖を見るため）"""
    out = {}
    for host, root in HOSTS.items():
        f = root / "_redirects"
        out[host] = {_norm(s) for s, _, _ in parse_redirects(read(f))} if f.is_file() else set()
    return out


def redirect_problems(rules, own_root, own_host, others=None):
    srcs = {_norm(s) for s, _, _ in rules}
    bad = []
    for src, dst, code in rules:
        if "*" in dst or ":" in dst.split("//", 1)[-1] or code == "200":
            continue
        own = re.match(rf"https?://{re.escape(own_host)}(/.*)?$", dst)
        dpath = (own.group(1) or "/") if own else dst
        far = re.match(r"https?://([^/]+)(/.*)?$", dpath)
        if (dpath.startswith("/") and _norm(dpath) in srcs) or \
                (far and _norm(far.group(2) or "/") in (others or {}).get(far.group(1).lower(), set())):
            bad.append(f"連鎖 {src} → {dst}")
            continue
        tgt = local_target(dpath, own_root)
        if tgt and tgt[0] is not None and tgt[0].is_dir() and not exists_at(*tgt):
            bad.append(f"転送先が無い {src} → {dst}")
    return bad


def test_hist_redirect_targets_exist():
    print("\n■ 履歴A-2: _redirects の転送先が実在し、連鎖していない")
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "live").mkdir()
        (r / "live" / "index.html").write_text("x", encoding="utf-8")
        bad = redirect_problems(parse_redirects("/a/ /gone/ 301\n/b/ /c/ 301\n/c/ /live/ 301"), r, "x.test")
        check("検出器: 消えた転送先と A→B→C の連鎖を拾う", sorted(x.split()[0] for x in bad), ["転送先が無い", "連鎖"])
        check("検出器: 別ドメインの転送先がさらに転送される連鎖を拾う（2026-10-03 の実例）",
              redirect_problems(parse_redirects("/a/ https://lp.test/blog/old/ 301"), r, "x.test", {"lp.test": {"/blog/old"}}),
              ["連鎖 /a/ → https://lp.test/blog/old/"])
        check("検出器: 実在する転送先・別ドメイン・splat は拾わない",
              redirect_problems(parse_redirects("/a/ /live/ 301\n/g/* /live/ 301\n/x/ https://example.com/y/ 301"), r, "x.test"), [])
    others = redirect_sources()
    own = redirect_problems(parse_redirects(read(SITE / "_redirects")), SITE, "ai.7senses.co.jp", others) \
        if (SITE / "_redirects").is_file() else []
    check("site/_redirects の転送先が全て実在し、連鎖が無い", own, [])
    for name, root, host in (("補助金", SUB, "lp.7senses.co.jp"), ("コーポレート", CORP / "out", "corp.7senses.co.jp")):
        f = root / "_redirects"
        if f.is_file():
            warn(f"{name}の _redirects（作業コピー）", redirect_problems(parse_redirects(read(f)), root, host, others))


# ── 5. 記事の画像・og:image が配信先に実在する（2026-07-30 / 08-07 / 09-25）────────
IMG_RX = re.compile(r'<img\b[^>]*?\ssrc=["\']([^"\']+)["\']|<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)


def missing_images(html, own_root):
    out = []
    for a, b in IMG_RX.findall(strip_code(html.replace('<script type="application/ld+json"', "<x"))):
        u = a or b
        if u.startswith("data:"):
            continue
        t = local_target(u, own_root)
        if t and t[0] is not None and t[0].is_dir() and not exists_at(*t):
            out.append(u)
    return out


def test_hist_images_exist_where_served():
    print("\n■ 履歴A-5: 本文の画像と og:image が配信先に実在する")
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        (r / "images" / "blog" / "s").mkdir(parents=True)
        (r / "images" / "blog" / "s" / "x.png").write_bytes(b"x")
        bad = '<img src="/images/s/x.png"><meta property="og:image" content="/images/s/og.png">'
        check("検出器: images_dir の抜けた画像パス（/images/blog/ 抜け）を拾う", len(missing_images(bad, r)), 2)
        check("検出器: 実在する画像・外部URL・data: は拾わない",
              missing_images('<img src="/images/blog/s/x.png"><img src="https://example.com/a.png"><img src="data:image/png;base64,AA">', r), [])
    own = sorted({f"{p.relative_to(SITE).parent.as_posix()}: {u}" for p in html_files(SITE) for u in missing_images(read(p), SITE)})
    check("site/ のページの画像が全て実在する", own, [])
    # コーポレートは配信前の原稿（JSON）で見る。out/ は古いことがある
    pub = CORP / "public"
    corp = []
    for f in sorted((CORP / "src" / "content" / "blog").glob("*.json")) if pub.is_dir() else []:
        a = json.loads(read(f))
        corp += [f"{f.stem}: {u}" for u in missing_images(a.get("html", ""), pub)]
        corp += [f"{f.stem}: {a[k]}" for k in ("eyecatch", "eyecatchWebp", "photo")
                 if a.get(k) and str(a[k]).startswith("/") and not exists_at(pub, a[k])]
    warn("コーポレート原稿の画像が public/ に無い", corp)
    warn("補助金ブログの画像が無い", [f"{p.parent.name}: {u}" for p in html_files(SUB, "blog") for u in missing_images(read(p), SUB)])


# ── 6. CSS が構文として閉じている・白い面に白いロゴを置かない（2026-07-28 〜 10-03）──
def css_brace_errors(css):
    """波括弧の対応。コメントと文字列の中は数えない（content:"}" で誤検出しない）"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', css)
    if "/*" in css:
        return ["閉じていないコメント"]
    depth, errs = 0, []
    for i, ch in enumerate(css):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                errs.append(f"余分な }} （{css.count(chr(10), 0, i) + 1}行目付近）")
                depth = 0
    if depth:
        errs.append(f"閉じていない {{ が{depth}個")
    return errs


class _Tree(HTMLParser):
    """表がはみ出し対策の入れ物に入っているか・ヘッダーのロゴは何か、を構文で見る"""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self, scrollers):
        super().__init__()
        self.stack, self.bare_tables, self.header_white, self.scrollers = [], 0, [], scrollers

    def _scrolls(self, cls, style):
        return bool(set((cls or "").split()) & self.scrollers) or bool(re.search(r"overflow(-x)?\s*:\s*(auto|scroll)", style or ""))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table" and not any(sc for _, _, sc in self.stack):
            self.bare_tables += 1
        if tag == "img" and any(t == "header" for t, _, _ in self.stack) and "white" in (a.get("src") or ""):
            self.header_white.append(a.get("src"))
        if tag not in self.VOID:
            self.stack.append((tag, a.get("class") or "", self._scrolls(a.get("class"), a.get("style"))))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def scroll_classes(css):
    """横スクロールさせる（overflow-x: auto/scroll）クラス。クラス名で推測しない
    （research の表は .rs-tbl で包まれていたのに「wrap」の名前が無いだけで拾った）"""
    out = set()
    for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        if re.search(r"overflow(-x)?\s*:\s*(auto|scroll)", body):
            for part in sel.split(","):
                last = part.strip().split()[-1] if part.strip() else ""
                out |= set(re.findall(r"\.([\w-]+)", last))
    return out


_SCROLL = {}


def tree(html, root=None):
    if root not in _SCROLL:
        _SCROLL[root] = set().union(*[scroll_classes(read(p)) for p in css_files() if root and p.is_relative_to(root)]) if root else set()
    page_css = "".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S | re.I))
    t = _Tree(_SCROLL[root] | scroll_classes(page_css))
    t.feed(strip_code(html))
    return t


def css_files():
    fs = list((SITE / "css").glob("*.css"))
    if SUB.is_dir():
        fs += [p for p in SUB.rglob("*.css") if not (SKIP_DIRS & set(p.relative_to(SUB).parts))]
    if (CORP / "src").is_dir():
        fs += list((CORP / "src").rglob("*.css"))
    return fs


def test_hist_css_is_well_formed_and_logos_fit():
    print("\n■ 履歴A-6: CSS の波括弧が閉じている・ヘッダーに白いロゴを置かない")
    check("検出器: 閉じ波括弧が1つ足りない CSS を拾う", bool(css_brace_errors(".a{color:red}\n.b{color:blue\n.c{x:1}")), True)
    check("検出器: 正規表現の貪欲マッチで消えた（} だけ残った）CSS を拾う", bool(css_brace_errors(".a{x:1}}\n.b{y:2}")), True)
    check("検出器: 文字列やコメントの中の波括弧は拾わない",
          css_brace_errors('.a::after{content:"}"}/* { */@media(x){.b{y:1}}'), [])
    bad = sorted(f"{p.relative_to(ROOT).as_posix()}: {e}" for p in css_files() if p.is_relative_to(SITE) for e in css_brace_errors(read(p)))
    check("site/css の CSS が全て閉じている", bad, [])
    inline = sorted(f"{p.relative_to(SITE).as_posix()}" for p in html_files(SITE)
                    for s in re.findall(r"<style[^>]*>(.*?)</style>", read(p), re.S) if css_brace_errors(s))
    check("site/ のページ内 <style> が全て閉じている", inline, [])
    warn("別リポジトリの CSS の波括弧", [f"{p.relative_to(ROOT).as_posix()}: {e}" for p in css_files()
                                if not p.is_relative_to(SITE) for e in css_brace_errors(read(p))])
    check("検出器: 白いヘッダーの白いロゴを拾う",
          tree('<header class="site-header"><a><img src="/images/company/logo-white.png"></a></header>').header_white,
          ["/images/company/logo-white.png"])
    check("検出器: フッターの白いロゴは拾わない",
          tree('<header><img src="/images/company/logo.png"></header><footer><img src="/images/company/logo-white.png"></footer>').header_white, [])
    hw = sorted(p.relative_to(SITE).as_posix() for p in html_files(SITE) if tree(read(p)).header_white)
    check("site/ のヘッダーに白いロゴ（logo-white）が無い", hw, [])


# ── 7. スマホ幅で表がはみ出さない（2026-07-28 / 08-04 / 10-02 / 10-03）──────────────
def test_hist_tables_are_wrapped():
    print("\n■ 履歴A-7: 表がはみ出し対策の入れ物（table-wrap）に入っている")
    check("検出器: 包まれていない表を拾う", tree("<p>x</p><table><tr><td>a</td></tr></table>", SITE).bare_tables, 1)
    check("検出器: 横スクロールしない入れ物（名前だけ wrap）の表を拾う",
          tree('<div class="wrapper-x"><table><tr><td>a</td></tr></table></div>', SITE).bare_tables, 1)
    check("検出器: <style> の中の「<table」の文字は数えない（2026-10-02 の誤報）",
          tree('<style>.x{content:"<table>"}</style><div class="table-wrap"><table><tr><td>a</td></tr></table></div>', SITE).bare_tables, 0)
    check("検出器: ページ内 CSS で横スクロールする入れ物（.rs-tbl）は拾わない",
          tree('<style>.rs-tbl{overflow-x:auto}</style><div class="rs-tbl"><table><tr><td>a</td></tr></table></div>').bare_tables, 0)
    check("検出器: site の CSS から table-wrap を横スクロールの入れ物と読めた", "table-wrap" in tree("", SITE).scrollers, True)
    bare = sorted(p.relative_to(SITE).as_posix() for p in html_files(SITE) if tree(read(p), SITE).bare_tables)
    check("site/ の表が全て横スクロールの入れ物に入っている", bare, [])
    warn("補助金ブログの包まれていない表", [p.parent.name for p in html_files(SUB, "blog") if tree(read(p), SUB).bare_tables])
    corp = []
    for f in sorted((CORP / "src" / "content" / "blog").glob("*.json")) if CORP.is_dir() else []:
        if tree(json.loads(read(f)).get("html", ""), CORP).bare_tables:
            corp.append(f.stem)
    warn("コーポレート原稿の包まれていない表", corp)


MEASURE_JS = r"""() => {
  const rgb = (s) => { const m = (s || "").match(/rgba?\(([^)]+)\)/); if (!m) return null; const v = m[1].split(",").map(Number); return {r: v[0], g: v[1], b: v[2], a: v.length > 3 ? v[3] : 1}; };
  const lum = (c) => { const f = (x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const grad = (e) => { const bi = getComputedStyle(e).backgroundImage || ""; if (bi === "none") return {cs: [], full: false};
    const all = (bi.match(/rgba?\([^)]+\)/g) || []).map(rgb).filter(Boolean);
    return {cs: all.filter(c => c.a > 0.5), full: all.length > 0 && all.every(c => c.a > 0.5)}; };
  const bgOf = (el) => { for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e);
      if (e !== el && cs.backgroundImage && cs.backgroundImage !== "none") return null;
      const c = rgb(cs.backgroundColor); if (c && c.a > 0.5) return c; } return {r: 255, g: 255, b: 255, a: 1}; };
  const vis = (e) => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none" && +cs.opacity > 0.5; };
  const low = [];
  for (const e of document.querySelectorAll(".btn, a[class*='btn'], button, th, mark, strong")) {
    if (!vis(e) || !e.textContent.trim()) continue;
    const fg = rgb(getComputedStyle(e).color); if (!fg || fg.a < 0.5) continue;
    // 要素ぜんたいを塗るグラデーション（ボタン）は親の色を見ない。透明を含むもの（マーカー）は親の色とも比べる
    const g = grad(e); const bgs = g.cs; const base = g.full ? null : bgOf(e); if (base) bgs.push(base);
    if (!bgs.length) continue;
    const r = Math.min(...bgs.map(b => ratio(fg, b)));
    if (r < 3) low.push(`${e.tagName.toLowerCase()}.${String(e.className || "").slice(0, 24)} ${r.toFixed(2)}「${e.textContent.trim().slice(0, 14)}」`);
  }
  for (const i of document.querySelectorAll("img")) {
    if (!/white/i.test(i.getAttribute("src") || "") || !vis(i)) continue;
    const b = bgOf(i.parentElement || i); if (b && lum(b) > 0.6) low.push(`白いロゴが明るい面に ${i.getAttribute("src")}`);
  }
  const W = document.documentElement.clientWidth, wide = [];
  for (const e of document.querySelectorAll("body *")) {
    const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
    if (r.right <= W + 1 || r.width === 0 || cs.position === "fixed" || cs.visibility === "hidden") continue;
    let clipped = false;
    for (let p = e.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o !== "visible") { clipped = true; break; } }
    if (!clipped) wide.push(`${e.tagName.toLowerCase()}.${String(e.className || "").slice(0, 24)} 右端${Math.round(r.right)}px`);
  }
  return {scroll: document.documentElement.scrollWidth, W, low, wide};
}"""

STILL_CSS = "*,*::before,*::after{transition:none!important;animation:none!important}.reveal{opacity:1!important}"


def _serve(d):
    import functools
    import http.server
    import threading

    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=str(d)))
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


def render_issues(page, url=None, html=None):
    if html is not None:
        page.set_content(html)
    else:
        page.goto(url, wait_until="load", timeout=20000)
    page.add_style_tag(content=STILL_CSS)
    page.evaluate("document.querySelectorAll('.reveal').forEach(e => e.classList.add('in'))")
    r = page.evaluate(MEASURE_JS)
    out = [f"横幅 {r['scroll']}px > {r['W']}px"] if r["scroll"] > r["W"] + 1 else []
    return out + [f"はみ出し {w}" for w in r["wide"][:3]] + [f"コントラスト不足 {x}" for x in r["low"][:5]]


def test_hist_mobile_render_and_contrast():
    """375px で描いて、横スクロール・はみ出し・読めない文字色を実測する（文字列検索で判定しない）"""
    print("\n■ 履歴A-6/7: 375px で描画して、はみ出し・コントラストを実測する")
    try:
        from playwright.sync_api import sync_playwright
        p = sync_playwright().start()
        browser = p.chromium.launch()
    except Exception as e:      # ブラウザの無い CI では測れない（research.yml は入れている）
        print(f"  SKIP  chromium が使えないため描画の検査を飛ばす: {str(e)[:80]}")
        return
    try:
        page = browser.new_page(viewport={"width": 375, "height": 800})
        page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(("http://127.0.0.1", "data:", "about:")) else r.abort())
        bad = render_issues(page, html='<body style="margin:0"><header style="background:#fff"><img src="logo-white.png" width="40" height="20"></header>'
                                        '<a class="btn" style="background:#2b6;color:#2b6">送る</a><table style="width:900px"><tr><td>x</td></tr></table>'
                                        '<section style="background:#111"><strong style="color:#fff;background:linear-gradient(transparent 60%,#ffe14d 60%)">黄色の線</strong></section></body>')
        kinds = {x.split()[0] for x in bad}
        check("検出器: 横スクロール・はみ出し・見えないボタン・白いロゴ・暗い面の黄マーカーを拾う",
              kinds >= {"横幅", "はみ出し", "コントラスト不足"} and sum("コントラスト不足" in x for x in bad) >= 3, True)
        good = render_issues(page, html='<body style="margin:0"><header style="background:#fff"><img src="logo.png" width="40" height="20"></header>'
                                        '<a class="btn" style="background:#1b4fa0;color:#fff">送る</a>'
                                        '<form style="background:#fff"><button style="color:#fff;background:linear-gradient(120deg,#2563eb,#1d4ed8)">診断</button></form>'
                                        '<div class="table-wrap" style="overflow-x:auto">'
                                        '<table style="width:900px"><tr><th style="background:#1d3461;color:#fff">x</th></tr></table></div></body>')
        check("検出器: 包まれた表・読める色・暗くない面のロゴは拾わない", good, [])
        pages = {SITE: ["/", "/lp/", "/lab/"]}
        arts = sorted(SITE.glob("aio/*/index.html"))[:1]
        pages[SITE] += ["/" + a.parent.relative_to(SITE).as_posix() + "/" for a in arts]
        if (SUB / "blog").is_dir():
            sb = sorted(p for p in (SUB / "blog").glob("*/index.html") if p.parent.name != "category")[:1]
            pages[SUB] = ["/"] + ["/blog/" + p.parent.name + "/" for p in sb]
        found = {}
        for root, paths in pages.items():
            s = _serve(root)
            try:
                for path in paths:
                    if exists_at(root, path):
                        found[f"{'補助金' if root == SUB else 'site'}{path}"] = render_issues(page, f"http://127.0.0.1:{s.server_port}{path}")
            finally:
                s.shutdown()
        own = sorted(f"{k}: {x}" for k, v in found.items() if k.startswith("site") for x in v)
        check("site/ の代表ページ（375px）に横スクロール・はみ出し・読めない文字色が無い", own, [])
        warn("補助金の代表ページ（375px）", [f"{k}: {x}" for k, v in found.items() if not k.startswith("site") for x in v])
    finally:
        browser.close()
        p.stop()


# ── 8. 旧ドメイン www.7senses.co.jp へのリンク（2026-08-04）─────────────────────
OLD_RX = re.compile(r"""(?:href=["']|\]\(|["']url["']\s*:\s*["']|\(\s*)https?://www\.7senses\.co\.jp""", re.I)


def old_domain_links(text):
    """本文のリンクとして旧ドメインを指している箇所。sameAs（会社の同一性の宣言）と _redirects は除く"""
    text = re.sub(r'<script[^>]*application/ld\+json.*?</script>', "", text, flags=re.S | re.I)
    text = re.sub(r'"sameAs"\s*:\s*\[.*?\]', "", text, flags=re.S)
    return len(OLD_RX.findall(text))


def test_hist_no_old_corporate_domain():
    print("\n■ 履歴A-8: 本文・設定のリンクが旧ドメイン www.7senses.co.jp を指していない")
    check("検出器: HTML と Markdown の旧ドメインへのリンクを拾う",
          old_domain_links('<a href="https://www.7senses.co.jp/">x</a> [y](https://www.7senses.co.jp/a/)'), 2)
    check("検出器: sameAs の宣言と新ドメインは拾わない",
          old_domain_links('<script type="application/ld+json">{"sameAs":["https://www.7senses.co.jp/"]}</script>'
                           '<a href="https://corp.7senses.co.jp/">x</a>'), 0)
    files = list((ROOT / "articles").glob("*.md")) + html_files(SITE) + [SITE / "llms.txt"] \
        + list((ROOT / "sites").glob("*.json")) + list((ROOT / "automation" / "gas").glob("*")) + list((ROOT / "templates").glob("*"))
    bad = sorted(p.relative_to(ROOT).as_posix() for p in files if p.is_file() and old_domain_links(read(p)))
    check("原稿・site/・サイト設定・GAS・テンプレートに旧ドメインへのリンクが無い", bad, [])
    sib = [p.relative_to(ROOT).as_posix() for p in html_files(SUB) + [SUB / "llms.txt"] if p.is_file() and old_domain_links(read(p))]
    sib += [f.stem for f in (CORP / "src" / "content" / "blog").glob("*.json") if old_domain_links(read(f))] if CORP.is_dir() else []
    warn("別リポジトリに残る旧ドメインへのリンク", sib)


# ── 18. CSS/JS の版番号が改行コード（CRLF/LF）で割れない（2026-10-03）──────────────
def test_hist_asset_hash_ignores_line_endings():
    print("\n■ 履歴A-18: CSS/JS の版番号が CRLF と LF で同じになる")
    import build
    saved = build.SITE
    vers = []
    try:
        for body in (b"a{}\r\nb{}\r\n", b"a{}\nb{}\n", b"a{}\nb{x:1}\n"):
            with tempfile.TemporaryDirectory() as d:
                r = Path(d)
                (r / "css").mkdir()
                (r / "js").mkdir()
                (r / "css" / "style.css").write_bytes(body)
                (r / "js" / "site.js").write_bytes(b"var a=1;\n")
                (r / "index.html").write_text('<link href="/css/style.css">', encoding="utf-8")
                build.SITE = r
                build.stamp_assets()
                m = re.search(r"style\.css\?v=([0-9a-f]+)", (r / "index.html").read_text(encoding="utf-8"))
                vers.append(m.group(1) if m else None)
    finally:
        build.SITE = saved
    check("版番号が付く", all(vers), True)
    check("同じ中身の CRLF 版と LF 版は同じ版番号", vers[0] == vers[1], True)
    check("中身が変われば版番号も変わる（検出器が効いている）", vers[1] != vers[2], True)


# ── 29. 本文の先頭にアイキャッチと同じ画像を置かない（2026-09-15）────────────────
def first_image(body):
    m = re.search(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)|<img\b[^>]*\ssrc=[\"']([^\"']+)", body)
    return (m.group(1) or m.group(2)) if m else ""


def dup_eyecatch(eyecatch, body):
    norm = lambda u: re.sub(r"\.(png|webp|jpe?g)$", "", re.sub(r"^https?://[^/]+", "", str(u or "")).split("?")[0])
    return bool(eyecatch) and norm(first_image(body)) == norm(eyecatch)


def test_hist_no_duplicate_eyecatch_in_body():
    print("\n■ 履歴A-29: 本文の最初の画像がアイキャッチと同じでない（2枚続けて出る）")
    check("検出器: 本文1行目のアイキャッチを拾う", dup_eyecatch("/images/s/eyecatch.png", "![](/images/s/eyecatch.png)\n本文"), True)
    check("検出器: webp と絶対URLの同じ画像も拾う", dup_eyecatch("/images/s/eyecatch.png", '<img src="https://x.test/images/s/eyecatch.webp">'), True)
    check("検出器: 別の図解は拾わない", dup_eyecatch("/images/s/eyecatch.png", "本文\n![](/images/s/flow.png)"), False)
    bad = []
    for p in (ROOT / "articles").glob("*.md"):
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", read(p), re.S)
        ey = re.search(r"^eyecatch:\s*[\"']?([^\s\"']+)", m.group(1), re.M) if m else None
        if ey and dup_eyecatch(ey.group(1), m.group(2)):
            bad.append(p.stem)
    check("原稿の本文先頭にアイキャッチと同じ画像が無い", sorted(bad), [])
    corp = [f.stem for f in (CORP / "src" / "content" / "blog").glob("*.json")
            if (lambda a: dup_eyecatch(a.get("eyecatch"), a.get("html", "")))(json.loads(read(f)))] if CORP.is_dir() else []
    warn("コーポレート原稿の本文先頭のアイキャッチ重複", corp)


# ── 39. 3サイトの robots.txt で許可するクローラーが揃っている（2026-08-07）─────────
def robots_agents(text):
    """User-agent ごとに Disallow: / か（全面拒否）を返す"""
    out, cur = {}, []
    for ln in text.splitlines():
        k, _, v = ln.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "user-agent":
            cur = cur if out.get("_open") else []
            cur.append(v.lower())
            out.setdefault(v.lower(), False)
            out["_open"] = True
        elif k in ("allow", "disallow"):
            out["_open"] = False
            if k == "disallow" and v == "/":
                for a in cur:
                    out[a] = True
    out.pop("_open", None)
    return out


def corp_robots():
    built = CORP / "out" / "robots.txt"
    if built.is_file():
        return read(built)
    ts = CORP / "src" / "app" / "robots.ts"
    return "\n".join(f"User-agent: {a}\nAllow: /" for a in re.findall(r"userAgent:\s*[\"']([^\"']+)", read(ts))) if ts.is_file() else ""


def test_hist_robots_agents_match():
    print("\n■ 履歴A-39: 3サイトの robots.txt が同じAIクローラーを許可している")
    check("検出器: クローラーの集合と全面拒否を読む",
          robots_agents("User-agent: GPTBot\nUser-agent: ClaudeBot\nAllow: /\n\nUser-agent: BadBot\nDisallow: /\n"),
          {"gptbot": False, "claudebot": False, "badbot": True})
    a = robots_agents(read(SITE / "robots.txt"))
    check("site/robots.txt で Googlebot・主要AIを全面拒否していない",
          [k for k in ("*", "googlebot", "gptbot", "oai-searchbot", "claudebot", "perplexitybot", "google-extended", "bingbot") if a.get(k)], [])
    for name, text in (("補助金", read(SUB / "robots.txt") if (SUB / "robots.txt").is_file() else ""), ("コーポレート", corp_robots())):
        if not text:
            continue
        b = robots_agents(text)
        diff = sorted(f"{'無い' if k in a else '余分'}:{k}" for k in set(a) ^ set(b))
        diff += sorted(f"拒否が違う:{k}" for k in set(a) & set(b) if a[k] != b[k])
        warn(f"{name}の robots.txt が site/ と食い違う（コーポレートだけ PerplexityBot が無い、の再発）", diff)
        check(f"{name}: 比較が働いている（クローラーを10種以上読めた）", len(b) >= 10, True)


# ── 40. llms.txt に公開記事が全部載っている（2026-08-05）──────────────────────
def llms_gap(llms_text, sitemap_text, rx):
    arts = set(re.findall(rx, sitemap_text))
    listed = set(re.findall(rx, llms_text))
    return sorted(arts - listed)


def test_hist_llms_lists_every_article():
    print("\n■ 履歴A-40: llms.txt に sitemap の記事が全部載っている")
    rx = r"https://x\.test/blog/([a-z0-9-]+)/?"
    check("検出器: llms.txt に載っていない記事を拾う",
          llms_gap("- [a](https://x.test/blog/a/)", "<loc>https://x.test/blog/a/</loc><loc>https://x.test/blog/b/</loc>", rx), ["b"])
    check("検出器: 全部載っていれば拾わない", llms_gap("- [a](https://x.test/blog/a/) [b](https://x.test/blog/b)",
                                                "<loc>https://x.test/blog/a/</loc><loc>https://x.test/blog/b/</loc>", rx), [])
    import sites as S
    cats = "|".join(map(re.escape, S.load("ai-lab").get("categories", {})))
    lab_rx = rf"https://ai\.7senses\.co\.jp/(?:{cats})/([a-z0-9-]+)/"
    sm, ll = read(SITE / "sitemap.xml"), read(SITE / "llms.txt")
    check("site: 比較が働いている（sitemap から記事を読めた）", len(re.findall(lab_rx, sm)) > 50, True)
    check("site/llms.txt に sitemap の記事が全部載っている", llms_gap(ll, sm, lab_rx), [])
    for name, root, host, pat in (("補助金", SUB, r"lp\.7senses\.co\.jp", r"/blog/(?!category/)([a-z0-9-]+)/?"),
                                  ("コーポレート", CORP / "out", r"corp\.7senses\.co\.jp", r"/blog/(?!theme\b)([a-z0-9-]+)/?")):
        if (root / "sitemap.xml").is_file() and (root / "llms.txt").is_file():
            r = rf"https://{host}{pat}"
            warn(f"{name}の llms.txt に載っていない記事（作業コピー）", llms_gap(read(root / "llms.txt"), read(root / "sitemap.xml"), r))


# ── 41. 配信するカテゴリ表示名が配信先で定着している表記と同じ（2026-08-03）────────
def established_labels(counts):
    total = sum(counts.values())
    return {k for k, v in counts.items() if v >= max(2, total * 0.1)}


def test_hist_category_label_matches_destination():
    print("\n■ 履歴A-41: 配信するカテゴリ表示名が、配信先の既存記事の表記と同じ")
    import publish
    import sites as S
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d)
        for i in range(3):
            (dest / "blog" / f"a{i}").mkdir(parents=True)
            (dest / "blog" / f"a{i}" / "index.html").write_text('<span class="cat">補助金</span>', encoding="utf-8")
        cfg = {"id": "t", "categories": {"hojokin": "補助金・助成金"}}
        try:
            publish.check_contract(cfg, dest, {"category": "hojokin", "slug": "new"})
            stopped = False
        except SystemExit:
            stopped = True
        check("検出器: 表示名「補助金・助成金」（既存は「補助金」）を配信前に止める", stopped, True)
        cfg["categories"]["hojokin"] = "補助金"
        check("検出器: 既存と同じ表示名は通す", publish.check_contract(cfg, dest, {"category": "hojokin", "slug": "new"}), True)
    sub_cfg = S.load("subsidy")
    if (SUB / "blog").is_dir():
        used = {}
        for p in (SUB / "blog").glob("*/index.html"):
            m = re.search(r'<span class="cat">(.*?)</span>', read(p))
            if m:
                used[m.group(1).strip()] = used.get(m.group(1).strip(), 0) + 1
        est = established_labels(used)
        check("補助金: sites/subsidy.json の表示名が配信先で定着している表記",
              sorted(v for v in sub_cfg.get("categories", {}).values() if est and v not in est), [])
    corp_cfg = S.load("corporate")
    if (CORP / "src" / "content" / "blog").is_dir():
        by_cat = {}
        for f in (CORP / "src" / "content" / "blog").glob("*.json"):
            a = json.loads(read(f))
            by_cat.setdefault(a.get("category"), {}).setdefault(a.get("categoryName"), 0)
            by_cat[a.get("category")][a.get("categoryName")] += 1
        bad = [f"{c}:{n}" for c, n in corp_cfg.get("categories", {}).items()
               if c in by_cat and n not in established_labels(by_cat[c])]
        check("コーポレート: sites/corporate.json の表示名が配信先の categoryName と同じ", sorted(bad), [])


# ── 44. 未公開（監修待ち・門を通らない）記事へリンクを張らない（2026-09-25）────────────
def links_to_unpublished(metas, domains):
    """metas: slug → (サイト, 公開してよいか, 原稿)。公開する原稿から同じサイトの未公開原稿へのリンク"""
    out = set()
    for slug, (owner, ok, text) in metas.items():
        if not ok:
            continue
        dom = re.escape(domains[owner])
        for t in re.findall(rf"\]\((?:https://{dom})?/blog/([a-z0-9-]+)/?\)", text):
            if t in metas and metas[t][0] == owner and not metas[t][1]:
                out.add(f"{slug}→{t}")
    return sorted(out)


def test_hist_links_only_to_published():
    print("\n■ 履歴A-44: link_boost の送り先は公開済みの記事だけ")
    import editorial_review as ER
    import link_boost as LB
    with tempfile.TemporaryDirectory() as d:
        r = Path(d)
        fm = "---\ntitle: t\ncategory: aio\nscore: {s}\nscore_breakdown: {{originality: {s}, extractability: {s}, decision: {s}}}\n---\n本文\n"
        for slug, s in (("ok", 93), ("low", 70), ("held", 93)):
            (r / f"{slug}.md").write_text(fm.format(s=s), encoding="utf-8")
        arts = {s: {"path": r / f"{s}.md"} for s in ("ok", "low", "held")}
        saved = ER.REQUIRED
        try:
            ER.REQUIRED = True
            recs = {"ok": {}, "low": {}}
            check("検出器: 監修待ち（HELD）の記事を送り先にしない", LB.linkable("held", arts, recs), False)
            check("検出器: 門を通らない記事を送り先にしない", LB.linkable("low", arts, recs), False)
            check("公開済みの記事は送り先にする", LB.linkable("ok", arts, recs), True)
        finally:
            ER.REQUIRED = saved
    src = read(ROOT / "scripts" / "link_boost.py")
    check("link_boost の送り先の選び方（--only・救済・通常）が linkable を通る", src.count("linkable(") >= 4, True)
    # 原稿で見る: 別リポジトリへ配信する記事から、同じサイトの未公開の原稿へのリンク。
    # build.py は自サイトの未公開リンクを文字に戻すが、配信（publish.py）には無いため本番で404になる
    # （2026-10-03: it-hojokin-clinic → 採点前の ai-hojokin-clinic-keihi が本番で404だった）
    import publish
    import sites as S
    metas = {}
    for p in (ROOT / "articles").glob("*.md"):
        m = publish.read_meta(p) or {}
        owner = S.find_category_owner(str(m.get("category", "")))
        if owner and S.load(owner).get("url_prefix"):
            metas[p.stem] = (owner, publish.gate_ok(m) and ER.reviewed(p.stem), read(p))
    fake = {"a": ("s", True, "[x](/blog/b/) [y](https://s.test/blog/c/)"), "b": ("s", False, ""), "c": ("s", True, "")}
    check("検出器: 未公開の原稿へのリンクを拾い、公開済みへのリンクは拾わない",
          links_to_unpublished(fake, {"s": "s.test"}), ["a→b"])
    doms = {o: S.load(o)["domain"] for o, _, _ in metas.values()}
    check("配信する原稿から、同じサイトの未公開の原稿へのリンクが無い", links_to_unpublished(metas, doms), [])
    # 配信先の原稿で、同じサイトの存在しない記事へのリンク（404）
    dead = []
    cdir = CORP / "src" / "content" / "blog"
    if cdir.is_dir():
        have = {f.stem for f in cdir.glob("*.json")}
        for f in cdir.glob("*.json"):
            for s in re.findall(r'href="(?:https://corp\.7senses\.co\.jp)?/blog/([a-z0-9-]+)/?"', json.loads(read(f)).get("html", "")):
                if s not in have:
                    dead.append(f"corp {f.stem}→{s}")
    if (SUB / "blog").is_dir():
        have = {p.name for p in (SUB / "blog").iterdir() if p.is_dir()}
        have |= {s.strip("/").split("/")[-1] for s in redirect_sources().get("lp.7senses.co.jp", set())}  # 転送で開けるものは404でない
        for p in (SUB / "blog").glob("*/index.html"):
            for s in re.findall(r'href="(?:https://lp\.7senses\.co\.jp)?/blog/([a-z0-9-]+)/?"', strip_code(read(p))):
                if s not in have:
                    dead.append(f"subsidy {p.parent.name}→{s}")
    warn("配信先の記事から存在しない記事へのリンク（作業コピー）", sorted(set(dead)))


# ── 50. 否定された施策（llms.txt）の加点・旧採点「6観点120点満点」を出さない（2026-09-23〜28）──
STALE_RX = re.compile(r"120点満点|114点|6観点|6つの観点")


def test_hist_no_retired_scoring_claims():
    print("\n■ 履歴A-50: 旧採点（6観点120点満点）と llms.txt の加点を外に出さない")
    check("検出器: 提案書の「6観点120点満点」を拾う", bool(STALE_RX.search("さらに6観点120点満点の採点で")), True)
    check("検出器: いまの採点（3観点・100点）は拾わない", bool(STALE_RX.search("3観点を各100点で採点")), False)
    pub = [p for p in html_files(SITE)] + [SITE / "llms.txt"] + list((ROOT / "functions").rglob("*.js")) \
        + [ROOT / "scripts" / n for n in ("proposal_make.py", "monthly_report.py", "group_report.py", "sales_deck.py")]
    bad = sorted(p.relative_to(ROOT).as_posix() for p in pub if p.is_file() and STALE_RX.search(read(p)))
    check("site/・診断API・提案書とレポートの生成元に旧採点の表記が無い", bad, [])
    warn("営業資料・顧客向け文書に残る旧採点の表記（文面の判断が要るため人が直す）",
         [p.relative_to(ROOT).as_posix() for p in list((ROOT / "docs" / "sales").glob("*.html")) + [ROOT / "docs" / "client-readme.md"]
          if p.is_file() and STALE_RX.search(read(p))])
    js = read(ROOT / "functions" / "api" / "audit.js")
    items = re.findall(r'name:\s*"([^"]+)",\s*pts:\s*(\d+)', js)
    pts = {n: int(v) for n, v in items}
    llms = [v for n, v in pts.items() if "llms" in n.lower()]
    check("診断: 配点表を読めた（検出器が働いている）", len(pts) >= 8, True)
    check("診断: llms.txt の配点は最小（Google が読まないと明言）", bool(llms) and max(llms) <= min(pts.values()), True)
    check("診断: 合計100点", sum(pts.values()), 100)


# ── 83. 公開フォームの API が壊れた入力に 4xx を返す（2026-09-02 / 09-05）──────────
NODE_HARNESS = r"""
import { pathToFileURL } from "node:url";
globalThis.fetch = async () => { throw new Error("offline"); };
const cases = [["text/plain", "hello"], [null, ""], ["application/json", "{bad"],
               ["application/json", '{"type":"zzz"}'], ["application/x-www-form-urlencoded", "type=zzz"]];
const out = [];
for (const f of JSON.parse(process.argv[2])) {
  const m = await import(pathToFileURL(f).href);
  if (!m.onRequestPost) continue;
  for (const [ct, body] of cases) {
    const req = new Request("https://x.test/api/x", { method: "POST", headers: ct ? { "content-type": ct } : {}, body });
    let st;
    try { const r = await m.onRequestPost({ request: req, env: {}, waitUntil: () => {} }); st = r ? r.status : "none"; }
    catch (e) { st = "throw"; }
    out.push([f.split(/[\\/]/).pop(), ct || "-", body, st]);
  }
}
console.log(JSON.stringify(out));
"""


def api_bad_input(files):
    node = shutil.which("node")
    if not node:
        return None
    with tempfile.TemporaryDirectory() as d:
        h = Path(d) / "harness.mjs"
        h.write_text(NODE_HARNESS, encoding="utf-8")
        r = subprocess.run([node, str(h), json.dumps([str(f) for f in files])], capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
    if r.returncode != 0:
        return [f"検査が動かない: {r.stderr.strip()[-200:]}"]
    rows = json.loads(r.stdout.strip().splitlines()[-1])
    return [f"{f} {ct} {body!r} → {st}" for f, ct, body, st in rows if not (isinstance(st, int) and 400 <= st < 500)]


def test_hist_form_apis_reject_bad_input():
    print("\n■ 履歴A-83: フォームの API が壊れた入力に 4xx を返す（生の500・例外を出さない）")
    with tempfile.TemporaryDirectory() as d:
        bad, good = Path(d) / "bad.mjs", Path(d) / "good.mjs"
        bad.write_text('export async function onRequestPost({request}){const fd=await request.formData();'
                       'return new Response(String(fd.get("email")),{status:200});}', encoding="utf-8")
        good.write_text('export async function onRequestPost({request}){let fd;try{fd=await request.formData();}'
                        'catch(_){return new Response("x",{status:400});}if(!fd.get("email"))return new Response("x",{status:400});'
                        'return new Response("ok");}', encoding="utf-8")
        got_bad, got_good = api_bad_input([bad]), api_bad_input([good])
    if got_bad is None:
        print("  SKIP  node が無いため API の検査を飛ばす")
        return
    check("検出器: text/plain で例外になる（Cloudflare の生500）API を拾う", any("throw" in x for x in got_bad), True)
    check("検出器: 壊れた入力に400を返す API は拾わない", got_good, [])
    files = sorted(f for f in (ROOT / "functions" / "api").glob("*.js") if "onRequestPost" in read(f))
    check("functions/api の POST が、壊れた入力・空・未知の種類に全て 4xx を返す", api_bad_input(files), [])
    js = read(SITE / "js" / "site.js")
    acts = {a for p in html_files(SITE) for a in re.findall(r'<form[^>]*action="(/api/[a-z-]+)"', read(p))}
    check("公開フォームの送信先を読めた", bool(acts), True)
    check("公開フォームは画面内で送り、失敗を画面内に出す（ページを移らない）",
          sorted(a for a in acts if f'fetch("{a}"' not in js or "preventDefault" not in js), [])
