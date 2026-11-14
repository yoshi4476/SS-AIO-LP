# -*- coding: utf-8 -*-
"""主要クエリを宣言し、順位を毎週追い、上がっていない語に手を割り当てる。

**なぜ要るか**: 既存の `rank_up` と `rank_rescue` はページ単位で動く。
「この案件の主要クエリはこれ」という宣言がどこにも無いため、
何を上げたかったのかが記録に残らず、上がったかどうかも後から言えない。
実際、AIO運用の成果を「主要クエリの平均順位が開始時より上がったか」で
数えたが、その主要クエリの一覧はこのリポジトリのどこにも無かった。

**圏外の扱い（ここで固定する）**: GSCは表示が発生した語しか返さない。
返ってこない語は「検索結果に出ていない」とみなし、**101位として扱う**。
「出ていない」と「出ているがGSCが返さない」は区別できないため、
順位が付いた時点を「上がった」と数える。この定義を公開するデータにも書く。

    python scripts/key_queries.py --init --site ai-lab   # 主要クエリを作る
    python scripts/key_queries.py --track                # 週次。順位を記録する
    python scripts/key_queries.py                        # いまの状況を見る
    python scripts/key_queries.py --ledger --site ai-lab [--write]  # 1位を狙う語の台帳（業種×サービスの組）を作る
    python scripts/key_queries.py --line                 # 週次の findings に添える台帳の行（情報）

**1位を狙う語の台帳**: sites/<id>.json に key_queries（max・industry_terms・services・buyer_words）がある社だけ、
主要クエリを「優先業種（kw_seeds.priority）×サービス」の組ごとの買い手の語に置き換える（1組3〜5語）。
語の候補は管制塔の台帳・GSC の順位の記録（data/ranks/<id>.json）・記事の狙う語・kw_seeds の組み合わせ。
検索の量は data/rakko_volume.json の控えだけを使う（ラッコは新しく呼ばない）。控えに無ければ GSC の表示で代える。

終了コードは常に0（CLAUDE.md 8.7）。判定は KEYQ_OK= の印で行う。
"""
import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

REG = ROOT / "data" / "key_queries.json"
HIST = ROOT / "data" / "key_query_history.jsonl"
SITES = ROOT / "sites"
ARTICLES = ROOT / "articles"

OUT = 101.0          # 検索結果に出ていない語の扱い。定義を1か所に固定する
MIN_IMP = 3          # これ未満の表示は順位が安定しないので主要クエリにしない
DEFAULT_N = 30       # 1サイトの主要クエリ数の上限（sites/<id>.json の key_queries.max で変える）
CANN_MAX_POS = 30.0  # 食い合いとみなす上限順位（rank_rescue と同じ）
CANN_MAX_GAP = 15.0  # 2ページの順位差がこれを超えれば偶然とみなす


def sites():
    import sites as S               # お客様の社は非公開の置き場の戦略の部分を重ねたもの
    return {sid: cfg for sid, cfg in S.load_all().items()}


def load():
    import client_private as CP
    return CP.load_dict("data/key_queries.json", pub=REG)


def save(d):
    # お客様の社の狙う語と順位は public に置かない（client_private の置き場へ。読むときは load が合わせる）
    import client_private as CP
    CP.save_dict("data/key_queries.json", d, CP.site_key,
                 dump=lambda o: json.dumps(o, ensure_ascii=False, indent=2), pub=REG)


def norm(s):
    """表記ゆれを吸収する。ハイフン・長音・空白の違いで別語にしない"""
    return re.sub(r"[\s\-‐-―ー_]+", "", str(s)).lower()


def fetch(domain, days=28, dims=("query",)):
    """GSCから取る。**順位はquery次元でしか取れない**ので、ここでは合計を出さない。

    query次元は検索数の少ない語を落とす。合計を出すとその分だけ小さく出るため、
    このファイルでは合計を一切計算しない（CLAUDE.md 0.1 のGSCの落とし穴）。
    """
    import gsc_detail as G
    sc = G.client()
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days - 1)
    # 取得失敗を [] で返すと、全語が圏外として起点や履歴に残る。呼び出し側で飛ばす
    rows = G.q(sc, domain, start.isoformat(), end.isoformat(), dims=list(dims), limit=5000,
               raise_errors=True)
    return [G.row(r) for r in rows]


