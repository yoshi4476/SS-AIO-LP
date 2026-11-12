# -*- coding: utf-8 -*-
"""AI集客ラボの固定ページを図と表で強くする（2026-10-08・運用者の依頼「表やグラフ、図で視覚的に見やすく」）。

直す前にあったこと:
  - トップに、業種別のAI調査（29業種・1,700問）の数字が1つも無かった。グラフを手で書くと、調査を足したり
    聞き直したりしたときに /research/ と食い違う → 集計から毎回作る（industry_ai_sources.home_section）
  - サービスの全体像（何を頼めて、どう進むか）が箱の並びだけ。LP の流れは6枚の箱で、ご契約前が無料だと読み取れない
  - LP に「自社で運用／代行を頼む／ツールだけ使う」の比較も、AIO・SEO・LLMO の関係の図も無かった
  - /tools/ に「わかること・所要時間」の表が無い。業種ハブに、その業種の調査の数字が無い
  - カテゴリ一覧（/aio/ ほか）の札が英字（CATEGORY・ARTICLES・GUIDE・SERVICES）。トップ・LP の見出しの上の札も英字
  - 比較表・用語集・テーマ・業種の一覧・業種のよくある質問で、h1 と同じ文の h2 が続けて出ていた。
    業種ハブでは業種の説明の段落が2回続いていた

数字の検算は、ページの数字をデータから別の数え方で数え直して突き合わせる（CLAUDE.md 0.1）。
"""
import html as _html
import json
import re
import statistics
import sys

from test_gates import check, ROOT

sys.path.insert(0, str(ROOT / "scripts"))

SITE = ROOT / "site"
LOC = "地域で探す"


def _read(rel):
    p = SITE / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _text(s):
    return _html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def _survey():
    """data/research/<業種>-summary.json から、業種ごとの3つの数を数え直す（ページを作る関数は使わない）。
    lc・lp: 地域で探す質問の出典の件数に占める公式サイト・比較サイトの割合
    oa: それ以外の質問で、公式サイトを1つ以上出典に入れた回答の割合（出典のある回答が母数）"""
    import industry_ai_sources as IAS
    out = {}
    for f in sorted((ROOT / "data" / "research").glob("*-summary.json")):
        ind = f.name[:-len("-summary.json")]
        s = json.loads(f.read_text(encoding="utf-8"))
        if ind not in IAS.QUESTIONS or "per_answer" not in s or LOC not in s.get("by_group", {}):
            continue
        loc = s["by_group"][LOC]
        tot = sum(loc.values()) or 1
        other = [g for g in s["by_group"] if g != LOC]
        hit = sum(s["per_answer"][g].get("clinic", 0) for g in other)
        ans = sum(s["per_answer"][g]["answers"] for g in other) or 1
        out[ind] = {"name": s["name"], "lc": round(loc.get("clinic", 0) / tot * 100, 1),
                    "lp": round(loc.get("portal", 0) / tot * 100, 1), "oa": round(hit / ans * 100, 1)}
    return out


