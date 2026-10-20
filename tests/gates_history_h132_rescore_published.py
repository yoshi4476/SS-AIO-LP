# -*- coding: utf-8 -*-
"""2026-10-20 運用者「これで90点以上であれば評価が低い記事を修正していって」「一気に変えた場合不利益や不具合おこるか」。
公開前の採点で合格が出てから、点の低い公開済みの記事を毎日の記事の枠で1本ずつ直す。一気に直すと、同じ型の文が
数百本に並ぶ（量産の指紋）・よく読まれている記事の順位が揺れる・効果を比べる相手がいなくなる・時間が足りなくなるので、
社ごとに7日で12本まで、よく読まれている記事は後回し、対照群（月ごとに5本に1本）は触らない、当社調べの書き出しは散らす。
あわせて Codex は手順の鍵を引き継がずに呼ぶ（検索で読んだページの指示で答えに鍵を書かせられると控えに残る）。
"""
import json
import sys
import tempfile
from pathlib import Path

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_rescore_published_after_new_articles_pass():
    import quality_loop as Q
    print("\n■ 公開済みの記事の直し: 公開前の採点で合格が出てから・社ごとに7日で12本まで・対照群は触らない")
    today = Q.date.today().isoformat()
    rows = [{"at": today + " 10:00", "slug": f"zz-{i}", "mode": "new", "action": "score"} for i in range(5)]
    rows += [{"at": today + " 10:05", "slug": f"zz-{i}", "mode": "new", "action": "pass"} for i in range(2)]
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "q.jsonl"
        log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        before = Q.auto_ready(log)
        rows.append({"at": today + " 11:00", "slug": "zz-2", "mode": "new", "action": "pass"})
        log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        after = Q.auto_ready(log)
        rows += [{"at": today + " 12:00", "slug": f"zz-r{i}", "site": "ai-lab", "mode": "rescore", "action": "score"}
                 for i in range(12)]
        log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        cap = Q.week_done("ai-lab", log)
    check("合格2本/5本では始めず、3本/5本で始める", (before[0], after[0]), (False, True))
    check("7日で直した本数を社ごとに数える（上限12本）", (cap, Q.RESCORE_WEEK_CAP), (12, 12))
    share = sum(Q.control(f"zz-{i}", "2026-10") for i in range(1000)) / 1000
    check("対照群は約5本に1本", 0.15 < share < 0.25, True)
    wf = (ROOT / ".github" / "workflows" / "pipeline-multi.yml").read_text(encoding="utf-8")
    a = wf.index("- name: 公開前の品質ループ（この回に書いた記事を別工程で採点し、届くまで直す）")
    b = wf.index("- name: 当社調べ（点の低い公開済みの記事")
    c = wf.index("- name: 点の低い公開済みの記事を1本直す")
    d_ = wf.index("- name: AIの変更のうち触ってはいけない場所を戻す")
    check("記事の枠: 新しい記事の採点 → 当社調べ → 公開済みを1本 → 触ってはいけない場所を戻す", a < b < c < d_, True)
    step = wf[c:d_]
    check("公開済みの直しは鍵を外した確かめの後・25分無ければ始めない・全権の合言葉を渡さない",
          ("agent_guard.py --verify" in step, '[ "$budget" -lt 25 ]' in step, "HUB_SECRET" in step), (True, True, False))
    wk = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次: 採点し直しの前に当社調べ",
          wk.index("- name: 当社調べ（採点し直す公開済みの記事") < wk.index("- name: 公開済みの記事を公開前と同じ基準で採点し直す"),
          True)