def limit_of(cfg):
    """その社の主要クエリの上限。1位を狙う語を組ごとに持つ社（AI集客ラボ）は30語では組が埋まらない"""
    try:
        return int((cfg.get("key_queries") or {}).get("max") or DEFAULT_N)
    except (TypeError, ValueError):
        return DEFAULT_N


def owns_of(cfg):
    got = cfg.get("owns") or []
    seeds = cfg.get("kw_seeds") or {}
    return [norm(x) for x in list(got) + list(seeds.get("core") or [])]


def keywords_of_site(site_id, cfg):
    """記事の keyword: を集める。どのサイトの記事かは category: で決まる（site: は無い）"""
    cats = set(cfg.get("categories") or {})
    out = {}
    for p in ARTICLES.glob("*.md"):
        head = p.read_text(encoding="utf-8", errors="replace")[:1200]
        m = re.search(r"^keyword:\s*(.+)$", head, re.M)
        c = re.search(r"^category:\s*(.+)$", head, re.M)
        if not (m and c) or c.group(1).strip() not in cats:
            continue
        out[norm(m.group(1).strip())] = (m.group(1).strip(), p.stem)
    return out


def init(site_id, cfg, limit=None):
    """主要クエリを作る。宣言した語（keyword:）と、実際に表示が出ている語の両方から取る"""
    limit = limit or limit_of(cfg)
    declared = keywords_of_site(site_id, cfg)
    try:
        rows = fetch(cfg["domain"])
    except Exception as e:
        print(f"  {site_id}: GSCから取得できないため登録しません: {str(e)[:60]}")
        return
    seen, picked = set(), []
    by_q = {norm(r["k"][0]): r for r in rows}

    # 表示の出ている語を先に置く。アルファベット順で切ると、
    # 実測できる語が落ちて圏外の語だけが残る（実際にそうなった）
    def rank(kv):
        r = by_q.get(kv[0])
        return (0, -r["imp"], r["pos"]) if r else (1, 0, 0)

    for nq, (raw, slug) in sorted(declared.items(), key=rank):
        r = by_q.get(nq)
        pos = round(r["pos"], 1) if r else OUT
        picked.append({"q": raw, "base": pos, "base_at": date.today().isoformat(),
                       "from": "宣言", "slug": slug})
        seen.add(nq)

    owns = owns_of(cfg)
    for r in sorted(rows, key=lambda x: -x["imp"]):
        nq = norm(r["k"][0])
        if nq in seen or r["imp"] < MIN_IMP:
            continue
        if owns and not any(o in nq for o in owns):
            continue
        picked.append({"q": r["k"][0], "base": round(r["pos"], 1),
                       "base_at": date.today().isoformat(), "from": "実績", "slug": ""})
        seen.add(nq)
        if len(picked) >= limit:
            break

    d = load()
    d[site_id] = {"since": date.today().isoformat(), "queries": picked[:limit]}
    save(d)
    print(f"  {site_id}: 主要クエリ {len(d[site_id]['queries'])}語を登録しました "
          f"（宣言 {sum(1 for x in picked[:limit] if x['from'] == '宣言')}語 / "
          f"実績 {sum(1 for x in picked[:limit] if x['from'] == '実績')}語）")
    return d[site_id]


# ---- 1位を狙う語の台帳（業種×サービスの組） ------------------------------------------------
BANDS = (("1〜3位", 3), ("4〜10位", 10), ("11〜30位", 30), ("圏外", None))
# GSC には AI に聞くような文の問いも語として出る（「〜に強い会社を教えてください」）。1位を狙う検索の語ではない
SENTENCE = re.compile(r"教えて|ください|探して|頼みたい|ですか|[?？]|は$")
SENTENCE_LEN = 24   # 空白を除いた字数。これを超える語は文の問い


