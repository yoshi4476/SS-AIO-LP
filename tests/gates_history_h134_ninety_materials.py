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
           "両方ともはいなら、自社で続けられます。", "ここを取り違えると失敗します。"]
    # 「上の表で2つ以上に当てはまるときは…」は優先の決まりが求める文なので拾わない（2026-10-21 両方の検査が食い違った）
    good = ["そこで当社は、週に1回数えます。", "ここでいう構造化データとは、タグです。",
            "同じ調べでは、3件の答えのうち1件でした。", "上の表で自社の状態が2つ以上に当てはまるときは、書類の回収を先にしてください。"]
    check("悪い例を拾う", [bool(S.pointing_sentences(body + s)) for s in bad], [True] * len(bad))
    check("良い例を拾わない", [bool(S.pointing_sentences(body + s)) for s in good], [False] * len(good))
    faq = ("\n\n## よくある質問\n<details><summary>どのくらいで変化が見えますか？</summary>\n<p>{}</p></details>\n")
    main = "## 期間\n当社のAIO運用10件は、3か月以内に順位が上がりました（わずかな上昇も含みます）。\n"
    check("条件の落ちた答えを拾う", bool(S.faq_scope_issues(main + faq.format("10件すべてが3か月以内に上がりました。"))), True)
    sc = (ROOT / "scripts" / "score_check.py").read_text(encoding="utf-8")
    check("FAQ の条件の検査は警告（FAIL にすると点の上がる直しを捨てる。2026-10-21 の CI で89点の記事の直しを捨てた）",
          'not scope, "、".join(scope[:2]), warn=True)' in sc, True)
    check("条件を書いた答えは拾わない",
          S.faq_scope_issues(main + faq.format("当社の10件（わずかな上昇も含む）は3か月以内に上がりました。")), [])


def test_pass_85_target_90_pdca():
    import rubric as R
    print("\n■ 公開の下限85・目標90（運用者 2026-10-21）。85〜89点は公開しつつ直し続ける（PDCA）")
    # 2026-10-21 運用者「かなりではなく少し厳しいに」「緩和しても AI から選ばれるように」: 一次性だけ80、ほかは75
    check("下限と目標・観点ごとの足切り", (R.PASS_TOTAL, R.TARGET, R.PASS_EACH, R.floor("originality")), (85, 90, 75, 80))
    check("85点で合格・84点で不合格・一次性79は不合格・抽出性75は合格・74は不合格",
          [R.judge({"originality": a, "extractability": b, "decision": c})["ok"]
           for a, b, c in ((85, 85, 85), (84, 84, 84), (79, 90, 90), (90, 75, 90), (90, 74, 95))],
          [True, False, False, True, False])
    ql = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("公開前の直しは90点未満なら回数の残りで続ける・85〜89点の合格は直す対象に残す",
          ('while (not sc["ok"] or sc["total"] < R.TARGET)' in ql,
           'low = r["state"] == "passed" and (r.get("total") or 0) < R.TARGET' in ql), (True, True))
    # 点数の判定に下限以外の数字を直接書かない（90 を40か所近くに直接書いていて、1か所を変えても漏れた）
    pat = re.compile(r"(?:score|total|_score\(p\)|\bsc\b)[^\n]{0,30}?(?:<|>=)\s*(\d{2})\b(?!\s*[日件本字%])")
    odd = []
    for p in (ROOT / "scripts").glob("*.py"):
        if p.name in ("rubric.py",):
            continue
        for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if ln.lstrip().startswith("#"):
                continue
            for m in pat.finditer(ln):
                if m.group(1) == "90":
                    odd.append(f"{p.name}:{i}")
    check("点数の判定に 90 を直接書いていない（下限は rubric.PASS_TOTAL）", odd, [])
    # 定数の形（QUALITY_GATE = 90）も見る。比べる式だけを探していたので build.py の定数を見落とし、85〜89点で合格した記事が
    # サイトに出ず404になった（2026-10-21）
    const = re.compile(r"^\s*[A-Z_]*(?:GATE|PASS|MIN_SCORE|PUBLISH)[A-Z_]*\s*=\s*9\d\b")
    left = [f"{p.name}:{i}" for p in (ROOT / "scripts").glob("*.py") if p.name != "rubric.py"
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if const.match(ln)]
    check("公開の下限を定数で直接書いていない（QUALITY_GATE・PUBLISH_SCORE など）", left, [])
    # 公開している説明が基準とずれない（FAQ のページは build では作られず faq_page.py を手で動かすので、変え忘れた）
    shown_pages = {rel: (ROOT / "site" / rel).read_text(encoding="utf-8")
                   for rel in ("faq/index.html", "editorial-policy/index.html")}
    check("公開しているページの基準の表示が下限と同じ（faq_page.py → build.py で作り直す）",
          (f"総合{R.PASS_TOTAL}点以上" in shown_pages["faq/index.html"], "総合90点以上" in shown_pages["faq/index.html"],
           f"{R.PASS_TOTAL}点未満は非公開" in shown_pages["editorial-policy/index.html"]), (True, False, True))
    php = (ROOT / "automation" / "wordpress" / "ss-quality-gate.php").read_text(encoding="utf-8")
    check("WordPress の門も85", "const SSQG_MIN_SCORE  = 85;" in php, True)


