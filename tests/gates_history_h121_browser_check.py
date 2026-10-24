# -*- coding: utf-8 -*-
"""ブラウザでの表示確認（scripts/browser_check.py）の門。2026-10-20 運用者の指示「ブラウザでの表示確認の拡張」。

HTML を読む検査では、スマホ幅の横のはみ出し・JavaScript のエラー・読み込めない画像・画面に残った Markdown の
記法が分からない。本物のブラウザで開く検査を週次に足したので、
1. 検出器が崩れたページで4種類とも拾い、HTTP 404 も拾うこと
2. 崩れていないページ（横に流せる箱の中の広い表・コードの中の ** ・読める画像）では何も拾わないこと
3. 週次で Chromium を入れる手順があり、findings.py が BROWSER の印で判定すること
を確かめる。ネットには出ない（手元に立てたサーバーだけを開く）。
"""
import base64
import http.server
import re
import sys
import tempfile
import threading
from functools import partial
from pathlib import Path

import yaml

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

# 1x1 の PNG（読める画像）
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

BAD = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0"><main>
<p>これは **太字のつもり** の残りです</p>
<p>詳しくは [料金の記事](/aio/ryokin/) をご覧ください</p>
<p>| 項目 | 内容 |</p>
<div class="wide-box hero" style="width:900px;height:20px;background:#eee">広い箱</div>
<img src="/missing.png" alt="欠け">
</main>
<script>throw new Error("boom-from-test")</script>
</body></html>"""

CLEAN = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0"><main>
<p>コードの中の <code>**太字**</code> と <code>[a](/b/)</code> は記法の説明なので数えません</p>
<pre>| 項目 | 内容 |</pre>
<p>全角の区切り ｜ は表ではありません</p>
<div class="table-wrap" style="overflow-x:auto"><table style="width:900px"><tr><td>広い表</td></tr></table></div>
<nav style="position:fixed;top:0;left:100%;width:300px">画面の外に隠したメニュー</nav>
<img src="/ok.png" alt="読める画像" loading="lazy" width="10" height="10">
</main></body></html>"""


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def guess_type(self, path):
        # Windows の Python は初めての判定でレジストリを読み、手元で17.8秒かかる（gates_history_a.SERVE_TYPES と同じ理由）
        from gates_history_a import SERVE_TYPES
        return SERVE_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def _serve(root):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(_Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_browser_check_detects_and_stays_quiet():
    print("\n■ ブラウザでの表示確認: 崩れたページで5種類を拾い、崩れていないページでは何も拾わない")
    import browser_check as B
    check("Markdown の記法の判定: ** ・](/ ・行頭の表の | を拾う",
          sorted(k for k, _ in B.markdown_left(["a **b** c", "x [y](/z/)", "| a | b |"])), ["**", "](/", "|"])
    check("Markdown の記法の判定: 全角の ｜・文中の | 1本は拾わない",
          B.markdown_left(["題｜副題", "A | B は比べる"]), [])
    check("第三者のドメインの判定（自社の別のサブドメインは自社）",
          (B.third_party("https://www.googletagmanager.com/gtag/js", "ai.7senses.co.jp"),
           B.third_party("https://corp.7senses.co.jp/x.js", "ai.7senses.co.jp"), B.third_party("", "ai.7senses.co.jp")),
          (True, False, False))
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
    except Exception as e:      # ブラウザの無い CI では測れない（週次は入れてから動かす）
        print(f"  SKIP  chromium が使えないため描画の検査を飛ばす: {str(e)[:80]}")
        return
    tmp = Path(tempfile.mkdtemp())
    (tmp / "bad.html").write_text(BAD, encoding="utf-8")
    (tmp / "clean.html").write_text(CLEAN, encoding="utf-8")
    (tmp / "ok.png").write_bytes(PNG)
    srv = _serve(tmp)
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    try:
        ctx = browser.new_context(user_agent=B.UA)
        bad, why = B.open_and_inspect(ctx, base + "/bad.html", "テスト")
        check("崩れたページは開けた", why, None)
        text = "\n".join(bad)
        check("拾う: JavaScript のエラー（捕まえていない例外）", "boom-from-test" in text, True)
        check("拾う: console の error（自社のドメインの 404 の画像）",
              any("JavaScript のエラー" in x and "404" in x for x in bad), True)
        check("拾う: スマホ幅の横のはみ出しと、原因の要素（div.wide-box.hero）",
              any("スマホ幅で横にはみ出し" in x and "div.wide-box.hero 900px" in x for x in bad), True)
        check("拾う: 読み込めない画像", any("読み込めない画像 1枚" in x and "missing.png" in x for x in bad), True)
        check("拾う: 画面に残った Markdown の記法 3種類",
              sorted(re.findall(r"記法 (\S+) が残って", text)), ["**", "](/", "|"])
        check("PC幅（1440px）では 900px の箱ははみ出さない", any("PC幅で横にはみ出し" in x for x in bad), False)
        clean, why = B.open_and_inspect(ctx, base + "/clean.html", "テスト")
        check("崩れていないページでは何も拾わない（横に流せる箱・コードの中・固定の部品・遅れて読む画像）",
              (clean, why), ([], None))
        gone, why = B.open_and_inspect(ctx, base + "/nothing-here/", "テスト")
        check("拾う: ページが HTTP 404", any("HTTP 404" in x for x in gone), True)
        down, why = B.open_and_inspect(ctx, "http://127.0.0.1:9/", "テスト")
        check("つながらないページは問題ではなく「読めなかった」（unknown の材料）", (down, why is not None), ([], True))
        ctx.close()
    finally:
        srv.shutdown()
        browser.close()
        pw.stop()


def test_browser_check_is_wired_weekly():
    print("\n■ ブラウザでの表示確認: 週次で Chromium を入れ、findings.py が BROWSER の印で判定する")
    src = (ROOT / "scripts" / "browser_check.py").read_text(encoding="utf-8")
    check("印は BROWSER_OK=yes|no|unknown・見つかっても0で終わる",
          all(f'print("BROWSER_OK={v}")' in src for v in ("yes", "no", "unknown")), True)
    check("自社のサイトだけを開く（own_ids と is_client で外す）", ("own_ids()" in src, "is_client(sid)" in src), (True, True))
    check("1回に開く上限がある", "MAX_LOADS = 25" in src, True)
    import findings as F
    reg = [(label, s) for label, s, _ in F.CHECKS if s.split()[0] == "browser_check.py"]
    check("findings.py の CHECKS に登録されている", len(reg), 1)
    check("findings は BROWSER_OK の値で判定する（no は要対応・unknown は動かせず）",
          (F.judge("BROWSER_OK=no", 0), F.judge("BROWSER_OK=unknown", 0), F.judge("BROWSER_OK=yes", 0)),
          ("要対応", "動かせず", "問題なし"))
    pat = next(p for _, s, p in F.CHECKS if s.split()[0] == "browser_check.py")
    check("明細は「要対応:」の行を拾う",
          F.details("要対応: ブラウザ表示 ai-lab 記事 x\n  読めなかったページ: y", pat), ["要対応: ブラウザ表示 ai-lab 記事 x"])
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "weekly-optimize.yml").read_text(encoding="utf-8"))
    steps = wf["jobs"]["optimize"]["steps"]
    names = [s.get("name") for s in steps]
    i_inst = next((i for i, n in enumerate(names) if n and "Chromium" in n), -1)
    i_meas = names.index("実測（速度・インデックス・表記ゆれ・AI引用）と残枠")
    i_find = names.index("見つかったものを集めて知らせる")
    check("optimize に Chromium を入れる手順があり、実測の後・findings の前",
          i_meas < i_inst < i_find, True)
    run = steps[i_inst].get("run", "")
    check("入れ方は月次と同じ（playwright install --with-deps chromium）・失敗しても週次は止めない",
          ("python -m playwright install --with-deps chromium" in run, "|| " in run), (True, True))
