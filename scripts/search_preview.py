# -*- coding: utf-8 -*-
"""検索結果での見え方（robots の meta）と、画像・動画のサイトマップを3サイトとお客様の雛形で揃える。

**なぜ要るか**: 画像も動画も作って載せているのに、Google に「大きく出してよい」とも
「ここにある」とも伝えていなかった。どちらも Google が公式に説明している手段だけを使う。
AI専用の印や llms.txt のような、効くと確かめられていないものは足さない（CLAUDE.md 0.3節）。

build.py（AI集客ラボ）・subsidy/pages.py（補助金）・publish.py（お客様の配信先）が同じ関数を呼ぶ。
コーポレート（Next.js）は templates/corporate_sitemap.ts と --corporate で同じ形にする。

    python scripts/search_preview.py --check site            # 何ページに足すかを見る
    python scripts/search_preview.py --apply <dir>           # 静的サイトの全ページに足す
    python scripts/search_preview.py --corporate <Next.jsの作業コピー>   # コーポレートへ反映（push はしない）
"""
import html as _h
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent

# 値の意味と、1つの meta にカンマでまとめてよいこと: https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag
DIRECTIVES = ("max-snippet:-1", "max-image-preview:large", "max-video-preview:-1")
# https://developers.google.com/search/docs/crawling-indexing/sitemaps/image-sitemaps
NS_IMAGE = "http://www.google.com/schemas/sitemap-image/1.1"
# https://developers.google.com/search/docs/crawling-indexing/sitemaps/video-sitemaps
NS_VIDEO = "http://www.google.com/schemas/sitemap-video/1.1"
MAX_IMAGES = 1000      # 1つの <url> に載せられる画像の上限（公式）
MAX_VIDEO_DESC = 2048  # 動画の説明の上限（公式）

_ROBOTS_RX = re.compile(r'<meta\s+name="robots"\s+content="([^"]*)"\s*/?>', re.I)


def robots_tag(page: str) -> str:
    """robots の meta を1つにまとめ、見え方の指定を足す。noindex のページは一切触らない
    （noindex に max-* を足しても意味が無く、値を書き換えて noindex を落とす事故だけが起き得る）"""
    if "</head>" not in page:
        return page
    found = list(_ROBOTS_RX.finditer(page))
    vals = []
    for m in found:
        vals += [v.strip() for v in m.group(1).split(",") if v.strip()]
    if any(v.lower() in ("noindex", "none") for v in vals):
        return page
    have = {v.split(":")[0].lower() for v in vals}
    merged = vals + [d for d in DIRECTIVES if d.split(":")[0] not in have]
    tag = f'<meta name="robots" content="{", ".join(merged)}">'
    if not found:
        return page.replace("</head>", tag + "\n</head>", 1)
    if len(found) == 1 and found[0].group(0) == tag:
        return page
    # 2つ目以降を消し、最初の位置にまとめた1つを置く
    for m in reversed(found[1:]):
        end = m.end() + (1 if page[m.end():m.end() + 1] == "\n" else 0)
        page = page[:m.start()] + page[end:]
    m = found[0]
    return page[:m.start()] + tag + page[m.end():]


SKIP_DIRS = {".git", "node_modules", "dist", ".next", "out"}


def apply_dir(root: Path, write=True) -> int:
    """静的サイトの全ページに robots_tag を当てる。変えたページ数"""
    n = 0
    for f in Path(root).rglob("*.html"):
        if SKIP_DIRS & set(f.relative_to(root).parts):
            continue
        h = f.read_text(encoding="utf-8", errors="replace")
        u = robots_tag(h)
        if u != h:
            n += 1
            if write:
                f.write_text(u, encoding="utf-8", newline="\n")
    return n


def x(s) -> str:
    """XML に入れる文字の退避（& < > " が混ざるとサイトマップ全体が読めなくなる）"""
    return _h.escape(str(s), quote=True)


