# -*- coding: utf-8 -*-
"""業種別のAI調査の一覧（/research/）は、最初に全体の結論、続けて業種を2本の棒で比べる形にする。

2026-10-07 運用者から「見にくい・デザインも悪い」。29業種が同じ形の文字だけのカードで並び、数字が長い文に
埋もれて比べられず、スマホで約9,800px。題「業種別のAI調査」が h1 と h2 で重複し、英語の飾り「ALL ARTICLES」が
あり、全体として何が言えるかが無かった。
カードと結論の数字は業種ページと同じ headline() から作るが、ここでは別の道筋（業種ページの HTML と、
元のデータの CSV の件数）から数え直して一致を確かめる。
"""
import csv
import io
import re
import statistics
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

RES = ROOT / "site" / "research"
TAG = re.compile(r"<[^>]+>")
NUM = re.compile(r"(\d+(?:\.\d+)?)%")


def _text(s):
    return re.sub(r"\s+", " ", TAG.sub("", s)).strip()


def _csv_local(ind, owner_label):
    """元のデータ（CSV）の件数から、地域で探す質問の (公式サイトの割合, 公式サイト以外で最も多い種類の割合) を出す"""
    rows = list(csv.reader(io.StringIO((RES / f"{ind}-ai-sources" / "data.csv").read_text(encoding="utf-8-sig"))))
    loc = [(r[1], int(r[2])) for r in rows[1:] if r and r[0] == "地域で探す"]
    tot = sum(n for _, n in loc) or 1
    pct = {k: round(n / tot * 100, 1) for k, n in loc}
    return pct.get(owner_label, 0.0), pct


