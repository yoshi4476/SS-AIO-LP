# -*- coding: utf-8 -*-
"""2026-11-01 AI集客ラボの計測・1画面目・記事の CTA を、GA4（日本だけ・機械の訪問を除く）の実測で直した。
1. 実績の帯（トップ・LP の1画面目のすぐ下）と著者の実績が、10/20 の運用者の訂正から漏れていた
   （「3,200店舗以上のMEO」「50社以上」「AIO 15件中0件」「SEO 74件」）。帯の数字は一次情報の台帳の文にある数だけ、
   「店舗以上」「社以上」（累計◯社は書かない決まり）を使わない
2. 記事本文の相談の箱（/lp/ への「AI検索対策の無料相談」）は 9〜10月に表示 A228・B171 で押下が両方0。
   当サイトの LP へ向かう相談ボタンだけを URL診断の入口にし、新しい試験名 body_scan で半々に出し分ける。
   外のサイトへのボタンと、印の付いたボタンは触らない。既存の article_cta の試験は残る
3. ツールのページは区画（data-area）が無く、入口のリンクに印が無いため名前が「tools_main1_lp」のように並び順で決まっていた。
   区画を付け、ビルドで作り直す「あわせて読む・使う」の入口にも印を付ける（記事へのリンクは押下に数えないので付けない）
4. トップと LP の1画面目に、頼める内容と料金へ進む入口を置く（印つき）
"""
import json
import re
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

OLD_BAND = ('<div class="lx-proof" aria-label="実績"><ul>'
            '<li><span class="n">3,200<small>店舗以上</small></span><span class="l">MEO運用の実績</span></li>'
            '<li><span class="n">50<small>社以上</small></span><span class="l">導入を支援</span></li>'
            '<li><span class="n">15<small>件中</small> 0<small>件</small></span><span class="l">AIO運用の3か月以内の解約</span></li>'
            '<li><span class="n">74<small>件</small></span><span class="l">SEO運用のご契約</span></li></ul></div>')


def _claims():
    d = json.loads((ROOT / "data" / "first_party_facts.json").read_text(encoding="utf-8"))
    return [f["claim"] for f in d.get("facts", []) if "ai-lab" in f.get("sites", []) and not f.get("retired")]


def band_problems(html, claims):
    """実績の帯の数字のうち、台帳の文に無いもの・使わない単位"""
    m = re.search(r'<div class="lx-proof".*?</div>', html, re.S)
    if not m:
        return ["帯が無い"]
    out = []
    for n in re.findall(r'<span class="n">(.*?)</span>', m.group(0), re.S):
        if re.search(r"店舗以上|社以上", n):
            out.append("単位: " + re.sub(r"<[^>]+>", "", n))
        for num in re.findall(r"\d[\d,]*", re.sub(r"<[^>]+>", " ", n)):
            pat = r"(?<![\d,.])" + re.escape(num) + r"(?![\d,.])"
            if not any(re.search(pat, c) for c in claims):
                out.append("台帳に無い数: " + num)
    return out


def test_proof_band_uses_ledger_numbers():
    print("\n■ 1. 実績の帯は台帳の数だけ")
    claims = _claims()
    bad = band_problems(OLD_BAND, claims)
    check("悪い例: 訂正前の帯は「店舗以上」「社以上」と台帳に無い数（50・15・74）で止まる",
          (any("店舗以上" in x for x in bad), any("社以上" in x for x in bad),
           {"台帳に無い数: 50", "台帳に無い数: 74"} <= set(bad)), (True, True, True))
    for page in ("index.html", "lp/index.html"):
        html = (ROOT / "site" / page).read_text(encoding="utf-8")
        check(f"良い例: site/{page} の帯は台帳の数だけ", band_problems(html, claims), [])
    au = (ROOT / "site" / "author" / "haraguchi" / "index.html").read_text(encoding="utf-8")
    check("著者の実績に「店舗以上」のMEOの数を出さない", bool(re.search(r"店舗以上</small>", au)), False)