def page_images(page: str, slug: str, origin: str, exists) -> list:
    """記事の画像（アイキャッチ・図解）。パスに記事のスラッグを含むものだけ＝その記事のために作った画像。
    ロゴ・著者写真のような共通画像は、どの記事にも出るので載せない。exists(パス) が偽のものは載せない"""
    out = []
    srcs = re.findall(r'<img\b[^>]*?\ssrc="([^"]+)"', page) + \
        re.findall(r'<meta property="og:image" content="([^"]+)"', page)
    for s in srcs:
        u = urlparse(_h.unescape(s))
        if u.netloc and u.netloc != urlparse(origin).netloc:
            continue
        if f"/{slug}/" not in u.path or not exists(u.path):
            continue
        full = origin.rstrip("/") + u.path
        if full not in out:
            out.append(full)
    return out[:MAX_IMAGES]


def _seconds(iso):
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", str(iso or ""))
    return (int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)) if m else 0


def page_videos(page: str) -> list:
    """ページに埋め込んだ動画（VideoObject の JSON-LD）。サイトマップの題・説明をページの構造化データと
    同じにする（公式は「動画を載せたページの説明と一致すること」を求める）。必須がそろわないものは載せない"""
    out = []
    ld_rx = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
    shown = ld_rx.sub("", page)
    for raw in ld_rx.findall(page):
        try:
            ld = json.loads(raw)
        except ValueError:
            continue
        for v in (ld if isinstance(ld, list) else ld.get("@graph", [ld]) if isinstance(ld, dict) else []):
            if not (isinstance(v, dict) and v.get("@type") == "VideoObject"):
                continue
            thumb = v.get("thumbnailUrl")
            thumb = thumb[0] if isinstance(thumb, list) and thumb else thumb
            player = v.get("embedUrl")
            if not (thumb and v.get("name") and v.get("description") and player):
                continue
            if "/embed/" + player.rstrip("/").rsplit("/", 1)[-1] not in shown:
                continue  # 構造化データだけあって、実際には埋め込まれていない
            out.append({"thumbnail_loc": thumb, "title": v["name"],
                        "description": str(v["description"])[:MAX_VIDEO_DESC],
                        "player_loc": player, "duration": _seconds(v.get("duration")),
                        "publication_date": v.get("uploadDate") or ""})
    return out


def url_xml(loc, lastmod="", images=(), videos=(), extra="") -> str:
    """<url> 1つ分。画像・動画が無ければ従来と同じ1行"""
    head = f"<loc>{x(loc)}</loc>" + (f"<lastmod>{x(lastmod)}</lastmod>" if lastmod else "") + extra
    if not images and not videos:
        return f"  <url>{head}</url>"
    parts = [f"  <url>{head}"]
    parts += [f"    <image:image><image:loc>{x(i)}</image:loc></image:image>" for i in images]
    for v in videos:
        d = v.get("duration") or 0
        parts.append(
            "    <video:video>"
            f"<video:thumbnail_loc>{x(v['thumbnail_loc'])}</video:thumbnail_loc>"
            f"<video:title>{x(v['title'])}</video:title>"
            f"<video:description>{x(v['description'])}</video:description>"
            f"<video:player_loc>{x(v['player_loc'])}</video:player_loc>"
            + (f"<video:duration>{d}</video:duration>" if 1 <= d <= 28800 else "")
            + (f"<video:publication_date>{x(v['publication_date'])}</video:publication_date>"
               if v.get("publication_date") else "")
            + "</video:video>")
    parts.append("  </url>")
    return "\n".join(parts)


def media_lines(page: str, slug: str, origin: str, exists) -> str:
    """<url> の中に差し込む画像・動画の行（改行つき）。複数行で <url> を書く生成器から使う"""
    lines = url_xml("x", "", page_images(page, slug, origin, exists), page_videos(page)).split("\n")
    return "".join(l + "\n" for l in lines[1:-1])


def urlset_open(images=True, videos=True) -> str:
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
            + (f' xmlns:image="{NS_IMAGE}"' if images else "")
            + (f' xmlns:video="{NS_VIDEO}"' if videos else "") + ">")


