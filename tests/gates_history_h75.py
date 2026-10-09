# -*- coding: utf-8 -*-
"""2026-10-09 URL診断「タイトル（15〜45字）」で、補助金サイトの題が45字を超えていた。
記事の題は45字以内でも、雛形が末尾に「|セブンセンシズ株式会社」（12字）を付けて15本が超えていた。
本題（狙う語が前にある）は削らず、超えるときだけ末尾のサイト名を外す（publish.fit_title_tag）。
"""
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))


def test_title_drops_site_name_only_when_too_long():
    import publish as P
    tpl = "<head><title>{{TITLE}}|セブンセンシズ株式会社</title></head>"
    long_t = "クリーニング店のAI導入補助金 対象要件｜取次店とフランチャイズの判定【2026年】"
    short_t = "AI導入補助金の不採択理由と対策"
    check("45字を超えるときは末尾のサイト名だけを外す（本題の｜は残す）",
          P.fit_title_tag(tpl, long_t, {}), "<head><title>{{TITLE}}</title></head>")
    check("45字以内ならサイト名を残す", P.fit_title_tag(tpl, short_t, {}), tpl)
    tpl2 = "<title>{{TITLE}}｜{{SITE_NAME}}</title>"
    check("サイト名が差し込みの印でも、差し込んだ後の長さで決める",
          P.fit_title_tag(tpl2, "あ" * 30, {"SITE_NAME": "あ" * 20}), "<title>{{TITLE}}</title>")
    check("本題だけの雛形は触らない", P.fit_title_tag("<title>{{TITLE}}</title>", "あ" * 60, {}),
          "<title>{{TITLE}}</title>")
    src = (ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    check("配信の雛形への差し込みが fit_title_tag を通る", "out = fit_title_tag(tpl, meta[\"title\"], vals)" in src, True)


def test_subsidy_index_reads_titles_without_site_name():
    """補助金の一覧・sitemap を作る pages.py は、題を「最初の区切り（|・｜）まで」で読んでいた。
    社名を外した題は読めずに12本が一覧・sitemap から落ちかけ（2026-10-09 の描き直しで発見・push 前に止めた）、
    題の中に「｜」がある記事は一覧の題が途中で切れていた"""
    import re
    src = (ROOT / "scripts" / "subsidy" / "pages.py").read_text(encoding="utf-8")
    check("題は <title> 全体から読む（最初の区切りまでで切らない）",
          ('re.search(r"<title>(.*?)</title>", c, re.S)' in src, 'r"<title>(.*?)[||]"' in src), (True, False))
    m = re.search(r'SITE_SUFFIX = re\.compile\(r"(.+?)"\)', src)
    suf = re.compile(m.group(1)) if m else None
    check("末尾の社名だけを外す（題の中の｜は残す）",
          [suf.sub("", t) if suf else None for t in ("飲食店のAI導入補助金｜申請の進め方|セブンセンシズ株式会社",
                                                     "飲食店のAI導入補助金｜申請の進め方")],
          ["飲食店のAI導入補助金｜申請の進め方", "飲食店のAI導入補助金｜申請の進め方"])
