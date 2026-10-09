# -*- coding: utf-8 -*-
"""記事の表の数字を、同じ数字の横棒グラフにして表の直後に添える（2026-10-08 運用者の依頼「表やグラフ、図なども盛り込んで
視覚的に見やすく」）。全サイト（自社3サイトとお客様の社）の記事に効かせる。

数字の入った表は約半数の記事にあるのに（AI集客ラボ 147本中71本・コーポ 131本中54本・補助金 130本中95本）、
グラフは1つも無く、大小は表を読み比べないと分からなかった。グラフは誤れば表より害が大きいので、門で守るのは:
  1. 描いてよい表だけを選ぶ（範囲・約・年や年度・番号・電話・郵便番号・版・注記つきの数・単位の混ざる列・符号つきの数は描かない）
  2. 描いた値は表の値そのもの（四捨五入・単位の変換をしない）。作った SVG を読み戻して表と1つでも違えば描かない
  3. 1記事に2つまで（描く棒の多い表を先に。同じなら記事の前にある表）。それぞれ表の直後に置く
  4. 4サイトの変換（build.py・nextjs-json・external-html・external-md の journal）を通しても SVG が残る
  5. サイトの色だけ（図の主色と本文の文字色）・外部の読み込みなし・スマホ 390px で文字が 11px を割らない
"""
import contextlib
import io
import json
import re
import tempfile
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

from test_gates import check, client_ready

SLUG = "h58-charts"
T_RATE = ("| 申請枠 | 採択率 |\n|:--|:--|\n| 通常枠 | 43.6% |\n| インボイス枠 | 55.3% |\n"
          "| セキュリティ対策推進枠 | 71.4% |\n| 複数者連携枠 | 50.0% |\n")                       # 4本
T_TWO = ("| 情報源 | 検討者 | 実施者 |\n|:--|:--|:--|\n| インターネット | 34.4% | 26.0% |\n"
         "| いつも依頼している業者 | 22.5% | 25.5% |\n| チラシ・広告誌 | 22.4% | 18.4% |\n")      # 2本ずつ × 3行 = 6本
T_YEN = ("| 項目 | 金額 |\n|:--|:--|\n| ソフト利用料 | 60万円 |\n| 初期設定 | 25万円 |\n| 操作研修 | 15万円 |\n"
         "| 保守料 | 12万円 |\n| 合計 | 112万円 |\n")                                            # 合計を除いて4本（枠の外）
T_RANGE = "| 型 | 費用 |\n|:--|:--|\n| 伴走型 | 3〜5万円 |\n| 部分型 | 5〜8万円 |\n| 一括型 | 10万円〜 |\n"
BODY = ("**表の数字は、グラフにすると大小がひと目で分かります。**この記事は試験用です。\n\n"
        "## 申請枠ごとの採択率\n\n**採択率は枠で違います。**次の表のとおりです。\n\n" + T_RATE + "\n"
        "表の数字は公表された結果です。\n\n"
        "## 情報源の違い\n\n**検討と実施で使う情報源が違います。**\n\n" + T_TWO + "\n"
        "## 費用の内訳\n\n**ソフトの利用料がいちばん大きい費用です。**\n\n" + T_YEN + "\n"
        "## 型ごとの費用\n\n**費用は型で変わります。**\n\n" + T_RANGE + "\n"
        "## まとめ\n\n**数字は表が正、グラフは見え方です。**\n")
META = {"title": "表のグラフの試験の記事です", "description": "表の数字を横棒グラフにする仕組みを試すための記事です。" * 2,
        "slug": SLUG, "keyword": "表 グラフ", "date": "2026-10-08", "modified": "2026-10-08", "score": 95}


def _tc():
    import table_charts as T
    return T


def _md_table(md):
    lines = md.strip().split("\n")
    cells = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
    return cells[0], cells[2:]


def _a(md):
    return _tc().analyze(*_md_table(md))


def _mk(head, rows):
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "|".join(":--" for _ in head) + "|"]
                     + ["| " + " | ".join(r) + " |" for r in rows]) + "\n"


# ── 1. 描いてよい表だけを選ぶ ──────────────────────────────────────

