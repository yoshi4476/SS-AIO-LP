# -*- coding: utf-8 -*-
"""公開から60日たち、直近28日に検索に出ていない記事を、近い記事へ統合して面を薄めない。

**なぜ要るか**: auto_merge は「同じ語で2本が出ている組」しか見ない。
一度も表示されない記事は誰の競合にもならず、そのまま残る。薄い記事が増えると
サイト全体の評価が下がる（8.2.5節と同じ理由）。

やること（判断は機械だけ）:
  1. 60日以上前に公開し、GSC のページ次元で直近28日の表示が0・90日のクリックが0の記事を出す
     （以前は「90日以上前に公開・90日の表示が0」だけだった。3サイトで直近28日の表示が0の記事107本のうち、
     当てはまるのは2本。残りは「公開から約1か月だけ表示され、その後消えた」記事で、どの手当ても拾っていなかった。
     うち45本には、近い内容で今も表示されている記事があった。2026-11-12）
  2. 同じサイトの公開記事から、題名と狙う語が最も近いもの（Dice ≥ 0.35）を吸収先にする
  3. auto_merge.run_one で統合する（検算・301・内部リンクの付け替えは auto_merge と同じ）
  近い記事が無いものは統合しない（無理に吸わせると主題がぼやける）。一覧に出すだけ

  python scripts/retire_stale.py                    # 候補を見る
  python scripts/retire_stale.py --write --limit 2  # 統合する
出す印: STALE_OK=yes / STALE=<本> / MERGED=<本>

**付け替え（--retarget。週次はこちら。2026-11-15 運用者の承認）**: 同じ候補を、1位を狙う語の台帳
（key_queries --ledger。業種×サービスの組）と突き合わせる。記事と同じ組で題・狙う語が最も近い語（Dice）を選び、
  - その語を担う記事がまだ無い → 狙う語・題（H1）・説明文をその語へ付け替える（auto_rewrite の retarget。kw_guard を通し、
    食い合いなら付け替えない。28日後に表示が出なければ rewrite_rollback が直す前の原稿へ戻す）
  - 担う記事がある → その記事へ統合する（auto_merge）
  - 組に語が無い・一度付け替えを試した記事 → 今までどおり近い記事へ統合（近い記事が無ければ残す）
付け替えと統合を合わせて週 WEEK_LIMIT 本まで。

  python scripts/retire_stale.py --retarget --dry-run            # 対象の数と振り分けを見る（GSC を読めなければ控えで代える）
  python scripts/retire_stale.py --retarget --write --limit 6    # 当てる（週次）
出す印: RETARGET_OK=yes / STALE=<本> / RETARGET=<本> / MERGE=<本> / KEEP=<本> / RETARGETED=<本> / MERGED=<本>

書き直しを2回しても別工程の採点（score_audit）で一次性が80点に届かない記事も、同じ統合に回す。
自動で統合するのは90日の表示・クリックが少なく、吸収先より表示が少ないものだけ（検算は auto_merge）

  python scripts/retire_stale.py --quality                    # 候補を見る
  python scripts/retire_stale.py --quality --write --limit 1  # 統合する（週次）
出す印: QUALITY_STUCK_OK=yes / QUALITY_STUCK=<本> / QUALITY_MERGED=<本>
"""
import argparse
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
AGE_DAYS = 60        # 公開からこの日数たった記事だけ（順位が落ち着く前に統合しない。article_health の「若い」は35日未満）
WINDOW_DAYS = 28     # この日数の表示が0なら「いま出ていない」
CLICK_DAYS = 90      # この日数にクリックがあった記事は、読まれた実績があるので統合しない
MIN_SIM = 0.35
WEEK_LIMIT = 6       # 付け替えと統合を合わせた週の本数（前は統合だけで2本。2026-11-15 運用者の承認）
# 台帳の語は題より短く、同じ主題でも Dice が統合の下限（0.35）に届かない（実データで 0.26〜0.49）。
# 主題の違う組（医療広告ガイドラインの記事 → ホームページ制作の外注）は 0.19 だった
RETARGET_SIM = 0.25


