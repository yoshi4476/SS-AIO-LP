# -*- coding: utf-8 -*-
"""自社3サイトの本番を本物のブラウザ（Chromium）で開き、読者の画面にだけ出る崩れを週次で見る

**なぜ要るか**（2026-10-20 運用者の指示「ブラウザでの表示確認の拡張」）: これまでの検査（seo_audit --live・
render_check・aio_check）は HTML の文字を読むだけで、描いた後の画面は見ていなかった。スマホ幅での横のはみ出し・
JavaScript のエラー・読み込めない画像・変換されずに残った Markdown の記法は、HTML を読んでも分からず、
読者の画面にだけ出る。月次の PDF 用に Chromium は既に使っているので、同じものを週次の点検に使う。

見るページ（サイトごと・自社の3サイトだけ。お客様の社は開かない）:
  トップ／一覧（カテゴリか /blog）／新しい公開済みの記事3本（原稿の date の新しい順で、本番の sitemap に載っているもの）
  ／相談の入口（sites/<id>.json の cta.url。トップと同じなら開かない）
幅: 390x844（スマホ）で開き、同じページを 1440x900（PC）に広げて測り直す（読み込みは1ページ1回・1回の実行で25回まで）

見るもの:
  1. 捕まえていない JavaScript のエラー（pageerror）と console の error（第三者の計測・埋め込みが出すものは除く。下の NOISE）
  2. 横のはみ出し（documentElement.scrollWidth > innerWidth + 1。最も右へ出ている要素のタグ・class を添える）
  3. ページそのものの HTTP の状態が 400 以上
  4. 画面に残った Markdown の記法（`**`・`](/`・行頭の表の `|`。コードの中は除く）
  5. 本文（main / article）の中の読み込めない画像（読み込み後に naturalWidth が 0 で、decode も失敗するもの）

    python scripts/browser_check.py                       # 3サイト（週次の findings.py が呼ぶ）
    python scripts/browser_check.py --site ai-lab --articles 1
    python scripts/browser_check.py --screens /tmp/shots   # 画面の写真を残す（コミットしない）

出す印（CLAUDE.md 8.7）: 問題は「要対応:」の行、最後に BROWSER_OK=yes|no|unknown。見つかっても終了コード0。
読めなかったページ（通信の失敗・時間切れ・Cloudflare の確認画面）だけの回は unknown。
検査そのものが動かなかったとき（Playwright・Chromium が無い）だけ終了コード1。
"""
import argparse
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, urljoin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# 機械だと名乗る（相手のログで分かるように）。Chrome の語も残すのは、名乗りだけの UA を断る CDN があるため
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36 SS-AIO-BrowserCheck/1.0 (+https://ai.7senses.co.jp/)")
MOBILE = (390, 844)
DESKTOP = (1440, 900)
MAX_LOADS = 25          # 1回の実行で開くページの上限（相手のサーバーに負担をかけない）
TIMEOUT_MS = 30000
SETTLE_MS = 1500        # load の後に待つ時間。計測タグは load の1.2秒後に読む（speed_fix）ので、その後のエラーも拾う
GAP_S = 1.0             # ページとページの間を空ける（順番に1枚ずつ開く）

# console の error のうち、こちらで直せないもの（小さく保つ。足すときは理由を書く）
#  - ERR_BLOCKED_BY_CLIENT: 広告よけ・追跡よけが計測タグを止めたときの印。サイトの不具合ではない
#  - 第三者のドメイン（計測・YouTube の埋め込み・フォントの CDN など）から出たもの: 中身はこちらで直せない。
#    自社のドメイン（*.7senses.co.jp）から出たものと、出どころの無いもの（ページの中のスクリプト）だけを数える
NOISE = re.compile(r"ERR_BLOCKED_BY_CLIENT")

MD_BOLD = re.compile(r"\*\*")
MD_LINK = re.compile(r"\]\(\s*(?:/|https?://)")
MD_PIPE = re.compile(r"^\s*\|[^|\n]*\|")

OVERFLOW_JS = r"""
() => {
  const vw = window.innerWidth;
  const sw = document.documentElement.scrollWidth;
  let worst = null;
  if (sw > vw + 1) {
    // 横に流せる箱（overflow が visible 以外）の中身と、固定の部品（画面の外に隠したメニューなど）は、
    // ページの横幅を押し広げないので数えない
    const cache = new Map();
    const contained = (el) => {
      const chain = [];
      let hit = false;
      for (let a = el; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
        if (cache.has(a)) { hit = cache.get(a); break; }
        chain.push(a);
        const s = getComputedStyle(a);
        if (s.position === 'fixed') { hit = true; break; }
        if (a !== el && s.overflowX !== 'visible') { hit = true; break; }
      }
      chain.forEach(a => cache.set(a, hit));
      return hit;
    };
    for (const el of document.body.querySelectorAll('*')) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.right <= vw + 1) continue;
      if (contained(el)) continue;
      if (!worst || r.right > worst.right) {
        const cls = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
        worst = {right: Math.round(r.right), width: Math.round(r.width), tag: el.tagName.toLowerCase(),
                 id: el.id || '', cls: cls.join('.')};
      }
    }
  }
  return {vw, sw, worst};
}
"""

MARKDOWN_JS = r"""
() => {
  const sel = 'p,li,td,th,h1,h2,h3,h4,h5,h6,dd,dt,figcaption,blockquote,caption,summary';
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (el.closest('pre,code,kbd,samp,script,style,noscript,textarea,template')) continue;
    if (el.checkVisibility && !el.checkVisibility()) continue;
    const c = el.cloneNode(true);
    c.querySelectorAll('pre,code,kbd,samp,script,style,noscript,textarea,template').forEach(n => n.remove());
    const t = c.textContent || '';
    if (/\*\*|\]\(|\|/.test(t)) out.push(t);
  }
  return out;
}
"""

IMAGES_JS = r"""
async () => {
  const root = document.querySelector('main, article, [role=main]') || document.body;
  const imgs = [...root.querySelectorAll('img')].filter(i => i.currentSrc || i.getAttribute('src'));
  // 遅れて読む画像（loading=lazy）は画面に入るまで読まれず、壊れているかが分からない。その場で読ませる
  imgs.forEach(i => { if (i.loading === 'lazy') i.loading = 'eager'; });
  const t0 = Date.now();
  while (Date.now() - t0 < 10000 && imgs.some(i => !i.complete)) await new Promise(r => setTimeout(r, 250));
  const bad = [];
  for (const i of imgs) {
    if (!i.complete || i.naturalWidth > 0) continue;
    // 大きさの書いていない SVG も naturalWidth が 0 になりうる。decode が失敗したものだけを壊れた画像とする
    try { await i.decode(); } catch (e) { bad.push(i.currentSrc || i.getAttribute('src')); }
  }
  return bad;
}
"""


def _base(host):
    parts = (host or "").lower().removeprefix("www.").split(".")
    return ".".join(parts[-3:] if len(parts) >= 3 and parts[-2] in ("co", "or", "go", "ne", "ac", "lg") else parts[-2:])


def third_party(url, page_host):
    host = urlparse(url or "").hostname or ""
    return bool(host) and _base(host) != _base(page_host)


def markdown_left(texts):
    """画面の文字に残った Markdown の記法（種類ごとに最初の1か所）"""
    found = {}
    for t in texts:
        flat = re.sub(r"\s+", " ", t).strip()
        if "**" not in found and MD_BOLD.search(t):
            found["**"] = flat
        if "](/" not in found and MD_LINK.search(t):
            found["](/"] = flat
        if "|" not in found and any(MD_PIPE.match(ln) and ln.count("|") >= 2 for ln in t.splitlines() or [t]):
            found["|"] = flat
    return [(k, v[:40]) for k, v in found.items()]


def inspect(page, url, label, errors, response, screens=None, shot_name=""):
    """開いたページを2つの幅で測り、問題の文（要対応の行の中身）を返す。errors は読み込み中に拾った JS のエラー"""
    out = []
    if response is not None and response.status >= 400:
        out.append(f"{label} ページが HTTP {response.status} を返します {url}")
    for e in dict.fromkeys(errors):
        out.append(f"{label} JavaScript のエラー「{e[:90]}」 {url}")
    for k, snip in markdown_left(page.evaluate(MARKDOWN_JS)):
        out.append(f"{label} 画面に Markdown の記法 {k} が残っています「{snip}」 {url}")
    broken = page.evaluate(IMAGES_JS)
    if broken:
        out.append(f"{label} 読み込めない画像 {len(broken)}枚（{broken[0][:80]}） {url}")
    for name, (w, h) in (("スマホ幅", MOBILE), ("PC幅", DESKTOP)):
        page.set_viewport_size({"width": w, "height": h})
        page.wait_for_timeout(300)
        r = page.evaluate(OVERFLOW_JS)
        if r["sw"] > r["vw"] + 1:
            wst = r.get("worst")
            who = ("最も右へ出ている要素: %s%s%s %dpx" % (wst["tag"], "#" + wst["id"] if wst["id"] else "",
                                                     "." + wst["cls"] if wst["cls"] else "", wst["width"])
                   if wst else "原因の要素は特定できません")
            out.append(f"{label} {name}で横にはみ出し {r['sw']}px＞{r['vw']}px（{who}） {url}")
        if screens:
            Path(screens).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(screens) / f"{shot_name}-{w}.png"))
    return out


