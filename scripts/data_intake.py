# -*- coding: utf-8 -*-
"""自社の一次データを、記入シート1枚から「引用されるページ」にする。

AI検索が根拠に選ぶのは「そこにしか無い数字」。構造や網羅性が揃っていても、他社でも
書ける一般論は引用されない。3,200店舗のMEO運用・SEO 74件・補助金30社の集計は、
この会社にしか出せない。**数字は人が入れる。機械は作らない**（架空のデータは優良誤認）。

  python scripts/data_intake.py --sheet             # 記入シートを作る（intake/データ記入シート.xlsx）
  python scripts/data_intake.py <xlsx>              # 検査だけ
  python scripts/data_intake.py <xlsx> --apply      # 登録して公開ページを作る

intake/ に置いたまま `intake_watch.py --apply` でも拾う（ファイル名に「データ」）。

作られるもの:
  data/datasets/<slug>.json            … 元データ（コミットする。会社名等は入れない設計）
  site/data/<slug>/index.html          … 公開ページ（表・棒グラフ・引用用の一文・集計方法・Dataset 構造化データ）
  site/data/<slug>/data.csv            … ダウンロード用
  site/llms.txt「## 一次データ」        … AIクローラー向けの案内
  data/first_party_facts.json          … 引用用の一文を一次情報として登録（記事から使われる）
  記事の「自社の一次データ」枠          … build.py が同じカテゴリの記事に自動で出す
"""
import argparse
import csv
import html
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
IN = ROOT / "intake"
SHEET = IN / "データ記入シート.xlsx"
DATASETS = ROOT / "data" / "datasets"
SITE = ROOT / "site"
SHELL = SITE / "lab" / "index.html"
SITE_URL = "https://ai.7senses.co.jp"
ORG = "セブンセンシズ株式会社"
START, END = "<!-- datasets:start -->", "<!-- datasets:end -->"
CATS = {"aio": "AIO・LLMO運用", "seo": "SEO運用", "meo": "MEO運用", "ai-marketing": "AI集客・活用全般"}

RULES = [
    "この1枚に入れた数字だけが公開されます。機械は数字を作りません。空欄のシートは登録しません。",
    "「母数（件数）」と「対象期間」は必須です。無いデータは公開しません（根拠を読者が確かめられないため）。",
    "母数が10件未満のデータは公開しません（割合として意味を持たず、個社が特定される恐れがあるため）。",
    "「データ」タブは「項目」と「値」が必須です。値は数字だけ（単位は概要タブの「単位」に）。",
    "割合のデータは「分子」「分母」も書いてください。実数の表・信頼区間・1件あたりの振れ幅まで自動で出ます。",
    "個社が分かる情報（会社名・店名・住所）は入れないでください。業種・規模などの区分で書きます。",
    "URLの一部になる「slug」は英小文字・数字・ハイフンだけ（例: meo-review-reply-rate）。",
]
OVERVIEW = [
    ("slug", "", "例: meo-review-reply-rate（英小文字・数字・ハイフン）"),
    ("題名", "", "例: 業種別・口コミ返信率と新患数の関係（3,200店舗の集計）"),
    ("説明（1〜2文）", "", "何を、どう数えたかが分かるように"),
    ("母数（件数）", "", "例: 3200"),
    ("母数の単位", "店舗", "店舗 / 社 / 件"),
    ("対象期間（開始）", "", "例: 2024-01"),
    ("対象期間（終了）", "", "例: 2026-08"),
    ("集計方法・出典", "", "例: G-ranの運用データから、口コミ返信率を月次で集計"),
    ("値の単位", "%", "例: % / 件 / 営業日"),
    ("関連カテゴリ", "meo", "aio / seo / meo / ai-marketing をカンマ区切り（記事に枠を出す先）"),
    ("引用用の一文（空なら自動で作ります）", "", "例: 3,200店舗の集計では、口コミ返信率80%以上の店舗は新患数が1.6倍でした"),
    ("分母の呼び名（任意）", "", "例: 契約件数（データタブに分子・分母を書いたときだけ使います）"),
    ("分子の呼び名（任意）", "", "例: 継続"),
    ("差の呼び名（任意）", "", "例: 解約"),
]
DATA_COLS = ["項目", "値", "分子（任意）", "分母（任意）", "判定の条件（任意）",
             "判定期間・月（任意）", "開始（任意）", "終了（任意）", "備考"]
DATA_EXAMPLE = ["例: SEO運用", "86.5", "64", "74", "契約から1年以内の解約で判定",
                "12", "2023-05", "2026-09", "いちばん古い契約から数えます"]