def test_charts_pick_only_tables_that_can_be_drawn_truthfully():
    print("\n■ 表のグラフ: 描いてよい表だけを選ぶ（誤ったグラフより、描かない方がよい）")
    T = _tc()
    ok = _a(T_RATE)
    check("1つの数（同じ単位）の列は描く。値は表の文字のまま（四捨五入しない）",
          [isinstance(ok, dict), ok["series"], [v[0][1] for _, v in ok["rows"]], [v[0][0] for _, v in ok["rows"]]],
          [True, ["採択率"], ["43.6%", "55.3%", "71.4%", "50.0%"],
           [Decimal("43.6"), Decimal("55.3"), Decimal("71.4"), Decimal("50.0")]])
    lab = ["飲食店", "美容室", "建設業", "製造業"]
    bad = {
        "範囲（〜）": ["3〜5件", "5〜8件", "10件〜", "2〜3件"],
        "約・以上・程度": ["約30%", "40%以上", "25%程度", "約12%"],
        "年": ["2023年", "2024年", "2025年", "2026年"],
        "年度": ["令和5年度", "令和6年度", "令和7年度", "令和8年度"],
        "番号・回": ["No.3", "第2回", "No.7", "第5回"],
        "電話": ["03-1234-5678", "06-1111-2222", "092-333-4444", "011-555-6666"],
        "郵便番号": ["〒530-0001", "〒100-0005", "〒810-0001", "〒060-0001"],
        "版": ["v2.1", "Ver.3", "v1.0", "v4.2"],
        "上限の注記": ["上限450万円", "最大350万円", "150万円（上限）", "上限50万円"],
        "単位の混ざる列": ["750万円", "1億円", "3,000万円", "8,000万円"],
        "単位の無い数": ["320", "298", "410", "388"],
        "日付": ["10月7日", "10月23日", "11月5日", "12月1日"],
    }
    got = {k: _a(_mk(["業種", "値"], [[a, b] for a, b in zip(lab, v)])) for k, v in bad.items()}
    check("範囲・約・以上・年・年度・番号・電話・郵便番号・版・上限の注記・単位の混在・単位の無い数・日付は描かない",
          {k: isinstance(v, str) for k, v in got.items()}, {k: True for k in bad})
    signed = _a(_mk(["業種", "増減"], [["A", "12%"], ["B", "8%"], ["C", "−5%"], ["D", "3%"], ["E", "9%"]]))
    check("符号の付いた数（−5%・▲・+）が1つでもある列は、8割が数でも描かない（負の値を黙って落とさない）",
          isinstance(signed, str) and "符号" in signed, True)
    check("1列目が数（番号・数量）の表は描かない",
          isinstance(_a(_mk(["#", "所要時間"], [["1", "5分"], ["2", "3分"], ["3", "15分"]])), str), True)
    check("行が3〜12でない表は描かない（2行・13行）",
          [isinstance(_a(_mk(["枠", "率"], [["a", "1%"], ["b", "2%"]])), str),
           isinstance(_a(_mk(["枠", "率"], [[f"枠{i}", f"{i}%"] for i in range(1, 14)])), str)], [True, True])
    check("見出しが日付・期限（締切日・申請期限）の列は描かないが、「2次締切の採択率」は率の列として描く",
          [isinstance(_a(_mk(["回", "締切日"], [["1次", "15日"], ["2次", "20日"], ["3次", "25日"]])), str),
           isinstance(_a(_mk(["申請枠", "2次締切の採択率"], [["通常", "43.59%"], ["インボイス", "55.30%"], ["セキュリティ", "71.43%"]])), dict)],
          [True, True])
    hu = _a(_mk(["方式", "費用（万円）"], [["既製", "30"], ["ノーコード", "120"], ["開発", "1,200"]]))
    check("単位が見出しの括弧にある列は数として読み、棒の端に単位を付けて見せる（数は変えない）",
          [v[0][1] for _, v in hu["rows"]], ["30万円", "120万円", "1,200万円"])
    two = _a(T_TWO)
    three = _a(_mk(["枠", "1人", "2人", "3人"], [["A", "40万円", "70万円", "90万円"], ["B", "50万円", "100万円", "130万円"],
                                              ["C", "100万円", "240万円", "270万円"]]))
    mixed = _a(_mk(["枠", "上限", "率"], [["A", "450万円", "50%"], ["B", "350万円", "66%"], ["C", "150万円", "75%"]]))
    check("数字の列がちょうど2つで単位が同じなら2本ずつ。3つ以上・単位が違えば1列だけ（数の多い列、同じなら左）",
          [two["series"], three["series"], mixed["series"]], [["検討者", "実施者"], ["1人"], ["上限"]])
    yen = _a(T_YEN)
    rate_all = _a(_mk(["申請枠", "採択率"], [["通常", "43.6%"], ["インボイス", "55.3%"], ["セキュリティ", "71.4%"], ["全体", "51.5%"]]))
    check("量（円・件）の列の合計の行は棒にしない（内訳がつぶれる）。率の列の「全体」は同じ物差しなので残す",
          [[lab for lab, _ in yen["rows"]], yen["totals"], [lab for lab, _ in rate_all["rows"]][-1]],
          [["ソフト利用料", "初期設定", "操作研修", "保守料"], ["合計"], "全体"])
    part = _a(_mk(["期間", "控除率"], [["〜2026年9月", "80%"], ["〜2028年9月", "70%"], ["〜2029年9月", "50%"],
                                     ["〜2031年9月", "30%"], ["2031年10月以降", "控除なし"]]))
    check("数でない行が2割以内なら、その行だけ除いて描き、図の説明に書く",
          [len(part["rows"]), part["skipped"], "数字で書かれていない行は除く" in T.caption(part)], [4, 1, True])


