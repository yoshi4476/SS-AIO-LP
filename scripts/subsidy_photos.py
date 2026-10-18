# -*- coding: utf-8 -*-
"""補助金サイト（lp.7senses.co.jp）の各ページに写真を置く。何度実行しても同じ結果になる。

  - ページの題（会社案内・サービス・要項）: 題の右に写真を置く（スマホでは題の下）。見た目は補助金サイトの DESIGN.md
  - トップ: 写真を置かない（顔は自己負担の計算。2026-10-18）
  - サービスページの問い合わせ: 入力欄の左に写真
  - 業種ページ・ブログ一覧・記事: 見出しの下に、その業種・記事の写真（記事は一覧のサムネイルと同じ1枚）

写真は assets/img/（在庫）と images/shelf/（3サイト共通の写真の棚）から名前で引く。
    python scripts/subsidy_photos.py <補助金サイトのリポジトリ>
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

CSS = """<style id="ph-css">
/* 写真の置き方（決まりは補助金サイトの DESIGN.md）。ページの題の右に写真を置く（文字に重ねない）。スマホでは題の下に短い帯で出す */
.hero:has(>.hero-ph){position:relative;display:flex;flex-direction:column}
.hero-ph{position:absolute;top:0;right:0;bottom:0;width:min(38vw,540px);z-index:0;pointer-events:none;background:var(--sheet,#f3f5f1)}
.hero-ph img{display:block;width:100%;height:100%;object-fit:cover;object-position:center}
.hero>.wrap{position:relative;z-index:1}
.hero:has(>.hero-ph)>.wrap{width:100%}
@media(min-width:1024px){.hero:has(>.hero-ph)>.wrap>*{max-width:min(620px,52vw)}}
@media(max-width:1023px){.hero-ph{position:static;order:2;width:auto;height:200px;margin-top:28px}.hero:has(>.hero-ph){padding-bottom:0}}
.ph-side{margin:0;border-radius:var(--r-md,8px);overflow:hidden}
.ph-side img{display:block;width:100%;height:auto;object-fit:cover;aspect-ratio:4/3}
@media(min-width:900px){
 .ph-grid{display:grid !important;grid-template-columns:.9fr 1.1fr;column-gap:56px;align-items:start;text-align:left !important}
 .ph-grid>*{grid-column:2}
 .ph-grid>.ph-side{grid-column:1;grid-row:1/span 12;position:sticky;top:96px}
 .ph-grid .fit-cta{justify-content:flex-start !important}
 .ph-grid .micro{text-align:left !important}
}
@media(max-width:899px){.ph-side{margin:0 0 22px}.ph-side img{aspect-ratio:16/9}}
.ph-band{margin:24px 0;border-radius:var(--r-md,8px);overflow:hidden}
.ph-band img{display:block;width:100%;height:auto;aspect-ratio:21/9;object-fit:cover}
.ph-band figcaption{margin-top:6px;font-size:12px;color:var(--ink-3,#616a79)}
@media(pointer:coarse){.crumb a,footer li>a,footer nav a{display:inline-block;padding:9px 0}}
</style>"""

# 紺のヒーローに敷く写真（ページの場所 → 在庫の名前）
DARK = {
    "about/index.html": "/assets/img/office-wide.webp",
    "service/hojokin/index.html": "/assets/img/consulting.webp",
    "service/aio/index.html": "/assets/img/screen-review.webp",
    "service/meo/index.html": "/assets/img/map-tablet.webp",
    "service/dev/index.html": "/assets/img/code.webp",
    "youkou/index.html": "/assets/img/documents.webp",
}
# 業種ページ → 写真の棚の鍵
INDUSTRY = {"clinic": "clinic", "biyou": "salon", "inshokuten": "inshoku", "kensetsu": "kensetsu", "shukuhaku": "hotel", "nougyou": "nougyou"}
# 制度別のまとめページ → 写真の棚の鍵
SEIDO = {"ai-hojokin": "subsidy", "monozukuri": "seizou", "jizokuka": "kouri", "sonota": "subsidy-docs"}


def _mark(html, key, block):
    """<!--ph:key--> … <!--/ph:key--> を入れ替える（無ければ空文字を返す合図として None）"""
    rx = re.compile(rf"<!--ph:{key}-->.*?<!--/ph:{key}-->", re.S)
    if rx.search(html):
        return rx.sub(lambda _: f"<!--ph:{key}-->{block}<!--/ph:{key}-->", html, count=1)
    return None


def _insert_after(html, anchor_rx, key, block):
    done = _mark(html, key, block)
    if done is not None:
        return done
    m = re.search(anchor_rx, html, re.S)
    if not m:
        return html
    return html[:m.end()] + f"<!--ph:{key}-->{block}<!--/ph:{key}-->" + html[m.end():]


def _shelf(repo, key, slug=""):
    import hashlib
    try:
        import photo_shelf
        fs = photo_shelf.files(key)
    except ImportError:
        # 補助金サイトのデプロイ工程（tools/photos.py として複製）では、配信先にある写真から選ぶ
        photo_shelf = None
        fs = sorted(p.name for p in (repo / "images" / "shelf").glob(f"{key}-*.webp")
                    if re.fullmatch(rf"{re.escape(key)}-\d+\.webp", p.name))
    if not fs:
        return ""
    f = fs[int(hashlib.md5(slug.encode("utf-8")).hexdigest(), 16) % len(fs)]
    return photo_shelf.copy_to(repo, f"/images/shelf/{f}") if photo_shelf else f"/images/shelf/{f}"


def decorate(repo: Path, rel: str, html: str) -> str:
    if 'id="ph-css"' in html:
        html = re.sub(r'<style id="ph-css">.*?</style>', lambda _: CSS, html, count=1, flags=re.S)
    else:
        html = html.replace("</head>", CSS + "\n</head>", 1)
    img = lambda src, alt="", cls="", eager=False: (
        f'<img src="{src}" alt="{alt}" width="1600" height="900" loading="{"eager" if eager else "lazy"}"{' fetchpriority="high"' if eager else ""} decoding="async"{(" class=" + chr(34) + cls + chr(34)) if cls else ""}>')

    if rel in DARK:
        html = _insert_after(html, r'<div class="hero">', "hero",
                             f'<div class="hero-ph" aria-hidden="true">{img(DARK[rel], "このページの内容に関わる場面のイメージ", eager=True)}</div>')
    # トップには写真を差し込まない（2026-10-18 のデザインの作り直し）。トップの顔は自己負担の計算（帳簿の形）で、
    # 試算の後ろに敷いていた経営者の写真は文字と重なり、スマホで最初に読む大きな画像になっていた
    if rel.startswith("service/") and 'id="svcform"' in html:
        html = html.replace('<section id="svcform"><div class="wrap">', '<section id="svcform"><div class="wrap ph-grid">')
        html = _insert_after(html, r'<section id="svcform"><div class="wrap ph-grid">', "form",
                             f'<figure class="ph-side">{img("/assets/img/contact-call.webp", "オンラインで相談に応じる担当者のイメージ")}</figure>')

    m = re.match(r"industry/([a-z-]+)/index\.html$", rel)
    if m and m.group(1) in INDUSTRY:
        src = _shelf(repo, INDUSTRY[m.group(1)], m.group(1))
        if src:
            html = _insert_after(html, r'<p class="lead">.*?</p>', "band",
                                 f'<figure class="ph-band">{img(src, "この業種の現場のイメージ", eager=True)}<figcaption>※ 写真はイメージです</figcaption></figure>')
    m = re.match(r"seido/([a-z-]+)/index\.html$", rel)
    if m and m.group(1) in SEIDO:
        src = _shelf(repo, SEIDO[m.group(1)], m.group(1))
        if src:
            html = _insert_after(html, r'<p class="lead">.*?</p>', "band",
                                 f'<figure class="ph-band">{img(src, "この制度を使う場面のイメージ", eager=True)}<figcaption>※ 写真はイメージです</figcaption></figure>')
    if rel in ("blog/index.html", "industry/index.html", "seido/index.html"):
        html = _insert_after(html, r'<p class="lead">.*?</p>', "band",
                             f'<figure class="ph-band">{img("/assets/img/meeting-jp.webp", "補助金の申請を打ち合わせる様子のイメージ", eager=True)}<figcaption>※ 写真はイメージです</figcaption></figure>')
    m = re.match(r"blog/([a-z0-9-]+)/index\.html$", rel)
    if m and (repo / "images" / "blog" / m.group(1) / "thumbnail.webp").is_file():
        html = _insert_after(html, r'<div class="meta">.*?</div>', "eye",
                             f'<figure class="ph-band">{img(f"/images/blog/{m.group(1)}/thumbnail.webp", "記事の内容に関わる場面のイメージ", eager=True)}'
                             f'<figcaption>※ 写真はイメージです</figcaption></figure>')
    return html


STOCK_ALT = {"factory": "工場の現場", "renovation": "店舗の改装工事", "warehouse": "倉庫の作業", "documents": "申請書類を書く手元",
             "paperwork": "書類を整理する担当者", "calculator": "費用を計算する経営者", "meeting": "打ち合わせの様子"}
_TITLES = {}


def _title_of(repo: Path, slug: str) -> str:
    if slug not in _TITLES:
        f = repo / "blog" / slug / "index.html"
        t = ""
        if f.is_file():
            m = re.search(r"<title>(.*?)</title>", f.read_text(encoding="utf-8"), re.S)
            t = re.split(r"[｜|]", m.group(1))[0].strip() if m else ""
        _TITLES[slug] = t
    return _TITLES[slug]


def fill_alts(repo: Path, html: str) -> str:
    """alt が空の画像に説明を入れる（一覧カードのサムネイルは記事の題名、在庫写真は写真の中身）"""
    import html as _h

    def one(m):
        tag = m.group(0)
        src = re.search(r'src="([^"]+)"', tag)
        if not src:
            return tag
        u = src.group(1)
        b = re.match(r"/images/blog/([a-z0-9-]+)/thumbnail\.webp", u)
        if b and _title_of(repo, b.group(1)):
            alt = f"{_title_of(repo, b.group(1))}のイメージ"
        else:
            k = next((v for k, v in STOCK_ALT.items() if f"/{k}" in u), "")
            alt = f"{k}のイメージ" if k else ""
        return tag.replace('alt=""', f'alt="{_h.escape(alt)}"', 1) if alt else tag
    return re.sub(r'<img\b[^>]*\balt=""[^>]*>', one, html)


def decorate_file(repo: Path, page: Path):
    rel = page.relative_to(repo).as_posix()
    s = page.read_text(encoding="utf-8")
    t = fill_alts(repo, decorate(repo, rel, s))
    if t != s:
        page.write_text(t, encoding="utf-8", newline="\n")
        return True
    return False


def run(repo: Path):
    pages = [repo / "index.html", repo / "industry" / "index.html", repo / "blog" / "index.html"]
    pages += [repo / k for k in DARK]
    pages += list((repo / "industry").glob("*/index.html")) + list((repo / "blog").glob("*/index.html"))
    pages += [repo / "seido" / "index.html"] + list((repo / "seido").glob("*/index.html"))
    n = sum(decorate_file(repo, p) for p in pages if p.is_file())
    print(f"SUBSIDY_PHOTOS={n}")


if __name__ == "__main__":
    run(Path(sys.argv[1]))
