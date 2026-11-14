"""競合と比べて測る語の数を、サイトごとに設定で変えられるようにする（2026-11-15 運用者「今までの記事もすべてAIに
取り上げられるようにしたい」）。前は1サイト月20語の決め打ちで、AI集客ラボの181本のうちAIに聞いて測れていたのは
23語だけだった。差を埋める書き足し（auto_rewrite --kind compete）はこの語からしか選ばれない"""
from test_gates import check


def test_compete_keyword_count_is_configurable():
    import compete as C
    import sites as S
    print("\n■ 競合比較: 測る語の数をサイトの設定（compete.max_kw）で変えられる")
    check("設定が無ければ今までどおり20語", C.max_kw({}), 20)
    check("設定があればその数", C.max_kw({"compete": {"max_kw": 40}}), 40)
    check("壊れた設定は既定に戻す", C.max_kw({"compete": {"max_kw": "abc"}}), 20)
    lab = S.load("ai-lab")
    check("AI集客ラボは40語を測る", C.max_kw(lab), 40)
    # 1語につき3つ前後のAIに新しく聞く（11月は20語で59回）。40語なら上限も倍にしないと途中で止まる
    check("AI集客ラボの月の上限は語の数の3倍以上", C.ai_cap(lab) >= 3 * C.max_kw(lab), True)
