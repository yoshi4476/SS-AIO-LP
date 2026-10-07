# -*- coding: utf-8 -*-
"""外部プロフィール（LinkedIn・note）のアイコンを、3サイトのフッターに置く。

構造化データの sameAs だけでは、機械には伝わっても読者には見えない。
フッターから実際にたどれることで、外部の足跡が「実在する人物・会社の証拠」として働く
（人がたどるリンクは、検索エンジンにも同じ意味で読まれる）。

  python scripts/social_footer.py            # 何が変わるか
  python scripts/social_footer.py --apply    # 入れる
  python scripts/social_footer.py --apply --subsidy <補助金サイトの作業コピー>

対象:
  AI集客ラボ  templates/article.html・scripts/build.py の雛形・site/**.html（暗い足元。白の輪郭）
  補助金      .publish-work/subsidy/**.html（フッターが2種類あるので両方見る。明るい足元なので灰色の輪郭・中央）
  コーポレート  src/components/Footer.tsx は React のため手で入れる（この道具では触らない）

足元の色は社ごとに違う（SITE_CSS）。補助金サイトの各ページの CSS は、暗い足元用のものが入っていれば入れ替える。
何度実行しても同じ結果（既に入っていれば何もしない）。
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINKEDIN = "https://www.linkedin.com/in/yu-haraguchi"
NOTE = "https://note.com/yu_haraguchi"
MARK = "social-links"

# LinkedIn の公式グリフ。note は正確な図形を再現できないため、誤った形を描かず文字で置く
LI_SVG = ('<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false" fill="currentColor">'
          '<path d="M20.45 20.45h-3.56v-5.57c0-1.33-.03-3.04-1.85-3.04-1.86 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05'
          'c.47-.9 1.63-1.85 3.36-1.85 3.6 0 4.27 2.37 4.27 5.45v6.29zM5.34 7.43a2.07 2.07 0 1 1 0-4.14 2.07 2.07 0 0 1 0 4.14z'
          'M7.12 20.45H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.72'
          'V1.72C24 .77 23.2 0 22.22 0z"/></svg>')

BLOCK = (f'<ul class="{MARK}" aria-label="外部プロフィール">'
         f'<li><a href="https://x.com/sevensensece" target="_blank" rel="noopener me" aria-label="X（セブンセンシズ株式会社）" data-net="x"><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false" fill="currentColor"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg></a></li>'
         f'<li><a href="{LINKEDIN}" target="_blank" rel="noopener me" aria-label="LinkedIn（原口 優）" '
         f'data-net="linkedin">{LI_SVG}</a></li>'
         f'<li><a href="{NOTE}" target="_blank" rel="noopener me" aria-label="note（原口 優）" '
         f'data-net="note"><span>note</span></a></li></ul>')

CSS = """
/* 外部プロフィール（フッター）。暗い面に置くので、既定は白の輪郭、触れると各サービスの色 */
.social-links { list-style: none; display: flex; gap: .55rem; margin: .9rem 0 0; padding: 0; }
.social-links a { display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px;
  border: 1px solid rgba(255,255,255,.28); border-radius: 50%; color: rgba(255,255,255,.82);
  text-decoration: none; transition: background-color .2s, border-color .2s, color .2s; }
