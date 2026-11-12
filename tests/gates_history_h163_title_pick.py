# -*- coding: utf-8 -*-
"""2026-11-12 週次の「書き直しの効き（種類別・28日・対照群比）」が title を「効かない」と出した。
判定済み21件（前後28日・自社の記事）を順位帯で分けると、11位以下で題を直した記事は前後14日・21日・28日の
どの窓でもクリックが0本のまま（直す前は2・4・4本）で、28日の表示は対照比0.65倍だった。1〜10位の記事は
対照比1.39倍（中央値）で、全体の1.01倍は2つの層を混ぜた値だった。11位以下は狙う語が題に無いこと・飾りの年号を理由に
rank_up が title として渡していたが、その帯は題が良くなってもクリックがほとんど生まれない（同じ条件の触っていない記事の
CTRも0.1〜0.8%）。同じ日の週次でも、題を直した10本のうち6本が11位以下だった"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def _page(slug, pos, imp, clicks, kw):
    return {"slug": slug, "url": f"https://zz.example/blog/{slug}", "pos": pos, "imp": imp, "clicks": clicks,
            "kws": [(kw, pos, imp)], "urls": 1}


def test_title_rewrites_only_on_page_one():
    import rank_up
    import sites
    print("\n■ 題の書き直しの候補は1〜10位だけ（11位以下は題を直してもクリックが生まれなかった）")
    fm = "---\ntitle: {t}\nkeyword: {k}\ndate: 2026-08-01\n---\n本文\n"
    texts = {
        "zz-snippet": fm.format(t="経理代行の費用相場｜月額の目安と内訳", k="経理代行 費用"),
        "zz-deco7": fm.format(t="記帳代行の選び方【2026年】", k="記帳代行 選び方"),
        "zz-kw15": fm.format(t="経理の仕事の範囲と任せ方", k="経理補助 違い"),
        "zz-deco15": fm.format(t="経理代行の相場【2026年最新】", k="経理代行 相場"),
        "zz-kw30": fm.format(t="バックオフィスの外注先", k="経理 外注 比較"),
    }
    pages = {p["url"]: p for p in (
        _page("zz-snippet", 7.0, 120, 0, "経理代行 費用"),
        _page("zz-deco7", 6.0, 80, 0, "記帳代行 選び方"),    # 目安まで上がれば3.6本増える（h165 の下限3本を超える）
        _page("zz-kw15", 15.0, 60, 0, "経理補助 違い"),
        _page("zz-deco15", 15.0, 40, 0, "経理代行 相場"),
        _page("zz-kw30", 30.0, 80, 0, "経理 外注 比較"),
    )}
    saved = rank_up.fetch, rank_up.articles, sites.load_all
    rank_up.fetch = lambda domain, days=28: pages
    rank_up.articles = lambda: texts
    sites.load_all = lambda: {"client-zz": {"id": "client-zz", "domain": "zz.example"}}
    try:
        got = {x["slug"]: x["kind"] for x in rank_up.human_items()}
    finally:
        rank_up.fetch, rank_up.articles, sites.load_all = saved
    check("7位でクリック率が目安の半分未満 → 題の書き直し", got.get("zz-snippet"), "title")
    check("6位で飾りの年号・クリック0 → 題の書き直し", got.get("zz-deco7"), "title")
    check("15位で題に狙う語が無い → 題の書き直しに回さない", got.get("zz-kw15") == "title", False)
    check("15位で飾りの年号 → 題の書き直しに回さない", got.get("zz-deco15") == "title", False)
    check("30位で題に狙う語が無い → 題の書き直しに回さない", got.get("zz-kw30") == "title", False)
    # 一覧（rank_up の画面）には今までどおり出す。自動の書き直しに回さないだけ
    kinds = [k for k, _, _ in rank_up.diagnose("zz-kw15", pages["https://zz.example/blog/zz-kw15"], texts, pages)]
    check("11位以下の「題に狙う語が無い」は一覧には出す", "title" in kinds, True)
    check("境目は1ページ目（10.5位）", rank_up.TITLE_MAX_POS, 10.5)
    doc = (ROOT / "docs" / "pipeline" / "08-weekly.md").read_text(encoding="utf-8")
    check("文書に選び方の決まりがある", "題の書き直しの候補は1〜10位だけ" in doc, True)
