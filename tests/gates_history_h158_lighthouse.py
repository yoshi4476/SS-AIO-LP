# -*- coding: utf-8 -*-
"""2026-11-12 Lighthouse のアクセシビリティ・ベストプラクティスで、AI集客ラボの3ページが満点でなかった
（トップ 95・サービスのページ 99・記事のベストプラクティス 96）。原因は3つ:
1. 図の札（白い 11px の字）の下地の濃さが 3.74（基準 4.5）
2. 最初の画面の採点表の小見出しが、h1 のすぐ下で h3（見出しの順番の飛び）
3. 記事の動画の埋め込みが、押す前から YouTube の Cookie の指摘を出す
"""
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _lum(hexcolor):
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_chart_key_text_has_enough_contrast():
    print("\n■ 図の札: 白い小さい字の下地は、濃さの比が 4.5 以上")
    css = (ROOT / "site" / "css" / "style.css").read_text(encoding="utf-8")
    m = re.search(r"\.rsx-key\.loc \{ background: (#[0-9a-fA-F]{6}); \}", css)
    check("検算の道具は、足りない色（3.74）と足りる色を見分ける",
          (round(_ratio("#ffffff", "#0d9488"), 2) < 4.5, _ratio("#ffffff", "#0f766e") >= 4.5), (True, True))
    check("札（探す）の下地を、白い字で 4.5 以上になる色で上書きしている", bool(m) and _ratio("#ffffff", m.group(1)) >= 4.5, True)


def test_hero_console_does_not_skip_heading_levels():
    print("\n■ 最初の画面の採点表: h1 のすぐ下に h3 を置かない（見出しの順番を飛ばさない）")
    for f in ("index.html", "lp/index.html"):
        h = (ROOT / "site" / f).read_text(encoding="utf-8")
        hero = h[h.find('class="lx-console"'):h.find("</section>", h.find('class="lx-console"'))]
        check(f"{f}: 採点表の小見出しは見出しの要素ではない（3つ）", (len(re.findall(r"<h[2-6]", hero)), hero.count('<p class="lx-gh">')), (0, 3))
    js = (ROOT / "site" / "js" / "lp-scan.js").read_text(encoding="utf-8")
    css = (ROOT / "site" / "css" / "lp-v2.css").read_text(encoding="utf-8")
    check("点数を書き込む処理と見た目の定義も、同じ名前（lx-gh）を見る",
          ('$(".lx-gh span", g)' in js, ".lx-group .lx-gh {" in css, ".lx-group h3" in css), (True, True, False))


def test_article_video_loads_youtube_only_after_click():
    import video_embed as VE
    print("\n■ 記事の動画: AI集客ラボでは、押すまで YouTube を読み込まない")
    out = VE.facade("abcdEFGhijk", '題 "引用" <b>')
    check("先にサムネイルと再生の印だけを出し、押した先が同じ動画の埋め込み",
          ('srcdoc="' in out, "https://i.ytimg.com/vi/abcdEFGhijk/hqdefault.jpg" in out,
           "https://www.youtube-nocookie.com/embed/abcdEFGhijk?autoplay=1" in out, "aria-label=&#x27;動画を再生する&#x27;" in out),
          (True, True, True, True))
    check("題の引用符や印で、属性が途中で切れない", (out.count('title="'), '"引用"' in out, "<b>" in out.split("srcdoc=")[0]), (1, False, False))
    check("srcdoc が使えない環境のために、src にも埋め込みの場所を残す", out.startswith('<iframe src="https://www.youtube-nocookie.com/embed/abcdEFGhijk" '), True)
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("AI集客ラボのビルドはこの形で埋め込む（配信先のサイトはこれまでどおり）",
          ("video_embed.prepend(content, meta, click_to_load=True)" in src,
           "click_to_load" in (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")), (True, False))
    pages = [p for p in (ROOT / "site").rglob("index.html") if '<figure class="article-video"' in p.read_text(encoding="utf-8")]
    plain = [p.parent.name for p in pages if 'srcdoc="' not in p.read_text(encoding="utf-8").split('<figure class="article-video"')[1].split("</figure>")[0]]
    check("公開中の記事ページの動画も、押すまで読み込まない形になっている", plain, [])


def test_article_eyecatch_has_a_small_version_for_phones():
    """2026-11-12 記事の冒頭の画像（最初の画面で優先して読む画像）が横 1600px で、スマホには 2 倍以上大きかった
    （Google の計測で LCP 2.7 秒・性能 95 点）。横 800px の版を作り、画面の幅に合う方を読ませる"""
    import tempfile
    from pathlib import Path
    from PIL import Image
    import build as B
    print("\n■ 記事の冒頭の画像: スマホ用の横 800px の版があり、srcset で選ばせる")
    with tempfile.TemporaryDirectory() as td:
        site = Path(td)
        (site / "images" / "x").mkdir(parents=True)
        Image.new("RGB", (1600, 900), (120, 130, 140)).save(site / "images" / "x" / "big.webp", "WEBP")
        Image.new("RGB", (640, 360), (120, 130, 140)).save(site / "images" / "x" / "tiny.webp", "WEBP")
        ss = B.eyecatch_srcset("/images/x/big.webp?v=abc", site)
        check("大きい画像には小さい版を作り、srcset と sizes を出す（版の印は外して書く）",
              ((site / "images" / "x" / "big-800.webp").is_file(), ss),
              (True, ' srcset="/images/x/big-800.webp 800w, /images/x/big.webp 1600w" sizes="(max-width: 860px) 100vw, 980px"'))
        check("小さい版の大きさは横 800px で、縦横の比は同じ", Image.open(site / "images" / "x" / "big-800.webp").size, (800, 450))
        check("元が 800px 以下の画像・無い画像には何も足さない（これまでどおり1枚だけ）",
              (B.eyecatch_srcset("/images/x/tiny.webp", site), B.eyecatch_srcset("/images/x/none.webp", site)), ("", ""))
    pages = [p for p in (ROOT / "site").rglob("index.html") if '<figure class="article-eyecatch">' in p.read_text(encoding="utf-8")]
    bad = []
    for p in pages:
        tag = re.search(r'<figure class="article-eyecatch"><img[^>]*>', p.read_text(encoding="utf-8")).group(0)
        m = re.search(r'srcset="(/images/[^" ]+-800\.webp)(?:\?v=[0-9a-f]+)? 800w, ', tag)
        if not m or not (ROOT / "site" / m.group(1).lstrip("/")).is_file() or 'fetchpriority="high"' not in tag:
            bad.append(p.parent.name)
    check("公開中の記事ページの冒頭の画像は、小さい版つきで優先して読む", (len(pages) > 100, bad[:5]), (True, []))