def make_sheet(path=SHEET):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    head, fill, yellow = Font(bold=True, color="FFFFFF"), PatternFill("solid", start_color="0B2447"), PatternFill("solid", start_color="FFF9DB")
    ws = wb.active; ws.title = "書き方"
    ws["A1"] = "一次データ 記入シート"; ws["A1"].font = Font(bold=True, size=14)
    for i, r in enumerate(RULES, 3):
        ws.cell(row=i, column=1, value=f"{i - 2}. {r}")
    ws.column_dimensions["A"].width = 110
    w = wb.create_sheet("概要")
    w.append(["項目", "記入", "例・注意"])
    for c in w[1]:
        c.font, c.fill = head, fill
    for r in OVERVIEW:
        w.append(list(r))
    for row in w.iter_rows(min_row=2, min_col=2, max_col=2):
        row[0].fill = yellow
    w.column_dimensions["A"].width = 34; w.column_dimensions["B"].width = 44; w.column_dimensions["C"].width = 56
    d = wb.create_sheet("データ")
    d.append(DATA_COLS)
    for c in d[1]:
        c.font, c.fill = head, fill
    d.append(DATA_EXAMPLE)
    for c in d[2]:
        c.font = Font(color="888888", italic=True)
    for _ in range(8):
        d.append([""] * len(DATA_COLS))
    for row in d.iter_rows(min_row=3, min_col=1, max_col=4):
        for c in row:
            c.fill = yellow
    for col, wd in zip("ABCDEFGHI", (22, 9, 11, 11, 28, 14, 12, 12, 34)):
        d.column_dimensions[col].width = wd
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def read(path):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    got = {"overview": {}, "rows": []}
    if "概要" in wb.sheetnames:
        for row in wb["概要"].iter_rows(min_row=2, values_only=True):
            if row and row[0]:
                got["overview"][str(row[0]).strip()] = "" if row[1] is None else str(row[1]).strip()
    if "データ" in wb.sheetnames:
        for row in wb["データ"].iter_rows(min_row=2, values_only=True):
            vals = ["" if v is None else str(v).strip() for v in (list(row) + [""] * 9)[:9]]
            if not vals[0] or vals[0].startswith("例:"):
                continue
            got["rows"].append({"label": vals[0], "value": vals[1], "num": vals[2], "den": vals[3],
                                "window": vals[4], "months": vals[5], "row_start": vals[6],
                                "row_end": vals[7], "note": vals[8]})
    return got


def _num(s):
    try:
        return float(str(s).replace(",", "").replace("%", ""))
    except Exception:
        return None


def _ym(s):
    s = str(s or "").strip().replace("/", "-").replace("年", "-").replace("月", "")
    m = re.match(r"^(\d{4})-(\d{1,2})$", s)
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else ""


def _fmt(v, unit):
    s = f"{v:,.1f}".rstrip("0").rstrip(".") if v != int(v) else f"{int(v):,}"
    return f"{s}{unit}"


def review(got):
    """検査する。(データセット, 不備, 警告) を返す"""
    o, rows, ng, warn = got.get("overview") or {}, got.get("rows") or [], [], []
    g = lambda k: next((v for kk, v in o.items() if kk.startswith(k)), "")
    slug = g("slug")
    if not any(o.values()) and not rows:
        return None, ["何も記入されていません（空欄のシートです）"], []
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,60}", slug or ""):
        ng.append("slug は英小文字・数字・ハイフン（3〜60字）で書いてください")
    title, desc = g("題名"), g("説明")
    if len(title) < 8:
        ng.append("題名が短すぎます（8字以上）")
    if len(desc) < 20:
        ng.append("説明が短すぎます（20字以上。何をどう数えたかが分かるように）")
    n = _num(g("母数"))
    unit_n = g("母数の単位") or "件"
    if n is None:
        ng.append("母数（件数）が要ります")
    elif n < 10:
        ng.append(f"母数が{int(n)}{unit_n}では公開しません（10未満）")
    s, e = _ym(g("対象期間（開始）")), _ym(g("対象期間（終了）"))
    if not (s and e):
        ng.append("対象期間（開始・終了）を YYYY-MM で書いてください")
    method = g("集計方法")
    if len(method) < 10:
        ng.append("集計方法・出典が要ります（10字以上）")
    unit = g("値の単位") or ""
    cats = [c.strip() for c in re.split(r"[,、\s/]+", g("関連カテゴリ") or "") if c.strip()]
    bad = [c for c in cats if c not in CATS]
    if bad:
        ng.append(f"関連カテゴリに無い値: {', '.join(bad)}（{'/'.join(CATS)}）")
    data = []
    for r in rows:
        v = _num(r["value"])
        if v is None:
            ng.append(f"「{r['label']}」の値が数字ではありません: {r['value']!r}")
            continue
        if re.search(r"株式会社|有限会社|合同会社|店\b|医院|クリニック[^・]", r["label"]) and "業種" not in r["label"]:
            warn.append(f"「{r['label']}」は個社名に見えます。区分名にしてください")
        item = {"label": r["label"], "value": v, "note": r.get("note", "")}
        num, den = _num(r.get("num")), _num(r.get("den"))
        if (num is None) != (den is None):
            ng.append(f"「{r['label']}」は分子と分母の両方が要ります（片方だけでは割合を確かめられません）")
            continue
        if num is not None:
            if den <= 0 or num < 0 or num > den:
                ng.append(f"「{r['label']}」の分子{num:g}・分母{den:g}が成り立ちません")
                continue
            calc = num / den * 100
            if unit in ("%", "％") and abs(calc - v) > 0.1:
                ng.append(f"「{r['label']}」の値{v:g}%が分子分母と合いません（{num:g}/{den:g}={calc:.1f}%）")
                continue
            item.update(num=int(num), den=int(den))
        if r.get("window"):
            item["window"] = r["window"]
        months = _num(r.get("months"))
        if months:
            item["months"] = int(months)
        rs, re_ = _ym(r.get("row_start")), _ym(r.get("row_end"))
        if rs and re_:
            item["row_start"], item["row_end"] = rs, re_
        data.append(item)
    if len(data) < 2:
        ng.append("データは2行以上要ります")
    if ng:
        return None, ng, warn
    top = max(data, key=lambda r: r["value"])
    sentence = g("引用用の一文") or (f"{ORG}が{s}〜{e}に{int(n):,}{unit_n}を集計した「{title}」では、"
                                   f"{top['label']}が{_fmt(top['value'], unit)}で最も大きな値でした")
    ds = {"slug": slug, "title": title, "description": desc, "n": int(n), "n_unit": unit_n,
          "den_label": g("分母の呼び名") or "", "num_label": g("分子の呼び名") or "",
          "neg_label": g("差の呼び名") or "",
          "period": f"{s}〜{e}", "start": s, "end": e, "method": method, "unit": unit,
          "categories": cats or ["ai-marketing"], "sentence": sentence, "rows": data,
          "published": date.today().isoformat(), "modified": date.today().isoformat()}
    if not re.search(r"\d", sentence):
        ng.append("引用用の一文に数字が入っていません")
        return None, ng, warn
    return ds, [], warn


