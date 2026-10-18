# -*- coding: utf-8 -*-
"""AI集客ラボの見た目とリード導線（2026-10-08 のデザイン点検・リード導線の点検）。

見つかったこと（どれも記事146本・全ページに効いていた）:
  - スマホで記事の答えより先に、目次・「無料相談を見てみる」・「AI導入補助金で最大350万円」が積まれ、本文の最初の段落が 2,083px 下
  - /lp/ のヒーローのリンクが墨色のまま紺の写真の上（1.6〜1.9:1）。紺の写真・金と墨の明朝体・青いボタンの3つの見た目が混在
  - /lp/#service（243本）・#price・#diagnosis の行き先の目印が無く、LP の一番上に着いていた
  - LP の下の固定の帯が最初の画面から出てヒーローのボタンに重なり、フォームの入力中も出たまま
  - Windows では本文が細い Regular（"Yu Gothic" の既定）
  - 日付 11.84px・タグ 10.24px・調査の質問集の答え 12.48px 灰色・著者欄 12〜13px
  - スマホの固定のヘッダー 111px（ツールの帯 40px つき）＋記事の下の帯 83px で画面の約1/4
  - 黄色のマーカーが文字の下42%に太く、1本に33か所。<button class="btn"> にブラウザ既定の黒枠と 13.33px の文字
  - パンくずの「ホーム」だけ約10px下・一覧の見出しの上に約100pxの空き・共有ボタンが2段
  - 比較表・テーマのページに英字の飾り「ALL ARTICLES」。業種ハブ・比較表・用語集・運営者の段落が1行70〜91字
  - コピーライト 4.39:1・タグ 3.32〜4.49:1。一覧で文字入りのテーマ画像の使い回し（「AIO対策の始め方」が12回）
  - 資料ダウンロードの後が「2営業日以内に担当者よりご連絡」。項目数が「34項目」と「約25項目」に分かれていた
  - data-cta の無いボタンの名前が文言から作られ305本が同じ「AI」。本文の文字リンクの入口は押されても送られない
  - 問い合わせ（パソコン）でフォームの右が空き、運営者の「お客様の声」が中央揃えの12px台
  - 業種のよくある質問の入口が全業種向けの /lp/ だけ。業種ハブの診断・チェックリストは季節の特集のときだけ。業種LPの相談で業種が消える
"""
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

CSS = ROOT / "site" / "css"
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _css(name="style.css"):
    return (CSS / name).read_text(encoding="utf-8")


