# -*- coding: utf-8 -*-
"""新記事の公開30日後のAI引用確認と、業種調査の前回との差の門（2026-10-04）。

どちらも「拾うはずのものを拾い、隣のものを誤って拾わない」ことを作った見本で確かめる。
窓の端を1日ずらすと、毎週同じ記事に課金して聞き直すか、一度も聞かれない記事が出る。
AIの顔ぶれが変わった回をそのまま比べると、顔ぶれの違いが「出典の変化」に見える。
"""
import inspect
from datetime import date

from test_gates import check, ROOT


def test_ai_followup_picks_each_new_article_once():
    import ai_followup as F

    today = date(2026, 10, 4)

    def art(slug, d, kw="経理 代行", score=95, cat="aio"):
        return {"slug": slug, "keyword": kw, "date": d, "category": cat, "score": score}

    items = [art("d27", date(2026, 9, 7)), art("d28", date(2026, 9, 6)), art("d40", date(2026, 8, 25)),
             art("d41", date(2026, 8, 24)), art("nokw", date(2026, 9, 1), kw=""),
             art("draft", date(2026, 9, 1), score=85), art("noscore", date(2026, 9, 1), score=None),
             art("done", date(2026, 9, 1)), art("nodate", None)]
    got = [a["slug"] for a in F.targets(items, {"done"}, today)]
    check("公開28日と40日は対象、27日と41日は対象外", got, ["d40", "d28"])
    check("窓を出そうな古い順に並ぶ", got[0], "d40")
    check("上限を超えた分は次の週に回す",
          len(F.targets([art(f"a{i}", date(2026, 9, 1)) for i in range(12)], set(), today, limit=8)), 8)

    hits = ["https://ai.7senses.co.jp/aio/x/", "https://www.ai.7senses.co.jp/seo/y/",
            "https://corp.7senses.co.jp/blog/z", "https://example.com/ai.7senses.co.jp/"]
    check("自社ドメインの出典だけを数える（www は同じ・別のサブドメインと他所のパスは数えない）",
          F.ours(hits, "ai.7senses.co.jp"), hits[:2])

    class Boom(Exception):
        pass

    def fail(q):
        raise Boom("HTTP 429")

    a = art("x", date(2026, 9, 1))
    check("全エンジンが失敗したら記録しない（次の週に聞き直す）", F.measure(a, "ai.7senses.co.jp", {"G": fail}), None)
    r = F.measure(a, "ai.7senses.co.jp", {"G": fail, "C": lambda q: ["https://ai.7senses.co.jp/aio/x/"]})
    check("1つでも答えれば記録し、引用ありと数える", (r["cited"], "error" in r["engines"]["G"]), (True, True))
    r = F.measure(a, "ai.7senses.co.jp", {"C": lambda q: ["https://example.com/"]})
    check("出典に自社が無ければ引用なし", r["cited"], False)

    src = inspect.getsource(F)
    check("聞き方は ai_cite_check.engines_available を使う（新しい呼び出し方を書かない）",
          "AC.engines_available()" in src and "urllib" not in src, True)
    rep = inspect.getsource(F.report)
    check("引用0は要対応にしない（全件失敗だけ）",
          rep.count("要対応") == 1 and 'state") == "failed"' in rep, True)
    # 他の門が findings を差し替えることがあるので、モジュールではなく原文で見る
    fs = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("findings が結果を拾う", '"ai_followup.py --report"' in fs, True)
    wf = (ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8")
    check("週次が上限つきで回す", "ai_followup.py --limit" in wf, True)


def test_research_diff_compares_like_with_like():
    import research_diff as R

    def summ(d, answered, by_engine, top):
        return {"date": d, "answered": answered, "by_engine": by_engine, "portal_top": [[x, 1] for x in top]}

    prev = summ("2026-07-02", {"ChatGPT": 0, "Claude": 50},
                {"Claude": {"clinic": 60, "portal": 40}}, ["a.jp", "b.jp"])
    cur = summ("2026-10-02", {"ChatGPT": 50, "Claude": 50},
               {"Claude": {"clinic": 50, "portal": 50}, "ChatGPT": {"portal": 100}}, ["b.jp", "c.jp"])
    r = R.compare(prev, cur)
    check("前回答えていないAIは割合に入れない", r["engines"], ["Claude"])
    check("割合の差はポイントで出す", {x["type"]: x["pt"] for x in r["rows"]}, {"clinic": -10.0, "portal": 10.0})
    check("上位サイトの入れ替わり", (r["entered"], r["left"]), (["c.jp"], ["a.jp"]))
    check("AIの顔ぶれが違えば入れ替わりに注記する", r["mixed"], True)
    check("顔ぶれが同じなら注記しない",
          R.compare(prev, summ("2026-10-02", {"ChatGPT": 0, "Claude": 50},
                               {"Claude": {"clinic": 60, "portal": 40}}, ["a.jp"]))["mixed"], False)

    small = summ("2026-10-02", {"Claude": 19}, {"Claude": {"clinic": 19}}, [])
    check("回答20未満の回は比べない", "reason" in R.compare(prev, small), True)
    check("20ちょうどなら比べる",
          "reason" in R.compare(prev, summ("2026-10-02", {"Claude": 20}, {"Claude": {"clinic": 20}}, [])), False)
    check("前回が無ければ比べない", "reason" in R.compare(None, cur), True)
    check("両方で答えたAIが無ければ比べない",
          "reason" in R.compare(summ("2026-07-02", {"Gemini": 30}, {"Gemini": {"clinic": 30}}, []),
                                summ("2026-10-02", {"Claude": 30}, {"Claude": {"clinic": 30}}, [])), True)
    check("同じ回の途中の版（数日違い）は前回にしない", R.MIN_DAYS >= 30, True)
    md = R.markdown([("dental", "歯科", r), ("x", "X", {"reason": "前回の回がありません"})], "2026-10")
    check("レポートに比べたAIと比べなかった業種が出る", "比べたAI: Claude" in md and "## 比べなかった業種" in md, True)
    wf = (ROOT / ".github" / "workflows" / "industry-research.yml").read_text(encoding="utf-8")
    check("業種調査の公開の前に差を出し、docs をコミットに入れる",
          wf.index("research_diff.py") < wf.index("git commit") and "docs/research-diff-" in wf, True)