def wilson(k, n, z=1.96):
    """95%信頼区間（Wilson）。母数が小さいほど幅が広い＝数字が当てにならないことを、そのまま示す"""
    import math
    if not n:
        return (0.0, 0.0)
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, (c - h) * 100), min(100.0, (c + h) * 100))


def span_months(a, b):
    """YYYY-MM の差を月で返す"""
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return (yb - ya) * 12 + (mb - ma)


def range_svg(ds):
    """95%の範囲を横線で見せる。表の数字だけでは「幅が広い＝まだ当てにできない」が伝わらない"""
    rows = ds["rows"]
    h = 44 * len(rows) + 40
    x0, w = 150, 420
    p = [f'<svg viewBox="0 0 640 {h}" width="100%" role="img" '
         f'aria-label="項目ごとの95%の範囲" style="max-width:640px;font-family:inherit">']
    for g in range(0, 101, 25):                       # 目盛り
        x = x0 + w * g / 100
        p.append(f'<line x1="{x:.0f}" y1="24" x2="{x:.0f}" y2="{h - 20}" stroke="#e3e8ef" stroke-width="1"></line>'
                 f'<text x="{x:.0f}" y="16" font-size="10" fill="#8a97a8" text-anchor="middle">{g}%</text>')
    for i, r in enumerate(rows):
        y = 40 + i * 44
        lo, hi = wilson(r["num"], r["den"])
        xl, xh = x0 + w * lo / 100, x0 + w * hi / 100
        xv = x0 + w * r["value"] / 100
        p.append(f'<text x="0" y="{y + 4}" font-size="12" fill="#243">{html.escape(r["label"][:14])}</text>'
                 f'<line x1="{xl:.0f}" y1="{y}" x2="{xh:.0f}" y2="{y}" stroke="#9db8e8" stroke-width="8" stroke-linecap="round"></line>'
                 f'<circle cx="{xv:.0f}" cy="{y}" r="6" fill="#1a73e8"></circle>'
                 f'<text x="0" y="{y + 20}" font-size="10" fill="#667">{lo:.1f}〜{hi:.1f}%（{r["den"]}件）</text>')
    p.append(f'<text x="{x0}" y="{h - 4}" font-size="10" fill="#8a97a8">'
             f'● は集計値、横線は95%の範囲。母数が小さいほど横線が長くなります</text></svg>')
    return "".join(p)


