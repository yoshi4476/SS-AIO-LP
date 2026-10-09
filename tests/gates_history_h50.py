# -*- coding: utf-8 -*-
"""記事を配信先へ渡すときの変換の門（2026-10-08 のデザイン点検とリード導線の点検）。

CONFLUX（external-md）は先方の scripts/build-journal.mjs（fromPipeline）が Markdown を読み替えて marked で描く。
当社の原稿のまま置くと、score があり author の無い記事で先方の組み立てが RangeError で落ち、「**…。**本文」の ** が
記号のまま出て、定義・注意・相談の箱が素の段落（相談の箱は当社の青）になり、よくある質問の殻と見出しが残り、
結論の枠に説明文が入り、図と写真は Next.js が配らない置き場（リポジトリ直下の images/）で 404 だった。
図の右下には「CONFLUX PARTNERS の記事（セブンセンシズ株式会社）」と当社名が入り、色は AI集客ラボの青だった。
コーポレート・補助金では部品（定義・注意・要約）の CSS が無く素の段落になり、補助金は冒頭で結論・対象読者・時点が
雛形と本文に2回ずつ出て、47本で「…書いています。向けです」と文が壊れていた。まとめのページは h1 と同じ文の h2 が続き、
一覧は黒丸と下線だけ・日付が題にくっつき、コーポレートでは h1 が固定ヘッダーの下に潜っていた。
相談のボタン2本（4か所）が AI集客ラボの /lp/ を指して 404 だった。

先方の変換（marked）はここでは動かせないので、fromPipeline の読み方を写した _from_pipeline で読む
（写しは 2026-10-08 の版。先方が変えたら合わせる）。
"""
import html as _html
import json
import re
import tempfile
from pathlib import Path

from test_gates import check, ROOT, client_ready

SLUG = "h50-journal"
LEAD = "**業務の自動化は、手順の決まった業務を1つ選んで小さく試すと失敗しにくくなります。**画面の数より、決める範囲で費用が動きます。"
BODY = (
    LEAD + "\n\n"
    '<div class="target-reader">この記事は、IT の専任者がいない会社の経営者向けです。まだ何も始めていない方に向けて書いています。</div>\n\n'
    '<p class="freshness">※ 2026年10月時点の情報です。税務の扱いは2026年4月1日現在の法令等にもとづきます。</p>\n\n'
    '<div class="lead-summary"><p class="lst-title">この記事でわかること</p><ul><li>選び方</li><li>**進め方**</li></ul></div>\n\n'
    + "".join(f"## 見出し{i}\n\n**結論{i}は、ここで決まります。**本文{i}です。\n\n本文{i}の2段落目です。\n\n" for i in range(1, 7))
    + '<div class="definition-box"><span class="term">人月とは</span>、1人が1か月で行う作業の量です。</div>\n\n'
    '<div class="caution-box"><span class="box-title">注意: 安さだけで選ぶのはNG</span><br>総額で比べてください。<span class="txt-red">先に払わない</span></div>\n\n'
    "| 工程 | 費用 |\n|:--|:--|\n| 要件定義 | **小さい** |\n\n"
    f"![図](/images/{SLUG}/zu.png)\n\n"
    "作るときに決めていたのは、*進める仕組みと止める仕組み*でした。\n\n"
    '<div class="cta-box"><p>いまの業務をうかがいます。</p><a class="cta-button" href="https://example-journal.test/contact">相談する</a></div>\n\n'
    "## よくある質問\n\n<div class=\"faq\">\n"
    "<details><summary>質問1？</summary><p class=\"faq-a\">答え1です。</p></details>\n"
    "<details><summary>質問2？</summary><p class=\"faq-a\">答え2です。</p></details>\n</div>\n\n"
    "## まとめ\n\n**範囲と総額で見る。**記事の一覧は[一覧](https://example-journal.test/journal/category/development)にあります。\n")
