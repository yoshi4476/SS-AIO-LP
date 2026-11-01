# -*- coding: utf-8 -*-
"""案件台帳（1案件1行）から、記事に使う一次情報と体験を数えて登録する。

**なぜ要るか**: 材料の質問シートは主題ごと（135の主題）に同じ記録を聞き、2026-11-01 に返った答えの多くが
「質問に対応する記録はありません。不足しているのは、対象案件の全件一覧・問題の発生件数・理由別内訳です」だった。
足りないのはどの主題でも同じ数種類の記録なので、1案件1行の台帳を1枚書いてもらい、機械が業務・指標・問題ごとに
「何社のうち」「何件のうち」を数える。**数字は台帳の行から数えるだけで、AI に文や数字を作らせない**（架空の実績は優良誤認）。

    python scripts/case_ledger.py --make --site ai-lab        # 記入用の台帳をデスクトップに作る
    python scripts/case_ledger.py --apply <xlsx>              # 何を登録するかを見る
    python scripts/case_ledger.py --apply <xlsx> --write      # 登録する（intake_watch も呼ぶ）

数え方の決まり（0.1節）: 割合は母数10以上だけ。2〜9社は幅と中央値を出さず「◯社のうち◯社」と各社の値。
同じ台帳を何度入れても同じ id を上書きする（行を直して入れ直せば数字が直る）。
"""
import argparse
import hashlib
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
OWN_FACTS = ROOT / "data" / "first_party_facts.json"
OWN_EXPS = ROOT / "data" / "experiences.json"
MARK = "案件台帳"
MIN_RATE = 10

CASE_COLS = ["案件番号（社名は書かない）", "業種", "規模（従業員数）", "地域", "業務の種類", "開始月", "終了月（続いていれば空）",
             "測った指標", "前", "後", "単位", "前と後を測った期間", "記事に出してよいか"]
EVENT_COLS = ["案件番号", "起きた月", "業務の種類", "起きたこと", "件数", "対象の総件数", "理由", "決めた対応", "結果",
              "記事に出してよいか"]
# 書く人が選びやすい候補（ほかの語も書ける）。お客様の社は共通の候補だけ
CHOICES = {
    "ai-lab": {"業務": ["AIO・SEOの記事運用", "MEO・口コミ返信", "サイト改善", "広告運用", "SNS運用"],
               "指標": ["検索順位", "検索の表示回数", "検索のクリック数", "問い合わせ件数", "予約件数", "AIの回答での引用回数"]},
    "corporate": {"業務": ["記帳代行", "請求書の発行代行", "請求書の受け取り・支払処理", "経費精算", "給与計算", "月次決算",
                           "インボイス対応", "システム開発"],
                  "指標": ["月の作業時間", "締めの日数", "月の処理件数", "誤りの件数", "差し戻しの件数"]},
    "": {"業務": [], "指標": ["月の作業時間", "工数（人日）", "月の処理件数", "問い合わせ件数", "誤りの件数"]},
}
EXAMPLE_CASE = ["例", "歯科医院", "8", "大阪府", "MEO・口コミ返信", "2026-04", "", "問い合わせ件数", "3", "11", "件/月",
                "2026-03 と 2026-09", "可"]
EXAMPLE_EVENT = ["例", "2026-06", "MEO・口コミ返信", "返信の差し戻し", "4", "120", "定型文の使い回しを指摘された",
                 "返信を1件ずつ書き分け、院長の確認を挟む", "翌月の差し戻し0件", "可"]


def choices(site):
    import sites as S
    return CHOICES.get(site) or CHOICES[""] if not S.is_client(site) else CHOICES[""]