def test_body_consult_becomes_scan_entry():
    import build as B
    print("\n■ 2. 本文の相談の箱 → URL診断の入口（試験 body_scan）")
    own = '<div class="cta-box"><p>一緒に確かめませんか。</p><a class="cta-button" href="/lp/">AI検索対策の無料相談はこちら</a></div>'
    ind = '<a class="cta-button" href="/lp/shigyou/">AI検索対策の無料相談</a>'
    out = B.body_scan_cta(own + ind)
    check("悪い例だった /lp/・/lp/<業種>/ の相談ボタンは、2つとも URL診断へ・印と試験名つき",
          (out.count('href="/tools/url-check/"'), out.count('data-cta="article_body_url_check"'),
           out.count('data-ab="body_scan"'), "無料相談" in out), (2, 2, 2, False))
    keep = ('<a class="cta-button" href="https://corp.7senses.co.jp/contact?s=keiri-bpo">経理BPOの無料相談</a>'
            '<a class="cta-button" href="/lp/#diagnosis" data-cta="exit_diagnosis">無料診断</a>')
    check("良い例: 外のサイトへのボタンと印の付いたボタンはそのまま", B.body_scan_cta(keep), keep)
    src = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("置き換えは article_cta の試験より先（body_scan のボタンに article_cta が重ならない）",
          0 < src.find("content = body_scan_cta(content)") < src.find('data-ab="article_cta" data-ab-b='), True)
    check("文言は約束をしない（「必ず」「保証」「上位」を書かない）",
          bool(re.search(r"必ず|保証|上位", B.BODY_SCAN["a"] + B.BODY_SCAN["b"])), False)
    import ab_result as AR
    check("ab_result が試験 body_scan を読む",
          ("ab_impression_body_scan_", "cta_click_body_scan_") in [(i, c) for _, i, c in AR.tests()], True)


def test_tool_pages_have_areas_and_names():
    import page_enrich as P
    print("\n■ 3. ツールのページの区画と入口の印")
    check("悪い例: 記事へのリンクには印を付けない（押下に数えない）", P.guide_cta("url_check", "/aio/x/"), "")
    check("良い例: 入口のリンクは道具と行き先の名前", (P.guide_cta("url_check", "/lp/"), P.guide_cta("meo_check", "/tools/kuchikomi-henshin/")),
          (' data-cta="url_check_guide_lp"', ' data-cta="meo_check_guide_kuchikomi_henshin"'))
    import tools_catalog as T
    check("ほかの無料ツールの塊に区画の印", 'data-area-id="others"' in T.others_html(T.TOOLS[0]), True)
    entry = re.compile(r'<a href="/(?:lp|contact|download|tools)[^"]*"(?![^>]*data-cta)[^>]*>')
    for t in ("url-check", "aio-check", "meo-check", "kuchikomi-henshin", "ai-check"):
        s = (ROOT / "site" / "tools" / t / "index.html").read_text(encoding="utf-8")
        main = s[s.find("</nav>", s.find('class="breadcrumb')):s.find('<footer')]
        ids = set(re.findall(r'data-area-id="([^"]+)"', s))
        check(f"/tools/{t}/: 本文の入口リンクに印が無いものは0・冒頭とほかのツールの区画がある",
              (entry.findall(main), {"others"} <= ids and bool(ids & {"hero", "mv"})), ([], True))


def test_hero_offers_service_and_price():
    print("\n■ 4. 1画面目に頼める内容・料金への入口")
    top = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    lp = (ROOT / "site" / "lp" / "index.html").read_text(encoding="utf-8")
    hero_top = top[top.find('data-area-id="mv"'):top.find('class="lx-console"')]
    hero_lp = lp[lp.find('data-area-id="hero"'):lp.find('class="lx-console"')]
    check("トップ: サービスと料金・新着記事・無料相談の入口（既存の印の名前は変えない）",
          all(x in hero_top for x in ('data-cta="top_hero_service"', 'data-cta="top_hero_read"', 'data-cta="top_hero_consult"',
                                      'data-cta="top_hero_scan"')), True)
    check("LP: サービス・料金の入口（行き先の区画がある）",
          all(x in hero_lp for x in ('href="#service" data-cta="lp_hero_service"', 'href="#price" data-cta="lp_hero_price"'))
          and 'id="price"' in lp and 'id="service"' in lp, True)
    check("トップの最初の一文で、何を頼めるかを書く", "毎月の運用としてお引き受け" in hero_top, True)