def _fm(p):
    t = p.read_text(encoding="utf-8-sig")
    m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    if not m:
        return None
    fm = m.group(1)
    import noindex
    if noindex.hidden_fm(fm):
        return None          # 検索から外した記事（noindex）は統合の候補（どちらの側にも）にしない

    def g(k):
        x = re.search(rf"^{k}:\s*(.+)$", fm, re.M)
        return x.group(1).strip().strip('"') if x else ""
    return {"slug": p.stem, "title": g("title"), "keyword": g("keyword"), "category": g("category"),
            "date": g("date"), "score": int(g("score") or 0)}


def page_stats(cfg, days=CLICK_DAYS):
    """days 日間のURLごとの (表示, クリック)。末尾スラッシュを揃える"""
    import report_verify as RV
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    rows = RV._gsc(f"https://{cfg['domain']}/", start.isoformat(), end.isoformat(), ["page"], 25000).get("rows", [])
    out = {}
    for r in rows:
        u = r["keys"][0].rstrip("/") + "/"
        i, c = out.get(u, (0, 0))
        out[u] = (i + int(r.get("impressions", 0)), c + int(r.get("clicks", 0)))
    return out


def shown_urls(cfg):
    """直近 WINDOW_DAYS 日に一度でも表示されたURL（末尾スラッシュを揃える）"""
    return {u for u, (i, _) in page_stats(cfg, WINDOW_DAYS).items() if i > 0}


def clicked_urls(cfg):
    """CLICK_DAYS 日にクリックがあったURL"""
    return {u for u, (_, c) in page_stats(cfg, CLICK_DAYS).items() if c > 0}


def faded(a, url, shown, clicked, today=None):
    """統合の候補か: 公開から AGE_DAYS 日以上たち、いま表示が無く、クリックの実績も無い"""
    old = ((today or date.today()) - timedelta(days=AGE_DAYS)).isoformat()
    return bool(a.get("date")) and a["date"] <= old and url not in shown and url not in clicked


def nearest(a, arts, shown_url):
    """題名と狙う語が最も近い、検索に出ている同じサイトの記事"""
    from cannibal_check import dice
    best, sim = None, 0.0
    for b in arts:
        if b["slug"] == a["slug"] or not shown_url(b):
            continue
        s = dice(a["title"] + " " + a["keyword"], b["title"] + " " + b["keyword"])
        if s > sim:
            best, sim = b, s
    return best, sim


def cached_urls(sid):
    """GSC を読めない手元の --dry-run だけで使う控え（rank_track の data/ranks/<id>.pages.json・28日×2）。
    表示は直近28日で同じ、クリックは90日ではなく56日分になる"""
    import json
    import client_private as CP
    pg = json.loads(CP.find_file(f"data/ranks/{sid}.pages.json").read_text(encoding="utf-8"))
    n = lambda u: u.rstrip("/") + "/"
    cur, prev = pg.get("cur") or {}, pg.get("prev") or {}
    return ({n(u) for u, v in cur.items() if v[0] > 0},
            {n(u) for d in (cur, prev) for u, v in d.items() if v[1] > 0})


def stale(site_id="", cache=False):
    import sites as S
    out = []
    for sid, cfg in S.load_all().items():
        if site_id and sid != site_id:
            continue
        arts = [a for a in (_fm(p) for p in (ROOT / "articles").glob("*.md")) if a
                and a["score"] >= 85 and S.find_category_owner(a["category"]) == sid]
        try:
            shown, clicked = shown_urls(cfg), clicked_urls(cfg)
        except Exception as e:
            if not cache:
                print(f"   {sid}: GSC を読めません（{str(e)[:50]}）")
                continue
            try:
                shown, clicked = cached_urls(sid)
            except Exception:  # noqa: BLE001  控えも無い社は数えない
                print(f"   {sid}: GSC も控えも読めません")
                continue
            print(f"   {sid}: GSC を読めないため控え（data/ranks/{sid}.pages.json。クリックは56日分）で数えます")
        for a in arts:
            url = S.article_url(cfg, a).rstrip("/") + "/"
            if not faded(a, url, shown, clicked):
                continue
            best, sim = nearest(a, arts, lambda b: (S.article_url(cfg, b).rstrip("/") + "/") in shown)
            out.append({"site": sid, "loser": a["slug"], "title": a["title"], "date": a["date"],
                        "survivor": best["slug"] if best and sim >= MIN_SIM else "", "sim": round(sim, 2),
                        "kws": [{"kw": a["keyword"], "imp": 0, "win_pos": 0, "lose_pos": 0}],
                        "imp": 0, "loser_stat": {"pos": 0, "clicks": 0}, "survivor_stat": {"pos": 0}})
    # 近い記事がはっきりあるものから統合する（週の本数が限られるので、迷いの少ない組を先に）
    return sorted(out, key=lambda r: -r["sim"])