def open_and_inspect(context, url, label, screens=None, shot_name=""):
    """1ページを開いて測る。返すのは (問題の文の一覧, 読めなかった理由 or None)"""
    page = context.new_page()
    host = urlparse(url).hostname or ""
    errors = []

    def on_console(msg):
        if msg.type != "error" or NOISE.search(msg.text or ""):
            return
        if third_party((msg.location or {}).get("url", ""), host):
            return
        errors.append((msg.text or "").splitlines()[0] if msg.text else "（文なし）")

    def on_error(err):
        stack = str(getattr(err, "stack", "") or "")
        urls = re.findall(r"https?://[^\s)]+", stack)
        if urls and all(third_party(u, host) for u in urls):
            return
        msg = str(getattr(err, "message", "") or err)
        errors.append((msg.splitlines() or ["（文なし）"])[0])

    page.on("console", on_console)
    page.on("pageerror", on_error)
    try:
        page.set_viewport_size({"width": MOBILE[0], "height": MOBILE[1]})
        try:
            resp = page.goto(url, wait_until="load", timeout=TIMEOUT_MS)
        except Exception as e:
            return [], f"開けませんでした（{type(e).__name__}: {str(e).splitlines()[0][:80]}）"
        if resp is None:
            return [], "応答がありませんでした"
        # Cloudflare の確認画面（機械と見られた）は、読者の画面ではないので測らない
        if resp.status in (403, 503) and (resp.headers.get("cf-mitigated") == "challenge"):
            return [], f"Cloudflare の確認画面になりました（HTTP {resp.status}）"
        page.wait_for_timeout(SETTLE_MS)
        return inspect(page, url, label, errors, resp, screens, shot_name), None
    finally:
        page.close()


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ja"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def sitemap_urls(domain):
    """本番の sitemap に載っている URL（末尾の / をそろえる）。取れなければ None"""
    try:
        xml = _get(f"https://{domain}/sitemap.xml")
    except Exception:
        return None
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    if "<sitemapindex" in xml:
        sub = []
        for sm in locs[:5]:
            try:
                sub += re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", _get(sm))
            except Exception:
                pass
        locs = sub
    return {u.rstrip("/") for u in locs}