def ledger_conf(cfg):
    """組の設定。key_queries.services の無い社は台帳を作らない（None）"""
    kq = cfg.get("key_queries") or {}
    if not kq.get("services"):
        return None
    terms = kq.get("industry_terms") or {}
    inds = [(i, [str(w).lower() for w in terms.get(i) or [i]])
            for i in (cfg.get("kw_seeds") or {}).get("priority") or []]
    svcs = [(s, [str(w).lower() for w in v.get("terms") or [s]], v.get("seed") or s)
            for s, v in kq["services"].items()]
    lo, hi = (list(kq.get("per_group") or [3, 5]) + [5])[:2]
    return {"industries": inds, "services": svcs, "buyer": list(kq.get("buyer_words") or []),
            "per_group": (int(lo), int(hi)), "max": limit_of(cfg)}


def group_of(text, conf):
    """(業種, サービス)。どちらかが無ければ None。設定の順に見る（先に書いた方を優先）"""
    low = str(text).lower()
    ind = next((i for i, ws in conf["industries"] if any(w in low for w in ws)), None)
    svc = next((s for s, ws, _seed in conf["services"] if any(w in low for w in ws)), None)
    return (ind, svc) if ind and svc else None


def build_ledger(cfg, declared, hub_kws, ranks, vols, prev=(), today="", slugs=None):
    """台帳の行。declared は {norm: (語, slug)}（記事の狙う語）、ranks は {norm: {q, imp, pos, url}}（GSC の28日）、
    vols は {norm: 検索の量}（ラッコの控え）、prev は前の主要クエリ（起点を引き継ぐ）、slugs はその社の記事の slug"""
    import kw_intent
    conf = ledger_conf(cfg)
    if not conf:
        return []
    today = today or date.today().isoformat()
    lo, hi = conf["per_group"]
    groups = {(i, s): [] for i, _w in conf["industries"] for s, _t, _seed in conf["services"]}
    seen = set()
    for q in list(hub_kws) + [r["q"] for r in ranks.values()] + [raw for raw, _s in declared.values()]:
        g, nq = group_of(q, conf), norm(q)
        if g in groups and nq not in seen and kw_intent.is_buyer(q) \
                and len(nq) <= SENTENCE_LEN and not SENTENCE.search(str(q).strip()):
            seen.add(nq)
            groups[g].append(q)
    for g, qs in groups.items():
        # 量の分かる語を先に（ラッコの量 → GSC の表示）。並びを固定し、毎週の作り直しで語が入れ替わらないようにする
        qs.sort(key=lambda q: (-(vols.get(norm(q)) or 0), -(ranks.get(norm(q), {}).get("imp") or 0), norm(q)))
        seed = next(sd for s, _t, sd in conf["services"] if s == g[1])
        for b in conf["buyer"]:
            q = f"{g[0]} {seed} {b}"
            if norm(q) not in {norm(x) for x in qs} and kw_intent.is_buyer(q):
                qs.append(q)
        del qs[hi:]
    # 各組の1語目、2語目…の順に配る。上限で切っても、どの組も lo 語までは必ず残る
    picked = []
    for k in range(hi):
        for g, qs in groups.items():
            if k < len(qs) and (k < lo or len(picked) < conf["max"]):
                picked.append((g, qs[k], k))
    picked.sort(key=lambda x: (list(groups).index(x[0]), x[2]))
    old = {norm(x["q"]): x for x in prev}
    out = []
    for (ind, svc), q, _k in picked[:max(conf["max"], lo * len(groups))]:
        nq = norm(q)
        r = ranks.get(nq) or {}
        vol = vols.get(nq)
        vol, src = (vol, "rakko") if vol is not None else (r["imp"], "gsc") if r.get("imp") else (None, "なし")
        slug, how = "", ""
        if nq in declared:
            slug, how = declared[nq][1], "keyword"
        elif r.get("url"):
            s = r["url"].rstrip("/").rsplit("/", 1)[-1]
            if slugs is None or s in slugs:
                slug, how = s, "gsc"
        pos = round(r["pos"], 1) if r.get("pos") else OUT
        o = old.get(nq) or {}
        out.append({"q": q, "ind": ind, "svc": svc, "vol": vol, "vol_src": src, "slug": slug, "slug_src": how,
                    "pos": pos, "base": o.get("base", pos), "base_at": o.get("base_at", today), "from": "台帳"})
    return out