def test_h59_top_research_chart_is_counted_from_the_survey():
    import build as B
    import industry_ai_sources as IAS
    top = _read("index.html")
    sec = re.search(r"<!-- research:home -->(.*?)<!-- /research:home -->", top, re.S)
    body = sec.group(1) if sec else ""
    check("トップに業種別のAI調査の区画（印の間）がある", bool(sec) and 'data-area-id="research"' in body, True)
    check("区画はビルドのたびに集計から作り直す（手で書かない）",
          ("sync_home_research()" in (ROOT / "scripts" / "build.py").read_text(encoding="utf-8"),
           callable(getattr(B, "sync_home_research", None))), (True, True))
    check("いまの集計から作った区画と、ページの区画が同じ（数字が古いまま・手で直したまま、になっていない）",
          "<!-- research:home -->" + body + "<!-- /research:home -->" == IAS.home_section(), True)
    sv = _survey()
    groups = []
    for gid, label, ids in IAS.INDEX_GROUPS:
        vals = [sv[i] for i in ids if i in sv]
        if vals:
            groups.append((label, vals))
    check("29業種すべてがどれかのまとまりに入る（はみ出した業種が図から消えない）",
          (sum(len(v) for _, v in groups), len(sv)), (len(sv), len(sv)))
    for key in ("oa", "lc"):
        fig = re.search(rf'<figure class="vz" data-measure="{key}">(.*?)</figure>', body, re.S)
        rows = re.findall(r'<span class="vz-l">([^<]+)<small>(\d+)業種・幅 ([\d.]+)〜([\d.]+)%</small></span>'
                          r'.*?<span class="vz-v">([\d.]+)%</span>', fig.group(1) if fig else "", re.S)
        got = [(lab, int(n), float(lo), float(hi), float(v)) for lab, n, lo, hi, v in rows]
        want = [(lab, len(vs), min(x[key] for x in vs), max(x[key] for x in vs),
                 round(statistics.median(x[key] for x in vs), 1)) for lab, vs in groups]
        check(f"トップの図（{key}）: まとまりごとの中央値・業種数・幅が、調査のデータを数え直した値と一致", got, want)
        bars = re.findall(r'<i style="width:([\d.]+)%"></i></span><span class="vz-v">([\d.]+)%', fig.group(1) if fig else "")
        check(f"トップの図（{key}）: 棒の長さが数字と同じ", [a == b for a, b in bars], [True] * len(want))
        plot = re.search(r'<div class="vz-plot" role="img" aria-label="([^"]+)"', fig.group(1) if fig else "")
        check(f"トップの図（{key}）: 棒は role=img と、全部の数字を言葉にした説明",
              bool(plot) and all(f'{lab}（{n}業種）{v}%' in _html.unescape(plot.group(1)) for lab, n, _, _, v in want), True)
    n = len(sv)
    half = sum(x["oa"] > 50 for x in sv.values())
    pmore = sum(x["lp"] > x["lc"] for x in sv.values())
    tiles = re.findall(r'<p class="rsx-stat-n">(\d+)<small>／(\d+)業種</small>', body)
    check("トップの2つの数字（調べる質問で半数超の業種・探す質問で比較サイトが上回った業種）がデータと一致",
          tiles, [(str(half), str(n)), (str(pmore), str(n))])
    check("調査の一覧（/research/）への入口と、表で見る形（読み上げ・AIのため）がある",
          ('href="/research/"' in body, '<details class="vz-table">' in body, "<table>" in body), (True, True, True))
    check("トップの区画に画像を足さない（CSS と文字で描く）", "<img" in body, False)


def test_h59_industry_hubs_lead_with_their_own_survey():
    import industry_ai_sources as IAS
    import industry_hub as IH
    sv = _survey()
    seen = 0
    for hub, r in IAS.HUB_TO_RESEARCH.items():
        page = _read(f"industry/{hub}/index.html")
        if not page or r not in sv or not (SITE / "research" / f"{r}-ai-sources" / "index.html").is_file():
            continue
        seen += 1
        card = re.search(r'<aside class="rsh-hub".*?</aside>', page, re.S)
        c = card.group(0) if card else ""
        find = re.search(r'data-measure="find">(.*?)</figure>', c, re.S)
        seek = re.search(r'data-measure="seek">(.*?)</figure>', c, re.S)
        fv = [float(v) for v in re.findall(r'<span class="vz-v">([\d.]+)%</span>', find.group(1) if find else "")]
        sk = [float(v) for v in re.findall(r'<span class="vz-v">([\d.]+)%</span>', seek.group(1) if seek else "")]
        check(f"業種ハブ {hub}: 調査（{r}）の数字（比較サイト・公式サイト・調べる質問）がデータと一致",
              (fv, sk), ([sv[r]["lp"], sv[r]["lc"]], [sv[r]["oa"]]))
        check(f"業種ハブ {hub}: 図は見出しの下・記事の検索欄より上",
              bool(card) and card.start() < page.find('id="blogSearch"'), True)
        check(f"業種ハブ {hub}: 図の数字を本文の文でも書く（AIは画像を読めない）",
              all(f"{v}%" in _text(re.search(r'<p class="rsh-hub-text">(.*?)</p>', c, re.S).group(1)) for v in fv + sk)
              if '<p class="rsh-hub-text">' in c else False, True)
        lead = re.search(r'<p class="lead">(.*?)</p>', page, re.S)
        again = [x for x in re.findall(r'<p class="hub-lead">(.*?)</p>', page, re.S) if lead and _text(x) == _text(lead.group(1))]
        check(f"業種ハブ {hub}: 業種の説明の段落を2回続けて出さない（見出しの下と「◯◯の記事」の下）",
              (bool(lead), again), (True, []))
    check("調査のある業種ハブを1つ以上たしかめた", seen >= 6, True)
    ind = {"slug": "shika", "name": "歯科医院", "lead": "説明"}
    metas = [{"slug": f"s{i}", "title": f"題{i}", "category": "aio", "date": "2026-10-01"} for i in range(3)]
    off = IH.hub_body(ind, metas, {"aio": ("AIO", "cat-aio")}, lambda m: "<li></li>", extras=False)
    check("お客様のサイトの業種ハブ（extras=False）には調査の図も調査へのリンクも出さない",
          ("rsh-hub" in off, "/research/" in off), (False, False))


