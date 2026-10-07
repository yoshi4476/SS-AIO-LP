# -*- coding: utf-8 -*-
"""補助金サイト（lp.7senses.co.jp）の見た目とリード導線の点検（2026-10-07）から作った門。

- 足元の SNS アイコンは暗い足元用の白い輪郭のままで、明るい足元では地の色と 1.1:1 で見えなかった
  → 社ごとに色を持つ（AI集客ラボの暗い足元は変えない）
"""
from test_gates import check

DARK_SOCIAL = ('<style>\n/* 外部プロフィール（フッター）。暗い面に置くので、既定は白の輪郭、触れると各サービスの色 */\n'
               '.social-links a { border: 1px solid rgba(255,255,255,.28); color: rgba(255,255,255,.82); }\n</style>')


def _contrast(a, b):
    def lum(h):
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


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