def test_research_index_is_comparable_and_matches_pages():
    page = RES / "index.html"
    check("research一覧: ページが作られている", page.is_file(), True)
    if not page.is_file():
        return
    html = page.read_text(encoding="utf-8")

    # 見出し: h1 は1つ・同じ見出しを2度出さない・英語の飾りを出さない
    h1 = [_text(h) for h in re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.S)]
    check("research一覧: h1 は1つ", len(h1), 1)
    heads = [_text(h) for h in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.S)]
    check("research一覧: 見出しの重複が無い", sorted({h for h in heads if heads.count(h) > 1}), [])
    check("research一覧: 英語の飾りの見出し（All Articles）が無い", bool(re.search(r"all articles", html, re.I)), False)
    lead = re.search(r'<p class="rsx-lead">(.*?)</p>', html, re.S)
    meta = re.search(r'<meta name="description" content="([^"]*)"', html)
    check("research一覧: 説明文を本文に2度出さない（最初の画面の説明は1つ）",
          html.count(_text(lead.group(1))) if lead else 0, 1)
    check("research一覧: meta description がある", bool(meta and meta.group(1)), True)

    # 全業種のカードがある（業種ページのある業種すべて）
    inds = sorted(p.parent.name[:-len("-ai-sources")] for p in RES.glob("*-ai-sources/index.html"))
    cards = {m.group(1): m.group(0) for m in
             re.finditer(r'<li class="rsx-item"[^>]*data-ind="([a-z0-9_-]+)".*?</li>', html, re.S)}
    check("research一覧: 業種ページのある業種すべてにカードがある", sorted(cards), inds)
    check("research一覧: 業種が1つ以上ある（検出器が空振りしていない）", len(inds) > 0, True)

    # カードの数字は、業種ページの最初の画面（HTML）と元のデータ（CSV）の件数の両方と一致する
    import industry_ai_sources as IAS
    bad, lps, lcs, oas = [], [], [], []
    for ind in inds:
        c = cards.get(ind, "")
        shown = NUM.findall(" ".join(re.findall(r'<span class="rsx-v">(.*?)</span>', c)))
        loc = re.search(r'data-loc="([\d.]+)"', c)
        oth = re.search(r'data-oth="([\d.]+)"', c)
        if not (loc and oth and shown == [loc.group(1), oth.group(1)]):
            bad.append(f"{ind}: 棒の数字と並べ替えの値が違う {shown}")
            continue
        ih = (RES / f"{ind}-ai-sources" / "index.html").read_text(encoding="utf-8")
        stats = re.findall(r'<div class="lx-stat"><b>(.*?)</b><span>(.*?)</span>', ih, re.S)
        if len(stats) < 2:
            bad.append(f"{ind}: 業種ページの要点が読めない")
            continue
        first = NUM.findall(stats[0][0] + stats[0][1]) or NUM.findall(stats[0][0].replace("／", "% "))
        page_oa = NUM.findall(stats[1][0])
        if loc.group(1) not in first:
            bad.append(f"{ind}: 探す {loc.group(1)}% が業種ページの {first} に無い")
        if page_oa != [oth.group(1)]:
            bad.append(f"{ind}: 調べる {oth.group(1)}% が業種ページでは {page_oa}")
        T = IAS.headline(ind)["T"]   # CSV の「種類」の列の名前を引くためだけに使う（数字は使わない）
        lc_csv, pct = _csv_local(ind, T["owner_site"])
        lp_csv = pct.get(T["portal"], 0.0)
        if lc_csv != float(loc.group(1)):
            bad.append(f"{ind}: 探す {loc.group(1)}% が CSV の件数からは {lc_csv}%")
        if sorted(first) != sorted([str(lc_csv), str(lp_csv)]):
            bad.append(f"{ind}: 業種ページの最初の画面 {first} と CSV の件数（公式 {lc_csv}%・比較等 {lp_csv}%）が違う")
        lps.append(lp_csv)
        lcs.append(lc_csv)
        oas.append(float(page_oa[0]) if page_oa else -1)
    check("research一覧: カードの数字が業種ページ（HTML）と元のデータ（CSV）に一致", bad, [])

    # 最初の結論の数字も、業種ページと CSV から数え直した値と一致する
    n = len(inds)
    stat_n = [int(_text(x).split("／")[0].replace(",", "")) for x in
              re.findall(r'<p class="rsx-stat-n">(.*?)</p>', html, re.S)]
    want = [sum(v > 50 for v in oas), sum(p > c for p, c in zip(lps, lcs))]
    check("research一覧: 結論の件数（調べる質問で半数超・探す質問で比較等が上回る）が数え直しと一致", stat_n[:2], want)
    if n >= 10:
        med = lambda xs: round(statistics.median(xs), 1)
        summ = _text(re.search(r'<div class="rsx-sum">(.*?)</div><div class="rsx-tools"', html, re.S).group(1))
        for label, v in (("調べる質問の中央値", med(oas)), ("比較・予約などの中央値", med(lps)), ("公式サイトの中央値", med(lcs))):
            check(f"research一覧: {label} {v}% が結論の枠にある", f"{v}%" in summ, True)
        check("research一覧: 結論の枠に業種数と調査の時期がある",
              f"{n}業種" in summ and re.search(r"\d{4}年\d{1,2}月\d{1,2}日", summ) is not None, True)

    # 絞り込みは JS があるときだけ出し、JS が無くても全業種がまとまりごとに見えている
    css = (ROOT / "site" / "css" / "style.css").read_text(encoding="utf-8")
    check("research一覧: 絞り込みは JS が無いときは出さない（.rsx-tools は既定で隠し、html.js のときだけ出す）",
          bool(re.search(r"\.rsx-tools\s*\{\s*display:\s*none", css)) and "html.js .rsx-tools" in css, True)
    check("research一覧: 絞り込みのボタンがある", len(re.findall(r'<button type="button" data-g="', html)) >= 2, True)
    before_flat = html.split('id="rsxFlat"')[0]
    hidden_secs = re.findall(r'<section class="rsx-group[^"]*"[^>]*\shidden', html)
    hidden_items = re.findall(r'<li class="rsx-item"[^>]*\shidden', html)
    check("research一覧: JS が無いとき、まとまりも業種も隠さない", hidden_secs + hidden_items, [])
    check("research一覧: 全業種のカードが、JS が無くても見えるまとまりの中にある",
          sorted(set(re.findall(r'<li class="rsx-item"[^>]*data-ind="([a-z0-9_-]+)"', before_flat))), inds)
    check("research一覧: 並べ替え用の枠は空で出す（カードを二重に出さない）",
          bool(re.search(r'<ul class="rsx-list rsx-flat" id="rsxFlat" hidden></ul>', html)), True)

    # 構造化データ: 一覧（ItemList）とパンくず
    ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    import json
    types = {}
    for block in ld:
        try:
            node = json.loads(block)
        except ValueError:
            continue
        for g in node.get("@graph", [node]):
            types[g.get("@type")] = g
    check("research一覧: ItemList に全業種", (types.get("ItemList") or {}).get("numberOfItems"), n)
    check("research一覧: パンくずの構造化データ", "BreadcrumbList" in types, True)

    # 業種が10未満なら、結論に中央値（割合）を出さない
    small = IAS.index_page(inds[:5], None)
    check("research一覧: 業種が10未満のときは中央値を出さない", "中央値" in small[1].split('<div class="rsx-tools"')[0], False)
