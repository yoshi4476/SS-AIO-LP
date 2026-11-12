# -*- coding: utf-8 -*-
"""2026-11-12 週次の「主要クエリの推移」が「経理代行サービス（16位→圏外）… 記事が無い → その語に答える記事を書く」と出した。
記事（keyword: 経理代行サービス）は公開中で、検索結果に出ていなかっただけ（90日の表示10回）。
表示が無いことを「記事が無い」と取り違えると、同じ語の記事をもう1本書かせて食い合いを作る"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_no_impressions_is_not_no_article():
    import key_queries as KQ
    print("\n■ 主要クエリ: 表示が無いことを「記事が無い」と取り違えない")
    titles = {"keiri-daiko-service": "経理代行サービスの失敗は業務範囲の認識違い｜できること6つ"}
    c, how = KQ.cause("経理代行サービス", KQ.OUT, [], titles, slug="keiri-daiko-service")
    check("記事があり表示が無い語は「表示が無い（記事はある）」で、新しい記事を書かせない", (c, "記事を書く" in how), ("表示が無い（記事はある）", False))
    c, _ = KQ.cause("経理代行サービス", KQ.OUT, [], titles, slug="")
    check("記事が本当に無い語は、これまでどおり「記事が無い」", c, "記事が無い")
    c, _ = KQ.cause("経理代行サービス", KQ.OUT, [], titles, slug="消えた記事")
    check("宣言の記事が今は無い（統合・取り下げ）なら「記事が無い」", c, "記事が無い")
    src = (ROOT / "scripts" / "key_queries.py").read_text(encoding="utf-8")
    check("推移の判定に、宣言した記事を渡す", "cause(q, pos, rows_pq, titles, slug=slug)" in src, True)
