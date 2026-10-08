# -*- coding: utf-8 -*-
"""「人が判断すること」として残っていた直しを、機械に任せる。

auto_improve は、タイトルの書き換えと検索意図の見直しを人へ回していた。
理由は「正規表現で当てると主張のずれた記事が量産される」から。これは正しい。
ただし記事本体はすでに無人の claude が書いている。同じ仕組みに検算を付ければ、
ここも任せられる。判断は claude がし、**通してよいかは機械が決める**。

流れ:
  1. auto_improve が挙げた対象を1本取る
  2. claude -p に、その1本だけを直させる（何を守るかを渡す）
  3. 検算する。1つでも崩れたら直す前の中身へ戻す
  4. 台帳に残す

検算（1つでも外れたら書き込まない）:
  - 触ったファイルがその1本だけか
  - 狙う語（keyword）が変わっていないか
  - タイトルが15〜45字で、狙う語を含むか
  - 本文の数字が増えていないか（**数字を作らせない**。減るのは可）
  - 外部の出典リンクが消えていないか
  - score_check の警告が増えていないか
  - kw_guard が通るか（既存記事との食い合いを作らない）
  - build.py が通るか

  python scripts/auto_rewrite.py              # 何を直すか見る
  python scripts/auto_rewrite.py --write      # 実際に直す（既定3本）
  python scripts/auto_rewrite.py --write --limit 1
  python scripts/auto_rewrite.py --write --kind early --limit 2   # 公開14〜35日の記事に、15位以内の細い語を入れる
"""
import argparse
import collections
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LOG = ROOT / "automation" / "logs" / "auto_fix.jsonl"
# 台帳のお客様の記事の行（題・説明文・順位）は置き場に書き、読むときに合わせる
import client_private as CP  # noqa: E402
TITLE_MIN, TITLE_MAX = 15, 45


def sh(args, timeout=1800, stdin_text=None, cwd=None):
    """外部コマンドを動かす。stdin_text を渡すと標準入力から流し込む。

    **複数行の文字列を引数で渡してはいけない。** Windows では claude が
    claude.CMD（バッチ）に解決されるため、最初の改行で切れる。実測で、
    引数で渡した複数行は1行目しか届かず、書き換えが24本続けて空振りした。
    """
    return subprocess.run(args, cwd=cwd or ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="ignore", timeout=timeout,
                          input=stdin_text)


def aio_items():
    """1ページ目にいるのに AI Overview に答えを取られている疑いの記事（最優先）。

    ai_citation_check が月ごとに data/ai_citations/YYYY-MM.json に残す。
    順位はあるのにクリックが期待の半分未満＝AIが答えを出し、自社は引用されていない。
    直す手は「そこにしか無い情報」を先頭に置くこと（第8.2章の最高優先度）
    """
    # 月の記録（YYYY-MM.json）だけ。*.json だと followup.json が最新に来て、候補が空になっていた。
    # お客様の社の分は data/clients/<id>/private/ にある（client_private が合わせる）
    import client_private as CP
    months = CP.citation_months()
    if not months:
        return []
    try:
        d = CP.load_citations(months[-1])
    except Exception:
        return []
    out, seen = [], set()
    for sid, s in (d.get("sites") or {}).items():
        for it in s.get("items") or []:
            slug = (it.get("url") or "").rstrip("/").rsplit("/", 1)[-1]
            if not slug or slug in seen or not (ROOT / "articles" / f"{slug}.md").is_file():
                continue
            seen.add(slug)
            out.append({"kind": "aio", "slug": slug, "site": sid,
                        "why": (f"{it.get('pos', 0):.1f}位・表示{it.get('imp', 0)}・CTR{it.get('ctr', 0)}%"
                                f"（目安{it.get('expected_ctr', 0)}%）｜「{it.get('kw', '')}」でAI Overviewに答えを取られている疑い")})
    return out


def audit_items():
    """別工程の採点（score_audit・今の基準）で一次性が80点を割った記事。

    自己採点は全記事90点以上だが、別工程では2026-09に採点した4本すべてが一次性45〜66点だった。
    直す手は aio と同じ（登録済みの一次情報の数字だけを足す。無い事実は書かせない）"""
    try:
        import rubric as R
        d = json.loads((ROOT / "data" / "score_audit.json").read_text(encoding="utf-8"))
        ver = R.VERSION
    except Exception:
        return []
    out = []
    for slug, r in d.items():
        a = r.get("audit") or {}
        o = (a.get("axes") or {}).get("originality")
        if o is None or o >= 80 or a.get("version") != ver:
            continue
        if not (ROOT / "articles" / f"{slug}.md").is_file():
            continue
        out.append({"kind": "aio", "slug": slug, "site": site_of(slug),
                    "why": f"別工程の採点で一次性{o}点（80点未満）・合計{a.get('total')}点"})
    return sorted(out, key=lambda x: x["why"])


def targets():
    """直すべき記事を、効く順に受け取る。

    最優先は「1ページ目にいるのに AI Overview に取られている」記事（aio_items）。
    次に rank_up の「4〜10位でクリックが取れていない」。無ければ auto_improve の一覧。
    """
    # 語の欠落（stuck）を先に置く。aio より成果が確かめやすいため。
    # aio は「1ページ目にいるのにAIに答えを取られている」記事を直す種別だが、
    # 実行すると3本続けて「変更なし（直す必要なしと判断）」を返した。
    # 構造が既に整っている記事が多く、直す余地が無い。一方 stuck は
    # 「需要のある語に答える節が無い」という具体的な欠けで、
    # 直ったかを見出しで機械的に確かめられる（2026-09-22 の実測）
    head = []
    try:
        import rank_rescue as RR
        head = RR.items()                    # 表示が多い順に来る
    except Exception as e:
        print(f"  （rank_rescue から取れません: {str(e)[:50]}）")
    seen0 = {x["slug"] for x in head}
    head = head + [x for x in aio_items() if x["slug"] not in seen0]
    # 採点（一次性）だけを理由にした書き直しは週次の対象にしない（audit_items は残すが、ここでは使わない）。
    # 自社データでは点数と順位が揃わず（91〜93点が96点以上より上。公開日数を揃えても同じ・2026-10-04）、
    # 一次性は登録済みのデータが無いと書き直しても上がらなかった（補助金の旧記事12本で確認）。
    # 書き直しの時間は、順位とクリックで効いたかを測れる記事に使う。公開の条件（90点・各80点）は変えない
    try:
        import rank_up
        items = rank_up.human_items()
        if items or head:
            seen = {x["slug"] for x in head}
            return head + [x for x in items if x["slug"] not in seen]
    except Exception as e:
        print(f"  （rank_up から取れないため auto_improve を使います: {str(e)[:40]}）")
    import auto_improve as ai
    try:
        return ai.human_items()
    except AttributeError:
        # auto_improve が一覧を返さない版のときは、出力から拾う
        r = sh([sys.executable, "scripts/auto_improve.py"])
        out = []
        for m in re.finditer(r"\[(title|review)\]\s+(\S+)\s+(.*)", r.stdout or ""):
            out.append({"kind": m.group(1), "slug": m.group(2), "why": m.group(3).strip()})
        return out


FRESH_DAYS = 180


def fresh_items(limit=4):
    """公開（または更新）から180日以上たった公開記事。古い順"""
    import datetime as _dt
    old = (_dt.date.today() - _dt.timedelta(days=FRESH_DAYS)).isoformat()
    rows = []
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        sc = re.search(r"^score:\s*(\d+)", fm, re.M)
        if not sc or int(sc.group(1)) < 90:
            continue
        d = re.search(r"^modified:\s*(\d{4}-\d{2}-\d{2})", fm, re.M) or re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", fm, re.M)
        if not d or d.group(1) > old:
            continue
        rows.append({"kind": "fresh", "slug": p.stem, "site": site_of(p.stem),
                     "why": f"公開・更新から{FRESH_DAYS}日以上（{d.group(1)}）。時点表記と dateModified を更新する"})
    rows.sort(key=lambda r: r["why"])
    return rows[:limit]


def ext_links(s):
    """本文の外部URL（HTMLの href と Markdown のリンクの両方）"""
    return set(re.findall(r'href="(https?://[^"]+)"', s)) | set(re.findall(r"\]\((https?://[^)\s]+)\)", s))


def aisplit_items(limit=2):
    """AIに聞いた調査（data/ai_survey）で答えが割れた問いを持ち、まだその文が入っていない記事"""
    import subsidy_survey as SV
    rows = []
    for f in sorted((ROOT / "data" / "ai_survey").glob("*/*.json")):
        slug = f.stem
        art = ROOT / "articles" / f"{slug}.md"
        if not art.is_file():
            continue
        rec = json.loads(f.read_text(encoding="utf-8"))
        split_qs = []
        for q, by in (rec.get("stance") or {}).items():
            labels = {v["label"] for v in by.values() if v.get("label") in ("yes", "cond", "no")}
            if len(labels) >= 2:
                split_qs.append(q)
        if not split_qs:
            continue
        cl = [c["claim"] for c in SV.claims(slug) if any(f"「{q}」" in c["claim"] for q in split_qs)]
        body = art.read_text(encoding="utf-8-sig")
        if not cl or "と聞いたところ" in body:
            continue                       # 書ける文が無い、または既に入っている
        rows.append({"kind": "aisplit", "slug": slug, "site": site_of(slug), "claims": cl,
                     "why": f"AIの答えが割れた問い {len(split_qs)}件（{split_qs[0][:30]}）"})
    return rows[:limit]