# ---- 台帳の語への付け替え（--retarget） -----------------------------------------------------
def route(rows, ledger, arts, conf, tried=(), pending=()):
    """表示ゼロの記事ごとに、付け替え（retarget）・統合（merge）・残す（none）を決める。
    rows は stale() の行、ledger は台帳の行（key_queries の ind・svc のある行）、arts は {slug: {title, keyword}}。
    台帳の同じ組（業種×サービス）で題と狙う語が最も近い語を選び、担う記事が無ければ付け替え、あれば統合。
    組に語が無い・一度付け替えを試した記事（tried）・同じ語を先に別の記事へ渡した記事は、今までの統合（近い記事）へ。
    付け替えの判定期間中の記事（pending）は、効いたかを見る前に統合しないよう外す"""
    import key_queries as KQ
    from cannibal_check import dice
    losers = {r["loser"] for r in rows}
    # すでに台帳の語を担う記事は、別の語へ向けると担っていた語を手放す（GSC の着地ページとして担う記事も）
    carriers = {x["slug"] for x in ledger if x.get("slug")}
    taken, out = set(), []
    for r in rows:
        s = r["loser"]
        if s in pending:
            continue
        a = arts.get(s) or {}
        text = f"{a.get('title', '')} {a.get('keyword', '')}"
        g = KQ.group_of(text, conf) if conf else None
        pool = [x for x in ledger if g and (x["ind"], x["svc"]) == g and x.get("slug") != s]
        best = max(pool, key=lambda x: dice(text, x["q"]), default=None)
        if best and s not in tried and s not in carriers and KQ.norm(best["q"]) not in taken \
                and dice(text, best["q"]) >= RETARGET_SIM:
            if not best.get("slug"):
                taken.add(KQ.norm(best["q"]))
                out.append({**r, "action": "retarget", "kw": best["q"], "group": g})
                continue
            # 担う記事も表示ゼロで統合の候補なら、そこへ寄せない（吸収先が次に消える）
            if best["slug"] not in losers and best["slug"] in arts:
                out.append({**r, "action": "merge", "survivor": best["slug"], "kw": best["q"], "group": g})
                continue
        out.append({**r, "action": "merge" if r.get("survivor") else "none"})
    return out


def retarget_log(log=None, today=None):
    """(付け替えを試した記事, 付け替えの判定期間中の記事)。判定期間は rewrite_rollback と同じ28日＋GSC の遅れ3日"""
    import json
    import client_private as CP
    f = Path(log) if log else ROOT / "automation" / "logs" / "auto_fix.jsonl"
    since = ((today or date.today()) - timedelta(days=31)).isoformat()
    tried, pending = set(), set()
    for line in CP.read_lines(f):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("by") != "auto_rewrite" or d.get("kind") != "retarget":
            continue
        tried.add(d.get("slug", ""))
        if d.get("ok") and str(d.get("note", "")).startswith("直しました") and str(d.get("at", ""))[:10] >= since:
            pending.add(d.get("slug", ""))
    return tried, pending


