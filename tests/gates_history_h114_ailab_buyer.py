# -*- coding: utf-8 -*-
"""2026-10-19 運用者の決定: AI集客ラボの新しい記事は「業種＋依頼する人の語」だけ。

AIO・LLMO の一般語は28日で表示の約6割（2,720回）なのにクリック率0.22%で、相談につながっていなかった。
新しく書く語の入口（next_kw・add_kw・kw_plan・kw_discover・ai_kw_research・kw_gate）は kw_fit.judge_new を通し、
既存の記事の書き直し・配信（kw_guard・publish_flow）は judge のまま（書いた記事を配信から外さない）。
あわせて、名指しした記事の押し上げで空振りしていた2か所を直した:
  - link_boost --inline --only: 順位の表が空のとき、全記事を「送り先より下位」とみなして送り元が0本だった
  - auto_rewrite --kind stock/stuck --slugs: 候補一覧の上位に無い記事を「材料が無い」として飛ばしていた
"""
import json
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_ailab_new_keywords_need_industry_or_buyer_words():
    import kw_fit
    print("\n■ AI集客ラボの新しい記事は業種か依頼する人の語だけ（既存の記事の判定は変えない）")
    got = {k: kw_fit.judge_new(k, "ai-lab")[0] for k in ("aio やり方", "aio とは", "llmo 対策 やり方",
                                                         "歯科 ai 集客", "aio対策 費用", "インバウンド 集客 ai検索")}
    check("一般語は新しく書かない・業種や依頼の語は書く", got,
          {"aio やり方": 2, "aio とは": 2, "llmo 対策 やり方": 2, "歯科 ai 集客": 0, "aio対策 費用": 0,
           "インバウンド 集客 ai検索": 0})
    check("既存の記事の判定（judge）は一般語でも担当領域のまま", kw_fit.judge("aio やり方", "ai-lab")[0], 0)
    check("kw_require の無い社は judge と同じ", kw_fit.judge_new("経理 代行 費用", "corporate"), kw_fit.judge("経理 代行 費用", "corporate"))
    cfg = json.loads((ROOT / "sites" / "ai-lab.json").read_text(encoding="utf-8"))
    check("実際に相談が来た業種を優先に加えた",
          all(x in cfg["kw_seeds"]["priority"] for x in ("インバウンド飲食店", "買取店", "人材紹介会社")), True)


def test_new_article_entrances_use_judge_new_and_existing_ones_do_not():
    print("\n■ 新しく書く語の入口は judge_new・既存の記事の書き直しと配信は judge")
    src = lambda n: (ROOT / "scripts" / n).read_text(encoding="utf-8")
    check("next_kw・add_kw（hub_client._unfit）", "kw_fit.judge_new(k, site)" in src("hub_client.py"), True)
    check("kw_plan・kw_discover・ai_kw_research・kw_gate",
          ["judge_new" in src(n) for n in ("kw_plan.py", "kw_discover.py", "ai_kw_research.py", "kw_gate.py")],
          [True] * 4)
    check("kw_guard・publish_flow は judge のまま",
          ["judge_new" in src(n) for n in ("kw_guard.py", "publish_flow.py")], [False, False])


def test_unwritable_keywords_are_not_counted_as_stock():
    import hub_client
    import kw_plan
    print("\n■ 新しく書けない語は在庫に数えない（数えると書ける語が尽きても積み足さない）")
    rows = [{"site": "ai-lab", "status": "未着手", "keyword": "aio やり方"},
            {"site": "ai-lab", "status": "未着手", "keyword": "歯科 ai 集客"}]
    o_en, o_all = hub_client.enabled, hub_client.all_kw
    try:
        hub_client.enabled, hub_client.all_kw = (lambda: True), (lambda strict=False: rows)
        got = kw_plan.stock("ai-lab")["todo"]
    finally:
        hub_client.enabled, hub_client.all_kw = o_en, o_all
    check("kw_plan.stock: 書ける語だけ", got, ["歯科 ai 集客"])
    src = lambda n: (ROOT / "scripts" / n).read_text(encoding="utf-8")
    check("daily_audit の在庫の点検も judge_new で数える", "kw_fit.judge_new(k.get(\"keyword\"" in src("daily_audit.py"), True)
    check("台帳が読めない日の代わりの語（kw_gate.next_keyword）も judge_new を通す",
          "kw_conflicts(k, arts) and kw_fit.judge_new(k, site)" in src("kw_gate.py"), True)
    check("--ledger --retire で外せる（ledger_unfit も judge_new）", "lv, why = judge_new(r.get(\"keyword\"" in src("kw_fit.py"), True)


def test_named_boosts_do_not_silently_find_nothing():
    import link_boost
    import auto_rewrite as A
    print("\n■ 名指しした記事の押し上げが空振りしない")
    seen = []
    orig, orig_ph = link_boost.sources, link_boost.phrases_for
    try:
        link_boost.phrases_for = lambda site, tgt, arts: ["語句"]
        link_boost.sources = lambda site, tgt, arts, cnt, ranks=None: seen.append(ranks) or []
        link_boost.run_inline("ai-lab", {"t": {"cat": "aio", "title": "t", "kw": "", "body": ""}}, ["t"], {}, {}, "", False,
                              use={})
    except Exception:
        pass
    finally:
        link_boost.sources, link_boost.phrases_for = orig, orig_ph
    check("文中リンク: 順位の表が空なら順位で絞らない（ranks=None）", seen, [None])
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("決まり文句の直し: 名指しなら全記事から探す", "stock_items(10 ** 6 if a.slugs" in src, True)
    check("語の欠けの直し: 名指しなら無料の調べでその場で材料を作る", 'kind == "stuck"' in src and "cooccur_item(s)" in src, True)
