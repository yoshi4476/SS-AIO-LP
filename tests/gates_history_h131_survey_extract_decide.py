# -*- coding: utf-8 -*-
"""2026-10-20 運用者「全て網羅させて。情報がなくても90以上になるように」。
公開前の採点で、一次性（材料が無い題）・抽出性（前を読まないと分からない書き出し）・決定支援（分かれ道が無い）が
足りずに止まる記事が続いた。
- 当社調べ（own_survey）: 記事の狙う語を複数の AI に聞き、答えに出た語・出なかった語と出典の種類を数えて、
  母数と時期のある自社の実測にする（数えたことだけを書く。解釈は書かない）
- 抽出性・決定支援は score_check が書く段階で止め、直しの指示にも機械の指摘として渡す
- 領域の判定は、移す先の社が担当の外とする語の記事を報告しない（「aio 外注」を外注の社の領域と誤判定した）
"""
import json
import re
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_own_survey_counts_only_what_it_saw():
    import own_survey as O
    print("\n■ 当社調べ: 見出しの論点の語・答えに出た観点・出典の種類を数えた文だけを作る")
    body = ("## 庭木の剪定とは？\n本文\n## 剪定を業者に頼むときの見積もりの見方\n本文\n"
            "## 丸投げで失敗する3つの判断\n本文\n## 2026年10月からの変更\n本文\n## よくある質問\n本文\n")
    tp = O.topics(body)
    words = [w for _, ws in tp for w in ws]
    check("論点の語は名詞の続きだけ（送り仮名の続く語幹「丸投」・数字入り・FAQ は拾わない）",
          ("丸投" in words, any(re.search(r"\d", w) for w in words), "剪定" in words),
          (False, False, True))
    res = {"ok": True, "date": "2026-10-20", "question": "庭木 剪定について教えてください",
           "engines": ["Claude", "ChatGPT", "Gemini"],
           "topics": [{"topic": "a", "words": ["業者"], "engines": []},
                      {"topic": "b", "words": ["見積"], "engines": ["Claude", "ChatGPT", "Gemini"]}],
           "dims": {"費用の金額（◯円）": [], "期間（◯か月・◯日など）": ["Claude"], "注意点・失敗・リスク": ["Claude", "ChatGPT", "Gemini"]},
           "sources": {"a.go.jp": "public", "b.example": "", "c.example": ""}}
    cs = O.claims(res)
    check("時期・AI の数と名前・答えの件数をそろえて書く（聞いていない回数は書かない）",
          all("2026年10月" in c and "3つのAI（Claude・ChatGPT・Gemini）" in c and "3件の答え" in c for c in cs)
          and len(cs) >= 3 and not any("複数回" in c for c in cs), True)
    dim = next((c for c in cs if "費用の金額" in c), "")
    check("0件は「触れた答えは無く」と書き、全部に出た観点は後ろに回す",
          ("費用の金額（◯円）に触れた答えは無く" in dim, dim.find("費用の金額") < dim.find("注意点")), (True, True))
    check("見分けのつかない出典を「同業」と書かない", any("出典に挙がったページは3件で、公的機関・学会・業界団体が1件" in c for c in cs)
          and not any("同業" in c for c in cs), True)
    check("2つ未満の AI しか答えなければ書かない", O.claims({"ok": False}), [])


def test_own_survey_order_and_keep_old():
    import ai_cite_check as AC
    import own_survey as O
    print("\n■ 当社調べ: Claude・ChatGPT は契約の枠（Codex）、Gemini は無料の枠。従量課金の API は使わない（2026-10-20 運用者）")
    sub, paid = AC.subscription_engines, AC.engines_available
    AC.engines_available = lambda site=None: {"ChatGPT": "api", "Gemini": "g", "Perplexity": "p"}
    try:
        AC.subscription_engines = lambda: {"Claude": "c", "ChatGPT": "codex"}
        got = O.engines("ai-lab")
        AC.subscription_engines = lambda: {"Claude": "c"}
        no_codex = O.engines("ai-lab")
    finally:
        AC.subscription_engines, AC.engines_available = sub, paid
    check("聞く AI と経路（ChatGPT は Codex・Perplexity は使わない）", got, {"Claude": "c", "ChatGPT": "codex", "Gemini": "g"})
    check("Codex が無ければ ChatGPT は API で聞かない", no_codex, {"Claude": "c", "Gemini": "g"})
    act = (ROOT / ".github" / "actions" / "own-survey" / "action.yml").read_text(encoding="utf-8")
    check("部品: Codex のログイン情報は途中で落ちても消し、従量課金の鍵を受け取らない",
          ("trap cleanup EXIT" in act, "rm -f ~/.codex/auth.json" in act, "OPENAI_API_KEY" in act or "PERPLEXITY" in act),
          (True, True, False))
    check("部品: 書き戻しは AI を動かさない別の手順（GH_TOKEN は当社調べの手順に渡さない）",
          act.index("GH_TOKEN: ${{ inputs.gh_token }}") > act.index("python scripts/own_survey.py"), True)
    src = (ROOT / "scripts" / "own_survey.py").read_text(encoding="utf-8")
    check("聞けなかった回は前に測った結果を返す", 'if not res.get("ok") and old.get("ok"):\n        return old' in src, True)
    check("お客様の社の文はログに出さない", "if not CP.is_private(site):" in src, True)


