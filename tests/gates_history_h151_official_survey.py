"""h151: 当社調べは記事が公的資料から引いた制度・法令に AI の答えが触れたかを数え、一次性が低い直しには直し方を渡す（2026-11-02）"""
import sys

from test_gates import check, ROOT


def test_survey_counts_official_points():
    sys.path.insert(0, str(ROOT / "scripts"))
    import own_survey as O
    import quality_loop as Q
    print("\n■ 当社調べ: 公的資料の点に AI の答えが触れたかを数える（「論点の語が出たか」は採点で「判断に使えない」と減点。運用者「一次性を上げる努力を」）")
    body = ("## 差額の扱い\n振込手数料の差引きは[公正取引委員会の資料](https://www.jftc.go.jp/x.pdf)で取適法の違反とされます。"
            "独立行政法人の窓口もあります。各種融資制度は別です。\n## 消費税\n国税庁はインボイス制度の端数処理を示しています。\n"
            "一般の仕訳の制度の話（出典なし）。景品表示法には触れない文です。\n")
    terms = O.official_terms(body, "差額 仕訳")
    check("拾う名前（法人・各種・出典の無い文の名前は拾わない）", terms,
          [("取適法", "公正取引委員会"), ("インボイス制度", "国税庁")])
    check("狙う語を含む名前は拾わない", O.official_terms("国税庁のインボイス制度。", "インボイス制度"), [])

    def ask(site, qs):
        texts = ["取適法では差引きは違反です", "手数料は支払手数料で処理します", "インボイス制度の端数は1回",
                 "相殺の仕訳です", "インボイス制度と取適法", "値引きの処理"]
        return {("ChatGPT" if i < 3 else "Gemini", i % 3): {"text": t, "domains": []} for i, t in enumerate(texts)}
    kinds, O.kinds = O.kinds, lambda d, s: {}
    try:
        res = O.measure("zz", "zz-a", body, "差額 仕訳", ask_fn=ask)
    finally:
        O.kinds = kinds
    check("公的資料の点ごとの数（答え6件のうち）", [(r["term"], r["hits"], r["of"]) for r in res["official"]],
          [("取適法", 2, 6), ("インボイス制度", 2, 6)])
    cs = O.claims(res)
    check("文は公的資料の点が先で、論点の語の文は書かない",
          (len(cs) >= 2, "公正取引委員会の資料にある「取適法」に触れたものは2件" in cs[0] + cs[1],
           any("に触れたものは" in c and "資料にある" not in c for c in cs)), (True, True, False))
    src = (ROOT / "scripts" / "own_survey.py").read_text(encoding="utf-8")
    check("公的資料の点を数える前の結果は、同じ月でも数え直して残す",
          ('counted = "official" in old or not official_terms(text, kw)' in src,
           src.count("and counted") >= 2), (True, True))


def test_low_originality_gets_a_plan():
    sys.path.insert(0, str(ROOT / "scripts"))
    import quality_loop as Q
    base = {"axes": {"originality": 77, "extractability": 90, "decision": 88},
            "quotes": {"originality": "", "extractability": "", "decision": ""},
            "weak": {"originality": [], "extractability": [], "decision": []}}
    low = Q.weak_text(base)
    high = Q.weak_text({**base, "axes": {**base["axes"], "originality": 92}})
    check("一次性が基準の近くまでなら直し方を渡し、十分なら渡さない",
          ("一次性を上げる直し方" in low, "一次性を上げる直し方" in high), (True, False))
    check("直し方は材料に無い事実を足させない", "材料に無い事実・数字は足さない" in Q.ORIGINALITY_PLAN, True)