# ── 2. 描いた値は表の値。SVG を読み戻して検算する ───────────────────────

def test_chart_values_are_read_back_from_the_svg_and_match_the_table():
    print("\n■ 表のグラフ: SVG から読み戻した文字・値・棒の長さが表と同じ。1つでも違えば描かない")
    T = _tc()
    colors = {"s1": "#2563EB", "s2": "currentColor"}
    for name, md in (("1本", T_RATE), ("2本ずつ", T_TWO), ("合計を除く", T_YEN)):
        spec = _a(md)
        s = T.svg(spec, colors)
        root = ET.fromstring(s)
        got = T.read_back(s)
        want = [(lab, [v[1] for v in vals if v]) for lab, vals in spec["rows"]]
        check(f"{name}: 読み戻したラベルと値の文字が表と同じ", [(re.sub(r"\s", "", lab), [t for _, t, _, _ in items]) for lab, items in got],
              [(re.sub(r"\s", "", lab), v) for lab, v in want])
        lens = [x1 - x0 for _, items in got for _, _, x0, x1 in items]
        vals = [v[0] for _, vv in spec["rows"] for v in vv if v]
        check(f"{name}: 棒の長さは値に比例し、最大の値の棒がいちばん長い",
              all(abs(ln - float(v / max(vals)) * max(lens)) <= 0.02 for ln, v in zip(lens, vals)), True)
        check(f"{name}: 検算（verify）を通る・XML として読める・role=img・要約・<title>",
              [T.verify(spec, s), root.get("role"), bool(root.get("aria-label")), root.find("{http://www.w3.org/2000/svg}title") is not None],
              [True, "img", True, True])
    spec = _a(T_RATE)
    s = T.svg(spec, colors)
    tampered = {
        "値の文字を丸めた（43.6% → 44%）": s.replace(">43.6%<", ">44%<"),
        "棒の長さを変えた": re.sub(r'(<path class="tc-bar tc-s1" d="M[\d.]+,[\d.]+H)([\d.]+)',
                                lambda m: m.group(1) + str(float(m.group(2)) + 30), s, count=1),
        "行を1つ落とした": re.sub(r'<g class="tc-row">(?:(?!</g>).)*</g>', "", s, count=1),
        "XML として壊れた": s.replace("</svg>", ""),
    }
    check("検算: 値の文字・棒の長さ・行の数・形のどれかが違えば通さない",
          {k: T.verify(spec, v) for k, v in tampered.items()}, {k: False for k in tampered})
    keep = T.svg
    try:
        T.svg = lambda sp, c: keep(sp, c).replace(">55.3%<", ">55%<")
        broken = T.figure(spec, colors)
    finally:
        T.svg = keep
    check("検算を通らない図は記事に入れない（figure が空）", broken, "")
    fig = T.figure(spec, colors)
    check("図は figure.table-chart に入れ、説明は「上の表の『◯◯』をグラフにしたもの」",
          [fig.startswith('<figure class="table-chart"'), "<figcaption" in fig, "上の表の『採択率』をグラフにしたもの" in fig,
           "\n" in fig], [True, True, True, False])


# ── 3. 1記事に2つまで・表の直後 ───────────────────────────────────

