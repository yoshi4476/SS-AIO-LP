# -*- coding: utf-8 -*-
"""サイトをまたいだ重複とリンクの操作への備えを、一部から全部にする（2026-11-15 運用者「一部を完璧にして」）。

  1. 量産の検査（scaled_guard）の比べる相手が「90点以上」のままで、公開の下限を85へ下げた（2026-10-21）後の
     85〜89点の記事（自社63本・お客様の社21本）が外れていた。下限は rubric.PASS_TOTAL にそろえる。
     お客様の社の記事も比べる相手に入るので、ログには slug を出さない（CI のログは public）
  2. 本文のサイト間リンクに上限が無かった。1記事1本・各サイトで他サイトへリンクする記事は2割まで。
     新しい記事は build.py と publish.py の門で止め、週次で知らせる。コーポレートの35本が材料に渡された
     AI集客ラボの調査ページへリンクしていたため、上限に届いている間は材料に URL を渡さない

ネットワーク・台帳には触れない（記事は一時の場所に作る）。
"""
import tempfile
from pathlib import Path

from test_gates import check

ROOT = Path(__file__).resolve().parent.parent


def _art(d, slug, cat, score, body):
    (d / f"{slug}.md").write_text(
        f"---\ntitle: {slug}\nslug: {slug}\ncategory: {cat}\nkeyword: {slug}\nscore: {score}\n---\n\n{body}\n",
        encoding="utf-8")


def _cats():
    import sites as S
    lab, corp = S.load("ai-lab"), S.load("corporate")
    return (next(iter(lab["categories"])), next(iter(corp["categories"])),
            "https://" + lab["domain"], "https://" + corp["domain"])


def test_scaled_corpus_uses_publish_bar():
    import rubric
    import scaled_guard as SG
    print("\n■ 量産の検査: 比べる相手は公開の下限（rubric.PASS_TOTAL）以上の全記事")
    lab_cat, _c, _l, _u = _cats()
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        body = "これは比べる相手に入るかを確かめるための本文です。" * 20
        _art(d, "s-bar", lab_cat, rubric.PASS_TOTAL, body)
        _art(d, "s-mid", lab_cat, 89, body)
        _art(d, "s-low", lab_cat, rubric.PASS_TOTAL - 1, body)
        old = SG.ARTICLES
        SG.ARTICLES = d
        try:
            got = sorted(SG.corpus())
        finally:
            SG.ARTICLES = old
    check("公開の下限ちょうど・89点の記事も比べる相手に入り、下限未満は入らない", got, ["s-bar", "s-mid"])


def test_client_slug_is_not_logged():
    import cross_links as CL
    import sites as S
    print("\n■ 量産・リンクの検査: お客様の社の記事は slug をログに出さない")
    orig = (S.is_client, S.public_id)
    S.is_client = lambda sid: sid == "client-x"
    S.public_id = lambda sid: "pub123" if sid == "client-x" else sid
    try:
        masked = CL.name("secret-client-slug", "client-x")
        own = CL.name("own-slug", "ai-lab")
    finally:
        S.is_client, S.public_id = orig
    check("お客様の社の記事は公開の id と短い印だけ", ("secret-client-slug" in masked, masked.startswith("pub123")), (False, True))
    check("自社の記事は slug のまま", own, "own-slug")
    import scaled_guard as SG
    src = (ROOT / "scripts" / "scaled_guard.py").read_text(encoding="utf-8")
    check("量産の検査の明細は name() を通して出す", ("{name(near[1])}" in src, "{name(a)} ～ {name(b)}" in src), (True, True))
    check("量産の検査に name がある", callable(getattr(SG, "name", None)), True)


def test_cross_site_link_limits():
    import cross_links as CL
    print("\n■ 本文のサイト間リンク: 1記事1本・各サイト2割まで")
    lab_cat, corp_cat, lab_url, corp_url = _cats()
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        for i in range(8):
            _art(d, f"c{i}", corp_cat, 90, f"本文 {corp_url}/services/ へのリンク（同じサイトは数えない）")
        _art(d, "c-one", corp_cat, 90, f"調査は [こちら]({lab_url}/research/x/) を見る")
        _art(d, "c-two", corp_cat, 90, f"[a]({lab_url}/a/) と [b]({lab_url}/b/)")
        old = CL.ARTICLES
        CL.ARTICLES = d
        try:
            arts = CL.corpus()
            one = CL.check("c-one", arts)
            two = CL.check("c-two", arts)
            plain = CL.check("c0", arts)
            room_now = CL.room("corporate", arts)
            _art(d, "c-new", corp_cat, 90, f"もう1本 [x]({lab_url}/x/)")
            third = CL.check("c-new", CL.corpus())
        finally:
            CL.ARTICLES = old
    check("同じサイトへのリンクは数えない", plain, [])
    check("他サイトへ1本で、サイトの2割以内なら通す", one, [])
    check("他サイトへ2本の記事は止める", any("1本" in x and "2本" in x for x in two), True)
    check("2割を超える記事は止める（11本中3本がリンクを持つ）", any("上限20%" in x for x in third), True)
    check("上限に届いた後の room は False", room_now, False)


