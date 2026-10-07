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

**通常の動画は、YouTube で検索されているテーマだけ**（yt_demand。2026-10-05 から）。
ショートは毎日1本のまま。通常の動画を作らない記事はショートだけにし、本数は増やさない。
題は YouTube のサジェストの検索語を先頭に置いた問いの形。上げ済みの動画は変えない。

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
    # 動画にするカテゴリを絞った社（自社は AIO だけ・2026-10-07 運用者の決定）。キーの無い社（お客様）は絞らない
    if "video_categories" in cfg and row.get("category", "") not in cfg["video_categories"]:
        return None
    pri = (cfg.get("kw_seeds") or {}).get("priority") or []
    return (2 if any(w in (row.get("title") or "") for w in pri) else 0) + \
           (1 if row.get("category") == cfg.get("main_category") else 0)


def candidates(days, limit):
    """直近 days 日に公開した score>=90 の記事で、まだ動画にしていないもの（新しい順）"""
    import sites as S
    import youtube_upload as YT
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
        # チャンネル未接続のクライアントは、本数で切る前に外す。切った後で外すと、
        # その社の記事が新しい順の先頭にあった日は1日の枠（1本）がまるごと空になる
        if S.is_client(sid) and not YT.token_path(sid).is_file():
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


JUDGE_MAX = 5      # 通常の動画の枠のために、1回で判定する記事の数（サジェストは1記事5回まで・無料）


def plan_long(cands, need, judge):
    """通常の動画は、YouTube で検索されているテーマ（yt_demand.judge が make）だけ need 本まで。
    実測（2026-10-05）で通常の動画は0〜1回しか見られず、ショートは183〜543回だった。
    skip の記事はショートだけにする（その記事の判定は台帳に残す）。空いた枠で別のショートは作らない。
    unknown（サジェストが取れなかった）は記録せず、翌日また判定する"""
    make, skipped = [], []
    for r in cands:
        if len(make) >= need:
            break
        j = judge(r["slug"])
        if j["decision"] == "make":
            make.append(dict(r, yt=j))
        elif j["decision"] == "skip":
            skipped.append((r, j))
    return make, skipped


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


def research_due(ledger, per_week, today=None):
    """今週まだ調査の動画を上げていなければ、次に動画にする調査（research_promo の出せる業種で、まだ動画の無いもの）。
    調査はそこにしか無い数字なので言及の元になるが、1日の上限は記事動画と共有なので週 per_week 本まで"""
    import research_promo as RP
    if per_week <= 0:
        return None
    since = ((today or date.today()) - timedelta(days=6)).isoformat()
    recent = [k for k, v in ledger.items() if k.startswith(RP.PREFIX) and (v.get("date") or "") >= since]
    if len(recent) >= per_week:
        return None
    ng = RP.load_ledger().get("video_ng", {})
    for ind in RP.industries():
        if RP.PREFIX + ind not in ledger and ind not in ng:
            return ind
    return None