def timeline_svg(ds):
    """観測できている期間と判定期間の比較。AIOが100%な理由は「まだ短い」ことにある"""
    rows = [r for r in ds["rows"] if r.get("row_start") and r.get("row_end")]
    if not rows:
        return ""
    obs = [(r, span_months(r["row_start"], r["row_end"])) for r in rows]
    mx = max(max(m for _, m in obs), max((r.get("months") or 0) for r in rows)) or 1
    h = 52 * len(rows) + 34
    x0, w = 150, 400
    p = [f'<svg viewBox="0 0 640 {h}" width="100%" role="img" '
         f'aria-label="観測できている期間と判定期間" style="max-width:640px;font-family:inherit">',
         '<rect x="150" y="4" width="12" height="10" rx="2" fill="#1a73e8"></rect>'
         '<text x="168" y="13" font-size="11" fill="#243">観測できている期間</text>'
         '<rect x="290" y="4" width="12" height="10" rx="2" fill="#f3b23f"></rect>'
         '<text x="308" y="13" font-size="11" fill="#243">判定期間</text>']
    for i, (r, m) in enumerate(obs):
        y = 28 + i * 52
        wo = max(3, w * m / mx)
        p.append(f'<text x="0" y="{y + 12}" font-size="12" fill="#243">{html.escape(r["label"][:14])}</text>'
                 f'<rect x="{x0}" y="{y}" width="{wo:.0f}" height="16" rx="3" fill="#1a73e8"></rect>'
                 f'<text x="{x0 + wo + 8:.0f}" y="{y + 13}" font-size="11" fill="#123">{m}か月</text>')
        wm = r.get("months")
        if wm:
            ww = max(3, w * wm / mx)
            p.append(f'<rect x="{x0}" y="{y + 20}" width="{ww:.0f}" height="12" rx="3" fill="#f3b23f"></rect>'
                     f'<text x="{x0 + ww + 8:.0f}" y="{y + 30}" font-size="10" fill="#667">判定 {wm}か月</text>')
    p.append("</svg>")
    return "".join(p)


def limits_table(ds):
    """この数字で言えること・言えないこと。引用する側がいちばん知りたい部分"""
    rows = sorted(ds["rows"], key=lambda r: r["den"])
    small, big = rows[0], rows[-1]
    lo_s, hi_s = wilson(small["num"], small["den"])
    lo_b, hi_b = wilson(big["num"], big["den"])
    e = html.escape
    u = e(ds.get("n_unit", ""))
    can = [f'{e(big["label"])}は{big["den"]}{u}の集計で、{big["value"]:g}%（95%の範囲 {lo_b:.1f}〜{hi_b:.1f}%）']
    if big.get("months"):
        can.append(f'{e(big["label"])}は{span_months(big["row_start"], big["row_end"])}か月ぶんの契約を、'
                   f'{big["months"]}か月の判定期間で見た結果')
    cannot = [f'{e(small["label"])}の{small["value"]:g}%は母数{small["den"]}{u}で、'
              f'95%の範囲が{lo_s:.1f}〜{hi_s:.1f}%と広い。実力値としては読めない']
    newest = min((r for r in ds["rows"] if r.get("row_start")), key=lambda r: r["row_start"], default=None)
    late = max((r for r in ds["rows"] if r.get("row_start")), key=lambda r: r["row_start"], default=None)
    if late is not None and late.get("row_end"):
        cannot.append(f'{e(late["label"])}は観測が{span_months(late["row_start"], late["row_end"])}か月しかなく、'
                      f'長い目で見た数字は分からない')
    del newest
    cannot.append("業界の平均との比較（他社の数字を同じやり方で集計していないため）")
    li = lambda xs: "".join(f"<li>{x}</li>" for x in xs)
    return ('<section class="section">\n<h2>この数字で言えること・言えないこと</h2>\n'
            '<div class="table-wrap"><table><thead><tr><th style="width:50%">言えること</th>'
            '<th style="width:50%">言えないこと</th></tr></thead><tbody><tr>'
            f'<td><ul style="margin:0;padding-left:1.1em">{li(can)}</ul></td>'
            f'<td><ul style="margin:0;padding-left:1.1em">{li(cannot)}</ul></td>'
            '</tr></tbody></table></div>\n</section>')


def has_counts(ds):
    return all("den" in r for r in ds["rows"]) and len(ds["rows"]) > 0


def totals(ds):
    num = sum(r["num"] for r in ds["rows"])
    den = sum(r["den"] for r in ds["rows"])
    return num, den


def stack_svg(ds):
    """分子と分母を積み上げで見せる。割合だけの棒より、母数の差が一目で分かる"""
    rows = ds["rows"]
    den_max = max(r["den"] for r in rows) or 1
    lab = ds.get("num_label") or "該当"
    neg = ds.get("neg_label") or "非該当"
    h = 46 * len(rows) + 34
    p = [f'<svg viewBox="0 0 640 {h}" width="100%" role="img" '
         f'aria-label="{html.escape(lab)}と{html.escape(neg)}の件数" style="max-width:640px;font-family:inherit">',
         f'<rect x="170" y="4" width="12" height="12" rx="3" fill="#1a73e8"></rect>'
         f'<text x="188" y="14" font-size="11" fill="#243">{html.escape(lab)}</text>'
         f'<rect x="240" y="4" width="12" height="12" rx="3" fill="#d0d7e4"></rect>'
         f'<text x="258" y="14" font-size="11" fill="#243">{html.escape(neg)}</text>']
    for i, r in enumerate(rows):
        y = 30 + i * 46
        w = 380 * r["den"] / den_max
        wn = w * r["num"] / r["den"] if r["den"] else 0
        p.append(f'<text x="0" y="{y + 14}" font-size="12" fill="#243">{html.escape(r["label"][:14])}</text>'
                 f'<text x="0" y="{y + 30}" font-size="10" fill="#667">{r["den"]}{html.escape(ds.get("n_unit", ""))}</text>'
                 f'<rect x="170" y="{y}" width="{w:.0f}" height="22" rx="4" fill="#d0d7e4"></rect>'
                 f'<rect x="170" y="{y}" width="{wn:.0f}" height="22" rx="4" fill="#1a73e8"></rect>'
                 f'<text x="{170 + w + 8:.0f}" y="{y + 16}" font-size="12" fill="#123">'
                 f'{r["num"]} / {r["den"]}（{r["value"]:g}%）</text>')
    p.append("</svg>")
    return "".join(p)