.social-links a span { font-size: .66rem; font-weight: 700; letter-spacing: .02em; }
.social-links a:hover, .social-links a:focus-visible { color: #fff; border-color: transparent; }
.social-links a[data-net="linkedin"]:hover, .social-links a[data-net="linkedin"]:focus-visible { background: #0a66c2; }
.social-links a[data-net="x"]:hover, .social-links a[data-net="x"]:focus-visible { background: #000; }
.social-links a[data-net="note"]:hover, .social-links a[data-net="note"]:focus-visible { background: #41c9b4; }
"""

# 明るい面の足元（補助金サイトはアイボリー #f4f1e9）。暗い面用の白い輪郭のままだと地の色と 1.1:1 で見えず、
# 中央揃えの足元で左端に寄っていた（2026-10-07 の点検）。社ごとに色を持ち、ほかの社の見た目は変えない
CSS_LIGHT = """
/* 外部プロフィール（フッター）。明るい面に置くので、灰色の輪郭で中央に並べ、触れると各サービスの色 */
.social-links { list-style: none; display: flex; flex-wrap: wrap; justify-content: center; gap: .6rem; margin: .9rem 0 0; padding: 0; }
.social-links a { display: inline-flex; align-items: center; justify-content: center; width: 40px; height: 40px;
  border: 1px solid #d8d2c2; border-radius: 50%; color: #5b6472; background: #fff;
  text-decoration: none; transition: background-color .2s, border-color .2s, color .2s; }
.social-links a span { font-size: .72rem; font-weight: 700; letter-spacing: .02em; }
.social-links a:hover, .social-links a:focus-visible { color: #fff; border-color: transparent; }
.social-links a[data-net="linkedin"]:hover, .social-links a[data-net="linkedin"]:focus-visible { background: #0a66c2; }
.social-links a[data-net="x"]:hover, .social-links a[data-net="x"]:focus-visible { background: #000; }
.social-links a[data-net="note"]:hover, .social-links a[data-net="note"]:focus-visible { background: #41c9b4; }
"""
SITE_CSS = {"subsidy": CSS_LIGHT}
# 補助金サイトの各ページの head に入れた CSS（古いものは id が無い）。見出しのコメントで見分けて入れ替える
STYLE_RX = re.compile(r'<style(?: id="social-css")?>\s*/\* 外部プロフィール（フッター）.*?</style>', re.S)


def css_for(site):
    """その社の足元に合う CSS（指定の無い社は暗い面用）"""
    return SITE_CSS.get(site, CSS)


def style_tag(site):
    return f'<style id="social-css">{css_for(site)}</style>'


def fix_style(text, site, nl="\n"):
    """アイコンを置いたページの CSS を、その社の足元の色に揃える（暗い面用の古い CSS は入れ替える）。
    アイコンの無いページは触らない。nl はそのページの改行（CRLF のページに LF を混ぜない）。何度当てても同じ結果"""
    if f'<ul class="{MARK}"' not in text:
        return text
    want = style_tag(site).replace("\n", nl)
    if STYLE_RX.search(text):
        return STYLE_RX.sub(lambda _: want, text, count=1)
    return text.replace("</head>", want + nl + "</head>", 1) if "</head>" in text else text

# 置く場所。AI集客ラボは住所の段落の直後、補助金はページによってフッターが2種類ある
AI_ANCHOR = r'<p class="addr">.*?</p>'
SUB_ANCHORS = (r'<p>セブンセンシズ株式会社<br>.*?</p>',
               r'<p>© \d{4} SEVEN SENSES INC\..*?</p>')


def _walk(base):
    return sorted(p for p in base.rglob("*.html")
                  if ".git" not in p.parts and "node_modules" not in p.parts)


def insert(text, anchor_rx):
    """anchor の直後に1つだけ入れる。既にあれば触らない"""
    if MARK in text:
        return text
    m = re.search(anchor_rx, text, re.S)
    if not m:
        return text
    return text[: m.end()] + "\n      " + BLOCK + text[m.end():]


def subsidy_page(text):
    """補助金サイトの1ページ: アイコンが無ければ足元に入れ、CSS を明るい足元の色に揃える（改行はそのページのまま）"""
    nl = "\r\n" if "\r\n" in text else "\n"
    u = text
    for rx in SUB_ANCHORS:
        u = insert(u, rx)
        if u != text:
            u = u.replace("\n      " + BLOCK, nl + "      " + BLOCK, 1) if nl != "\n" else u
            break
    return fix_style(u, "subsidy", nl)


def run(write, subsidy=None):
    changed = []
    # ── AI集客ラボ（雛形・生成側・公開済みの固定ページ）
    for p in [ROOT / "templates" / "article.html", ROOT / "scripts" / "build.py"] + _walk(ROOT / "site"):
        t = p.read_text(encoding="utf-8", errors="surrogateescape")
        u = insert(t, AI_ANCHOR)
        if u != t:
            changed.append(p)
            if write:
                p.write_text(u, encoding="utf-8", errors="surrogateescape", newline="\n")
    css = ROOT / "site" / "css" / "style.css"
    if MARK not in css.read_text(encoding="utf-8"):
        changed.append(css)
        if write:
            css.write_text(css.read_text(encoding="utf-8").rstrip("\n") + "\n" + CSS,
                           encoding="utf-8", newline="\n")
    # ── 補助金（配信先の作業コピー。無ければ飛ばす）。外部CSSを持たないページがあるため、CSS は各ページの head に入れる
    sub = Path(subsidy) if subsidy else ROOT / ".publish-work" / "subsidy"
    if sub.is_dir():
        for p in _walk(sub):
            # 改行コードは元のまま（変換すると、アイコンと関係ない全行が差分になる）
            t = p.read_bytes().decode("utf-8", "surrogateescape")
            u = subsidy_page(t)
            if u == t:
                continue
            changed.append(p)
            if write:
                p.write_bytes(u.encode("utf-8", "surrogateescape"))
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--subsidy", default="", help="補助金サイトの作業コピー（既定は .publish-work/subsidy）")
    a = ap.parse_args()
    changed = run(a.apply, a.subsidy or None)
    print(f"{'入れた' if a.apply else '入れる'}: {len(changed)}ファイル")
    for p in changed[:6]:
        print("  ", p.relative_to(ROOT).as_posix() if p.is_relative_to(ROOT) else p.as_posix())
    if len(changed) > 6:
        print(f"   …ほか{len(changed) - 6}")
    if not a.apply and changed:
        print("  --apply で書き換えます")
    print("  ※ コーポレート（Next.js）の Footer.tsx は別途")
    return 0


if __name__ == "__main__":
    sys.exit(main())