def make(site, out_dir, today=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    import sites as S
    today = today or date.today().isoformat()
    ch = choices(site)
    wb = Workbook()
    how = wb.active
    how.title = "使い方"
    for r in ("1案件を1行で書きます（数字を測った指標が2つあれば2行）。社名は書かず、案件番号（A1・A2…）で区別します。",
              "数字は、業務の記録（会計ソフト・請求の控え・作業時間の記録・GSC など）から写してください。覚えや見込みは書かないでください。",
              "「問題と判断」には、起きた問題1件を1行で。件数と対象の総件数があれば「何件のうち何件」として登録します。",
              "「記事に出してよいか」が「可」の行だけを使います。「例」の行は読みません。",
              "書いたら、このファイルを intake/ に入れてください（機械が数えて登録し、結果を知らせます）。"):
        how.append([r])
    how.column_dimensions["A"].width = 120
    head = PatternFill("solid", start_color="1F4E78")
    for title, cols, ex in (("案件", CASE_COLS, EXAMPLE_CASE), ("問題と判断", EVENT_COLS, EXAMPLE_EVENT)):
        ws = wb.create_sheet(title)
        ws.append(cols)
        ws.append(ex)
        for c in ws[1]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), head
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for c in ws[2]:
            c.font = Font(color="808080", italic=True)
        for i in range(1, len(cols) + 1):
            ws.column_dimensions[chr(64 + i)].width = 18
        ok = DataValidation(type="list", formula1='"可,不可"', allow_blank=True)
        ws.add_data_validation(ok)
        ok.add(f"{chr(64 + len(cols))}3:{chr(64 + len(cols))}500")
        lists = [("業務の種類", ch["業務"]), ("測った指標", ch["指標"])]
        for name, vals in lists:
            if name in cols and vals:
                col = chr(65 + cols.index(name))
                dv = DataValidation(type="list", formula1='"' + ",".join(vals) + '"', allow_blank=True,
                                    showErrorMessage=False)       # 候補に無い語も書ける
                ws.add_data_validation(dv)
                dv.add(f"{col}3:{col}500")
        ws.freeze_panes = "A3"
    mark = wb.create_sheet(MARK)
    mark.append(["site", site])
    mark.sheet_state = "hidden"
    name = re.sub(r'[\\/:*?"<>|]', "_", S.load(site).get("name", site))
    out = Path(out_dir) / f"{MARK}_{name}_{today}.xlsx"
    wb.save(out)
    return out


def _num(v):
    if v is None or str(v).strip() == "":
        return None
    try:
        return float(str(v).replace(",", "").replace("，", "").strip())
    except ValueError:
        return None


def _ym(v):
    if hasattr(v, "year"):
        return f"{v.year}-{v.month:02d}"
    m = re.match(r"^\s*(\d{4})\s*[-/年.]\s*(\d{1,2})", str(v or ""))
    return f"{m.group(1)}-{int(m.group(2)):02d}" if m else ""


def _fmt(x):
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,.1f}"