def counts_table(ds):
    lab = ds.get("num_label") or "該当"
    neg = ds.get("neg_label") or "非該当"
    den_l = ds.get("den_label") or "母数"
    e = html.escape
    head = (f"<tr><th>項目</th><th style=\"text-align:right\">{e(den_l)}</th>"
            f"<th style=\"text-align:right\">{e(lab)}</th><th style=\"text-align:right\">{e(neg)}</th>"
            f"<th style=\"text-align:right\">割合</th><th style=\"text-align:right\">95%の範囲</th>"
            f"<th style=\"text-align:right\">1件で動く幅</th></tr>")
    body = []
    for r in ds["rows"]:
        lo, hi = wilson(r["num"], r["den"])
        body.append(f'<tr><td>{e(r["label"])}</td>'
                    f'<td style="text-align:right">{r["den"]}</td>'
                    f'<td style="text-align:right">{r["num"]}</td>'
                    f'<td style="text-align:right">{r["den"] - r["num"]}</td>'
                    f'<td style="text-align:right"><strong>{r["value"]:g}%</strong></td>'
                    f'<td style="text-align:right">{lo:.1f}〜{hi:.1f}%</td>'
                    f'<td style="text-align:right">{100 / r["den"]:.1f}pt</td></tr>')
    tn, td = totals(ds)
    lo, hi = wilson(tn, td)
    body.append(f'<tr style="background:#f3f7ff;font-weight:700"><td>合計</td>'
                f'<td style="text-align:right">{td}</td><td style="text-align:right">{tn}</td>'
                f'<td style="text-align:right">{td - tn}</td>'
                f'<td style="text-align:right">{tn / td * 100:.1f}%</td>'
                f'<td style="text-align:right">{lo:.1f}〜{hi:.1f}%</td>'
                f'<td style="text-align:right">{100 / td:.1f}pt</td></tr>')
    return (f'<div class="table-wrap"><table><thead>{head}</thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def window_table(ds):
    """判定の条件が行ごとに違う場合だけ出す。条件を伏せた割合は比べられない"""
    rows = [r for r in ds["rows"] if r.get("window")]
    if not rows:
        return ""
    e = html.escape
    # 条件が書かれていない行もある。全行を r["window"] で回すと落ちる
    trs = "".join(f'<tr><td>{e(r["label"])}</td><td>{e(r.get("window") or "—")}</td>'
                  f'<td>{e(r.get("note", ""))}</td></tr>' for r in ds["rows"])
    return ('<section class="section">\n<h2>判定の条件</h2>\n'
            '<p>項目ごとに判定の条件が違います。1つの条件に揃えたほうが見栄えはよくなりますが、'
            '性質の違うものを同じ物差しで測ると、比べられない数字になります。条件を明示したうえで並べています。</p>\n'
            f'<div class="table-wrap"><table><thead><tr><th>項目</th><th>判定の条件</th><th>対象</th></tr></thead>'
            f'<tbody>{trs}</tbody></table></div>\n</section>')


def reading_section(ds):
    """この数字の読み方。母数が小さいほど動くことを、実際の値で説明する"""
    rows = sorted(ds["rows"], key=lambda r: r["den"])
    small, big = rows[0], rows[-1]
    tn, td = totals(ds)
    lo, hi = wilson(small["num"], small["den"])
    e = html.escape
    return ('<section class="section">\n<h2>この数字の読み方</h2>\n'
            f'<p>母数が小さい項目ほど、1件の増減で割合が大きく動きます。'
            f'母数がいちばん小さい<strong>{e(small["label"])}</strong>は{small["den"]}{e(ds.get("n_unit", ""))}なので、'
            f'1件変われば{100 / small["den"]:.1f}ポイント動きます。'
            f'いちばん大きい<strong>{e(big["label"])}</strong>は{big["den"]}{e(ds.get("n_unit", ""))}で、'
            f'1件あたり{100 / big["den"]:.1f}ポイントです。</p>\n'
            f'<p>上の表の「95%の範囲」は、同じやり方で母数を増やしていったときに'
            f'落ち着く先の目安です。{e(small["label"])}は{lo:.1f}〜{hi:.1f}%と幅が広く、'
            f'現時点の{small["value"]:g}%をそのまま実力と読むことはできません。'
            f'合計（{td}{e(ds.get("n_unit", ""))}）では{tn / td * 100:.1f}%です。</p>\n'
            f'<p>言い換えると、{e(big["label"])}はおよそ'
            f'{big["den"] / max(1, big["den"] - big["num"]):.0f}件に1件が'
            f'{e(ds.get("neg_label") or "非該当")}です'
            f'（{big["den"]}件中{big["den"] - big["num"]}件）。'
            + (f'判定の条件は「{e(big["window"])}」です。' if big.get("window") else '')
            + '割合だけを見ず、母数と判定の条件と合わせて読んでください。'
            + 'そのために、この3つを同じ表に並べています。</p>\n</section>')


def chart_svg(rows, unit):
    """棒グラフ（インラインSVG・ライブラリ無し）。画像にすると AI が読めないので文字も出す"""
    mx = max(r["value"] for r in rows) or 1
    h = 30 * len(rows) + 10
    parts = [f'<svg viewBox="0 0 640 {h}" width="100%" role="img" aria-label="棒グラフ" style="max-width:640px;font-family:inherit">']
    for i, r in enumerate(rows):
        y = 10 + i * 30
        w = max(2, 380 * r["value"] / mx)
        parts.append(f'<text x="0" y="{y + 15}" font-size="12" fill="#243">{html.escape(r["label"][:16])}</text>'
                     f'<rect x="150" y="{y}" width="{w:.0f}" height="20" rx="4" fill="#1a73e8"></rect>'
                     f'<text x="{150 + w + 6:.0f}" y="{y + 15}" font-size="12" fill="#123">{html.escape(_fmt(r["value"], unit))}</text>')
    parts.append("</svg>")
    return "".join(parts)


def dataset_jsonld(ds):
    url = f"{SITE_URL}/data/{ds['slug']}/"
    return {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": ds["title"], "description": ds["description"], "url": url,
        "creator": {"@type": "Organization", "name": ORG, "url": "https://corp.7senses.co.jp/"},
        "publisher": {"@type": "Organization", "name": ORG, "url": "https://corp.7senses.co.jp/"},
        "datePublished": ds["published"], "dateModified": ds["modified"],
        "temporalCoverage": f"{ds['start']}/{ds['end']}",
        "measurementTechnique": ds["method"],
        "keywords": [CATS.get(c, c) for c in ds["categories"]],
        "isAccessibleForFree": True,
        "creditText": f"出典: {ORG}「{ds['title']}」（{url}）",
        # 分子・分母まで書く。割合だけでは、AIも読者も「何件中何件か」を確かめられない
        "variableMeasured": [
            {"@type": "PropertyValue", "name": r["label"], "value": r["value"], "unitText": ds["unit"],
             **({"description": (f'{ds.get("den_label") or "母数"} {r["den"]}'
                                 f'{ds.get("n_unit", "")}のうち{ds.get("num_label") or "該当"} {r["num"]}'
                                 f'{ds.get("n_unit", "")}'
                                 + (f'（{r["window"]}）' if r.get("window") else ''))} if "den" in r else {})}
            for r in ds["rows"]],
        "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": f"{url}data.csv"}],
    }


