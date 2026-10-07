# -*- coding: utf-8 -*-
"""結果の見張り: 「動いたか」ではなく「出来たか」を毎日見る（自動修復の夜の回 JST 0:00 が呼ぶ）。

2026-09-28〜10-03、記事の枠は毎回「成功」で終わっていたが、月の上限の判定が壊れていて
3サイトとも記事が1本も書かれていなかった。実行の成否では分からない。出来たものを数える。

    python scripts/outcome_watch.py              # 前日（JST）を見る
    python scripts/outcome_watch.py --day 2026-10-02
出す印: WATCH_OK=yes|no と「要対応: …」の行（検査が動かなかったときだけ終了コード1）

見るもの:
  1. 記事: サイトごとに、その日に書かれた本数が、書くはずの本数（1日2本・量産の兆候で減らした本数・月の上限）に届いたか
  2. 公開: その日の公開済みの記事が、本番で開けるか（HTTP 200）
  3. 動画: その日に動画が1本上がったか（data/videos.json）
  4. ニュースレター: 月曜の配信が成功したか（GitHub の実行記録）
  5. 問い合わせ: フォームの送信（GA4）と台帳が食い違う日が無いか（lead_reconcile.py・直近3日）
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
JST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (compatible; ss-aio-watch/1.0)"}


def expected_articles(sid, arts, day):
    """その日に書くはずの本数。月の上限に達していれば0、量産の兆候で絞っていればその本数。
    上限は社ごと（daily_audit.site_cap）。全社60で数えると、月30本と決めた社（rules.monthly_cap）が
    上限で止まった日から月末まで「書かれていない」と毎日知らせてしまう（2026-10-07 の点検）"""
    import daily_audit as D
    before = sum(1 for a in arts if a["date"][:7] == day.isoformat()[:7] and a["date"] < day.isoformat()
                 and D._is_published(a, need_review=False))
    cap = D.site_cap(sid)
    if before >= cap:
        return 0
    try:
        import pace
        q = pace.quota(sid)
    except Exception:
        q = D.DAILY_TARGET
    return min(D.DAILY_TARGET, q, cap - before)


def check_articles(day, bad):
    import daily_audit as D
    import sites as S
    cfgs = S.load_all()
    for sid, arts in D.articles_by_site().items():
        name = cfgs[sid].get("name", sid)
        # 前日の不足分として翌日に書いた記事（data/makeup.json）は、その前日の本数に数える（公開日は書いた日のまま）
        done = [a for a in arts if D.counted_day(a) == day.isoformat() and D._is_published(a, need_review=False)]
        want = expected_articles(sid, arts, day)
        print(f"  記事 {name}: {len(done)}/{want}本")
        if len(done) < want:
            bad.append(f"要対応: {name} — {day} の記事が {len(done)}/{want} 本でした（実行は成功でも書かれていない。"
                       "pipeline-multi の「対象サイトの判定」のログで、どの理由で止まったかを確かめる）")
        for a in done:
            if not D._is_published(a):              # 監修待ちはまだ公開されないので、開けなくて正常
                continue
            url = S.article_url(cfgs[sid], {"slug": a["slug"], "category": a.get("category", "")})
            try:
                st = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).status
            except Exception as e:
                st = getattr(e, "code", str(e)[:40])
            if st != 200:
                bad.append(f"要対応: {name} — 公開したはずの記事が開けません（{st}）: {url}")


def check_video(day, bad):
    p = ROOT / "data" / "videos.json"
    if not p.is_file():
        return
    vids = json.loads(p.read_text(encoding="utf-8"))
    # 通常の動画は YouTube で検索されるテーマだけ作るので、ショートだけの日がある（yt_demand）
    n = sum(1 for v in vids.values() if isinstance(v, dict)
            for d in (v.get("date"), (v.get("short") or {}).get("date")) if d == day.isoformat())
    print(f"  動画: {n}本")
    if n == 0:
        bad.append(f"要対応: {day} に動画が1本も上がっていません（daily-video の実行記録を確かめる）")


def check_newsletter(day, bad):
    """月曜 9:00 JST（= 月曜 0:00 UTC）の週刊ニュースレターが成功したか"""
    if day.weekday() != 0:
        return
    try:
        out = subprocess.run(["gh", "run", "list", "--workflow", "digest.yml", "-L", "20",
                              "--json", "conclusion,createdAt,event"], capture_output=True, text=True, timeout=60)
        runs = json.loads(out.stdout or "[]")
    except Exception as e:
        print(f"  ニュースレター: 実行記録を読めません（{str(e)[:40]}）")
        return
    mine = [r for r in runs if r.get("event") == "schedule" and r["createdAt"][:10] == day.isoformat()
            and int(r["createdAt"][11:13]) < 3]
    ok = any(r.get("conclusion") == "success" for r in mine)
    print(f"  ニュースレター: {'配信の実行あり' if ok else '成功した実行なし'}")
    if not ok:
        bad.append(f"要対応: {day}（月）の週刊ニュースレターが成功していません（Weekly Newsletter Digest の実行記録を確かめる）")


def check_leads(bad):
    try:
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "lead_reconcile.py"), "--days", "3"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    except Exception as e:
        bad.append(f"要対応: 問い合わせの突き合わせが動きませんでした（{str(e)[:60]}）")
        return
    # 動かなかったのに「食い違いなし」と出さない（Codex の点検で指摘）。LEADS_OK の印が無ければ照合できていない
    if out.returncode != 0 or "LEADS_OK=" not in out.stdout:
        bad.append(f"要対応: 問い合わせの突き合わせが途中で止まりました（{(out.stdout + out.stderr).strip()[-80:]}）")
        return
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip().startswith("要対応")]
    print(f"  問い合わせ: {'食い違いあり' if lines else '食い違いなし'}")
    bad.extend(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="")
    ap.add_argument("--no-net", action="store_true", help="外へ問い合わせない（門の試験用）")
    a = ap.parse_args()
    day = date.fromisoformat(a.day) if a.day else datetime.now(JST).date() - timedelta(days=1)
    print(f"■ 結果の見張り（{day}）")
    bad = []
    check_articles(day, bad)
    check_video(day, bad)
    if not a.no_net:
        check_newsletter(day, bad)
        check_leads(bad)
    for b in bad:
        print(b)
    print(f"WATCH_OK={'no' if bad else 'yes'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