def retarget_main(a):
    import key_queries as KQ
    import private_store as PS
    import sites as S
    write = a.write and not a.dry_run
    rows = stale(a.site, cache=not write)
    tried, pending = retarget_log()
    routed = []
    for sid in sorted({r["site"] for r in rows}):
        led = [x for x in (KQ.load().get(sid) or {}).get("queries") or [] if x.get("ind")]
        arts = {b["slug"]: b for b in (_fm(p) for p in (ROOT / "articles").glob("*.md"))
                if b and S.find_category_owner(b["category"]) == sid}
        routed += route([r for r in rows if r["site"] == sid], led, arts,
                        KQ.ledger_conf(S.load(sid)) if led else None, tried, pending)
    # 台帳の語に向ける手（付け替え・担う記事への統合）を先に、次に今までの統合を近い順に
    routed.sort(key=lambda r: (r["action"] == "none", not r.get("kw"), -r.get("sim", 0)))
    n = {k: sum(1 for r in routed if r["action"] == k) for k in ("retarget", "merge", "none")}
    print(f"■ 公開{AGE_DAYS}日以上で、直近{WINDOW_DAYS}日の表示ゼロ・{CLICK_DAYS}日のクリックゼロ: {len(rows)}本"
          f"（付け替え {n['retarget']}本・統合 {n['merge']}本・残す {n['none']}本・付け替えの判定期間中で外した "
          f"{len(rows) - len(routed)}本）")
    for r in routed[:20]:
        secret = S.is_client(r["site"])
        to = (f"付け替え「{'（お客様の語）' if secret else r['kw']}」" if r["action"] == "retarget" else
              f"統合 → {PS.shown(r['survivor'])[:28]}" + ("（台帳の語を担う記事）" if r.get("kw") else "")
              if r["action"] == "merge" else "残す（近い記事も台帳の語も無い）")
        print(f"   [{'お客様の社' if secret else r['site']}] {PS.shown(r['loser'])[:34]:<34} → {to}")
    done_rt = done_mg = 0
    if write:
        import auto_merge as AM
        import auto_rewrite as AR
        t0 = time.time()
        for r in [x for x in routed if x["action"] != "none"][:a.limit]:
            if a.budget_min and (time.time() - t0) / 60 >= a.budget_min:
                break
            if r["action"] == "merge":
                ok, why = AM.run_one(r, True)
                AM.note(r, ok, "（表示ゼロの整理）" + why)
                print(f"   {'○' if ok else '×'} 統合 {PS.shown(r['loser'])[:30]} → {PS.shown(r['survivor'])[:30]}: {why[:60]}")
                done_mg += ok
                continue
            rc = AR.sh([sys.executable, "scripts/kw_guard.py", r["kw"], "--site", r["site"],
                        "--exclude-slug", r["loser"]], timeout=600).returncode
            if rc == 3:
                print(f"   -- 付け替え {PS.shown(r['loser'])[:30]}: 食い合いを判定できないため来週に回します（kw_guard 3）")
                continue
            item = {"kind": "retarget", "slug": r["loser"], "site": r["site"], "kw": r["kw"], "age": AGE_DAYS,
                    "why": f"公開{AGE_DAYS}日以上・直近{WINDOW_DAYS}日の表示0。台帳の組（{r['group'][0]}×{r['group'][1]}）の"
                           f"語「{r['kw']}」はまだどの記事も担っていません"}
            ok, why = (False, f"食い合いのため付け替えません（kw_guard {rc}）") if rc >= 2 else AR.run_one(item, True)
            AR.note(item["slug"], "retarget", ok, why)
            print(f"   {'○' if ok else '×'} 付け替え {PS.shown(r['loser'])[:30]}: {AR.said(r['loser'], why)[:60]}")
            if ok and why.startswith("直しました"):
                AR.hub_rewrite_log(item, why)
                done_rt += 1
    print(f"RETARGET_OK=yes\nSTALE={len(rows)}\nRETARGET={n['retarget']}\nMERGE={n['merge']}\nKEEP={n['none']}"
          f"\nRETARGETED={done_rt}\nMERGED={done_mg}")
    return 0


# ---- 書き直しても一次性が上がらない記事（--quality） -------------------------------------
# 一次性は「そこにしか無い数字・経験」で決まり、登録済みの一次情報が無いと書き直しても上がらない
# （2026-10-04: 補助金の旧記事12本を書き直しても全部が80点未満のまま。人手で近い記事へ取り下げた）。
# 同じ記事を書き直し続けると時間だけが減るので、2回で見切って近い記事へ寄せる
MIN_TRIES = 2
QUALITY_MAX_IMP = 300     # 90日の表示。これを超える記事は統合で失うものがあるので、人に回す
QUALITY_REASON = """理由: {loser} は書き直しを{tries}回しても、別工程の採点で一次性が{orig}点（基準80点）のままです。
題名と狙う語が近い {survivor} に、{loser} にしか無い中身だけを移して1本にまとめます（90日の表示 {loser}={limp}回・{survivor}={simp}回）。"""


def quality_tries(log=None):
    """slug → 一次性を上げるための書き直し（auto_rewrite の quality）を実際に当てた日の一覧"""
    import json
    import client_private as CP
    f = Path(log) if log else ROOT / "automation" / "logs" / "auto_fix.jsonl"
    out = {}
    for line in CP.read_lines(f):            # お客様の記事の行（置き場）も合わせる
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("by") == "auto_rewrite" and d.get("kind") == "quality" and d.get("ok") \
                and str(d.get("note") or "").startswith("直しました"):
            out.setdefault(d.get("slug", ""), []).append(str(d.get("at", ""))[:10])
    return out


