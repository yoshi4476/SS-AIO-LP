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
    2. 左メニューの「生成AIのパフォーマンス」を開く（期間はそのままでよい）
    3. 右上の「エクスポート」→「CSV をダウンロード」（ZIPのまま置いておく）

    ダウンロードフォルダは毎日自動で見ている（タスク「SS生成AIレポート取り込み」）。
    どのサイトか・どの月かは中身から決まり、月ごとに分けて記録して git へ反映する。
    手で取り込むなら: python scripts/genai_import.py --scan --push

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


def tables(path):
    """CSV 1つ、または Search Console が出す ZIP（表ごとの CSV の束）を (名前, 見出し, 行) の列で返す"""
    import zipfile
    path = Path(path)
    if path.suffix.lower() == ".zip":
        out = []
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if n.lower().endswith(".csv"):
                    tmp = ROOT / "data" / ".genai_tmp.csv"
                    tmp.write_bytes(z.read(n))
                    try:
                        out.append((n, *read_csv(tmp)))
                    except SystemExit:
                        pass
                    finally:
                        tmp.unlink(missing_ok=True)
        return out
    return [(path.name, *read_csv(path))]


def detect_site(path, tabs):
    """どのサイトのレポートか。ページのURL、なければファイル名のドメインで決める"""
    import sites as S
    doms = {sid: cfg["domain"].lower().replace("www.", "") for sid, cfg in S.load_all().items()}
    seen = set()
    for _, header, rows in tabs:
        for r in rows[:200]:
            for cell in r:
                m = re.match(r"https?://(?:www\.)?([^/]+)", str(cell).strip())
                if m:
                    seen |= {sid for sid, d in doms.items() if d == m.group(1).lower()}
    if not seen:
        name = Path(path).name.lower()
        seen = {sid for sid, d in doms.items() if d in name}
    return seen.pop() if len(seen) == 1 else ""


def by_month(tabs):
    """日付の表があれば、月ごとの表示回数と、その月に何日ぶんあるか"""
    import calendar
    for _, header, rows in tabs:
        low = [str(h).strip().lower().lstrip("﻿") for h in header]
        i_d, i_i = pick(low, COL_DATE), pick(low, COL_IMP)
        if i_d < 0 or i_i < 0:
            continue
        tot, days = {}, {}
        for r in rows:
            m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", str(r[i_d]).strip()) if i_d < len(r) else None
            if not m or i_i >= len(r):
                continue
            ym = f"{m.group(1)}-{int(m.group(2)):02d}"
            tot[ym] = tot.get(ym, 0) + to_int(r[i_i])
            days[ym] = days.get(ym, 0) + 1
        # 欠けの多い月は記録しない（期間の途中から始まる月・集計の遅れで末尾が欠ける月）。
        # 3日までの欠けは Search Console の反映の遅れとして許す
        full = {}
        for ym, n in days.items():
            y, mo = map(int, ym.split("-"))
            if n >= calendar.monthrange(y, mo)[1] - 3:
                full[ym] = tot[ym]
        return full, sorted(days)
    return None, []


def page_table(tabs):
    for _, header, rows in tabs:
        low = [str(h).strip().lower().lstrip("﻿") for h in header]
        i_p, i_i = pick(low, COL_PAGE), pick(low, COL_IMP)
        if i_p >= 0 and i_i >= 0:
            pages = {}
            for r in rows:
                if max(i_p, i_i) < len(r) and r[i_p].strip():
                    key = re.sub(r"^https?://[^/]+", "", r[i_p].strip()).rstrip("/") + "/"
                    pages[key] = pages.get(key, 0) + to_int(r[i_i])
            return pages
    return None


