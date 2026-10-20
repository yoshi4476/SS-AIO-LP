# -*- coding: utf-8 -*-
"""2026-10-21 運用者「手間を減らす案作って」。SNS の接続を、グラフ API エクスプローラのトークンを貼る手順から、
ブラウザで許可を押すだけにした（Facebook・Instagram・Threads）。お客様は別の PC で押すので、戻り先は localhost ではなく
管制塔（Apps Script）にし、許可の印を15分だけ預かって、全権の合言葉の道具だけが1回きり受け取る。
"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_hub_holds_sns_code_briefly_and_only_for_the_full_secret():
    print("\n■ 管制塔: 許可の印は一時保存に15分だけ・受け取りは合言葉の道具だけ・1回きり")
    hub = (ROOT / "automation" / "gas" / "hub.gs").read_text(encoding="utf-8")
    check("戻り先は一時保存（表に残さない）・15分", ("CacheService.getScriptCache().put(String(p.state)" in hub, "900);" in hub,
                                          "appendRow" in hub[hub.index("function snsCode_"):hub.index("function doGet")]),
          (True, True, False))
    check("受け取ったら消す", "c.remove(String(state));" in hub, True)
    main = hub[hub.index("switch (body.action) {"):]
    agent = hub[hub.index("function agentWrite_"):hub.index("function doGet")]
    check("受け取りは全権の合言葉の分岐にだけある（AI 用の通行証では受け取れない）",
          ("case 'sns_code'" in main, "sns_code" in agent), (True, False))
    check("印の形を決めて受ける", "const SNS_STATE = /^sns_[A-Za-z0-9_-]{16,64}$/;" in hub, True)


def test_social_connect_browser_link_paste():
    import social_connect as SC
    print("\n■ つなぐ道具: 既定はブラウザで許可・お客様には --link・前の方法は --paste")
    src = (ROOT / "scripts" / "social_connect.py").read_text(encoding="utf-8")
    check("3つの入り方", ('mode = "paste" if a.paste else "link" if a.link else "browser"' in src,
                         'def facebook(site, page_hint, mode="browser"):' in src, 'def threads(site, mode="browser"):' in src),
          (True, True, True))
    check("印の名前は推測できない長さ", len(SC.new_state()) >= 20 and SC.new_state().startswith("sns_"), True)
    check("LinkedIn も管制塔を戻り先にし、お客様には --link（localhost はつなぐ道具の控え）",
          ('def linkedin(site, mode="browser"):' in src, 'linkedin(a.site, "link" if a.link else "browser")' in src,
           "_linkedin_finish(site, d, app, redirect, wait_code(url, \"LinkedIn\", mode == \"link\"))" in src),
          (True, True, True))
    check("投稿に要る権限を求める", ("pages_manage_posts" in SC.FB_SCOPES, "instagram_content_publish" in SC.FB_SCOPES,
                                  "threads_content_publish" in SC.TH_SCOPES), (True, True, True))