def ranks_of(site_id, days=28):
    """GSC の順位の記録（rank_track の data/ranks/<id>.json）の直近 days 日を、語ごとに表示・加重順位・着地ページへ"""
    import client_private as CP
    try:
        hist = json.loads(CP.find_file(f"data/ranks/{site_id}.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  記録が無ければ GSC の候補なしで作る
        return {}
    days_ = sorted(hist)[-days:]
    acc = {}
    for d in days_:
        for r in hist[d] or []:
            nq = norm(r.get("kw", ""))
            imp = int(r.get("imp") or 0)
            if not nq or not imp:
                continue
            a = acc.setdefault(nq, {"q": r["kw"], "imp": 0, "ps": 0.0, "urls": {}})
            a["imp"] += imp
            a["ps"] += float(r.get("pos") or 0) * imp
            a["urls"][r.get("url", "")] = a["urls"].get(r.get("url", ""), 0) + imp
    return {k: {"q": a["q"], "imp": a["imp"], "pos": a["ps"] / a["imp"],
                "url": max(a["urls"], key=a["urls"].get)} for k, a in acc.items()}


def volumes():
    """ラッコの検索の量の控え（kw_plan が予算の中で取ったもの）。CI のキャッシュに無ければ空"""
    try:
        raw = json.loads((ROOT / "data" / "rakko_volume.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  手元・キャッシュの無い回は GSC の表示で代える
        return {}
    return {norm(k): v["vol"] for k, v in raw.items() if isinstance(v, dict) and v.get("vol") is not None}


def hub_words(site_id):
    import hub_client
    return [str(r.get("keyword")) for r in hub_client.all_kw() if r.get("site") == site_id and r.get("keyword")]


def ledger(site_id, cfg, write=False):
    import sites as S
    blk = load().get(site_id) or {}
    declared = keywords_of_site(site_id, cfg)
    slugs = {s for _r, s in declared.values()} | {p.stem for p in ARTICLES.glob("*.md")}
    rows = build_ledger(cfg, declared, hub_words(site_id), ranks_of(site_id), volumes(),
                        prev=blk.get("queries") or [], slugs=slugs)
    if not rows:
        return None
    groups = {(r["ind"], r["svc"]) for r in rows}
    empty = groups - {(r["ind"], r["svc"]) for r in rows if r["slug"]}
    src = {k: sum(1 for r in rows if r["vol_src"] == k) for k in ("rakko", "gsc", "なし")}
    name = "お客様の社" if S.is_client(site_id) else site_id
    print(f"  {name}: 台帳 {len(rows)}語・{len(groups)}組（担う記事が無い組 {len(empty)}組）"
          f"・検索の量 rakko {src['rakko']}語／gsc {src['gsc']}語／なし {src['なし']}語")
    if write:
        d = load()
        d[site_id] = {"since": blk.get("since") or date.today().isoformat(), "queries": rows}
        save(d)
    return rows


def band(pos):
    p = int(float(pos) + 0.5)
    return next(name for name, top in BANDS if top is None or p <= top)


def ledger_lines(site_id, rows, hist, client=False):
    """週次の findings に添える行（どれも「情報:」で始める）。hist は key_query_history の行"""
    mine = [h for h in hist if h.get("site") == site_id]
    ats = sorted({h["at"] for h in mine})
    by_at = lambda at: {norm(h["q"]): h["pos"] for h in mine if h["at"] == at}
    now = by_at(ats[-1]) if ats else {}
    last = by_at(ats[-2]) if len(ats) >= 2 else {}
    qs = [norm(r["q"]) for r in rows]
    cur = {q: now.get(q, r.get("pos", OUT)) for q, r in zip(qs, rows)}

    def dist(m):
        c = {name: 0 for name, _t in BANDS}
        for p in m.values():
            c[band(p)] += 1
        return "／".join(f"{name} {c[name]}語" for name, _t in BANDS)
    prev = {q: last[q] for q in qs if q in last}
    up = sum(1 for q, p in prev.items() if cur[q] < p - 0.5)
    down = sum(1 for q, p in prev.items() if cur[q] > p + 0.5)
    groups = list(dict.fromkeys((r["ind"], r["svc"]) for r in rows))
    empty = [g for g in groups if not any(r["slug"] for r in rows if (r["ind"], r["svc"]) == g)]
    who = "お客様の社" if client else site_id
    out = [f"情報: 1位を狙う語の台帳（{who}・{len(rows)}語・{len(groups)}組）: {dist(cur)}",
           f"情報: 台帳の先週との比較: 先週 {dist(prev)}（先週の記録が無い語 {len(qs) - len(prev)}）。"
           f"上がった {up}語・下がった {down}語",
           f"情報: 台帳で担う記事が無い組 {len(empty)}組"
           + ("" if client or not empty else "（例: " + "、".join(f"{i}×{s}" for i, s in empty[:3]) + "）")]
    return out


def line():
    import sites as S
    hist = [json.loads(x) for x in (HIST.read_text(encoding="utf-8").splitlines() if HIST.is_file() else []) if x.strip()]
    for site_id, blk in sorted(load().items()):
        rows = [r for r in blk.get("queries") or [] if r.get("ind")]
        if rows:
            for x in ledger_lines(site_id, rows, hist, client=S.is_client(site_id)):
                print(x)
    return 0


def cause(q, pos, rows_pq, titles, slug=""):
    """上がっていない語に、既存のどの工程を当てるかを決める。slug はその語に宣言した記事
    （検索結果に出ていないだけの語を「記事が無い」とすると、同じ語の記事をもう1本書かせて食い合いを作る。2026-11-12）"""
    nq = norm(q)
    pages = [r for r in rows_pq if norm(r["k"][1]) == nq]
    if not pages:
        if slug and slug in titles:
            return "表示が無い（記事はある）", "その記事に、その語に答える節を書き足す（auto_rewrite の stuck）・インデックスを確かめる"
        return "記事が無い", "その語に答える記事を書く（kw_guard を通してから）"
    # 2ページ出ているだけでは食い合いではない。順位が離れていれば、
    # 片方はたまたま出ているだけ。rank_rescue と同じ基準（30位以内・差15以内）に揃える
    if len(pages) >= 2:
        ps = sorted(p["pos"] for p in pages)
        if ps[0] <= CANN_MAX_POS and ps[1] - ps[0] <= CANN_MAX_GAP:
            return "食い合い", "auto_merge（統合）か、負け側から勝ち側へリンク"
    slug = pages[0]["k"][0].rstrip("/").rsplit("/", 1)[-1]
    t = titles.get(slug, "")
    if t and not any(w and norm(w) in norm(t) for w in re.split(r"\s+", q)):
        return "語がタイトルに無い", "auto_rewrite（タイトルと見出しに語を入れる）"
    if pos > 30:
        return "内容が足りない", "auto_rewrite の stuck 種別（その語に答える節を足す）"
    return "抽出構造・一次データ", "冒頭の断言・H2直下の1文結論・一次データを足す"


def titles_map():
    out = {}
    for p in ARTICLES.glob("*.md"):
        m = re.search(r"^title:\s*(.+)$", p.read_text(encoding="utf-8", errors="replace")[:1200], re.M)
        if m:
            out[p.stem] = m.group(1).strip()
    return out


def track(only=""):
    reg, allsites, titles = load(), sites(), titles_map()
    if not reg:
        print("  主要クエリが未登録です。--init --site <id> で作ってください")
        print("KEYQ_OK=yes")
        return 0
    today, stuck_all, up_all, tot = date.today().isoformat(), [], 0, 0
    failed = []
    lines = []
    # 同じ日に2回走ると履歴が二重になる。当日分を落としてから書き直す
    keep = [l for l in (HIST.read_text(encoding="utf-8").splitlines() if HIST.is_file() else [])
            if l.strip() and json.loads(l).get("at") != today]
    HIST.write_text(chr(10).join(keep) + (chr(10) if keep else ""), encoding="utf-8")
    with HIST.open("a", encoding="utf-8") as fh:
        for site_id, blk in sorted(reg.items()):
            if only and site_id != only:
                continue
            cfg = allsites.get(site_id)
            if not cfg:
                continue
            try:
                rows = fetch(cfg["domain"])
                rows_pq = fetch(cfg["domain"], dims=("page", "query"))
            except Exception as e:
                failed.append(site_id)
                lines.append(f"  {site_id}: GSCから取得できず、今回は記録しません: {str(e)[:60]}")
                continue
            by_q = {norm(r["k"][0]): r for r in rows}
            up, same, down, stuck = 0, 0, 0, []
            for item in blk["queries"]:
                r = by_q.get(norm(item["q"]))
                pos = round(r["pos"], 1) if r else OUT
                imp = r["imp"] if r else 0
                fh.write(json.dumps({"at": today, "site": site_id, "q": item["q"],
                                     "pos": pos, "imp": imp,
                                     "clicks": r["clicks"] if r else 0}, ensure_ascii=False) + "\n")
                base = item.get("base", OUT)
                if pos < base - 0.5:
                    up += 1
                elif pos > base + 0.5:
                    down += 1
                    stuck.append((item["q"], base, pos, item.get("slug") or ""))
                else:
                    same += 1
                    stuck.append((item["q"], base, pos, item.get("slug") or ""))
            n = len(blk["queries"])
            tot += n
            up_all += up
            lines.append(f"  {site_id}: {n}語中 上がった{up} / 変わらず{same} / 下がった{down}"
                         f"（起点 {blk['since']}）")
            import sites as _S
            for q, base, pos, slug in ([] if _S.is_client(site_id) else stuck[:6]):     # お客様の語と順位は CI のログに出さない
                c, how = cause(q, pos, rows_pq, titles, slug=slug)
                b = "圏外" if base >= OUT else f"{base:g}位"
                p = "圏外" if pos >= OUT else f"{pos:g}位"
                lines.append(f"      {q}（{b}→{p}） … {c} → {how}")
                stuck_all.append((site_id, q, c))
            if _S.is_client(site_id):
                stuck_all += [(site_id, q, "") for q, _b, _p, _s in stuck]
    print("■ 主要クエリの推移")
    for l in lines:
        print(l)
    if tot:
        print(f"  合計 {tot}語中 {up_all}語が起点より上がりました（{up_all / tot * 100:.1f}%）")
    print(f"KEYQ_OK={'no' if stuck_all else ('unknown' if failed else 'yes')}")
    if stuck_all:
        print(f"  上がっていない語 {len(stuck_all)}件に、上の工程を当ててください")
    # 取れなかったサイトがあるのに0で終えると、「全部見た」と読まれる（CLAUDE.md 8.7）
    return 1 if failed else 0


def show():
    reg = load()
    if not reg:
        print("  主要クエリが未登録です。--init --site <id> で作ってください")
        return 0
    for site_id, blk in sorted(reg.items()):
        print(f"■ {site_id}（起点 {blk['since']}・{len(blk['queries'])}語）")
        for x in blk["queries"][:12]:
            b = "圏外" if x["base"] >= OUT else f"{x['base']:g}位"
            print(f"     {x['q']}  起点 {b}  [{x['from']}]")
        if len(blk["queries"]) > 12:
            print(f"     …ほか {len(blk['queries']) - 12}語")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true", help="主要クエリを作る")
    ap.add_argument("--track", action="store_true", help="順位を記録する（週次）")
    ap.add_argument("--site", default="", help="サイトID")
    ap.add_argument("--limit", type=int, default=0, help="上限（0=sites/<id>.json の key_queries.max・無ければ30）")
    ap.add_argument("--ledger", action="store_true", help="1位を狙う語の台帳（業種×サービスの組）を作る")
    ap.add_argument("--write", action="store_true", help="--ledger の結果を data/key_queries.json へ書く")
    ap.add_argument("--line", action="store_true", help="週次の findings に添える台帳の行（情報）")
    a = ap.parse_args()
    if a.line:
        return line()
    if a.ledger:
        for sid, cfg in sites().items():
            if (not a.site or sid == a.site) and ledger_conf(cfg):
                ledger(sid, cfg, a.write)
        return 0
    if a.init:
        allsites = sites()
        for sid, cfg in allsites.items():
            if a.site and sid != a.site:
                continue
            init(sid, cfg, a.limit or None)
        return 0
    if a.track:
        return track(a.site)
    return show()


if __name__ == "__main__":
    sys.exit(main())