def ingest(path, write=True, site="", month=""):
    """落としたファイルを置くだけで取り込む。(取り込めたか, 説明) を返す。
    期間を先月に合わせなくてよいよう、日付の表から月ごとに分ける。
    日付の表が無いときだけ、従来どおりファイル全体を1か月ぶんとして扱う"""
    tabs = tables(path)
    if not tabs:
        return False, f"{Path(path).name}: CSV が入っていません"
    sid = site or detect_site(path, tabs)
    if not sid:
        return False, f"{Path(path).name}: どのサイトのレポートか分かりません（--site で指定してください）"
    monthly, seen = by_month(tabs)
    pages = page_table(tabs)
    t = date.today()
    last = f"{t.year if t.month > 1 else t.year - 1}-{(t.month - 1) or 12:02d}"
    if monthly is None:
        # 日付の表が無い: ファイル全体を1か月とみなす（期間を1か月に合わせて落とした前提）
        if pages is None:
            return False, f"{Path(path).name}: 表示回数の列が見つかりません"
        monthly = {month or last: sum(pages.values())}
        page_month = month or last
    else:
        if not monthly:
            return False, (f"{Path(path).name}: 丸1か月ぶんそろった月がありません"
                           f"（含まれる月: {', '.join(seen)}）")
        # ページ別の表は期間全体の合計なので、期間が1か月のときだけその月に付ける
        page_month = seen[0] if len(seen) == 1 else ""
    if not write:
        return True, f"{sid}: {', '.join(f'{m} {v:,}表示' for m, v in sorted(monthly.items()))}（--apply で記録）"
    store = load()
    for ym, v in monthly.items():
        cur = store.setdefault(ym, {}).get(sid) or {}
        store[ym][sid] = {"total": v,
                          "pages": pages if (ym == page_month and pages) else cur.get("pages", {}),
                          "imported": date.today().isoformat(), "source": Path(path).name}
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    note = "" if page_month else "（ページ別は期間が複数月のため記録せず）"
    return True, f"{sid}: {', '.join(f'{m} {v:,}表示' for m, v in sorted(monthly.items()))} を記録{note}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", help="Search Console から落としたCSV")
    ap.add_argument("--site", default="", help="サイトID")
    ap.add_argument("--month", default="", help="対象月（YYYY-MM。省略で先月）")
    ap.add_argument("--scan", action="store_true", help="ダウンロードフォルダに落ちたレポートを取り込む")
    ap.add_argument("--push", action="store_true", help="取り込んだら git へ反映する（--scan と使う）")
    a = ap.parse_args()
    if a.scan:
        return scan(a.push)

    store = load()
    t = date.today()
    last = f"{t.year if t.month > 1 else t.year - 1}-{(t.month - 1) or 12:02d}"
    if not a.csv:
        # 前月ぶんが揃っているかを見る。APIから取れない以上、
        # 人が落とすのを忘れれば数字は永久に空く。忘れたことに気づける形にする
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

    if a.site and a.site not in site_ids():
        raise SystemExit(f"--site は {' / '.join(site_ids())} のどれかです")
    if a.month and not re.fullmatch(r"\d{4}-\d{2}", a.month):
        raise SystemExit("--month は YYYY-MM で書いてください")
    ok, why = ingest(a.csv, True, a.site, a.month)
    print(f"  {'○' if ok else '×'} {why}")
    print("  ※ このレポートは表示回数のみです。クリック数はGoogleが出していません")
    print(f"GENAI_OK={'yes' if ok else 'no'}")
    return 0


# ダウンロードフォルダに落ちたレポートを拾う。人の作業を「ブラウザで落とす」だけにする
DOWNLOADS = Path.home() / "Downloads"
SEEN = ROOT / "automation" / "logs" / "genai_seen.json"
AI_MARK = re.compile(r"生成\s*AI|AI\s*(Overview|モード|Mode|による概要)|generative|ai[-_ ]?(overview|mode)", re.I)


def is_genai(path, tabs):
    """生成AIのレポートか。ファイル名か、フィルタの表に印があるものだけ（他のCSVを誤って取り込まない）"""
    if AI_MARK.search(Path(path).name):
        return True
    return any(AI_MARK.search(" ".join(map(str, h)) + " " + " ".join(" ".join(map(str, r)) for r in rows[:50]))
               for n, h, rows in tabs if re.search(r"filter|フィルタ", n, re.I))


def scan(push=False):
    seen = json.loads(SEEN.read_text(encoding="utf-8")) if SEEN.is_file() else {}
    cutoff = date.today().toordinal() - 60
    got = []
    for p in sorted(DOWNLOADS.glob("*")):
        if p.suffix.lower() not in (".zip", ".csv") or not p.is_file():
            continue
        if date.fromtimestamp(p.stat().st_mtime).toordinal() < cutoff:
            continue
        sig = f"{p.name}|{p.stat().st_size}|{int(p.stat().st_mtime)}"
        if sig in seen:
            continue
        try:
            tabs = tables(p)
        except Exception:
            continue
        if not detect_site(p, tabs):
            continue
        if not is_genai(p, tabs):
            # 自サイトのURLを含むが生成AIの印が無い。形式が想定と違う可能性があるので名前だけ出す
            print(f"  － 見送り（生成AIのレポートと確認できない）: {p.name}")
            continue
        ok, why = ingest(p)
        print(f"  {'○' if ok else '×'} {why}")
        seen[sig] = date.today().isoformat()
        got.append(ok)
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    SEEN.write_text(json.dumps(seen, ensure_ascii=False, indent=1), encoding="utf-8")
    if not got:
        print("  新しいレポートはありません")
    if push and any(got):
        import subprocess
        run = lambda *c: subprocess.run(c, cwd=ROOT, capture_output=True, text=True)
        run("git", "add", str(STORE.relative_to(ROOT)))
        run("git", "commit", "-m", "生成AIレポートを取り込む（ダウンロードから自動）")
        run("git", "pull", "--rebase", "--autostash")
        r = run("git", "push")
        print("  反映しました" if r.returncode == 0 else f"  反映できませんでした: {r.stderr[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