def page_html(ds):
    url = f"{SITE_URL}/data/{ds['slug']}/"
    e = html.escape
    trs = "".join(f"<tr><td>{e(r['label'])}</td><td style=\"text-align:right\">{e(_fmt(r['value'], ds['unit']))}</td><td>{e(r.get('note', ''))}</td></tr>" for r in ds["rows"])
    rich = has_counts(ds)
    if rich:
        tl = timeline_svg(ds)
        data_block = (f"<h2>実数で見る</h2>\n{stack_svg(ds)}\n{counts_table(ds)}\n"
                      f'<p style="font-size:.9rem;color:#556;">「95%の範囲」は母数から計算した目安（Wilson信頼区間）、'
                      f'「1件で動く幅」は1件の増減で割合が何ポイント動くかです。どちらも上の実数から導いた値です。</p>\n'
                      f'<p><a href="data.csv" download>CSVをダウンロード</a></p>')
        extra = ('<section class="section">\n<h2>数字の確からしさ</h2>\n'
                 '<p>同じ「90%」でも、母数が10件のときと100件のときでは意味が違います。'
                 '下の図は、集計値（●）と、母数から計算した95%の範囲（横線）です。'
                 '横線が長い項目は、いま出ている数字がそのまま実力とは読めません。</p>\n'
                 f'{range_svg(ds)}\n</section>')
        if tl:
            extra += ('\n\n<section class="section">\n<h2>観測できている期間</h2>\n'
                      '<p>判定期間より、契約を見てきた期間のほうが短ければ、'
                      'その数字はまだ途中経過です。青が観測できている期間、黄色が判定期間です。</p>\n'
                      f'{tl}\n</section>')
        extra += "\n\n" + window_table(ds) + "\n\n" + limits_table(ds) + "\n\n" + reading_section(ds)
    else:
        data_block = (f"<h2>データ</h2>\n{chart_svg(ds['rows'], ds['unit'])}\n"
                      f'<div class="table-wrap"><table><thead><tr><th>項目</th>'
                      f'<th style="text-align:right">値（{e(ds["unit"]) or "—"}）</th><th>備考</th></tr></thead>'
                      f'<tbody>{trs}</tbody></table></div>\n<p><a href="data.csv" download>CSVをダウンロード</a></p>')
        extra = ""
    body = f'''<main class="lab">
<section class="hero">
<span class="kicker">FIRST-PARTY DATA</span>
<h1>{e(ds["title"])}</h1>
<p class="lead">{e(ds["description"])}</p>
<p class="freshness">母数: {ds["n"]:,}{e(ds["n_unit"])}／対象期間: {e(ds["period"])}／集計: {e(ds["method"])}／最終更新: {ds["modified"]}</p>
</section>

<section class="section">
<h2>要点（引用用）</h2>
<blockquote style="border-left:5px solid #1a73e8;padding:.8em 1.2em;background:#f3f7ff;border-radius:0 12px 12px 0;"><p style="margin:0;font-weight:700;">{e(ds["sentence"])}</p></blockquote>
<p style="font-size:.9rem;color:#556;">引用される際は「出典: {ORG}「{e(ds["title"])}」（{url}）」と明記してください。</p>
</section>

<section class="section">
{data_block}
</section>

{extra}

<section class="section">
<h2>集計方法と限界</h2>
<p>{e(ds["method"])}。母数は{ds["n"]:,}{e(ds["n_unit"])}、対象期間は{e(ds["period"])}です。自社で運用・支援した案件の集計であり、業界全体の平均ではありません。個社が特定される情報は含めていません。</p>
</section>
<script type="application/ld+json">{json.dumps(dataset_jsonld(ds), ensure_ascii=False)}</script>
</main>'''
    shell = SHELL.read_text(encoding="utf-8")
    head = shell[: shell.index("<main")]
    tail = shell[shell.index("</main>") + len("</main>"):]
    head = re.sub(r"<title>.*?</title>", f"<title>{e(ds['title'])}｜AI集客ラボの一次データ</title>", head, count=1, flags=re.S)
    head = re.sub(r'<meta name="description" content="[^"]*"', f'<meta name="description" content="{e(ds["description"][:150])}"', head, count=1)
    head = re.sub(r'<link rel="canonical" href="[^"]*"', f'<link rel="canonical" href="{url}"', head, count=1)
    head = re.sub(r'<meta property="og:title" content="[^"]*"', f'<meta property="og:title" content="{e(ds["title"])}"', head, count=1)
    head = re.sub(r'<meta property="og:url" content="[^"]*"', f'<meta property="og:url" content="{url}"', head, count=1)
    head = re.sub(r'<meta property="og:description" content="[^"]*"', f'<meta property="og:description" content="{e(ds["description"][:150])}"', head, count=1)
    return head + body + tail


