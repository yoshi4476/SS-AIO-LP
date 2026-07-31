# -*- coding: utf-8 -*-
"""PDF生成の共通処理

1ページ=1セクションを保つため、A4に収まらないページを生成時に検出して警告する。
閉じタグの抜けや文量超過は、PDFを目で見るまで気づきにくいため機械で検査する。
"""
A4_PX = 297 / 25.4 * 96  # A4の高さ(297mm)をpxへ換算 ≒ 1122.5
TOL = 4  # 端数の誤差を許容する


def check_overflow(page, label="レポート"):
    """開いているページ内の .sheet を実測し、A4を超えるものを報告する"""
    try:
        heights = page.eval_on_selector_all(
            ".sheet", "els => els.map(e => e.getBoundingClientRect().height)")
        titles = page.eval_on_selector_all(
            ".sheet",
            "els => els.map(e => (e.querySelector('h2')||{}).textContent || '(表紙/裏表紙)')")
    except Exception as e:
        print(f"ページ高さの検査をスキップ: {e}")
        return []

    over = [(i + 1, t.strip()[:26], h)
            for i, (t, h) in enumerate(zip(titles, heights)) if h > A4_PX + TOL]
    if not over:
        print(f"ページ検査: 全{len(heights)}ページ、すべてA4に収まっています")
        return []

    print(f"WARN: {label}に{len(over)}件のページ溢れがあります（1ページに収まらず次ページへ流れます）")
    for i, t, h in over:
        print(f"  ページ{i:2d} {t:28s} {h:.0f}px（+{h - A4_PX:.0f}px 超過）")
    print("  → 該当セクションの文量を減らすか、2ページに分割してください")
    return over