def stuck_quality(audits, tries, legacy=None, version="", pass_each=80, min_tries=MIN_TRIES):
    """書き直しを min_tries 回しても一次性が pass_each 点に届かない記事。

    audits は score_audit.json（今の基準 version の採点だけ見る）。採点が最後の書き直しより前なら、
    書き直した版はまだ採点されていない（採点待ち）。legacy は legacy_scores.json（旧形式の記事。
    articles/ に無いので統合ではなく取り下げの候補）"""
    out = []
    for slug, r in (audits or {}).items():
        au = r.get("audit") or {}
        o = (au.get("axes") or {}).get("originality")
        if o is None or o >= pass_each or (version and au.get("version") != version):
            continue
        ds = sorted(tries.get(slug, []))
        if len(ds) < min_tries:
            continue
        status = "候補" if str(r.get("at", "")) >= ds[-1] else "採点待ち"
        out.append({"slug": slug, "orig": o, "tries": len(ds), "status": status, "src": "audit",
                    "first": next((h.get("originality", o) for h in r.get("history") or []
                                   if not version or h.get("version") == version), o)})
    for slug, r in (legacy or {}).items():
        o = (r.get("axes") or {}).get("originality")
        n = r.get("attempts", 1 if r.get("rewritten") else 0)
        if r.get("pass") or o is None or o >= pass_each or n < min_tries:
            continue
        out.append({"slug": slug, "orig": o, "tries": n, "status": "候補", "src": "legacy"})
    return sorted(out, key=lambda x: (x["status"] != "候補", x["orig"]))


def quality_pairs(site_id=""):
    """一次性が上がらない記事 → 近い記事への統合の組。表示とクリックが少ないものだけ自動に回す"""
    import json
    import rubric as R
    import sites as S
    import auto_merge as AM
    import industry_hub as IH
    inds = IH.load()[0]
    load = lambda p: json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    rows = stuck_quality(load(ROOT / "data" / "score_audit.json"), quality_tries(),
                         load(ROOT / "data" / "legacy_scores.json"), R.VERSION, R.PASS_EACH)
    out = []
    stats_by = {}
    for x in rows:
        p = ROOT / "articles" / f"{x['slug']}.md"
        if x["src"] == "legacy" or not p.is_file():
            # 旧形式の記事は articles/ に無く、統合の検算に通せない。取り下げは人が retract で行う
            out.append({**x, "survivor": "", "auto": False, "skip": "articles/ に無い（取り下げは人が判断）"})
            continue
        a = _fm(p)
        sid = S.find_category_owner(a["category"]) if a else ""
        if not a or not sid or (site_id and sid != site_id):
            continue
        cfg = S.load(sid)
        if sid not in stats_by:
            try:
                stats_by[sid] = page_stats(cfg)
            except Exception as e:
                print(f"   {sid}: GSC を読めません（{str(e)[:50]}）")
                stats_by[sid] = None
        st = stats_by[sid]
        if st is None:
            out.append({**x, "survivor": "", "auto": False, "skip": "GSC を読めない"})
            continue
        arts = [b for b in (_fm(q) for q in (ROOT / "articles").glob("*.md")) if b
                and b["score"] >= 85 and S.find_category_owner(b["category"]) == sid]
        url = lambda b: S.article_url(cfg, b).rstrip("/") + "/"
        # 同じ手法（カテゴリ）で、業種のある記事は同じ業種の記事へだけ寄せる。題の近さだけで選ぶと、
        # 型が同じ別業種（clinic-seo-taisaku → reform-seo-taisaku）や別の手法（→ clinic-meo-taisaku）が
        # 選ばれ、統合した記事の主題がぼやける（2026-10-04 の実データで確認）
        ind = IH.detect(a["title"], a["keyword"], inds)
        pool = [b for b in arts if b["category"] == a["category"]
                and (not ind or IH.detect(b["title"], b["keyword"], inds) == ind)]
        best, sim = nearest(a, pool, lambda b: st.get(url(b), (0, 0))[0] > 0)
        li, lc = st.get(url(a), (0, 0))
        si = st.get(url(best), (0, 0))[0] if best else 0
        skip = ("近い記事なし" if not best or sim < MIN_SIM else
                "採点待ち（書き直した版がまだ採点されていない）" if x["status"] != "候補" else
                f"クリック{lc}回（{AM.MAX_LOSER_CLICKS}回超は人が判断）" if lc > AM.MAX_LOSER_CLICKS else
                f"表示{li}回（{QUALITY_MAX_IMP}回超は人が判断）" if li > QUALITY_MAX_IMP else
                f"吸収先より表示が多い（{li} > {si}）" if li >= si else "")
        out.append({**x, "site": sid, "loser": x["slug"], "survivor": best["slug"] if best and sim >= MIN_SIM else "",
                    "sim": round(sim, 2), "auto": not skip, "skip": skip, "title": a["title"],
                    "kws": [{"kw": a["keyword"], "imp": li, "win_pos": 0, "lose_pos": 0}], "imp": li,
                    "loser_stat": {"imp": li, "clicks": lc, "pos": 0}, "survivor_stat": {"imp": si, "pos": 0},
                    "reason": QUALITY_REASON.format(loser=x["slug"], survivor=best["slug"] if best else "",
                                                    tries=x["tries"], orig=x["orig"], limp=li, simp=si)})
    return out


