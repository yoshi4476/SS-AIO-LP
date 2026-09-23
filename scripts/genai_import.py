# -*- coding: utf-8 -*-
"""Search Console の「生成AIパフォーマンス」CSVを取り込む。

**なぜ手作業が要るか**: このレポートは Search Console API から取れない（2026-09時点）。
`searchanalytics.query` の `type` は web / image / video / news / discover / googleNews のみで、
`aiOverview` も `aiMode` も無い。画面とCSVエクスポートだけ。指標は表示回数のみで、
クリック数・CTRは含まれない。

CLAUDE.md の Phase 7 と 8.5 は「GSC生成AIレポートを取得する」と書いているが、
自動では取れない。**月1回、人がCSVを落として置く**運用にする。

  1. Search Console を開く → 検索パフォーマンス → 生成AI（Search）
  2. 期間を先月に合わせる → エクスポート → CSV
  3. python scripts/genai_import.py <落としたCSV> --site ai-lab

取り込んだ分は data/genai_impressions.json に月ごとに積まれ、月次レポートに出る。

    python scripts/genai_import.py                 # いま何が入っているか
    python scripts/genai_import.py <csv> --site <id>
"""
import argparse
import csv
import io
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "genai_impressions.json"
SITES = ROOT / "sites"

# CSVの見出しは言語で変わる。日本語と英語の両方を見る
COL_PAGE = ("ページ", "page", "上位のページ", "top pages", "url")
COL_IMP = ("表示回数", "impressions", "インプレッション")
COL_DATE = ("日付", "date")

HOW = """  取り込み方（月1回・3サイトぶん。所要5分）

    1. Search Console を開き、対象のプロパティを選ぶ
    2. 左メニューの「検索パフォーマンス」→ 上部のタブで「生成AI（Search）」
    3. 期間を「先月」に合わせる
    4. 右上の「エクスポート」→「CSV をダウンロード」→ ページ別の表を選ぶ
    5. 落としたCSVを指定して取り込む

       python scripts/genai_import.py <CSVのパス> --site ai-lab --month YYYY-MM
       python scripts/genai_import.py <CSVのパス> --site corporate --month YYYY-MM
       python scripts/genai_import.py <CSVのパス> --site subsidy --month YYYY-MM

  **APIからは取れません。** Search Console API の type は web/image/video/news/
  discover/googleNews だけで、aiOverview も aiMode もありません（2026-09時点）。
  指標も表示回数のみで、クリック数はGoogleが出していません。"""


def site_ids():
    return [p.stem for p in sorted(SITES.glob("*.json")) if p.stem != "sample"]


def load():
    return json.loads(STORE.read_text(encoding="utf-8")) if STORE.is_file() else {}


def pick(header, names):
    for i, h in enumerate(header):
        if str(h).strip().lower().lstrip("﻿") in names:
            return i
    return -1


def read_csv(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp932"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeError:
            continue
    else:
        raise SystemExit("文字コードを判別できません（UTF-8 / UTF-16 / Shift_JIS）")
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any(str(x).strip() for x in r)]
    if len(rows) < 2:
        raise SystemExit("行がありません")
    return rows[0], rows[1:]


def to_int(s):
    s = re.sub(r"[^\d]", "", str(s))
    return int(s) if s else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", help="Search Console から落としたCSV")
    ap.add_argument("--site", default="", help="サイトID")
    ap.add_argument("--month", default="", help="対象月（YYYY-MM。省略で今月）")
    a = ap.parse_args()

    store = load()
    if not a.csv:
        # 前月ぶんが揃っているかを見る。APIから取れない以上、
        # 人が落とすのを忘れれば数字は永久に空く。忘れたことに気づける形にする
        t = date.today()
        last = f"{t.year if t.month > 1 else t.year - 1}-{(t.month - 1) or 12:02d}"
        have = set((store.get(last) or {}))
        missing = [s for s in site_ids() if s not in have]

        if store:
            print("■ 取り込み済みの生成AI表示回数")
            for month in sorted(store):
                for sid, d in sorted(store[month].items()):
                    print(f"  {month}  {sid:<10} {d['total']:>7,}表示 / {len(d['pages'])}ページ"
                          f"（取り込み {d['imported']}）")
            print()
        else:
            print("  まだ何も取り込んでいません")

        if missing:
            print(f"  {last} ぶんが未取込です: {', '.join(missing)}")
            print(HOW)
            print("GENAI_OK=no")
        else:
            print(f"  {last} ぶんは3サイトとも取り込み済みです")
            print("GENAI_OK=yes")
        return 0

    if a.site not in site_ids():
        raise SystemExit(f"--site は {' / '.join(site_ids())} のどれかです")
    month = a.month or date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", month):
        raise SystemExit("--month は YYYY-MM で書いてください")

    header, rows = read_csv(a.csv)
    low = [str(h).strip().lower().lstrip("﻿") for h in header]
    i_page, i_imp = pick(low, COL_PAGE), pick(low, COL_IMP)
    if i_imp < 0:
        raise SystemExit(f"表示回数の列が見つかりません（見出し: {header}）")

    pages, total = {}, 0
    for r in rows:
        if i_imp >= len(r):
            continue
        n = to_int(r[i_imp])
        total += n
        if i_page >= 0 and i_page < len(r) and r[i_page].strip():
            key = r[i_page].strip().rstrip("/").split("/")[-1] or r[i_page].strip()
            pages[key] = pages.get(key, 0) + n

    store.setdefault(month, {})[a.site] = {
        "total": total, "pages": pages, "imported": date.today().isoformat(),
        "source": Path(a.csv).name}
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"  {month} / {a.site}: {total:,}表示 を取り込みました（{len(pages)}ページ）")
    if pages:
        print("  表示の多いページ")
        for k, v in sorted(pages.items(), key=lambda x: -x[1])[:5]:
            print(f"      {v:>6,}  {k}")
    print("  ※ このレポートは表示回数のみです。クリック数はGoogleが出していません")
    print("GENAI_OK=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