def _section(page, area_id):
    m = re.search(rf'<section[^>]*data-area-id="{area_id}"[^>]*>(.*?)</section>\s*(?:<!--|<section|<div class="(?:section|photo-band)"|<footer)',
                  page, re.S)
    return m.group(1) if m else ""


def test_h59_lp_flow_comparison_and_layers():
    lp = _read("lp/index.html")
    flow = _section(lp, "flow")
    steps = re.findall(r'<li class="(is-free|is-run)[^"]*"><span class="step-title">([^<]+)</span>', flow)
    check("LP の流れ: 6段の段階図（1〜4 ご契約前・5〜6 ご契約後）", [c for c, _ in steps],
          ["is-free"] * 4 + ["is-run"] * 2)
    check("LP の流れ: 目印 id=flow（トップのサービスの図からリンクする）・見出しは「運用開始までの流れ」",
          ('id="flow"' in lp, "ご相談から運用開始までの流れ" in flow), (True, True))
    check("LP の流れ: 「ご契約前は費用がかからない」は料金の区画の注記と同じ事実",
          ("費用はかかりません" in flow, "ご契約前に費用が発生することはありません" in lp), (True, True))
    check("LP の流れ: 2営業日以内の連絡はフォームの案内と同じ", ("2営業日以内" in flow, "2営業日以内に担当者からご連絡します" in lp), (True, True))
    ap = _section(lp, "approach")
    head = re.findall(r'<th scope="col"[^>]*>([^<]+)</th>', ap)
    check("LP: 進め方の比較（自社で運用する・代行を頼む・ツールだけ使う）", head[1:4] if len(head) >= 4 else head,
          ["自社で運用する", "代行を頼む", "ツールだけ使う"])
    cells = re.findall(r'<td[^>]*data-label="([^"]+)"[^>]*>(.*?)</td>', ap, re.S)
    check("LP の比較: 空の欄が無く、スマホで列名を出す data-label が全部の欄にある",
          (len(cells) >= 20, all(_text(v) for _, v in cells), ap.count("<td") == len(cells)), (True, True, True))
    check("LP の比較: 出典の記事へのリンクがある（中身は記事にある比較だけ）",
          all(f'href="/aio/{s}/"' in ap for s in ("aio-taisaku-jibunde", "aio-service-hikaku", "aio-taisaku-donyu-hoho",
                                                   "aio-taisaku-muryou-tool", "aio-taisaku-souba")), True)
    srcs = "".join((ROOT / "articles" / f"{s}.md").read_text(encoding="utf-8") for s in
                   ("aio-taisaku-jibunde", "aio-service-hikaku", "aio-taisaku-donyu-hoho", "aio-taisaku-muryou-tool",
                    "aio-taisaku-souba") if (ROOT / "articles" / f"{s}.md").is_file())
    for phrase in ("原因の特定と修正の全部", "一次情報の提供と確認", "担当者の異動で止まりやすい", "経験がある分だけ早い",
                   "担当者を置けない", "直せる担当者がいる", "担当者に時間を割ける", "Search Console・GA4の基本操作"):
        if phrase in ap:
            check(f"LP の比較の言葉は記事にあるもの: {phrase}", phrase in srcs, True)
    check("LP の比較: 料金の数字を書き足さない（0円＝無料ツール以外の金額が無い）",
          sorted(set(re.findall(r"[\d,]+(?:万)?円", _text(ap))) - {"0円"}), [])
    # AIO・SEO・LLMO の関係: 出る場所と成果の見え方は、記事「AIOとは？」の表と同じ
    lay = re.search(r'<figure class="layers.*?</figure>', lp, re.S)
    lay = lay.group(0) if lay else ""
    towa = (ROOT / "articles" / "aio-towa.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| (SEO|AIO|LLMO) \| ([^|]+) \| ([^|]+) \|", towa, re.M)
    check("記事「AIOとは？」に AIO・SEO・LLMO の表がある（図の根拠）", len(rows), 3)
    for name, target, seen in rows:
        box = re.search(rf'<div class="layer is-{name.lower()}">(.*?)</dl>', lay, re.S)
        b = _text(box.group(1)) if box else ""
        check(f"LP の図 {name}: 出る場所と成果の見え方が記事の表と同じ（{target.strip()}／{seen.strip()}）",
              (target.strip() in b, seen.strip() in b), (True, True))
    check("LP の図: role=img と説明・図の中身を本文の文でも書く",
          ('class="layers-fig" role="img" aria-label="' in lay, '<p class="layers-text' in lp), (True, True))
    glossary = _read("glossary/index.html")
    if glossary:
        for term, word in (("AIO（AI Overview Optimization）", "引用"), ("LLMO（Large Language Model Optimization）", "引用"),
                           ("SEO（Search Engine Optimization）", "上位に表示")):
            g = re.search(rf"<h3>{re.escape(term)}とは</h3>(.*?)</section>", glossary, re.S)
            check(f"用語集の定義と図が食い違わない: {term} の定義に「{word}」", bool(g) and word in _text(g.group(1)), True)
    new = flow + ap + lay
    check("LP の新しい図と表に、誇大・約束の言葉が無い", [w for w in ("最強", "No.1", "必ず", "保証", "確実") if w in _text(new)], [])
    check("LP の新しい図と表に画像を足さない", "<img" in new, False)