def quality_main(a):
    rows = quality_pairs(a.site)
    can = [r for r in rows if r["auto"]]
    print(f"■ 書き直しを{MIN_TRIES}回しても一次性が80点に届かない記事: {len(rows)}本（自動で統合できる {len(can)}本）")
    for r in rows[:20]:
        print(f"   {r['slug'][:36]:<36} 一次性{r.get('first', r['orig'])}→{r['orig']}（書き直し{r['tries']}回・{r['src']}）→ "
              + (f"{r['survivor'][:28]}（{r.get('sim')}）" if r.get("survivor") else "吸収先なし")
              + (f"  ｜{r['skip']}" if r["skip"] else ""))
    merged = 0
    if a.write and can:
        import auto_merge as AM
        t0 = time.time()
        for pair in can[:a.limit]:
            if a.budget_min and (time.time() - t0) / 60 >= a.budget_min:
                break
            ok, why = AM.run_one(pair, True)
            AM.note(pair, ok, "（一次性が上がらない記事の整理）" + why)
            print(f"   {'○' if ok else '×'} {pair['loser'][:30]} → {pair['survivor'][:30]}: {why[:60]}")
            merged += ok
    print(f"QUALITY_STUCK_OK=yes\nQUALITY_STUCK={len(rows)}\nQUALITY_MERGED={merged}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--site", default="")
    ap.add_argument("--limit", type=int, default=2)
    ap.add_argument("--budget-min", type=int, default=0)
    ap.add_argument("--quality", action="store_true",
                    help=f"書き直しを{MIN_TRIES}回しても一次性が80点に届かない記事を、近い記事へ統合する")
    ap.add_argument("--retarget", action="store_true",
                    help="表示ゼロの記事を、台帳（key_queries --ledger）の近い語へ付け替える／担う記事へ統合する")
    ap.add_argument("--dry-run", action="store_true", help="--retarget で、対象の数と振り分けだけを出す（書かない）")
    a = ap.parse_args()
    if a.retarget:
        return retarget_main(a)
    if a.quality:
        return quality_main(a)
    rows = stale(a.site)
    can = [r for r in rows if r["survivor"]]
    print(f"■ 公開{AGE_DAYS}日以上で、直近{WINDOW_DAYS}日の表示ゼロ・{CLICK_DAYS}日のクリックゼロ: {len(rows)}本（吸収先あり {len(can)}本）")
    for r in rows[:20]:
        print(f"   [{r['site']:<9}] {r['loser'][:34]:<34} {r['date']} → "
              + (f"{r['survivor'][:28]}（{r['sim']}）" if r["survivor"] else "近い記事なし（残す）"))
    merged = 0
    if a.write and can:
        import auto_merge as AM
        t0 = time.time()
        for pair in can[:a.limit]:
            if a.budget_min and (time.time() - t0) / 60 >= a.budget_min:
                break
            ok, why = AM.run_one(pair, True)
            AM.note(pair, ok, "（表示ゼロの整理）" + why)
            print(f"   {'○' if ok else '×'} {pair['loser'][:30]} → {pair['survivor'][:30]}: {why[:60]}")
            merged += ok
    print(f"STALE_OK=yes\nSTALE={len(rows)}\nMERGED={merged}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