def test_score_check_extract_and_decide():
    import score_check as SC
    print("\n■ 機械採点: H2直下の1文が単体で通じるか・分かれ道/やらない判断/今日の一歩があるか")
    bad = ("**庭木の剪定は、木の高さで頼むか決めます。**\n\n## 選び方\n4つのうち、最初に決めるのは予算です。\n## 理由\n"
           "理由は、調べ方が変わったためです。\n## よくある質問\n<details><summary>頼む時期は？</summary><p class=\"faq-a\">その場合は秋です。</p></details>\n")
    good = "## 選び方\n庭木の剪定を頼む業者は、見積もりの内訳で選びます。\n"
    check("抽出の単位（H2直下の1文・FAQ の答え）の悪い例は拾い、良い例は拾わない",
          (SC.extract_issues(bad), SC.extract_issues(good)), (["選び方", "理由", "FAQ: 頼む時期は？"], []))
    check("冒頭の書き出しが前を指していれば拾う", SC.extract_issues("それは秋です。\n\n## a\n庭木は秋に切ります。\n"), ["冒頭"])
    import quality_loop as Q
    check("採点の指示: 段の間の点も付ける・抽出性は基準の単位で判断する（運用者の決定 2026-10-21）",
          ("）の間も付ける" in Q.SCORE_PROMPT, "基準に書いた単位" in Q.SCORE_PROMPT), (True, True))
    yes = ("木が3本以下なら自分で切ってください。高い木の場合は業者に頼むほうが安全です。"
           "毎年切る必要が無い木なら見送ってください。まず木の高さを測ってください。"
           "2つ以上に当てはまるなら、業者に頼むほうを先にしてください。")
    check("分かれ道・やらない判断・今日の一歩・重なったときの優先がそろえば空", SC.decision_issues(yes), [])
    full = yes + "剪定を外に頼む相場は1本あたり1〜3万円です。業者に聞く質問は、処分費が見積もりに入るかです。"
    check("外注の題でも相場の額と業者に聞く質問があれば空", SC.decision_issues(full, "剪定 業者 費用"), [])
    # 2026-10-21: 条件が重なったときの優先も求める（決定支援で85〜90点に止まった指摘）。外注の題では相場と業者に聞く質問も
    check("無ければ4つとも挙げる", len(SC.decision_issues("剪定の方法を説明します。")), 4)
    check("外注の題では相場と業者に聞く質問も挙げる", len(SC.decision_issues("剪定の方法を説明します。", "剪定 業者 費用")), 6)


def test_quality_loop_uses_survey_and_machine_notes():
    import own_survey as O
    import quality_loop as Q
    print("\n■ 品質ループ: 採点の前に当社調べを測り、その文を材料（増えてよい数字）に入れ、機械の指摘を直しの指示に渡す")
    load = O.load
    O.load = lambda site, slug: {"ok": True, "claims": ["当社が2026年10月に3つのAIへ聞いたところ、Xに触れたのは3つ中1つでした"]}
    try:
        allowed, mats = Q.materials("ai-lab", "zz-none")
    finally:
        O.load = load
    check("当社調べの文が一次情報と増えてよい数字に入る", ("当社調べ" in mats["facts"], "3つ中1つ" in allowed), (True, True))
    src = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("採点の前に測る・機械の指摘を直しに渡す",
          ("    survey(slug, budget, base)\n    sc, why = score(slug)" in src, 'sc["machine"] = machine_note(slug)' in src,
           "機械が見つけた抽出性・決定支援の足りない所" in src), (True, True, True))
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    a = wf.index("- name: 当社調べ（直している記事")
    b = wf.index("- name: 公開前の品質ループ（前の回から直している記事を先に）")
    c = wf.index("- name: 当社調べ（この回に書いた記事")
    d = wf.index("- name: 公開前の品質ループ（この回に書いた記事を別工程で採点し、届くまで直す）")
    check("記事の枠: 当社調べは各採点の前（鍵のある機械の手順）", (a < b, c < d), (True, True))
    step = wf[a:b]
    # 2026-10-21: Gemini の残りを台帳で確かめるため合言葉を部品に渡す。ただし AI（claude・codex）が動く手順には置かず、
    # 前後の機械の手順（残りを読む・検索の回数を送る）だけが使う。部品に渡さないと Gemini が外れ、2つの AI だけで聞いていた
    act = (ROOT / ".github" / "actions" / "own-survey" / "action.yml").read_text(encoding="utf-8")
    steps = act.split("\n    - shell: bash")[1:]
    ai = [x for x in steps if "own_survey.py" in x]
    check("当社調べの手順（AI が動く）に全権の合言葉を置かない・前後の機械の手順だけが持つ",
          (len(ai), any("HUB_SECRET" in x for x in ai), sum("HUB_SECRET" in x for x in steps),
           "GEMINI_USAGE_FILE" in ai[0] if ai else False), (1, False, 2, True))
    pl = (ROOT / ".github" / "workflows" / "pipeline.yml").read_text(encoding="utf-8")
    check("救済: 当社調べは品質ループの前",
          pl.index("- name: 当社調べ（直している記事・救済") < pl.index("- name: 公開前の品質ループ（別工程の3観点の採点と直し）"), True)


def test_territory_skips_keywords_the_invader_refuses():
    import cannibal_check as C
    import kw_fit
    print("\n■ 領域の判定: 移す先の社が担当の外とする語の記事は、本文に移す先の語が多くても報告しない")
    judge = kw_fit.judge_new
    kw_fit.judge_new = lambda kw, site: (2, "担当の外の文脈") if "zz" in kw else (0, "")
    try:
        r = (C._invader_refuses("title: t\nkeyword: zz 外注\n", "client-zz"),
             C._invader_refuses("title: t\nkeyword: 開発 外注\n", "client-zz"),
             C._invader_refuses("title: t\n", "client-zz"))
    finally:
        kw_fit.judge_new = judge
    check("担当の外なら報告しない・担当なら報告する・狙う語が無ければ従来どおり", r, (True, False, False))
