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


def audit_group(pdf, month, through=None):
    """3サイト合算レポートの照合。**サイトごとに取り直して足し、印字と突き合わせる。**

    合算は誤りが3倍になる。1サイトの取り違えが、そのまま合計に乗る。
    """
    import json
    import report_verify as RV
    import monthly_report as M

    text, pages = pdf_text(pdf)
    start = f"{month}-01"
    end = through or M.month_end(month)
    tot = {"表示回数": 0, "クリック": 0, "リード": 0}
    per = []
    for f in sorted((ROOT / "sites").glob("*.json")):
        cfg = json.loads(f.read_text(encoding="utf-8"))
        if not cfg.get("domain"):
            continue
        url = cfg.get("gsc_site_url") or f"https://{cfg['domain']}/"
        row = (RV._gsc(url, start, end).get("rows") or [{}])[0]
        imp, clk = int(row.get("impressions", 0)), int(row.get("clicks", 0))
        lead = 0
        if cfg.get("ga4_property_id"):
            ev = RV._ga_events(cfg["ga4_property_id"], start, end)
            lead = ev.get("lead_capture", 0)
            parts = sum(ev.get(k, 0) for k in RV.LEAD_PARTS)
            if parts != lead:
                per.append((cfg["id"], f"リードの傘{lead}と内訳{parts}が不一致"))
        tot["表示回数"] += imp
        tot["クリック"] += clk
        tot["リード"] += lead
        print(f"   {cfg['id']:<10} 表示 {imp:>7,} / クリック {clk:>5,} / リード {lead}")

    print(f"■ {pdf}（{pages}ページ）合算を、サイトごとに取り直して照合")
    bad = [f"{s}: {m}" for s, m in per]
    for key, v in tot.items():
        found = bool(re.search(rf"{v:,}|{v}\b", text))
        print(f"   {key:<8} 合計 {v:>8,}  … 本文に {'OK' if found else '★見つからない'}")
        if not found and v:
            bad.append(f"合算の{key}（{v:,}）が本文に見当たりません")
    if tot["リード"] and re.search(r"(CV|リード)[^。]{0,8}0\s*件", text):
        bad.append(f"リードは合計{tot['リード']}件あるのに「0件」と書かれています")
    if through and "途中経過です" not in text:
        bad.append("途中経過であることが書かれていません")
    # 合算レポートは「3サイト分＋合計」で同じ指標の前月比が4つ並ぶのが正常。
    # 見るのは**同じ値に別の前月比が付いていないか**（353が+25%と+12%の両方など）
    for name in ("セッション", "検索クリック", "検索表示回数", "CV"):
        seen = {}
        pairs = re.findall(rf"{name}[^\d\n]{{0,30}}\n?([\d,]+)件?\n前月比 ([+\-]\d+)%", text)
        pairs += re.findall(rf"{name}は([\d,]+)件?（前月比([+\-]\d+)%）", text)
        pairs += re.findall(rf"{name}は([\d,]+)件?（([+\-]\d+)%）", text)
        for v, pct in pairs:
            seen.setdefault(v, set()).add(pct)
        for v, pcts in seen.items():
            if len(pcts) > 1:
                bad.append(f"「{name}」{v} の前月比が {sorted(pcts)} と食い違います")
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
