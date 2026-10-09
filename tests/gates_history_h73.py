# -*- coding: utf-8 -*-
"""2026-10-09 運用者の決定2つから。

1. 補助金の浮いた枠の書き直しの候補（上位の見出しがある4〜20位の主力の記事）は5本ほどで尽きる。
   尽きた日は「無料の材料で候補を広げる」: 4〜30位・表示15回以上の主力の記事に、上位・AIの出典の記事の
   見出しにあって自記事に無い語を cooccur（Gemini 検索＋見出しの取得。課金なし）で調べ、語が見つかった記事を直す。
2. 旧称の IT導入補助金の記事も主力に数える（同じ制度の名前が変わっただけ）。sites/subsidy.json の main_schemes。
"""
import sys
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_old_name_scheme_counts_as_main():
    import kw_plan as KP
    rule, share, name = KP.main_rule("subsidy")
    check("補助金の主力は AI導入補助金と旧称の IT導入補助金（配分は2つの合計）",
          (bool(rule("ai導入補助金 着金 いつ")), bool(rule("it導入補助金 おすすめ")), bool(rule("ものづくり補助金 個人事業主")),
           share), (True, True, False, 70))
    with mock.patch("sites.load_all", return_value={"z": {"scheme_mix": {"A": 50, "B": 20, "C": 30}}}):
        r, s, _ = KP.main_rule("z")
    check("main_schemes が無い社は今までどおり一番大きい制度だけ", s, 50)


def test_spare_slot_falls_back_to_free_research():
    import auto_rewrite as AR
    import kw_plan as KP
    import noindex
    arts = {"main-a": "ai導入補助金 書類", "main-b": "ai導入補助金 期限", "main-far": "ai導入補助金 遠い",
            "side": "ものづくり補助金 書類", "main-recent": "ai導入補助金 最近"}
    pos = {"main-a": (8.0, 40), "main-b": (25.0, 30), "main-far": (45.0, 99), "side": (6.0, 80), "main-recent": (5.0, 90)}
    asked = []

    def cover(sid, slug, kw, body):
        asked.append(slug)
        return {"missing": ["申請の流れ", "小規模事業者持続化補助金", "対象経費"] if slug == "main-a" else []}

    with mock.patch.object(KP, "site_articles", return_value=arts), \
            mock.patch.object(AR, "page_positions", return_value=pos), \
            mock.patch.object(AR, "is_main", side_effect=lambda slug, site="": slug.startswith("main")), \
            mock.patch.object(noindex, "slugs", return_value=set()), \
            mock.patch("cooccur.cover", side_effect=cover), \
            mock.patch("pathlib.Path.read_text", return_value="---\nkeyword: x\n---\n本文"):
        got = AR.free_spare_items("subsidy", skip={"main-recent"})
    check("無料の調べは4〜30位・主力・最近直していない記事だけに試す", sorted(asked), ["main-a", "main-b"])
    check("主力の記事に、ほかの制度の名前（持続化補助金など）は足させない・無い語が見つかった記事だけを stuck の形で返す",
          [(x["slug"], x["kind"], x["terms"]) for x in got], [("main-a", "stuck", ["申請の流れ", "対象経費"])])

    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    body = src[src.index("def main("):]
    check("補充は浮いた枠（spare）の候補が尽きたときだけ・主力に絞った回だけ",
          'if not items and a.kind == "spare" and a.main_only:' in body
          and body.index("free_spare_items(") > body.index("recently_touched(a.skip_recent)"), True)
    check("無料の調べはラッコを呼ばない（cooccur は Gemini 検索と見出しの取得だけ）",
          "rakko" in (ROOT / "scripts" / "cooccur.py").read_text(encoding="utf-8"), False)


def test_free_research_skips_page_parts():
    import cooccur
    got = cooccur.terms(["投稿ナビゲーション", "ワンポイントアドバイス", "関連記事一覧", "申請の流れ", "AI検索の対策", "広告運用"])
    check("ページの部品の見出しは拾わない（2026-10-09 に「投稿ナビゲーション」を語として渡していた）・主題の語は残す",
          sorted(got), sorted(["申請", "検索", "対策", "広告運用"]))   # 語はひらがなで切れる（cooccur.terms の切り方）
