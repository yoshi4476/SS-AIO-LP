# -*- coding: utf-8 -*-
"""過去の誤り（分析・レポート）のうち、本番のデータに当てないと確かめられないもの。

門（tests/gates_history_c.py）はスタブで「取れなかったら止まるか」を見る。
ここは実際に取りに行き、取れていない・食い違っているものを知らせる。

  1. 各社の月次の照合が、その社の GSC・GA4 を読めるか
     （2026-09-25: corporate/subsidy を AI集客ラボの数字で照合し、毎回届かなかった）
  2. 食い合い審査が、その社の GSC 実績を読めているか
     （読めないまま「着手可」を返していた）
  3. 公開本数が、台帳の記録と公開中のページで食い違っていないか
     （2026-08-05: 取り下げを含めて「コーポレート12本」と報告し、実際は5本）

    python scripts/history_checks_c.py
出す印: HISTC_OK=yes|no|unknown（見つかっても終了コード0。何も確かめられなかったときだけ1）
"""
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    import sites as S
    found, ran, skipped = [], 0, []
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=27)

    print("■ 各社の照合が、その社のデータを読めるか")
    try:
        import report_verify as RV
    except Exception as e:
        print(f"  照合の部品を読み込めません（{type(e).__name__}）")
        skipped.append("月次照合の取得先")
        RV = None
    for sid, cfg in S.load_all().items():
        if RV is None:
            break
        url = f"https://{cfg['domain']}/"
        try:
            rows = RV._gsc(url, str(start), str(end)).get("rows") or []
            ran += 1
            print(f"  ○ {sid}: GSC {url} 表示{int((rows or [{}])[0].get('impressions', 0)):,}")
        except Exception as e:
            found.append(f"要対応: {sid} の月次照合が {url} の GSC を読めません（{str(e)[:60]}）")
            print("  " + found[-1])
        prop = cfg.get("ga4_property_id")
        if prop:
            try:
                RV._ga_events(str(prop), str(start), str(end))
                ran += 1
                print(f"  ○ {sid}: GA4 {prop}")
            except Exception as e:
                found.append(f"要対応: {sid} の月次照合が GA4 {prop} を読めません（{str(e)[:60]}）")
                print("  " + found[-1])

    print("\n■ 食い合い審査が、その社の GSC 実績を読めているか")
    try:
        import kw_guard as KG
        for sid in S.load_all():
            n = len(KG.gsc_rows(sid))
            if getattr(KG.gsc_rows, "failed", ""):
                found.append(f"要対応: {sid} の食い合い審査が GSC を読めません（{KG.gsc_rows.failed}）")
                print("  " + found[-1])
            else:
                ran += 1
                print(f"  ○ {sid}: 実績 {n}行")
    except Exception as e:
        print(f"  動かせません（{type(e).__name__}: {str(e)[:60]}）")
        skipped.append("食い合い審査のGSC")

    print("\n■ 公開本数: 台帳の記録と、公開中のページ")
    try:
        import hub_client as HC
        import external_index as EI
        if not HC.enabled():
            print("  管制塔が未接続のため比べません（HUB_URL）")
            skipped.append("公開本数の突き合わせ")
        else:
            ledger = {}
            for k in HC.all_kw(strict=True):
                if str(k.get("status", "")).strip() == "公開済み":
                    ledger[k.get("site")] = ledger.get(k.get("site"), 0) + 1
            live = {s: len(v) for s, v in EI.load()["sites"].items()}
            ran += 1
            for sid in sorted(live):
                a, b = ledger.get(sid, 0), live[sid]
                mark = "○" if a <= b else "×"
                print(f"  {mark} {sid}: 台帳の公開済み {a}本 / 公開中 {b}本")
                # 公開中には当パイプライン以前の記事も入るので、多いのは正常。台帳の方が多いのは取り下げの残り
                if a > b:
                    found.append(f"要対応: {sid} の台帳の公開済み {a}本が公開中の {b}本より多い"
                                 "（取り下げた記事が台帳に残っている。レポートは公開中で数えるが、台帳も直す）")
    except Exception as e:
        print(f"  比べられません（{type(e).__name__}: {str(e)[:60]}）")
        skipped.append("公開本数の突き合わせ")

    if not ran:
        print("\n何も確かめられませんでした（鍵・接続を確認）")
        return 1
    print()
    for f in found:
        print(f)
    # 確かめられなかった項目があるのに yes と出さない（この検査が見張っている誤りそのもの）
    if skipped:
        print("確かめられなかった項目: " + "・".join(skipped))
    print("HISTC_OK=" + ("no" if found else "unknown" if skipped else "yes"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
