# -*- coding: utf-8 -*-
"""公開した記事を、毎日1本ずつ短い動画にして YouTube へ上げる。

1日1本にしているのは、同じ型の動画を大量に上げると YouTube が量産コンテンツとして
扱い、チャンネルごと表示を抑えられるため（1日6本は危ない）。
記事をリライトして読み上げ部分の数字が変わったら、古い動画は限定公開に下げ（消さない）、
その記事を作り直しの列の先頭に置く。作り直しも1日1本の枠の中で行う。

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


_CFG = {}


def focus(row):
    """動画にする優先度。打ち出しから外したテーマ（drop_kw・配分0のカテゴリ）は None（作らない）。
    主力の業種（kw_seeds.priority）が題にあれば +2、主力のカテゴリなら +1"""
    import sites as S
    if not _CFG:
        _CFG.update(S.load_all())
    cfg = _CFG.get(row.get("site", ""), {})
    title = (row.get("title") or "").lower()
    if any(w and w.lower() in title for w in cfg.get("drop_kw") or []):
        return None
    if (cfg.get("category_mix") or {}).get(row.get("category", "")) == 0:
        return None
    pri = (cfg.get("kw_seeds") or {}).get("priority") or []
    return (2 if any(w in (row.get("title") or "") for w in pri) else 0) + \
           (1 if row.get("category") == cfg.get("main_category") else 0)


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
        row = {"slug": p.stem, "site": sid, "title": g("title"), "date": g("date"), "category": g("category")}
        if focus(row) is None:
            continue
        rows.append(row)
    # 打ち出しの業種・主力の分野を先に（見られて社名が出る動画を優先する）。同じなら新しい順
    rows.sort(key=lambda r: (focus(r), r["date"]), reverse=True)
    # サイトを回して選ぶ（1サイトに偏らせない）
    out, by = [], {}
    for r in rows:
        by.setdefault(r["site"], []).append(r)
    while len(out) < limit and any(by.values()):
        for sid in sorted(by):
            if by[sid] and len(out) < limit:
                out.append(by[sid].pop(0))
    return out


def _nums(script):
    """読み上げる文に含まれる数字（時点表記の年月も含む）。記事と動画の食い違いはここで見る"""
    say = " ".join(s["say"] for s in script.get("segments", []))
    return sorted(set(re.findall(r"\d[\d,.]*", say)))


def stale(ledger):
    """動画にした後で、読み上げ部分の数字が変わった記事。以前の分は今を基準として控えるだけ"""
    import video_make as VM
    out = []
    for slug, rec in ledger.items():
        if not rec.get("youtube") or not (ROOT / "articles" / f"{slug}.md").is_file():
            continue
        try:
            now = _nums(VM.from_article(slug))
        except SystemExit:
            continue
        if "nums" not in rec:
            rec["nums"] = now
            continue
        if now != rec["nums"]:
            out.append(slug)
    return out


def note_token_missing():
    line = "要対応: YouTube の鍵（youtube-token.json）が無く、記事動画を作るだけで上げていません（初回だけ python scripts/youtube_upload.py --auth）"
    FINDINGS.parent.mkdir(parents=True, exist_ok=True)
    t = FINDINGS.read_text(encoding="utf-8") if FINDINGS.is_file() else ""
    if line not in t:
        FINDINGS.write_text(t.rstrip("\n") + ("\n" if t else "") + line + "\n", encoding="utf-8")


def shorts(ledger, limit, token, public):
    """横型の動画がある記事から、ショートの無いものを新しい順に作る。
    TikTok は審査前だと自動投稿が非公開になるため、mp4 を残すだけ（CI の成果物から手で上げる）"""
    import duo_short as DS
    import video_make as VM
    import youtube_upload as YT
    import sites as S

    def meta(k):
        t = (ROOT / "articles" / f"{k}.md").read_text(encoding="utf-8-sig")[:2000]
        g = lambda f: (re.search(rf"^{f}:\s*(.+)$", t, re.M) or [None, ""])[1].strip().strip('"')
        cat = g("category")
        return {"slug": k, "title": g("title"), "category": cat, "site": S.find_category_owner(cat) or ""}
    pool = [meta(k) for k, v in ledger.items() if v.get("youtube") and not v.get("short")
            and (ROOT / "articles" / f"{k}.md").is_file()]
    # 打ち出しから外したテーマは作らない。主力の業種・分野を先に、同じなら新しい順
    pool = [m for m in pool if focus(m) is not None]
    todo = [m["slug"] for m in sorted(pool, key=lambda m: (focus(m), ledger[m["slug"]].get("date", "")),
                                      reverse=True)][:limit]
    made = 0
    for slug in todo:
        try:
            sc = DS.load_script(slug) or DS.write_script(slug)
            if not sc:
                print(f"   × short {slug[:40]}: 台本が検査に通りませんでした")
                continue
            out = VM.OUT / f"{slug}.short.mp4"
            sec = DS.make(sc, out)
            rec = {"date": date.today().isoformat(), "sec": round(sec), "title": sc.get("title", "")}
            if token:
                rec["youtube"] = YT.upload(out, slug, public=public, quiet=True, short_title=sc.get("title", ""))
            ledger[slug]["short"] = rec
            made += 1
            print(f"   ○ short {slug[:40]:<40} {sec:.0f}秒" + (f" → youtube.com/shorts/{rec['youtube']}" if token else ""))
        except Exception as e:
            print(f"   × short {slug[:40]}: {str(e)[:80]}")
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=1)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--public", action="store_true", default=True)
    ap.add_argument("--shorts", type=int, default=1, help="縦型ショートを作る本数（動画のある記事から新しい順）")
    ap.add_argument("--reuse", action="store_true",
                    help="手元で書き出して確認済みの動画（台本より新しいもの）を作り直さずに上げる")
    a = ap.parse_args()
    import duo_video as DV
    import video_make as VM
    import youtube_upload as YT
    ledger = load()
    token = YT.TOKEN.is_file()
    # 作り直しを先に（記事と食い違った動画を長く出したままにしない）。枠は新しい記事と共有する
    redo = stale(ledger) if token else []
    # 掛け合い形式（基準の形）になっていない動画も作り直す。数字が変わったものの後ろに並べる
    if token and DV.ready():
        redo += [k for k, v in ledger.items()
                 if v.get("youtube") and v.get("format") != "duo" and k not in redo
                 and (ROOT / "articles" / f"{k}.md").is_file()]
    rows = [{"slug": s, "site": ledger[s].get("site") or "", "title": s, "date": "", "redo": True}
            for s in redo][:a.limit]
    rows += candidates(a.days, a.limit - len(rows)) if len(rows) < a.limit else []
    print(f"■ 記事動画: 今回 {len(rows)}本（作り直し {len(redo)}本待ち・直近{a.days}日の未作成） / "
          f"YouTubeの鍵 {'あり' if token else '無し'}")
    for r in rows:
        print(f"   [{r['site']:<9}] {'作り直し' if r.get('redo') else r['date']} {r['title'][:44]}")
    if not a.write:
        print(f"YT_TOKEN={'yes' if token else 'missing'}")
        return 0
    made, ok = 0, True
    for r in rows:
        try:
            script = VM.from_article(r["slug"])
            out = VM.OUT / f'{r["slug"]}.mp4'
            out.parent.mkdir(parents=True, exist_ok=True)
            # 基準はキャラクター2人の掛け合い（duo_video）。台本が検査に通らなければスライド形式で出す
            duo = (DV.load_script(r["slug"]) or DV.write_script(r["slug"])) if DV.ready() else None
            sj = DV.SCRIPTS / f'{r["slug"]}.json'
            if duo and a.reuse and out.is_file() and sj.is_file() and out.stat().st_mtime > sj.stat().st_mtime:
                sec, fmt = VM.duration(out), "duo"
            elif duo:
                sec, fmt = DV.make(duo, out), "duo"
            else:
                sec, fmt = VM.build(script, out, quiet=True), "slides"
            old = ledger.get(r["slug"]) or {}
            rec = {"site": r["site"], "date": date.today().isoformat(),
                   "sec": round(sec), "mp4": str(out.relative_to(ROOT)).replace("\\", "/"),
                   "nums": _nums(script), "format": fmt}
            if r.get("redo") and old.get("youtube"):
                # 消すと再生数と埋め込みが失われる。限定公開に下げて、新しい動画に差し替える
                YT.set_privacy(old["youtube"], "unlisted")
                rec["retired"] = old.get("retired", []) + [old["youtube"]]
                rec["site"] = old.get("site", rec["site"])
            if token:
                rec["youtube"] = YT.upload(out, r["slug"], public=a.public, quiet=True)
            ledger[r["slug"]] = rec
            made += 1
            print(f"   ○ {r['slug'][:40]:<40} {sec:.0f}秒 {fmt}" + (f" → youtu.be/{rec['youtube']}" if token else ""))
        except Exception as e:
            ok = False
            print(f"   × {r['slug'][:40]:<40} {str(e)[:80]}")
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    made_s = shorts(ledger, a.shorts, token, a.public) if a.shorts else 0
    # 作り直しの判定で控えた基準（nums）も残す（動画を作らなかった回でも）
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    if rows and not token:
        note_token_missing()
    print(f"VIDEOS_OK={'yes' if ok else 'no'}")
    print(f"VIDEOS_MADE={made}")
    print(f"SHORTS_MADE={made_s}")
    print(f"YT_TOKEN={'yes' if token else 'missing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
