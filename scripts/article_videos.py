# -*- coding: utf-8 -*-
"""公開した記事を、毎週まとめて短い動画にして YouTube へ上げる。

**なぜ要るか**: AI検索での可視性と最も強く相関するのは YouTube での言及
（AI Overviews 0.712 / ChatGPT 0.737。Ahrefs・75,000ブランド・Spearman）。
被リンク（0.218）の3倍強い。ところが動画は営業用の3本しか無く、記事は1本も
動画になっていなかった。台本は記事の1文結論を抜き出すだけ（video_make.from_article）
なので、本文に無い話は混ざらない。1本45秒で作れる（実測 160秒の動画・6.8MB）。

相関は因果ではない。効いたかは growth_plan / brand_search の指名検索で毎月見る。

  python scripts/article_videos.py                 # 何を作るかを見る
  python scripts/article_videos.py --write         # 作る（鍵があれば上げる）
  python scripts/article_videos.py --write --limit 3 --days 7
出す印: VIDEOS_OK=yes/no / VIDEOS_MADE=<本> / YT_TOKEN=yes|missing
台帳: data/videos.json（slug → 動画ID）。鍵 youtube-token.json が無ければ作るだけ上げない
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LEDGER = ROOT / "data" / "videos.json"
FINDINGS = ROOT / "automation" / "logs" / "findings.txt"


def load():
    return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.is_file() else {}


def candidates(days, limit):
    """直近 days 日に公開した score>=90 の記事で、まだ動画にしていないもの（新しい順）"""
    import sites as S
    have = load()
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = []
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)

        def g(k):
            x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
            return x.group(1).strip().strip('"') if x else ""
        if p.stem in have or (int(g("score") or 0) < 90) or g("date") < since:
            continue
        sid = S.find_category_owner(g("category")) or ""
        if not sid:
            continue
        rows.append({"slug": p.stem, "site": sid, "title": g("title"), "date": g("date")})
    rows.sort(key=lambda r: r["date"], reverse=True)
    # サイトを回して選ぶ（1サイトに偏らせない）
    out, by = [], {}
    for r in rows:
        by.setdefault(r["site"], []).append(r)
    while len(out) < limit and any(by.values()):
        for sid in sorted(by):
            if by[sid] and len(out) < limit:
                out.append(by[sid].pop(0))
    return out


def note_token_missing():
    line = "要対応: YouTube の鍵（youtube-token.json）が無く、記事動画を作るだけで上げていません（初回だけ python scripts/youtube_upload.py --auth）"
    FINDINGS.parent.mkdir(parents=True, exist_ok=True)
    t = FINDINGS.read_text(encoding="utf-8") if FINDINGS.is_file() else ""
    if line not in t:
        FINDINGS.write_text(t.rstrip("\n") + ("\n" if t else "") + line + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--public", action="store_true", default=True)
    a = ap.parse_args()
    import video_make as VM
    import youtube_upload as YT
    rows = candidates(a.days, a.limit)
    token = YT.TOKEN.is_file()
    print(f"■ 記事動画: 候補 {len(rows)}本（直近{a.days}日・未作成） / YouTubeの鍵 {'あり' if token else '無し'}")
    for r in rows:
        print(f"   [{r['site']:<9}] {r['date']} {r['title'][:44]}")
    if not a.write:
        print(f"YT_TOKEN={'yes' if token else 'missing'}")
        return 0
    ledger, made, ok = load(), 0, True
    for r in rows:
        try:
            script = VM.from_article(r["slug"])
            out = VM.OUT / f'{r["slug"]}.mp4'
            sec = VM.build(script, out, quiet=True)
            rec = {"site": r["site"], "date": date.today().isoformat(), "sec": round(sec),
                   "mp4": str(out.relative_to(ROOT)).replace("\\", "/")}
            if token:
                rec["youtube"] = YT.upload(out, r["slug"], public=a.public, quiet=True)
            ledger[r["slug"]] = rec
            made += 1
            print(f"   ○ {r['slug'][:40]:<40} {sec:.0f}秒" + (f" → youtu.be/{rec['youtube']}" if token else ""))
        except Exception as e:
            ok = False
            print(f"   × {r['slug'][:40]:<40} {str(e)[:80]}")
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    if rows and not token:
        note_token_missing()
    print(f"VIDEOS_OK={'yes' if ok else 'no'}")
    print(f"VIDEOS_MADE={made}")
    print(f"YT_TOKEN={'yes' if token else 'missing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
