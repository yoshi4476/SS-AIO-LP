# -*- coding: utf-8 -*-
"""記事の最初の章に「その場の入口」を1つだけ置く門（2026-10-05）。

9/5〜10/2 の3サイト合計で、記事の訪問261に対しボタンの押下3・問い合わせ0だった。記事のボタンは別ページへの
誘導だけだったので、最初の見出しの1文結論の後に URL の入力欄（AI集客ラボ）・診断への入口（補助金）を置いた。
固定すること: 最初の章に1つだけ／送り先が実在し URL を受けて自動で始まる／計測の名前が記事・ツール・集計でそろう／
補助金の診断は結果の前にお名前とメールを求めるので「登録不要」と書かない／料金や結果の約束を書かない。
"""
import json
import re

from test_gates import check, ROOT

BODY = ('<p>冒頭の断言です。</p>\n'
        '<h2 id="a">AIOとは？</h2>\n<p>AIOは、AIの回答に引用されるための対策です。</p>\n<p>本文1。</p>\n'
        '<h2 id="b">やり方</h2>\n<p>結論2。</p>\n<h2 id="c">費用</h2>\n<p>結論3。</p>\n'
        '<h2 id="d">注意点</h2>\n<p>結論4。</p>\n<h2 id="e">よくある質問</h2>\n<p>Q</p>\n')
META = {"category": "aio", "slug": "sample", "title": "AIO対策のやり方", "keyword": "aio 対策"}


def _sections(html):
    heads = [m.start() for m in re.finditer(r"<h2[ >]", html)]
    return [html[a:b] for a, b in zip(heads, heads[1:] + [len(html)])]


def test_inline_tool_sits_once_in_the_first_section():
    import build
    print("\n■ 記事の入力欄: 最初の章の1文結論の後に1つだけ")
    out = build.insert_inline_tool(BODY, META)
    secs = _sections(out)
    check("入力欄は記事に1つだけ", out.count('class="inline-tool"'), 1)
    check("最初の章の中にある", 'class="inline-tool"' in secs[0], True)
    check("最初の段落（1文結論）の直後", re.search(r"</h2>\s*<p>AIOは[^<]*</p>\s*<aside class=\"inline-tool\"", out) is not None, True)
    check("2回通しても増えない", build.insert_inline_tool(out, META).count('class="inline-tool"'), 1)
    full = build.insert_mid_cta(out, META)
    check("途中の診断（3つ目の見出しの手前）とは別の章", 'class="inline-tool"' in _sections(full)[1], False)
    check("最初の章がまとめなら置かない",
          build.insert_inline_tool('<h2>まとめ</h2>\n<p>x</p>\n<h2>b</h2>', META).count("inline-tool"), 0)
    check("見出しの直後が段落でなければ置かない",
          build.insert_inline_tool('<h2>a</h2>\n<div class="table-wrap"></div>\n<h2>b</h2>', META).count("inline-tool"), 0)
    kuchi = '<h2>口コミ返信のコツ</h2>\n<p>結論。</p>\n<aside class="scan-box tool-box"></aside>\n<h2>b</h2>'
    check("最初の章に口コミ返信ツールの案内があれば重ねない", build.insert_inline_tool(kuchi, META).count("inline-tool"), 0)
    import render_check
    check("描画の崩れが無い", render_check.problems(build.inline_tool(META)), [])