def test_quality_loop_fix_skips_number_check_only_there():
    import auto_rewrite as A
    import quality_loop as Q
    print("\n■ 公開前の品質ループの直しだけ数字の検算をしない（運用者「事実でない数字を防ぐ検算なしにして」2026-10-20）。ほかの直しは残す")
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("品質ループの種類だけ numbers=False", ('nums = kind != "quality_loop"' in src, src.count("numbers=nums")), (True, 2))
    check("ほかの種類は今までどおり無かった数字を止める", bool(A.new_fact_numbers("本文。", "本文。相場は1,500円です。")), True)
    check("直す回数は1回の実行で2回まで（運用者「最大でも二回で90に」）", (Q.ROUNDS, Q.MAX_ROUNDS), (2, 2))
    w = Q.lower({"axes": {"originality": 80, "extractability": 90, "decision": 90},
                 "quotes": {"originality": "a", "extractability": "a", "decision": "a"},
                 "weak": {"originality": ["x"], "extractability": ["y"], "decision": ["z"]}},
                {"axes": {"originality": 85, "extractability": 80, "decision": 90},
                 "quotes": {"originality": "b", "extractability": "b", "decision": "b"},
                 "weak": {"originality": ["x2"], "extractability": ["y2"], "decision": ["z"]}})
    check("2回採点の弱い点は合わせて渡す（同じ指摘は1つ）", (w["weak"]["originality"], w["weak"]["decision"]),
          (["x", "x2"], ["z"]))
    pr = (ROOT / "automation" / "multi_site_prompt.txt").read_text(encoding="utf-8")
    check("書く指示: 採点の100点の書き方と、専門家に確認で終わらせない決まり",
          ("90点以上で書くための条件" in pr, "「税理士（専門家）に確認してください」で終わらせない" in pr), (True, True))


def test_sns_posts_are_article_summaries_without_x():
    import post_social as PS
    print("\n■ SNS: 記事 → 要約 → 投稿（冒頭の答えと各H2の1文結論だけ）。X は使わない（運用者 2026-10-20）")
    body = ("**庭木の剪定は、木の高さで頼むか決めます。**3m以上なら業者です。\n\n## 自分で切れる木は？\n"
            "高さ3m未満の木は、自分で剪定できます。\n\n## 業者の選び方は？\n見積もりの内訳で業者を選びます。\n\n"
            "## よくある質問\n答え。\n")
    pts = PS.points(body)
    check("要点は冒頭の答えと H2 の1文結論（FAQ は入れない）",
          pts, ["庭木の剪定は、木の高さで頼むか決めます。", "高さ3m未満の木は、自分で剪定できます。", "見積もりの内訳で業者を選びます。"])
    meta = {"title": "庭木の剪定の頼み方", "description": "説明", "slug": "zz-niwaki"}
    cfg = {"domain": "zz.example", "cta": {"url": "/lp/", "label": "相談"}}
    th = PS.compose(meta, "https://zz.example/a/", cfg, "threads", body)
    ig = PS.compose(meta, "https://zz.example/a/", cfg, "instagram", body)
    check("Threads は500字未満・Instagram は本文にリンクを置かない",
          (len(th) <= PS.STYLE["threads"]["limit"], "https://" in ig), (True, False))
    check("X は投稿の媒体に無い", "x" in PS.STYLE, False)
    src = (ROOT / "scripts" / "post_social.py").read_text(encoding="utf-8")
    check("X に投稿しない", "x_post(t[" in src, False)


def test_codex_runs_without_step_keys_and_heads_vary():
    import own_survey as O
    print("\n■ Codex は手順の鍵を引き継がずに呼ぶ・当社調べの書き出しは記事ごとに散らす")
    src = (ROOT / "scripts" / "ai_cite_check.py").read_text(encoding="utf-8")
    seg = src[src.index("def ask_chatgpt_codex"):src.index("def subscription_engines")]
    check("Codex に鍵を外した環境を渡す", ("child_env()" in seg, "env=env" in seg), (True, True))
    base = {"ok": True, "date": "2026-10-20", "question": "q", "engines": ["Claude", "ChatGPT"], "topics": [],
            "dims": {"費用の金額（◯円）": []}, "sources": {}}
    heads = {O.claims({**base, "slug": f"zz-{i}"})[0].split("、")[0] for i in range(30)}
    check("書き出しは3通りに散る", len(heads), 3)
    ar = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("直しの指示: 当社調べは記事に2つまで・書き出しは1回", "当社調べ（出典: 当社調べ）の文は記事に2つまで" in ar, True)