META = {"title": "業務の自動化の進め方", "description": "説明文です。", "slug": SLUG, "keyword": "業務 自動化",
        "category": "development", "date": "2026-10-07", "modified": "2026-10-08", "score": 90,
        "score_breakdown": {"originality": 90}, "diagrams": [{"name": "zu"}],
        "eyecatch": f"/images/{SLUG}/eyecatch.png", "faq": [{"q": "質問1？", "a": "答え1です。"}]}
CFG = {"id": "h50-journal", "type": "external-md", "domain": "example-journal.test", "name": "試験の記事",
       "url_prefix": "/journal", "content_dir": "content/journal", "images_dir": "public/images/journal",
       "categories": {"development": "システム開発"}, "audience": "中小企業の経営者",
       "cta": {"label": "相談する", "url": "https://example-journal.test/contact"},
       "cta_mid": {"label": "料金を見る", "url": "https://example-journal.test/package"},
       "md_dialect": {"name": "journal", "author": "YW（試験）", "forbidden": ["禁止語"]}}


def _strip(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def _from_pipeline(md):
    """先方（CONFLUX）の build-journal.mjs の fromPipeline の読み方の写し（2026-10-08 の版）"""
    def take(text, title):
        m = re.search(r"^##\s*" + title + r"[^\n]*\n([\s\S]*?)(?=^##\s|\Z)", text, re.M)
        return (m.group(1), text.replace(m.group(0), "", 1)) if m else ("", text)
    _, md = take(md, "目次")
    pts, md = take(md, "この記事の要点")
    learn = [_strip(x) for x in re.findall(r"^[-*]\s+(.+)$", pts, re.M) if _strip(x)]
    faq = []

    def det(m):
        faq.append({"q": _strip(m.group(1)), "a": _strip(m.group(2))})
        return ""
    md = re.sub(r"<details>\s*<summary>([\s\S]*?)</summary>\s*<p[^>]*>([\s\S]*?)</p>\s*</details>", det, md)
    md = re.sub(r"^##\s*よくある質問[^\n]*\n\s*(?=^##\s|\Z)", "", md, count=1, flags=re.M)
    _, md = take(md, "(?:出典|参考(?:資料|文献)?)")
    md = re.sub(r"==([^=<>\n]+?)==", r'<strong class="marker">\1</strong>', md)
    answer = []

    def em(m):
        answer.append(_strip(m.group(1)))
        return f'<strong class="marker">{m.group(1)}</strong>'
    md = re.sub(r'<span class="em-marker">([\s\S]*?)</span>', em, md)
    m = re.search(r"^本記事は[^\n]*$", md, re.M)
    lead = m.group(0) if m else ""
    asof = re.search(r"本記事は(.+?時点の情報です)。", lead)
    aud = re.search(r"この記事は、?(.+?向けです)。", lead)
    if asof and aud:
        md = md.replace(lead, "", 1)
    return {"md": md, "answer": answer[0] if answer else "", "asOf": asof.group(1) if asof else "",
            "audience": aud.group(1) if aud else "", "learn": learn, "faq": faq}


class _Patched:
    """publish・sites・video_embed の ROOT と台帳を一時フォルダへ向ける（gates_history_h31 と同じ形）"""

    def __init__(self, root):
        import publish as P
        import sites as S
        import video_embed as V
        self.mods, self.root = (P, S, V), root

    def __enter__(self):
        P, S, V = self.mods
        self.old = (P.ROOT, S.ROOT, V.LEDGER)
        P.ROOT = S.ROOT = self.root
        V.LEDGER = self.root / "data" / "videos.json"
        return P

    def __exit__(self, *a):
        P, S, V = self.mods
        P.ROOT, S.ROOT, V.LEDGER = self.old


def _root(td):
    from PIL import Image
    r = Path(td)
    img = r / "site" / "images" / SLUG
    img.mkdir(parents=True)
    for n in ("eyecatch.png", "zu.png"):
        Image.new("RGB", (8, 8), "white").save(img / n)
    (r / "data").mkdir()
    (r / "data" / "videos.json").write_text("{}", encoding="utf-8")
    return r


def test_journal_md_is_what_the_receiver_reads():
    print("\n■ CONFLUX（external-md）: 先方の変換が読む形で置く（落ちない・** が残らない・先方の部品・図は public 配下）")
    with tempfile.TemporaryDirectory() as td:
        root = _root(td)
        dest = Path(td) / "dest"
        (dest / "public").mkdir(parents=True)
        with _Patched(root) as P:
            P.write_external_md(CFG, dest, dict(META), BODY, root / "x.md")
            md = (dest / "content" / "journal" / f"{SLUG}.md").read_text(encoding="utf-8")
            fm = __import__("yaml").safe_load(md.split("---\n")[1])
            body = md.split("---\n", 2)[2]
            got = _from_pipeline(body)
            # 更新日と狙う語は先方の書き方（modified・keyword）に合わせた（2026-10-08 の結合の確認・gates_history_h55）
            check("先方の「自動化の記事」の条件: score が無く date と author（YW）がある・更新日は modified・狙う語は keyword",
                  ["score" in fm, "score_breakdown" in fm, "diagrams" in fm, "updated" in fm, str(fm.get("date")),
                   str(fm.get("modified")), fm.get("author"), fm.get("keyword")],
                  [False, False, False, False, "2026-10-07", "2026-10-08", "YW（試験）", "業務 自動化"])
            check("結論の枠は本文の冒頭の結論（説明文ではない）・本文の頭に同じ文を残さない",
                  [got["answer"], got["answer"] in _strip(got["md"])],
                  ["業務の自動化は、手順の決まった業務を1つ選んで小さく試すと失敗しにくくなります。", False])
            check("時点と対象読者は「本記事は…。この記事は、…向けです。」の1行で渡し、先方が外す",
                  [got["asOf"], got["audience"], "本記事は" in got["md"]],
                  ["2026年10月時点の情報です", "IT の専任者がいない会社の経営者向けです", False])
            check("対象読者・時点の2文目以降は本文に残す",
                  ["まだ何も始めていない方に向けて書いています。" in got["md"],
                   "税務の扱いは2026年4月1日現在の法令等にもとづきます。" in got["md"]], [True, True])
            check("「この記事でわかること」は ## この記事の要点 の箇条書きで渡す", got["learn"], ["選び方", "進め方"])
            check("よくある質問は先方の質問欄へ（殻と見出しを本文に残さない）",
                  [[f["q"] for f in got["faq"]], "よくある質問" in got["md"], 'class="faq"' in got["md"]],
                  [["質問1？", "質問2？"], False, False])
            bare = re.sub(r"<script\b.*?</script>", "", got["md"], flags=re.S)
            check("** を残さない（marked は「**…。**本文」を太字にしない）", "**" in bare, False)
            check("*強調* は strong（斜体の無い和文で斜めにしない）",
                  "<strong>進める仕組みと止める仕組み</strong>" in got["md"], True)
            classes = sorted({c for cs in re.findall(r'class="([^"]+)"', bare) for c in cs.split()})
            check("部品は先方のもの（box-note・box-warn・cta-inline・table-wrap）だけ",
                  [c for c in classes if c not in ("box-note", "box-warn", "box-title", "cta-inline", "table-wrap", "marker")], [])
            check("定義は box-note（札を「定義」にする data-label。gates_history_h55）、注意は box-warn（「注意:」を外した題）、赤字は太字",
                  ['<div class="box-note" data-label="定義">\n<p><strong>人月とは</strong>' in got["md"],
                   '<p class="box-title">安さだけで選ぶのはNG</p>' in got["md"], "<strong>先に払わない</strong>" in got["md"]],
                  [True, True, True])
            check("相談の箱と中ほどの導線は先方の .cta-inline（当社の青 #1b4fa0 を持ち込まない）",
                  [got["md"].count('class="cta-inline"'), "#1b4fa0" in md, '<a class="cta-inline" href="/contact">' in got["md"]],
                  [2, False, True])
            check("表は先方の横スクロールの枠に入れる", got["md"].count('<div class="table-wrap">'), 1)
            check("自社サイト内のリンクは / から（先方は https のリンクを新しいタブで開く）",
                  "](/journal/category/development)" in got["md"], True)
            check("先方の変換で見出し（H2）が3つ以上残る", len(re.findall(r"^## ", got["md"], re.M)) >= 3, True)
            check("記事・FAQ の構造化データは置かない（先方のページが Article・FAQPage を出す）",
                  "application/ld+json" in md, False)
            check("図は Next.js が配る public/ の下へ置き、本文の参照もそこへ。アイキャッチ（運用会社の名前入り）は届けない",
                  [sorted(p.name for p in (dest / "public" / "images" / "journal" / SLUG).iterdir()),
                   f"](/images/journal/{SLUG}/zu.png)" in md],
                  [["zu.png"], True])
            check("配信の指紋（article-manifest.json）は公開される public/ に置く",
                  P.manifest_path(CFG, dest).relative_to(dest).as_posix(), "public/article-manifest.json")
            # 先方が組み立てを止める形は、書き込む前に止める
            bad = dict(META, title="禁止語を含む題")
            try:
                P.write_external_md(CFG, dest, bad, BODY, root / "x.md")
                stopped = ""
            except SystemExit as e:
                stopped = str(e)
            check("先方が止める語（forbidden）が入った記事は書き込まない", "禁止語" in stopped and "BLOCKED" in stopped, True)
            check("検出器: score が残ると止める", bool(P.journal_problems({"score": 90, "date": "2026-10-07"}, "## a\n## b\n## c\n", {})), True)


def test_journal_config_and_real_articles():
    # CONFLUX の設定・材料は非公開の置き場（2026-10-10 守秘義務）。取れない回は飛ばす（自社の門は回る）
    if not client_ready("conflux"):
        return
    print("\n■ CONFLUX の設定と、いまある記事が先方の変換の条件を満たす形で書き出せること")
    import publish as P
    import sites as S
    cfg = S.load("conflux")
    d = P.md_dialect(cfg)
    check("sites/conflux.json: 方言・著者・止める語・図の置き場（public/）",
          [d.get("name"), "YW" in str(d.get("author")), "原口" in (d.get("forbidden") or []),
           str(cfg.get("images_dir", "")).startswith("public/")], ["journal", True, True, True])
    check("先方に出す場所の無い cta_title を持たない（external-md は記事下の見出しを描かない）", "cta_title" in cfg, False)
    dd = {k: v for k, v in d.items() if k != "forbidden"}      # 語の有無は原稿の中身の問題。ここは変換の形だけを見る
    bad = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        try:
            meta, body = P.parse_article(p)
        except SystemExit:
            continue
        if S.find_category_owner(meta.get("category", "")) != "conflux":
            continue
        fm, md = P.journal_md(cfg, meta, P._md_insert_entries(body, cfg), dd)
        got = _from_pipeline(md)
        probs = P.journal_problems(fm, md, dd) + ([] if got["answer"] else ["結論が取れない"]) + \
            ([] if got["asOf"] and got["audience"] else ["時点・対象読者が取れない"])
        if probs:
            bad.append(f"{p.stem}: {' / '.join(probs)}")
    check("CONFLUX の記事は先方の変換の条件を満たす", bad, [])


def test_inline_markup_survives_commonmark():
    print("\n■ ** と * は配信前に HTML のタグにする（CommonMark は句読点の直後の ** を閉じと見なさない）")
    import publish as P
    check("「**…。**本文」を strong に", P.md_inline_to_html("**結論です。**本文"), "<strong>結論です。</strong>本文")
    check("コード・箇条書きの印は触らない",
          P.md_inline_to_html("`**a**` と\n* 項目\n- **b**"), "`**a**` と\n* 項目\n- <strong>b</strong>")
    check("script の中は触らない", P.md_inline_to_html('<script>{"a":"**x**"}</script>'), '<script>{"a":"**x**"}</script>')


def test_corporate_parts_follow_its_css():
    print("\n■ コーポレート: 部品を記事の CSS（article.css）の名前へ（定義 def-box・注意 note-box・要約 summary-box）")
    import publish as P
    import sites as S
    cfg = S.load("corporate")
    html = P.md2html.convert(
        '<div class="definition-box"><span class="term">記帳とは</span>、取引を帳簿に書くことです。</div>\n\n'
        '<div class="caution-box"><span class="box-title">注意: 月額だけで選ぶのはNG</span><br>総額で比べます。</div>\n\n'
        '<div class="lead-summary"><p class="lst-title">この記事でわかること</p><ul><li>手順</li></ul></div>\n')[0]
    out = P.apply_html_parts(html, cfg)
    check("3つの部品をコーポレートの名前へ", sorted(set(re.findall(r'<div class="([a-z-]+)"', out))),
          ["def-box", "note-box", "summary-box"])
    check("箱の題は strong（.summary-box > strong）。注意の題の後の改行は残す",
          ['<div class="summary-box"><strong>この記事でわかること</strong><ul>' in out,
           "<strong>注意: 月額だけで選ぶのはNG</strong><br>総額" in out], [True, True])
    check("設定の無い社には何もしない", P.apply_html_parts(html, {"id": "x"}), html)


def test_template_intro_is_not_said_twice():
    print("\n■ 補助金（external-html）: 雛形が出す結論・対象読者・時点を本文から外す（2回出ない・文が壊れない）")
    import publish as P
    body = ("**結論の文です。**説明です。\n\n"
            '<div class="target-reader">この記事は、中小企業の経営者向けです。申請の前の方に向けて書いています。</div>\n\n'
            '<p class="freshness">※ 2026年9月時点の情報です。日程は9月1日時点の公表にもとづきます。</p>\n\n'
            "## 見出し\n\n本文です。\n")
    html = P.md2html.convert(body)[0]
    tpl = "<div>{{LEAD_DANGEN}}</div><p>本記事は{{DATE_YM}}時点の情報です。この記事は<b>{{TARGET}}</b>向けです</p>{{BODY}}"
    out, lead, target = P.template_intro(html, tpl, {"audience": ""}, {"description": "説明"})
    check("結論と対象読者（最初の「向けです」の前だけ）", [lead, target], ["結論の文です。説明です。", "中小企業の経営者"])
    check("本文から外し、2文目以降は残す",
          ["結論の文です。" in out, "経営者向けです" in out, "時点の情報です" in out,
           "申請の前の方に向けて書いています。" in out, "日程は9月1日時点の公表にもとづきます。" in out],
          [False, False, False, True, True])
    out2, _, _ = P.template_intro(html, "{{BODY}}", {"audience": ""}, {"description": "説明"})
    check("雛形が出さないもの（先方の template.html に枠が無い）は本文に残す", out2, html)
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("external-html・FTP・ZIP の書き出しが使っている", "template_intro(html, tpl, cfg, meta)" in src, True)


def test_aggregate_pages_have_one_h1_and_styled_lists():
    print("\n■ まとめのページ: h1 は1回・一覧は AI集客ラボの hub-list と同じ見た目・Next.js は固定ヘッダーの下から")
    import aggregate_pages as AP
    import publish as P
    import sites as S
    check("題と同じ文の最初の h2 は外す（h1 は置く側が出す）",
          AP.drop_title_heading('<div class="cat-head"><h2>テーマから探す</h2><span class="cnt">7</span></div>', "テーマから探す"),
          '<div class="cat-head"><span class="cnt">7</span></div>')
    dup = []
    for sid in ("subsidy", "corporate"):
        for p in AP.collect(S.load(sid)):
            m = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", p["html"], re.S)
            if m and _html.unescape(_strip(m.group(1))) == p["title"]:
                dup.append(f"{sid}{p['path']}")
    check("補助金・コーポレートのまとめのページに h1 と同じ文の見出しが無い", dup, [])
    tpl = "<html><head><title>{{TITLE}}</title></head><body><header></header><main>x</main><footer></footer></body></html>"
    page = {"title": "テーマから探す", "description": "d", "html": '<ul class="hub-list"><li>a</li></ul>',
            "jsonld": [], "lang": "ja", "url": "https://x.test/topics/"}
    doc = AP.html_doc(tpl, {"domain": "x.test", "name": "x"}, page)
    check("HTML の社: 一覧の見た目（hub-list・cnt）を同梱し、h1 は1回",
          [".ss-aggregate .hub-list{" in doc, ".ss-aggregate .hub-list li>.cnt" in doc, doc.count("<h1>")], [True, True, 1])
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td)
        (dest / "src" / "app").mkdir(parents=True)
        cfg = {"id": "h50-next", "type": "nextjs-json", "domain": "n.test", "content_dir": "src/content/blog",
               "categories": {}, "trailing_slash": False}
        orig = AP.cached
        AP.cached = lambda c, live, kinds=AP.KINDS: [dict(page, kind="topics", path="/topics/", url="https://n.test/topics")]
        try:
            P.write_aggregate_nextjs(cfg, dest, set())
        finally:
            AP.cached = orig
        comp = (dest / "src" / "components" / "SsAggregatePage.tsx").read_text(encoding="utf-8")
        check("Next.js の社: 上の余白は固定ヘッダーより広く（112px・768px 以上 136px）、パンくずと一覧の見た目を持つ",
              ["padding:112px 20px 80px" in comp, "padding-top:136px" in comp, 'aria-label="パンくずリスト"' in comp,
               "BreadcrumbList" in comp, ".ss-aggregate .hub-list{" in comp, "__CSS__" in comp], [True, True, True, True, True, False])