def test_pre_improve_and_unused_materials():
    import quality_loop as Q
    print("\n■ 最初の採点の前に、機械の指摘と使っていない材料で1回直す・使っていない材料があれば材料待ちで止めない（2026-10-21）")
    facts = "\n".join([
        "- 当社は2026年10月に、3つのAI（Claude・ChatGPT・Gemini）へ「庭木」と同じ質問をしました。3件の答えのうち0件でした。（出典: 当社調べ）",
        "- お客様の声「助かりました」（庭の会社・2026-09・同じ業種。声は言い換えずに…）",
        "- お客様の声「別の業種です」（製造業・2026-09。声は…）",
        "- 外部委託（部分支援）の相場は月数十万円〜（出典: 2026年10月時点の相場の見立て。…）"])
    old = Q.materials, Q.read, Q._split, Q.site_of
    Q.materials = lambda site, slug: ("", {"facts": facts, "experiences": "", "research": ""})
    Q.site_of = lambda slug: "ai-lab"
    try:
        Q.read = lambda slug: "body"
        Q._split = lambda t: ("", "", "", "## 見出し\n本文です。\n")
        none_used = [x[2:].split("が記事に")[0] for x in Q.unused_materials("zz")]
        Q._split = lambda t: ("", "", "", "## 見出し\n当社は2026年10月に、3つのAIへ聞きました。「助かりました」。外部委託（部分支援）の相場は月数十万円〜です。\n")
        all_used = Q.unused_materials("zz")
    finally:
        Q.materials, Q.read, Q._split, Q.site_of = old
    check("使っていない材料を名指し（声は同じ業種の声があるときだけ）", none_used,
          ["当社調べ（複数のAIに同じ質問をして数えた結果）", "お客様の声", "費用の相場"])
    check("全部使っていれば空", all_used, [])
    src = (ROOT / "scripts" / "quality_loop.py").read_text(encoding="utf-8")
    check("先回りの直しは最初の採点の前（公開前の記事だけ）・材料待ちでも使っていない材料があれば直す",
          ("    if not published:\n        pre_improve(slug, budget, ctx, base)\n    sc, why = score(slug)" in src,
           "if unused_materials(slug, site):\n" in src), (True, True))
    fx = (ROOT / "scripts" / "facts.py").read_text(encoding="utf-8")
    check("書く AI にも相場と同じ業種のお客様の声を渡す", ("費用の相場（" in fx, "お客様の声（同じ業種" in fx), (True, True))


def test_publish_does_not_stop_on_scoring_axes():
    print("\n■ 配信の前の検査は、採点の観点の検査（SOFT_FAILS）では止めない（90点の記事が配信できなかった 2026-10-21）")
    src = (ROOT / "scripts" / "publish_flow.py").read_text(encoding="utf-8")
    check("止めるのは採点の観点の外の不合格だけ",
          ("!= 0 and hard_fails(slug):" in src, "not c[0].startswith(tuple(SOFT_FAILS))" in src), (True, True))


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
    ag = (ROOT / "scripts" / "agent_guard.py").read_text(encoding="utf-8")
    check("配信前の検査は採点の観点の検査（SOFT_FAILS）だけでは隔離しない（直している記事を _conflicted へ移していた）",
          "not c[0].startswith(tuple(SOFT_FAILS))" in ag, True)
    import legal_claims as L
    check("支援社数の検査: 1社の事例は拾わず、社数の表示は拾う",
          [bool(L.find(s)) for s in ("当社の不動産会社1社の支援では、順位が上がりました。", "当社は200社の導入を支援しました。",
                                      "当社は11社を支援しました。")], [False, True, True])
    check("相場の注記に当社の語を金額と並べない（当社の価格を書いた形になる）", "「当社」の語を金額と同じ文に書かない" in ql, True)
    import json
    pr = json.loads((ROOT / "data" / "price_ranges.json").read_text(encoding="utf-8"))
    check("相場: 記事作成ツールと一括の委託（数十万円より下に書かない決まりは残す）",
          ("article_tool" in [r["id"] for r in pr["ranges"]], pr["outsource_min_yen"] >= 200000), (True, True))


