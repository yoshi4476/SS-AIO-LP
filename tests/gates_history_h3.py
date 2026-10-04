# -*- coding: utf-8 -*-
"""AIクローラーの robots.txt 読みと、画像の崩れの検出器の門（2026-10-04）。

どちらも「見つけるはずのものを見つけ、隣のものを誤って拾わない」ことを、作った見本で確かめる。
検出器が黙って何も見つけなくなると、塞がったサイトや崩れた図がそのまま公開される。
"""
import tempfile
from pathlib import Path

from test_gates import check


def test_robots_parser_reads_blocks_like_google():
    import ai_crawler_check as C

    blocked = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    check("GPTBot に Disallow: / があれば塞がっている", C.robots_allows(blocked, "GPTBot"), False)
    check("名前の無い ClaudeBot は * のグループに従う", C.robots_allows(blocked, "ClaudeBot"), True)
    check("名前は大文字小文字を区別しない", C.robots_allows(blocked, "gptbot"), False)

    check("Allow: / だけなら通る", C.robots_allows("User-agent: GPTBot\nAllow: /\n", "GPTBot"), True)
    check("空の Disallow は何も塞がない",
          C.robots_allows("User-agent: *\nDisallow:\n", "Googlebot"), True)
    check("robots.txt が空なら通る", C.robots_allows("", "Googlebot"), True)

    wild = "User-agent: *\nDisallow: /\n"
    check("* に Disallow: / があれば名前の無いクローラーは全部塞がる",
          [C.robots_allows(wild, a) for a in ("GPTBot", "Googlebot", "Google-Extended")],
          [False, False, False])
    # 名前の一致するグループがあれば * は見ない（Google の解釈）
    check("自分のグループがあれば * の Disallow は効かない",
          C.robots_allows("User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nAllow: /\n", "Googlebot"), True)
    # 連続した User-agent は1つのグループ
    grp = "User-agent: GPTBot\nUser-agent: ClaudeBot\nDisallow: /\n"
    check("連続した User-agent 行は同じ規則を共有する",
          [C.robots_allows(grp, "GPTBot"), C.robots_allows(grp, "ClaudeBot"), C.robots_allows(grp, "Bingbot")],
          [False, False, True])
    # 長く当たる規則が勝つ・同じ長さなら Allow
    check("トップ以外だけ塞いだ場合、トップは通る",
          C.robots_allows("User-agent: *\nDisallow: /*\nAllow: /$\n", "GPTBot", "/"), True)
    check("ワイルドカードの Disallow は記事に効く",
          C.robots_allows("User-agent: *\nDisallow: /*\nAllow: /$\n", "GPTBot", "/aio/x/"), False)
    check("一部のフォルダだけ塞いでもトップは通る",
          C.robots_allows("User-agent: GPTBot\nDisallow: /private/\n", "GPTBot", "/"), True)
    check("同じグループ名が2か所にあれば規則をまとめる",
          C.robots_allows("User-agent: GPTBot\nAllow: /a/\n\nUser-agent: GPTBot\nDisallow: /\n", "GPTBot"), False)
    check("コメントは読み飛ばす",
          C.robots_allows("User-agent: GPTBot # 学習\nDisallow: / # 全部\n", "GPTBot"), False)
    check("検査の対象に Google-Extended と Googlebot が入っている",
          {"Google-Extended", "Googlebot"} <= set(C.ROBOTS_AGENTS), True)


def test_image_check_finds_broken_diagrams():
    import image_check as I

    ok_list = {"name": "a", "type": "list", "title": "申請前に確かめる3つのこと",
               "items": ["GビズIDを取る", "見積書を2社分そろえる", "締切を確かめる"]}
    check("収まる list は何も出さない", I.diagram_problems(ok_list), [])

    long_item = "あ" * 80
    got = I.diagram_problems({"name": "b", "type": "list", "title": "題",
                              "items": [long_item, "い", "う"]})
    check("最小の文字でも収まらない list の項目を拾う", any("はみ出します" in s for s in got), True)

    pipe = I.diagram_problems({"name": "c", "type": "list", "title": "題",
                               "items": ["ラベル|説明", "い", "う"]})
    check("list の「|」は注意として拾う（崩れには数えない）",
          [s.startswith(I.NOTE) for s in pipe], [True])

    check("list の項目が7個なら切られると知らせる",
          any("3〜6項目" in s for s in I.diagram_problems(
              {"name": "d", "type": "list", "title": "題", "items": list("あいうえおかき")})), True)
    check("flow の項目が6個なら切られると知らせる",
          any("2〜5項目" in s for s in I.diagram_problems(
              {"name": "e", "type": "flow", "title": "題", "items": list("あいうえおか")})), True)

    flow_ok = {"name": "f", "type": "flow", "title": "4つの手順",
               "items": ["準備する|書類をそろえる", "申請する", "審査を待つ", "報告する"]}
    check("収まる flow は何も出さない", I.diagram_problems(flow_ok), [])
    flow_ng = {"name": "g", "type": "flow", "title": "題", "items": ["あ" * 120] + ["い"] * 4}
    check("折り返しが箱の下まで届く flow を拾う",
          any("折り返され" in s for s in I.diagram_problems(flow_ng)), True)

    vs_ng = {"name": "h", "type": "vs", "title": "題",
             "items": ["NG|" + "あ" * 40, "OK|短い"]}
    check("vs の行が枠の端を越えるのを拾う",
          any("行が長すぎて" in s for s in I.diagram_problems(vs_ng)), True)
    check("vs の形が「見出し|行」でなければ拾う",
          any("見出し|行1" in s for s in I.diagram_problems(
              {"name": "i", "type": "vs", "title": "題", "items": ["NG", "OK|よい"]})), True)

    # 英語: 英字だけの段で、許可外の4文字以上の語があるときだけ
    check("英語だけの段を拾う", I.english_only("Step|準備"), ["Step"])
    check("日本語と混ざった段は拾わない", I.english_only("Googleで調べる"), [])
    check("許可した略語は拾わない", I.english_only("AIO|SEO|LLMO|GBP|URL"), [])
    check("3文字以下は拾わない", I.english_only("NG|OK|FAQ"), [])
    check("製品名は拾わない", I.english_only("Instagram|ChatGPT"), [])
    check("段をまたいだ名前（SECURITY|ACTION）は拾わない",
          I.english_only("GビズIDと|SECURITY|ACTIONの準備"), [])
    check("名前の片方だけ（SECURITY 単独）は拾う", I.english_only("SECURITY"), ["SECURITY"])
    check("図解の題の英語も拾う",
          any("英語だけ" in s for s in I.diagram_problems(
              {"name": "j", "type": "list", "title": "Checklist", "items": ["あ", "い", "う"]})), True)

    check("収まる題のアイキャッチは何も出さない", I.eyecatch_problems("補助金の申請で失敗しない5つの準備"), [])

    # 欠け: フロントマターにあるのにファイルが無いもの
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "images" / "s").mkdir(parents=True)
        (root / "images" / "s" / "a.png").write_bytes(b"x")
        meta = {"title": "題", "eyecatch": "/images/s/eyecatch.png",
                "diagrams": [ok_list, dict(ok_list, name="zz")]}
        got = I.article_problems(meta, "s", site_root=root)
        check("無いアイキャッチと図解だけを欠けとして拾う",
              sorted(s for s in got if "画像がありません" in s),
              ["画像がありません: /images/s/eyecatch.png", "画像がありません: /images/s/zz.png"])
