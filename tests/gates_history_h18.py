# -*- coding: utf-8 -*-
"""説明文（meta description）を100〜150字にそろえる門（2026-10-05）。

Bing Webmaster Tools が AI集客ラボの54ページを「メタ説明が短すぎる」と指摘した。手元の集計では
noindex を除く231ページのうち98ページが100字未満（記事・業種ハブ・比較表・固定ページ）。
門の下限が60字で、一覧の外枠は120字で切ったうえ90字未満にだけ運営者の一文を足していた。
記事には本文にある文だけを足し（新しい内容・数字を作らない）、一覧はページの中身（本数・業種・問い）から作る。
本物の記事は書き換えない（一時ファイルだけ）。
"""
import io
import re
import sys
import tempfile
from pathlib import Path

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

BODY = ("**クリニックの電話予約は、5項目を同じ順番で聞き取る型を決めることです。**"
        "型を決めておけば、担当者が変わっても対応の質が揃います。"
        "本記事では、電話予約の型と自動応答の使い方を解説します。\n\n"
        "<div class=\"target-reader\">この記事は院長向けです。</div>\n\n"
        "## 電話予約の基本の流れは？\n\n"
        "**電話予約の基本は、受電・聞き取り・空き枠提示・復唱確定の4ステップに固定することです。**"
        "この順番さえ守れば差は出ません。\n\n"
        "## 聞き取る項目は？\n\n"
        "**聞く項目は初診再診・症状・希望日時・氏名・連絡先の5つです。**\n")
DESC = "クリニックの電話予約のやり方は、聞き取り5項目を型にして初診・再診・キャンセル対応まで先に決めておくことです。"
NUM = re.compile(r"\d[\d,，.．]*")


def test_article_description_is_filled_only_from_its_own_sentences():
    print("\n■ 短い説明文には、記事の冒頭・H2の1文結論にある文だけを足す（100〜150字・文の途中で切らない・数字を増やさない）")
    import desc_fill as DF
    new, added, why = DF.fill(DESC, BODY)
    plain = DF.plain(BODY)
    check("短い説明文は足せる", (why, len(DESC) < 100), ("", True))
    check("足した文はどれも本文にある文そのもの", all(s in plain for _, s in added), True)
    check("元の説明文はそのまま先頭に残る", new.startswith(DESC), True)
    check("足した文以外の文字は入らない", new[len(DESC):], "".join(s for _, s in added))
    check("100〜150字に収まる", 100 <= len(new) <= 150, True)
    check("文の途中で切らない（句点で終わる）", new.endswith(("。", "！", "？")), True)
    check("本文に無い数字は1つも無い",
          [n for n in NUM.findall(new) if n not in set(NUM.findall(DESC)) | set(NUM.findall(plain))], [])
    check("前の文を受ける文（「この順番さえ…」）・記事の案内文（「本記事では…解説します」）は足さない",
          any(s.startswith(("この", "本記事")) for _, s in added), False)
    check("説明文と同じ主張の言い直し（冒頭の断言）は足さない",
          any("型を決めることです" in s for _, s in added), False)
    check("検算（verify）を通る", DF.verify(DESC, new, BODY, added), "")
    check("本文に無い文を足した説明文は検算で止まる",
          DF.verify(DESC, DESC + "初診の患者は9割が電話で予約します。", BODY, [("冒頭", "初診の患者は9割が電話で予約します。")]) != "", True)
    check("100字以上の説明文は触らない", DF.fill("あ" * 99 + "。", BODY)[1], [])
    check("文の途中で終わる説明文には足さない", DF.fill("クリニックの電話予約のやり方", BODY)[2] != "", True)

    # 原稿の書き換えは description の1行だけ。本文は1文字も変わらず、YAML として読み戻せる
    text = f"---\ntitle: t\ndescription: {DESC}\nslug: s\n---\n{BODY}"
    after = DF.set_description(text, new)
    check("書き換えは description の行だけ", DF.split(after)[3], DF.split(text)[3])
    check("YAML として読み戻せる", yaml.safe_load(DF.split(after)[1])["description"], new)
    check("「: 」を含む説明文は引用符で包んで読み戻せる",
          yaml.safe_load(DF.split(DF.set_description(text, "要点: 3つです。"))[1])["description"], "要点: 3つです。")


def test_published_articles_have_100_to_160_char_descriptions():
    print("\n■ 公開記事（score 90以上）の説明文は100〜160字（原稿・HTML・構造化データ・og:description が同じ値）")
    import desc_fill as DF
    bad = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        m = re.match(r"^---\s*\n(.*?)\n---", io.open(p, encoding="utf-8-sig").read(), re.S)
        meta = yaml.safe_load(m.group(1)) if m else {}
        if (meta.get("score") or 0) < 90:
            continue
        n = len(str(meta.get("description") or ""))
        if not DF.MIN <= n <= DF.GATE_MAX:
            bad.append(f"{p.stem}={n}字")
    check("100字未満・160字超の公開記事は無い", bad[:5], [])
    tpl = (ROOT / "templates" / "article.html").read_text(encoding="utf-8")
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("記事の meta・og:description（雛形）と構造化データ（build）は原稿の description をそのまま使う",
          (tpl.count("{{DESCRIPTION}}") >= 2, src.count('"description": meta["description"]') >= 1), (True, True))


