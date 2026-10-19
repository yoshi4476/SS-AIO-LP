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
import re
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
            # 本数の大小ではなく「台帳で公開済みなのに公開中に無い記事」を1本ずつ見る（2026-10-20）。件数で比べていた間は、
            # 検索から外した記事（noindex。URL は残す決まりで公開中の一覧には入らない）と、公開から日が浅く一覧の控えに
            # まだ無い記事まで「取り下げの残り」と数えていた。本当の残り（301 で取り下げた記事）だけを出す
            from datetime import date as _date, timedelta as _td
            import private_store as PS
            recent = (_date.today() - _td(days=14)).isoformat()
            idx = EI.load()["sites"]
            ledger, left = {}, {}
            for k in HC.all_kw(strict=True):
                if str(k.get("status", "")).strip() != "公開済み":
                    continue
                sid = k.get("site")
                ledger[sid] = ledger.get(sid, 0) + 1
                slug = str(k.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
                if not slug or sid not in idx or slug in {x.get("slug") for x in idx[sid]}:
                    continue
                art = ROOT / "articles" / f"{slug}.md"
                t = art.read_text(encoding="utf-8-sig", errors="replace") if art.is_file() else ""
                if re.search(r"^noindex:\s*true", t, re.M):
                    continue
                m = re.search(r"^date:\s*(\S+)", t, re.M)
                if m and m.group(1)[:10] >= recent:
                    continue
                left.setdefault(sid, []).append(slug)
            ran += 1
            for sid in sorted(idx):
                bad = left.get(sid, [])
                print(f"  {'×' if bad else '○'} {sid}: 台帳の公開済み {ledger.get(sid, 0)}本 / 公開中 {len(idx[sid])}本"
                      f"（台帳に残った取り下げ {len(bad)}本。検索から外した記事・公開14日以内は除く）")
                if bad:
                    found.append(f"要対応: {sid} の台帳で公開済みなのに公開中に無い記事 {len(bad)}本（取り下げた記事が台帳に残っている。"
                                 "hub_client.retire_kw(社, [語], 理由, force=True) で「取り下げ」にする）: "
                                 + "、".join(PS.shown(s) for s in bad[:5]))
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