def read(src):
    """(site, 案件の行, 問題の行, 読まなかった行の数)。可の行だけ"""
    from openpyxl import load_workbook
    wb = load_workbook(src, data_only=True)
    site = str(wb[MARK]["B1"].value or "").strip()
    out, skipped = {}, 0
    for title, cols in (("案件", CASE_COLS), ("問題と判断", EVENT_COLS)):
        rows = []
        for r in list(wb[title].iter_rows(min_row=2, values_only=True)):
            row = {c: (r[i] if i < len(r) else None) for i, c in enumerate(cols)}
            if not any(v not in (None, "") for v in row.values()) or str(r[0] or "").strip() == "例":
                continue
            if not str(row["記事に出してよいか"] or "").strip().startswith(("可", "○", "〇")):
                skipped += 1
                continue
            rows.append({k: (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
        out[title] = rows
    return site, out["案件"], out["問題と判断"], skipped


def _fid(site, *key):
    return f"{site}-case-" + hashlib.sha1("|".join(key).encode("utf-8")).hexdigest()[:10]


def count(site, cases, events, today=None):
    """(一次情報, 体験, 直してほしい行)。文は決まった型だけで作る"""
    today = today or date.today().isoformat()
    now = today[:7]
    facts, exps, bad = [], [], []
    by_work = defaultdict(dict)
    for c in cases:
        no, work = str(c[CASE_COLS[0]] or "").strip(), str(c["業務の種類"] or "").strip()
        start = _ym(c["開始月"])
        if not (no and work and start):
            bad.append(f"案件 {no or '（番号なし）'}: 案件番号・業務の種類・開始月のどれかが空です")
            continue
        by_work[work].setdefault(no, {"業種": str(c["業種"] or "").strip(), "start": start,
                                      "end": _ym(c["終了月（続いていれば空）"]) or now})
    for work, cs in by_work.items():
        n = len(cs)
        lo, hi = min(x["start"] for x in cs.values()), max(x["end"] for x in cs.values())
        kinds = Counter(x["業種"] for x in cs.values() if x["業種"])
        mix = "・".join(f"{k}{v}社" for k, v in kinds.most_common(4))
        facts.append({"id": _fid(site, "work", work), "topic": [work], "period": f"{lo}〜{hi}", "denominator": n,
                      "claim": f"{lo}〜{hi}に{work}を担当したのは{n}社です" + (f"（{mix}）" if mix else "") + "。"})
    by_metric = defaultdict(list)
    for c in cases:
        b, a = _num(c["前"]), _num(c["後"])
        metric, work = str(c["測った指標"] or "").strip(), str(c["業務の種類"] or "").strip()
        if not metric:
            continue
        if b is None or a is None:
            bad.append(f"案件 {c[CASE_COLS[0]]}: 「{metric}」の前と後に数字を入れてください")
            continue
        by_metric[(work, metric, str(c["単位"] or "").strip())].append((c, b, a))
    for (work, metric, unit), rows in by_metric.items():
        n = len(rows)
        period = str(rows[0][0]["前と後を測った期間"] or "").strip()
        if n == 1:
            c, b, a = rows[0]
            who = (c["業種"] or "") + (f"（従業員{c['規模（従業員数）']}名）" if c["規模（従業員数）"] else "")
            claim = (f"{work}の1社{('・' + who) if who else ''}では、{metric}が{_fmt(b)}{unit}から{_fmt(a)}{unit}になりました"
                     + (f"（{period}）" if period else "") + "。")
        else:
            down = sum(1 for _, b, a in rows if a < b)
            up = sum(1 for _, b, a in rows if a > b)
            claim = f"{work}の{n}社で{metric}を前と後で測ると、減った{down}社・増えた{up}社"
            if n >= 3:
                claim += (f"、中央値は{_fmt(statistics.median(b for _, b, _ in rows))}{unit}から"
                          f"{_fmt(statistics.median(a for _, _, a in rows))}{unit}")
            else:
                claim += "（" + "・".join(f"{_fmt(b)}→{_fmt(a)}{unit}" for _, b, a in rows) + "）"
            if n >= MIN_RATE:
                claim += f"。減った割合は{round(down / n * 100)}%"
            claim += "でした。"
        facts.append({"id": _fid(site, "metric", work, metric, unit), "topic": [work, metric], "denominator": n,
                      "period": period, "claim": claim})
    by_event = defaultdict(list)
    for e in events:
        what, work = str(e["起きたこと"] or "").strip(), str(e["業務の種類"] or "").strip()
        k = _num(e["件数"])
        if not (what and work and k is not None):
            bad.append(f"問題 {e['案件番号'] or '（番号なし）'}: 業務の種類・起きたこと・件数のどれかが空です")
            continue
        by_event[(work, what)].append(e)
        if e["理由"] and e["決めた対応"]:
            when = _ym(e["起きた月"])
            text = (f"{when + '、' if when else ''}{work}の案件で「{what}」が{_fmt(k)}件起きました。原因は{e['理由']}。"
                    f"{e['決めた対応']}ことにし" + (f"、{e['結果']}" if e["結果"] else "た") + "。")
            exps.append({"id": _fid(site, "exp", str(e["案件番号"]), what, when), "key": work, "text": text, "when": when})
    for (work, what), rows in by_event.items():
        k = sum(_num(e["件数"]) for e in rows)
        tots = [_num(e["対象の総件数"]) for e in rows]
        months = sorted(m for m in (_ym(e["起きた月"]) for e in rows) if m)
        period = f"{months[0]}〜{months[-1]}" if months else ""
        claim = f"{work}で「{what}」は{_fmt(k)}件"
        den = None
        if all(t is not None for t in tots):
            den = sum(tots)
            claim = f"{work}の対象{_fmt(den)}件のうち、「{what}」は{_fmt(k)}件"
            if den >= MIN_RATE:
                claim += f"（{k / den * 100:.1f}%）"
        why = Counter(str(e["理由"]).strip() for e in rows if e["理由"])
        if len(why) > 1:
            claim += "。理由は" + "・".join(f"{r}{c}件" for r, c in why.most_common(4))
        claim += (f"でした（{period}）。" if period else "でした。")
        facts.append({"id": _fid(site, "event", work, what), "topic": [work, what], "period": period,
                      "denominator": den, "claim": claim})
    return facts, exps, bad


def write(site, facts, exps, today=None):
    """同じ id は上書き（台帳を直して入れ直すと数字が直る）。お客様の社は非公開の置き場、自社は data/"""
    import private_store as P
    today = today or date.today().isoformat()
    if P.is_client(site):
        fd = P.read_json(site, "facts.json", {"facts": []}) or {"facts": []}
        ed = P.read_json(site, "experiences.json", {"experiences": []}) or {"experiences": []}
    else:
        fd = json.loads(OWN_FACTS.read_text(encoding="utf-8"))
        ed = json.loads(OWN_EXPS.read_text(encoding="utf-8"))
    fs = {str(x.get("id")): x for x in fd.setdefault("facts", [])}
    for it in facts:
        row = {"id": it["id"], "sites": [site], "topic": it["topic"][:6], "claim": it["claim"],
               "source": f"{MARK}（{today}）", "as_of": today[:7], "verifiable": True}
        for k in ("period", "denominator"):
            if it.get(k):
                row[k] = it[k]
        if it["id"] in fs:
            fs[it["id"]].clear()
            fs[it["id"]].update(row)
        else:
            fd["facts"].append(row)
    es = {str(x.get("id")): x for x in ed.setdefault("experiences", [])}
    for it in exps:
        row = {"id": it["id"], "sites": [site], "key": it["key"], "text": it["text"], "when": it["when"], "added": today}
        if it["id"] in es:
            es[it["id"]].update(row)
        else:
            ed["experiences"].append(row)
    if P.is_client(site):
        P.write_json(site, "facts.json", fd)
        P.write_json(site, "experiences.json", ed)
    else:
        OWN_FACTS.write_text(json.dumps(fd, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        OWN_EXPS.write_text(json.dumps(ed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def apply(src, do_write=False, today=None):
    """intake_watch から呼ぶ。(登録できたか, 説明)。お客様の社の語はログに出さない（件数だけ）"""
    import sites as S
    site, cases, events, skipped = read(src)
    if not site:
        return False, "案件台帳に社の印がありません（--make で作り直してください）"
    facts, exps, bad = count(site, cases, events, today)
    who = "（お客様の社）" if S.is_client(site) else site
    msg = (f"{who}: 案件 {len(cases)}行・問題 {len(events)}行から、一次情報 {len(facts)}件・体験 {len(exps)}件を"
           f"{'登録しました' if do_write and (facts or exps) else '登録できます（--write で実行）'}"
           + (f"。不可・空欄で読まなかった行 {skipped}行" if skipped else "")
           + (f"。直してほしい行 {len(bad)}行" if bad else ""))
    if not S.is_client(site):
        for f in facts:
            print(f"   - {f['claim']}")
    for b in bad[:20]:
        print(f"   ※ {b if not S.is_client(site) else re.sub(r'「[^」]*」', '「…」', b)}")
    if do_write and (facts or exps):
        write(site, facts, exps, today)
    return bool(facts or exps), msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--make", action="store_true")
    ap.add_argument("--site", default="")
    ap.add_argument("--out", default=str(Path.home() / "Desktop"))
    ap.add_argument("--apply", default="")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    if a.make:
        print(make(a.site, a.out))
    elif a.apply:
        print(apply(a.apply, a.write)[1])
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
