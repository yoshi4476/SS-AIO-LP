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
    "「データ」タブは「項目」と「値」の2列が必須です。値は数字だけ（単位は概要タブの「単位」に）。",
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
]
DATA_COLS = ["項目", "値", "備考"]
DATA_EXAMPLE = ["例: 返信率80%以上", "1.6", "新患数の相対値（返信率20%未満＝1.0）"]


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
        d.append(["", "", ""])
    for row in d.iter_rows(min_row=3, min_col=1, max_col=2):
        for c in row:
            c.fill = yellow
    d.column_dimensions["A"].width = 36; d.column_dimensions["B"].width = 14; d.column_dimensions["C"].width = 44
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
            vals = ["" if v is None else str(v).strip() for v in (list(row) + [""] * 3)[:3]]
            if not vals[0] or vals[0].startswith("例:"):
                continue
            got["rows"].append({"label": vals[0], "value": vals[1], "note": vals[2]})
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
        data.append({"label": r["label"], "value": v, "note": r["note"]})
    if len(data) < 2:
        ng.append("データは2行以上要ります")
    if ng:
        return None, ng, warn
    top = max(data, key=lambda r: r["value"])
    sentence = g("引用用の一文") or (f"{ORG}が{s}〜{e}に{int(n):,}{unit_n}を集計した「{title}」では、"
                                   f"{top['label']}が{_fmt(top['value'], unit)}で最も大きな値でした")
    ds = {"slug": slug, "title": title, "description": desc, "n": int(n), "n_unit": unit_n,
          "period": f"{s}〜{e}", "start": s, "end": e, "method": method, "unit": unit,
          "categories": cats or ["ai-marketing"], "sentence": sentence, "rows": data,
          "published": date.today().isoformat(), "modified": date.today().isoformat()}
    if not re.search(r"\d", sentence):
        ng.append("引用用の一文に数字が入っていません")
        return None, ng, warn
    return ds, [], warn


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
        "variableMeasured": [{"@type": "PropertyValue", "name": r["label"], "value": r["value"], "unitText": ds["unit"]} for r in ds["rows"]],
        "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": f"{url}data.csv"}],
    }


def page_html(ds):
    url = f"{SITE_URL}/data/{ds['slug']}/"
    e = html.escape
    trs = "".join(f"<tr><td>{e(r['label'])}</td><td style=\"text-align:right\">{e(_fmt(r['value'], ds['unit']))}</td><td>{e(r.get('note', ''))}</td></tr>" for r in ds["rows"])
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
<h2>データ</h2>
{chart_svg(ds["rows"], ds["unit"])}
<div class="table-wrap"><table><thead><tr><th>項目</th><th style="text-align:right">値（{e(ds["unit"]) or "—"}）</th><th>備考</th></tr></thead><tbody>{trs}</tbody></table></div>
<p><a href="data.csv" download>CSVをダウンロード</a></p>
</section>

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
        w = csv.writer(f); w.writerow(["項目", f"値（{ds['unit']}）", "備考"])
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
    a = ap.parse_args()
    if a.sheet:
        p = make_sheet()
        print(f"記入シートを作りました → {p.relative_to(ROOT).as_posix()}")
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