def test_research_url_withheld_when_full():
    import cross_links as CL
    import industry_ai_sources as IAS
    import sites as S
    print("\n■ 材料: 上限に届いたサイトには、調査の数字だけ渡して URL を渡さない")
    if not (S.load("corporate") or {}).get("research"):
        check("コーポレートに調査の業種の設定がある（前提）", False, True)
        return
    orig = (IAS.material_claims, CL.room)
    IAS.material_claims = lambda ind, who="当社": ["当社は2026年10月に調べました。"]
    try:
        CL.room = lambda site, arts=None: False
        full = IAS.for_site("corporate", "", "")
        CL.room = lambda site, arts=None: True
        free = IAS.for_site("corporate", "", "")
    finally:
        IAS.material_claims, CL.room = orig
    check("上限のときは数字だけ（URL は空）", (bool(full[0]), full[1]), (True, ""))
    check("余裕があれば URL も渡す", free[1].startswith("https://"), True)


def test_gates_are_wired():
    print("\n■ 本文のサイト間リンクの門がつながっているか")
    b = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    p = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    f = (ROOT / "scripts" / "findings.py").read_text(encoding="utf-8")
    check("build.py が新しい記事に当てる", '_CL.check(meta["slug"], _cl_corpus)' in b, True)
    check("publish.py が配信の前に当てる", "cross_links.check(args.slug)" in p, True)
    check("週次の知らせ（findings）が呼ぶ", '"cross_links.py"' in f, True)


def test_fresh_rewrite_moves_date_only_with_body():
    """鮮度の書き直しで題・説明だけ変わった回に更新日を進めると、本文が同じなのに日付だけ新しくなる。
    自社3サイトは build.py が戻すが、CONFLUX など別リポジトリの社は publish.py が modified をそのまま渡していた"""
    import auto_rewrite as AR
    print("\n■ 鮮度の書き直し: 本文が変わったときだけ更新日を進める")
    a = "---\ntitle: 旧\nmodified: 2026-10-01\n---\n\n本文はこれです。\n"
    b = "---\ntitle: 新しい題\nmodified: 2026-10-01\n---\n\n本文はこれです。\n"
    c = "---\ntitle: 旧\nmodified: 2026-10-01\n---\n\n本文を書き足しました。\n"
    check("題だけ変わった回は本文の変更と見なさない", AR.body_changed(a, b), False)
    check("本文が変わった回は変更と見なす", AR.body_changed(a, c), True)
    src = (ROOT / "scripts" / "auto_rewrite.py").read_text(encoding="utf-8")
    check("鮮度の書き直しの日付の更新は本文の変更が条件", 'kind == "fresh" and body_changed(before[2]' in src, True)


def test_industry_variants_are_not_cannibals():
    """業種ごとに記事を載せていく運用では、業種違いは別の検索で食い合わない（2026-11-15 運用者）。
    横断の検査とこれから書く語の検査が文字の似かた（0.7前後）だけで「重複のおそれ」と出していた"""
    import cannibal_check as C
    print("\n■ 食い合いの検査: 業種違いは重複のおそれにしない。同じ業種・業種なしの似た語は今までどおり")
    check("歯科と整骨院の同じ語は業種違い", C.other_industry("歯科 AIO対策 費用", "整骨院 AIO対策 費用"), True)
    check("工務店と不動産の同じ語は業種違い", C.other_industry("工務店 SEO対策 会社", "不動産 SEO対策 会社"), True)
    check("業種の無い似た語は業種違いにしない（食い合いとして見る）", C.other_industry("AIO対策 費用", "AIO対策 費用 相場"), False)
    check("同じ業種どうしは業種違いにしない", C.other_industry("歯科 AIO対策 費用", "歯科 AIO対策 会社"), False)
    src = (ROOT / "scripts" / "cannibal_check.py").read_text(encoding="utf-8")
    check("横断とこれから書く語の両方の検査で外す", src.count("and not other_industry("), 2)
