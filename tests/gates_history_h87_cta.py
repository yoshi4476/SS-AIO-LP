# -*- coding: utf-8 -*-
"""2026-10-10・10-11 と2日続けて、その日に書いた補助金の記事が相談への案内（CTA）1か所のまま先方へ届き、門
（CTAが2箇所未満の記事）で止まった。CTA を足す道具（cta_fill.py）は週次でしか動いていなかった。別のリポジトリへ
届ける社は、記事の枠の後の工程で直しても届いた記事に反映されないので、公開の流れ（publish_flow）の配信の前で足す
"""
from test_gates import check, ROOT


def test_publish_flow_fills_cta_before_delivering():
    print("\n■ 公開の流れ: 配信の前に、CTA が2か所に満たない記事に足す")
    src = (ROOT / "scripts" / "publish_flow.py").read_text(encoding="utf-8")
    fill = src.find('"scripts/cta_fill.py", "--write"')
    deliver = src.find("# 3. 配信（サイト種別ごとの出口）")
    check("配信の前で cta_fill.py --write を動かす（失敗しても配信は止めない）",
          (fill >= 0, 0 <= fill < deliver, "check=False" in src[fill:fill + 80]), (True, True, True))
