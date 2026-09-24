# -*- coding: utf-8 -*-
"""出来上がったPDFの中の数字を、データ源から取り直して照合する。

**report_verify との違い**
  report_verify … レポートを作る前に、データ源どうしを突き合わせる
  report_audit  … 作った**PDFに実際に印字された数字**を読み、取り直した値と照合する

生成の途中で数字が入れ替わる事故（変数の取り違え・単位の誤り・
古い値の使い回し）は、データ源を見るだけでは見つからない。
**紙に出た数字を読んで確かめる**のが、最後の砦。

    python scripts/report_audit.py reports/2026-08/report.pdf --month 2026-08
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def pdf_text(path):
    import pymupdf
    d = pymupdf.open(path)
    return "\n".join(p.get_text() for p in d), d.page_count


def num(s):
    return int(str(s).replace(",", ""))


def audit(pdf, month, through=None):
    import report_verify as RV
    import monthly_report as M

    text, pages = pdf_text(pdf)
    start = f"{month}-01"
    end = through or M.month_end(month)
    site = M.ENV.get("GSC_SITE_URL") or "https://ai.7senses.co.jp/"

    # ── データ源から取り直す ────────────────────────
    tot = (RV._gsc(site, start, end).get("rows") or [{}])[0]
    真 = {"表示回数": int(tot.get("impressions", 0)),
         "クリック": int(tot.get("clicks", 0)),
         "平均順位": round(tot.get("position", 0), 1)}
    ev = RV._ga_events(M.ga4_property(), start, end)
    真["リード"] = ev.get("lead_capture", 0)
    rows = RV._gsc(site, start, end, ["query"], 5000).get("rows", [])
    真["検索語数"] = len(rows)

    print(f"■ {pdf}（{pages}ページ）の数字を、データ源から取り直して照合")
    bad = []

    # ── 1. 表示回数・クリックが本文に出ているか ─────────
    for key in ("表示回数", "クリック", "リード", "検索語数"):
        v = 真[key]
        # 3桁区切りの有無、どちらでも拾う
        pat = rf"{v:,}|{v}\b"
        found = bool(re.search(pat, text))
        mark = "OK" if found else "★見つからない"
        print(f"   {key:<8} データ源 {v:>8,}  … 本文に {mark}")
        if not found and v:
            bad.append(f"{key}（{v:,}）が本文に見当たりません")

    # ── 2. 「CV 0件」「0件」と書いていないか ───────────
    if 真["リード"] and re.search(r"(CV|リード)[^。]{0,8}0\s*件", text):
        bad.append(f"リードは{真['リード']}件あるのに「0件」と書かれています")
    print(f"   「0件」の誤記 … {'★あり' if bad and '0件' in bad[-1] else 'なし'}")

    # ── 3. 語数を「全体」と書いていないか ──────────────
    if re.search(r"全(検索語|語)\s*\d+語", text):
        bad.append("語数を『全体』として書いています"
                   "（query次元は一部しか返しません）")

    # ── 4. 下がった指標に文脈が添えてあるか ──────────────
    if "が下がりました" in text:
        if "ただし同じ期間に" not in text and "改善した指標はありません" not in text:
            bad.append("下がった指標に、同じ期間の改善が添えられていません")
        else:
            print("   下落への文脈 … OK")

    # ── 5. 途中の月なら、その旨が書いてあるか ────────────
    if through:
        if "途中経過です" not in text:
            bad.append("途中経過であることが書かれていません")
        else:
            print("   途中経過の明記 … OK")

    # ── 6. 同じ指標に2つの前月比が載っていないか ──────────
    # 実際に「セッション -13%」と「セッション +12%」が同じページに並んだ。
    # 月の合計をそのまま比べた値と、1日あたりに直した値が混在していた
    for name in ("セッション", "検索クリック", "表示回数", "リード獲得", "CV"):
        pcts = set(re.findall(rf"{name}[^。<]{{0,40}}?([+\-]\d+)%", text))
        if len(pcts) > 1:
            bad.append(f"「{name}」の前月比が {sorted(pcts)} と複数あります"
                       f"（計算方法が混在しています）")
    print(f"   前月比の重複 … {'★あり' if any('前月比が' in b for b in bad) else 'なし'}")

    print()
    for b in bad:
        print(f"   ★ {b}")
    ok = not bad
    print(f"AUDIT_OK={'yes' if ok else 'no'}")
    return ok, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--month", required=True)
    ap.add_argument("--through")
    a = ap.parse_args()
    try:
        ok, _ = audit(a.pdf, a.month, a.through)
    except Exception as e:
        print(f"検査そのものが動きませんでした: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
