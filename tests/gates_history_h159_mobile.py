# -*- coding: utf-8 -*-
"""2026-11-12 スマホの画面（390px）で見つかった2つの崩れ:
1. サービスのページの実績の1行が2列に割れた。札の行（.trust-row span）は横並び（inline-flex）なので、
   太字と続きの文をそのまま並べると、別々の列になる
2. 「↑」（先頭へ戻る）のボタンが、問い合わせフォームの入力欄の右端に重なった
"""
import re

from test_gates import check, ROOT


def _split_spans(html):
    """札の行の中で、太字などの部品と地の文がじかに並んでいる札（2列に割れる形）"""
    bad = []
    for row in re.findall(r'<div class="trust-row"[^>]*>(.*?)</div>', html, re.S):
        for inner in re.findall(r"<span[^>]*>(.*?)</span>", row, re.S):
            text_outside = re.sub(r"<(\w+)[^>]*>.*?</\1>", "", inner, flags=re.S).strip()
            if re.search(r"<\w+", inner) and text_outside:
                bad.append(inner[:40])
    return bad


def test_trust_row_text_is_one_block():
    print("\n■ 札の行: 太字まじりの文は、ひとまとまりにする（スマホで2列に割れない）")
    check("悪い例（太字と地の文がじかに並ぶ）を見つける",
          len(_split_spans('<div class="trust-row"><span><strong>累計3,200件以上</strong>の運営実績</span><span>規約違反なし</span></div>')), 1)
    check("良い例（i でひとまとまり・文だけ・部品だけ）は見つけない",
          _split_spans('<div class="trust-row"><span><i><strong>累計</strong>の実績</i></span><span>規約違反なし</span><span><strong>無料</strong></span></div>'), [])
    for f in sorted((ROOT / "site").rglob("*.html")):
        h = f.read_text(encoding="utf-8", errors="replace")
        if 'class="trust-row"' in h:
            check(f"{f.relative_to(ROOT / 'site').as_posix()}: 割れる形の札が無い", _split_spans(h), [])
    css = (ROOT / "site" / "css" / "style.css").read_text(encoding="utf-8")
    check("ひとまとまりにした文（i）は斜めの字にしない", ".trust-row span > i { font-style: normal;" in css, True)


def test_to_top_button_hides_over_forms():
    print("\n■ 「↑」のボタン: フォームが画面にある間は出さない（入力欄に重ならない）")
    js = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    css = (ROOT / "site" / "css" / "style.css").read_text(encoding="utf-8")
    check("フォームが画面に入ったかを見て、印（by-form）を付け外しする",
          ("document.querySelectorAll('form').forEach(function (f) { formWatch.observe(f); })" in js,
           "toTop.classList.toggle('by-form', formsOn.length > 0)" in js), (True, True))
    m = re.search(r"\.to-top\.by-form \{([^}]*)\}", css)
    check("印が付いている間は見えず、押せない", bool(m) and "opacity: 0" in m.group(1) and "pointer-events: none" in m.group(1), True)
    check("出す指定（.show）より後に書いてある（後の指定が勝つ）", css.index(".to-top.by-form") > css.index(".to-top.show"), True)
