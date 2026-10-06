# -*- coding: utf-8 -*-
"""補助金サイト（lp.7senses.co.jp）のフッターに、LP の制作の関係を書いた表記を揃える。

フッターは作る場所が4つある（pages.py の FOOTER・配信先の blog/_template.html・
手書きの LP（index.html）と固定ページ・404）。1か所ずつ足すと漏れるため、表記はここの1か所に置き、
pages.py が配信のたびに配信先の全ページへ揃える（手書きのページも含む。何度実行しても同じ結果）。

関係を書いた相互リンクなので、文言を省かず、nofollow も付けない。

  python scripts/subsidy/footer_credit.py <補助金サイトの作業コピー>   # 揃える
"""
import re
import sys
from pathlib import Path

LABEL = "LP 制作：YW（CONFLUX PARTNERS）"
URL = "https://conflux-partners.jp/works/7senses-lp"
# ページごとにフッターの CSS が違う（固定ページ・LP・404）ため、見た目は親のフッターの色と文字の大きさを継ぐ
CREDIT = (f'<p class="footer-credit" style="margin:.4em 0 0;font-size:12px">'
          f'<a href="{URL}" target="_blank" rel="noopener" '
          f'style="color:inherit;text-decoration:underline;text-underline-offset:2px">{LABEL}</a></p>')

FOOT_RX = re.compile(r"<footer[^>]*>.*?</footer>", re.S)
CREDIT_RX = re.compile(r'(?:\r?\n)?[ \t]*<p class="footer-credit"[^>]*>.*?</p>', re.S)
COPY_RX = re.compile(r"<p[^>]*>[^<]*©[^<]*</p>")


def fix(text):
    """最初の <footer> の著作権表示の直後に表記を1つだけ置く（無ければ </footer> の直前）"""
    m = FOOT_RX.search(text)
    if not m:
        return text
    foot = CREDIT_RX.sub("", m.group(0))
    c = COPY_RX.search(foot)
    if c:
        indent = re.search(r"[ \t]*$", foot[:c.start()]).group(0)
        # Windows で書いたページは CRLF（pages.py の write_text）。同じ改行で足さないと、揃えるたびに空行が増える
        nl = "\r\n" if "\r\n" in foot else "\n"
        foot = foot[:c.end()] + nl + indent + CREDIT + foot[c.end():]
    else:
        k = foot.rfind("</footer>")
        foot = foot[:k] + CREDIT + foot[k:]
    return text[:m.start()] + foot + text[m.end():]


def apply(root):
    """root 以下の全 HTML に揃える。揃えたページ数を返す"""
    n = 0
    for p in sorted(Path(root).rglob("*.html")):
        if ".git" in p.parts or "node_modules" in p.parts:
            continue
        # 改行コードは元のまま（読み書きで変換すると、表記と関係ない全行が差分になる）
        t = p.read_bytes().decode("utf-8", "surrogateescape")
        u = fix(t)
        if u != t:
            p.write_bytes(u.encode("utf-8", "surrogateescape"))
            n += 1
    return n


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("使い方: python scripts/subsidy/footer_credit.py <補助金サイトの作業コピー>")
    print(f"フッターの制作表記: {apply(sys.argv[1])}ページを揃えました")
