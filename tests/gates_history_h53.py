# -*- coding: utf-8 -*-
"""補助金サイト（lp.7senses.co.jp）の見た目とリード導線の点検（2026-10-07）から作った門。

- トップにだけナビがあり、記事・制度・サービスのヘッダーはロゴと「無料で相談する」だけで、スマホにはメニューも無かった。
  比較・用語集・調査のページはどこからもたどれなかった → scripts/subsidy/pages.py がヘッダーを1か所に持ち、
  配信のたびに全ページ（手書きのトップ・固定ページ・記事と比較などの雛形・記事）へ揃える
- トップの「最新ノウハウ」は手で並べた7月の3本のままで、3枚目は記事の統合で写真が 404 → 配信のたびに新しい3本へ差し替える
- 一覧の小見出しが、制度・業種のページでも「Blog — 毎日更新」だった
- 足元の SNS アイコンは暗い足元用の白い輪郭のままで、明るい足元では地の色と 1.1:1 で見えなかった
  → 社ごとに色を持つ（AI集客ラボの暗い足元は変えない）
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

OLD_HEAD = ('<header>\n  <div class="nav">\n    <a class="logo" href="/"><img src="/assets/img/logo-h.webp" alt="x" width="372" height="148"></a>\n'
            '    <a class="cta" href="/#contact">無料で相談する</a>\n  </div>\n</header>')
DARK_SOCIAL = ('<style>\n/* 外部プロフィール（フッター）。暗い面に置くので、既定は白の輪郭、触れると各サービスの色 */\n'
               '.social-links a { border: 1px solid rgba(255,255,255,.28); color: rgba(255,255,255,.82); }\n</style>')


def _page(title, date, head="", body=""):
    return ('<!DOCTYPE html>\n<html lang="ja">\n<head>\n<meta charset="UTF-8">\n'
            f'<title>{title}|セブンセンシズ株式会社</title>\n<meta name="description" content="{title}についての説明です。">\n'
            '<meta name="robots" content="index, follow, max-snippet:-1, max-image-preview:large, max-video-preview:-1">\n'
            f'<script type="application/ld+json">{{"datePublished": "{date}", "dateModified": "{date}"}}</script>\n{head}</head>\n<body>\n'
            f'{OLD_HEAD}\n<main><span class="cat">補助金</span><h1>{title}</h1>{body}</main>\n'
            '<footer>\n  <nav><a href="/">トップ</a></nav>\n  <p>© 2026 SEVEN SENSES INC.</p>\n'
            '      <ul class="social-links" aria-label="外部プロフィール"></ul>\n</footer>\n</body>\n</html>\n')


def _run_pages(root):
    env = dict(os.environ, SUBSIDY_ROOT=str(root), PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "subsidy" / "pages.py")], env=env, cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _contrast(a, b):
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_subsidy_pages_share_one_header_and_latest_posts():
    print("\n■ 補助金サイト: ヘッダー（ナビ・スマホのメニュー）を全ページで揃え、トップの最新記事を差し替える")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for slug, date in (("old-post", "2026-07-20"), ("new-post", "2026-10-06"), ("mid-post", "2026-09-01"), ("first-post", "2026-07-01")):
            (root / "blog" / slug).mkdir(parents=True)
            (root / "blog" / slug / "index.html").write_text(_page(f"記事{slug}", date, DARK_SOCIAL), encoding="utf-8", newline="\n")
        (root / "images" / "blog" / "new-post").mkdir(parents=True)
        (root / "images" / "blog" / "new-post" / "thumbnail.webp").write_bytes(b"x")
        top = _page("トップ", "2026-07-21", body='<div class="blog-grid"><!--latest--><a class="post" href="/blog/gone/">手で並べた記事</a><!--/latest--></div>')
        (root / "index.html").write_bytes(top.replace("\n", "\r\n").encode("utf-8"))   # Windows で書いたページ（CRLF）
        (root / "service" / "x").mkdir(parents=True)
        (root / "service" / "x" / "index.html").write_text(_page("サービス", "2026-07-21", body='<section id="svcform"></section>'), encoding="utf-8", newline="\n")
        (root / "compare").mkdir()
        (root / "compare" / "index.html").write_text(_page("比較", "2026-10-01"), encoding="utf-8", newline="\n")
        code, out = _run_pages(root)
        check("pages.py が最後まで動く", (code, "done" in out), (0, True))
        top = (root / "index.html").read_bytes().decode("utf-8")
        svc = (root / "service" / "x" / "index.html").read_text(encoding="utf-8")
        art = (root / "blog" / "old-post" / "index.html").read_text(encoding="utf-8")
        lst = (root / "blog" / "index.html").read_text(encoding="utf-8")
        for name, t in (("トップ", top), ("サービス", svc), ("記事", art), ("一覧", lst)):
            check(f"{name}: 共通のヘッダー・CSS・動きが1つずつで、古いヘッダーが残らない",
                  (t.count('id="gh"'), t.count('id="ss-common"'), t.count('id="ss-common-js"'), 'class="nav"' in t), (1, 1, 1, False))
            check(f"{name}: スマホのメニューのボタン", ('class="gh-menu"' in t, 'aria-controls="gh-nav"' in t), (True, True))
        check("ナビから配信先にある比較のページへ行ける", 'href="/compare/"' in art, True)
        check("配信先に無いページへはナビから送らない（用語集は無い）", 'href="/glossary/"' in art, False)
        check("ページ内に相談の入力欄があるページは、ヘッダーの相談もそこへ",
              ('class="gh-cta" href="#svcform"' in svc, 'class="gh-cta" href="/#contact"' in art), (True, True))
        latest = top.split("<!--latest-->", 1)[1].split("<!--/latest-->", 1)[0]
        check("トップの最新記事: 新しい3本に差し替わり、手で並べた記事・4本目は出ない",
              [f"/blog/{s}/" in latest for s in ("new-post", "mid-post", "old-post", "first-post", "gone")], [True, True, True, False, False])
        check("トップの最新記事: 新しい順", latest.find("/blog/new-post/") < latest.find("/blog/mid-post/") < latest.find("/blog/old-post/"), True)
        check("トップの最新記事: 記事の写真があればそれを使う", "/images/blog/new-post/thumbnail.webp" in latest, True)
        check("CRLF のページに LF だけの改行を混ぜない", top.count("\n"), top.count("\r\n"))
        check("足元のアイコンの CSS は明るい足元の色に入れ替わる",
              ('id="social-css"' in art, "#d8d2c2" in art, "rgba(255,255,255,.82)" in art), (True, True, False))
        check("一覧の小見出しは中身に合う日本語（「Blog — 毎日更新」を出さない）", ("Blog — 毎日更新" in lst, "記事一覧（毎日更新）" in lst), (False, True))
        before = {p: p.read_bytes() for p in root.rglob("*.html")}
        code, _ = _run_pages(root)
        check("2回回しても、どのページも変わらない", (code, sorted(str(p.relative_to(root)) for p, b in before.items() if p.read_bytes() != b)), (0, []))
    src = (ROOT / "scripts" / "subsidy" / "pages.py").read_text(encoding="utf-8")
    check("制度・業種の一覧の小見出しを中身に合わせる", ('kicker="制度から探す"' in src, 'kicker="業種から探す"' in src, '<p class="kicker">Blog' in src), (True, True, False))
    m = re.search(r"\.post p\{font-size:([\d.]+)px", src)
    check("一覧の抜粋は 15px 以上（12.5px で1ページ 9,300字超を読ませていた）", bool(m) and float(m.group(1)) >= 15, True)
    check("Windows で本文が細くならない（游ゴシック Medium を先に使う）",
          ('local("Yu Gothic Medium")' in src, '"Hiragino Sans","YuGothicM","Yu Gothic"' in src), (True, True))


def test_social_footer_colors_per_site():
    print("\n■ 足元の外部プロフィール: 社ごとの足元の色（明るい足元で白い輪郭にしない。AI集客ラボの暗い足元は変えない）")
    import social_footer as SF
    check("AI集客ラボは暗い足元用のまま", (SF.css_for("ai-lab") == SF.CSS, "rgba(255,255,255,.28)" in SF.CSS), (True, True))
    light = SF.css_for("subsidy")
    check("補助金は灰色の輪郭で中央に並べる", ("#d8d2c2" in light, "color: #5b6472" in light, "justify-content: center" in light), (True, True, True))
    check("アイコンの色は白い丸の上・足元の地の上で 4.5:1 以上", (_contrast("#5b6472", "#ffffff") >= 4.5, _contrast("#5b6472", "#f4f1e9") >= 4.5), (True, True))
    page = "<head>\n" + DARK_SOCIAL + "\n</head><footer><ul class=\"social-links\"></ul></footer>"
    once = SF.fix_style(page, "subsidy")
    check("暗い足元用の CSS を入れ替え、何度当てても同じ",
          (once.count('id="social-css"'), "rgba(255,255,255,.82)" in once, SF.fix_style(once, "subsidy")), (1, False, once))
    check("アイコンの無いページは触らない", SF.fix_style("<head></head><p>x</p>", "subsidy"), "<head></head><p>x</p>")
    crlf = SF.fix_style(page.replace("\n", "\r\n"), "subsidy", "\r\n")
    check("CRLF のページには CRLF で入れる", crlf.count("\n"), crlf.count("\r\n"))
