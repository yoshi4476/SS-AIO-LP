# -*- coding: utf-8 -*-
"""2026-10-19 オリジナルとして認められる記事の門（originality.py・score_check）。

Google は AI が書いたかではなく、独自の経験・一次情報・役に立つか・大量生成でないかで見る。
1. 出どころの無い体験談の決まり文句（全471本のうち164本）を止める。登録した本当の体験の目印を含む文は通す
2. 検索上位の見出しに無い節が2つ以上あるかを見る。データの無い語は「確かめていない」（合格にしない）
"""
import json
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_stock_experience_phrases():
    import originality as O
    print("\n■ 出どころの無い体験談の決まり文句: 見つかるはずの例を拾い、見つかってはいけない例を拾わない")
    bad = ["私たちが中小企業の相談を受ける中でも、「AIは高そう」という声があります。",
           "私たちが申請支援の相談を受ける中でも、よく似た誤解があります。",
           "「一度は自分たちで始めたが、半年で更新が止まった」というケースを何度も聞いてきました。",
           "当社が支援したある医院では、問い合わせが増えました。",
           "ある工務店では、見学会の予約が埋まりました。"]
    good = ["当社は現場で使う会計ソフトの設定から支援します。",
            "当社では、担当者を専任で置けない場合は外部委託を勧めています。理由は、更新が止まりやすいためです。",
            "厚生労働省の資料では、次の3点が求められています。",
            "支援の範囲は、申請書の確認と提出の手順の案内です。"]
    old = O.load_experiences
    try:
        O.load_experiences = lambda site=None: []
        hit_bad = [bool(O.stock_phrases(s)) for s in bad]
        hit_good = [bool(O.stock_phrases(s)) for s in good]
        O.load_experiences = lambda site=None: [{"key": "2026年9月の大阪の歯科医院の相談", "text": "x"}]
        allowed = O.stock_phrases("私たちが相談を受ける中でも、2026年9月の大阪の歯科医院の相談では予約の導線が無かった。")
    finally:
        O.load_experiences = old
    check("悪い例をすべて拾う", hit_bad, [True] * len(bad))
    check("良い例（当社の判断と理由・一次資料・範囲）は拾わない", hit_good, [False] * len(good))
    check("登録した体験の目印を含む文は通す", allowed, [])


def test_info_gain_against_top_headings():
    import originality as O
    import kw_serp
    print("\n■ 検索上位の見出しに無い節を数える（データが無ければ確かめていないと返す）")
    rec = {"headline": {"pages": [
        {"pos": 1, "ours": False, "heads": [["h2", "AIO対策とは"], ["h2", "AIO対策の費用相場"], ["h2", "AIO対策のやり方"]]},
        {"pos": 2, "ours": False, "heads": [["h2", "AIO対策のメリット"], ["h2", "AIO対策の費用"]]}]}}
    old = kw_serp.get
    try:
        kw_serp.get = lambda site, kw, stale_days=None: rec
        g = O.info_gain("ai-lab", "aio対策 費用", ["AIO対策とは", "AIO対策の費用相場", "担当者を置けない会社が半年で止まる理由",
                                                "内製と外部委託を分ける三つの条件"])
        kw_serp.get = lambda site, kw, stale_days=None: None
        none = O.info_gain("ai-lab", "aio対策 費用", ["AIO対策とは"])
    finally:
        kw_serp.get = old
    check("上位に無い節だけを数える（4節のうち2節）", g[:2], (2, 4))
    check("データが無ければ None（合格にしない）", none, None)


def test_wired_into_writer_and_checker():
    print("\n■ 書く AI の案内と点検に入っている")
    sc = (ROOT / "scripts" / "score_check.py").read_text(encoding="utf-8")
    sb = (ROOT / "scripts" / "site_brief.py").read_text(encoding="utf-8")
    check("score_check が決まり文句を止め、上位との差を見る（データが無ければ警告で、合格にしない）",
          ("originality.stock_phrases" in sc, "originality.info_gain" in sc, "確かめていません" in sc), (True, True, True))
    check("site_brief が登録した体験を書く AI に渡す", "originality.brief_lines" in sb, True)
    d = json.loads((ROOT / "data" / "experiences.json").read_text(encoding="utf-8"))
    check("体験の台帳がある（本当にあったことだけを登録する決まりつき）", ("experiences" in d, "作った話を入れない" in d["_readme"]), (True, True))


def test_existing_articles_are_cleaned_weekly():
    print("\n■ 今ある記事の決まり文句は、週次の書き直し（種類 stock）で毎週直す")
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("書き直しの種類 stock（対象・指示・直した後の検算）がある",
          ("def stock_items" in src, '"stock": (' in src, '決まり文句が残っています' in src, '本文が減りすぎました' in src),
          (True, True, True, True))
    check("週次が stock を回す", "--kind stock" in wk, True)