def load_all():
    out = []
    for p in sorted(DATASETS.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def datasets_html():
    """/data/ と記事の枠に出す一覧"""
    items = load_all()
    if not items:
        return ""
    lis = "".join(f'<li><a href="/data/{d["slug"]}/">{html.escape(d["title"])}</a>'
                  f'<span style="color:#556;font-size:.9rem;">（母数{d["n"]:,}{html.escape(d["n_unit"])}・{html.escape(d["period"])}）</span></li>' for d in items)
    return f'{START}\n<section class="section">\n<h2>自社の一次データ</h2>\n<ul>{lis}</ul>\n</section>\n{END}'


def apply(ds):
    DATASETS.mkdir(parents=True, exist_ok=True)
    prev = DATASETS / f"{ds['slug']}.json"
    if prev.is_file():
        try:
            ds["published"] = json.loads(prev.read_text(encoding="utf-8")).get("published", ds["published"])
        except Exception:
            pass
    prev.write_text(json.dumps(ds, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out = SITE / "data" / ds["slug"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page_html(ds), encoding="utf-8", newline="\n")
    with (out / "data.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if has_counts(ds):
            w.writerow(["項目", ds.get("den_label") or "母数", ds.get("num_label") or "該当",
                        ds.get("neg_label") or "非該当", f"割合（{ds['unit']}）", "95%下限", "95%上限",
                        "判定の条件", "備考"])
            for r in ds["rows"]:
                lo, hi = wilson(r["num"], r["den"])
                w.writerow([r["label"], r["den"], r["num"], r["den"] - r["num"], r["value"],
                            f"{lo:.1f}", f"{hi:.1f}", r.get("window", ""), r.get("note", "")])
        else:
            w.writerow(["項目", f"値（{ds['unit']}）", "備考"])
            for r in ds["rows"]:
                w.writerow([r["label"], r["value"], r.get("note", "")])
    touched = [f"site/data/{ds['slug']}/index.html", f"site/data/{ds['slug']}/data.csv"]
    # /data/ の一覧（印の間を置き換える）
    idx = SITE / "data" / "index.html"
    if idx.is_file():
        h = idx.read_text(encoding="utf-8")
        block = datasets_html()
        if START in h and END in h:
            u = h[: h.index(START)] + block + h[h.index(END) + len(END):]
        else:
            anchor = '<section class="section">\n<h2>この数字の使い方</h2>'
            u = h.replace(anchor, block + "\n\n" + anchor, 1) if anchor in h else h.replace("</main>", block + "\n</main>", 1)
        if u != h:
            idx.write_text(u, encoding="utf-8", newline="\n"); touched.append("site/data/index.html")
    # llms.txt
    llms = SITE / "llms.txt"
    if llms.is_file():
        t = llms.read_text(encoding="utf-8")
        line = f"- [{ds['title']}]({SITE_URL}/data/{ds['slug']}/): {ds['description'][:80]}"
        if f"/data/{ds['slug']}/" not in t:
            if "## 一次データ" not in t:
                t = t.rstrip("\n") + "\n\n## 一次データ（自社で集計した実測値）\n"
            t = t.rstrip("\n") + "\n" + line + "\n"
            llms.write_text(t, encoding="utf-8", newline="\n"); touched.append("site/llms.txt")
    # 一次情報として登録（記事から使われる）
    try:
        import add_fact
        d = add_fact.load(); fid = f"dataset-{ds['slug']}"
        fact = {"id": fid, "sites": ["ai-lab", "corporate", "subsidy"],
                "topic": [CATS.get(c, c) for c in ds["categories"]] + ["一次データ", "実測"],
                "claim": ds["sentence"], "source": f"{ORG} 一次データ「{ds['title']}」 {SITE_URL}/data/{ds['slug']}/",
                "as_of": ds["modified"][:7], "denominator": ds["n"], "period": ds["period"], "verifiable": True}
        others = [f for f in d["facts"] if f["id"] != fid]
        pr = add_fact.problems(fact, {f["id"] for f in others})
        if pr:
            print("  一次情報には登録しません:", "; ".join(pr))
        else:
            d["facts"] = others + [fact]
            add_fact.SRC.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            touched.append("data/first_party_facts.json")
    except Exception as e:
        print(f"  （一次情報の登録をスキップ: {str(e)[:60]}）")
    return touched


def one(src, write):
    import intake_watch as W
    try:
        ds, ng, warn = review(read(src))
    except Exception as e:
        return False, f"読めません（{str(e)[:80]}）"
    if ng:
        note = ("このシートは登録していません。次を直して intake/ に戻してください。\n\n"
                + "\n".join("  - " + x for x in ng) + ("\n\n（警告）\n" + "\n".join("  - " + x for x in warn) if warn else "") + "\n")
        if write:
            W.move(src, W.TODO, note)
        return False, f"{src.name}: 不備{len(ng)}件（intake/todo/ へ移しました）"
    if not write:
        return True, f"{src.name}: 「{ds['title']}」を公開できます（--apply で実行）"
    touched = apply(ds)
    W.move(src, W.DONE)
    return True, f"{src.name}: 「{ds['title']}」を公開しました（{', '.join(touched[:3])}）"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx", nargs="?")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="登録済みのデータからページを作り直す")
    a = ap.parse_args()
    if a.sheet:
        p = make_sheet()
        print(f"記入シートを作りました → {p.relative_to(ROOT).as_posix()}")
        return 0
    if a.rebuild:
        items = load_all()
        for ds in items:
            print("  作り直し:", ", ".join(apply(ds)))
        print(f"\n  {len(items)}件のページを作り直しました")
        return 0
    if not a.xlsx:
        raise SystemExit(__doc__.strip())
    ds, ng, warn = review(read(Path(a.xlsx)))
    for w in warn:
        print(f"  △ {w}")
    for x in ng:
        print(f"  × {x}")
    if ng:
        print(f"\n  不備{len(ng)}件。公開しません")
        return 1
    print(f"  ○ 「{ds['title']}」 母数{ds['n']:,}{ds['n_unit']} {ds['period']} データ{len(ds['rows'])}行")
    print(f"  引用用の一文: {ds['sentence']}")
    if not a.apply:
        print("\n  --apply で公開ページを作り、一次情報に登録します")
        return 0
    touched = apply(ds)
    print("\n  公開:", ", ".join(touched))
    print("  次に python scripts/build.py を通し、コミットしてください")
    return 0


if __name__ == "__main__":
    sys.exit(main())