EARLY_DAYS = (14, 35)       # 公開2〜5週目。1〜3週が表示の山で、6週で山の約1/4に落ちる（2026-10-05・3サイト）
EARLY_POS, EARLY_IMP = 15, 3  # 6週以降も残った記事を分けた線（ある語で15位以内・3回以上表示）


def narrower_terms(q, kw):
    """検索語 q が狙う語 kw より細い（kw の語を1つ以上含み、kw に無い語が1つ以上ある）なら、
    q のうち kw に無い・kw の語を細かくした語を返す。細くなければ空"""
    import kw_reach
    from rank_rescue import norm
    nk = norm(kw)
    kt = [norm(t) for t in kw_reach.tokens(kw) if len(norm(t)) >= 2]
    shared, extra = 0, []
    toks = kw_reach.tokens(q)
    if len(toks) < 2:
        return []
    for t in toks:
        n = norm(t)
        if len(n) < 2:
            continue
        if n in nk:
            shared += 1
        elif any(k in n for k in kt):
            shared += 1
            extra.append(t)            # 「照合」→「三点照合」のように語を細かくした
        else:
            extra.append(t)
    return extra if shared and extra else []


def _ranks_rows(site):
    """data/ranks/<site>.json の最新の28日（語×ページ）。rank_track が毎日残す。Search Console を呼ばない"""
    try:
        hist = json.loads((ROOT / "data" / "ranks" / f"{site}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return hist[sorted(hist)[-1]] if hist else []


def _done_kind(kind, log=None):
    """その種類で一度でも直した（ok）記事。early は1記事1回まで（公開直後の1回で効かせる）"""
    f = Path(log) if log else LOG
    out = set()
    for line in CP.read_lines(f):            # お客様の記事の行（置き場）も合わせて読む
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("kind") == kind and d.get("ok"):
            out.add(d.get("slug"))
    return out


def early_items(limit=2, today=None, rows_of=None, log=None):
    """公開14〜35日の記事のうち、狙う語より細い語で15位以内・3回以上表示が出ているもの（表示の多い順）。

    6週以降も残った記事は公開1〜4週にある語で15位以内に入っていて、残った表示の73%はその細い語だった。
    山が過ぎる前に、その語を題・H2・FAQに入れて15位以内を確かにする"""
    import datetime as _dt
    import sites as S
    today = today or _dt.date.today()
    lo, hi = (str(today - _dt.timedelta(days=d)) for d in (EARLY_DAYS[1], EARLY_DAYS[0]))
    rows_of = rows_of or _ranks_rows
    done = _done_kind("early", log)
    arts, kws = {}, {}
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.group(1), m.group(2)
        g = lambda k: (re.search(rf"^{k}:\s*(.+)$", fm, re.M) or [0, ""])[1].strip().strip('"')
        kws[re.sub(r"\s", "", g("keyword").lower())] = p.stem
        sc, d = g("score"), g("date")[:10]
        if not sc.isdigit() or int(sc) < 90 or not (lo <= d <= hi) or p.stem in done:
            continue
        heads = [g("title")] + re.findall(r"^#{2,3}\s*(.+)$", body, re.M)
        arts[p.stem] = {"kw": g("keyword"), "date": d, "heads": heads,
                        "site": S.find_category_owner(g("category")) or ""}
    best_of = {}
    for sid in sorted({a["site"] for a in arts.values() if a["site"]}):
        rows = rows_of(sid)
        top = {}                                   # 語 → いちばん上にいる自社ページ
        for r in rows:
            if r.get("kw") and (r["kw"] not in top or r["pos"] < top[r["kw"]][1]):
                top[r["kw"]] = (r["url"].rstrip("/").rsplit("/", 1)[-1], r["pos"])
        for r in rows:
            slug = r["url"].rstrip("/").rsplit("/", 1)[-1]
            a = arts.get(slug)
            if not a or a["site"] != sid or r["imp"] < EARLY_IMP or r["pos"] > EARLY_POS:
                continue
            q = r["kw"]
            if top.get(q, (slug,))[0] != slug:
                continue                           # 同じ語で別の自社ページが上にいる（入れると食い合う）
            other = kws.get(re.sub(r"\s", "", q.lower()))
            if other and other != slug:
                continue                           # 別の記事がその語を狙っている
            terms = narrower_terms(q, a["kw"])
            if not terms or all(heads_cover_terms(a["heads"], [x]) for x in terms):
                continue                           # 細くない、または題・見出しで既に扱っている
            if slug in best_of and best_of[slug]["imp"] >= r["imp"]:
                continue
            age = (today - _dt.date.fromisoformat(a["date"])).days
            best_of[slug] = {"kind": "early", "slug": slug, "site": sid, "query": q, "pos": r["pos"],
                             "imp": r["imp"], "terms": terms, "age": age,
                             "why": f"公開{age}日・細い語「{q}」で{r['pos']:.1f}位・表示{r['imp']}回（狙う語「{a['kw']}」）"}
    return sorted(best_of.values(), key=lambda x: -x["imp"])[:limit]


def faq_questions(text):
    """フロントマターの faq の問い"""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    return re.findall(r"^\s*-\s*q:\s*(.+)$", m.group(1), re.M) if m else []


def early_guard(before, after, title0, title1, item):
    """early の書き直しにだけ足す検算（共通の check() の後）。通らない理由を返す（空なら合格）"""
    from cannibal_check import dice
    from rank_rescue import norm
    if title1 != title0 and dice(norm(title0), norm(title1)) < 0.5:
        return f"題を変えすぎています（{title0} → {title1}）。細い語を足すだけの直しです"
    h0, h1 = len(re.findall(r"^##\s", before, re.M)), len(re.findall(r"^##\s", after, re.M))
    if not 0 <= h1 - h0 <= 1:
        return f"H2の本数が{h0}→{h1}本（変えないか、1本足すだけ）"
    q0, q1 = faq_questions(before), faq_questions(after)
    if len(q1) < len(q0):
        return f"FAQ が減りました（{len(q0)}→{len(q1)}問）"
    if not any(norm(x) in norm(q) for q in q1 for x in item.get("terms") or ()):
        return "FAQ に細い語の問いが入っていません（" + "/".join((item.get("terms") or [])[:3]) + "）"
    more = ext_links(after) - ext_links(before)
    if more:
        return "出典のURLが増えました（記事にあった出典だけで書くこと）: " + str(sorted(more)[:2])
    return ""


COMPETE_LOCK_DAYS = 28   # effect_ab --rewrites・rewrite_rollback が前後28日で比べる。その間に重ねて直さない


def compete_items(limit=2, log=None):
    """競合がAIの出典に出て自社が出ない語のうち、差が書き直しで埋まるもの（compete --gaps が月次で書く）。
    一次データが無いと勝てない語（needs_data）は書き直さない（運用者への要対応になる）"""
    from datetime import date, timedelta
    since = str(date.today() - timedelta(days=COMPETE_LOCK_DAYS))
    recent = set()
    f = Path(log) if log else LOG
    for line in CP.read_lines(f):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("kind") == "compete" and d.get("ok") and str(d.get("at", ""))[:10] >= since:
            recent.add(d.get("slug"))
    rows, seen = [], set()
    for g in sorted((ROOT / "data" / "compete").glob("*/gaps.json")):
        try:
            gd = json.loads(g.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for it in gd.get("items") or []:
            slug = it.get("slug") or ""
            if it.get("action") != "rewrite" or not slug or slug in seen or slug in recent \
                    or not (ROOT / "articles" / f"{slug}.md").is_file():
                continue
            seen.add(slug)
            rows.append({"kind": "compete", "slug": slug, "site": gd.get("site") or site_of(slug), "imp": it.get("imp") or 0,
                         "gap": it, "why": f"「{it['kw']}」でAIの出典に競合（{'・'.join(it.get('competitors', [])[:2])}）が出て、自社が出ていない"})
    rows.sort(key=lambda r: -r["imp"])
    return rows[:limit]


def copied_heads(before, after, heads, min_len=10):
    """競合の見出しを、そのまま本文に写したもの（直す前には無かったもの）"""
    nz = lambda s: re.sub(r"[\s　、。・「」（）()【】|｜:：!！?？]", "", s or "")
    a, b = nz(after), nz(before)
    return [h for h in heads if len(nz(h)) >= min_len and nz(h) in a and nz(h) not in b]


def compete_guard(before, after, title0, title1, gap):
    """compete の書き直しにだけ足す検算（共通の check() の後）。通らない理由を返す（空なら合格）"""
    if title1 != title0:
        return "タイトルが変わりました（足りない問いを足す直しで、題は変えない）"
    more = ext_links(after) - ext_links(before)
    if more:
        return "出典のURLが増えました（記事にあった出典だけで書くこと）: " + str(sorted(more)[:2])
    heads = [h for t in gap.get("their_pages") or [] for h in t.get("heads") or []]
    cp = copied_heads(before, after, heads)
    if cp:
        return "競合の見出しをそのまま写しています: " + " / ".join(cp[:2])
    if len(after) < len(before) * 0.98:
        return f"本文が減りました（{len(before)}→{len(after)}字）。足す直しのはずです"
    return ""


def keep_before(slug, raw, after_raw):
    """28日後に効かなければ戻すため、直す前の原稿を残す（rewrite_rollback が読む）。
    戻すのは、その後だれも触っていないとき（after_sha が一致）だけ"""
    import hashlib
    d = ROOT / "data" / "rewrite_before"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{slug}@{time.strftime('%Y-%m-%d')}.md"
    p.write_bytes(raw)
    return {"before_path": p.relative_to(ROOT).as_posix(), "after_sha": hashlib.sha1(after_raw).hexdigest()}


def question_items(limit=4):
    """H2に質問形が1本も無い公開記事（表示の多い順は取らず、古い順）"""
    rows = []
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", t, re.S)
        if not m:
            continue
        fm, body = m.group(1), m.group(2)
        sc = re.search(r"^score:\s*(\d+)", fm, re.M)
        if not sc or int(sc.group(1)) < 90:
            continue
        h2 = re.findall(r"^##\s+(.+)$", body, re.M)
        if len(h2) < 4 or any(re.search(r"[?？]", h) for h in h2):
            continue
        d = re.search(r"^date:\s*(\S+)", fm, re.M)
        rows.append({"kind": "question", "slug": p.stem, "site": site_of(p.stem),
                     "why": f"H2 {len(h2)}本に質問形が1本も無い（公開 {d.group(1) if d else '-'}）"})
    rows.sort(key=lambda r: r["why"])
    return rows[:limit]


def desc_items(limit=4, days=28):
    """流入している上位の語が description の先頭40字に無い公開記事（表示の多い順）"""
    import gsc_detail as G
    import sites as S
    from datetime import date as _d, timedelta as _td
    end = _d.today() - _td(days=3)
    start = end - _td(days=days)
    try:
        sc = G.client()
    except Exception:
        return []
    metas = {}
    for p in (ROOT / "articles").glob("*.md"):
        t = p.read_text(encoding="utf-8-sig")
        m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
        if not m:
            continue
        fm = m.group(1)
        sc_ = re.search(r"^score:\s*(\d+)", fm, re.M)
        cat = re.search(r"^category:\s*(\S+)", fm, re.M)
        if not sc_ or int(sc_.group(1)) < 90 or not cat:
            continue
        metas[p.stem] = {"desc": _desc_of(t), "site": S.find_category_owner(cat.group(1)) or ""}
    rows = []
    for cfg in S.load_all().values():
        by = {}
        for r in G.q(sc, cfg["domain"], str(start), str(end), ["query", "page"], 25000):
            slug = r["keys"][1].rstrip("/").split("/")[-1]
            if slug in metas:
                by.setdefault(slug, []).append((r["keys"][0], int(r["impressions"])))
        for slug, qs in by.items():
            qs.sort(key=lambda x: -x[1])
            top = [q for q, imp in qs[:3] if imp >= 10]
            if not top:
                continue
            head = metas[slug]["desc"][:40].lower()
            toks = [w for w in re.split(r"[\s　]+", top[0].lower()) if len(w) >= 2]
            # 100字未満の説明文も直す対象（Bing が「短すぎる」と指摘する。2026-10-05）
            short = len(metas[slug]["desc"]) < 100
            if toks and all(w in head for w in toks) and not short:
                continue
            rows.append({"kind": "desc", "slug": slug, "site": metas[slug]["site"], "queries": top,
                         "imp": sum(imp for _, imp in qs[:3]),
                         "why": (f"説明文が{len(metas[slug]['desc'])}字で短い" if short else
                                 f"流入語「{top[0]}」が説明文の先頭に無い")
                                + f"（表示{sum(imp for _, imp in qs[:3])}回）"})
    rows.sort(key=lambda r: -r["imp"])
    return rows[:limit]


def split_items(limit=4):
    """同じ語に自社の2本が出ているが、主題が別で統合しない組（auto_merge が「主題が違う」で見送る組）。
    弱い側の題と説明文を、その記事の狙う語へ寄せて付け分ける。共通の話題は相手の記事へ渡す"""
    import auto_merge as AM
    nz = lambda s: re.sub(r"[\s　]+", "", (s or "").lower())

    def owns(slug, q):
        t, k, _ = meta(slug)
        return nz(q) in nz(k) or nz(q) in nz(t)

    def retitled(slug):
        # 28日以内に題を変えた記事は、効きが出るまで待つ（直した直後に逆側を直すと、どちらが効いたか分からない）
        r = sh(["git", "log", "--since=28.days", "-p", "--format=", "--", f"articles/{slug}.md"], timeout=60)
        return bool(re.search(r"^[-+]title:", r.stdout or "", re.M))

    out, seen = [], set()
    for p in AM.candidates():
        if "主題が違う" not in (p.get("skip") or ""):
            continue
        shared = [k["kw"] for k in p["kws"]]
        a, b = p["loser"], p["survivor"]
        if not all((ROOT / "articles" / f"{s}.md").is_file() for s in (a, b)):
            continue
        if retitled(a) or retitled(b):
            continue
        # 共通の語をすでに狙っている側は持ち主。持っていない側を付け分ける（両方持っていれば見送る）
        free = [s for s in (a, b) if not owns(s, shared[0])]
        if not free:
            continue
        lose = a if a in free else free[0]
        other = b if lose == a else a
        if lose in seen:
            continue
        seen.add(lose)
        out.append({"kind": "split", "slug": lose, "site": p["site"], "imp": p["imp"],
                    "other": other, "other_title": meta(other)[0], "other_url": AM.url_of(p["site"], other),
                    "shared": shared,
                    "why": f"「{shared[0]}」で同じサイトの別記事と競り合い、互いの順位を下げている（主題は別なので統合しない）"})
    out.sort(key=lambda x: -x["imp"])
    return out[:limit]


PROMPT = """articles/{slug}.md を直してください。この1ファイル以外は触らないでください。

直す理由: {why}

{what}

必ず守ること:
- 事実を変えない。数字・社名・出典・年月日は1文字も変えない。**新しい数字を書かない**
- 外部の出典リンク（href="http…"）を消さない
- ですます調。1文は50字を目安、100字を超えない
- フロントマターの keyword は変えない
- 記事の主張をずらさない。読者が求めている答えを先に書く
- 当社の採択率・支援社数は書かない。当社が申請書類を作成する・申請を代行すると読める文を書かない
  （当社は申請に向けた相談・助言と内容の確認を行い、申請書類はお客様が作成する）

直したら、変更点を1行で説明して終了してください。"""

WHAT = {
    # 採点（3観点）で基準に届かなかった記事を、採点者の指摘に沿って直す（旧形式の記事の移行で使う）
    "quality": ("この記事は品質の採点で基準（一次性・抽出性・決定支援の各80点以上、平均90点以上）に届きませんでした。\n"
                "採点者の指摘は次のとおりです:\n{weak}\n\n"
                "指摘を1つずつ直してください。守ること:\n"
                "- 一次性: 使ってよい数字は下の登録済みの一次情報だけ。無ければ数字は足さず、現場での判断の順番・\n"
                "  失敗しやすい点・確かめ方を具体的に書く。自社の採択率や支援社数は書かない\n"
                "- 母数と時期の無い自社の事例・実績・お客様の声（「当社支援事例」「当社支援実績」など）は削る。\n"
                "  採点で毎回減点される原因で、確かめられない話は信頼を落とす。下の調査の数字に置き換える\n"
                "- 登録済みの一次情報に「当社調べ」の調査があれば、その文をそのまま（数字を変えずに）2か所までに使い、\n"
                "  読者が次に何を確かめればよいかの根拠にする\n"
                "- 抽出性: 冒頭の2文で結論を言い切る。各H2の直後は、その節の答えを1文で言い切る\n"
                "- 決定支援: 読者が次に何をするか決められるよう、判断の基準か手順か比較表を1つ以上置く\n"
                "- 制度名・金額・締切は本文にあるものだけを使い、新しく足さない\n"
                "- title・keyword・slug・category は変えない。FAQ はフロントマターと本文の両方を同じ文にする\n"
                "登録済みの一次情報:\n{facts}"),
    "split": ("この記事と、同じサイトの別記事「{other_title}」（{other_url}）が、検索語「{shared}」で\n"
              "同時に検索結果に出て、互いの順位を下げています。主題は別なので統合はしません。\n"
              "この記事の title と description を、この記事の狙う語（keyword）の主題に寄せてください。\n"
              "共通の語「{shared}」をタイトルの前半に置かないこと。15〜45字。keyword は必ず残すこと。\n"
              "description は100〜160字（目安100〜150字）で、狙う語を含め、タイトルで言っていないことを書く。\n"
              "本文で共通の語の話題を詳しく扱っている段落があれば、要点1〜2文に縮め、\n"
              "詳しくは [{other_title}]({other_url}) へ案内する1文を添えてください（新しい節は足さない）。"),
    "title": ("フロントマターの title・description と、H1相当の書き出しを\n"
              "見直してください。検索結果に出るのはタイトルと説明文の両方で、\n"
              "説明文だけを直しても、タイトルだけを直しても効きません。\n"
              "この記事は表示されているのにクリックされていません。検索結果に並ぶ他の\n"
              "ページと同じことを言っているためです。**検索結果に出せないもの**\n"
              "（違反になる例・失敗した事例・自社で実際に測った数字）をタイトルの前半に置いて\n"
              "ください。15〜45字。狙う語（keyword）は必ず残すこと。\n"
              "【2026年最新】【2026年】のような飾りの年号は外してください（自社の実測で負けた型）。\n"
              "「2024年問題」のように中身として要る年は残します。\n"
              "description は100〜160字（目安100〜150字）。狙う語を含め、タイトルで言っていないことを書く\n"
              "（同じ文言を繰り返すと、検索結果で見える情報量が半分になる）。\n"
              "本文にない内容をタイトルや説明文に書かないこと（書くなら本文にも追記する）。"),
    "aio": ("この記事は検索1ページ目にいるのに、AI Overview（AIによる概要）が答えを出してしまい、\n"
            "クリックされていません。AIが引用するのは「そこにしか無い情報」です。\n"
            "1. 冒頭200字を、下に示す自社の一次情報（実数）を含む断言型の回答に書き直す\n"
            "2. 狙う語に対する答えを、40〜60字の1文＋比較表（または手順表）で本文の最初のH2直下に置く\n"
            "3. 「失敗例・注意点」の見出しに、一次情報から言える具体例を1つ足す\n"
            "4. FAQ の最初の1問を、狙う語そのものの質問にし、回答に一次情報の数字を1つ入れる\n"
            "使ってよい自社の一次情報（**この数字以外の新しい数字は書かない**）:\n{facts}"),
    "desc": ("この記事の説明文（description）が、実際に流入している検索語を前半に含んでいないか、100字に届いていません。\n"
             "検索結果に出る説明文に検索語が無いと、Googleが本文から別の文を切り出して並べ、意図が伝わりません。\n"
             "流入している語（多い順）:\n{queries}\n"
             "1. フロントマターの description だけを書き換える（100〜160字。目安100〜150字）。先頭40字以内に上の語のうち\n"
             "   最も多いものを自然に含める。タイトルと同じ文言の繰り返しは避ける\n"
             "2. 本文・タイトル・keyword・他のフロントマターは1文字も変えない\n"
             "3. 本文に無い数字・事実を書かない"),
    "aisplit": ("当社がこの記事の問いを ChatGPT・Claude・Gemini に聞いたところ、AIによって答えが割れました。\n"
                "AIに聞いても答えが定まらない問いに、根拠つきで答えている記事は他にありません。そこを書き足します。\n"
                "1. 冒頭の断言段落の直後（最初のH2より前）に、次の調査の文を**1文字も変えずに**そのまま1つ入れる:\n"
                "{claims}\n"
                "2. その直後に、なぜ答えが割れるのか（条件によって答えが変わる点）と、この記事としての答えを2〜4文で書く。\n"
                "   答えの根拠は、**この記事にすでにある出典リンクと本文の内容だけ**を使う。新しいURLは足さない\n"
                "   （AIが存在しないURLを作ることがあるため）。記事の中に根拠が無ければ、断言せず条件を分けて書く\n"
                "3. 見出しは足さない。上の調査の文以外の数字は足さない。狙う語・タイトル・FAQは変えない"),
    "question": ("この記事のH2見出しは名詞句ばかりで、質問の形がありません。自社の実測で、H2の1〜3割が\n"
                 "質問形の記事は、質問形ゼロの記事より平均4.2位上にいます。AI Overview は質問形の\n"
                 "クエリで64.7%出ます。\n"
                 "1. H2のうち**2〜3本だけ**を、読者がそのまま検索しそうな質問の形（「〜とは？」「〜はいくら？」\n"
                 "   「〜はどう選ぶ？」）に書き換える。まとめ・よくある質問・失敗例の見出しは変えない\n"
                 "2. 見出しの数と順番は変えない。増やさない、減らさない、統合しない\n"
                 "3. 見出しの直下の1文結論は、質問への答えになっているか読み直し、必要なら語順だけ整える\n"
                 "4. 本文・数字・出典・狙う語は変えない"),
    "fresh": ("この記事は公開（または最終更新）から6か月以上たっています。AI検索は鮮度を重視します。\n"
              "1. 「◯年◯月時点」「現在」「最新」など、時点を示す表現をすべて探す\n"
              "2. その記述が**いまも事実として正しいと本文の根拠から判断できる**箇所だけ、時点を「{ym}時点」に更新する\n"
              "3. 制度・料金・機能など、変わった可能性があり本文の根拠だけでは確かめられない箇所は、\n"
              "   数字も文も変えず、その文の直後に「（{ym}時点の再確認中）」とだけ添える\n"
              "4. 冒頭の鮮度表記が無ければ、冒頭ボックスの近くに「この記事は{ym}時点の情報です」を1文足す\n"
              "**新しい数字・新しい事実は書かない。** 年月の更新以外で数字を増やしてはいけない。\n"
              "見出し・狙う語・出典リンクは変えない。"),
    "stuck": ("この記事は検索1ページ目の手前（11〜30位）で止まっています。\n"
              "**実際に検索されている語に、記事が答えていない**のが原因です。\n"
              "下に、その語と順位・表示回数を挙げます。\n"
              "1. その語が扱う内容が、この記事の主題に**本当に含まれるか**を最初に判断する\n"
              "   含まれないなら、何も変えずに終了する（無理に足すと主題がぼやけて、\n"
              "   いま取れている順位まで落ちる）\n"
              "2. 含まれるなら、その語に答える**H2またはH3の節を1つ足す**。\n"
              "   見出しにその語を自然な日本語で入れ、直下に40〜60字の1文結論を置く\n"
              "3. 語を本文にちりばめる直し方はしないこと。読者が読んで意味のある\n"
              "   節になっていなければ順位は動かない\n"
              "4. 既存の見出し・本文は消さない。足すだけにする\n"
              "5. 同義語・言い換え（例: 整骨院と接骨院）なら別々の節を作らず、\n"
              "   1つの節でまとめて扱い、両方の呼び方を本文に書く\n"),
    "compete": ("この記事の狙う語「{kw}」で、AIの回答の出典に競合のページが選ばれ、この記事は選ばれていません。\n"
                "競合の公開ページと比べて、この記事に足りないものは次のとおりです\n"
                "（競合の見出しは「どんな問いに答えているか」の手がかりです。見出しも文も写さないこと）:\n{diffs}\n"
                "1. 足りない問いのうち、この記事の主題に**本当に含まれるもの**だけに答える節（H2またはH3）を足す。\n"
                "   見出しは自分の言葉で書き、直下に40〜60字の1文結論を置く。主題に含まれなければ足さない\n"
                "2. 「表」が足りないと出ていれば、この記事にすでにある情報だけで比較表か手順表を1つ置く\n"
                "3. 新しい数字は、下の登録済みの一次情報だけを使う。出典のURLは足さない（記事にある出典だけを使う）\n"
                "4. タイトル・keyword・既存の見出しと本文は変えない。足すだけにする\n"
                "5. どれも主題に含まれなければ、何も変えずに終了する\n"
                "登録済みの一次情報（この数字以外の新しい数字は書かない）:\n{facts}"),
    "early": ("この記事は公開から{age}日です。自社3サイトの実測では、公開1〜4週のうちにある語で15位以内に入った\n"
              "記事だけが6週以降も表示を保ち、その表示の7割は狙う語より細い語でした。\n"
              "いま、狙う語より細い検索語「{query}」で{pos}位・表示{imp}回が出ています。この語を3か所に自然に入れます。\n"
              "1. title: {title_rule}\n"
              "2. H2: 既存のH2のうち「{query}」に最も近い1本の見出しに、その語を自然な日本語で入れる（本数・順番は変えない）。\n"
              "   近いH2が無ければ、その語に答えるH2を1本だけ足し、直下に40〜60字の1文結論を置く\n"
              "3. FAQ: 「{query}」をそのまま問う質問を1問足す。フロントマターの faq と本文の「よくある質問」の両方に\n"
              "   同じ文で入れる。回答は本文にある内容だけで40〜60字\n"
              "4. その語が記事の主題に含まれない（別の記事で扱うべき）と判断したら、何も変えずに終了する\n"
              "5. 既存の本文・見出しは消さない。新しい数字・出典URLは足さない。keyword は変えない"),
    "review": ("直前の自動修正で表示回数が落ちています。検索意図とずれた可能性があります。\n"
               "冒頭200字と各H2直下の1文結論を読み、狙う語で検索した人が求めている答えに\n"
               "なっているか確かめてください。ずれていれば直してください。\n"
               "ずれていなければ何も変えずに終了してください（無理に直さない）。"),
}


PERM = json.dumps({"permissions": {
    # articles/ の書き換えだけを許す。Bash も外部通信も渡さないので、
    # この工程にできるのは原稿1本の書き換えだけ。
    # 全権限を飛ばす指定は使わない（ゲートが綴りの有無で見張っている）
    "allow": ["Read", "Edit(articles/**)"],
    "defaultMode": "acceptEdits",
}}, ensure_ascii=False)


KW_NOISE = re.compile(r"[\s　のをにはがともへやかでるな・｜|【】\[\]「」（）()？?！!、。,.:：/／-]")


def title_covers_kw(title, kw):
    """タイトルが狙う語を扱っているか。助詞・記号の違いは同じ語とみなす。

    そのまま含まれるかだけで見ると「中小企業助成金」に対する
    「中小企業の助成金とは？」が落ちる。落ちた記事は検算を通らないので、
    どう直しても差し戻され、二度と直せなくなる（実測4本）。
    """
    parts = [w for w in re.split(r"[\s　]+", kw) if len(w) >= 2]
    if not parts:
        return True
    lt = title.lower()
    if any(w.lower() in lt for w in parts):
        return True
    nt, nk = KW_NOISE.sub("", lt), KW_NOISE.sub("", kw.lower())
    if nk and nk in nt:
        return True
    # 自然文の狙う語は丸ごと一致しない。内容語がどれだけ入っているかで見る
    toks = [x for x in re.split(KW_NOISE, kw.lower()) if len(x) >= 2]
    if not toks:
        return False
    hit = sum(1 for x in toks if KW_NOISE.sub("", x) in nt)
    return hit / len(toks) >= 0.7


def claude_bin():
    """claude の実行ファイルを解決する。

    Windows では `claude` は claude.cmd として入るため、名前だけを
    subprocess に渡すと WinError 2 になる（CreateProcess は PATHEXT を
    探さない）。Linux の CI では通るので、手元だけで落ちて気づきにくい。
    """
    import shutil
    return shutil.which("claude") or shutil.which("claude.cmd") or "claude"


# 記事を書く・書き直すときに使うモデル。上から順に、使える最初のものを選ぶ。
# **版が古いと 400 で落ちる**（実測: 2.1.218 は claude-opus-5-5 を
# 「version 2.1.280 or newer is required」で拒否した）。手元とCIで版が違うため、
# 名前を決め打ちにせず、版を見て切り替える
# 定型の直し・台本・下書きは Sonnet で足りる（結果は検算・門が止める）。Opus は使用量が大きく、
# サブスクの枠を早く使い切っていた（2026-10-03 ユーザーの指示で切り替え）。記事の執筆（pipeline-multi）は別に指定する
MODELS = [("claude-sonnet-5-5", (2, 1, 280)), ("claude-sonnet-5", (0, 0, 0))]


def cli_version():
    try:
        out = subprocess.run([claude_bin(), "--version"], capture_output=True,
                             text=True, timeout=60).stdout
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
    except Exception:
        return (0, 0, 0)


def model_args():
    """`--model ...` を返す。使えない版なら1つ下のモデルに落とす"""
    v = cli_version()
    for name, need in MODELS:
        if v >= need:
            return ["--model", name]
    return []


def warns(slug):
    r = sh([sys.executable, "scripts/score_check.py", slug], timeout=300)
    return [l for l in (r.stdout or "").splitlines() if l.startswith("WARN")]


def meta(slug):
    t = (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")
    fm = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    fm = fm.group(1) if fm else ""
    g = lambda k: (re.search(rf"^{k}:\s*(.+)$", fm, re.M) or [0, ""])[1].strip().strip('"')
    return g("title"), g("keyword"), t


def numbers(s):
    return collections.Counter(re.findall(r"[0-9０-９][0-9０-９,，.．%％]*", s))


def fact_numbers(added, had):
    """増えた数字のうち、事実として扱うべきものだけを返す。

    節を足す直しでは「3つの観点」のような個数が必ず増える。回数の差だけで
    見ると、正しい書き換えまで差し戻されて一本も直せない（実測で2/3が該当）。
    止めたいのは、記事に無かった事実の数字が公開されることだけ。
    """
    # 記事に既にある数字を別の箇所で繰り返すのは、新しい事実ではない。
    # 以前は「1,600」のような桁区切りの数字は既出でも回数が増えれば止めていたため、
    # タイトルにある時給相場（1,600〜2,500円）を本文の答えに書いただけで差し戻した（2026-09-28）
    return {tok: n for tok, n in added.items() if tok not in had}


def new_fact_numbers(before, after, allowed=""):
    """書き換えで増えた、記事にも許可した一次情報にも無い数字"""
    # 許可した一次情報の数字は、何回使ってもよい。回数で引くと、同じ事実を
    # 2箇所に書いただけで差し戻される（実測で4本が「3,200」で落ちた）
    added = numbers(after) - numbers(before)
    for tok in set(numbers(allowed or "")):
        added.pop(tok, None)
    return fact_numbers(added, numbers(before) + numbers(allowed or ""))


def heads_cover_terms(heads, terms):
    """足した語が見出しに入ったか。rank_rescue が「足りない」と判定したのと同じ物差しで見る。

    素の部分一致で見ていたため、rank_rescue が「足りている」とみなす書き方
    （「aiocr」に対する「AI-OCR」、「tool」に対する「AIOツール」）で節を足しても
    差し戻し、その記事は何度直しても通らなかった（2026-09-23 に同じ穴を rank_rescue 側だけ塞いでいた）"""
    from rank_rescue import norm, _covered_by_kana
    hay = norm(" ".join(heads))
    return any(norm(x) in hay or _covered_by_kana(x, hay) for x in terms)


def false_alarms():
    """通すべき書き換えを差し戻す穴。返すのは差し戻してしまった例の名前（空なら健全）。

    selftest は「止めるべき例」しか試しておらず、正しい書き換えを止める誤検出は
    記事が永久に直せない形でしか表に出なかった（2026-09-23〜28 に5種類）"""
    base = "title: 時給1,500円の経理代行\n本文。3つの手順と2026年の制度。3,200店舗が導入。\n"
    cases = [
        ("桁区切りの既出数字を本文で繰り返す",
         not new_fact_numbers(base, base + "相場は1,500円です。\n")),
        ("同じ事実を2回目に書く",
         not new_fact_numbers(base, base + "3,200店舗の例です。\n3,200店舗では\n", "3,200店舗")),
        ("既出の個数「3」が1回増えるだけ", not new_fact_numbers(base, base + "3つの観点で見ます。\n")),
        ("英語表記の語を日本語の見出しで扱う", heads_cover_terms(["AIOツールの選び方"], ["tool"])),
        ("ハイフンつきの AI-OCR を見出しで扱う", heads_cover_terms(["AI-OCRで請求書を読む"], ["aiocr"])),
        ("題の助詞違い", title_covers_kw("中小企業の助成金とは？申請の流れ", "中小企業助成金")),
        ("細い語を題・H2・FAQに足すだけ（early）",
         not early_guard("---\nfaq:\n  - q: 工務店のMEOとは？\n---\n## 始め方\n本文\n",
                         "---\nfaq:\n  - q: 工務店のMEOとは？\n  - q: 工務店のMEOが上がらないときは？\n---\n"
                         "## 始め方\n本文\n## 順位が上がらないときは？\n本文\n",
                         "工務店のMEO対策｜始め方と5つのコツ", "工務店のMEO対策｜上がらない時の5つのコツ",
                         {"terms": ["上がらない"]})),
    ]
    return [name for name, ok in cases if not ok]


def sources(s):
    return set(re.findall(r'href="(https?://[^"]+)"', s))


def snapshot():
    """articles/ の指紋。「触ったのはこの1本だけか」を、git ではなく直前の状態と比べる。

    週次では link_boost・rank_up・split_paragraphs が先に記事を直し、その分は
    まだコミットされていない。git status と比べると、その未コミットの記事が
    「別の記事まで変わっている」と見なされ、正しい書き換えまで毎回戻していた"""
    import hashlib
    return {p.name: hashlib.sha1(p.read_bytes()).hexdigest() for p in (ROOT / "articles").glob("*.md")}


def changed_since(snap):
    now = snapshot()
    return sorted(n for n in set(snap) | set(now) if snap.get(n) != now.get(n))


def guard_message(rc):
    """kw_guard の終了コードを差し戻しの理由にする。

    3（判定不能）を「食い合います」と書くと、GSC の鍵や通信が原因なのに
    記事の中身を疑って直しに行ってしまう。動かなかったことはそのまま書く。
    """
    if rc == 3:
        return "食い合いの検査が動きませんでした（鍵・通信を確認）（kw_guard 終了コード3）"
    return f"既存記事と食い合います（kw_guard 終了コード{rc}）"


def check(slug, before, before_warns, snap=None, allowed="", terms=()):
    """直した結果を検算する。通らない理由を返す（空なら合格）"""
    if snap is not None:
        other = [c for c in changed_since(snap) if c != f"{slug}.md"]
    else:
        changed = [l[3:].strip() for l in
                   (sh(["git", "status", "--porcelain", "--", "articles"]).stdout or "").splitlines()]
        other = [c for c in changed if c != f"articles/{slug}.md"]
    if other:
        return f"別の記事まで変わっています: {', '.join(other[:3])}"

    title, kw, after = meta(slug)
    _, kw0, _ = before
    if kw != kw0:
        return f"狙う語が変わりました（{kw0} → {kw}）"
    if not (TITLE_MIN <= len(title) <= TITLE_MAX):
        return f"タイトルが{len(title)}字（{TITLE_MIN}〜{TITLE_MAX}字）"
    if not title_covers_kw(title, kw):
        return f"タイトルに狙う語が入っていません（{kw}）"

    b = before[2]
    new_nums = new_fact_numbers(b, after, allowed)
    if new_nums:
        return f"本文に無かった数字が増えました: {dict(list(new_nums.items())[:4])}"
    lost = sources(b) - sources(after)
    if lost:
        return f"出典リンクが消えました: {list(lost)[:2]}"

    now = warns(slug)
    if len(now) > len(before_warns):
        # 何の警告かを返す。件数だけでは、やり直しのときに直す場所が分からない
        new = [w for w in now if w not in before_warns]
        return f"警告が増えました（{len(before_warns)} → {len(now)}）: " + " / ".join(new)[:400]

    # --exclude-slug を必ず渡す。渡さないと、その記事自身が食い合い相手として
    # 数えられ、順位を持つ記事のリライトは100%差し戻される。
    # 実際 kw_guard は「狙う語が既存記事と完全一致: meo-algorithm-kouryaku」と
    # 自分自身を挙げて終了コード2を返していた（2026-09-22 に発見）
    r = sh([sys.executable, "scripts/kw_guard.py", kw, "--site",
            site_of(slug), "--title", title, "--exclude-slug", slug], timeout=600)
    if r.returncode:
        return guard_message(r.returncode)

    if terms:
        # 「足した」と言いながら見出しが変わっていないものを通さない。
        # 本文にちりばめるだけの直し方では順位は動かない
        if not heads_cover_terms(re.findall(r"^#{2,4}\s*(.+)$", after, re.M), terms):
            return "狙った語が見出しに入っていません（" + "/".join(terms[:3]) + "）"
        if len(after) < len(b) * 0.98:
            return f"本文が減りました（{len(b)}→{len(after)}字）。足す直しのはずです"

    r = sh([sys.executable, "scripts/build.py"], timeout=1800)
    if r.returncode or "BLOCKED" in (r.stdout or ""):
        return "ビルドが通りません"
    return ""


def mechanically_fixable(new_warns):
    """増えた警告が、機械で分けられる長さの警告（長文・長い段落）だけか。

    書き直しで1文・1段落が伸びただけで、正しい書き直しまで戻していた。分け方は
    split_sentences / split_paragraphs が意味の壊れない形に限って決めているので任せられる。
    名前の欄だけで判定する（明細の欄に「長文」が出る別の警告を拾わない）"""
    def fixable(w):
        name = (w.split(" | ") + [""])[1]
        return ("長文" in name and "100字超" in name) or "段落が200字以内" in name
    return bool(new_warns) and all(fixable(w) for w in new_warns)


def fix_mechanical(slug, before_warns):
    """増えた警告が長さだけなら、その1本だけを分けて True を返す（他の記事は触らない）"""
    new = [w for w in warns(slug) if w not in before_warns]
    if not mechanically_fixable(new):
        return False
    sh([sys.executable, "scripts/split_sentences.py", "--only", slug, "--write"], timeout=300)
    sh([sys.executable, "scripts/split_paragraphs.py", slug, "--write"], timeout=300)
    return True


def site_of(slug):
    import sites as S
    t = (ROOT / "articles" / f"{slug}.md").read_text(encoding="utf-8-sig")
    cat = (re.search(r"^category:\s*(.+)$", t, re.M) or [0, ""])[1].strip()
    return S.find_category_owner(cat) or "ai-lab"


def only_sites(items, spec):
    """spec（空白かカンマ区切りの社ID）の記事だけに絞る。空なら絞らない（全社）"""
    want = {s for s in re.split(r"[\s,]+", spec or "") if s}
    if not want:
        return items

    def owner(x):
        try:
            return x.get("site") or site_of(x["slug"])
        except OSError:
            return ""
    return [x for x in items if owner(x) in want]


def hub_rewrite_log(item, why):
    """管制塔の「リライトログ」に残す。手元の台帳（auto_fix.jsonl）だけだと、
    シートを見る人には直した記録が1件も見えなかった（4行しか無かった）"""
    m = re.search(r"(\d+(?:\.\d+)?)位", item.get("why", ""))
    # rank_up --effect が前後を比べる台帳にも残す。ここに無いと後順位が永遠に空欄のまま。
    # 手元の台帳なので管制塔の有無に関係なく残す（管制塔が無い回に記録ごと消えていた）
    if m:
        try:
            import rank_up
            log = rank_up.load_log()
            log[item["slug"]] = {"at": time.strftime("%Y-%m-%d"), "pos": float(m.group(1)),
                                 "site": item.get("site", ""), "by": "auto_rewrite"}
            rank_up.save_log(log)
        except Exception as e:
            print(f"     （順位の台帳への記録をスキップ: {str(e)[:60]}）")
    try:
        import hub_client
        if not hub_client.enabled():
            return
        hub_client.rewrite_log(item.get("site", ""), item["slug"],
                               reason=f"{item['kind']}: {item.get('why', '')[:60]}",
                               summary=why[:80], pos_before=(m.group(1) if m else ""))
    except Exception as e:
        print(f"     （管制塔への記録をスキップ: {str(e)[:60]}）")


LAST = {}      # slug → 直す前後のタイトル・説明文（rewrite_rollback が戻すのに使う）


def _desc_of(text):
    m = re.search(r"^description:\s*(.+)$", text, re.M)
    return m.group(1).strip().strip('"') if m else ""


TITLE_LOCK_DAYS = 28   # rewrite_rollback.DAYS と同じ。この間に題を変えると効いたか判定できない


def title_changes(log=None):
    """台帳から「タイトルを実際に変えた」記録を (slug, 日付) で返す"""
    out = []
    f = Path(log) if log else LOG
    for line in CP.read_lines(f):            # お客様の記事の行（置き場）も合わせる。見ないと判定期間中に題を変える
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not (d.get("ok") and d.get("before_title")):
            continue
        after = d.get("after_title")
        changed = (after != d["before_title"]) if after is not None \
            else (d.get("kind") == "title" and str(d.get("note", "")).startswith("直しました"))
        if changed:
            out.append((d.get("slug", ""), str(d.get("at", ""))[:10]))
    return out


def title_locked(slug, today=None, log=None):
    """判定期間中なら、その題を変えた日を返す（空なら変えてよい）。

    09-25 に auto_rewrite が変えた seikyusho-shougou-jidoka の題を 09-27 に手で変え直し、
    rewrite_rollback が効いたかを判定できなくなった（取り消して戻した）"""
    from datetime import date, timedelta
    today = today or date.today()
    since = str(today - timedelta(days=TITLE_LOCK_DAYS))
    hits = [at for s, at in title_changes(log) if s == slug and at >= since]
    return max(hits) if hits else ""


TAG = ""      # --tag。集中モード（focus-mode.yml）の直しを対照群と分けて測るための印。既定は付けない


def note(slug, kind, ok, why):
    rec = {"at": time.strftime("%Y-%m-%d %H:%M"),
           "by": "auto_rewrite", "slug": slug, "kind": kind,
           "ok": ok, "note": why, **LAST.pop(slug, {})}
    if TAG:
        rec["tag"] = TAG
    CP.append_jsonl(LOG, rec)               # お客様の記事の行（題・説明文・順位）は置き場へ


def recently_touched(days, log=None, today=None):
    """直近 days 日に auto_rewrite が手を付けた記事（直した・検算で戻した）。

    集中モードは週次の上に乗るので、週次（月曜）が直した記事を水曜にまた直すと、
    どちらが効いたか測れず、28日の判定（rewrite_rollback）も混ざる。戻した記事も外すのは、
    同じ理由でまた戻る書き直しに時間を使わないため"""
    from datetime import date, timedelta
    if days <= 0:
        return set()
    f = Path(log) if log else LOG
    since = str((today or date.today()) - timedelta(days=days))
    out = set()
    for line in CP.read_lines(f):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("by") == "auto_rewrite" and str(d.get("at", ""))[:10] >= since:
            out.add(d.get("slug", ""))
    return out


def build_prompt(item):
    """書き直しの指示と、増えてよい数字（allowed）。記事の今の状態には依存しない（並列で先に作れる）"""
    slug, kind = item["slug"], item["kind"]
    allowed = ""
    what = WHAT[kind]
    if kind == "aio":
        import facts as F
        _, fs = F.load_for(item.get("site") or site_of(slug))
        allowed = "\n".join(f"- {f.get('claim', '')}" for f in fs if f.get("claim"))
        what = what.format(facts=allowed or "（登録された一次情報がありません。数字は足さないでください）")
    if kind == "quality":
        import facts as F
        _, fs = F.load_for(item.get("site") or site_of(slug))
        # 記事ごとの調査（subsidy_survey など）は呼び出し側が extra_facts で渡す
        fs = list(fs) + list(item.get("extra_facts") or [])
        allowed = "\n".join(f"- {f.get('claim', '')}" for f in fs if f.get("claim"))
        what = what.format(weak=item.get("why", "")[:1500],
                           facts=allowed or "（登録された一次情報がありません。数字は足さないでください）")
    if kind == "aisplit":
        allowed = "\n".join(item["claims"])
        what = what.format(claims="\n".join(f"「{c}」" for c in item["claims"][:1]))
    if kind == "split":
        what = what.format(other_title=item["other_title"], other_url=item["other_url"],
                           shared="」「".join(item["shared"][:3]))
    if kind == "desc":
        what = what.format(queries="\n".join(f"- {q}" for q in item.get("queries") or []))
    if kind == "title":
        # 自社のGSCで実測した「効いた型」を渡す（通説ではなく、このサイトの数字で決める）
        try:
            import title_patterns as TPn
            b = TPn.brief()
            if b:
                what += "\n実測（自社GSC・1〜20位）で分かっているタイトルの型:\n" + b
        except Exception:
            pass
    if kind == "stuck":
        # 上位・引用元の記事が扱っていて、この記事に無い語（cooccur が週次で書く。お客様の社は private の置き場）
        import client_private as CP
        cp = CP.find_file(f"data/cooccur/{slug}.json")
        if cp.is_file():
            try:
                miss = json.loads(cp.read_text(encoding="utf-8")).get("missing") or []
                if miss:
                    what += ("\n上位・引用元の記事の見出しにあって、この記事に無い語（扱う価値があるか判断して、"
                             "主題に含まれるものだけ節を足す）:\n" + "／".join(miss[:10]))
            except Exception:
                pass
    if kind == "compete":
        gap = item["gap"]
        names = {"questions": "競合が答えていて、この記事が扱っていない問い", "table": "表",
                 "fresh": "更新日", "primary": "自社で集計した数字（一次データ）", "length": "文字数（参考。長さは成果を分けない）"}
        lines = []
        for dd in gap.get("diffs") or []:
            det = dd.get("detail")
            det = "／".join(det) if isinstance(det, list) else str(det)
            lines.append(f"- {names.get(dd['type'], dd['type'])}: {det}")
        allowed = "\n".join(f"- {c}" for c in gap.get("facts") or [])
        what = what.format(kw=gap.get("kw", ""), diffs="\n".join(lines),
                           facts=allowed or "（登録された一次情報がありません。数字は足さないでください）")
    if kind == "early":
        locked = title_locked(slug)
        rule = ("変えない（{0} に変えた題の判定期間中）".format(locked) if locked else
                "狙う語（keyword）を残したまま、その語が自然に入るなら最小限の言い換えで入れる。"
                "入らなければ変えない。全面的に書き換えない。15〜45字")
        what = what.format(age=item.get("age", ""), query=item["query"], pos=f"{item['pos']:.1f}",
                           imp=item["imp"], title_rule=rule)
    if kind == "fresh":
        # 年月の更新だけを許す。今日の年・月・日のトークンは「増えた数字」に数えない
        t = time.localtime()
        ym = f"{t.tm_year}年{t.tm_mon}月"
        what = what.format(ym=ym)
        allowed = f"{t.tm_year} {t.tm_mon} {t.tm_mon:02d} {t.tm_mday:02d} {t.tm_mday}"
    prompt = PROMPT.format(slug=slug, why=item["why"], what=what)
    return prompt, allowed


def draft_quota(n, workers, budget_min, per_min):
    """先に下書きさせる本数。下書きは予算の計測より前に走るので、全件を書かせると
    当てる段階で予算が尽きて0本で終わる。予算に収まる回数（最低1回・最大2回）分だけ書かせる"""
    if not budget_min:
        return n
    rounds = max(1, min(2, budget_min // per_min))
    return min(n, max(1, workers) * rounds)


def map_each(fn, items, workers):
    """1本ずつ例外を受け止めて並列に回す。ex.map をそのまま list にすると、
    1本の TimeoutExpired で他の本の結果まで全部失う"""
    from concurrent.futures import ThreadPoolExecutor

    def safe(x):
        try:
            return fn(x)
        except Exception as e:  # noqa: BLE001  1本の失敗で他の下書きを捨てない
            print(f"  下書きに失敗: {type(e).__name__} {str(e)[:60]}", file=sys.stderr)
            return None
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(safe, items))


def draft_all(items, workers):
    """各記事の書き直し案を、記事のコピー（一時フォルダ）で同時に書かせる。

    1本の書き直しのほぼ全部は AI の応答待ち。指示は「この1ファイルだけを直す」なので、コピーの上で
    書かせても中身は同じになる。当てて検算するのは呼び出し側（run_one(edited=…)）で1本ずつ行う"""
    import tempfile
    exe = claude_bin()

    def one(item):
        src = ROOT / "articles" / f"{item['slug']}.md"
        if not src.is_file():
            return None
        prompt, _ = build_prompt(item)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            dst = Path(tmp) / "articles" / src.name
            dst.parent.mkdir(parents=True)
            dst.write_bytes(src.read_bytes())
            sh([exe, "-p", "--max-turns", "40", *model_args(), "--allowedTools", "Read,Edit",
                "--settings", PERM], timeout=1800, stdin_text=prompt, cwd=tmp)
            return dst.read_text(encoding="utf-8-sig")
    return map_each(one, items, workers)


def run_one(item, write, edited=None):
    slug, kind = item["slug"], item["kind"]
    p = ROOT / "articles" / f"{slug}.md"
    if not p.is_file():
        return False, "記事がありません"
    if write:
        import shutil
        if not (shutil.which("claude") or shutil.which("claude.cmd")):
            return False, "claude が見つかりません（npm install -g @anthropic-ai/claude-code）"
    if not write:
        return True, "（確認のみ）"
    if kind == "title" and title_locked(slug):
        return False, f"{title_locked(slug)} に変えたタイトルの判定期間中のため見送ります"

    # 戻すときは HEAD ではなくこの時点の中身へ。同じ週次で先に当てた未コミットの直しを消さない
    raw = p.read_bytes()
    before, before_warns, snap = meta(slug), warns(slug), snapshot()
    prompt, allowed = build_prompt(item)
    # 権限を全部飛ばすのではなく、使える道具を読み書きだけに絞る。
    # この工程がやるのは1ファイルの書き換えだけで、コマンド実行も外部通信も要らない
    if edited is not None:
        # 並列で先に書かせた案（draft_all）。当てた後の検算は1本ずつのときと同じ
        if edited != before[2]:
            p.write_text(edited, encoding="utf-8", newline="")
        r = subprocess.CompletedProcess([], 0, "", "")
    else:
        exe = claude_bin()
        # --permission-mode acceptEdits が無いと、Edit は「承認待ち」で止まり、
        # 何も書き換わらないまま「変更なし」で終わる。実際 16本連続で空振りし、
        # 手で1本動かして初めて「権限の許可が必要です」と出ているのが分かった。
        # 道具は Read,Edit に絞ったままなので、できるのは1ファイルの書き換えだけ。
        # 悪い書き換えは check() が見つけて直前の中身へ戻す
        # プロンプトは stdin で渡す（引数だと1行目しか届かない）
        r = sh([exe, "-p", "--max-turns", "40",
                *model_args(),
                "--allowedTools", "Read,Edit",
                "--settings", PERM], timeout=1800, stdin_text=prompt)
    if r.returncode and not p.read_text(encoding="utf-8-sig") != before[2]:
        return False, f"claude が動きませんでした（{(r.stderr or '')[:60]}）"

    if p.read_text(encoding="utf-8-sig") == before[2]:
        return True, "変更なし（直す必要なしと判断）"

    if kind == "fresh":
        # 鮮度を更新した記事は dateModified も動かす（検算の前に書き、ビルドまで通す）
        t = p.read_text(encoding="utf-8-sig")
        today = time.strftime("%Y-%m-%d")
        t2 = re.sub(r"^modified:.*$", f"modified: {today}", t, count=1, flags=re.M) if re.search(r"^modified:", t, re.M) \
            else re.sub(r"^(date:.*)$", rf"\1\nmodified: {today}", t, count=1, flags=re.M)
        if t2 != t:
            p.write_text(t2, encoding="utf-8", newline="")

    ng = check(slug, before, before_warns, snap, allowed,
               item.get("terms") or ())
    if ng.startswith("警告が増えました") and fix_mechanical(slug, before_warns):
        # 長さの警告は分ける道具が決まった形で直せる。他の検算は1つも緩めず、もう1回だけ通す
        ng = check(slug, before, before_warns, snap, allowed,
                   item.get("terms") or ())
    if not ng and kind == "aisplit":
        after_now = p.read_text(encoding="utf-8-sig")
        if item["claims"][0] not in after_now:
            ng = "調査の文がそのまま入っていません（言い換えると調査の数字と食い違う）"
        elif ext_links(after_now) - ext_links(before[2]):
            ng = "出典のURLが増えました（記事にあった出典だけで答えること）: " + str(sorted(ext_links(after_now) - ext_links(before[2]))[:2])
    if not ng and kind == "desc":
        # 説明文だけの直し。本文・タイトルが1文字でも変わっていたら通さない
        strip = lambda t: re.sub(r"^description:.*$", "", t, count=1, flags=re.M)
        after_now = p.read_text(encoding="utf-8-sig")
        d = _desc_of(after_now)
        if strip(after_now) != strip(before[2]):
            ng = "説明文以外が変わりました"
        elif not (100 <= len(d) <= 160):
            ng = f"説明文が{len(d)}字（100〜160字）"
        elif item.get("queries") and not any(w in d[:40].lower() for w in re.split(r"[\s　]+", item["queries"][0].lower()) if len(w) >= 2):
            ng = "流入語が説明文の先頭に入っていません"
        if ng:
            p.write_bytes(raw)
            sh([sys.executable, "scripts/build.py"], timeout=1800)
            return False, ng
    if not ng and kind == "question":
        # 見出しの本数と順番が変わったら通さない（質問形にする直しは言い換えだけ）
        h_before = re.findall(r"^##\s+", before[2], re.M)
        after_now = p.read_text(encoding="utf-8-sig")
        h_after = re.findall(r"^##\s+(.+)$", after_now, re.M)
        if len(h_before) != len(h_after):
            ng = f"H2の本数が変わりました（{len(h_before)}→{len(h_after)}）"
        elif not any(re.search(r"[?？]", h) for h in h_after):
            ng = "質問形の見出しが1本も入りませんでした"
        if ng:
            p.write_bytes(raw)
            sh([sys.executable, "scripts/build.py"], timeout=1800)
            return False, ng
    if not ng and kind == "split":
        # 共通の語がまだタイトルの前半にそろって残っていれば、付け分けになっていない
        t_now = meta(slug)[0]
        toks = [w for w in re.split(r"[\s　]+", item["shared"][0].lower()) if w]
        if toks and all(w in t_now[:max(len(t_now) // 2, 1)].lower() for w in toks):
            ng = f"共通の語「{item['shared'][0]}」がタイトルの前半に残っています"
    if not ng and kind == "compete":
        ng = compete_guard(before[2], p.read_text(encoding="utf-8-sig"), before[0], meta(slug)[0], item["gap"])
    if not ng and kind == "early":
        ng = early_guard(before[2], p.read_text(encoding="utf-8-sig"), before[0], meta(slug)[0], item)
    if not ng and meta(slug)[0] != before[0]:
        lk = title_locked(slug)
        if lk:
            ng = f"{lk} に変えたタイトルの判定期間（{TITLE_LOCK_DAYS}日）中です"
    after_text = p.read_text(encoding="utf-8-sig")
    LAST[slug] = {"before_title": before[0], "before_description": _desc_of(before[2]),
                  "after_title": meta(slug)[0], "after_description": _desc_of(after_text)}
    if ng:
        p.write_bytes(raw)
        sh([sys.executable, "scripts/build.py"], timeout=1800)
        return False, ng
    if kind in ("compete", "early"):
        LAST[slug].update(keep_before(slug, raw, p.read_bytes()))
    if kind == "early":
        LAST[slug].update({"query": item["query"], "pos_before": item["pos"], "imp_before": item["imp"]})
    return True, f"直しました（{before[0][:24]}… → {meta(slug)[0][:24]}…）"


def selftest():
    """検算が本当に効くかを、本番の記事で確かめる。

    claude を呼ばずに、こちらで「やってはいけない書き換え」を当てて、
    検算が止めるかを見る。止まらなければ、その穴から壊れた記事が通る。
    最後は必ず元のバイト列に戻す。
    """
    import auto_improve  # 対象の取り方まで含めて試す
    wrong = false_alarms()
    for name in wrong:
        print(f"  NG  通すべき書き換えを差し戻します: {name}")
    if wrong:
        return 1
    items = targets()
    if not items:
        print("  対象がないため、記事を1本選んで試します")
        items = [{"kind": "title", "slug": sorted(
            p.stem for p in (ROOT / "articles").glob("*.md"))[0], "why": "自己診断"}]
    # 手を付ける前から検算に落ちる記事を選ぶと、何を当てても同じ理由で止まり、
    # 「6/6を止めた」と出ても何も試していないことになる。実際 ai-kantan-shukyaku は
    # タイトルに狙う語が無いため、5件が同じ理由で止まっていた（2026-09-23）
    slug = ""
    # git status と比べると、先に走った工程の未コミットの記事で全件が落ちる
    snap0 = snapshot()
    for it in items[:8]:
        s = it["slug"]
        if not (ROOT / "articles" / f"{s}.md").is_file():
            continue
        if not check(s, meta(s), warns(s), snap0):
            slug = s
            break
        print(f"  --  {s}: 直す前から検算に落ちるため、診断には使いません")
    if not slug:
        print("  NG  検算を試せる記事がありません（全件が手つかずで落ちます）")
        return 1
    p = ROOT / "articles" / f"{slug}.md"
    # BOM・改行コードまでそのまま戻す（読み直した文字列で書くと差分が残る）
    orig = p.read_bytes()
    before, before_warns, snap = meta(slug), warns(slug), snapshot()
    title, kw, body = before
    print(f"  診断に使う記事: {slug}" + chr(10))

    # やってはいけない書き換えを、1つずつ当てる
    cases = [
        ("無かった数字を書く", body.replace("。", "。前年比12.7%増です。", 1)),
        ("出典リンクを消す",
         re.sub(r'<a href="https?://[^"]+"[^>]*>(.*?)</a>', r"\1", body, count=1)),
        ("狙う語を変える", body.replace(f"keyword: {kw}", "keyword: 別の語", 1)),
        ("タイトルを短くしすぎる",
         body.replace(f"title: {title}", "title: 短い", 1)),
    ]
    # stuck 種別の検算は terms を渡したときだけ効く。別に試す
    stuck_cases = [
        ("語を本文にちりばめるだけ（見出しに入れない）",
         body + chr(10) + "この記事は接骨院にも当てはまります。" + chr(10), ("接骨院",)),
        ("見出しに入れたが本文を削る",
         body[:len(body) // 2] + chr(10) + "## 接骨院の場合" + chr(10), ("接骨院",)),
    ]
    ok = 0
    try:
        for name, broken, terms in stuck_cases:
            p.write_text(broken, encoding="utf-8", newline="")
            ng = check(slug, before, before_warns, snap, "", terms)
            print(f"  {'OK' if ng else 'NG'}  {name}: "
                  + (f"止めた（{ng[:44]}）" if ng else "素通りしました"))
            ok += bool(ng)
            p.write_bytes(orig)
        for name, broken in cases:
            if broken == body:
                print(f"  --  {name}: この記事では試せません")
                continue
            p.write_text(broken, encoding="utf-8", newline="")
            ng = check(slug, before, before_warns, snap)
            print(f"  {'OK' if ng else 'NG'}  {name}: "
                  + (f"止めた（{ng[:44]}）" if ng else "素通りしました"))
            ok += bool(ng)
            p.write_bytes(orig)
    finally:
        p.write_bytes(orig)
        sh([sys.executable, "scripts/build.py"], timeout=1800)
    total = len(cases) + len(stuck_cases)
    print(f"\n  {ok}/{total} を止めました（記事は元に戻しました）")
    return 0 if ok == total else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--limit", type=int, default=3, help="1回に直す本数")
    ap.add_argument("--parallel", type=int, default=0, help="書き直し案を同時に書かせる本数（検算は1本ずつ）")
    # 1本あたり最大30分かかる。本数だけ増やすとCIの時間上限で途中終了し、
    # 直した分がcommitされずに捨てられる。残り時間を見て、次を始めない
    ap.add_argument("--budget-min", type=int, default=0,
                    help="この分数を超えたら、次の記事に着手しない（0=無制限）")
    ap.add_argument("--selftest", action="store_true",
                    help="検算が効くかを本番の記事で確かめる（claudeは呼ばない）")
    ap.add_argument("--kind", default="", help="種別を絞る（fresh は鮮度更新だけを回す）")
    ap.add_argument("--skip-recent", type=int, default=0,
                    help="直近この日数に auto_rewrite が手を付けた記事を外す（0=外さない。集中モードが使う）")
    ap.add_argument("--tag", default="", help="台帳に残す印（集中モードの直しを対照群と分けるため）")
    ap.add_argument("--sites", default="",
                    help="この社の記事だけを直す（空白かカンマ区切り。空=全社。集中モードが focus_report --sites を渡す）")
    a = ap.parse_args()
    global TAG
    TAG = a.tag

    if a.selftest:
        print("■ 検算の自己診断（やってはいけない書き換えを当てて、止まるか見る）\n")
        return selftest()

    if a.kind == "fresh":
        items = fresh_items(max(a.limit, 4))
    elif a.kind == "question":
        items = question_items(max(a.limit, 4))
    elif a.kind == "desc":
        items = desc_items(max(a.limit, 4))
    elif a.kind == "aisplit":
        items = aisplit_items(max(a.limit, 2))
    elif a.kind == "split":
        items = split_items(max(a.limit, 4))
    elif a.kind == "compete":
        items = compete_items(max(a.limit, 2))
    elif a.kind == "early":
        items = early_items(max(a.limit, 2))
    else:
        items = [x for x in targets() if not a.kind or x["kind"] == a.kind]
    items = only_sites(items, a.sites)
    if a.skip_recent:
        busy = recently_touched(a.skip_recent)
        # 判定期間中の題は run_one が必ず見送る。先に外さないと、本数の枠と下書きの時間をそれに使う
        busy |= {x["slug"] for x in items if x["kind"] == "title" and title_locked(x["slug"])}
        held = [x["slug"] for x in items if x["slug"] in busy]
        items = [x for x in items if x["slug"] not in busy]
        if held:
            print(f"  直近{a.skip_recent}日に手を付けた・題の判定期間中の{len(held)}本を外しました: {', '.join(held[:6])}")
    print(f"■ 人の判断に回っていた直し: {len(items)}件"
          + (f"（1回に{a.limit}本まで）\n" if a.write else "\n"))
    if not items:
        print("  対象がありません")
        return 0
    if not a.write:
        for x in items[:12]:
            print(f"  [{x['kind']}] {x['slug'][:36]:<36} {x['why'][:40]}")
        print("\n  --write を付けると claude が直し、機械が検算します"
              "（通らなければ元に戻します）")
        return 0

    ok = ng = 0
    started = time.time()
    todo = items[:a.limit]
    drafts = [None] * len(todo)
    if a.parallel > 1:
        k = draft_quota(len(todo), a.parallel, a.budget_min, per_min=30)
        drafts[:k] = draft_all(todo[:k], a.parallel)
    for x, edited in zip(todo, drafts):
        used = (time.time() - started) / 60
        # 書き終えた下書きは AI を待たずに当てられるので、予算を過ぎても捨てない
        if a.budget_min and used >= a.budget_min and edited is None:
            print(f"\n  {used:.0f}分使ったので、ここで止めます"
                  f"（残りは次回。上限{a.budget_min}分）")
            break
        good, why = run_one(x, True, edited=edited) if edited is not None else run_one(x, True)
        print(f"  {'○' if good else '×'} [{x['kind']}] {x['slug'][:34]:<34} {why[:56]}")
        note(x["slug"], x["kind"], good, why)
        if good and why.startswith("直しました"):
            hub_rewrite_log(x, why)
        ok, ng = ok + good, ng + (not good)
    print(f"\n  直した {ok}件 / 戻した {ng}件 / {(time.time() - started) / 60:.0f}分")
    print("  台帳: automation/logs/auto_fix.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