def test_held_article_counts_on_the_day_it_was_written():
    import daily_audit as D
    import quality_loop as Q
    import tempfile
    from pathlib import Path
    print("\n■ 改善中のまま日をまたいで通った記事は、書いた日の本数に数える（公開日は今日。2026-10-21 に 7/2 本と出た）")
    check("数える日: 前日分の印 → 書いた日 → 公開日",
          [D.counted_day({"date": "2026-10-21", "written": "2026-10-20"}),
           D.counted_day({"date": "2026-10-21", "written": "2026-10-20", "makeup_for": "2026-10-19"}),
           D.counted_day({"date": "2026-10-21", "written": ""})], ["2026-10-20", "2026-10-19", "2026-10-21"])
    with tempfile.TemporaryDirectory() as d:
        art = Path(d) / "zz-held.md"
        art.write_text("---\ntitle: 架空の記事の題です\nslug: zz-held\ncategory: aio\ndate: 2000-01-01\n"
                       "quality_state: improving\n---\n本文です。\n", encoding="utf-8")
        old = Q.ARTICLES
        Q.ARTICLES = Path(d)
        try:
            sc = {"total": 90, "axes": {"originality": 90, "extractability": 90, "decision": 90}}
            Q.write_pass("zz-held", sc, attempts=2, refresh_date=True)
            m = Q.meta_of(Q.read("zz-held"))
        finally:
            Q.ARTICLES = old
    check("通った記事: 公開日は今日・書いた日を残す", (str(m.get("written")), str(m.get("date")) != "2000-01-01"),
          ("2000-01-01", True))


def test_manual_run_does_not_exceed_daily_quota():
    import daily_audit as D
    import pace
    print("\n■ 手で社を指定して起動した回も、その日の本数を書き終えていれば書かない（2026-10-21 に 7/2 本）")
    old = D.articles_by_site, pace.quota, D.today_iso
    D.articles_by_site = lambda: {"zz": [{"date": "2026-10-21", "score": "90", "quality_state": ""},
                                         {"date": "2026-10-21", "score": "", "quality_state": "improving"},
                                         {"date": "2026-10-21", "written": "2026-10-20", "score": "90", "quality_state": ""}]}
    pace.quota = lambda sid: 2
    D.today_iso = lambda: "2026-10-21"
    try:
        full = D.day_left("zz")
        pace.quota = lambda sid: 3
        room = D.day_left("zz")
    finally:
        D.articles_by_site, pace.quota, D.today_iso = old
    check("改善中も数え、前の日に書いた記事は数えない（2本書いた日は残り0・本数3なら残り1）", (full, room), (0, 1))
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    check("手で社を指定した回は書く前に本数を確かめる",
          wf.index('python scripts/daily_audit.py --day-full "$real"') < wf.index('if [ -z "$s" ]; then'), True)


def test_temporary_daily_setting_expires():
    import pace as P
    from datetime import date, timedelta
    print("\n■ 1日の本数を期限つきで減らす（daily_articles_until）。期限を過ぎたら既定の2本へ戻る（2026-10-22 運用者「3日間だけ1日1本」）")
    old = P._site
    today = date.today()
    try:
        P._site = lambda sid: {"daily_articles": 1, "daily_articles_until": today.isoformat()}
        on_last_day = P.setting("zz")
        P._site = lambda sid: {"daily_articles": 1, "daily_articles_until": (today - timedelta(days=1)).isoformat()}
        after = P.setting("zz")
        P._site = lambda sid: {"daily_articles": 1}
        no_limit = P.setting("zz")
    finally:
        P._site = old
    check("期限の日までは1本・過ぎたら2本・期限なしは設定のまま", (on_last_day, after, no_limit), (1, 2, 1))
