# -*- coding: utf-8 -*-
"""表示速度を直す（3サイト共通の方針）。

Lighthouse（モバイル）で3サイトとも LCP が 7〜13秒だった。サーバー応答は 50〜100ms で
速い。原因は運ぶ量で、1ページ 1.5〜2.2MB のうち **日本語Webフォントが 1.0〜1.4MB**
（Noto Sans JP は文字範囲ごとに 60〜100 本に分割され、日本語の本文はそのほとんどに
触れる）。次いで GA4 の計測タグ 172KB を描画より先に読んでいた。

方針:
  1. 日本語のWebフォントをやめ、端末のフォント（ヒラギノ／游ゴシック／Noto Sans CJK）を使う。
     英数字用（Outfit / Oswald）も外す。描画後に見出しが描き直されて LCP が0.6秒伸びた。
     コーポレートの Space Grotesk は next/font の自前配信（2本・25KB）なので残す
  2. 計測タグは描画の後（load から 1.2 秒後）に読む。それまでの出来事は dataLayer に
     溜まり、読み込み後にまとめて送られるので計測は落ちない
  3. 本文の画像は遅延読み込み。アイキャッチ（LCP候補）は優先読み込み

  python scripts/speed_fix.py --site ai-lab            # 何が変わるか
  python scripts/speed_fix.py --site ai-lab --apply    # 直す
  python scripts/speed_fix.py --site subsidy --apply   # .publish-work/subsidy の全HTML
  python scripts/speed_fix.py --site corporate --apply # .publish-work/corporate の layout / globals.css

何度実行しても同じ結果（2回目は変更なし）。
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYS_SANS = ('"Hiragino Kaku Gothic ProN", "Hiragino Sans", "Yu Gothic", "Noto Sans JP", '
            '"Noto Sans CJK JP", "BIZ UDPGothic", Meiryo, sans-serif')
SYS_SERIF = '"Hiragino Mincho ProN", "Yu Mincho", "Noto Serif JP", "Noto Serif CJK JP", serif'
# 英数字のWebフォント（Outfit / Oswald）も外す。1本32KBでも、読み込み後に見出しが描き直されて
# LCP が 2.1秒→2.7秒に伸びた（基準 2.5秒）。数字は端末のフォントで描く
LATIN = {}

DEFER_GTAG = (
    "<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
    "gtag('js',new Date());gtag('config','{gid}');\n"
    "/* 計測タグ(172KB)は描画の後に読む。先に読むと文字が出るのが遅れる。"
    "それまでの出来事は dataLayer に溜まり、読み込み後にまとめて送られる */\n"
    "window.addEventListener('load',function(){{setTimeout(function(){{var s=document.createElement('script');"
    "s.async=true;s.src='https://www.googletagmanager.com/gtag/js?id={gid}';document.head.appendChild(s);}},1200);}});"
    "</script>"
)
_GTAG = re.compile(
    r'<script async src="https://www\.googletagmanager\.com/gtag/js\?id=(G-[A-Z0-9]+)"></script>\s*'
    r'<script>\s*window\.dataLayer=window\.dataLayer\|\|\[\];.*?</script>', re.S)
_FONT_LINKS = [
    re.compile(r'[ \t]*<link rel="preconnect" href="https://fonts\.googleapis\.com">\s*\n?'),
    re.compile(r'[ \t]*<link rel="preconnect" href="https://fonts\.gstatic\.com" crossorigin>\s*\n?'),
    re.compile(r'[ \t]*<link rel="preload" as="style" href="https://fonts\.googleapis\.com/[^"]*">\s*\n?'),
    re.compile(r'[ \t]*<noscript><link href="https://fonts\.googleapis\.com/[^"]*" rel="stylesheet"></noscript>\s*\n?'),
]
_FONT_CSS = re.compile(r'[ \t]*<link href="https://fonts\.googleapis\.com/css2\?family=[^"]*" rel="stylesheet"[^>]*>\s*\n?')
_IMG = re.compile(r"<img\b(?![^>]*\bloading=)([^>]*)>")


def latin_link(site):
    fam = LATIN.get(site)
    if not fam:
        return ""
    return ('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            f'<link href="https://fonts.googleapis.com/css2?family={fam}&display=swap" rel="stylesheet" '
            'media="print" onload="this.media=\'all\'">\n')


def fix_html(text, site, lazy_images=False):
    """フォントの読み方と計測タグを直す。変える所が無ければそのまま返す"""
    out = text
    # 直した印（ラテン文字だけの非同期リンク）が既にあれば、フォントは触らない（2回目で変わらないため）
    done = LATIN.get(site) and f'family={LATIN[site]}&display=swap" rel="stylesheet" media="print"' in out
    if not done:
        for rx in _FONT_LINKS:
            out = rx.sub("", out)
        m = _FONT_CSS.search(out)
        pos = m.start() if m else -1
        out = _FONT_CSS.sub("", out)          # Google Fonts のCSSを全部外してから
        latin = latin_link(site)
        if latin and "fonts.googleapis.com/css2" not in out:   # ラテン文字だけの非同期リンクを1つ入れる
            if pos < 0:
                m2 = re.search(r'[ 	]*<link rel="stylesheet"', out) or re.search(r"</head>", out)
                pos = m2.start() if m2 else -1
            if pos >= 0:
                out = out[:pos] + latin + out[pos:]
    out = _GTAG.sub(lambda m: DEFER_GTAG.format(gid=m.group(1)), out)
    if lazy_images:
        out = _lazy(out)
    return out


def _lazy(html):
    """最初の画像とロゴ以外を遅延読み込みにする"""
    seen = {"n": 0}

    def rep(m):
        attrs = m.group(1)
        seen["n"] += 1
        if seen["n"] == 1 or re.search(r'logo|hero|eyecatch|fetchpriority', attrs, re.I):
            return m.group(0)
        return f'<img{attrs} loading="lazy" decoding="async">'
    return _IMG.sub(rep, html)


def fix_css_vars(text, site):
    """フォント変数を端末のフォントに。日本語Webフォントの名前を先頭から外す"""
    out = text
    if site == "ai-lab":
        out = re.sub(r'--head:\s*"Zen Kaku Gothic New"[^;]*;', f"--head: {SYS_SANS};", out)
        out = re.sub(r'--sans:\s*"Noto Sans JP"[^;]*;', f"--sans: {SYS_SANS};", out)
    elif site == "subsidy":
        out = re.sub(r'--sans:"Noto Sans JP",sans-serif;', f"--sans:{SYS_SANS};", out)
        out = re.sub(r'--serif:"Shippori Mincho B1",serif;', f"--serif:{SYS_SERIF};", out)
        out = re.sub(r'--num:"Oswald","Noto Sans JP",sans-serif;', f'--num:"Oswald",{SYS_SANS};', out)
    return out


def _walk_html(base):
    return sorted(p for p in base.rglob("*.html") if ".git" not in p.parts and "node_modules" not in p.parts)


def apply_static(site, base, write, css_files=(), lazy_dirs=()):
    changed = []
    for p in _walk_html(base):
        t = p.read_text(encoding="utf-8", errors="surrogateescape")
        lazy = any(str(p).replace("\\", "/").startswith(str(d).replace("\\", "/")) for d in lazy_dirs)
        u = fix_html(fix_css_vars(t, site), site, lazy_images=lazy)
        if u != t:
            changed.append(p)
            if write:
                p.write_text(u, encoding="utf-8", errors="surrogateescape", newline="\n")
    for p in css_files:
        t = p.read_text(encoding="utf-8")
        u = fix_css_vars(t, site)
        if u != t:
            changed.append(p)
            if write:
                p.write_text(u, encoding="utf-8", newline="\n")
    return changed


def apply_corporate(base, write):
    """Next.js: next/font の日本語フォントをやめ、計測タグを後回しにし、資料画像を遅延にする"""
    changed = []
    lay = base / "src" / "app" / "layout.tsx"
    t = lay.read_text(encoding="utf-8")
    u = t.replace('import { Noto_Sans_JP, Space_Grotesk, Zen_Kaku_Gothic_New } from "next/font/google";',
                  'import { Space_Grotesk } from "next/font/google";')
    u = re.sub(r"// 日本語フォントは1ウェイト.*?(?=const zen = )", "", u, flags=re.S)
    u = re.sub(r"const zen = Zen_Kaku_Gothic_New\(\{.*?\}\);\n\n", "", u, flags=re.S)
    u = re.sub(r"const noto = Noto_Sans_JP\(\{.*?\}\);\n\n",
               "// 日本語のWebフォントは使わない。文字範囲ごとに60本以上・1MB超を読み、\n"
               "// モバイルの表示が13秒かかっていた。端末のフォント（globals.css）で描く\n", u, flags=re.S)
    u = u.replace("className={`${zen.variable} ${noto.variable} ${grotesk.variable} h-full antialiased`}",
                  "className={`${grotesk.variable} h-full antialiased`}")
    u = u.replace(
        "            <script async src={`https://www.googletagmanager.com/gtag/js?id=${site.ga4Id}`} />\n"
        "            <script\n"
        "              dangerouslySetInnerHTML={{\n"
        "                __html: `window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${site.ga4Id}');`,\n"
        "              }}\n"
        "            />",
        "            {/* 計測タグ(172KB)は描画の後に読む。それまでの出来事は dataLayer に溜まり、読み込み後にまとめて送られる */}\n"
        "            <script\n"
        "              dangerouslySetInnerHTML={{\n"
        "                __html: `window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${site.ga4Id}');"
        "window.addEventListener('load',function(){setTimeout(function(){var s=document.createElement('script');s.async=true;s.src='https://www.googletagmanager.com/gtag/js?id=${site.ga4Id}';document.head.appendChild(s);},1200);});`,\n"
        "              }}\n"
        "            />")
    if u != t:
        changed.append(lay)
        if write:
            lay.write_text(u, encoding="utf-8", newline="\n")
    css = base / "src" / "app" / "globals.css"
    t = css.read_text(encoding="utf-8")
    u = t.replace('--font-display: var(--font-zen), "Hiragino Kaku Gothic ProN", sans-serif;', f"--font-display: {SYS_SANS};")
    u = u.replace('--font-body: var(--font-noto), "Hiragino Kaku Gothic ProN", sans-serif;', f"--font-body: {SYS_SANS};")
    u = u.replace("--font-data: var(--font-grotesk), var(--font-noto), sans-serif;", f"--font-data: var(--font-grotesk), {SYS_SANS};")
    if u != t:
        changed.append(css)
        if write:
            css.write_text(u, encoding="utf-8", newline="\n")
    ms = base / "src" / "components" / "MediaShowcase.tsx"
    if ms.is_file():
        t = ms.read_text(encoding="utf-8")
        u = t.replace('loading={i < 2 ? "eager" : "lazy"}', 'loading="lazy"\n                    decoding="async"')
        if u != t:
            changed.append(ms)
            if write:
                ms.write_text(u, encoding="utf-8", newline="\n")
    return changed


def leftovers(base):
    """まだ残っている重い読み方（ゲート用）"""
    bad = []
    for p in _walk_html(base):
        t = p.read_text(encoding="utf-8", errors="surrogateescape")
        if re.search(r'fonts\.googleapis\.com/css2\?family=[^"]*(Noto\+Sans\+JP|Zen\+Kaku|Shippori)', t):
            bad.append((p, "日本語Webフォント"))
        if re.search(r'<link href="https://fonts\.googleapis\.com/[^"]*" rel="stylesheet">', t):
            bad.append((p, "描画を止めるフォントCSS"))
        if '<script async src="https://www.googletagmanager.com/gtag/js' in t:
            bad.append((p, "先に読む計測タグ"))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True, choices=["ai-lab", "subsidy", "corporate"])
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.site == "ai-lab":
        changed = apply_static("ai-lab", ROOT / "site", a.apply, css_files=[ROOT / "site" / "css" / "style.css"])
        changed += apply_static("ai-lab", ROOT / "templates", a.apply)
    elif a.site == "subsidy":
        base = ROOT / ".publish-work" / "subsidy"
        changed = apply_static("subsidy", base, a.apply, lazy_dirs=[base / "blog"])
    else:
        changed = apply_corporate(ROOT / ".publish-work" / "corporate", a.apply)
    print(f"{'直した' if a.apply else '直す'}: {len(changed)}ファイル")
    for p in changed[:8]:
        print("  ", p.relative_to(ROOT).as_posix())
    if len(changed) > 8:
        print(f"   …ほか{len(changed) - 8}")
    if not a.apply and changed:
        print("  --apply で書き換えます")
    return 0


if __name__ == "__main__":
    sys.exit(main())