def newest_articles(sid, cfg, n, live=None):
    """原稿の date が新しい順で、公開済み（90点以上・noindex でない・今日までの日付）の記事の URL"""
    import yaml
    import sites as S
    cats = set(S.valid_categories(cfg))
    today = date.today().isoformat()
    rows = []
    for p in (ROOT / "articles").glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8-sig")
            m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
            meta = yaml.safe_load(m.group(1)) if m else None
        except Exception:
            continue
        if not isinstance(meta, dict) or meta.get("category") not in cats or not meta.get("slug"):
            continue
        if meta.get("noindex") or int(meta.get("score") or 0) < 85 or str(meta.get("date", "")) > today:
            continue
        rows.append((str(meta.get("date", "")), str(meta.get("modified", "")), meta))
    out = []
    for _, _, meta in sorted(rows, key=lambda r: (r[0], r[1]), reverse=True):
        try:
            url = S.article_url(cfg, meta)
        except Exception:
            continue
        # 書いたばかりで配信がまだの記事を「開けない」と数えないよう、本番の sitemap にあるものだけを開く
        if live is not None and url.rstrip("/") not in live:
            continue
        out.append(url)
        if len(out) >= n:
            break
    return out


def targets(sid, cfg, n_articles=3):
    """（種類, URL）の並び。同じ URL（#以降を除く）は1回だけ"""
    domain = cfg["domain"]
    top = f"https://{domain}/"
    prefix = cfg.get("url_prefix")
    if prefix:
        listing = f"https://{domain}{prefix}" + ("/" if cfg.get("trailing_slash", True) else "")
    else:
        cats = list((cfg.get("categories") or {}).keys())
        listing = f"https://{domain}/{cats[0]}/" if cats else ""
    cta = ((cfg.get("cta") or {}).get("url") or "").strip()
    cta = urljoin(top, cta) if cta else ""
    if cta and _base(urlparse(cta).hostname or "") != _base(domain):
        cta = ""
    live = sitemap_urls(domain)
    rows = [("トップ", top), ("一覧", listing)]
    rows += [("記事", u) for u in newest_articles(sid, cfg, n_articles, live)]
    rows.append(("相談の入口", cta))
    seen, out = set(), []
    for kind, u in rows:
        key = u.split("#")[0].rstrip("/")
        if not u or key in seen:
            continue
        seen.add(key)
        out.append((kind, u))
    return out