def test_h59_top_service_map_is_drawn_and_written():
    top = _read("index.html")
    svc = re.search(r'<figure class="svc-map.*?</figure>\s*<p class="svc-map-text[^>]*>(.*?)</p>', top, re.S)
    fig = svc.group(0) if svc else ""
    check("トップ: サービスの全体像の図（ご契約前の3段・ご契約後の4段の輪）",
          (len(re.findall(r"<li><b>", re.search(r'<ol class="svc-steps">(.*?)</ol>', fig, re.S).group(1))) if '<ol class="svc-steps">' in fig else 0,
           len(re.findall(r"<li><b>", re.search(r'<ol class="svc-cycle">(.*?)</ol>', fig, re.S).group(1))) if '<ol class="svc-cycle">' in fig else 0),
          (3, 4))
    check("トップ: 図は role=img と説明、中身は図の下の文でも書く",
          ('class="svc-map-fig" role="img" aria-label="' in fig, bool(svc) and "無料" in svc.group(1) and "毎月" in svc.group(1)),
          (True, True))
    check("トップ: 図から LP の流れ（/lp/#flow）へ進める", 'href="/lp/#flow"' in fig, True)
    check("トップのサービスの図に、料金の数字・誇大の言葉を書かない",
          (re.findall(r"[\d,]+(?:万)?円", _text(fig)), [w for w in ("最強", "No.1", "必ず", "保証") if w in _text(fig)]), ([], []))


def test_h59_tools_table_lists_what_each_tool_tells_and_how_long():
    import tools_catalog as TC
    page = _read("tools/index.html")
    tbl = re.search(r"<!-- tools:table -->(.*?)<!-- /tools:table -->", page, re.S)
    t = tbl.group(1) if tbl else ""
    rows = re.findall(r'<tr><th scope="row"><a href="([^"]+)"[^>]*>([^<]+)</a></th>(.*?)</tr>', t, re.S)
    check("/tools/: 全部のツールが比べる表に並ぶ（並びは目的別の一覧と同じ）",
          [u for u, _, _ in rows], [x["url"] for g, _, _ in TC.GROUPS for x in TC.TOOLS if x["group"] == g])
    check("/tools/: どの行にも、わかること・所要時間・入力するもの",
          all(len(re.findall(r'<td data-label="[^"]+"[^>]*>[^<]+</td>', r)) == 3 for _, _, r in rows) and len(rows) > 0, True)
    made = [f"{x['name']}（{x['time']}）" for x in TC.TOOLS
            if re.search(r"\d+\s*(?:秒|分)", x["time"]) and re.search(r"約?\d+\s*(?:秒|分)", x["time"]).group(0) not in x["spec"]]
    check("/tools/ の所要時間の秒数・分数は、ツールの一覧（spec）に書いた目安のまま（数字の無いツールに秒数を作らない）", made, [])
    check("/tools/ の表の所要時間は一覧の値そのもの", [(re.findall(r'<td data-label="所要時間"[^>]*>([^<]+)</td>', r) or [""])[0] for _, _, r in rows],
          [x["time"] for g, _, _ in TC.GROUPS for x in TC.TOOLS if x["group"] == g])
    check("/tools/ の見出しの上の札が英字でない", bool(re.search(r'class="kicker">[A-Za-z ]+<', page)), False)


