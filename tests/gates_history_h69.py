# -*- coding: utf-8 -*-
"""2026-10-08 Search Console（corp.7senses.co.jp）「日時プロパティ『uploadDate』にタイムゾーンがありません」
「『uploadDate』の日時値が無効です」から。

原因: 動画の台帳（data/videos.json）は日本時間の日付だけ（2026-10-06）を持ち、VideoObject の uploadDate に
そのまま出していた。AI集客ラボ（build.py）とコーポレート・補助金（publish.py）が同じ video_embed を通るので、
そこで時差つきの日時にそろえる。
"""
import json
import re
import sys
from unittest import mock

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

ISO_TZ = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})$")


def test_video_upload_date_has_timezone():
    import video_embed as VE
    check("日付だけの台帳は日本時間の0時（+09:00）にする", VE.upload_date({"date": "2026-10-06"}),
          "2026-10-06T00:00:00+09:00")
    check("時差つきの日時はそのまま", VE.upload_date({"date": "2026-10-06T12:30:00+09:00"}),
          "2026-10-06T12:30:00+09:00")
    rec = {"youtube": "abcdefghijk", "date": "2026-10-03", "sec": 285}
    with mock.patch.object(VE, "info", return_value=rec):
        html = VE.block({"slug": "s1", "title": "題", "description": "説明"})
    ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1))
    check("記事に埋める VideoObject の uploadDate は時差つきの日時", bool(ISO_TZ.match(ld["uploadDate"])), True)
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("配信先（アプリ用の JSON）も同じ関数を通す（日付だけを直接出さない）",
          ["video_embed.upload_date(rec)" in src, '"uploadDate": rec.get("date"' in src], [True, False])


def test_indexnow_uses_the_key_each_domain_serves():
    """同じ日の通知「CONFLUX … IndexNow の鍵ファイル https://conflux-partners.jp/acc9b880….txt が出ていません」から。
    先方は自分の鍵（b1d698…）を直下に置いていた。共通の鍵で確かめると毎回「要対応」が出て、通知も送られない"""
    import notify_indexnow as NI
    import search_connect as SC
    check("社の設定に鍵があればその鍵", NI.key_for("https://conflux-partners.jp", "共通"),
          "b1d698a3b0111f8ddc9cc2f94d344fde")
    check("無ければ共通の鍵", NI.key_for("https://lp.7senses.co.jp", "共通"), "共通")
    sent = []
    cfgs = {"x": {"id": "x", "domain": "x.example.jp", "indexnow_key": "k" * 32, "type": "external-md"}}
    with mock.patch.object(NI, "load_env", return_value={"INDEXNOW_KEY": "c" * 32}), \
            mock.patch.object(NI, "key_ok", side_effect=lambda d, k: sent.append(("ok", k)) or True), \
            mock.patch.object(NI, "sitemap_urls", return_value=["https://x.example.jp/a/"]), \
            mock.patch.object(NI, "notify", side_effect=lambda u, k, s: sent.append(("send", k)) or 200):
        NI.main([], cfgs)
    check("通知も確かめも、その社の鍵で行う", sent, [("ok", "k" * 32), ("send", "k" * 32)])
    with mock.patch.object(NI, "load_env", return_value={"INDEXNOW_KEY": "c" * 32}), \
            mock.patch("bing_webmaster.auth_code", return_value=""), mock.patch("sites.is_client", return_value=True):
        files = SC.files_for({"id": "x", "type": "external-md", "indexnow_key": "k" * 32})
    check("配信で置く鍵ファイルも、その社の鍵（共通の鍵を足さない）", sorted(files), [f"{'k' * 32}.txt"])
    for f in ("reindex.py", "onboard_check.py"):
        s = (ROOT / "scripts" / f).read_text(encoding="utf-8")
        check(f"{f} もその社の鍵で確かめる", "key_for(" in s or 'cfg.get("indexnow_key")' in s, True)


def test_profile_page_date_modified_is_datetime():
    """2026-10-10 Search Console（ai.7senses.co.jp）「プロフィール ページ … 『dateModified』の日時値が無効です」
    （/author/haraguchi/）から。ProfilePage の dateModified は日時（DateTime）で、日付だけ（2026-10-05）を出していた。
    書き換える author_profile.py は日付だけの形しか探さず、週次のたびに中身が同じでも日付だけ進めていた"""
    import shutil
    import tempfile
    from pathlib import Path
    import author_profile as AP
    page = ROOT / "site" / "author" / "haraguchi" / "index.html"
    src = page.read_text(encoding="utf-8")
    lds = [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">(.*?)</script>', src, re.S)]
    prof_ld = [g for ld in lds for g in ld.get("@graph", [ld]) if g.get("@type") == "ProfilePage"]
    check("著者ページの ProfilePage の dateModified は時差つきの日時", [bool(ISO_TZ.match(g.get("dateModified", ""))) for g in prof_ld], [True])

    block = re.search(r"<!-- auto:works -->.*?<!-- /auto:works -->", src, re.S).group(0)
    same = json.loads(re.search(r'"sameAs":\s*(\[[^\]]*\])', src).group(1))
    old = re.search(r'"dateModified":\s*"([^"]*)"', src).group(1)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / "index.html"
        shutil.copy(page, tmp)
        stamp = lambda p: AP.STAMP.sub(f"自動集計・{p['date']}更新", block)
        with mock.patch.object(AP, "PAGE", tmp), mock.patch.object(AP, "render_block", side_effect=stamp):
            AP.write_page({"date": "2099-01-02", "same_as": same})
            got = re.search(r'"dateModified":\s*"([^"]*)"', tmp.read_text(encoding="utf-8")).group(1)
            check("中身が同じ回は日付を進めない（日時の形のまま）", got, old)
            AP.write_page({"date": "2099-01-02", "same_as": same + ["https://example.com/new-profile"]})
            got = re.search(r'"dateModified":\s*"([^"]*)"', tmp.read_text(encoding="utf-8")).group(1)
            check("中身が変わった回は新しい日付を時差つきの日時で出す", got, "2099-01-02T00:00:00+09:00")
