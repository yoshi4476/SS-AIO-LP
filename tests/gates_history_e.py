# -*- coding: utf-8 -*-
"""過去の誤りの棚卸しから作った門（相場・価格の表記）。

AIO・SEO・LLMO対策の相場は data/price_ranges.json だけを正とする。
記事ごとに別の相場（外注で月3万円台から、月10万〜30万円 など）を書くと、同じサイトの中で
数字が食い違い、当社の見立てとも矛盾する。当社の価格（例: 月99万円。本当の額は非公開の sales/prices.json）も書かない。

検出器は「悪い例を拾う」「良い例を拾わない」を先に確かめてから記事に当てる（CLAUDE.md 0.1）。
"""
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
from price_claims import CATS, OWN_PRICE_MAN, low_claims, own_price  # noqa: E402  判定は1か所（score_check も使う）


def ai_lab_articles():
    for p in sorted((ROOT / "articles").glob("*.md")):
        t = p.read_text(encoding="utf-8")
        m = re.search(r"^category:\s*(\S+)", t, re.M)
        if m and m.group(1) in CATS:
            yield p, t


def test_hist_price_ranges_consistent():
    print("\n■ 相場の表記が data/price_ranges.json と食い違わない")
    bad = ["AIO対策の外部委託は月3万円台から始められます。",
           "SEOの外注費用は月10万〜30万円が目安です。",
           "| 部分外注（記事のみ） | 3万〜8万円 |",
           "AIO対策を代行会社に任せると数千円〜数万円です。",
           "SEOコンサルは月額十数万円が中心です。",
           "SEOは自社対応中心で月1〜5万円、外注では月10〜30万円が目安です。",
           "| フルサポート型 | 月15万〜30万円 | MEO・SEO・AI検索を一括で任せたい医院 |",
           "  - q: SEOコンサルの費用相場はいくらですか？\n    a: 月額5万〜20万円が目安です。",
           "AIO対策の相場は月5万円です。",
           "ツールより外注の相場は月5万円です。",
           "外注と内製の相場は月5万円です。",
           "社内に担当がいない場合の相場は月5万円です。",
           "無料の診断もありますが、相場は月5万円です。",
           "ツールを使わない場合、相場は月5万円です。",
           "| 外注・内製の相場 | 月5万円 |"]
    good = ["内製＋有料ツールは月数万〜数十万円です。",
            "内製＋有料ツールの相場は月数万〜数十万円です（2026年10月時点の相場の見立て）。",
            "AIO対策は、内製＋有料ツールなら月数万〜数十万円、外部委託・部分支援は月数十万円〜です。",
            "| 内製＋有料ツール併用 | 数万〜数十万円＋担当者の人件費 |",
            "DolphinX は月額99ドルのツールで、AI引用を自動で記録します。",
            "無料の次の一歩は、月25ドルから月3万円台の入門プランです。",
            "MEO対策の代行（G-ran）は月3万円です。",
            "SEOの外部委託は月数十万〜数百万円が目安です。",
            "SEOの競合は宅地建物取引業者13万2,291業者です。",
            "SEOを自社対応中心で進めると月1〜5万円です。",
            "月30,000円は6か月契約時の価格で、12か月契約なら月27,000円に下がります。",
            "SEO記事の外注は、3,000字の記事であれば1,500〜6,000円です。",
            # 2026-11-09 に門が拾った、相場表どおりの書き方（記事作成ツール・内製の額）
            "記事作成ツールの相場は月4〜5万円前後です。",
            "予算の目安は、体制が無いなら月数万〜数十万円の内製＋有料ツール、体制と予算があるなら月20万円以上の一括委託です。",
            "月数万円台なら内製＋ツールで、担当者の時間を確保してください。"]
    for s in bad:
        check(f"相場: 悪い例を拾う「{s[:24]}」", bool(low_claims("## AIO対策の費用\n" + s)), True)
    for s in good:
        check(f"相場: 良い例を拾わない「{s[:24]}」", low_claims("## AIO対策の費用\n" + s), [])
    # 額は書かずに組み立てる（public のリポジトリに当社の料金を書かない。2026-10-20）
    check("当社の価格: 悪い例を拾う", bool(own_price(f"当社のAIO対策は月{OWN_PRICE_MAN}万円です。")), True)
    check("当社の価格: 良い例を拾わない", own_price("当社の見立てでは月数十万円〜です。厚労省の統計では120万円です。"), [])

    low, own = [], []
    for p, t in ai_lab_articles():
        low += [f"{p.stem}:{i} {s}" for i, s in low_claims(t)]
        own += [f"{p.stem}:{i} {s}" for i, s in own_price(t)]
    for x in low + own:
        print("    " + x)
    check("AI集客ラボの記事: 外部委託の月額を数十万円より下に書かない", low, [])
    check("AI集客ラボの記事: 当社の価格を書かない", own, [])
