# -*- coding: utf-8 -*-
"""公開済みなのに KW台帳で「執筆中」のまま止まった語を見つけ、「公開済み」に直す（週次の検査が --write で呼ぶ）。

なぜ要るか: 2026-10-11、AI集客ラボの「クリニック 建築 事例」「工務店 meo対策」は、記事が9月に公開済み（95点・本番200）
なのに、台帳では9月から「執筆中」のままだった。公開の記録（publish_log）が台帳の行に当たらなかった回がある。
執筆中のまま残ると、在庫（未着手・執筆中）の数と進み具合の表示がずれる。

直すのは、その社の記事の狙う語が台帳の語と同じ（表記ゆれを吸収）で、90点以上で、本番で開ける（200）ものだけ。
記事作成ログには足さない（受け口の kw_published。公開を2回数えない）。お客様の社の語・slug はログに出さない。

    python scripts/kw_published_sync.py            # 見るだけ
    python scripts/kw_published_sync.py --write    # 直す
出す印: KW_SYNC_OK=yes|no（直せなかったものがある）。台帳を読めないときは終了コード1
"""
import argparse
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-pipeline/1.0; kw-sync)"}


def live(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def stuck(rows, arts_by_site, norm):
    """執筆中の行のうち、同じ社に同じ語（正規化して一致）の記事があるもの → [(社, 台帳の語, slug)]"""
    out = []
    for r in rows:
        if str(r.get("status", "")).strip() != "執筆中":
            continue
        sid, kw = r.get("site", ""), r.get("keyword", "")
        for slug, akw in sorted((arts_by_site.get(sid) or {}).items()):
            if norm(akw) == norm(kw):
                out.append((sid, kw, slug))
                break
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    import hub_client as HC
    import hub_sheets as HS
    import kw_plan as KP
    import publish
    import sites as S
    try:
        rows = HC.all_kw(strict=True)
    except Exception as e:
        print(f"台帳を読めません（{str(e)[:80]}）")
        return 1
    cfgs = S.load_all()
    arts = {sid: KP.site_articles(sid) for sid in cfgs}
    found = stuck(rows, arts, HS.norm_kw)
    print(f"■ 執筆中のまま止まった語（公開済みの記事あり）: {len(found)}件")
    fixed, left, failed = 0, 0, []
    for sid, kw, slug in found:
        cfg = cfgs[sid]
        client = bool(cfg.get("client"))
        name = "（お客様の記事）" if client else f"{sid}: {kw}"
        meta = publish.read_meta(ROOT / "articles" / f"{slug}.md") or {}
        try:
            score = int(meta.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        url = S.article_url(cfg, {"slug": slug, "category": meta.get("category", "")}) if meta else ""
        if score < 90 or not url or not live(url):
            left += 1                          # まだ公開されていない（90点未満・本番に無い）。執筆中のままが正しい
            continue
        if not a.write:
            print(f"  直せる: {name}")
            continue
        try:
            r = HC._post({"action": "kw_published", "site": sid, "keyword": kw, "url": url}) or {}
        except Exception as e:
            r = {"error": f"管制塔につながりません（{type(e).__name__}）"}
        if r.get("ok"):
            fixed += 1
            print(f"  公開済みに直しました: {name}")
        else:
            failed.append(name)
            print(f"  要対応: {name} を公開済みに直せませんでした（{r.get('error', '')}）")
    print(f"  直した {fixed}件 / 公開前で執筆中のまま {left}件 / 直せなかった {len(failed)}件")
    print(f"KW_SYNC_OK={'no' if failed else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