def test_diagram_credit_and_colors_follow_the_site():
    # CONFLUX の設定・材料は非公開の置き場（2026-10-10 守秘義務）。取れない回は飛ばす（自社の門は回る）
    if not client_ready("conflux"):
        return
    print("\n■ 図: お客様の図の名義はその社の名前だけ・色はサイトの設定（無ければ AI集客ラボの色）")
    import make_diagram as MD
    import sites as S
    conflux, lab = S.load("conflux"), S.load("ai-lab")
    check("名義: お客様は社名だけ（運用会社の名前を出さない）、自社は「（セブンセンシズ株式会社）」つき",
          [MD.credit_text(conflux), "セブンセンシズ" in MD.credit_text(lab)], ["CONFLUX PARTNERS", True])
    check("色: CONFLUX は設定の色（橙・黒鉛）、AI集客ラボは今の色",
          [MD.palette_for(conflux)["accent"], MD.palette_for(conflux)["ink"], MD.palette_for(lab) == MD.PALETTE],
          [(0xC2, 0x41, 0x0C), (0x0E, 0x0F, 0x12), True])
    got = {}
    real = (MD.site_for_slug, MD.save_png, MD.credit)
    try:
        MD.site_for_slug = lambda slug: conflux
        MD.save_png = lambda img, slug, name: got.setdefault("img", img)
        MD.credit = lambda d, h, text="", pal=MD.PALETTE: got.setdefault("credit", text) and real[2](d, h, text, pal)
        MD.draw_list("zz-h50", "x", "題", ["一", "二", "三"])
    except SystemExit:
        print("  WARN  日本語フォントが無いため、図の描画は確かめられません")
        return
    finally:
        MD.site_for_slug, MD.save_png, MD.credit = real
    # 図は論理の座標の SCALE 倍で書き出す（gates_history_h57）。題の印は論理の (46, 56) にある
    s = getattr(MD, "SCALE", 1)
    check("描いた図: 題の印の色と地の色が CONFLUX の色・名義に当社名が無い",
          [got["img"].getpixel((46 * s, 56 * s)), got["img"].getpixel((5, 5)), "セブンセンシズ" in got["credit"]],
          [(0xC2, 0x41, 0x0C), (0xF4, 0xF4, 0xF1), False])