def _rules(css):
    """（セレクタの組, 宣言の本文）を出現順に。@media の中の規則も拾う"""
    for m in RULE.finditer(re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        sels = [re.sub(r"\s+", " ", s).strip() for s in m.group(1).split(",")]
        yield sels, m.group(2)


def _decl(css, selector, prop):
    """selector に最後に当たった prop の値（同じ詳細度なら後勝ち）"""
    got = None
    for sels, body in _rules(css):
        if selector in sels:
            for d in body.split(";"):
                k, _, v = d.partition(":")
                if k.strip() == prop:
                    got = v.strip()
    return got


def _base(css):
    """@media の塊を除いた、どの幅でも効く規則だけ"""
    out, i = [], 0
    for m in re.finditer(r"@media[^{]*\{", css):
        if m.start() < i:
            continue
        out.append(css[i:m.start()])
        k, depth = m.end(), 1
        while depth and k < len(css):
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        i = k
    return "".join(out) + css[i:]


def _px(v):
    m = re.match(r"([\d.]+)(rem|px)", v or "")
    return round(float(m.group(1)) * (16 if m.group(2) == "rem" else 1), 2) if m else 0


def _media(css, query):
    """@media (query) { … } の中身（同じ条件の塊をすべてつなぐ）"""
    out, i = [], 0
    while True:
        j = css.find(f"@media {query}", i)
        if j < 0:
            return "".join(out)
        k, depth = css.index("{", j) + 1, 1
        start = k
        while depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        out.append(css[start:k - 1])
        i = k


def _hex(c):
    c = c.lstrip("#")
    return [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def _mix(a, b, pa):
    """color-mix(in srgb, a pa, b)"""
    return [x * pa + y * (1 - pa) for x, y in zip(a, b)]


def _contrast(fg, bg):
    def lum(c):
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def test_h51_article_answer_comes_before_the_side_column_on_phones():
    import build as B
    css = _css()
    one_col = _media(css, "(max-width: 1099.98px)")
    check("記事（1列）: 横の欄の箱を外し、中身を本文と同じ列に並べる",
          (_decl(one_col, ".article-side", "display"), _decl(one_col, ".article-side .side-sticky", "display")),
          ("contents", "contents"))
    check("記事（1列）: 相談と補助金の案内は本文の後ろ、目次は本文の前",
          (_decl(one_col, ".article-side .side-cta", "order"), _decl(one_col, ".article-side .side-banner", "order"),
           _decl(one_col, ".article-side .toc", "order")), ("1", "1", "-1"))
    toc = B.render_toc([{"id": "a", "name": "見出し1"}, {"id": "b", "name": "見出し2"}])
    check("目次は開閉できる形で、最初は閉じている（パソコンだけ直後の処理で開く）",
          ("<details>" in toc, "<details open" in toc, 'matchMedia("(min-width: 1100px)")' in toc), (True, False, True))


def test_h51_lp_is_blue_white_and_its_links_are_visible():
    lp = _css("lp.css")
    check("LP: 墨・金・明朝の上書きが無い", [w for w in ("Shippori", "--gold", "#23201a", "#96751a", "counter(chapter")
                                           if w in lp], [])
    check("LP: 全体のリンクを墨色にする指定が無い（ヒーローの白いリンクに勝っていた）",
          [s for sels, _ in _rules(lp) for s in sels if s == "body.lp-doc a"], [])
    check("LP: ヒーローの上の文字リンクは白", _decl(lp, "body.lp-doc .lx-hero a:not(.btn)", "color"), "#fff")
    v2 = _css("lp-v2.css")
    alpha = re.search(r"rgba\(255, ?255, ?255, ?\.(\d+)\)", _decl(v2, ".lx-item .pt", "color") or "")
    check("LP: 14項目の点数は白75%以上（50%で 2.55:1）", bool(alpha) and int(alpha.group(1).ljust(2, "0")) >= 75, True)
    check("LP: 入力欄の外の案内も覆いの上に出す", _decl(v2, ".lx-hero > p", "z-index"), "2")
    check("style.css に LP の金の飾りが残っていない", "var(--gold)" in _css(), False)
    page = (ROOT / "site" / "lp" / "index.html").read_text(encoding="utf-8")
    check("LP: 紺の足元には白いロゴ", 'class="footer-logo" src="/images/company/logo-white.png"' in page, True)


def test_h51_lp_anchor_targets_exist():
    page = (ROOT / "site" / "lp" / "index.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'\sid="([\w-]+)"', page))
    srcs = [ROOT / "templates" / "article.html", ROOT / "site" / "index.html", ROOT / "site" / "lp" / "index.html",
            ROOT / "site" / "contact" / "index.html", ROOT / "site" / "download" / "index.html",
            ROOT / "site" / "thanks" / "index.html"] + sorted((ROOT / "scripts").glob("*.py"))
    want = set()
    for p in srcs:
        if p.is_file():
            want |= set(re.findall(r'/lp/(?:\?[^"\'#\s<>]*)?#([A-Za-z][\w-]*)', p.read_text(encoding="utf-8", errors="ignore")))
    check("/lp/#… の行き先がすべて LP にある（service・price・diagnosis が無く、一番上に着いていた）",
          sorted(want - ids), [])
    check("行き先が固定のヘッダーの下に潜らない", _px(_decl(_base(_css()), "html", "scroll-padding-top")) >= 72, True)


def test_h51_fixed_bars_step_aside():
    js = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    at = js.find('document.querySelector(".scan-sticky, .sticky-cta")')
    sticky = js[at:] if at >= 0 else ""
    check("固定の帯: 記事と LP を同じ仕組みで出し入れする", at >= 0, True)
    ends = re.search(r'var ends = document\.querySelectorAll\("([^"]*)"\)', sticky)
    watched = {s.strip() for s in ends.group(1).split(",")} if ends else set()
    check("固定の帯: フォーム・申し込みの区画が見えている間と、入力している間は引っ込める",
          ({"form", "#form", "#scan-start", ".site-footer"} <= watched, "focusin" in sticky and "!typing" in sticky),
          (True, True))
    css = _css()
    check("LP の帯は最初は画面の外（出すのは is-on のときだけ）",
          ("translateY(110%)" in (_decl(css, ".sticky-cta", "transform") or ""), _decl(css, ".sticky-cta.is-on", "transform")),
          (True, "none"))
    check("LP の帯のために本文の下に余白を足さない（帯は足元で引っ込む）", "body.has-sticky" in css, False)
    # 帯の高さ = ボタンの行の高さ + 上下の余白。64px 以内
    def bar_h(btn_sel, font_px, wrap_pad_px):
        lh = float(_decl(css, btn_sel, "line-height") or 2)
        pad = re.match(r"([\d.]+)em", _decl(css, btn_sel, "padding") or "1em")
        return round(font_px * lh + 2 * float(pad.group(1)) * font_px + 2 * wrap_pad_px)
    check("記事の下の帯は 64px 以内（83px あった）", bar_h(".scan-sticky .btn", 16, 8) <= 64, True)
    check("LP の下の帯は 64px 以内（79px あった）", bar_h(".sticky-cta .btn", 14.4, 8) <= 64, True)


def test_h51_windows_reads_medium_weight():
    css = _css()
    faces = re.findall(r"@font-face\s*\{([^}]*)\}", css)
    medium = [f for f in faces if '"YuGothicM"' in f and 'local("Yu Gothic Medium")' in f]
    check("Windows: 端末の Yu Gothic Medium を名前で呼ぶ（ファイルは読まない）",
          (len(medium), any("url(" in f for f in faces)), (1, False))
    check("Windows: 太字は Bold を同じ名前で", any('local("Yu Gothic Bold")' in f and "font-weight: 700" in f for f in faces), True)
    for var in ("--sans", "--head"):
        check(f"文字の指定（{var}）: Hiragino の次に YuGothicM", '"Hiragino Sans", "YuGothicM", "Yu Gothic"' in (_decl(css, ":root", var) or ""), True)


def test_h51_small_text_has_a_floor():
    css = _css()
    floor = {".post-list time": 13, ".post-list .tag": 12, ".qa-top": 15, ".author-box .role": 13, ".author-box p": 15,
             ".author-box p.how-made": 13, ".article-meta": 13, ".site-footer .copyright": 13, ".share-btn": 13,
             ".article-header .cat-badge": 12, ".side-cta .s": 13}
    check("小さい文字: 日付・注記 13px／ラベル 12px／説明 15px を下回らない",
          {s: _px(_decl(css, s, "font-size")) for s in floor if _px(_decl(css, s, "font-size")) < floor[s]}, {})
    check("調査の質問集の答えは本文の色（灰色の12.48pxだった）", _decl(css, ".qa-top", "color"), "var(--text)")


def test_h51_phone_header_is_small_and_tools_band_only_where_needed():
    css = _css()
    nav = _media(css, "(max-width: 1260px)")
    check("スマホのヘッダー: 上下の余白 .5rem・ボタン 42px（全体 約59px）",
          (_decl(nav, ".site-header .inner", "padding-top"), _decl(nav, ".nav-toggle", "height")), (".5rem", "42px"))
    reserve = [sels for sels, body in _rules(nav) if "padding-bottom" in body and any(":has(.nav-tool)" in s for s in sels)]
    check("ツールの帯の場所を取るのはトップと /tools/ だけ",
          reserve, [["body.home .site-header:has(.nav-tool)", "body:has(.tools-main) .site-header:has(.nav-tool)"]])
    js = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    check("ツールの帯を出すのも同じ条件（CSS と JS がずれると、空きか重なりが出る）",
          "document.body.classList.contains('home') || document.querySelector('.tools-main')" in js, True)
    check("目次のリンクは指で押せる高さ（文字だけの18pxだった）",
          (_decl(_base(css), ".toc a", "display"), _decl(_base(css), ".toc a", "padding")), ("block", ".4em 0"))


def test_h51_markers_and_buttons_are_calm():
    css = _css()
    bg = _decl(css, "main.article strong", "background") or ""
    pct = re.search(r"transparent (\d+)%", bg)
    check("黄色の帯は文字の下 3割まで（42%を塗っていた）・濃い #ffe873 を使わない",
          (bool(pct) and int(pct.group(1)) >= 70, "#ffe873" in re.sub(r"/\*.*?\*/", "", css, flags=re.S)), (True, False))
    check("見出し直下の1文結論の中の太字には帯を重ねない", _decl(css, "main.article .article-body h2 + p strong", "background"), "none")
    check("<button class=\"btn\"> にブラウザ既定の黒枠と小さい文字を出さない",
          (_decl(css, ".btn", "border"), _decl(css, ".btn", "font")), ("0", "inherit"))


def test_h51_first_view_on_phones():
    css = _css()
    check("パンくずは中央揃え（「ホーム」だけ下にずれていた）", _decl(css, ".breadcrumb ol", "align-items"), "center")
    sm = _media(css, "(max-width: 720px)")
    check("スマホの一覧: パンくずと見出しの間を詰める", _px(_decl(sm, ".hero", "padding-top")) <= 28, True)
    check("スマホの共有ボタンは1段", _decl(sm, ".share-row", "flex-wrap"), "nowrap")


def test_h51_page_labels_are_japanese():
    import build as B
    labels = {h1: B.page_shell(h1)["kicker"] for h1 in
              ("比較表から探す", "テーマから探す", "AIO・LLMO運用の比較表", "ホームページの記事", "記事一覧",
               "クリニックの集客", "用語集", "AIOとは", "業種別のAI調査")}
    check("見出しの上の札に英字を使わない（比較表・テーマに ALL ARTICLES と出ていた）",
          {h: k for h, k in labels.items() if re.search(r"[A-Za-z]{3,}", re.sub(r"<[^>]+>", "", k))}, {})
    check("札が見出しと同じ言葉なら出さない", labels["比較表から探す"], "")
    for p in ("compare/index.html", "topics/index.html"):
        f = ROOT / "site" / p
        if f.is_file():
            check(f"{p}: 英字の飾り（All Articles）が無い", bool(re.search(r"all articles", f.read_text(encoding="utf-8"), re.I)), False)


def test_h51_description_lines_are_not_too_long():
    css = _css()
    check("説明の段落は1行42字前後まで（業種ハブ・比較表・用語集・運営者で70〜91字）",
          {s: _decl(css, s, "max-width") for s in (".hub-lead", ".gl-rel", ".season-lead", "main.article > .author-box p")
           if _decl(css, s, "max-width") != "42em"}, {})


def test_h51_contrast_of_labels_and_copyright():
    css = _css()
    root = dict(re.findall(r"(--cat-[a-z]+):\s*(#[0-9a-f]{6})", css))
    check("タグの文字はカテゴリ色を黒に7割で混ぜる", _decl(css, ".post-list .tag", "color"),
          "color-mix(in srgb, var(--cat-color, var(--blue)) 70%, #000)")
    low = {}
    for k, c in root.items():
        fg = _mix(_hex(c), [0, 0, 0], .7)
        bg = _mix(_hex(c), [1, 1, 1], .1)
        if _contrast(fg, bg) < 4.5:
            low[k] = round(_contrast(fg, bg), 2)
    check("タグ: どのカテゴリ色でも 4.5:1 以上（3.32〜4.49:1 だった）", low, {})
    a = re.search(r"\.(\d+)\)", _decl(css, ".site-footer .copyright", "color") or "")
    alpha = int(a.group(1).ljust(2, "0")) / 100 if a else 0
    navy = _hex("#071a38")
    check("コピーライト: 4.5:1 以上（4.39:1 だった）", _contrast(_mix([1, 1, 1], navy, alpha), navy) >= 4.5, True)


def test_h51_list_images_do_not_repeat_and_carry_no_theme_text():
    import collections
    import industry_thumbs as IT
    check("文字入りのテーマ画像（theme-*.jpg）を当てる道が無い", hasattr(IT, "theme_for") or hasattr(IT, "THEMES"), False)
    got = IT.apply({"slug": "x", "category": "aio", "eyecatch": "/images/x/eyecatch.png",
                    "title": "AIO対策の計測方法｜見るべき5つの指標", "keyword": "aio 計測"})
    check("業種の無いAIO記事に「AIO対策の始め方」と書いた画像を当てない", "/images/thumbs/theme-" in str(got), False)
    slugs = [p.parent.name for p in sorted((ROOT / "site" / "images").glob("*/eyecatch.png"))[:4]]
    tiles = "".join(f'<li class="cat-aio"><a href="/aio/{s}/"><span class="thumb"><img src="/images/thumbs/aio-shika.webp" '
                    f'alt="題{s}のアイキャッチ画像" width="1200" height="675" loading="lazy"></span><time>x</time></a></li>' for s in slugs)
    once = IT._limit(tiles, 2)
    srcs = collections.Counter(re.findall(r'<img src="([^"]+)"', once))
    check("同じ一覧で同じ画像は2回まで（3回目からは題を描いたアイキャッチ）",
          (max(srcs.values()) if srcs else 0, len(slugs) >= 3), (2, True))
    check("何度当てても同じ", IT._limit(once, 2), once)
    bad = []
    for p in ("aio/index.html", "ai-marketing/index.html", "blog/index.html", "industry/clinic/index.html"):
        f = ROOT / "site" / p
        if not f.is_file():
            continue
        s = f.read_text(encoding="utf-8")
        for ul in re.findall(r'<ul class="post-list[^"]*">(.*?)</ul>', s, re.S):
            c = collections.Counter(re.findall(r'<span class="thumb"><img src="([^"]+)"', ul))
            if c and max(c.values()) > 2:
                bad.append(p)
        if "/images/thumbs/theme-" in s:
            bad.append(p + "（テーマ画像）")
    check("出来上がった一覧: 同じ画像が3回以上並ばず、テーマ画像も無い", sorted(set(bad)), [])


def test_h51_download_ends_on_its_own_thanks_page():
    lead = (ROOT / "functions" / "api" / "lead.js").read_text(encoding="utf-8")
    check("資料ダウンロードの後は /thanks/?type=download（GAS 経路・控えの経路の両方）",
          ('"/thanks/?type=download"' in lead, lead.count("Response.redirect(thanks, 303)")), (True, 2))
    thanks = (ROOT / "site" / "thanks" / "index.html").read_text(encoding="utf-8")
    branch = thanks[thanks.find("thanksType === 'download'"):]
    branch = branch[:branch.find("}\n")]
    check("資料の完了ページ: 資料の案内と次の一歩（担当者からの連絡の案内は出さない）",
          ("チェックリスト" in branch, "2営業日" in branch, "/tools/" in branch, "#form" in branch), (True, False, True, True))
    import page_enrich as PE
    texts = [b for _, b in PE.DOWNLOAD["steps"] + PE.DOWNLOAD["learn"]]
    check("資料の項目数は1つ（34項目。「約25項目」が混ざっていた）",
          (sorted({n for t in texts for n in re.findall(r"約?\d+項目", t)}), PE.CHECKLIST_ITEMS), (["34項目"], 34))
    page = (ROOT / "site" / "download" / "index.html").read_text(encoding="utf-8")
    check("資料ダウンロードのページの項目数がそろう", sorted(set(re.findall(r"約?\d+項目", page)) - {"14項目"}), ["34項目"])
    try:
        import pypdf
    except Exception:
        return
    pdf = ROOT / "site" / "download" / "checklist-clinic.pdf"
    if pdf.is_file():
        text = "".join(p.extract_text() or "" for p in pypdf.PdfReader(str(pdf)).pages[:2])
        check("PDF の実物も34項目", f"{PE.CHECKLIST_ITEMS}項" in text, True)


def test_h51_entry_clicks_are_measured_with_unique_names():
    js = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    check("入口（/lp/・/contact/・/download/・/tools/）への文字リンクも cta_click を送る",
          ("ENTRY = /^\\/(?:lp|contact|download|tools)(?:\\/|$)/" in js, "isEntry(a)" in js), (True, True))
    check("data-cta の無いボタンの名前を文言から作らない（305本が同じ「AI」になった）",
          ("slugId((a.textContent" in js, "autoId(a)" in js), (False, True))
    check("名前はページの種類＋位置＋行き先", all(f in js for f in ("function pageKind(", "function region(", "function dest(")), True)


def test_h51_contact_two_columns_and_left_aligned_voices():
    page = (ROOT / "site" / "contact" / "index.html").read_text(encoding="utf-8")
    check("問い合わせ: フォームと右の欄の2段組", ('class="contact-grid"' in page, "<!-- contact-side -->" in page), (True, True))
    import page_enrich as PE
    side = PE._contact_side()
    check("右の欄は既存の文言（相談の流れ・よくある質問）", ("ご相談の流れ" in side, "よくある質問" in side, "contact-side" in side),
          (True, True, True))
    css = _css()
    check("お客様の声: 左揃え・14px", (_decl(css, ".voice", "text-align"), _px(_decl(css, ".voice-metric .m-label", "font-size"))),
          ("left", 14.0))


def test_h51_industry_entries_keep_the_industry():
    import build as B
    import industry_hub as IH
    import industry_lp as IL
    check("業種のページの相談の帯は業種のLPへ（無い業種は全業種向けのまま）",
          ((B.industry_cta("clinic") or {}).get("cta_url"), B.industry_cta("btob")), ("/lp/medical/", None))
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("業種ハブと業種のよくある質問の両方で使う", src.count('cta=industry_cta(ind["slug"])'), 2)
    ind = {"slug": "clinic", "name": "クリニック", "lead": "説明"}
    metas = [{"slug": f"s{i}", "title": f"題{i}", "category": "aio", "date": "2026-10-01"} for i in range(3)]
    on = IH.hub_body(ind, metas, {"aio": ("AIO", "cat-aio")}, lambda m: "<li></li>")
    off = IH.hub_body(ind, metas, {"aio": ("AIO", "cat-aio")}, lambda m: "<li></li>", extras=False)
    check("業種ハブ: 診断とチェックリストの入口をいつも出す（季節の特集のときだけだった）",
          ("/tools/ai-check/?ind=clinic" in on, "/download/?ind=clinic" in on, "/tools/url-check/" in on), (True, True, True))
    check("業種ハブ（お客様のサイト）: AI集客ラボにしか無い入口は出さない", ("/tools/" in off, "/download/" in off), (False, False))
    url = IL.consult_url("medical")
    check("業種LPの「相談する」は業種を ?ind= で渡す", (url.startswith("/lp/?ind="), url.endswith("#form"), "src=lp_medical" in url),
          (True, True, True))
    lsrc = (ROOT / "scripts" / "industry_lp.py").read_text(encoding="utf-8")
    check("業種LPに業種の消える「/lp/#form」が残っていない", 'href="/lp/#form"' in lsrc, False)
    lp = (ROOT / "site" / "lp" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "site" / "js" / "site.js").read_text(encoding="utf-8")
    lead = (ROOT / "functions" / "api" / "lead.js").read_text(encoding="utf-8")
    check("LP: 業種を受け取る隠し項目・選択肢にある値だけ入れる・受付が本文に添える",
          ('<input type="hidden" name="industry"' in lp, "#lx-industry option" in js and 'input[name="industry"]' in js,
           "【業種】" in lead), (True, True, True))