def test_h59_labels_above_headings_are_japanese():
    pages = ["index.html", "lp/index.html", "tools/index.html"] + [f"{c}/index.html" for c in ("aio", "seo", "meo", "ai-marketing")]
    pages += sorted(p.relative_to(SITE).as_posix() for p in (SITE / "lp").glob("*/index.html"))
    pages += sorted(p.relative_to(SITE).as_posix() for p in (SITE / "research").rglob("index.html"))
    bad = {}
    for p in pages:
        s = _read(p)
        found = re.findall(r'<span class="en"[^>]*>[^<]*</span>', s)
        found += re.findall(r'class="(?:kicker|ilp-eb)[^"]*"[^>]*>[A-Za-z][A-Za-z &;]*<', s)
        found += re.findall(r'<span class="num">[A-Za-z][^<]*</span>', s)
        found += re.findall(r'<p class="mc-label">[A-Za-z][^<]*</p>', s)
        found += re.findall(r">STEP \d<", s)
        if found:
            bad[p] = found[:3]
    check("トップ・LP・業種別LP・調査・ツール一覧・カテゴリ一覧の見出しの上の札に英字を使わない（CATEGORY・ARTICLES・SERVICE…）", bad, {})
    b = (ROOT / "scripts" / "build.py").read_text(encoding="utf-8")
    check("build.py が作る調査の質問集・ランキング・業種の記事の札も日本語",
          [w for w in ('kicker">AI Questions', 'kicker">Monthly Ranking', 'ilp-eb">Articles') if w in b], [])
    j = (ROOT / "scripts" / "jisseki_intake.py").read_text(encoding="utf-8")
    check("LP の「お客様の声」を作り直す処理も日本語の札（英字に戻さない）", ('class="en">Voice' in j, 'class="eyebrow">' in j), (False, True))


def test_h59_aggregate_pages_do_not_repeat_the_title():
    import build as B
    dup = []
    for top in ("compare", "glossary", "topics", "industry", "area"):
        for p in sorted((SITE / top).rglob("index.html")) if (SITE / top).is_dir() else []:
            s = p.read_text(encoding="utf-8")
            h1 = re.search(r"<h1[^>]*>(.*?)</h1>", s, re.S)
            if h1 and _text(h1.group(1)) in [_text(x) for x in re.findall(r"<h2[^>]*>(.*?)</h2>", s, re.S)]:
                dup.append(p.relative_to(SITE).as_posix())
    check("比較表・用語集・テーマ・業種のページで、h1 と同じ文の h2 を続けて出さない", dup, [])
    nested = sorted(p.relative_to(SITE).as_posix() for p in (SITE / "compare").rglob("index.html")
                    if '<div class="table-wrap"><div class="table-wrap">' in p.read_text(encoding="utf-8")) if (SITE / "compare").is_dir() else []
    check("比較表のページで、表の枠（table-wrap）を二重にしない（表の上に白い帯と影が2重に出ていた）", nested, [])
    page = ('<h1>AIO・LLMO運用の比較表</h1>\n  <p class="lead">AIO・LLMO運用の記事にある比較表20表を1か所に集めました。</p>'
            '<div class="latest-block" data-cat="new"><div class="cat-head"><h2>AIO・LLMO運用の比較表</h2>'
            '<span class="cnt">20表</span></div><p class="hub-lead">AIO・LLMO運用の記事にある比較表を1か所に集めました。'
            '表は各記事のものと同じです。</p></div><div class="latest-block"><div class="cat-head"><h2>別の表</h2></div></div>')
    out = B.drop_echo_head(page)
    check("同じ文の見出しを外し、説明の同じ文（数を除いて同じ）も外す・ほかの見出しは残す",
          ("<h2>AIO・LLMO運用の比較表</h2>" in out, "1か所に集めました。表は" in out, "表は各記事のものと同じです。" in out, "<h2>別の表</h2>" in out),
          (False, False, True, True))
    check("見出しが違えば何もしない", B.drop_echo_head(page.replace("<h2>AIO・LLMO運用の比較表</h2>", "<h2>違う見出し</h2>")),
          page.replace("<h2>AIO・LLMO運用の比較表</h2>", "<h2>違う見出し</h2>"))
