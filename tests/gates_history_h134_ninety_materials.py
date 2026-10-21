# -*- coding: utf-8 -*-
"""2026-10-21 運用者「毎回90以上出るように何が原因か追求して直して」「他に90点以上になるために考えられることは」。
CI の採点の記録で、点の上がる直しが機械の警告（100字超の文・FAQ の字数）だけで丸ごと戻され、当社調べは2つの AI だけ、
業種の記事は「その業種の数字が無い」で一次性が80点に止まっていた。材料・検査・直しの流れを直した分を守る。
"""
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_survey_claims_are_short_sentences():
    import own_survey as O
    print("\n■ 当社調べの文: 調べ方と結果の2文に分け、どの文も100字を超えない")
    res = {"ok": True, "date": "2026-10-20", "question": "飲食店 集客 サービスについて教えてください", "slug": "zz",
           "engines": ["Claude", "ChatGPT", "Gemini"],
           "topics": [{"topic": "a", "words": ["業者"], "engines": []}],
           "dims": {"費用の金額（◯円）": [], "期間（◯か月・◯日など）": ["Claude"], "注意点・失敗・リスク": ["Claude", "ChatGPT", "Gemini"]},
           "sources": {"a.go.jp": "public"}}
    sents = [s for c in O.claims(res) for s in re.findall(r"[^。]+。", c)]
    check("文は全部100字以内", (bool(sents), max(map(len, sents)) <= 100), (True, True))


def test_industry_research_reaches_articles():
    import industry_ai_sources as I
    print("\n■ 業種調査: 業種の記事の材料に、調査ページと同じ数字で入る")
    cs, url = I.for_article("飲食店の集客サービスの注意点", "飲食店 集客 サービス")
    h = I.headline("inshoku")
    check("飲食店の記事に飲食店の調査", (url.endswith("/research/inshoku-ai-sources/"), len(cs)), (True, 3))
    check("数字は headline と同じ", all(str(h[k]) in "".join(cs) for k in ("lp", "lc", "ap", "ac", "oa")), True)
    check("業種の無い記事には入れない", I.for_article("AIO外注の失敗", "aio 外注"), ([], ""))


def test_pointing_and_faq_scope_detectors():
    import score_check as S
    print("\n■ 検査: 前を指す言い方を広げ（接続の「そこで」は拾わない）、FAQ の答えから落ちた条件を拾う")
    body = "## 見出し\n本文です。\n\n"
    bad = ["以下は、この不動産会社の支援での実績です。", "4つ目の状況に近く、まず社名を調べます。",
           "両方ともはいなら、自社で続けられます。", "ここを取り違えると失敗します。", "上の図のとおり、4つに分かれます。"]
    good = ["そこで当社は、週に1回数えます。", "ここでいう構造化データとは、タグです。",
            "同じ調べでは、3件の答えのうち1件でした。"]
    check("悪い例を拾う", [bool(S.pointing_sentences(body + s)) for s in bad], [True] * len(bad))
    check("良い例を拾わない", [bool(S.pointing_sentences(body + s)) for s in good], [False] * len(good))
    faq = ("\n\n## よくある質問\n<details><summary>どのくらいで変化が見えますか？</summary>\n<p>{}</p></details>\n")
    main = "## 期間\n当社のAIO運用10件は、3か月以内に順位が上がりました（わずかな上昇も含みます）。\n"
    check("条件の落ちた答えを拾う", bool(S.faq_scope_issues(main + faq.format("10件すべてが3か月以内に上がりました。"))), True)
    check("条件を書いた答えは拾わない",
          S.faq_scope_issues(main + faq.format("当社の10件（わずかな上昇も含む）は3か月以内に上がりました。")), [])


def test_materials_and_repair_pass():
    print("\n■ 直しの材料と流れ: 相場・お客様の声・控え書きを外した出典・機械の指摘だけを直す2回目")
    ql = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("相場とお客様の声を材料に入れる", ("price_ranges.json" in ql, "voices.json" in ql, "industry_ai_sources" in ql),
          (True, True, True))
    check("「運用者の申告」は記事に出す出典から外す",
          all(r"[（(][^）)]*申告[^）)]*[）)]" in (ROOT / "scripts" / f).read_text(encoding="utf-8")
              for f in ("quality_loop.py", "facts.py")), True)
    ar = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    seg = ar[ar.index("def _apply_one"):ar.index('if not ng and kind == "aisplit"')]
    check("警告が増えた直しは、外れた検査だけを名指しして1回直させ、同じ検算を通す",
          ('ng.startswith("警告が増えました") and kind == "quality_loop"' in seg, "guarded(lambda: draft_one(item, fix))" in seg,
           seg.count("ng = check(") >= 3), (True, True, True))
    import json
    pr = json.loads((ROOT / "data" / "price_ranges.json").read_text(encoding="utf-8"))
    check("相場: 記事作成ツールと一括の委託（数十万円より下に書かない決まりは残す）",
          ("article_tool" in [r["id"] for r in pr["ranges"]], pr["outsource_min_yen"] >= 200000), (True, True))
