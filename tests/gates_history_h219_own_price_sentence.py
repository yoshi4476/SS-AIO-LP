# -*- coding: utf-8 -*-
"""2026-11-26 AI集客ラボの費用比較の記事が、公開前の機械採点「相場: 当社の価格を書かない」で隔離された。
当たった金額は「記事作成ツールで月◯万円前後」という市場の相場の文にあり、「当社」は次の文（支援の実績）にあった。
前後40字の範囲が文の切れ目をまたいでいた。別のものの値段の文で、その文に当社の語が無ければ当社の価格としない。
当社の価格を書いた文は、これまでどおり拾う。"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_own_price_does_not_cross_sentences():
    from price_claims import OWN_PRICE_MAN as P, own_price
    print("\n■ 相場: 当社の価格の判定が、別のものの値段の文から次の文の「当社」へまたがない")
    # 落ちたときに当社の本当の額が CI の記録に出ないよう、拾った件数だけを比べる
    check("ツールの相場の文の後ろに当社の実績の文があっても拾わない",
          len(own_price(f"相場は記事作成ツールで月{P - 1}〜{P}万円前後、外部委託で月99万円以上です。当社が支援した7件のうち1件でした。")), 0)
    check("当社の価格を書いた文は拾う", bool(own_price(f"当社のAIO対策は月{P}万円です。")), True)
    check("当社の語が前の文でも、金額の文がほかのものの値段でなければ拾う",
          bool(own_price(f"当社の料金です。月{P}万円で始められます。")), True)
    check("ツールの語があっても、同じ文に当社の語があれば拾う",
          bool(own_price(f"当社は記事作成ツールと同じ月{P}万円で支援します。")), True)