def ensure_ns(sitemap: str) -> str:
    """既存のサイトマップに画像・動画の名前空間を足す（先方の sitemap.xml に追記するとき）"""
    m = re.search(r"<urlset\b[^>]*>", sitemap)
    if not m:
        return sitemap
    tag = m.group(0)
    new = tag
    if "image:" in sitemap and "xmlns:image=" not in tag:
        new = new[:-1] + f' xmlns:image="{NS_IMAGE}">'
    if "video:" in sitemap and "xmlns:video=" not in tag:
        new = new[:-1] + f' xmlns:video="{NS_VIDEO}">'
    return sitemap.replace(tag, new, 1)


def check_sitemap(text: str) -> list:
    """サイトマップの壊れを数える（XMLとして読めるか・名前空間・画像の上限・動画の必須）。空なら正常"""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as e:
        return [f"XMLとして読めません: {e}"]
    sm = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    bad = []
    for u in root.iter(sm + "url"):
        loc = (u.findtext(sm + "loc") or "").strip()
        if len(u.findall(f"{{{NS_IMAGE}}}image")) > MAX_IMAGES:
            bad.append(f"{loc}: 画像が{MAX_IMAGES}を超えています")
        for v in u.findall(f"{{{NS_VIDEO}}}video"):
            need = [t for t in ("thumbnail_loc", "title", "description") if not (v.findtext(f"{{{NS_VIDEO}}}{t}") or "").strip()]
            if not (v.findtext(f"{{{NS_VIDEO}}}player_loc") or v.findtext(f"{{{NS_VIDEO}}}content_loc")):
                need.append("player_loc/content_loc")
            if len(v.findtext(f"{{{NS_VIDEO}}}description") or "") > MAX_VIDEO_DESC:
                need.append("description が2048字超")
            if need:
                bad.append(f"{loc}: 動画の必須が欠けています（{', '.join(need)}）")
    return bad


LAYOUT_RX = re.compile(r"(robots:\s*\{\s*index:\s*true,\s*follow:\s*true,)(\s*\},)")
LAYOUT_ADD = '\n    "max-image-preview": "large",\n    "max-snippet": -1,\n    "max-video-preview": -1,'


def corporate(dest: Path) -> list:
    """コーポレート（Next.js）の作業コピーに反映する。push はしない（呼び出し側が確かめて押す）。
    noindex のページ（privacy 等）は各ページが robots を丸ごと上書きしているので、そのまま noindex が残る"""
    changed = []
    lay = dest / "src" / "app" / "layout.tsx"
    t = lay.read_text(encoding="utf-8")
    if "max-image-preview" not in t:
        u = LAYOUT_RX.sub(lambda m: m.group(1) + LAYOUT_ADD + m.group(2), t, count=1)
        if u == t:
            raise SystemExit("layout.tsx の robots の書き方が想定と違います。手で足してください")
        lay.write_text(u, encoding="utf-8", newline="\n")
        changed.append(lay)
    sm = dest / "src" / "app" / "sitemap.ts"
    new = (ROOT / "templates" / "corporate_sitemap.ts").read_text(encoding="utf-8")
    if sm.read_text(encoding="utf-8") != new:
        sm.write_text(new, encoding="utf-8", newline="\n")
        changed.append(sm)
    return changed


def main():
    a = sys.argv[1:]
    if len(a) == 2 and a[0] in ("--check", "--apply"):
        n = apply_dir(Path(a[1]), write=a[0] == "--apply")
        print(f"SEARCH_PREVIEW_PAGES={n}")
        sm = Path(a[1]) / "sitemap.xml"
        if sm.is_file():
            bad = check_sitemap(sm.read_text(encoding="utf-8"))
            print(f"SEARCH_PREVIEW_OK={'no' if bad else 'yes'}")
            for b in bad[:20]:
                print("  " + b)
    elif len(a) == 2 and a[0] == "--corporate":
        for f in corporate(Path(a[1])):
            print(f"更新: {f}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
