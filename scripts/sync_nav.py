# -*- coding: utf-8 -*-
"""サイト全体のナビゲーションと、フッターの制作表記を1つに揃える。

記事とカテゴリ一覧は build.py がナビを差し込むが、トップ・運営者情報・LPなどの
固定ページはHTMLに直書きされている。そのため両者が食い違っていた——
固定ページには「実装ラボ」があり「業種から探す」が無い、生成ページはその逆。
訪問者は同じサイトの中でメニューが変わるのを見ることになる。

build.py の NAV_DEFAULT / FOOTER_NAV_DEFAULT（= site.config.json があればそちら）を
唯一の正とし、全ページの `<nav class="global-nav">` と
`<nav aria-label="フッターナビゲーション">` の中身を書き換える。

フッターの制作・顧問の表記（site.config.json の footer_credit）も同じ考えで、
`<div class="footer-credit">` を全ページで同じにする。無いページには著作権表示の直後に足す。
フッターを作る場所が雛形・生成・手書きと複数あり、1か所ずつ足すと漏れるため。

  python scripts/sync_nav.py            # ずれているページ
  python scripts/sync_nav.py --apply    # 揃える

何度実行しても同じ結果。
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
SITE = ROOT / "site"
G_RX = re.compile(r'(<nav class="global-nav"[^>]*>)(.*?)(</nav>)', re.S)
F_RX = re.compile(r'(<nav aria-label="フッターナビゲーション"[^>]*>)(.*?)(</nav>)', re.S)
C_RX = re.compile(r'[ \t]*<div class="footer-credit">.*?</div>\n?', re.S)
COPY_RX = re.compile(r'<div class="copyright">.*?</div>', re.S)
FOOTER = '<footer class="site-footer">'


def wanted():
    import build
    return (build._nav("nav", build.NAV_DEFAULT),
            build._nav("footer_nav", build.FOOTER_NAV_DEFAULT))


def credit():
    import build
    return build._footer_credit()


def fix_credit(text, cred):
    """site-footer の中の制作表記を cred に揃える（cred が空なら外す）"""
    i = text.find(FOOTER)
    j = text.find("</footer>", i) if i >= 0 else -1
    if j < 0:
        return text
    foot = text[i:j]
    body = C_RX.sub("", foot)
    if cred:
        m = COPY_RX.search(body)
        if m:
            body = body[:m.end()] + "\n    " + cred + body[m.end():]
        else:
            k = body.rfind("</div>")
            body = body[:k] + cred + "\n" + body[k:] if k >= 0 else body + cred + "\n"
    return text[:i] + body + text[j:]


def fix(text, gnav, fnav, cred=None):
    out = G_RX.sub(lambda m: m.group(1) + "\n" + gnav + "\n    " + m.group(3), text, count=1)
    out = F_RX.sub(lambda m: m.group(1) + "\n" + fnav + "\n    " + m.group(3), out, count=1)
    return fix_credit(out, cred) if cred is not None else out


def apply_credit(site=SITE):
    """制作表記だけを全ページに揃える（build.py が出力の最後に呼ぶ）。揃えたページ数を返す"""
    cred = credit()
    n = 0
    for p in sorted(Path(site).rglob("*.html")):
        t = p.read_text(encoding="utf-8", errors="surrogateescape")
        if FOOTER not in t:
            continue
        u = fix_credit(t, cred)
        if u != t:
            p.write_text(u, encoding="utf-8", errors="surrogateescape", newline="\n")
            n += 1
    return n


def run(write):
    gnav, fnav = wanted()
    cred = credit()
    changed = []
    for p in sorted(SITE.rglob("*.html")):
        t = p.read_text(encoding="utf-8", errors="surrogateescape")
        if not (G_RX.search(t) or F_RX.search(t) or FOOTER in t):
            continue
        u = fix(t, gnav, fnav, cred)
        if u != t:
            changed.append(p)
            if write:
                p.write_text(u, encoding="utf-8", errors="surrogateescape", newline="\n")
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    changed = run(a.apply)
    print(f"{'揃えた' if a.apply else 'ずれている'}: {len(changed)}ページ")
    for p in changed[:8]:
        print("  ", p.relative_to(ROOT).as_posix())
    if len(changed) > 8:
        print(f"   …ほか{len(changed) - 8}")
    if not a.apply and changed:
        print("  --apply で揃えます")
    return 0


if __name__ == "__main__":
    sys.exit(main())
