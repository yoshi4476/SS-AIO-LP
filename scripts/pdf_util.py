# -*- coding: utf-8 -*-
"""PDF生成の共通処理

1ページ=1セクションを保つため、A4に収まらないページを生成時に検出して警告する。
閉じタグの抜けや文量超過は、PDFを目で見るまで気づきにくいため機械で検査する。
"""
A4_PX = 297 / 25.4 * 96  # A4の高さ(297mm)をpxへ換算 ≒ 1122.5
TOL = 4  # 端数の誤差を許容する

# 隣り合うセクションが2つとも短いとき、1枚に詰め直す。
# サイト立ち上げ期はデータが少なく、1セクション=1ページだと空白ばかりのページになるため。
# 実測して「収まる場合だけ」結合するので、途中で切れることはない。
_COMPACT_JS = """(gap) => {
  const sheets = [...document.querySelectorAll('.sheet')];
  const used = el => {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    const top = r.top + parseFloat(cs.paddingTop);
    let bottom = top;
    el.querySelectorAll('*').forEach(c => {
      const cr = c.getBoundingClientRect();
      if (cr.height > 0 && cr.bottom > bottom) bottom = cr.bottom;
    });
    return { h: bottom - top,
             cap: r.height - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) };
  };
  // 表紙・裏表紙（見出しを持たないページ）は対象外
  const body = sheets.filter(s => !s.classList.contains('cover-page') && s.querySelector('.sec'));
  let merged = 0;
  for (let i = 0; i < body.length - 1; i++) {
    const a = body[i], b = body[i + 1];
    if (!a.isConnected || !b.isConnected) continue;
    const ua = used(a), ub = used(b);
    if (ua.h + ub.h + gap > ua.cap) continue;
    const spacer = document.createElement('div');
    spacer.style.height = gap + 'px';
    a.appendChild(spacer);
    while (b.firstChild) a.appendChild(b.firstChild);
    b.remove();
    merged++;
    i++;  // 結合済みのbは次の起点にしない（3枚以上の連結は次の走査に任せる）
  }
  return merged;
}"""


def compact_pages(page, gap=26):
    """空白の多いページを、収まる範囲で隣と結合する（結合した枚数を返す）"""
    total = 0
    try:
        for _ in range(3):  # 結合の結果さらに詰められる場合があるため繰り返す
            n = page.evaluate(_COMPACT_JS, gap)
            if not n:
                break
            total += n
    except Exception as e:
        print(f"ページの詰め直しをスキップ: {e}")
        return 0
    if total:
        print(f"空白の多いページを{total}枚分、隣のセクションと結合しました")
    return total


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