def test_at_most_two_charts_per_article_each_right_after_its_table():
    print("\n■ 表のグラフ: 1記事に2つまで（棒の多い表を先に）。それぞれ表の直後。HTML と Markdown で同じ選び方")
    import md2html
    T = _tc()
    html = md2html.convert(BODY)[0]
    out = T.add_to_html(html)
    caps = re.findall(r"<figcaption[^>]*>(.*?)</figcaption>", out)
    check("4つの表（描ける3つ・範囲の1つ）から2つ: 2本ずつの表（6本）と、4本の表のうち前にある採択率",
          caps, ["上の表の『採択率』をグラフにしたもの", "上の表の『検討者』と『実施者』をグラフにしたもの"])
    check("図はそれぞれの表の横スクロールの枠の直後",
          len(re.findall(r'</table></div><figure class="table-chart"', out)), 2)
    check("何度通しても図は増えない", T.add_to_html(out), out)
    md = T.add_to_markdown(BODY)
    lines = md.split("\n")
    figs = [i for i, ln in enumerate(lines) if ln.startswith('<figure class="table-chart"')]
    check("Markdown: 同じ2つを、前後を空行で挟んだ1行の HTML の塊として表の直後に置く",
          [len(figs), all(lines[i - 1] == "" and lines[i + 1] == "" and lines[i - 2].startswith("|") for i in figs),
           re.findall(r"<figcaption[^>]*>(.*?)</figcaption>", md) == caps], [2, True, True])
    check("Markdown に置いた図は、Python-Markdown を通してもそのまま残る（生の HTML の塊として素通し）",
          md2html.convert(md)[0].count('<figure class="table-chart"'), 2)
    check("何度通しても図は増えない（Markdown）", T.add_to_markdown(md), md)


# ── 4. 4サイトの変換で SVG が残る ──────────────────────────────────

def _svgs(text):
    return re.findall(r'<figure class="table-chart".*?</figure>', text, re.S)


def _tree(td):
    from PIL import Image
    r = Path(td)
    img = r / "site" / "images" / SLUG
    img.mkdir(parents=True)
    Image.new("RGB", (8, 8), "white").save(img / "eyecatch.png")
    (r / "data").mkdir()
    (r / "data" / "videos.json").write_text("{}", encoding="utf-8")
    return r


def _dest(path):
    path.mkdir(parents=True)
    (path / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                                      '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n</urlset>\n',
                                      encoding="utf-8")
    (path / "llms.txt").write_text("# 試験\n", encoding="utf-8")
    return path


class _Patched:
    """publish・sites・video_embed の ROOT と台帳を一時フォルダへ向ける（gates_history_h31・h50 と同じ形）"""

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


def _ok_svg(fig):
    m = re.search(r"<svg\b.*?</svg>", fig, re.S)
    try:
        ET.fromstring(m.group(0))
        return True
    except (ET.ParseError, AttributeError):
        return False




# ── 5. 色・読み込み・スマホの文字・ページの題 ───────────────────────────

def test_chart_uses_site_colors_only_and_stays_light_and_readable():
    print("\n■ 表のグラフ: サイトの色だけ・外部の読み込みなし・スマホ 390px で文字が 11px 以上・ページの題を増やさない")
    T = _tc()
    import sites as S
    import seo_audit
    # 全社（お客様の社は非公開のデータがある回だけ入る）。お客様の社は公開の id で出す（CI のログに社の id を出さない）
    for real, cfg in sorted(S.load_all().items()):
        sid = cfg.get("public_id") or real
        c = T.colors_for(cfg)
        s = T.svg(_a(T_TWO), c)
        paints = set(re.findall(r'(?:fill|stroke)="([^"]+)"', s))
        check(f"{sid}: 色は図の主色・本文の文字色（currentColor）と、2本目に主色の淡い色だけ（新しい色みを足さない）",
              [paints, c["s2"] in ("currentColor", T._tint(c["s1"]))], [{c["s1"], c["s2"], "currentColor"}, True])
        s2 = c["ink"] if c["s2"] == "currentColor" else c["s2"]
        check(f"{sid}: 2本の棒が見分けられる（主色と2本目の輝度比 {T.S2_INK_MIN} 以上。濃紺どうしにしない）",
              T.contrast(c["s1"], s2) >= T.S2_INK_MIN, True)
    s = T.svg(_a(T_TWO), T.colors_for(None))
    check("外部の CSS・フォント・画像・スクリプトを読まない（<style>・<link>・<script>・url(・href・src が無い）",
          [bool(re.search(r"<style|<link|<script|url\(|href=|src=|@import", s))], [False])
    vb = float(re.search(r'viewBox="0 0 ([\d.]+)', s).group(1))
    smallest = min(float(x) for x in re.findall(r'font-size="([\d.]+)"', s))
    check("スマホ（本文の幅 340px）でいちばん小さい文字が 11px 以上", round(smallest * 340 / vb, 1) >= 11.0, True)
    check("幅は viewBox と width:100%（パソコンでは max-width で広がりすぎない）",
          ['width="100%"' in s, "max-width:" in s, "height:auto" in s], [True, True, True])
    page = ("<html><head><title>記事の題</title><meta name=\"description\" content=\"説明\"></head><body>"
            + T.figure(_a(T_RATE), T.colors_for(None)) + "</body></html>")
    f = seo_audit.page_facts(page)
    check("サイト監査: 図の <title> をページの題と数えない（題が複数の警告を出さない）", [f["n_title"], f["title"]], [1, "記事の題"])