def test_links_never_point_to_another_sites_paths():
    print("\n■ 相談のボタン: AI集客ラボの /lp/ を、ほかの社の記事に入れない（404）")
    import cta_fill
    import publish as P
    import sites as S
    corp = S.load("corporate")
    check("検出器: 作業コピーの無い方式でも AI集客ラボの入口（/lp/）を拾う",
          P.foreign_links(corp, '<a class="cta-button" href="/lp/">相談</a> [x](/blog/a/)'), ["/lp/"])
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td)
        (dest / "src" / "app" / "blog").mkdir(parents=True)
        (dest / "src" / "app" / "[locale]" / "contact").mkdir(parents=True)
        check("検出器: 配信先に在る経路（app・動的な階層の下）は通し、無い経路を拾う",
              P.foreign_links({"id": "h50", "type": "nextjs-json", "url_prefix": "/blog"},
                              "[a](/blog/x/) [b](/contact) [c](/lp/) [d](/#contact) ![e](/images/s/a.png)", dest),
              ["/lp/"])
    bad = []
    for p in sorted((ROOT / "articles").glob("*.md")):
        try:
            meta, body = P.parse_article(p)
        except SystemExit:
            continue
        sid = S.find_category_owner(meta.get("category", ""))
        if sid and S.load(sid).get("type") != "self-static" and P.foreign_links(S.load(sid), body):
            bad.append(p.stem)
    check("AI集客ラボ以外の原稿に、AI集客ラボにしか無い場所へのリンクが無い", bad, [])
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("配信の入口（main）が止める（作業コピーの無い方式と、Git の社の両方）",
          [len(re.findall(r"^\s+stop_foreign_links\(cfg, meta, body", src, re.M)),
           "stop_foreign_links(cfg, meta, body, dest)" in src], [2, True])
    real_load = S.load_all
    try:
        S.load_all = lambda: {"h50x": {"id": "h50x", "type": "external-html", "domain": "h50.test"}}
        block = cta_fill.cta_html("h50x")
    finally:
        S.load_all = real_load
    check("CTA の補充: 相談先の無い社に AI集客ラボの /lp/ を入れない", ["/lp/" in block, 'href="https://h50.test/"' in block],
          [False, True])


