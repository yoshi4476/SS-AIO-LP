# -*- coding: utf-8 -*-
"""2026-11-24 お客様の社のサイトで、前のサイトのURL（/about/ など）を新しいページへ301で移した直後、
公開後の本番巡回（live_check）が決め打ちで見に行く /about/ を「別のURLへ転送」と要対応で知らせた。
転送を問題にするのは、トップ・sitemap に載せたページ・sitemap が取れない回・別のドメインへ飛ぶときだけ。"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_live_check_redirect_only_matters_for_indexed_pages():
    import live_check as LC
    print("\n■ 本番巡回: 旧URLを同じサイトの新しいページへ移した転送を、要対応にしない")
    sm = {"https://x.example", "https://x.example/company", "https://x.example/column/a"}
    cases = [
        ("https://x.example/about/", "https://x.example/company/", sm),       # 意図した旧URLの転送
        ("https://x.example/column/a/", "https://x.example/column/b/", sm),   # sitemap に載せたページが転送
        ("https://x.example/", "https://x.example/home/", sm),                # トップが転送
        ("https://x.example/about/", "https://x.example/company/", None),     # sitemap が取れない回
        ("https://x.example/about/", "https://parked.example/", sm),          # 別のドメインへ飛ぶ
        ("https://x.example/about/", "https://www.x.example/about/", sm),     # www の付け外しは同じサイト
    ]
    got = [any("別のURLへ転送" in p for p in LC.check_page(u, "<p>x</p>", 200, f, idx)) for u, f, idx in cases]
    check("転送は sitemap のページ・トップ・sitemap なし・別ドメインだけ問題にする", got,
          [False, True, True, True, True, False])