def make_research(r, ledger, token, public):
    """調査の掛け合い動画。台本が検査に通らなければ作らない（記事と違い、スライド形式に落とす元が無い）"""
    import duo_video as DV
    import video_make as VM
    import youtube_upload as YT
    sc = DV.load_script(r["slug"]) or DV.write_script(r["slug"])
    if not sc:
        print(f"   × {r['slug']}: 台本が検査に通りませんでした（作りません）")
        # 翌日また同じ業種で claude を3回呼ばないよう、通らなかった業種は記録して次の業種へ回す
        import research_promo as RP
        led = RP.load_ledger()
        led.setdefault("video_ng", {})[r["slug"][len(RP.PREFIX):]] = date.today().isoformat()
        RP.LEDGER.write_text(json.dumps(led, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return False
    out = VM.OUT / f'{r["slug"]}.mp4'
    out.parent.mkdir(parents=True, exist_ok=True)
    sec = DV.make(sc, out)
    rec = {"site": "ai-lab", "kind": "research", "date": date.today().isoformat(), "sec": round(sec),
           "mp4": str(out.relative_to(ROOT)).replace("\\", "/"), "format": "duo", "url": r["url"]}
    if token:
        rec["youtube"] = YT.upload(out, r["slug"], public=public, quiet=True)
    ledger[r["slug"]] = rec
    LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   ○ {r['slug'][:40]:<40} {sec:.0f}秒 duo（調査）" + (f" → youtu.be/{rec['youtube']}" if token else ""))
    return True


def note_token_missing():
    line = "要対応: YouTube の鍵（youtube-token.json）が無く、記事動画を作るだけで上げていません（初回だけ python scripts/youtube_upload.py --auth）"
    FINDINGS.parent.mkdir(parents=True, exist_ok=True)
    t = FINDINGS.read_text(encoding="utf-8") if FINDINGS.is_file() else ""
    if line not in t:
        FINDINGS.write_text(t.rstrip("\n") + ("\n" if t else "") + line + "\n", encoding="utf-8")


def meta(k):
    import sites as S
    t = (ROOT / "articles" / f"{k}.md").read_text(encoding="utf-8-sig")[:2000]
    g = lambda f: (re.search(rf"^{f}:\s*(.+)$", t, re.M) or [None, ""])[1].strip().strip('"')
    cat = g("category")
    return {"slug": k, "title": g("title"), "category": cat, "site": S.find_category_owner(cat) or ""}


def shorts(ledger, limit, token, public):
    """横型の動画がある記事から、ショートの無いものを新しい順に作る。
    TikTok は審査前だと自動投稿が非公開になるため、mp4 を残すだけ（CI の成果物から手で上げる）"""
    import duo_short as DS
    import video_make as VM
    import youtube_upload as YT

    # 通常の動画がある記事と、YouTube で検索されていないため通常の動画を作らなかった記事（ショートだけ）
    pool = [meta(k) for k, v in ledger.items()
            if (v.get("youtube") or (v.get("long") or {}).get("decision") == "skip") and not v.get("short")
            and (ROOT / "articles" / f"{k}.md").is_file()]
    # 打ち出しから外したテーマは作らない。主力の業種・分野を先に、同じなら新しい順
    pool = [m for m in pool if focus(m) is not None]
    pool = [m for m in pool if not YT.is_client(m["site"]) or YT.token_path(m["site"]).is_file()]
    when = lambda k: ledger[k].get("date") or (ledger[k].get("long") or {}).get("date", "")
    todo = [m["slug"] for m in sorted(pool, key=lambda m: (focus(m), when(m["slug"])), reverse=True)][:limit]
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
            # 同じ記事の通常の動画があれば、説明欄の先頭に続きとして置く（この印の付いたショートだけ）
            lead = bool(ledger[slug].get("youtube"))
            if lead:
                rec["desc"] = YT.LEAD_LONG
            if token:
                rec["youtube"] = YT.upload(out, slug, public=public, quiet=True, short_title=sc.get("title", ""),
                                           lead_long=lead)
            ledger[slug]["short"] = rec
            made += 1
            print(f"   ○ short {slug[:40]:<40} {sec:.0f}秒" + (f" → youtube.com/shorts/{rec['youtube']}" if token else ""))
        except Exception as e:
            print(f"   × short {slug[:40]}: {str(e)[:80]}")
            if "uploadLimitExceeded" in str(e):
                # 1日のアップロード上限（API は手動より厳しい。2026-10-03 は約10本で当たった）。
                # 続けても作っては失敗するだけなので、この回はやめる。翌日の回で続きから上がる
                print("   要対応: YouTube の1日のアップロード上限に達しました。翌日の回で続きを上げます")
                break
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=1)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--public", action="store_true", default=True)
    ap.add_argument("--shorts", type=int, default=1, help="縦型ショートを作る本数（動画のある記事から新しい順）")
    ap.add_argument("--research", type=int, default=1,
                    help="調査ページの動画を週に何本まで混ぜるか（記事動画の枠と置き換える。本数は増やさない）")
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
                 and (ROOT / "articles" / f"{k}.md").is_file() and focus(meta(k)) is not None]
    rows = [{"slug": s, "site": ledger[s].get("site") or "", "title": s, "date": "", "redo": True}
            for s in redo][:a.limit]
    skipped = []
    if len(rows) < a.limit:
        import yt_demand as YD
        made_rows, skipped = plan_long(candidates(a.days, JUDGE_MAX), a.limit - len(rows), YD.judge)
        rows += made_rows
    # 受託のクライアントは、先方のチャンネルを接続した社だけ作る（作っても上げ先が無い。当社のチャンネルには上げない）
    skip = [r["slug"] for r in rows if YT.is_client(r["site"]) and not YT.token_path(r["site"]).is_file()]
    if skip:
        print(f"   チャンネル未接続のクライアントの記事を飛ばしました: {len(skip)}本")
        rows = [r for r in rows if r["slug"] not in skip]
    ind = research_due(ledger, a.research) if a.limit > 0 and DV.ready() else None
    if ind:
        import research_promo as RP
        hl = RP.headline(ind)
        rows = rows[:a.limit - 1] + [{"slug": RP.PREFIX + ind, "site": "ai-lab", "title": RP.title(hl),
                                      "date": "調査", "research": True, "url": hl["url"]}]
    print(f"■ 記事動画: 今回 {len(rows)}本（作り直し {len(redo)}本待ち・直近{a.days}日の未作成） / "
          f"YouTubeの鍵 {'あり' if token else '無し'}")
    for r in rows:
        print(f"   [{r['site']:<9}] {'作り直し' if r.get('redo') else r['date']} {r['title'][:44]}"
              + (f"\n               → 動画の題: {r['yt']['title']}" if r.get("yt") else ""))
    for r, j in skipped:
        print(f"   [{r['site']:<9}] 通常の動画なし（ショートだけ） {r['slug'][:40]}: {j['reason']}")
    if not a.write:
        print(f"YT_TOKEN={'yes' if token else 'missing'}")
        return 0
    for r, j in skipped:
        # 判定を残す（翌日また同じ記事を判定しない・ショートの対象にする）。top の date/youtube は付けない
        # （付けると video_embed・outcome_watch が動画を上げた記事として数える）
        ledger.setdefault(r["slug"], {"site": r["site"], "long": j})
    made, ok = 0, True
    for r in rows:
        try:
            if r.get("research"):
                made += make_research(r, ledger, token, a.public)
                continue
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
            replacing = [old["youtube"]] if r.get("redo") and old.get("youtube") else []
            if r.get("yt"):
                rec["long"] = r["yt"]
            if token:
                rec["youtube"] = YT.upload(out, r["slug"], public=a.public, quiet=True, replacing=replacing,
                                           title=(r.get("yt") or {}).get("title", ""))
            if replacing:
                # 消すと再生数と埋め込みが失われる。限定公開に下げて、新しい動画に差し替える。
                # 下げるのは新しい版が上がった後（先に下げると、上限で上がらなかった日に動画が無くなる。2026-10-03）
                if token:
                    YT.set_privacy(old["youtube"], "unlisted")
                rec["retired"] = old.get("retired", []) + [old["youtube"]]
                rec["site"] = old.get("site", rec["site"])
            ledger[r["slug"]] = rec
            made += 1
            print(f"   ○ {r['slug'][:40]:<40} {sec:.0f}秒 {fmt}" + (f" → youtu.be/{rec['youtube']}" if token else ""))
        except Exception as e:
            ok = False
            print(f"   × {r['slug'][:40]:<40} {str(e)[:80]}")
            if "uploadLimitExceeded" in str(e):
                print("   要対応: YouTube の1日のアップロード上限に達しました。翌日の回で続きを上げます")
                a.shorts = 0   # 同じ回のショートも上がらない
                break
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