def test_list_pages_get_100_chars_from_their_contents():
    print("\n■ 一覧・ハブの説明文は、ページの中身（本数・業種・問い）から作った文で100字以上にする")
    import desc_fill as DF
    import build as B
    base = "AIO・LLMO運用の記事にある比較表20表を1か所に集めました。"
    got = DF.extend(base, ["表は15本の記事に載せたものそのままで、表ごとに出典の記事へ進めます。",
                           DF.named("主な表は", ["費用の比較", "依頼先タイプ別の違い", "契約前に各社へ聞く質問"], "です。")])
    check("中身の文を足して100〜150字", 100 <= len(got) <= 150, True)
    check("同じ型の言い換え候補は1つしか使わない", got.count("主な表は"), 1)
    check("150字を超える文は足さない", len(DF.extend(base, ["あ" * 120 + "。"])) <= 150, True)
    check("長すぎる説明文は句点で切る（文の途中で切らない）",
          DF.clip("一文目です。" + "二" * 160 + "。"), "一文目です。")
    sh = B.page_shell("テストの比較表", base, ["表は15本の記事に載せたものそのままで、表ごとに出典の記事へ進めます。",
                                              "主な表は「依頼先タイプ別の違い」「契約前に各社へ聞く6つの質問」です。"])
    d = __import__("html").unescape(sh["desc"])
    check("外枠（page_shell）の説明文は100〜150字", 100 <= len(d) <= 150, True)
    check("外枠は中身の文で届けば運営者の一文を足さない", "出典の記事へ進めます" in d and "現場で確かめた" not in d, True)
    d = __import__("html").unescape(B.page_shell("用語集", "AI集客ラボの記事で定義した用語143語の意味を、1ページにまとめた用語集です。")["desc"])
    check("中身の文が無いときだけ運営者の一文を最後に足す", d.endswith("確かめた内容をもとにまとめています。"), True)
    lead = ("歯科医院は、商圏が狭いうえに競合が密集します。患者は地域名で医院を探し、費用や治療法を調べてから受診先を決めます。"
            "加えて医療広告ガイドラインの制約があり、書ける内容にも限りがあります。")
    check("120字で切って90字台に落としていた業種ハブの説明が100字以上になる",
          len(__import__("html").unescape(B.page_shell("歯科医院の集客", lead)["desc"])) >= 100, True)
    src = (ROOT / "scripts" / "subsidy" / "pages.py").read_text(encoding="utf-8")
    check("補助金サイトの一覧（pages.py）も同じ足し方を使う", "DF.extend(" in src and "more=" in src, True)


def test_new_articles_and_gates_use_100_char_floor():
    print("\n■ 新しく書く記事の説明文の下限は100字（score_check・build・seo_audit・auto_rewrite・執筆の指示）")
    import desc_fill as DF
    import score_check as SC
    import seo_audit as SA
    import build as B
    check("seo_audit の「説明文が短すぎる」は100字未満", (SA.DESC_MIN, SA.DESC_MAX), (100, 160))
    w = B.quality_checks([{"slug": "x", "title": "クリニックの電話予約のやり方を解説", "description": "あ" * 99}])
    check("build の機械ゲートは99字を止める", any("メタ記述字数NG" in x for x in w), True)
    w = B.quality_checks([{"slug": "x", "title": "クリニックの電話予約のやり方を解説", "description": "あ" * 100}])
    check("build の機械ゲートは100字を通す", any("メタ記述字数NG" in x for x in w), False)
    ar = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("auto_rewrite --kind desc の検算は100〜160字", "100 <= len(d) <= 160" in ar and "60 <= len(d)" not in ar, True)
    check("auto_rewrite の指示文に60〜160字が残っていない", "60〜160字" in ar, False)
    pr = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("執筆の指示に説明文100〜150字の決まりがある", "description は100〜150字" in pr, True)

    fm = ("---\ntitle: クリニックの電話予約のやり方｜5項目の型\ndescription: {d}\nslug: {s}\n"
          "keyword: クリニック 電話予約\ncategory: ai-marketing\ndate: 2026-10-05\nfaq: []\n---\n" + BODY)
    old = SC.ROOT
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "articles").mkdir()
        try:
            SC.ROOT = Path(tmp)
            res = {}
            for slug, d in (("short", "あ" * 99), ("ok", "あ" * 120)):
                (Path(tmp) / "articles" / f"{slug}.md").write_text(fm.format(d=d, s=slug), encoding="utf-8")
                item = [c for c in SC.run(slug) if c[0].startswith("説明文")]
                res[slug] = item[0][1] if item else None
        finally:
            SC.ROOT = old
    check("score_check は99字の説明文を落とし、120字を通す", res, {"short": False, "ok": True})
    check("下限・目標・上限の定数", (DF.MIN, DF.MAX, DF.GATE_MAX), (100, 150, 160))