def test_app_router_files_are_not_shadowed():
    print("\n■ Next.js の app/llms.txt/route.ts がある社に、public/llms.txt を置かない（同じ URL を取り合う）")
    import site_files as SF
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td)
        (dest / "src" / "app" / "llms.txt").mkdir(parents=True)
        (dest / "src" / "app" / "llms.txt" / "route.ts").write_text("export const GET = () => new Response('')\n",
                                                                     encoding="utf-8")
        (dest / "public").mkdir()
        check("生成コードとして見分ける", SF.generated(dest, "llms"), True)
        placed = SF.ensure({"id": "h50", "type": "external-md", "domain": "x.test", "name": "x"}, dest, write=False)
        check("llms.txt を置かない", [p.name for p in placed if p.name == "llms.txt"], [])


def test_client_supervisor_is_the_client():
    # CONFLUX の設定・材料は非公開の置き場（2026-10-10 守秘義務）。取れない回は飛ばす（自社の門は回る）
    if not client_ready("conflux"):
        return
    print("\n■ 監修: CONFLUX の記事の監修者は先方（YW）。当社の代表を出さない・「なし（…）」を資格にしない")
    import editorial_review as ER
    import publish as P
    import sites as S
    cr = P.client_credit(S.load("conflux"))
    check("監修の表示と構造化データ（YW・資格の欄に「なし」を入れない）",
          [cr["reviewer"]["name"], "hasCredential" in cr["reviewer"], "なし" in cr["byline"], "原口" in json.dumps(cr, ensure_ascii=False)],
          ["YW", False, False, False])
    slugs = [p.stem for p in sorted((ROOT / "articles").glob("*.md"))
             if S.find_category_owner((re.search(r"^category:\s*(\S+)", p.read_text(encoding="utf-8")[:3000], re.M)
                                       or [None, ""])[1]) == "conflux"]
    if not slugs:
        print("  --  CONFLUX の記事が無いため、承認の記録の名義は確かめません")
        return
    # 2026-10-08 運用者の決定: 自動化の記事の監修は「YW（CONFLUX PARTNERS）」と「セブンセンシズ株式会社」の両方（gates_history_h55）
    check("承認の記録の名義は先方の監修の表示と同じ並び（代表者の実名は入れない）",
          [ER.reviewer_for(slugs[0]), "原口" in ER.reviewer_for(slugs[0])],
          ["・".join(S.load("conflux")["review_by"]), False])