def own_sites(only=None):
    import sites as S
    out = []
    for sid in S.own_ids():
        if sid == "sample" or S.is_client(sid):     # お客様の社は開かない（名前もログに出さない）
            continue
        if only and sid not in only:
            continue
        out.append((sid, S.load(sid)))
    return out


def main():
    ap = argparse.ArgumentParser(description="自社サイトの本番をブラウザで開いて、画面の崩れを見る")
    ap.add_argument("--site", action="append", help="自社サイトの id（複数可。既定は自社の全サイト）")
    ap.add_argument("--articles", type=int, default=3, help="サイトごとに開く新しい記事の本数")
    ap.add_argument("--screens", help="画面の写真を残すフォルダ（コミットしない）")
    a = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"Playwright を読み込めません: {e}")
        return 1

    plan = [(sid, cfg, targets(sid, cfg, a.articles)) for sid, cfg in own_sites(a.site)]
    if not plan:
        print("開く自社サイトがありません")
        print("BROWSER_OK=unknown")
        return 0

    problems, failed, loaded, loads = [], [], 0, 0
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as e:
        print(f"Chromium を起動できません（python -m playwright install --with-deps chromium）: {str(e)[:200]}")
        return 1
    try:
        context = browser.new_context(user_agent=UA, locale="ja-JP",
                                      viewport={"width": MOBILE[0], "height": MOBILE[1]})
        for sid, cfg, pages in plan:
            print(f"\n■ {sid}（https://{cfg['domain']}）")
            for i, (kind, url) in enumerate(pages):
                if loads >= MAX_LOADS:
                    failed.append(f"{url}（1回の上限 {MAX_LOADS} ページに達したので開いていません）")
                    continue
                if loads:
                    time.sleep(GAP_S)
                loads += 1
                found, why = open_and_inspect(context, url, f"{sid} {kind}", a.screens, f"{sid}-{i}")
                if why:
                    failed.append(f"{url}（{why}）")
                    print(f"  ？ {kind} {url} … {why}")
                    continue
                loaded += 1
                print(f"  {'×' if found else '○'} {kind} {url}" + (f" … {len(found)}件" if found else ""))
                problems += found
        context.close()
    finally:
        browser.close()
        pw.stop()

    print()
    for p in problems:
        print(f"要対応: ブラウザ表示 {p}")
    for f in failed:
        print(f"  読めなかったページ: {f}")
    print(f"開いたページ {loaded}／{loads}（問題 {len(problems)}件・読めなかった {len(failed)}件）")
    if problems:
        print("BROWSER_OK=no")
    elif failed or not loaded:
        print("BROWSER_OK=unknown")
    else:
        print("BROWSER_OK=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