def test_inline_tool_wording_and_destination():
    import build
    print("\n■ 記事の入力欄: 文言と送り先")
    t = build.INLINE_TOOL
    check("見出しはツールが確かめる範囲を超えない（読まれているか）", t["head"], "御社のサイト、ChatGPTやGoogleのAIに読まれていますか？")
    check("補足は何を確かめるかを書く", t["sub"], "URLを入れると、AIのクローラーが入れるか・内容を読めるかを無料で確かめられます（登録不要）")
    h = build.inline_tool(META)
    check("入力は type=url・placeholder は https://", ('type="url"' in h, 'placeholder="https://"' in h), (True, True))
    check("ボタンは「確かめる」", ">確かめる</button>" in h, True)
    check("記事のパスをツールへ渡す", 'name="from" value="/aio/sample/"' in h, True)
    page = ROOT / "site" / t["path"].strip("/") / "index.html"
    check("送り先のツールが実在する", page.is_file(), True)
    src = page.read_text(encoding="utf-8")
    check("ツールは ?url= を受けて自動で測る", ('qs.get("url")' in src, "requestSubmit" in src), (True, True))
    check("URL だけで動く（メール・社名の入力欄が無い）", re.search(r'type="email"|name="company"', src) is None, True)
    words = t["head"] + t["sub"] + t["button"]
    check("料金・結果の約束を書かない", re.search(r"円|％|%|必ず|すぐ|確実|保証", words), None)


def test_inline_tool_events_line_up():
    import funnel
    print("\n■ 記事の入力欄: 計測の名前が記事・ツール・集計でそろう")
    js = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    tool = (ROOT / "site" / "tools" / "url-check" / "index.html").read_text(encoding="utf-8")
    names = [n for _, n in funnel.INLINE_STEPS]
    check("記事の側（site.js）", [n for n in names[:3] if f"'{n}'" in js], names[:3])
    check("ツールの側（URL診断）", [n for n in names[3:] if f'"{n}"' in tool], names[3:])
    check("記事のパスとツールを値に付ける", ("page_path: location.pathname" in js and "data-tool" in js), True)
    rec = json.loads((ROOT / "data" / "inline_tool.json").read_text(encoding="utf-8"))
    check("置いた日を記録している", bool(rec["sites"]["ai-lab"]["since"]), True)
    from datetime import date, timedelta
    since = (date.today() - timedelta(days=10)).isoformat()

    def rows(prop, a, b, ns):
        aft = a.isoformat() >= since
        return [("page_view", "/aio/x/", 100), ("page_view", "/tools/url-check/", 50),
                ("cta_click", "/aio/x/", 3)] + ([("inline_tool_submit", "/aio/x/", 4),
                                                ("inline_tool_result", "/tools/url-check/", 3)] if aft else [])
    res, n = funnel.inline_compare("ai-lab", "0", since, rows_fn=rows)
    got = {label: (b, a) for label, b, a in res}
    check("記事の訪問はツールのページを数えない", got["記事の訪問"], (100, 100))
    check("ツールの結果はツールのページで数える", got["ツールの結果を見た"], (0, 3))
    check("後ろは経過した日数だけ", n, 10)


def test_subsidy_entry_tells_the_truth():
    import publish
    print("\n■ 補助金サイト: 既存の診断（トップの8問）への入口")
    cfg = json.loads((ROOT / "sites" / "subsidy.json").read_text(encoding="utf-8"))
    ent = cfg["cta_inline"]
    check("送り先はトップの補助金適性診断", ent["url"], "https://lp.7senses.co.jp/?diag=hojokin#diagnosis")
    words = ent["head"] + ent.get("note", "") + ent.get("label", "")
    check("結果の前にお名前とメールが要るので「登録不要」と書かない", "登録不要" in words, False)
    check("料金・採択・結果の約束を書かない", re.search(r"円|採択率|必ず|すぐ|確実|保証", words), None)
    out = publish.insert_inline_entry(BODY, cfg)
    check("最初の章に1つだけ", (out.count('class="cta-inline"'), 'class="cta-inline"' in _sections(out)[0]), (1, True))
    check("2回通しても増えない", publish.insert_inline_entry(out, cfg).count('class="cta-inline"'), 1)
    check("見えた・押したを記事のパスつきで送る", ("inline_tool_view" in out and "inline_tool_submit" in out
                                              and "page_path:location.pathname" in out), True)
    other = json.loads((ROOT / "sites" / "corporate.json").read_text(encoding="utf-8"))
    check("設定の無い社には置かない", publish.insert_inline_entry(BODY, other), BODY)
